#!/usr/bin/env python3
"""Generate candidates awaiting label review from one training fold's ROI videos."""
from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from script.subvideo_generation.pilot import aligned, geometry, pilot as base
from script.subvideo_generation._legacy.core import anchors, verification

SCHEMA = "tensile-sub-video/2"
ANOMALIES = ("未夹紧", "视频异常", "爆炸性断裂")
PHENOMENA = ("伸长", "颈缩", "开裂", "界面分离", "断后脱夹")

# 本模块是历史归档生成路径（subvideo_generation/_legacy），只用于复现此前批次。
# 此前批次使用的 CSV/清单里 `断裂状态` 可能是旧词「无法确定」：为保持旧批次可复现，
# 输入判定同时接受「无法判断」与「无法确定」（UNCERTAIN_INPUTS）；但派生输出统一为
# 「无法判断」。新口径 CSV 归一化在 script/data_split 侧完成，本模块不做源值改写
# （`_source_labels` 仍原样透传源值）。
# 失效条件：旧批次不再需要复现，或历史清单里的旧词已离线迁移为「无法判断」
#（那时应把输入判定收缩为单一取值并删除本段说明）。
UNCERTAIN = "无法判断"
UNCERTAIN_INPUTS = (UNCERTAIN, "无法确定")
LEGACY_UNCERTAIN = ("无法确定", "无法识别")


class PendingSource(base.SkipSource):
    """An input cannot yet be processed under the approved rules."""


def _present(value) -> bool:
    return value not in (None, "", "无")


def _unified_uncertain(value):
    """Derived labels use the unified term even when the source row kept an old word."""
    return UNCERTAIN if value in LEGACY_UNCERTAIN else value


def adapt_annotation(row: dict, media: dict, phenomenon_anchor: dict | None = None) -> dict:
    """Use current temporal observations without the old label compatibility gates."""
    fields = ("断裂帧_前", "断裂帧_后", "断裂时间点", "断裂时间范围_下界", "断裂时间范围_上界")
    has_event = any(_present(row.get(name)) for name in fields)
    if row.get("异常_视频异常") == "是" and not has_event:
        raise PendingSource("视频异常")
    if row.get("异常_未夹紧") == "是":
        if not isinstance(phenomenon_anchor, dict):
            raise PendingSource("未夹紧：缺少现象时刻")
        event = phenomenon_anchor.get("source_frame")
        if type(event) is not int or not 0 <= event < media["total_frames"]:
            raise PendingSource("未夹紧：现象帧号无效或越界")
        return {"video_id": row["id"], "fps": media["fps"], "total_frames": media["total_frames"],
                "duration": media["duration"], "event_kind": "unclamped", "event_frame": event,
                "anchor_frames": [event], "source_event_pts": media["timestamps"][event],
                "phenomenon_anchor": dict(phenomenon_anchor)}
    if phenomenon_anchor is not None:
        raise PendingSource("现象帧记录与未夹紧标签不匹配")
    total = media["total_frames"]
    record = {"video_id": row["id"], "fps": media["fps"], "total_frames": total,
              "duration": total / media["fps"], "is_abnormal_canonical": False,
              "location_canonical": None, "source_fracture_mode": row.get("断裂模式", "")}
    if not has_event:
        if row.get("断裂状态") != "未断裂":
            raise PendingSource("断裂状态为无法判断（含旧记录的无法确定）且缺少断裂时刻或完整时间范围"
                                if row.get("断裂状态") in UNCERTAIN_INPUTS
                                else "缺少断裂时刻或完整时间范围")
        if row.get("异常_爆炸性断裂") == "是":
            raise PendingSource("未断裂与爆炸性断裂标签冲突")
        return dict(record, type="未断裂", has_fracture_canonical=False,
                    event_kind="none", event_time=None, event_time_reliable=False, anchor_frames=[])
    if row.get("断裂状态") == "未断裂":
        raise PendingSource("未断裂与断裂时间标注冲突")
    mechanism = row.get("断裂模式")
    # Root-type geometry is only an internal route to the existing 'other' strategy.
    # It is never exposed as a candidate or source label.
    geometry_type = mechanism if geometry.map_legacy_fracture_type(mechanism).matched else "齐根断裂"
    record.update(type=geometry_type, has_fracture_canonical=True)
    before = aligned._integer_frame(row.get("断裂帧_前"), total)
    after = aligned._integer_frame(row.get("断裂帧_后"), total)
    if before is not None and after is not None:
        if after != before + 1:
            raise PendingSource("精确断裂前后帧不相邻")
        return dict(record, event_kind="exact", event_frame=after, lower_frame=before, upper_frame=after,
                    anchor_frames=[before, after], event_time=after / media["fps"], event_time_reliable=True,
                    source_event_pts=media["timestamps"][after])
    lower_value, upper_value = row.get("断裂时间范围_下界"), row.get("断裂时间范围_上界")
    if _present(lower_value) or _present(upper_value):
        if not _present(lower_value) or not _present(upper_value):
            raise PendingSource("断裂时间范围缺少边界")
        try:
            lower = aligned._range_frame(lower_value, row.get("视频帧率"), total)
            upper = aligned._range_frame(upper_value, row.get("视频帧率"), total)
        except aligned.AlignmentUncertain as exc:
            raise PendingSource(str(exc)) from exc
        if lower >= upper:
            raise PendingSource("断裂时间范围上下界无效")
        return dict(record, event_kind="range", lower_frame=lower, upper_frame=upper,
                    anchor_frames=[lower, upper], event_time=lower / media["fps"], event_time_reliable=True,
                    source_event_range_pts=[media["timestamps"][lower], media["timestamps"][upper]])
    if _present(row.get("断裂时间点")):
        raise PendingSource("仅有断裂时间点：缺少已确认的源帧定位规则")
    raise PendingSource("缺少有效精确帧或完整断裂时间范围")


def plan_windows(record: dict, media: dict) -> tuple[list[dict], list[dict]]:
    if record["event_kind"] == "unclamped":
        event = record["event_frame"]
        times = media["timestamps"]
        usable_end = media["duration"]
        boundaries = times + [usable_end]
        accepted, excluded, seen = [], [], set()
        for target in geometry.TARGET_DURATIONS:
            base_window = {"window_role": "unclamped", "event_kind": "unclamped", "target_duration_seconds": target}
            if usable_end < target - 1e-9:
                excluded.append(dict(base_window, reason="未夹紧：源素材不足目标时长"))
                continue
            preferred_start = times[event] - target / 2
            desired_start = max(0., min(preferred_start, usable_end - target))
            start = anchors.nearest_boundary(boundaries, desired_start)
            end = anchors.nearest_boundary(boundaries, desired_start + target)
            if not 0 <= start <= event < end <= len(times) or boundaries[end] - boundaries[start] < 1 - 1e-9:
                excluded.append(dict(base_window, reason="未夹紧：窗口无法覆盖现象帧或不足一秒"))
                continue
            if (start, end) in seen:
                excluded.append(dict(base_window, reason="未夹紧：帧对齐后窗口重复"))
                continue
            seen.add((start, end))
            duration = boundaries[end] - boundaries[start]
            shifted = abs(desired_start - preferred_start) > 1e-9
            accepted.append(dict(base_window, start_frame=start, end_frame=end,
                                 source_frame_range=[start, end], start_time=times[start], end_time=boundaries[end],
                                 source_start_pts=times[start], source_end_pts=boundaries[end],
                                 duration=duration, source_duration=duration, duration_policy="standard",
                                 window_variant="unclamped_shifted" if shifted else "unclamped_centered",
                                 requested_event_position_ratio=.5,
                                 event_position_ratio=(times[event]-times[start])/duration,
                                 position_policy="shift_to_source_boundary" if shifted else "centered",
                                 phenomenon_anchor=dict(record["phenomenon_anchor"])))
        return accepted, excluded
    return aligned.plan_windows(record, media)


def _source_labels(row: dict) -> dict:
    return {"断裂状态": row.get("断裂状态", ""), "断裂模式": row.get("断裂模式", ""),
            "断裂位置": row.get("断裂位置", ""),
            "异常情况": {name: row.get("异常_" + name, "") for name in ANOMALIES},
            "断裂现象": {name: row.get("现象_" + name, "") for name in PHENOMENA}}


def candidate_labels(row: dict, role: str) -> dict:
    labels = _source_labels(row)
    state = row.get("断裂状态", UNCERTAIN) if role == "unclamped" else {"pre": "未断裂", "pre_event": "未断裂", "fracture": "发生断裂",
                            "transition": "发生断裂", "post": "已断裂", "post_event": "已断裂",
                            "no_fracture": "未断裂", "stable_negative": "未断裂"}.get(role, UNCERTAIN)
    labels["断裂状态"] = _unified_uncertain(state)
    if labels["断裂状态"] == "未断裂" or row.get("异常_未夹紧") == "是":
        labels["断裂模式"] = labels["断裂位置"] = "无"
    return labels


def _name_candidates(windows: list[dict], row: dict, folds: dict, source_sha: str, roi_sha: str) -> list[dict]:
    candidates = []
    from script.subvideo_generation import rules
    for old_role, role in rules.ROLE_NAMES.items():
        selected = sorted((w for w in windows if w["window_role"] == old_role), key=lambda w: (w["start_frame"], w["end_frame"]))
        for serial, window in enumerate(selected, 1):
            name = f"{row['id']}_{role}_{serial:02d}"
            candidate = {k: v for k, v in window.items() if k != "candidate_v3_labels"}
            candidate.update(candidate_id=name, filename=name + ".mp4", source_video_id=row["id"],
                             role=role, sequence=serial, folds=folds, scope="training",
                             source_sha256=source_sha, roi_sha256=roi_sha,
                             source_anchor_frames=[], output_path="videos/" + name + ".mp4", status="planned",
                             source_labels=_source_labels(row), candidate_labels=candidate_labels(row, role),
                             final_labels=None, labels_status="unreviewed", manual_review="required",
                             review={"status": "未审核", "decision": None, "change_notes": ""},
                             review_focus=["视频异常", "断裂位置"] if role == "pre" else list(_source_labels(row)))
            candidates.append(candidate)
    return candidates


def crop_video(roi_path: Path, output_path: Path, candidate: dict, roi_media: dict, source_proof: dict) -> dict:
    """Write an output only after independent, complete frame replay has passed."""
    verification.validate_source_receipt(source_proof, roi_path, candidate)
    fd, name = tempfile.mkstemp(prefix=".sub-video-", suffix=".mp4", dir=output_path.parent)
    os.close(fd)
    temporary = Path(name)
    temporary.unlink()
    try:
        base._checked(aligned.build_crop_command(roi_path, temporary, candidate))
        media = aligned.probe_video(temporary)
        if (media["total_frames"] != candidate["end_frame"] - candidate["start_frame"]
            or (media["width"], media["height"]) != (roi_media["width"], roi_media["height"])
            or media["duration"] < geometry.MIN_CANDIDATE_SECONDS - 1e-6):
            raise PendingSource("子视频帧数、分辨率或时长不符合窗口")
        proof = verification.verify_clip_replay(roi_path, temporary, candidate, roi_media, source_proof)
        digest = base.sha256_file(temporary)
        # Keep the document/source pins live through the final atomic publish.
        verification.validate_source_receipt(source_proof, roi_path, candidate)
        os.link(temporary, output_path)
        compact_media = {k: media[k] for k in ("duration", "total_frames", "fps", "width", "height", "time_base")}
        return {"sha256": digest, "media": compact_media, "full_decode": "passed", "frame_preserving_replay": proof,
                "frame_mapping": {"source_start_frame": candidate["start_frame"], "output_start_frame": 0,
                                  "anchors": proof["anchors"]}}
    finally:
        temporary.unlink(missing_ok=True)


def summarize(manifest: dict) -> dict:
    return {"scope": "training", "fold": manifest["identity"]["fold"], "source_count": len(manifest["sources"]),
            "source_status": dict(Counter(s["status"] for s in manifest["sources"])),
            "source_reasons": dict(Counter(s["reason"] for s in manifest["sources"] if s.get("reason"))),
            "candidate_count": len(manifest["candidates"]),
            "candidate_status": dict(Counter(c["status"] for c in manifest["candidates"])),
            "roles": dict(Counter(c["role"] for c in manifest["candidates"])),
            "excluded_windows": len(manifest["excluded_windows"]), "complete": manifest["complete"],
            "published": False, "manual_review": "required_for_every_publishable_clip"}


def run(project_root: Path, output_dir: Path | None = None, *, fold: int, plan_only=False, resume=False) -> dict:
    if type(fold) is not int or fold not in (0, 1, 2):
        raise base.PilotError("fold must be 0, 1 or 2")
    root = Path(project_root).resolve()
    output = (root / "data/sub_video") if output_dir is None else Path(output_dir)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    # Protect all existing inputs, even when the output path is customized.
    protected = [root / "data/videos", root / "data/roi", root / "data/splits", root / "script"]
    if output == root or any(output == p or p in output.parents or output in p.parents for p in protected):
        raise base.PilotError("output directory overlaps protected inputs")
    rows, rois, folds, hashes = base.load_inputs(root)
    anchor_path = root / anchors.DOCUMENT
    anchor_document_sha = base.sha256_file(anchor_path) if anchor_path.is_file() else None
    anchor_records, anchor_issue = {}, None
    if anchor_document_sha is not None:
        hashes[anchors.DOCUMENT] = anchor_document_sha
        try:
            anchor_records = anchors.load_anchors(anchor_path)
        except (anchors.AnchorError, UnicodeError) as exc:
            anchor_issue = str(exc)
    selected = {v for v in rows if folds[v][str(fold)] == "train"}
    identity = {"schema": SCHEMA, "fold": fold, "scope": "training", "inputs": hashes,
                "code": verification._code(), "guard_seconds": .5, "post_remaining_seconds": 2.0,
                "phenomenon_document": {"path": anchors.DOCUMENT, "sha256": anchor_document_sha}}
    with base._run_lock(output):
        if output.exists():
            if not resume:
                raise base.PilotError("output already exists; use another directory or explicit --resume")
            manifest = base._load(output / "manifest.json")
            if manifest.get("identity") != identity:
                raise base.PilotError("resume input, selected fold or code identity differs")
        else:
            if resume:
                raise base.PilotError("cannot resume a missing directory")
            output.mkdir(parents=True)
            manifest = {"schema": SCHEMA, "identity": identity, "sources": [], "candidates": [],
                        "excluded_windows": [], "complete": False, "published": False, "plan_only": bool(plan_only)}
        (output / "videos").mkdir(exist_ok=True)
        def save():
            base._atomic_json(output / "manifest.json", manifest)
            base._atomic_json(output / "summary.json", summarize(manifest))
        save()
        known = {s["video_id"] for s in manifest["sources"]}
        for video_id in sorted(selected - known):
            row, roi = rows[video_id], rois[video_id]
            source = {"video_id": video_id, "source_annotation": row, "folds": folds[video_id]}
            try:
                # Check label-only skip conditions before reading any source media.
                event_fields = ("断裂帧_前", "断裂帧_后", "断裂时间点", "断裂时间范围_下界", "断裂时间范围_上界")
                if row.get("异常_视频异常") == "是" and not any(_present(row.get(k)) for k in event_fields):
                    raise PendingSource("视频异常")
                if row.get("异常_未夹紧") == "是":
                    if anchor_issue or video_id not in anchor_records:
                        raise PendingSource(anchor_issue or "未夹紧：缺少现象时刻")
                elif video_id in anchor_records:
                    raise PendingSource("现象帧记录与未夹紧标签不匹配")
                if roi.get("status") != "success":
                    raise PendingSource("ROI不可用")
                raw, cropped = root / "data/videos" / (video_id + ".mp4"), root / "data/roi/videos" / (video_id + ".mp4")
                source_sha, roi_sha = base.sha256_file(raw), base.sha256_file(cropped)
                if (source_sha != roi.get("source", {}).get("sha256") or roi_sha != roi.get("output", {}).get("sha256")
                    or roi.get("decision", {}).get("source_sha256") != source_sha):
                    raise PendingSource("源视频、ROI或裁剪决定身份不一致")
                raw_media, roi_media = aligned.probe_video(raw), aligned.probe_video(cropped)
                if raw_media["total_frames"] != roi_media["total_frames"]:
                    raise PendingSource("源视频与ROI帧数不一致")
                phenomenon_anchor = anchor_records.get(video_id)
                if phenomenon_anchor and phenomenon_anchor["source_sha256"] != source_sha:
                    raise PendingSource("未夹紧：现象帧记录的源视频身份不一致")
                record = adapt_annotation(row, raw_media, phenomenon_anchor=phenomenon_anchor)
                windows, excluded = plan_windows(record, raw_media)
                proof = verification.verify_source_replay(raw, cropped, roi, source_annotation=row,
                                                          phenomenon_anchor=phenomenon_anchor)
                source.update(status="planned", source_path=str(raw.relative_to(root)), roi_path=str(cropped.relative_to(root)),
                              source_sha256=source_sha, roi_sha256=roi_sha, roi_media=roi_media,
                              frame_preserving_replay=proof)
                manifest["excluded_windows"].extend(dict(w, source_video_id=video_id) for w in excluded)
                candidates = _name_candidates(windows, row, folds[video_id], source_sha, roi_sha)
                for c in candidates:
                    c["source_anchor_frames"] = record["anchor_frames"]
                manifest["candidates"].extend(candidates)
                if not candidates:
                    source.update(status="pending", reason="没有满足时间边界和素材要求的窗口")
            except (PendingSource, aligned.AlignmentUncertain, verification.ReplayUncertain, FileNotFoundError) as exc:
                source.update(status="pending", reason=str(exc))
            except (base.PilotError, ValueError, KeyError, TypeError, OSError) as exc:
                source.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
            manifest["sources"].append(source)
            save()
        admitted = {s["video_id"]: s for s in manifest["sources"] if s["status"] == "planned"}
        if not plan_only:
            for candidate in manifest["candidates"]:
                dest = output / candidate["output_path"]
                if candidate["status"] == "cropped":
                    if not dest.is_file() or base.sha256_file(dest) != candidate["output"]["sha256"]:
                        raise base.PilotError("recorded output missing or changed")
                    continue
                if dest.exists():
                    raise base.PilotError("unrecorded output exists; no overwrite")
                source = admitted[candidate["source_video_id"]]
                try:
                    result = crop_video(root / source["roi_path"], dest, candidate, source["roi_media"], source["frame_preserving_replay"])
                    try:
                        unchanged = (base.sha256_file(root / source["source_path"]) == source["source_sha256"]
                                     and base.sha256_file(root / source["roi_path"]) == source["roi_sha256"]
                                     and all(base.sha256_file(root / relative) == digest for relative, digest in hashes.items())
                                     and not (anchor_document_sha is None and anchor_path.exists()))
                    except OSError:
                        unchanged = False
                    if not unchanged:
                        # Only remove bytes produced by this call, never a replaced file.
                        if dest.is_file() and base.sha256_file(dest) == result["sha256"]:
                            dest.unlink()
                        raise base.PilotError("input media changed during crop")
                    candidate.update(status="cropped", output=result)
                    candidate.pop("reason", None)
                except (PendingSource, verification.ReplayUncertain, aligned.AlignmentUncertain) as exc:
                    candidate.update(status="pending", reason=str(exc))
                except (base.PilotError, OSError, ValueError) as exc:
                    candidate.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
                save()
        for source in admitted.values():
            if (base.sha256_file(root / source["source_path"]) != source["source_sha256"]
                or base.sha256_file(root / source["roi_path"]) != source["roi_sha256"]):
                raise base.PilotError("input media changed during run")
        if any(base.sha256_file(root / relative) != digest for relative, digest in hashes.items()):
            raise base.PilotError("metadata inputs changed during run")
        if anchor_document_sha is None and anchor_path.exists():
            raise base.PilotError("phenomenon document appeared during run")
        if verification._code() != identity["code"]:
            raise base.PilotError("generation code changed during run")
        manifest["plan_only"] = bool(plan_only)
        manifest["complete"] = not plan_only and not any(s["status"] in {"pending", "failed"} for s in manifest["sources"]) and all(c["status"] == "cropped" for c in manifest["candidates"])
        save()
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--output-dir", type=Path, default=None, help="default: PROJECT_ROOT/data/sub_video")
    parser.add_argument("--fold", type=int, required=True, choices=(0, 1, 2), help="process only this fold's train members")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        manifest = run(args.project_root, args.output_dir, fold=args.fold, plan_only=args.plan_only, resume=args.resume)
    except (base.PilotError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(base.canonical_bytes(summarize(manifest)).decode(), end="")
    return 0 if args.plan_only or manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
