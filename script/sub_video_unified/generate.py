#!/usr/bin/env python3
"""Re-encode all 110 sources once into a single, unpublished candidate batch.

The three approved media strategies retain their own proof identities. This
orchestrator never imports media or receipts from an earlier output batch.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from script.sub_video import anchors, generate as legacy, verification as core
from script.sub_video_0093 import generate as special, verification as special_verification
from script.sub_video_supplement import generate as coverage, verification as coverage_verification
from script.subvideo_pilot import aligned, pilot as base

SCHEMA = "tensile-unified-sub-video/1"
SOURCE_COUNT = 110
COVERAGE_IDS = coverage.DEFAULT_IDS
MEDIA_FIELDS = ("duration", "total_frames", "fps", "width", "height", "time_base")
MUTABLE_CANDIDATE_FIELDS = {"status", "output", "reason", "details"}


def strategy_for(video_id):
    if video_id == "video_0093":
        return "0093"
    return "coverage" if video_id in COVERAGE_IDS else "regular"


def code_identity():
    """Pin orchestration as well as every imported generator/verifier/loader."""
    script = Path(__file__).resolve().parents[1]
    packages = ("sub_video_unified", "sub_video", "sub_video_all", "sub_video_0093",
                "sub_video_supplement", "subvideo_pilot")
    return {str(p.relative_to(script)): base.sha256_file(p)
            for name in packages for p in sorted((script / name).glob("*.py"))}


def load_inputs(root):
    # This helper independently checks all seven member lists, annotations and
    # ROI records. Its parent-manifest-dependent run/check functions are unused.
    rows, rois, folds, hashes, loader_code = coverage._verified_inputs(root)
    if (len(rows) != SOURCE_COUNT or set(rows) != set(rois) or set(rows) != set(folds)
        or not set(COVERAGE_IDS) <= set(rows) or "video_0093" not in rows):
        raise base.PilotError("unified input inventory must contain exactly 110 approved sources")
    if folds["video_0093"] != {str(i): "test" for i in range(3)}:
        raise base.PilotError("video_0093 must remain in fixed test")
    return rows, rois, folds, hashes, loader_code


def identity(root, hashes, loader_code):
    hashes = dict(hashes)
    hashes[anchors.DOCUMENT] = base.sha256_file(root / anchors.DOCUMENT)
    return {"schema": SCHEMA, "inputs": hashes, "code": code_identity(),
            "loader_code": loader_code, "scope": "all_sources", "source_count": SOURCE_COUNT,
            "coverage_ids": list(COVERAGE_IDS), "window_seconds": 20, "step_seconds": 15,
            "guard_seconds": .5, "post_remaining_seconds": 2.0,
            "policy": "fresh_encoding_only_no_donor_batches"}


def _unchanged(root, expected):
    if (code_identity() != expected["code"]
        or coverage.inputs.orchestration_code() != expected["loader_code"]
        or any(not (root / p).is_file() or base.sha256_file(root / p) != sha
               for p, sha in expected["inputs"].items())):
        raise base.PilotError("unified metadata or source code changed during run")


def _scope(folds):
    return "test" if folds["0"] == "test" else "development"


def _paths(root, video_id):
    return root / "data/videos" / (video_id + ".mp4"), root / "data/roi/videos" / (video_id + ".mp4")


def _backend(strategy):
    if strategy == "0093":
        return special, special_verification
    if strategy == "coverage":
        return coverage, coverage_verification
    if strategy == "regular":
        return legacy, core
    raise base.PilotError("unknown unified source strategy")


def _expected_candidates(key, row, folds, raw_media, source_sha, roi_sha, anchor_records):
    """Replan entirely from current inputs; never trust a stored candidate list."""
    strategy = strategy_for(key)
    if strategy == "coverage":
        candidates = []
        for sequence, window in enumerate(coverage.plan_windows(raw_media), 1):
            name = f"{key}_coverage_{sequence:02d}"
            candidates.append(dict(window, candidate_id=name, filename=name + ".mp4",
                source_video_id=key, scope=_scope(folds), folds=folds, role="coverage", sequence=sequence,
                output_path=f"videos/{name}.mp4", source_sha256=source_sha, roi_sha256=roi_sha,
                source_labels=legacy._source_labels(row), candidate_labels=None, final_labels=None,
                labels_status="unreviewed", manual_review="required",
                review={"status": "未审核", "decision": None, "change_notes": ""}, status="planned"))
        return candidates, []
    record = legacy.adapt_annotation(row, raw_media, phenomenon_anchor=anchor_records.get(key))
    if strategy == "0093" and record.get("anchor_frames") != [727, 728]:
        raise legacy.PendingSource("0093 requires the approved 727/728 source anchors")
    planner = special.plan_windows if strategy == "0093" else legacy.plan_windows
    windows, excluded = planner(record, raw_media)
    candidates = legacy._name_candidates(windows, row, folds, source_sha, roi_sha)
    for candidate in candidates:
        candidate.update(source_anchor_frames=record["anchor_frames"], scope=_scope(folds))
    return candidates, [dict(w, source_video_id=key) for w in excluded]


def _plan_source(root, key, row, roi, folds, anchor_records):
    """Admit one source only after its complete source-to-ROI replay passes."""
    strategy = strategy_for(key)
    source = {"video_id": key, "strategy": strategy, "source_annotation": row,
              "folds": folds, "scope": _scope(folds)}
    raw, cropped = _paths(root, key)
    try:
        if roi.get("status") != "success":
            raise legacy.PendingSource("ROI不可用")
        source_sha, roi_sha = base.sha256_file(raw), base.sha256_file(cropped)
        if (source_sha != roi.get("source", {}).get("sha256")
            or roi_sha != roi.get("output", {}).get("sha256")
            or source_sha != roi.get("decision", {}).get("source_sha256")):
            raise legacy.PendingSource("源视频、ROI或裁剪决定身份不一致")
        raw_media, roi_media = aligned.probe_video(raw), aligned.probe_video(cropped)
        candidates, excluded = _expected_candidates(key, row, folds, raw_media, source_sha, roi_sha, anchor_records)
        source_verifier = special_verification if strategy == "0093" else core
        proof = source_verifier.verify_source_replay(raw, cropped, roi, source_annotation=row,
                                                     phenomenon_anchor=anchor_records.get(key))
        if raw_media["total_frames"] != roi_media["total_frames"]:
            raise legacy.PendingSource("源视频与ROI帧数不一致")
        if not candidates:
            raise legacy.PendingSource("没有满足时间边界和素材要求的窗口")
        source.update(status="planned", source_path=str(raw.relative_to(root)),
            roi_path=str(cropped.relative_to(root)), source_sha256=source_sha, roi_sha256=roi_sha,
            roi_media=roi_media, frame_preserving_replay=proof)
        return source, candidates, excluded
    except (base.SkipSource, aligned.AlignmentUncertain, FileNotFoundError) as exc:
        source.update(status="pending", reason=str(exc), details=getattr(exc, "details", {}))
    except (base.PilotError, ValueError, KeyError, TypeError, OSError) as exc:
        source.update(status="failed", reason=f"{type(exc).__name__}: {exc}", details=getattr(exc, "details", {}))
    return source, [], []


def _sealed(receipt, schema, expected_code, expected_toolchain):
    if not isinstance(receipt, dict):
        raise base.PilotError("missing replay proof")
    raw = dict(receipt)
    seal = raw.pop("receipt_sha256", None)
    if (receipt.get("schema") != schema or receipt.get("status") != core.VERIFIED
        or seal != core._digest(raw) or receipt.get("code") != expected_code
        or receipt.get("toolchain") != expected_toolchain):
        raise base.PilotError("replay proof seal, schema, code or toolchain mismatch")


def _portable_anchor(anchor):
    return {k: v for k, v in anchor.items() if k != "document_path"} if isinstance(anchor, dict) else anchor


def _validate_source(root, source, row, roi, anchor_records, *, portable=False):
    key = source["video_id"]
    raw, cropped = _paths(root, key)
    verifier = special_verification if strategy_for(key) == "0093" else core
    proof = source["frame_preserving_replay"]
    _sealed(proof, verifier.SOURCE_SCHEMA, verifier._code(), proof.get("toolchain") if portable else verifier._toolchain())
    source_sha, roi_sha = base.sha256_file(raw), base.sha256_file(cropped)
    if (source.get("source_path") != str(raw.relative_to(root))
        or source.get("roi_path") != str(cropped.relative_to(root))
        or source.get("source_sha256") != source_sha or source.get("roi_sha256") != roi_sha
        or (not portable and (proof.get("source_path") != str(raw.resolve()) or proof.get("roi_path") != str(cropped.resolve())))
        or proof.get("video_id") != key or proof.get("source_sha256") != source_sha
        or proof.get("roi_sha256") != roi_sha or proof.get("reference_sha256") != roi_sha
        or proof.get("roi_record_sha256") != core._digest(roi)
        or proof.get("decision_sha256") != core._digest(roi.get("decision", {}))
        or proof.get("source_annotation") != row or proof.get("source_annotation_sha256") != core._digest(row)
        or _portable_anchor(proof.get("phenomenon_anchor")) != _portable_anchor(anchor_records.get(key))
        or (not portable and proof.get("phenomenon_anchor") != anchor_records.get(key))
        or proof.get("phenomenon_anchor_sha256") != (core._digest(proof["phenomenon_anchor"]) if proof.get("phenomenon_anchor") else None)):
        raise base.PilotError("source proof/media/annotation/ROI identity mismatch: " + key)
    if not portable:
        verifier._validate_phenomenon_anchor(proof.get("phenomenon_anchor"), row, source_sha,
                                            proof["source_decode"]["frame_count"])
    raw_media, roi_media = aligned.probe_video(raw), aligned.probe_video(cropped)
    if source.get("roi_media") != roi_media:
        raise base.PilotError("recorded ROI media differs from current media: " + key)
    for name, media in (("source_decode", raw_media), ("roi_decode", roi_media)):
        decoded = proof[name]
        if (decoded["frame_count"] != media["total_frames"]
            or len(decoded["normalized_pts"]) != len(media["timestamps"])
            or any(abs(Fraction(t) - Fraction(str(actual))) > Fraction(1, 1000000)
                   for t, actual in zip(decoded["normalized_pts"], media["timestamps"]))
            or abs(Fraction(decoded["usable_end"]) - Fraction(str(media["duration"]))) > Fraction(1, 1000000)):
            raise base.PilotError("bound replay timeline differs from current media: " + key)
    if strategy_for(key) == "0093":
        evidence = proof["source_decode"].get("presentation_evidence", {})
        if (source_sha != special_verification.APPROVED_SOURCE_SHA256
            or raw_media["total_frames"] != 733 or evidence.get("declared_frame_count") != 771
            or evidence.get("presented_frame_count") != 733 or evidence.get("discarded_preroll_frames") != 38):
            raise base.PilotError("0093 presentation/preroll identity mismatch")
    return raw_media


def _logical(candidate, *, portable=False):
    value = {k: v for k, v in candidate.items() if k not in MUTABLE_CANDIDATE_FIELDS}
    if portable and "phenomenon_anchor" in value:
        value["phenomenon_anchor"] = _portable_anchor(value["phenomenon_anchor"])
    return value


def _receipt_window(candidate, proof):
    """Derive receipt fields without reopening the original machine's paths."""
    start, end = candidate["start_frame"], candidate["end_frame"]
    pts = proof["source_decode"]["normalized_pts"]
    bounds = [Fraction(t) for t in pts] + [Fraction(proof["source_decode"]["usable_end"])]
    if candidate["event_kind"] == "none_unlocated":
        return {"source_frame_range": [start, end], "source_start_pts": str(bounds[start]),
            "source_end_pts": str(bounds[end]), "event_kind": "none_unlocated", "source_anchor_frames": [],
            "target_duration_seconds": 20, "step_seconds": 15}
    unclamped = candidate["event_kind"] == "unclamped"
    return {"annotation_sha256": proof["source_annotation_sha256"], "event_kind": candidate["event_kind"],
        "phenomenon_anchor_sha256": proof.get("phenomenon_anchor_sha256"),
        "source_anchor_frames": candidate["source_anchor_frames"], "source_frame_range": [start, end],
        "guard_seconds": None if unclamped else .5, "post_remaining_seconds": None if unclamped else 2.0,
        "source_start_pts": str(bounds[start]), "source_end_pts": str(bounds[end])}


def _validate_output(root, output, candidate, source, *, portable=False):
    """Check the sealed independent select proof and fully decode current bytes."""
    _, verifier = _backend(source["strategy"])
    proof = source["frame_preserving_replay"]
    roi_path = root / source["roi_path"]
    expected_window = _receipt_window(candidate, proof) if portable else verifier.validate_source_receipt(proof, roi_path, candidate)
    record = candidate["output"]
    clip = record["frame_preserving_replay"]
    schema = coverage_verification.SCHEMA if source["strategy"] == "coverage" else verifier.CLIP_SCHEMA
    _sealed(clip, schema, proof["code"], proof["toolchain"])
    if source["strategy"] == "coverage" and clip.get("supplement_code") != coverage_verification.code():
        raise base.PilotError("coverage clip proof code mismatch")
    path = output / candidate["output_path"]
    if not path.is_file() or path.is_symlink():
        raise base.PilotError("recorded clip missing or symlinked: " + candidate["candidate_id"])
    actual_sha = base.sha256_file(path)
    expected_anchors = [{"source_frame": i, "roi_frame": i, "output_frame": i-candidate["start_frame"]}
        for i in candidate["source_anchor_frames"] if candidate["start_frame"] <= i < candidate["end_frame"]]
    # Probe current metadata in both modes; portable mode skips RGB decoding.
    # A different decoder/toolchain must not be advertised as equivalent replay.
    media = aligned.probe_video(path)
    if portable:
        decoded = {"frame_count": clip["decoded_frame_count"],
                   "frame_sequence_sha256": clip["decoded_RGB_PTS_sequence_sha256"]}
    else:
        decoder = core if source["strategy"] == "coverage" else verifier
        decoded = decoder._decode_rgb(path, decoder._stream_info(path))
    if (record.get("sha256") != actual_sha or clip.get("output_sha256") != actual_sha
        or clip.get("source_receipt_sha256") != proof["receipt_sha256"]
        or clip.get("source_sha256") != proof["source_sha256"] or clip.get("roi_sha256") != proof["roi_sha256"]
        or clip.get("proof_type") != "independent_absolute_select_replay_of_trim_output"
        or clip.get("window") != expected_window or clip.get("anchors") != expected_anchors
        or clip.get("decoded_frame_count") != candidate["end_frame"]-candidate["start_frame"]
        or decoded["frame_count"] != clip.get("decoded_frame_count")
        or decoded["frame_sequence_sha256"] != clip.get("decoded_RGB_PTS_sequence_sha256")
        or record.get("media") != {k: media[k] for k in MEDIA_FIELDS}
        or record.get("full_decode") != "passed"
        or record.get("frame_mapping") != {"source_start_frame": candidate["start_frame"], "output_start_frame": 0, "anchors": expected_anchors}
        or "reuse_provenance" in record):
        raise base.PilotError("clip proof, decoded bytes or frame mapping mismatch: " + candidate["candidate_id"])


def _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records, *, require_complete=False, portable=False):
    if manifest.get("schema") != SCHEMA or manifest.get("published") is not False:
        raise base.PilotError("unified manifest schema/publication status mismatch")
    sources = {s["video_id"]: s for s in manifest["sources"]}
    if len(sources) != len(manifest["sources"]) or not set(sources) <= set(rows):
        raise base.PilotError("duplicate or unexpected unified source")
    if require_complete and set(sources) != set(rows):
        raise base.PilotError("unified source inventory does not cover all 110 sources")
    expected, excluded = [], []
    for key, source in sources.items():
        if (source.get("strategy") != strategy_for(key) or source.get("scope") != _scope(folds[key])
            or source.get("folds") != folds[key] or source.get("source_annotation") != rows[key]):
            raise base.PilotError("source strategy, fixed split or annotation mismatch: " + key)
        if source.get("status") != "planned":
            if source.get("status") not in {"pending", "failed"} or not source.get("reason"):
                raise base.PilotError("invalid source status/reason: " + key)
            if require_complete:
                raise base.PilotError("source has no admitted frame proof: " + key + ": " + source["reason"])
            continue
        media = _validate_source(root, source, rows[key], rois[key], anchor_records, portable=portable)
        cs, es = _expected_candidates(key, rows[key], folds[key], media,
            source["source_sha256"], source["roi_sha256"], anchor_records)
        if not cs:
            raise base.PilotError("admitted source has no approved windows: " + key)
        expected.extend(cs)
        excluded.extend(es)
    candidates = manifest["candidates"]
    by_id = {c["candidate_id"]: c for c in candidates}
    if (len(by_id) != len(candidates) or set(by_id) != {c["candidate_id"] for c in expected}
        or manifest["excluded_windows"] != excluded):
        raise base.PilotError("unified candidate/excluded-window inventory mismatch")
    for planned in expected:
        candidate = by_id[planned["candidate_id"]]
        if _logical(candidate, portable=portable) != _logical(planned, portable=portable):
            raise base.PilotError("candidate window, labels, review or split fields changed: " + planned["candidate_id"])
        if candidate.get("status") == "cropped":
            _validate_output(root, output, candidate, sources[candidate["source_video_id"]], portable=portable)
        elif (candidate.get("status") not in {"planned", "pending", "failed"}
              or "output" in candidate or (candidate["status"] != "planned" and not candidate.get("reason"))):
            raise base.PilotError("invalid candidate status or failure reason")
        elif require_complete:
            raise base.PilotError("expected clip has not passed independent replay: " + candidate["candidate_id"])
    videos = output / "videos"
    if videos.is_symlink() or (videos.exists() and not videos.is_dir()):
        raise base.PilotError("unsafe output videos directory")
    disk = {str(p.relative_to(output)) for p in videos.iterdir()} if videos.exists() else set()
    recorded = {c["output_path"] for c in candidates if c["status"] == "cropped"}
    if disk != recorded:
        raise base.PilotError("output contains missing, unrecorded or unexpected clip files")
    if require_complete and (manifest.get("complete") is not True or manifest.get("plan_only") is not False):
        raise base.PilotError("unified batch is not complete")
    return len(recorded)


def _safe_output(root, requested):
    candidate = root / "data/sub_video" if requested is None else Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise base.PilotError("output directory must not be a symlink")
    output = candidate.resolve()
    protected = [root / name for name in ("data/videos", "data/roi", "data/splits", "data/source",
        "data/annotation", "data/annotation-table-full.csv", "script", "docs", ".git")]
    protected += [p.resolve() for p in protected]
    if output == root or any(output == p or p in output.parents or output in p.parents for p in protected):
        raise base.PilotError("unified output overlaps protected inputs or source code")
    return output


def summarize(manifest):
    candidates, sources = manifest["candidates"], manifest["sources"]
    return {"scope": "all_sources", "source_count": len(sources),
        "source_status": dict(Counter(s["status"] for s in sources)),
        "source_reasons": dict(Counter(s["reason"] for s in sources if s.get("reason"))),
        "strategies": dict(Counter(s["strategy"] for s in sources)),
        "candidate_count": len(candidates), "candidate_status": dict(Counter(c["status"] for c in candidates)),
        "roles": dict(Counter(c["role"] for c in candidates)),
        "excluded_windows": len(manifest["excluded_windows"]),
        "split_counts": {scope: sum(c["scope"] == scope for c in candidates) for scope in ("development", "test")},
        "fold_counts": {str(i): {part: sum(c["folds"][str(i)] == part for c in candidates)
            for part in ("train", "val", "test")} for i in range(3)},
        "complete": manifest["complete"], "published": False, "reused_candidates": 0,
        "manual_review": "required_for_every_publishable_clip"}


def run(project_root, output_dir=None, *, plan_only=False, resume=False):
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    rows, rois, folds, hashes, loader_code = load_inputs(root)
    expected_identity = identity(root, hashes, loader_code)
    anchor_records = anchors.load_anchors(root / anchors.DOCUMENT)
    with base._run_lock(output):
        if output.exists() and any(output.iterdir()):
            if not resume:
                raise base.PilotError("nonempty output exists; choose an empty directory or explicit --resume")
            manifest = base._load(output / "manifest.json")
            if manifest.get("identity") != expected_identity:
                raise base.PilotError("unified resume metadata/code identity differs")
            _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records)
        else:
            if resume:
                raise base.PilotError("cannot resume a missing or empty unified output")
            output.mkdir(parents=True, exist_ok=True)
            manifest = {"schema": SCHEMA, "identity": expected_identity, "sources": [], "candidates": [],
                        "excluded_windows": [], "complete": False, "published": False, "plan_only": bool(plan_only)}
        (output / "videos").mkdir(exist_ok=True)

        def save():
            base._atomic_json(output / "manifest.json", manifest)
            base._atomic_json(output / "summary.json", summarize(manifest))

        save()
        source_indexes = {s["video_id"]: i for i, s in enumerate(manifest["sources"])}
        for key in sorted(rows):
            index = source_indexes.get(key)
            previous = manifest["sources"][index] if index is not None else None
            if previous is not None:
                if previous["status"] not in {"pending", "failed"}:
                    continue
                # A failed admission can be retried; an admitted source or any
                # source with planned/generated clips must never be regenerated.
                if any(c["source_video_id"] == key for c in manifest["candidates"]):
                    raise base.PilotError("cannot retry a source with existing candidates: " + key)
            _unchanged(root, expected_identity)
            source, candidates, excluded = _plan_source(root, key, rows[key], rois[key], folds[key], anchor_records)
            _unchanged(root, expected_identity)
            if previous is None:
                source_indexes[key] = len(manifest["sources"])
                manifest["sources"].append(source)
            else:
                source["previous_failures"] = list(previous.get("previous_failures", [])) + [
                    {k: previous[k] for k in ("status", "reason", "details") if k in previous}]
                manifest["sources"][index] = source
            manifest["candidates"].extend(candidates)
            manifest["excluded_windows"].extend(excluded)
            # Insert newly admitted windows at the original source position.
            # Stable sorting preserves every existing source's window order.
            manifest["candidates"].sort(key=lambda c: source_indexes[c["source_video_id"]])
            manifest["excluded_windows"].sort(key=lambda w: source_indexes[w["source_video_id"]])
            save()
        # Reconstruct the entire approved schedule before any clip is encoded.
        _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records)
        sources = {s["video_id"]: s for s in manifest["sources"]}
        if not plan_only:
            for candidate in manifest["candidates"]:
                if candidate["status"] == "cropped":
                    continue  # Already audited above; this is this run's own output.
                destination = output / candidate["output_path"]
                if destination.exists() or destination.is_symlink():
                    raise base.PilotError("unrecorded output exists; refusing overwrite")
                source = sources[candidate["source_video_id"]]
                generator, _ = _backend(source["strategy"])
                try:
                    _unchanged(root, expected_identity)
                    result = generator.crop_video(root / source["roi_path"], destination, candidate,
                        source["roi_media"], source["frame_preserving_replay"])
                    try:
                        _unchanged(root, expected_identity)
                        raw, roi_path = _paths(root, source["video_id"])
                        if (base.sha256_file(raw) != source["source_sha256"]
                            or base.sha256_file(roi_path) != source["roi_sha256"]):
                            raise base.PilotError("source or ROI changed during clip encoding")
                    except BaseException:
                        if destination.is_file() and not destination.is_symlink() and base.sha256_file(destination) == result["sha256"]:
                            destination.unlink()
                        raise
                    candidate.update(status="cropped", output=result)
                    candidate.pop("reason", None)
                    candidate.pop("details", None)
                except (base.SkipSource, aligned.AlignmentUncertain) as exc:
                    candidate.update(status="pending", reason=str(exc), details=getattr(exc, "details", {}))
                except (base.PilotError, OSError, ValueError) as exc:
                    candidate.update(status="failed", reason=f"{type(exc).__name__}: {exc}", details=getattr(exc, "details", {}))
                save()
        _unchanged(root, expected_identity)
        _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records)
        manifest["plan_only"] = bool(plan_only)
        manifest["complete"] = (not plan_only and set(sources) == set(rows)
            and all(s["status"] == "planned" for s in sources.values())
            and all(c["status"] == "cropped" for c in manifest["candidates"]))
        save()
        return manifest


def audit_outputs(project_root, output_dir, *, portable=False):
    """Independently replan all sources and verify all current outputs and proofs.

    This checks existing technical evidence against current bytes. It does not
    convert technical proof into human review or publication approval.
    """
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    with base._run_lock(output):
        manifest = base._load(output / "manifest.json")
        rows, rois, folds, hashes, loader_code = load_inputs(root)
        expected_identity = identity(root, hashes, loader_code)
        if manifest.get("identity") != expected_identity:
            raise base.PilotError("unified audit metadata/code identity differs")
        anchor_records = anchors.load_anchors(root / anchors.DOCUMENT)
        verified = _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records,
                                      require_complete=True, portable=portable)
        if base._load(output / "summary.json") != summarize(manifest):
            raise base.PilotError("unified summary differs from current manifest")
        _unchanged(root, expected_identity)
        return {"status": "current_bytes_and_planned_inventory_verified", "source_count": len(rows),
                "verified_outputs": verified, "published": False,
                "validation_level": "byte_receipt_and_source_timeline_only" if portable else "full_output_decode_and_current_receipts",
                "limitations": (["no_current_output_RGB_PTS_decode", "original_toolchain_receipts_preserved"] if portable else [])
                    + ["not_new_frame_replay", "not_human_label_review", "not_data_publication"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, help="default: PROJECT_ROOT/data/sub_video")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--portable-audit", action="store_true", help="read-only audit after copying outputs; no claim of current RGB replay")
    args = parser.parse_args()
    if args.portable_audit and not args.audit_only:
        parser.error("--portable-audit requires --audit-only")
    if args.audit_only and (args.plan_only or args.resume):
        parser.error("--audit-only cannot be combined with --plan-only or --resume")
    try:
        if args.audit_only:
            result = audit_outputs(args.project_root, args.output_dir or args.project_root / "data/sub_video", portable=args.portable_audit)
            print(base.canonical_bytes(result).decode(), end="")
            return 0
        manifest = run(args.project_root, args.output_dir, plan_only=args.plan_only, resume=args.resume)
    except (base.PilotError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(base.canonical_bytes(summarize(manifest)).decode(), end="")
    return 0 if args.plan_only or manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
