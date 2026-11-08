"""Standalone ROI rules and media processing; no GUI or model dependencies.

Geometry and encoding are adapted from mVllm_2 pipeline/roi_media.py and
pipeline/scripts/roi_annotation_app.py (2c272ce). Records use a new schema:
legacy visibility booleans are candidates, never evidence of current review.
"""
from __future__ import annotations

import csv
import functools
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

RULE_VERSION = "roi-rules/1"
PROCESSING_VERSION = "roi-processing/2"
SCHEMA = "tensile-roi/1"
EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
EVIDENCE_ITEMS = {
    "state": "断裂状态", "mode": "断裂模式", "location": "断裂位置",
    "unclamped": "异常：未夹紧", "video_abnormal": "异常：视频异常",
    "explosive": "异常：爆炸性断裂", "elongation": "现象：伸长",
    "necking": "现象：颈缩", "cracking": "现象：开裂",
    "interface_separation": "现象：界面分离", "detachment": "现象：断后脱夹",
}
REVIEW_VALUES = ("unchecked", "judgable", "insufficient", "not_applicable")
ENCODING = {"codec": "libx264", "preset": "fast", "crf": 23,
            "pixel_format": "yuv420p", "audio": "dropped", "frame_sync": "passthrough"}


class RoiError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RoiError(f"无法读取 JSON：{path}: {exc}") from exc


def atomic_json(path: Path, value: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".roi-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[\w.-]+", value, re.UNICODE) or value in {".", ".."}:
        raise RoiError(f"视频 ID 含不安全字符：{value!r}")
    return value


def exact_pad_dimensions(width: int, height: int) -> tuple[int, int]:
    if width < 2 or height < 2:
        raise RoiError("源画面至少应为 2×2")
    scale = max(math.ceil(width / 3), math.ceil(height / 4))
    scale += scale % 2
    return 3 * scale, 4 * scale


def normalize_drag_box(box: Mapping, source_width: int, source_height: int) -> dict:
    """Same even 3:4 normalization as the original interactive ROI tool."""
    try:
        left = float(box.get("left", box.get("x")))
        top = float(box.get("top", box.get("y")))
        width, height = float(box["width"]), float(box["height"])
    except (TypeError, ValueError, KeyError) as exc:
        raise RoiError("选框坐标无效") from exc
    if not all(math.isfinite(v) for v in (left, top, width, height)) or min(width, height) <= 0:
        raise RoiError("选框须为有限数且宽高为正")
    left, top = min(source_width, max(0, left)), min(source_height, max(0, top))
    width, height = min(width, source_width-left), min(height, source_height-top)
    scale = math.floor(min(width/3, height/4))
    scale -= scale % 2
    if scale < 2:
        raise RoiError("框太小，无法形成偶数像素 3:4 范围")
    w, h = 3*scale, 4*scale
    return {"x": min(source_width-w, max(0, round(left+width/2-w/2))),
            "y": min(source_height-h, max(0, round(top+height/2-h/2))), "width": w, "height": h}


def geometry(decision: Mapping) -> dict:
    try:
        width, height = decision["source_resolution"]
    except (KeyError, ValueError, TypeError) as exc:
        raise RoiError("缺少源分辨率") from exc
    if any(type(v) is not int or v < 2 for v in (width, height)):
        raise RoiError("源分辨率无效")
    if decision.get("mode") == "no_crop":
        w, h = exact_pad_dimensions(width, height)
        x, y = (w-width)//2, (h-height)//2
        # Pad in 4:4:4 so FFmpeg cannot round an odd offset to a chroma grid.
        return {"filter": f"format=yuv444p,pad={w}:{h}:{x}:{y}:color=black,setsar=1", "output_resolution": [w,h],
                "crop_pixels": {k: 0 for k in ("top","bottom","left","right")},
                "pad_pixels": {"top":y,"bottom":h-height-y,"left":x,"right":w-width-x}}
    if decision.get("mode") != "fixed_roi":
        raise RoiError("处理方式必须是 fixed_roi 或 no_crop")
    box = decision.get("pixel_box", {})
    if any(type(box.get(k)) is not int for k in ("x","y","width","height")):
        raise RoiError("像素框坐标必须为整数")
    x,y,w,h = (box[k] for k in ("x","y","width","height"))
    if x < 0 or y < 0 or min(w,h) < 2 or x+w > width or y+h > height:
        raise RoiError("像素框越界")
    if w % 2 or h % 2 or w*4 != h*3:
        raise RoiError("像素框须为偶数宽高、精确 3:4")
    # exact=1 preserves odd x/y coordinates instead of chroma rounding them.
    return {"filter":f"crop={w}:{h}:{x}:{y}:exact=1,setsar=1", "output_resolution":[w,h],
            "crop_pixels":{"top":y,"bottom":height-y-h,"left":x,"right":width-x-w},
            "pad_pixels":{k:0 for k in ("top","bottom","left","right")}}


def probe_video(path: Path) -> dict:
    result = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
        "-show_entries","stream=width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_read_frames,nb_frames,duration:stream_tags=rotate:stream_side_data=rotation:format=duration",
        "-of","json",str(path)], capture_output=True, text=True)
    if result.returncode:
        raise RoiError(f"ffprobe 失败：{result.stderr.strip()[-1000:]}")
    try:
        raw = json.loads(result.stdout); stream = raw["streams"][0]
        rotation = float(stream.get("tags", {}).get("rotate", 0))
        for side in stream.get("side_data_list", []):
            if "rotation" in side:
                rotation = float(side["rotation"])
        rate = float(Fraction(stream["r_frame_rate"]))
        duration = float(stream.get("duration") or raw["format"]["duration"])
        header_count = stream.get("nb_frames")
        count = int(header_count) if header_count not in (None, "N/A") else None
        width, height = int(stream["width"]), int(stream["height"])
        if not math.isfinite(duration) or not math.isfinite(rotation) or duration <= 0 or rate <= 0 or (count is not None and count <= 0):
            raise ValueError("无效时间或方向")
        return {"width":width,"height":height,"frame_rate":stream["avg_frame_rate"],
                "nominal_frame_rate":stream["r_frame_rate"],"frame_count":count,
                "metadata_frame_count":count,"frame_count_basis":"metadata",
                "duration":duration,"rotation":rotation % 360,"pixel_format":stream.get("pix_fmt","unknown")}
    except (ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
        raise RoiError(f"媒体属性无法可靠获取：{path}") from exc


def decoded_frame_count(path: Path) -> int:
    """Read actual frames only when handling one selected source/output."""
    result = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
        "-count_frames","-show_entries","stream=nb_read_frames","-of","json",str(path)],
        capture_output=True, text=True)
    if result.returncode or result.stderr.strip():
        raise RoiError(f"实际计帧失败：{path}: {result.stderr.strip()[-1000:]}")
    try:
        count = int(json.loads(result.stdout)["streams"][0]["nb_read_frames"])
        if count <= 0: raise ValueError("没有可解码帧")
        return count
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        raise RoiError(f"无法可靠取得实际帧数：{path}") from exc


def verified_media(path: Path, media: Mapping) -> dict:
    value=dict(media)
    value.setdefault("metadata_frame_count",value.get("frame_count"))
    value.update(frame_count=decoded_frame_count(path),frame_count_basis="decoded")
    return value


def validate_media(source: Mapping, output: Mapping, resolution: list[int]):
    if [output["width"],output["height"]] != list(resolution):
        raise RoiError("输出分辨率不符合裁剪决定")
    if source["frame_count"] != output["frame_count"]:
        raise RoiError("输出帧数与原视频不同")
    a,b = float(Fraction(source["nominal_frame_rate"])),float(Fraction(output["nominal_frame_rate"]))
    if not math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-9):
        raise RoiError("输出标称帧率与原视频不同")
    if abs(source["duration"]-output["duration"]) > max(.02,1/max(a,1)+.005):
        raise RoiError("输出时长超出容差")
    if output.get("rotation", 0) != 0:
        raise RoiError("输出方向标记未归零")


def build_ffmpeg_command(source: Path, output: Path, decision: Mapping) -> list[str]:
    return ["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-n","-noautorotate","-i",str(source),
        "-map","0:v:0","-vf",geometry(decision)["filter"],"-vsync","0","-c:v","libx264",
        "-preset","fast","-crf","23","-pix_fmt","yuv420p","-an","-metadata:s:v:0","rotate=0",
        "-movflags","+faststart",str(output)]


def review_errors(review: Mapping | None, duration: float) -> list[str]:
    if not isinstance(review, Mapping): return ["尚未审核"]
    errors=[]
    items=review.get("items",{})
    if not isinstance(items, Mapping): return ["逐项审核记录格式无效"]
    for key,label in EVIDENCE_ITEMS.items():
        item=items.get(key,{})
        if not isinstance(item,Mapping):
            errors.append(f"{label}审核记录格式无效")
            continue
        if item.get("result") not in REVIEW_VALUES or item.get("result") == "unchecked":
            errors.append(f"{label}未检查")
        elif item.get("result") == "insufficient" and item.get("cause") != "source":
            errors.append(f"{label}存在处理损失或原因未明")
        elif item.get("result") in {"insufficient","not_applicable"} and not str(item.get("note","")).strip():
            errors.append(f"{label}缺少原因或不适用依据")
    intervals=review.get("checked_intervals",[])
    if not isinstance(intervals,list): return errors+["检查区间格式无效"]
    if not intervals: errors.append("未记录实际检查位置")
    for interval in intervals:
        if (not isinstance(interval,list) or len(interval)!=2 or
            any(type(x) not in (int,float) or not math.isfinite(x) for x in interval) or
            not 0 <= interval[0] <= interval[1] <= duration):
            errors.append("检查区间无效")
    if not review.get("confirmed"): errors.append("尚未确认审核")
    return errors


def recipe(source: Mapping, decision: Mapping) -> str:
    # Verification provenance is not a different spatial/temporal recipe.
    media={key:value for key,value in source["media"].items()
           if key not in {"metadata_frame_count","frame_count_basis"}}
    return digest({"source_sha256":source["sha256"],"media":media,
                   "mode":decision.get("mode"),"pixel_box":decision.get("pixel_box"),
                   "rule_version":RULE_VERSION,"processing_version":PROCESSING_VERSION,"encoding":ENCODING})


def source_matches(source: Mapping, decision: Mapping) -> bool:
    return (decision.get("source_sha256") == source["sha256"] and
            decision.get("source_resolution") == [source["media"]["width"],source["media"]["height"]] and
            decision.get("source_rotation", 0) == source["media"]["rotation"])


def load_decisions(path: Path) -> dict:
    raw=load_json(path,{"decisions":[]})
    if not isinstance(raw,dict) or not isinstance(raw.get("decisions"),list):
        raise RoiError(f"决定文件必须包含 decisions 数组：{path}")
    result={}
    for d in raw["decisions"]:
        if not isinstance(d,Mapping): raise RoiError("决定数组包含非对象条目")
        key=d.get("source_video_id")
        if not isinstance(key,str) or key in result: raise RoiError("决定 ID 缺失或重复")
        result[key]=d
    return result


def labels_by_id(path: Path | None) -> dict:
    if not path or not path.is_file(): return {}
    with path.open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    result={}
    for row in rows:
        key=row.get("video_id") or row.get("id") or row.get("视频ID") or row.get("视频编号") or row.get("ID")
        if key: result[str(key)]=row
    return result


def discover_videos(directory: Path) -> list[dict]:
    if not directory.is_dir(): raise RoiError(f"源视频目录不存在：{directory}")
    groups={}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            groups.setdefault(path.stem,[]).append(path.resolve())
    records=[]
    for key,paths in groups.items():
        try: safe_id(key)
        except RoiError as exc:
            records.append({"video_id":key,"status":"failed","reason":str(exc),"paths":[str(p) for p in paths]}); continue
        if len(paths)>1:
            records.append({"video_id":key,"status":"failed","reason":"视频 ID 重复（同名不同路径/扩展名）","paths":[str(p) for p in paths]})
        else: records.append({"video_id":key,"path":str(paths[0])})
    return records


def serialized(method):
    """Use a thread-reentrant lock plus an inter-process file lock."""
    @functools.wraps(method)
    def run(self, *args, **kwargs):
        with self._thread_lock:
            if self._lock_depth:
                return method(self, *args, **kwargs)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with (self.output_dir / ".roi.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    self._lock_depth = 1
                    return method(self, *args, **kwargs)
                finally:
                    self._lock_depth = 0
                    fcntl.flock(lock, fcntl.LOCK_UN)
    return run


def load_splits(directory: Path | None) -> tuple[dict, dict]:
    """Read one explicitly selected split version, never merge versions."""
    if directory is None:
        return {}, {"status":"not_provided"}
    directory=directory.resolve()
    paths=sorted(directory.glob("fold_*_train.json"))+sorted(directory.glob("fold_*_val.json"))
    if (directory/"test.json").is_file(): paths.append(directory/"test.json")
    if not paths:
        return {}, {"status":"not_provided","directory":str(directory),"reason":"目录中没有划分文件"}
    mapping={}; inputs=[]
    for path in paths:
        if path.name != "test.json" and re.fullmatch(r"fold_(\d+)_(train|val)\.json",path.name) is None:
            raise RoiError(f"划分文件名无效：{path.name}，应为 fold_N_train.json 或 fold_N_val.json")
        raw=load_json(path)
        ids=raw.get("video_ids") if isinstance(raw,dict) else None
        if not isinstance(ids,list) or any(not isinstance(v,str) for v in ids):
            raise RoiError(f"划分文件缺少 video_ids 字符串数组：{path}")
        inputs.append({"path":str(path),"sha256":sha256_file(path)})
        for video_id in ids:
            entry=mapping.setdefault(video_id,{"status":"provided","partition":None,"folds":{},"conflicts":[]})
            partition="test" if path.name=="test.json" else "development"
            if entry["partition"] not in (None,partition): entry["conflicts"].append("同一 ID 同时进入 test 与 development")
            entry["partition"]=partition
            if ids.count(video_id)>1: entry["conflicts"].append(f"{path.name} 含重复 ID")
            if partition=="development":
                match=re.fullmatch(r"fold_(\d+)_(train|val)\.json",path.name)
                if match is None: raise RoiError(f"划分文件名无效：{path.name}，应为 fold_N_train.json 或 fold_N_val.json")
                fold,role=match.groups()
                if fold in entry["folds"] and entry["folds"][fold]!=role:
                    entry["conflicts"].append(f"fold {fold} 同时进入 train 与 val")
                entry["folds"][fold]=role
            if entry["conflicts"]: entry["status"]="conflict"
    return mapping,{"status":"provided","directory":str(directory),"files":inputs}


class Workspace:
    def __init__(self, videos_dir: Path, output_dir: Path, *, labels: Path | None=None,
                 decisions: Path | None=None, existing_manifest: Path | None=None,
                 existing_media_dir: Path | None=None, splits_dir: Path | None=None):
        self._thread_lock=threading.RLock()
        self._lock_depth=0
        self.splits_dir=splits_dir
        self.videos_dir=videos_dir.resolve(); self.output_dir=output_dir.resolve()
        if self.output_dir == self.videos_dir or self.output_dir.is_relative_to(self.videos_dir):
            raise RoiError("输出目录不能位于源视频目录内")
        self.labels=labels
        self.candidate_path=decisions or self.output_dir/"imports/roi_decisions.legacy.json"
        self.existing_manifest=existing_manifest or self.output_dir/"imports/media-manifest.legacy.json"
        self.existing_media_dir=existing_media_dir or self.output_dir/"imports/media"
        self.decisions_path=self.output_dir/"decisions.json"
        self.manifest_path=self.output_dir/"manifest.json"
        self.drafts_path=self.output_dir/"drafts.json"

    def inventory(self, *, verify_source_ids: set[str] | None = None,
                  decode_source_ids: set[str] | None = None) -> dict:
        verify_source_ids = verify_source_ids or set()
        decode_source_ids = decode_source_ids or set()
        candidates=load_decisions(self.candidate_path)
        decisions=load_decisions(self.decisions_path)
        previous=load_json(self.manifest_path,{})
        old={r["video_id"]:r for r in previous.get("videos",[])}
        labels=labels_by_id(self.labels)
        drafts=load_json(self.drafts_path,{})
        splits,split_input=load_splits(self.splits_dir)
        rows=[]
        directory_error=None
        try:
            found_videos=discover_videos(self.videos_dir)
        except RoiError as exc:
            if not old: raise
            found_videos=[]
            directory_error=str(exc)
        found_ids={item["video_id"] for item in found_videos}
        for found in found_videos:
            key=found["video_id"]
            if found.get("status")=="failed": rows.append(found); continue
            path=Path(found["path"])
            row={"video_id":key,"source_path":str(path),"labels":labels.get(key,{}),
                 "split":splits.get(key,{"status":"not_provided","partition":None,"folds":{}})}
            previous_row=old.get(key,{})
            history=dict(previous_row.get("history",{}))
            if previous_row.get("recipe_hash") and previous_row.get("output"):
                history[previous_row["recipe_hash"]]={"output":previous_row["output"],
                    "output_review":previous_row.get("output_review"),
                    "output_review_draft":previous_row.get("output_review_draft")}
            if history: row["history"]=history
            try:
                stat=path.stat(); cache=old.get(key,{}).get("source",{})
                state={"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
                cached = (cache.get("path")==str(path) and cache.get("stat")==state and
                          "pixel_format" in cache.get("media",{}) and
                          "frame_count_basis" in cache.get("media",{}))
                if cached and key not in verify_source_ids:
                    source=cache
                    row["source_identity_check"]="cached_file_state"
                else:
                    current_sha=sha256_file(path)
                    if cache.get("sha256")==current_sha and "frame_count_basis" in cache.get("media",{}):
                        # Restoring the same bytes may change path/stat; its
                        # previously decoded count remains valid by SHA-256.
                        source={**cache,"path":str(path),"stat":state}
                    else:
                        source={"path":str(path),"sha256":current_sha,"stat":state,"media":probe_video(path)}
                    row["source_identity_check"]="sha256_verified"
                if key in decode_source_ids and source["media"].get("frame_count_basis") != "decoded":
                    source={**source,"media":verified_media(path,source["media"])}
                row["source"]=source
                decision=decisions.get(key) or candidates.get(key)
                if decision:
                    row["decision"]=decision
                    if not source_matches(source,decision):
                        row.update(status="needs_review",reason="决定与源视频身份或方向不一致")
                    else:
                        geometry(decision)
                        errors=review_errors(decision.get("source_review"),source["media"]["duration"])
                        if decision.get("rule_version") != RULE_VERSION: errors.insert(0,"决定需要按当前规则复核")
                        row.update(status="needs_review" if errors else "ready",reason="；".join(errors))
                        if not errors:
                            row["recipe_hash"]=recipe(source,decision)
                            prior=old.get(key,{})
                            if prior.get("recipe_hash") != row["recipe_hash"] and row["recipe_hash"] in history:
                                prior={"recipe_hash":row["recipe_hash"],**history[row["recipe_hash"]]}
                            if prior.get("recipe_hash")==row["recipe_hash"] and prior.get("generation_error"):
                                row.update(status="failed",reason=prior["generation_error"],generation_error=prior["generation_error"])
                            media=prior.get("output")
                            if prior.get("recipe_hash")==row["recipe_hash"] and media:
                                output=Path(media["path"])
                                output_state = {"size":output.stat().st_size,"mtime_ns":output.stat().st_mtime_ns} if output.is_file() else None
                                output_cached = output_state is not None and media.get("stat")==output_state
                                if output_state is not None and ((output_cached and key not in verify_source_ids) or sha256_file(output)==media["sha256"]):
                                    row["output"]=media
                                    row["output_review"]=prior.get("output_review")
                                    if prior.get("output_review_draft"):
                                        row["output_review_draft"]=prior["output_review_draft"]
                                    if (row["output_review"] or {}).get("output_sha256") == media["sha256"]:
                                        review= row["output_review"]
                                        err=review_errors(review,source["media"]["duration"])
                                        row.update(status="needs_output_review" if err else "success",reason="；".join(err))
                                    else: row.update(status="needs_output_review",reason="实际输出尚未审核")
                                    if row.get("output_review_draft"):
                                        row.update(status="needs_output_review",reason=row["output_review_draft"].get("pending_reason") or "输出审核草稿待完成")
                else: row.update(status="needs_decision",reason="请选择范围并审核")
                if key in drafts:
                    row["draft"]=drafts[key]
                    row.update(status="needs_review",reason=drafts[key].get("pending_reason") or "选框或审核草稿待完成")
                if source["media"]["rotation"] != 0:
                    row.update(status="needs_verification",reason="视频含旋转标记，需先明确显示方向与坐标；暂不自动处理")
                if row["split"]["status"]=="conflict":
                    row.update(status="needs_verification",reason="划分冲突："+"；".join(row["split"]["conflicts"]))
            except (RoiError,OSError,subprocess.SubprocessError) as exc:
                row.update(status="failed",reason=str(exc))
            rows.append(row)
        # A refresh must not erase an expected source merely because the file
        # disappeared. Preserve its identity/history until it is restored.
        for key,previous_row in old.items():
            if key not in found_ids:
                row=dict(previous_row)
                row.update(status="failed",source_missing=True,
                    reason=directory_error or "此前登记的源视频已缺失或不可访问，请恢复原文件后刷新")
                row.pop("generation_error",None)
                rows.append(row)
        result={"schema":SCHEMA,"rule_version":RULE_VERSION,"generated_at":now(),
                "videos_dir":str(self.videos_dir),"split_input":split_input,"videos":rows}
        result["summary"]={s:sum(r.get("status")==s for r in rows) for s in sorted({r.get("status") for r in rows})}
        result["total"]=len(rows); result["complete"]=bool(rows) and all(r.get("status")=="success" for r in rows)
        return result

    @serialized
    def refresh(self, *, verify_source_ids: set[str] | None = None) -> dict:
        result=self.inventory(verify_source_ids=verify_source_ids); atomic_json(self.manifest_path,result); return result

    @serialized
    def save_draft(self, row: Mapping, draft: Mapping):
        source=row["source"]
        if sha256_file(Path(source["path"]))!=source["sha256"]:
            raise RoiError("保存前源视频发生变化，请刷新")
        value=dict(draft)
        value.update(source_video_id=row["video_id"],source_sha256=source["sha256"],
            source_resolution=[source["media"]["width"],source["media"]["height"]],
            source_rotation=source["media"]["rotation"],saved_at=now())
        drafts=load_json(self.drafts_path,{})
        drafts[row["video_id"]]=value
        atomic_json(self.drafts_path,drafts)
        self.refresh()

    @serialized
    def save_decision(self, row: Mapping, decision: Mapping):
        source=row["source"]; path=Path(source["path"])
        if sha256_file(path)!=source["sha256"]: raise RoiError("保存前源视频发生变化，请刷新")
        d=dict(decision); d.update(source_video_id=row["video_id"],source_sha256=source["sha256"],
            source_resolution=[source["media"]["width"],source["media"]["height"]],
            source_rotation=source["media"]["rotation"],rule_version=RULE_VERSION,reviewed_at=now())
        geometry(d)
        errors=review_errors(d.get("source_review"),source["media"]["duration"])
        if errors: raise RoiError("；".join(errors))
        if source["media"]["rotation"] != 0: raise RoiError("旋转方向尚待核实")
        decisions=load_decisions(self.decisions_path); decisions[row["video_id"]]=d
        atomic_json(self.decisions_path,{"schema":SCHEMA,"rule_version":RULE_VERSION,"decisions":list(decisions.values())})
        drafts=load_json(self.drafts_path,{})
        if drafts.pop(row["video_id"],None) is not None:
            atomic_json(self.drafts_path,drafts)
        self.refresh()

    def _legacy_entry(self, video_id: str) -> dict | None:
        raw=load_json(self.existing_manifest,{})
        entries=raw.get("videos",raw.get("entries",raw.get("items",[]))) if isinstance(raw,dict) else []
        if isinstance(entries,dict): entries=list(entries.values())
        entry=next((e for e in entries if e.get("source_video_id",e.get("video_id"))==video_id),None)
        if entry is None: return None
        return {**entry,"_encoding_profile":raw.get("encoding_profile",{})}

    @serialized
    def generate(self, video_id: str) -> dict:
        manifest=self.inventory(verify_source_ids={video_id}); row=next((r for r in manifest["videos"] if r["video_id"]==video_id),None)
        if row is None: raise RoiError("视频 ID 不在输入清单")
        if row["status"] in {"success","needs_output_review"}: return row
        if not (row["status"] == "ready" or (row["status"] == "failed" and row.get("generation_error"))):
            raise RoiError(row.get("reason","尚未就绪"))
        # Metadata frame counts can be stale after stream-copy trimming. Count
        # only this source, cache it under the checked source hash, then derive
        # the recipe from the verified media identity.
        manifest=self.inventory(verify_source_ids={video_id},decode_source_ids={video_id})
        atomic_json(self.manifest_path,manifest)
        row=next(r for r in manifest["videos"] if r["video_id"]==video_id)
        if not (row["status"] == "ready" or (row["status"] == "failed" and row.get("generation_error"))):
            raise RoiError(row.get("reason","实际计帧未能完成，请核实源视频"))
        source=row["source"]; d=row["decision"]; key=row["recipe_hash"]
        folder=self.output_dir/"media"/safe_id(video_id); folder.mkdir(parents=True,exist_ok=True)
        target=folder/(key+".mp4")
        # Never accept an orphan file just because its name looks right.
        if target.exists(): raise RoiError("目标文件已存在但无可核对的记录；保留文件，请先核实")
        temporary=folder/(".building-"+next(tempfile._get_candidate_names())+".mp4")
        origin="generated"
        try:
            legacy=self._legacy_entry(video_id)
            candidate=self.existing_media_dir/(video_id+".mp4")
            # Legacy media is eligible only with source, output and geometry identity.
            if legacy and candidate.is_file():
                source_hash=legacy.get("source_sha256")
                output_hash=legacy.get("output_sha256") or legacy.get("sha256")
                legacy_box=legacy.get("pixel_box")
                profile=legacy.get("_encoding_profile",{})
                encoding_matches=(profile.get("video_codec")=="libx264" and profile.get("preset")=="fast" and
                    profile.get("crf")==23 and profile.get("pixel_format")=="yuv420p" and
                    profile.get("audio")=="dropped" and profile.get("frame_sync") in {"vsync_0_passthrough","passthrough"})
                # crop aligns to the INPUT chroma grid unless exact=1. The
                # encoded output pixel format cannot establish that grid.
                pixel_format=source["media"].get("pixel_format", "unknown")
                subsampling=re.fullmatch(r"(?:yuv|yuva|yuvj)(420|422|444)p(?:\d+(?:le|be))?",pixel_format)
                aligned=False
                if subsampling and d["mode"]=="fixed_roi":
                    grid={"420":(2,2),"422":(2,1),"444":(1,1)}[subsampling.group(1)]
                    aligned=(all(d["pixel_box"][field] % grid[0] == 0 for field in ("x","width")) and
                             all(d["pixel_box"][field] % grid[1] == 0 for field in ("y","height")))
                if d["mode"]=="no_crop":
                    geo=geometry(d)
                    pad=geo["pad_pixels"]
                    legacy_filter=str(legacy.get("video_filter",""))
                    legacy_pad=re.search(r"(?:^|,)pad=(\d+):(\d+):(\d+):(\d+)(?=[:,]|$)",legacy_filter)
                    expected_pad=(*geo["output_resolution"],pad["left"],pad["top"])
                    same_pad=(legacy_pad is not None and tuple(map(int,legacy_pad.groups()))==expected_pad)
                    # Old pad also rounds to the INPUT chroma grid. Do not
                    # infer that grid from the encoded output format.
                    pad_aligned=False
                    if subsampling:
                        grid={"420":(2,2),"422":(2,1),"444":(1,1)}[subsampling.group(1)]
                        pad_aligned=(pad["left"] % grid[0] == 0 and pad["top"] % grid[1] == 0)
                    exact_geometry=(same_pad and
                        (pad_aligned or legacy_filter.startswith("format=yuv444p,")))
                else:
                    exact_geometry=(aligned or ":exact=1" in str(legacy.get("video_filter","")))
                compatible=(source_hash==source["sha256"] and output_hash and encoding_matches and exact_geometry and
                    legacy.get("mode")==d["mode"] and
                    (d["mode"]=="no_crop" or legacy_box==d.get("pixel_box")))
                if compatible and sha256_file(candidate)==output_hash:
                    shutil.copyfile(candidate,temporary); origin="imported"
            if not temporary.exists():
                result=subprocess.run(build_ffmpeg_command(Path(source["path"]),temporary,d),capture_output=True,text=True)
                if result.returncode: raise RoiError("ffmpeg 失败："+result.stderr.strip()[-1500:])
            output_probe=verified_media(temporary,probe_video(temporary))
            validate_media(source["media"],output_probe,geometry(d)["output_resolution"])
            # Check full decode in addition to actual frame counting.
            decode=subprocess.run(["ffmpeg","-v","error","-xerror","-i",str(temporary),"-map","0:v:0","-f","null","-"],capture_output=True,text=True)
            if decode.returncode: raise RoiError("输出解码校验失败："+decode.stderr.strip()[-1000:])
            if sha256_file(Path(source["path"]))!=source["sha256"]: raise RoiError("生成时源视频发生变化")
            latest=next(r for r in self.inventory()["videos"] if r["video_id"]==video_id)
            if latest.get("recipe_hash")!=key: raise RoiError("生成时输入或决定发生变化，请刷新重试")
            sha=sha256_file(temporary)
            os.rename(temporary,target)
            row.pop("generation_error",None)
            row.update(output={"path":str(target),"sha256":sha,"media":output_probe,"stat":{"size":target.stat().st_size,"mtime_ns":target.stat().st_mtime_ns},"origin":origin,
                "encoding":ENCODING,"geometry":geometry(d)},status="needs_output_review",reason="媒体检查通过，等待实际输出审核")
            for i,item in enumerate(manifest["videos"]):
                if item["video_id"]==video_id: manifest["videos"][i]=row
            atomic_json(self.manifest_path,manifest)
            return self.refresh()
        except (RoiError, OSError, subprocess.SubprocessError) as exc:
            row.update(status="failed",reason=str(exc),generation_error=str(exc))
            for i,item in enumerate(manifest["videos"]):
                if item["video_id"]==video_id: manifest["videos"][i]=row
            atomic_json(self.manifest_path,manifest)
            self.refresh()
            raise
        finally: temporary.unlink(missing_ok=True)

    @serialized
    def save_output_draft(self, video_id: str, review: Mapping):
        manifest=self.inventory(verify_source_ids={video_id})
        row=next(r for r in manifest["videos"] if r["video_id"]==video_id)
        if row["status"] not in {"needs_output_review","success"}:
            raise RoiError("尚无通过媒体校验的输出")
        row["output_review_draft"]={**review,"output_sha256":row["output"]["sha256"],"saved_at":now()}
        atomic_json(self.manifest_path,manifest)
        self.refresh()

    @serialized
    def save_output_review(self, video_id: str, review: Mapping):
        manifest=self.inventory(verify_source_ids={video_id}); row=next(r for r in manifest["videos"] if r["video_id"]==video_id)
        if row["status"] not in {"needs_output_review","success"}: raise RoiError("尚无通过媒体校验的输出")
        errors=review_errors(review,row["source"]["media"]["duration"])
        if errors: raise RoiError("；".join(errors))
        row["output_review"]={**review,"output_sha256":row["output"]["sha256"],"reviewed_at":now()}
        row.pop("output_review_draft",None)
        atomic_json(self.manifest_path,manifest); self.refresh()
