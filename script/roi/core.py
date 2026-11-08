"""Standalone ROI rules and media processing; no GUI or model dependencies.

Geometry and encoding are adapted from mVllm_2 pipeline/roi_media.py and
pipeline/scripts/roi_annotation_app.py (2c272ce). Records use a new schema:
legacy media keeps its original pixels; visual review is optional and never inferred.
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

if __package__:
    from .label_fields import FIELDS_BY_COLUMN, values_from_labels
else:
    from label_fields import FIELDS_BY_COLUMN, values_from_labels

RULE_VERSION = "roi-rules/2"
PROCESSING_VERSION = "roi-processing/3"
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


def chroma_grid(pixel_format: str) -> tuple[int, int] | None:
    match=re.fullmatch(r"(?:yuv|yuva|yuvj)(420|422|444|411|410)p(?:\d+(?:le|be))?",pixel_format)
    if match:
        return {"420":(2,2),"422":(2,1),"444":(1,1),"411":(4,1),"410":(4,4)}[match.group(1)]
    if pixel_format in {"gray","gray8","rgb24","bgr24","rgba","bgra","gbrp"}:
        return (1,1)
    return None


def legacy_geometry(source: Mapping, decision: Mapping, entry: Mapping) -> dict:
    """Describe the old file's actual geometry without moving/re-encoding pixels."""
    width,height=source["media"]["width"],source["media"]["height"]
    requested=entry.get("pixel_box") or decision.get("pixel_box")
    value={"filter":entry.get("video_filter"),"output_resolution":entry.get("output_resolution"),
           "requested_pixel_box":requested,"effective_pixel_box":None,"crop_pixels":None,
           "pad_pixels":None,"geometry_status":"uncertain",
           "note":"保留旧视频原始字节；当前记录不足以可靠还原生效边界。"}
    video_filter=str(entry.get("video_filter", ""))
    grid=chroma_grid(source["media"].get("pixel_format","unknown"))
    if video_filter.startswith("format=yuv444p,"): grid=(1,1)
    if decision.get("mode")=="fixed_roi":
        crop=re.search(r"(?:^|,)crop=(\d+):(\d+):(\d+):(\d+)(?=[:,]|$)",video_filter)
        if crop is None: return value
        w,h,x,y=map(int,crop.groups())
        exact=":exact=1" in video_filter
        if not exact and grid is None: return value
        gx,gy=(1,1) if exact else grid
        x,y,w,h=x//gx*gx,y//gy*gy,w//gx*gx,h//gy*gy
        if min(w,h)<=0 or min(x,y)<0 or x+w>width or y+h>height: return value
        if entry.get("output_resolution") != [w,h]: return value
        value.update(effective_pixel_box={"x":x,"y":y,"width":w,"height":h},
            crop_pixels={"top":y,"bottom":height-y-h,"left":x,"right":width-x-w},
            pad_pixels={k:0 for k in ("top","bottom","left","right")})
    elif decision.get("mode")=="no_crop":
        pad=re.search(r"(?:^|,)pad=(\d+):(\d+):(\d+):(\d+)(?=[:,]|$)",video_filter)
        if pad is None or grid is None: return value
        w,h,x,y=map(int,pad.groups()); gx,gy=grid
        x,y=x//gx*gx,y//gy*gy
        if x+width>w or y+height>h or entry.get("output_resolution") != [w,h]: return value
        value.update(effective_pixel_box={"x":0,"y":0,"width":width,"height":height},
            crop_pixels={k:0 for k in ("top","bottom","left","right")},
            pad_pixels={"top":y,"bottom":h-y-height,"left":x,"right":w-x-width})
    else: return value
    value.update(geometry_status="verified_from_filter_and_source_format",
                 note="按旧滤镜和源像素格式记录实际边界；旧视频原始字节保持不变。")
    return value


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
        self.label_reviews_path=self.output_dir/"label_reviews.json"

    def _load_label_reviews(self) -> dict:
        raw=load_json(self.label_reviews_path,{"schema":"tensile-roi-label-review/1","videos":{}})
        if (not isinstance(raw,dict) or raw.get("schema")!="tensile-roi-label-review/1"
                or not isinstance(raw.get("videos"),dict)):
            raise RoiError("ROI 标签审查记录格式无效，已保留原文件。")
        for video_id,entry in raw["videos"].items():
            if (not isinstance(video_id,str) or not isinstance(entry,dict)
                    or not isinstance(entry.get("revisions"),list)
                    or any(not isinstance(revision,dict) for revision in entry["revisions"])):
                raise RoiError("ROI 标签审查历史格式无效，已保留原文件。")
        return raw

    @staticmethod
    def _label_review_identity(row: Mapping) -> dict | None:
        source_sha=row.get("source",{}).get("sha256")
        output_sha=row.get("output",{}).get("sha256")
        video_id=row.get("video_id")
        if (not isinstance(video_id,str) or any(not isinstance(value,str)
                or re.fullmatch(r"[0-9a-f]{64}",value) is None for value in (source_sha,output_sha))):
            return None
        return {"video_id":video_id,"source_sha256":source_sha,"output_sha256":output_sha,
                "source_labels_sha256":digest(dict(row.get("labels",{})))}

    def _label_review_state(self, row: Mapping, store: Mapping) -> dict:
        values=values_from_labels(row.get("labels",{}))
        identity=self._label_review_identity(row)
        entry=store["videos"].get(row.get("video_id"),{})
        revisions=entry.get("revisions",[])
        state={"status":"unmodified","values":values,"changes":{},"revision":None,
               "revision_id":None,"history_count":len(revisions)}
        if identity is None or row.get("source_missing"):
            state["status"]="unavailable"
            return state
        matching=next((revision for revision in reversed(revisions)
                       if revision.get("identity")==identity),None)
        if matching is None:
            if revisions: state["status"]="stale"
            return state
        changes=matching.get("changes")
        if (not isinstance(changes,dict) or any(column not in FIELDS_BY_COLUMN
                or not isinstance(value,str) for column,value in changes.items())
                or not isinstance(matching.get("revision_id"),str)):
            raise RoiError("ROI 标签审查内容无效，已保留原记录。")
        state.update(status="saved",changes=dict(changes),revision=matching,
                     revision_id=matching["revision_id"],values={**values,**changes})
        return state

    def label_review_state(self, row: Mapping) -> dict:
        """Load only revisions bound to this video, ROI and annotation row.

        This does not mark the video as visually reviewed.  Source annotation
        values remain available in ``row['labels']`` and in each saved snapshot.
        """
        return self._label_review_state(row,self._load_label_reviews())

    @serialized
    def save_label_review(self, row: Mapping, values: Mapping, *, expected_revision: str | None) -> dict:
        """Save explicitly edited label values separately from the source CSV.

        The caller passes the viewed row and its revision token.  Media hashes,
        the original annotation row and the current review revision are checked
        again under the existing workspace lock before atomic publication.
        """
        expected=self._label_review_identity(row)
        if expected is None or row.get("source_missing"):
            raise RoiError("尚无可绑定的源视频和 ROI 输出，不能保存标签审查。")
        if not isinstance(values,Mapping) or any(column not in FIELDS_BY_COLUMN
                or not isinstance(value,str) for column,value in values.items()):
            raise RoiError("标签修改必须使用界面字段及原始文本值。")
        video_id=expected["video_id"]
        manifest=self.inventory(verify_source_ids={video_id})
        current=next((item for item in manifest["videos"] if item["video_id"]==video_id),None)
        if (current is None or current.get("source_missing")
                or current.get("status") not in {"success","needs_output_review"}
                or self._label_review_identity(current)!=expected):
            raise RoiError("源视频、ROI 输出或原始标签已变化，请刷新后再保存。")
        store=self._load_label_reviews()
        state=self._label_review_state(current,store)
        if state["revision_id"]!=expected_revision:
            raise RoiError("标签审查已被其他页面更新，请刷新后再保存。")
        updated={**state["values"],**dict(values)}
        original=values_from_labels(current.get("labels",{}))
        for column,value in values.items():
            field=FIELDS_BY_COLUMN[column]
            if field.readonly and value!=original[column]:
                raise RoiError(f"{field.label}为来源信息，不能在 ROI 审查中修改。")
            if field.kind=="select" and value not in field.options and value!=original[column]:
                raise RoiError(f"{field.label}包含不支持的新标签值。")
        changes={column:value for column,value in updated.items() if value!=original[column]}
        if changes==state["changes"]:
            return state
        labels_sha=sha256_file(self.labels) if self.labels and self.labels.is_file() else None
        # Recheck identity just before writing; no source/ROI/annotation file is changed.
        if (sha256_file(Path(current["source"]["path"]))!=expected["source_sha256"]
                or sha256_file(Path(current["output"]["path"]))!=expected["output_sha256"]
                or digest(labels_by_id(self.labels).get(video_id,{}))!=expected["source_labels_sha256"]):
            raise RoiError("保存期间源视频、ROI 输出或原始标签发生变化，请刷新。")
        revision={"identity":expected,"saved_at":now(),"changes":changes,
                  "original_labels":dict(current.get("labels",{})),
                  "label_source":{"path":str(self.labels) if self.labels else None,
                                  "csv_sha256":labels_sha},
                  "record_type":"label_edits","visual_review_claimed":False}
        revision["revision_id"]=digest(revision)
        entry=store["videos"].setdefault(video_id,{"revisions":[]})
        entry["revisions"].append(revision)
        atomic_json(self.label_reviews_path,store)
        return self._label_review_state(current,store)

    def inventory(self, *, verify_source_ids: set[str] | None = None,
                  decode_source_ids: set[str] | None = None) -> dict:
        verify_source_ids=verify_source_ids or set(); decode_source_ids=decode_source_ids or set()
        candidates=load_decisions(self.candidate_path); decisions=load_decisions(self.decisions_path)
        previous=load_json(self.manifest_path,{})
        old={r["video_id"]:r for r in previous.get("videos",[])}
        labels=labels_by_id(self.labels); drafts=load_json(self.drafts_path,{})
        splits,split_input=load_splits(self.splits_dir)
        legacy_entries=self._legacy_entries()
        rows=[]; directory_error=None
        try: found_videos=discover_videos(self.videos_dir)
        except RoiError as exc:
            if not old: raise
            found_videos=[]; directory_error=str(exc)
        found_ids={item["video_id"] for item in found_videos}
        for found in found_videos:
            key=found["video_id"]
            if found.get("status")=="failed": rows.append(found); continue
            path=Path(found["path"]); previous_row=old.get(key,{})
            row={"video_id":key,"source_path":str(path),"labels":labels.get(key,{}),
                 "split":splits.get(key,{"status":"not_provided","partition":None,"folds":{}}),
                 "visual_review":{"required":False,"status":"not_recorded"}}
            # Keep earlier human records and drafts as history, never synthesize them.
            for field in ("output_review","output_review_draft","source_review","historical_review_records"):
                if field in previous_row: row[field]=previous_row[field]
            history=dict(previous_row.get("history",{}))
            if previous_row.get("recipe_hash") and previous_row.get("output"):
                history[previous_row["recipe_hash"]]={"output":previous_row["output"],
                    "output_review":previous_row.get("output_review"),
                    "output_review_draft":previous_row.get("output_review_draft")}
            if history: row["history"]=history
            if key in drafts:
                row["draft_history" if drafts[key].get("saved_as_decision_at") else "draft"]=drafts[key]
            try:
                stat=path.stat(); cache=previous_row.get("source",{})
                state={"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
                cached=(cache.get("path")==str(path) and cache.get("stat")==state and
                        "pixel_format" in cache.get("media",{}) and "frame_count_basis" in cache.get("media",{}))
                if cached and key not in verify_source_ids:
                    source=cache; row["source_identity_check"]="cached_file_state"
                else:
                    current_sha=sha256_file(path)
                    if cache.get("sha256")==current_sha and "frame_count_basis" in cache.get("media",{}):
                        source={**cache,"path":str(path),"stat":state}
                    else: source={"path":str(path),"sha256":current_sha,"stat":state,"media":probe_video(path)}
                    row["source_identity_check"]="sha256_verified"
                if key in decode_source_ids and source["media"].get("frame_count_basis")!="decoded":
                    source={**source,"media":verified_media(path,source["media"])}
                row["source"]=source
                selected=decisions.get(key)
                candidate=candidates.get(key)
                decision=selected or candidate
                if decision:
                    row["decision"]=decision
                    row["decision_origin"]="selected" if selected else "legacy"
                    if not source_matches(source,decision):
                        row.update(status="needs_decision",reason="当前源视频与旧决定不同，请为当前视频保存画面范围。")
                        row["reference_decision"]=decision
                    else:
                        geometry(decision)
                        row.update(status="ready",reason="画面范围已记录，可以生成ROI。")
                        row["recipe_hash"]=recipe(source,decision)
                        prior=previous_row
                        if prior.get("recipe_hash")!=row["recipe_hash"]:
                            prior={"recipe_hash":row["recipe_hash"],**history.get(row["recipe_hash"],{})}
                        media=prior.get("output")
                        if media and self._output_matches(media,key in verify_source_ids):
                            row.update(output=media,status="success",reason="ROI可用，可直接查看；有问题再调整。")
                            if prior.get("output_review"): row["output_review"]=prior["output_review"]
                        elif prior.get("generation_error"):
                            row.update(status="failed",reason=prior["generation_error"],generation_error=prior["generation_error"])
                        # An explicit new range wins; otherwise retain the old result itself.
                        if selected is None:
                            legacy=legacy_entries.get(key)
                            if legacy:
                                output=self._preserved_legacy(source,decision,legacy,previous_row,key in verify_source_ids)
                                row.update(output=output,status="success",reason="沿用旧ROI结果，可直接查看；标签采用已有标注。")
                                row["recipe_hash"]=digest({"origin":"preserved_legacy","source_sha256":source["sha256"],
                                                          "output_sha256":output["sha256"]})
                else: row.update(status="needs_decision",reason="新视频尚无范围，请选框或保留全画面后生成。")
                for field in ("output_review","output_review_draft"):
                    if field in row and (not row.get("output") or row[field].get("output_sha256")!=row["output"]["sha256"]):
                        records=dict(row.get("historical_review_records",{}))
                        record=row.pop(field)
                        records[digest({"field":field,"record":record})]={"field":field,"record":record}
                        row["historical_review_records"]=records
                if row.get("output") and row.get("output_review",{}).get("output_sha256")==row["output"]["sha256"]:
                    row["visual_review"]={"required":False,"status":"recorded_earlier"}
                if source["media"]["rotation"]!=0:
                    row.update(status="needs_verification",reason="视频含旋转标记，需要明确画面方向和坐标。")
                if row["split"]["status"]=="conflict":
                    row.update(status="needs_verification",reason="划分冲突："+"；".join(row["split"]["conflicts"]))
            except (RoiError,OSError,subprocess.SubprocessError) as exc:
                row.update(status="failed",reason=str(exc))
                row.pop("output",None)
            rows.append(row)
        for key,previous_row in old.items():
            if key not in found_ids:
                row=dict(previous_row); row.update(status="failed",source_missing=True,
                    reason=directory_error or "此前登记的源视频已缺失或不可访问，请恢复原文件后刷新")
                row.pop("generation_error",None); rows.append(row)
        result={"schema":SCHEMA,"rule_version":RULE_VERSION,"generated_at":now(),
                "videos_dir":str(self.videos_dir),"split_input":split_input,"videos":rows,
                "completion_basis":"roi_media_available","visual_review_required":False}
        result["summary"]={state:sum(r.get("status")==state for r in rows) for state in sorted({r.get("status") for r in rows})}
        result["total"]=len(rows); result["complete"]=bool(rows) and all(r.get("status")=="success" for r in rows)
        return result

    def _output_matches(self, media: Mapping, verify: bool=False) -> bool:
        output=Path(media["path"])
        if not output.is_file(): return False
        state={"size":output.stat().st_size,"mtime_ns":output.stat().st_mtime_ns}
        return (not verify and media.get("stat")==state) or sha256_file(output)==media.get("sha256")

    def _preserved_legacy(self, source: Mapping, decision: Mapping, legacy: Mapping,
                          previous: Mapping, verify: bool) -> dict:
        if legacy.get("source_sha256")!=source["sha256"]:
            raise RoiError("旧ROI清单绑定的是另一份源视频，不能用于当前视频。")
        if legacy.get("mode")!=decision.get("mode") or (decision.get("mode")=="fixed_roi" and
                legacy.get("pixel_box")!=decision.get("pixel_box")):
            raise RoiError("旧ROI清单与旧决定的画面范围不一致。")
        path=self.existing_media_dir/(safe_id(decision["source_video_id"])+".mp4")
        if not path.is_file(): raise RoiError("旧ROI视频缺失，原决定仍可参考，请重新生成。")
        expected=legacy.get("output_sha256") or legacy.get("sha256")
        if not isinstance(expected,str) or not re.fullmatch(r"[0-9a-f]{64}",expected):
            raise RoiError("旧ROI清单缺少完整输出摘要。")
        prior=previous.get("output",{})
        state={"size":path.stat().st_size,"mtime_ns":path.stat().st_mtime_ns}
        cached=(prior.get("path")==str(path) and prior.get("sha256")==expected and prior.get("stat")==state)
        if (verify or not cached) and sha256_file(path)!=expected:
            raise RoiError("旧ROI视频摘要与清单不一致，请核实文件。")
        media=prior.get("media") if cached else probe_video(path)
        resolution=legacy.get("output_resolution")
        if resolution!=[media["width"],media["height"]]: raise RoiError("旧ROI分辨率与清单不一致。")
        if media.get("rotation",0)!=0: raise RoiError("旧ROI视频方向异常。")
        recorded_rate=legacy.get("nominal_frame_rate") or legacy.get("frame_rate")
        if recorded_rate and not math.isclose(float(Fraction(recorded_rate)),float(Fraction(media["nominal_frame_rate"])),rel_tol=1e-6,abs_tol=1e-9):
            raise RoiError("旧ROI帧率与清单不一致。")
        recorded_count=legacy.get("frame_count")
        if recorded_count is not None and media.get("frame_count") is not None and int(recorded_count)!=media["frame_count"]:
            raise RoiError("旧ROI文件头帧数与清单不一致。")
        recorded_duration=legacy.get("duration")
        rate=float(Fraction(media["nominal_frame_rate"]))
        if recorded_duration is not None and abs(float(recorded_duration)-media["duration"])>max(.02,1/max(rate,1)+.005):
            raise RoiError("旧ROI时长与清单不一致。")
        # A self-consistent short output is not a complete ROI for a longer source.
        source_media=source["media"]
        source_rate=float(Fraction(source_media["nominal_frame_rate"]))
        if abs(source_media["duration"]-media["duration"])>max(.02,1/max(source_rate,1)+.005):
            raise RoiError("旧ROI未覆盖当前源视频的完整时长。")
        source_count=source_media.get("frame_count")
        output_count=media.get("frame_count")
        if source_count is not None and output_count is not None and source_count!=output_count:
            raise RoiError("旧ROI与当前源的帧数记录不一致，需要实际计帧核实。")
        nominal={"status":"matches","source_current":source_media["nominal_frame_rate"],
                 "source_recorded":legacy.get("source_nominal_frame_rate"),
                 "output_current":media["nominal_frame_rate"],"output_recorded":recorded_rate}
        if not math.isclose(source_rate,rate,rel_tol=1e-6,abs_tol=1e-9):
            # ffprobe versions may report different r_frame_rate for the same
            # source bytes. This narrow legacy path requires the old source and
            # output records, counts, durations and averages to remain coherent.
            try:
                old_source_rate=float(Fraction(legacy["source_nominal_frame_rate"]))
                source_average=float(Fraction(source_media["frame_rate"]))
                output_average=float(Fraction(media["frame_rate"]))
                old_source_average=float(Fraction(legacy["source_frame_rate"]))
                old_output_average=float(Fraction(legacy["frame_rate"]))
                old_source_count=int(legacy["source_frame_count"])
                old_output_count=int(legacy["frame_count"])
                old_source_duration=float(legacy["source_duration"])
                tolerance=max(.02,1/max(old_source_rate,1)+.005)
                one_frame_rate_tolerance=max(1/source_media["duration"],1/media["duration"])
                coherent=(source_count is not None and output_count is not None and
                    source_count==output_count==old_source_count==old_output_count and
                    math.isclose(old_source_rate,rate,rel_tol=1e-6,abs_tol=1e-9) and
                    math.isclose(source_average,old_source_average,rel_tol=1e-6,abs_tol=1e-9) and
                    math.isclose(output_average,old_output_average,rel_tol=1e-6,abs_tol=1e-9) and
                    abs(old_source_duration-source_media["duration"])<=tolerance and
                    abs(source_average-output_average)<=one_frame_rate_tolerance)
            except (KeyError,ValueError,TypeError,ZeroDivisionError): coherent=False
            if not coherent:
                raise RoiError("旧ROI与当前源视频的标称帧率不同，且已有时序记录不足以证明兼容。")
            nominal.update(status="metadata_disagreement",
                source_average=source_media["frame_rate"],output_average=media["frame_rate"],
                average_rate_tolerance_fps=one_frame_rate_tolerance,
                note="标称帧率元数据存在差异；来源、帧数、总时长和平均帧率核对通过，旧视频保持原样。未比较逐帧时间戳。")
        return {"path":str(path),"sha256":expected,"stat":state,"media":media,"origin":"preserved_legacy",
                "encoding":legacy.get("_encoding_profile",{}),"geometry":legacy_geometry(source,decision,legacy),
                "validation":{"source_identity":"sha256","output_identity":"sha256",
                              "media_properties":"metadata_matches_legacy_manifest","full_decode":"not_performed",
                              "nominal_frame_rate":nominal,"frame_timestamps":"not_compared"},
                "visual_review":{"required":False,"status":"not_recorded"}}

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
        drafts=load_json(self.drafts_path,{})
        prior_draft=drafts.get(row["video_id"],{})
        d=dict(decision)
        if prior_draft:
            d["prior_draft"]=prior_draft
            if not d.get("pending_reason"): d["pending_reason"]=prior_draft.get("pending_reason","")
        d.update(source_video_id=row["video_id"],source_sha256=source["sha256"],
            source_resolution=[source["media"]["width"],source["media"]["height"]],
            source_rotation=source["media"]["rotation"],rule_version=RULE_VERSION,saved_at=now())
        geometry(d)
        if source["media"]["rotation"] != 0: raise RoiError("旋转方向尚待核实")
        decisions=load_decisions(self.decisions_path); decisions[row["video_id"]]=d
        atomic_json(self.decisions_path,{"schema":SCHEMA,"rule_version":RULE_VERSION,"decisions":list(decisions.values())})
        if prior_draft:
            drafts[row["video_id"]]={**prior_draft,"saved_as_decision_at":d["saved_at"]}
            atomic_json(self.drafts_path,drafts)
        self.refresh()

    def _legacy_entries(self) -> dict:
        raw=load_json(self.existing_manifest,{})
        entries=raw.get("videos",raw.get("entries",raw.get("items",[]))) if isinstance(raw,dict) else []
        if isinstance(entries,dict): entries=list(entries.values())
        if not isinstance(entries,list): raise RoiError("旧ROI清单须包含视频数组。")
        result={}
        for entry in entries:
            if not isinstance(entry,Mapping): raise RoiError("旧ROI清单含非对象条目。")
            key=entry.get("source_video_id",entry.get("video_id"))
            if not isinstance(key,str) or key in result: raise RoiError("旧ROI清单ID缺失或重复。")
            result[key]={**entry,"_encoding_profile":raw.get("encoding_profile",{})}
        return result

    def _legacy_entry(self, video_id: str) -> dict | None:
        return self._legacy_entries().get(video_id)

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
                "encoding":ENCODING,"geometry":geometry(d)},status="success",reason="ROI已生成并通过媒体检查，可直接查看，有问题再修改。")
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
    def import_generated(self, video_id: str, staged_path: Path, decision: Mapping,
                         expected_sha256: str, *, expected_source_sha256: str, generated_on: str) -> dict:
        """Accept one externally generated ROI after current-source/media checks.

        This internal helper does not add a user workflow or claim visual review.
        Source, old media, other rows and draft files are never overwritten.
        """
        if not re.fullmatch(r"[0-9a-f]{64}",expected_sha256) or not generated_on.strip():
            raise RoiError("导入需要完整输出摘要和生成位置记录。")
        staged_path=Path(staged_path).resolve()
        if staged_path.is_relative_to(self.videos_dir) or not staged_path.is_file():
            raise RoiError("待导入文件必须位于源视频目录之外且可读取。")
        if sha256_file(staged_path)!=expected_sha256:
            raise RoiError("待导入输出摘要不符。")
        manifest=self.inventory(verify_source_ids={video_id},decode_source_ids={video_id})
        row=next((item for item in manifest["videos"] if item["video_id"]==video_id),None)
        if row is None or "source" not in row or row.get("source_missing"):
            raise RoiError("当前源视频不在清单或不可读取。")
        if row["source"]["media"].get("frame_count_basis")!="decoded":
            raise RoiError("当前源实际计帧未完成。")
        if row["split"].get("status")=="conflict" or row["source"]["media"]["rotation"]!=0:
            raise RoiError("源视频方向或划分尚待核实。")
        source=row["source"]
        if source["sha256"]!=expected_source_sha256:
            raise RoiError("外部生成时的源摘要与当前源视频不一致。")
        required={"source_video_id","source_sha256","source_resolution","source_rotation"}
        if not required.issubset(decision) or decision.get("source_video_id")!=video_id or not source_matches(source,decision):
            raise RoiError("外部生成决定缺少完整来源身份，或与当前源视频不一致。")
        d=dict(decision)
        d.update(source_video_id=video_id,source_sha256=source["sha256"],
            source_resolution=[source["media"]["width"],source["media"]["height"]],
            source_rotation=source["media"]["rotation"],rule_version=RULE_VERSION,saved_at=now())
        geo=geometry(d); key=recipe(source,d)
        output_media=verified_media(staged_path,probe_video(staged_path))
        validate_media(source["media"],output_media,geo["output_resolution"])
        decode=subprocess.run(["ffmpeg","-v","error","-xerror","-i",str(staged_path),"-map","0:v:0","-f","null","-"],capture_output=True,text=True)
        if decode.returncode: raise RoiError("导入输出解码校验失败："+decode.stderr.strip()[-1000:])
        folder=self.output_dir/"media"/safe_id(video_id); folder.mkdir(parents=True,exist_ok=True)
        target=folder/(key+".mp4")
        history=dict(row.get("history",{}))
        if row.get("recipe_hash") and row.get("output"):
            history[row["recipe_hash"]]={"output":row["output"],"output_review":row.get("output_review"),
                                        "output_review_draft":row.get("output_review_draft")}
        known=row.get("output") if row.get("recipe_hash")==key else history.get(key,{}).get("output")
        if target.exists():
            if not known or known.get("path")!=str(target) or known.get("sha256")!=expected_sha256 or sha256_file(target)!=expected_sha256:
                raise RoiError("目标文件已存在但身份不符或没有记录；保留原文件，拒绝覆盖。")
        else:
            temporary=folder/(".importing-"+next(tempfile._get_candidate_names())+".mp4")
            try:
                shutil.copyfile(staged_path,temporary)
                if sha256_file(temporary)!=expected_sha256 or sha256_file(Path(source["path"]))!=source["sha256"]:
                    raise RoiError("导入期间源视频或输出发生变化。")
                # Hard-link publication is atomic and refuses a concurrent existing target.
                os.link(temporary,target)
            finally: temporary.unlink(missing_ok=True)
        if sha256_file(Path(source["path"]))!=source["sha256"]:
            raise RoiError("接入记录前源视频发生变化，请重新核对。")
        decisions=load_decisions(self.decisions_path); decisions[video_id]=d
        atomic_json(self.decisions_path,{"schema":SCHEMA,"rule_version":RULE_VERSION,"decisions":list(decisions.values())})
        row.update(decision=d,decision_origin="selected",recipe_hash=key,history=history,status="success",
            reason="已接入外部生成的ROI，媒体检查通过，可直接查看。",
            output={"path":str(target),"sha256":expected_sha256,"media":output_media,
                    "stat":{"size":target.stat().st_size,"mtime_ns":target.stat().st_mtime_ns},
                    "origin":"imported_generated","generated_on":generated_on,"encoding":ENCODING,"geometry":geo,
                    "validation":{"source_identity":"sha256","output_identity":"sha256","full_decode":"passed"}},
            visual_review={"required":False,"status":"not_recorded"})
        for field in ("generation_error","output_review","output_review_draft"):
            row.pop(field,None)
        for index,item in enumerate(manifest["videos"]):
            if item["video_id"]==video_id: manifest["videos"][index]=row
        atomic_json(self.manifest_path,manifest)
        return self.refresh()

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
