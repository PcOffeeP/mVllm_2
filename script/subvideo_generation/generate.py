#!/usr/bin/env python3
"""Re-encode all 110 sources once into a single, unpublished candidate batch.

The three approved media strategies retain their own proof identities. This
orchestrator never imports media or receipts from an earlier output batch.

``--verification`` decides how much frame evidence a batch records: ``full``
replays source and clip frames, ``basic`` (the default) only checks the encoded
output, ``none`` skips even that probe. Only ``full`` proves frame
correspondence; the fast modes record ``verification.frame_replay = "skipped"``
and leave frame-level checking to the human clip review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import concurrent.futures
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from script.subvideo_generation._legacy.core import anchors, generate as legacy, verification as core
from script.subvideo_generation._legacy.special import generate as special, verification as special_verification
from script.subvideo_generation._legacy.coverage import generate as coverage, verification as coverage_verification
from script.subvideo_generation.pilot import aligned, pilot as base
from script.subvideo_generation import rules as rules_registry
from script.subvideo_generation import virtual

SCHEMA = "tensile-unified-sub-video/1"
SOURCE_COUNT = 110
MEDIA_FIELDS = ("duration", "total_frames", "fps", "width", "height", "time_base")
MUTABLE_CANDIDATE_FIELDS = {"status", "output", "reason", "details"}
# ``full`` replays frames in both directions, ``basic`` keeps the output probe,
# ``none`` keeps the encoded bytes only. A batch records which one produced it.
VERIFICATION_MODES = ("full", "basic", "none")
DEFAULT_VERIFICATION = "basic"
VERIFICATION_REASON = aligned.FAST_VERIFICATION_REASON


def _verification_note(mode):
    """The honest record every fast-mode layer carries: what was skipped and why."""
    return {"mode": mode, "frame_replay": "skipped", "reason": VERIFICATION_REASON}


def _manifest_mode(manifest):
    """The mode a batch was written under; a manifest without the block is ``full``."""
    if "verification" not in manifest:
        return "full"
    record = manifest["verification"]
    mode = record.get("mode") if isinstance(record, dict) else None
    if mode not in VERIFICATION_MODES:
        raise base.PilotError("batch verification record is not a known mode")
    return mode


def _planned_frame_mapping(candidate):
    """The frame correspondence planning already decided; no decode is involved."""
    start, end = candidate["start_frame"], candidate["end_frame"]
    return {"source_start_frame": start, "output_start_frame": 0,
            "anchors": [{"source_frame": i, "roi_frame": i, "output_frame": i - start}
                        for i in candidate["source_anchor_frames"] if start <= i < end]}


def strategy_for(video_id, row):
    """Route one source: the special id first, then the annotation's coverage criterion."""
    if video_id == rules_registry.SPECIAL_VIDEO_ID:
        return "0093"
    return "coverage" if rules_registry.is_coverage_source(row) else "regular"


def code_identity():
    """Hash the orchestration and every imported generator/verifier/loader.

    Information only: batch equality is decided by the input identity plus the
    rules fingerprint (rules.py), never by these hashes. The function is kept
    because reports and older tooling still print it, and because it documents
    which files a batch of this generation touched.

    ``virtual.py`` is deliberately excluded: the videos-dir mode records its own
    identity in its own manifest, so it must not move this informational digest.
    """
    script = Path(__file__).resolve().parents[1]
    packages = ("subvideo_generation", "subvideo_generation/_legacy",
                "subvideo_generation/_legacy/core", "subvideo_generation/_legacy/special",
                "subvideo_generation/_legacy/coverage", "subvideo_generation/_legacy/all_sources",
                "subvideo_generation/pilot")
    return {str(p.relative_to(script)): base.sha256_file(p)
            for name in packages for p in sorted((script / name).glob("*.py"))
            if str(p.relative_to(script)) != "subvideo_generation/virtual.py"}


def load_inputs(root):
    # This helper independently checks all seven member lists, annotations and
    # ROI records. Its parent-manifest-dependent run/check functions are unused.
    rows, rois, folds, hashes, loader_code = coverage._verified_inputs(root)
    if (len(rows) != SOURCE_COUNT or set(rows) != set(rois) or set(rows) != set(folds)
        or rules_registry.SPECIAL_VIDEO_ID not in rows):
        raise base.PilotError("unified input inventory must contain exactly 110 approved sources")
    if folds[rules_registry.SPECIAL_VIDEO_ID] != {str(i): "test" for i in range(3)}:
        raise base.PilotError("the special source must remain in fixed test")
    return rows, rois, folds, hashes, loader_code


def identity(root, hashes):
    """The batch identity: what was read (inputs) and how it was cut (rules).

    Only ``inputs`` and ``rules.digest`` decide whether two batches are the same
    batch; ``info`` records the environment for humans and is never compared.
    """
    inputs = dict(hashes)
    inputs[anchors.DOCUMENT] = base.sha256_file(root / anchors.DOCUMENT)
    return {"schema": SCHEMA, "input_mode": "official", "inputs": inputs,
            "rules": rules_registry.stored_rules(), "info": _info(root)}


def _info(root):
    """Informative only: code revision and local toolchain, never a criterion."""
    return {"code_version": _code_version(root), "toolchain": _toolchain_info()}


def _code_version(root):
    """Short commit of the checkout, when git is available; ``None`` otherwise."""
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root),
                                capture_output=True, text=True, check=False)
    except (OSError, ValueError):
        return None
    revision = result.stdout.strip()
    return revision or None if result.returncode == 0 else None


def _degraded_toolchain():
    return {"degraded": True, "equivalent_to_verified_toolchain": False,
            "ffmpeg": {}, "ffprobe": {}}


def _normalized_toolchain(status):
    """Give an arbitrary toolchain report the four documented keys."""
    normalized = dict(status) if isinstance(status, dict) else {}
    if "degraded" not in normalized:
        normalized["degraded"] = not bool(normalized.get("equivalent_to_verified_toolchain"))
    normalized.setdefault("equivalent_to_verified_toolchain", not bool(normalized["degraded"]))
    normalized.setdefault("ffmpeg", {})
    normalized.setdefault("ffprobe", {})
    return normalized


def _toolchain_status():
    """The replay toolchain verdict, never raising and never deciding a batch.

    A missing or unprobeable toolchain degrades to "not equivalent" instead of
    failing the run: the point is to state honestly which environment produced
    the evidence, not to gate on it.
    """
    try:
        status = core._toolchain()
    except (core.ReplayUncertain, OSError):
        return _degraded_toolchain()
    return _normalized_toolchain(status)


def _toolchain_info():
    """Recorded in the identity's info block: context only, never a criterion."""
    return _toolchain_status()


def _recorded_toolchain(manifest):
    """The toolchain block as it was written into the batch, not as it is now."""
    identity = manifest.get("identity") or {}
    info = identity.get("info") or {}
    recorded = info.get("toolchain")
    return _normalized_toolchain(recorded) if isinstance(recorded, dict) else _degraded_toolchain()


def _compare_identity(identity):
    """Projection of an identity onto the only fields that decide batch equality."""
    rules = identity.get("rules") or {}
    return {"schema": identity.get("schema"), "input_mode": identity.get("input_mode"),
            "inputs": identity.get("inputs"), "rules_digest": rules.get("digest")}


def _has_rules(manifest):
    identity = manifest.get("identity") or {}
    return isinstance(identity.get("rules"), dict) and bool(identity["rules"].get("digest"))


def _check_identity(recorded, expected):
    have, want = _compare_identity(recorded), _compare_identity(expected)
    if have["rules_digest"] != want["rules_digest"]:
        raise base.PilotError("rules digest differs: the generation rules changed since this batch was written")
    if (have["schema"], have["input_mode"], have["inputs"]) != (want["schema"], want["input_mode"], want["inputs"]):
        raise base.PilotError("input identity differs: the inputs, batch schema or input mode changed")


def _unchanged(root, expected):
    if (rules_registry.digest() != expected["rules"]["digest"]
        or any(not (root / p).is_file() or base.sha256_file(root / p) != sha
               for p, sha in expected["inputs"].items())):
        raise base.PilotError("inputs or generation rules changed during run")


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


def _expected_candidates(key, row, folds, raw_media, source_sha, roi_sha, anchor_records, *,
                         verification=DEFAULT_VERIFICATION):
    """Replan entirely from current inputs; never trust a stored candidate list."""
    strategy = strategy_for(key, row)
    if strategy == "coverage":
        candidates = []
        for sequence, window in enumerate(coverage.plan_windows(raw_media), 1):
            name = f"{key}_coverage_{sequence:02d}"
            # The coverage initial labels are derived here from the source labels; the
            # archived verifier reads the same rule off the legacy producer, and the two
            # must stay field-for-field equal (pinned by
            # test_coverage_candidate_labels_agree_with_the_producer and
            # test_coverage_candidate_labels_match_the_producer_from_the_same_starting_point).
            candidates.append(dict(window, candidate_id=name, filename=name + ".mp4",
                source_video_id=key, scope=_scope(folds), folds=folds, role="coverage", sequence=sequence,
                output_path=f"videos/{name}.mp4", source_sha256=source_sha, roi_sha256=roi_sha,
                # Two independent _source_labels() calls on purpose: the rule rewrites the
                # dict it is given in place, so a shared local would silently overwrite
                # source_labels with the candidate's initial labels.
                source_labels=legacy._source_labels(row),
                candidate_labels=rules_registry.coverage_candidate_labels(legacy._source_labels(row), row),
                final_labels=None, labels_status="unreviewed", manual_review="required",
                review={"status": "未审核", "decision": None, "change_notes": ""}, status="planned"))
        if verification != "full":
            for candidate in candidates:
                candidate["verification"] = _verification_note(verification)
        return candidates, []
    record = legacy.adapt_annotation(row, raw_media, phenomenon_anchor=anchor_records.get(key))
    if (strategy == "0093"
            and record.get("anchor_frames") != list(rules_registry.SPECIAL_ANCHOR_FRAMES)):
        raise legacy.PendingSource("0093 requires the approved 727/728 source anchors")
    planner = special.plan_windows if strategy == "0093" else legacy.plan_windows
    windows, excluded = planner(record, raw_media)
    candidates = legacy._name_candidates(windows, row, folds, source_sha, roi_sha)
    for candidate in candidates:
        candidate.update(source_anchor_frames=record["anchor_frames"], scope=_scope(folds))
        if verification != "full":
            candidate["verification"] = _verification_note(verification)
    return candidates, [dict(w, source_video_id=key) for w in excluded]


def _plan_source(root, key, row, roi, folds, anchor_records, verification=DEFAULT_VERIFICATION):
    """Admit one source; ``full`` replays it, a fast mode binds identities only."""
    strategy = strategy_for(key, row)
    source = {"video_id": key, "strategy": strategy, "source_annotation": row,
              "folds": folds, "scope": _scope(folds)}
    if verification != "full":
        source["verification"] = _verification_note(verification)
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
        candidates, excluded = _expected_candidates(key, row, folds, raw_media, source_sha, roi_sha, anchor_records,
                                                    verification=verification)
        proof = None
        if verification == "full":
            source_verifier = special_verification if strategy == "0093" else core
            proof = source_verifier.verify_source_replay(raw, cropped, roi, source_annotation=row,
                                                        phenomenon_anchor=anchor_records.get(key))
        if raw_media["total_frames"] != roi_media["total_frames"]:
            raise legacy.PendingSource("源视频与ROI帧数不一致")
        if not candidates:
            raise legacy.PendingSource("没有满足时间边界和素材要求的窗口")
        source.update(status="planned", source_path=str(raw.relative_to(root)),
            roi_path=str(cropped.relative_to(root)), source_sha256=source_sha, roi_sha256=roi_sha,
            roi_media=roi_media)
        if verification == "full":
            source["frame_preserving_replay"] = proof
        return source, candidates, excluded
    except (base.SkipSource, aligned.AlignmentUncertain, FileNotFoundError) as exc:
        source.update(status="pending", reason=str(exc), details=getattr(exc, "details", {}))
    except (base.PilotError, ValueError, KeyError, TypeError, OSError) as exc:
        source.update(status="failed", reason=f"{type(exc).__name__}: {exc}", details=getattr(exc, "details", {}))
    return source, [], []


def _sealed(receipt, schema):
    """Check a receipt's own seal and schema.

    The recorded ``code`` and ``toolchain`` are history: they explain how a clip
    was produced, but a different build or a newer FFmpeg must not turn an
    already written proof into a lie. Only the seal (tamper evidence), the
    schema and the verified status are gates.
    """
    if not isinstance(receipt, dict):
        raise base.PilotError("missing replay proof")
    raw = dict(receipt)
    seal = raw.pop("receipt_sha256", None)
    if (receipt.get("schema") != schema or receipt.get("status") != core.VERIFIED
        or seal != core._digest(raw)):
        raise base.PilotError("replay proof seal or schema mismatch")


def _portable_anchor(anchor):
    return {k: v for k, v in anchor.items() if k != "document_path"} if isinstance(anchor, dict) else anchor


def _validate_fast_source(root, source, verification):
    """A fast batch bound identities; it promised no source frame replay."""
    key = source["video_id"]
    raw, cropped = _paths(root, key)
    note = source.get("verification") or {}
    if (note.get("mode") != verification or note.get("frame_replay") != "skipped"
        or "frame_preserving_replay" in source):
        raise base.PilotError("source verification record mismatch: " + key)
    if (source.get("source_path") != str(raw.relative_to(root))
        or source.get("roi_path") != str(cropped.relative_to(root))
        or source.get("source_sha256") != base.sha256_file(raw)
        or source.get("roi_sha256") != base.sha256_file(cropped)):
        raise base.PilotError("source media identity mismatch: " + key)
    raw_media, roi_media = aligned.probe_video(raw), aligned.probe_video(cropped)
    if source.get("roi_media") != roi_media:
        raise base.PilotError("recorded ROI media differs from current media: " + key)
    return raw_media


def _validate_source(root, source, row, roi, anchor_records, *, portable=False, verification=DEFAULT_VERIFICATION):
    if verification != "full":
        return _validate_fast_source(root, source, verification)
    key = source["video_id"]
    raw, cropped = _paths(root, key)
    verifier = special_verification if strategy_for(key, row) == "0093" else core
    proof = source["frame_preserving_replay"]
    _sealed(proof, verifier.SOURCE_SCHEMA)
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
    if strategy_for(key, row) == "0093":
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
            "target_duration_seconds": rules_registry.WINDOW_SECONDS, "step_seconds": rules_registry.STEP_SECONDS}
    unclamped = candidate["event_kind"] == "unclamped"
    return {"annotation_sha256": proof["source_annotation_sha256"], "event_kind": candidate["event_kind"],
        "phenomenon_anchor_sha256": proof.get("phenomenon_anchor_sha256"),
        "source_anchor_frames": candidate["source_anchor_frames"], "source_frame_range": [start, end],
        "guard_seconds": None if unclamped else .5, "post_remaining_seconds": None if unclamped else 2.0,
        "source_start_pts": str(bounds[start]), "source_end_pts": str(bounds[end])}


def _validate_fast_output(output, candidate, source, verification):
    """Check exactly what a fast batch promised: bytes, plan mapping, and (basic) media."""
    path = output / candidate["output_path"]
    if not path.is_file() or path.is_symlink():
        raise base.PilotError("recorded clip missing or symlinked: " + candidate["candidate_id"])
    record = candidate["output"]
    note = record.get("verification") or {}
    if (note.get("mode") != verification or note.get("frame_replay") != "skipped"
        or "frame_preserving_replay" in record or "reuse_provenance" in record
        or record.get("full_decode") == "passed"):
        raise base.PilotError("clip verification record mismatch: " + candidate["candidate_id"])
    if record.get("sha256") != base.sha256_file(path):
        raise base.PilotError("recorded clip bytes differ: " + candidate["candidate_id"])
    if record.get("frame_mapping") != _planned_frame_mapping(candidate):
        raise base.PilotError("clip frame mapping differs from the plan: " + candidate["candidate_id"])
    if verification == "none":
        # ``none`` never probes the encoded output, so it may not record media either.
        if "media" in record:
            raise base.PilotError("none verification must not record output media: " + candidate["candidate_id"])
        return
    media = aligned.probe_video(path)
    roi_media = source.get("roi_media") or {}
    if (set(record.get("media") or {}) != set(MEDIA_FIELDS)
        or record["media"] != {k: media[k] for k in MEDIA_FIELDS}
        or media["total_frames"] != candidate["end_frame"] - candidate["start_frame"]
        or (media["width"], media["height"]) != (roi_media.get("width"), roi_media.get("height"))):
        raise base.PilotError("clip media differs from the probe or from the plan: " + candidate["candidate_id"])


def _validate_output(root, output, candidate, source, *, portable=False, verification=DEFAULT_VERIFICATION):
    """Check the sealed independent select proof and fully decode current bytes."""
    if verification != "full":
        _validate_fast_output(output, candidate, source, verification)
        return
    _, verifier = _backend(source["strategy"])
    proof = source["frame_preserving_replay"]
    roi_path = root / source["roi_path"]
    expected_window = _receipt_window(candidate, proof) if portable else verifier.validate_source_receipt(proof, roi_path, candidate)
    record = candidate["output"]
    clip = record["frame_preserving_replay"]
    schema = coverage_verification.SCHEMA if source["strategy"] == "coverage" else verifier.CLIP_SCHEMA
    _sealed(clip, schema)
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


def _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records, *, require_complete=False,
                       portable=False, verification=DEFAULT_VERIFICATION):
    if manifest.get("schema") != SCHEMA or manifest.get("published") is not False:
        raise base.PilotError("unified manifest schema/publication status mismatch")
    if _manifest_mode(manifest) != verification:
        raise base.PilotError("manifest verification mode differs from the mode requested for this check")
    if verification != "full" and (manifest.get("verification") or {}).get("frame_replay") != "skipped":
        raise base.PilotError("a fast batch must record that frame replay was skipped")
    sources = {s["video_id"]: s for s in manifest["sources"]}
    if len(sources) != len(manifest["sources"]) or not set(sources) <= set(rows):
        raise base.PilotError("duplicate or unexpected unified source")
    if require_complete and set(sources) != set(rows):
        raise base.PilotError("unified source inventory does not cover all 110 sources")
    expected, excluded = [], []
    for key, source in sources.items():
        if (source.get("strategy") != strategy_for(key, rows[key]) or source.get("scope") != _scope(folds[key])
            or source.get("folds") != folds[key] or source.get("source_annotation") != rows[key]):
            raise base.PilotError("source strategy, fixed split or annotation mismatch: " + key)
        if verification != "full":
            note = source.get("verification") or {}
            if (not isinstance(note, dict) or note.get("mode") != verification
                or note.get("frame_replay") != "skipped" or not note.get("reason")
                or "frame_preserving_replay" in source):
                raise base.PilotError("source verification record mismatch: " + key)
        if source.get("status") != "planned":
            if source.get("status") not in {"pending", "failed"} or not source.get("reason"):
                raise base.PilotError("invalid source status/reason: " + key)
            if require_complete:
                raise base.PilotError("source has no admitted frame proof: " + key + ": " + source["reason"])
            continue
        media = _validate_source(root, source, rows[key], rois[key], anchor_records, portable=portable,
                                 verification=verification)
        cs, es = _expected_candidates(key, rows[key], folds[key], media,
            source["source_sha256"], source["roi_sha256"], anchor_records, verification=verification)
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
        if (verification == "full" and "verification" in candidate
            or verification != "full" and candidate.get("verification") != _verification_note(verification)):
            raise base.PilotError("candidate verification record mismatch: " + planned["candidate_id"])
        if _logical(candidate, portable=portable) != _logical(planned, portable=portable):
            raise base.PilotError("candidate window, labels, review or split fields changed: " + planned["candidate_id"])
        if candidate.get("status") == "cropped":
            _validate_output(root, output, candidate, sources[candidate["source_video_id"]],
                             portable=portable, verification=verification)
        elif (candidate.get("status") not in {"planned", "pending", "failed"}
              or "output" in candidate or (candidate["status"] != "planned" and not candidate.get("reason"))):
            raise base.PilotError("invalid candidate status or failure reason")
        elif require_complete:
            raise base.PilotError(("expected clip has not passed independent replay: " if verification == "full"
                                   else "expected clip has not been generated: ") + candidate["candidate_id"])
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
    summary = {"scope": "all_sources", "source_count": len(sources),
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
        "toolchain": _recorded_toolchain(manifest),
        "manual_review": "required_for_every_publishable_clip"}
    if "verification" in manifest:
        summary["verification"] = dict(manifest["verification"])
    return summary


def _named(key, stage, action):
    try:
        return action()
    except base.PilotError as exc:
        raise base.PilotError(f"{stage} {key} failed: {exc}") from exc
    except Exception as exc:
        raise base.PilotError(f"{stage} {key} failed: {type(exc).__name__}: {exc}") from exc


def _map_sources(worker, keys, jobs):
    """Yield ``(key, worker(key))`` in ``keys`` order, in threads when ``jobs`` > 1.

    Threads are enough on purpose: the expensive work is an ffmpeg subprocess,
    which releases the GIL, so threads suffice and they share this process (and
    therefore any injected test double). Results are handed over in ``keys`` order
    rather than completion order, which is what keeps a parallel batch identical
    to a serial one.
    """
    if jobs < 2 or len(keys) < 2:
        for key in keys:
            yield key, worker(key)
        return
    futures, executor = [], concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = [(key, executor.submit(worker, key)) for key in keys]
        for key, future in futures:
            yield key, future.result()
    finally:
        for _, future in futures:
            future.cancel()  # Never start sources whose result nobody will merge.
        executor.shutdown(wait=True)


def _apply_outcome(candidate, outcome):
    """Write one encoding result back into its candidate, as the serial run did."""
    candidate.update(outcome)
    if outcome.get("status") == "cropped":
        candidate.pop("reason", None)
        candidate.pop("details", None)


def _cut_candidate(root, output, source, candidate, verification, expected_identity):
    """Encode one planned window in the mode the batch was started with."""
    destination = output / candidate["output_path"]
    if destination.exists() or destination.is_symlink():
        raise base.PilotError("unrecorded output exists; refusing overwrite")
    try:
        _unchanged(root, expected_identity)
        if verification == "full":
            generator, _ = _backend(source["strategy"])
            result = generator.crop_video(root / source["roi_path"], destination, candidate,
                source["roi_media"], source["frame_preserving_replay"])
        else:
            result = aligned.crop_video(root / source["roi_path"], destination, candidate,
                source["roi_media"], verification=verification)
            result["verification"] = _verification_note(verification)
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
        return {"status": "cropped", "output": result}
    except (base.SkipSource, aligned.AlignmentUncertain) as exc:
        return {"status": "pending", "reason": str(exc), "details": getattr(exc, "details", {})}
    except (base.PilotError, OSError, ValueError) as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}", "details": getattr(exc, "details", {})}


def run(project_root, output_dir=None, *, plan_only=False, resume=False,
        verification=DEFAULT_VERIFICATION, jobs=1):
    """Cut or plan the whole 110-source batch.

    ``verification`` decides how much frame evidence the batch records (see the
    module docstring). ``jobs`` > 1 cuts independent sources in parallel; the
    manifest is written only from this function, so a parallel run produces the
    same batch as a serial one.
    """
    if verification not in VERIFICATION_MODES:
        raise base.PilotError("unknown verification mode: " + repr(verification)
                              + "; expected one of " + ", ".join(VERIFICATION_MODES))
    if type(jobs) is not int or jobs < 1:
        raise base.PilotError("jobs must be a positive integer, got " + repr(jobs))
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    with base._run_lock(output):
        existing = base._load(output / "manifest.json") if (output / "manifest.json").is_file() else None
        # A batch written before the rule registry cannot prove which rules produced it,
        # so it cannot be resumed. Decide this before reading the inventory: an old
        # batch may outlive the inputs it was cut from.
        if resume and existing is not None and not _has_rules(existing):
            raise base.PilotError("legacy batch has no rules digest: rebuild it into a new output directory")
        rows, rois, folds, hashes, _loader_code = load_inputs(root)
        expected_identity = identity(root, hashes)
        anchor_records = anchors.load_anchors(root / anchors.DOCUMENT)
        if output.exists() and any(output.iterdir()):
            if not resume:
                raise base.PilotError("nonempty output exists; choose an empty directory or explicit --resume")
            if existing is None:
                raise base.PilotError("unified resume requires an existing manifest.json")
            if _manifest_mode(existing) != verification:
                raise base.PilotError("verification mode differs: the batch was written in "
                                      + _manifest_mode(existing) + " mode, this run asks for " + verification)
            _check_identity(existing.get("identity") or {}, expected_identity)
            _validate_manifest(root, output, existing, rows, rois, folds, anchor_records,
                               verification=verification)
            manifest = existing
        else:
            if resume:
                raise base.PilotError("cannot resume a missing or empty unified output")
            output.mkdir(parents=True, exist_ok=True)
            manifest = {"schema": SCHEMA, "identity": expected_identity, "sources": [], "candidates": [],
                        "excluded_windows": [], "complete": False, "published": False, "plan_only": bool(plan_only)}
            if verification != "full":
                manifest["verification"] = _verification_note(verification)
        (output / "videos").mkdir(exist_ok=True)

        def save():
            base._atomic_json(output / "manifest.json", manifest)
            base._atomic_json(output / "summary.json", summarize(manifest))

        save()
        source_indexes = {s["video_id"]: i for i, s in enumerate(manifest["sources"])}
        planned_candidates = {c["source_video_id"] for c in manifest["candidates"]}

        def plan_source(key):
            index = source_indexes.get(key)
            previous = manifest["sources"][index] if index is not None else None
            if previous is not None:
                if previous["status"] not in {"pending", "failed"}:
                    return None
                # A failed admission can be retried; an admitted source or any
                # source with planned/generated clips must never be regenerated.
                if key in planned_candidates:
                    raise base.PilotError("cannot retry a source with existing candidates: " + key)
            _unchanged(root, expected_identity)
            planned = _plan_source(root, key, rows[key], rois[key], folds[key], anchor_records, verification)
            _unchanged(root, expected_identity)
            return planned

        def plan_one(key):
            try:
                return plan_source(key)
            except Exception as exc:
                raise base.PilotError(f"planning {key} failed: {type(exc).__name__}: {exc}") from exc

        for key, planned in _map_sources(plan_one, sorted(rows), jobs):
            if planned is None:
                continue
            source, candidates, excluded = planned
            index = source_indexes.get(key)
            if index is None:
                source_indexes[key] = len(manifest["sources"])
                manifest["sources"].append(source)
            else:
                previous = manifest["sources"][index]
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
        _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records, verification=verification)
        sources = {s["video_id"]: s for s in manifest["sources"]}
        if not plan_only:
            groups = {}
            for candidate in manifest["candidates"]:
                if candidate["status"] == "cropped":
                    continue  # Already audited above; this is this run's own output.
                groups.setdefault(candidate["source_video_id"], []).append(candidate)
            if jobs < 2 or len(groups) < 2:
                # Serial: record every clip as soon as it is cut, so an interrupted
                # run keeps exactly the clips that are already on disk.
                for key in sorted(groups):
                    for candidate in groups[key]:
                        outcome = _named(key, "cutting", lambda: _cut_candidate(
                            root, output, sources[key], candidate, verification, expected_identity))
                        _apply_outcome(candidate, outcome)
                        save()
            else:
                def cut_one(key):
                    return _named(key, "cutting", lambda: [
                        _cut_candidate(root, output, sources[key], candidate, verification, expected_identity)
                        for candidate in groups[key]])

                for key, outcomes in _map_sources(cut_one, sorted(groups), jobs):
                    for candidate, outcome in zip(groups[key], outcomes):
                        _apply_outcome(candidate, outcome)
                        save()
        _unchanged(root, expected_identity)
        _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records, verification=verification)
        manifest["plan_only"] = bool(plan_only)
        manifest["complete"] = (not plan_only and set(sources) == set(rows)
            and all(s["status"] == "planned" for s in sources.values())
            and all(c["status"] == "cropped" for c in manifest["candidates"]))
        save()
        return manifest


def audit_outputs(project_root, output_dir, *, portable=False):
    """Independently replan all sources and verify all current outputs and proofs.

    This checks existing technical evidence against current bytes. It does not
    convert technical proof into human review or publication approval, and it
    checks a fast batch only for what that mode promised.
    """
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    with base._run_lock(output):
        return _audit_outputs_locked(root, output, portable=portable)


def _audit_outputs_locked(root, output, *, portable=False):
    manifest = base._load(output / "manifest.json")
    mode = _manifest_mode(manifest)
    rows, rois, folds, hashes, _loader_code = load_inputs(root)
    expected_identity = identity(root, hashes)
    _check_identity(manifest.get("identity") or {}, expected_identity)
    anchor_records = anchors.load_anchors(root / anchors.DOCUMENT)
    verified = _validate_manifest(root, output, manifest, rows, rois, folds, anchor_records,
                                  require_complete=True, portable=portable, verification=mode)
    if base._load(output / "summary.json") != summarize(manifest):
        raise base.PilotError("unified summary differs from current manifest")
    _unchanged(root, expected_identity)
    toolchain = _toolchain_status()
    if mode != "full":
        return {"status": "current_bytes_and_planned_inventory_verified",
                "verification_mode": mode, "verification": _verification_note(mode),
                "source_count": len(rows), "verified_outputs": verified, "published": False,
                "toolchain": toolchain,
                "validation_level": ("output_bytes_and_metadata_only" if mode == "basic"
                                     else "output_bytes_only"),
                "limitations": ["no_frame_level_replay", "no_source_timeline_replay",
                                "no_clip_frame_correspondence", "not_new_frame_replay",
                                "not_human_label_review", "not_data_publication"]
                    + ([] if not toolchain["degraded"] else ["not_pinned_toolchain"])}
    return {"status": "current_bytes_and_planned_inventory_verified", "source_count": len(rows),
            "verified_outputs": verified, "published": False, "toolchain": toolchain,
            "validation_level": "byte_receipt_and_source_timeline_only" if portable else "full_output_decode_and_current_receipts",
            "limitations": (["no_current_output_RGB_PTS_decode", "original_toolchain_receipts_preserved"] if portable else [])
                + ["not_new_frame_replay", "not_human_label_review", "not_data_publication"]
                + ([] if not toolchain["degraded"] else ["not_pinned_toolchain"])}


def audit_content(project_root, output_dir=None):
    """Byte-level audit of one batch: recorded clips versus the files on disk.

    Deliberately independent of code hashes, of the rules digest and of any media
    decoding: a batch whose *rules* cannot be verified is still checkable at the
    content level. It says nothing about frames, labels or publication.
    """
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    with base._run_lock(output):
        return _audit_content_locked(root, output)


def _audit_content_locked(root, output):
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise base.PilotError("content audit requires an existing manifest.json")
    manifest = base._load(manifest_path)
    legacy = not _has_rules(manifest)
    candidates = manifest.get("candidates") or []
    cropped = [c for c in candidates if c.get("status") == "cropped"]
    missing, mismatched, unrecorded = [], [], []
    recorded = set()
    for candidate in cropped:
        relative = candidate["output_path"]
        recorded.add(relative)
        path = output / relative
        if path.is_symlink() or not path.is_file():
            missing.append(candidate["candidate_id"])
            continue
        recorded_sha = (candidate.get("output") or {}).get("sha256") or candidate.get("output_sha256")
        if not recorded_sha or base.sha256_file(path) != recorded_sha:
            mismatched.append(candidate["candidate_id"])
    videos = output / "videos"
    if videos.is_dir() and not videos.is_symlink():
        for entry in sorted(videos.iterdir()):
            relative = str(entry.relative_to(output))
            if relative not in recorded:
                unrecorded.append(relative)
    summary_path = output / "summary.json"
    recorded_count = base._load(summary_path).get("candidate_count") if summary_path.is_file() else None
    count_consistent = recorded_count is None or recorded_count == len(candidates)
    ok = not (missing or mismatched or unrecorded) and count_consistent
    return {"status": "content_audit", "verdict": "content_only",
            "batch_schema": manifest.get("schema"),
            "legacy_batch": legacy, "rules_unverifiable": legacy,
            "candidates": len(candidates), "checked": len(cropped),
            "missing": missing, "mismatched": mismatched, "unrecorded": unrecorded,
            "candidate_count_consistent": count_consistent, "ok": ok,
            "limitations": ["no_media_decode", "no_frame_replay",
                            "no_code_or_rules_identity", "not_human_label_review"]}


def audit_batch(project_root, output_dir, *, portable=False):
    """Route an audit by what the batch says it is.

    Virtual batches and batches written before the rule registry get a content
    audit; a current official batch gets the mode-appropriate output audit (a
    fast batch is audited for exactly what its mode promised).
    """
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    with base._run_lock(output):
        return _audit_batch_locked(root, output, portable=portable)


def _audit_batch_locked(root, output, *, portable=False):
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = base._load(manifest_path)
        if manifest.get("schema") == virtual.SCHEMA or not _has_rules(manifest):
            return _audit_content_locked(root, output)
    return _audit_outputs_locked(root, output, portable=portable)


AUDIT_SCHEMA = "tensile-unified-sub-video-audit/1"


def write_audit_record(project_root, output_dir=None, *, portable=False, replace=False):
    """Write a current official audit; content-only batches lack receipt validation.

    Replay counts count source ``frame_preserving_replay`` receipts and candidate
    ``output.frame_preserving_replay`` receipts recorded in the manifest. The
    audit and record write share the same batch lock.
    """
    return _write_audit_record_with_result(project_root, output_dir, portable=portable, replace=replace)[1]


def _write_audit_record_with_result(project_root, output_dir=None, *, portable=False, replace=False):
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    with base._run_lock(output):
        manifest = base._load(output / "manifest.json")
        result = _audit_batch_locked(root, output, portable=portable)
        if result.get("verdict") == "content_only":
            raise base.PilotError("content-only audit cannot establish current batch receipt validation")
        path = output / "audit.json"
        candidates = []
        counts = Counter()
        for candidate in manifest["candidates"]:
            labels = candidate.get("candidate_labels") or {}
            issues = []
            if labels.get("断裂状态") == "未断裂":
                if (labels.get("断裂现象") or {}).get("断后脱夹") == "是":
                    issues.append("未断裂片段的断后脱夹需复核")
                if (labels.get("异常情况") or {}).get("爆炸性断裂") == "是":
                    issues.append("未断裂与爆炸性断裂互斥")
            if issues:
                counts.update(issues)
                candidates.append({"candidate_id": candidate["candidate_id"],
                                   "source_video_id": candidate["source_video_id"],
                                   "scope": candidate["scope"], "issues": issues})
        record = {
            "schema": AUDIT_SCHEMA,
            "manifest_sha256": base.sha256_file(output / "manifest.json"),
            "checked_sources": len(manifest["sources"]),
            "checked_candidates": len(manifest["candidates"]),
            "source_replays_recorded": sum("frame_preserving_replay" in s for s in manifest["sources"]),
            "clip_replays_recorded": sum("frame_preserving_replay" in (c.get("output") or {})
                                         for c in manifest["candidates"]),
            "generation_validation": {
                "method": "generator_final_manifest_validation",
                "scope": result["validation_level"],
                "validated_outputs": result["verified_outputs"],
                "run_summary_sha256": base.sha256_file(output / "summary.json"),
                "limitations": result["limitations"],
            },
            "candidates_needing_attention": len(candidates),
            "issue_counts": dict(counts),
            "label_status": "candidate_labels_only_unreviewed",
            "description": "候选标签是初值；所有片段须根据画面由人工审核，覆盖片段不推测事件或标签。",
            "candidates": candidates,
        }
        if path.exists() and not replace:
            raise base.PilotError("audit.json already exists; use --replace-audit explicitly")
        base._atomic_json(path, record)
        return result, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, help="default: PROJECT_ROOT/data/sub_video")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--write-audit", action="store_true")
    parser.add_argument("--replace-audit", action="store_true")
    parser.add_argument("--portable-audit", action="store_true", help="read-only audit after copying outputs; no claim of current RGB replay")
    parser.add_argument("--videos-dir", type=Path, help="cut one window batch from this directory's top-level mp4 files; replaces the 110-source project mode and requires --output-dir")
    parser.add_argument("--verification", choices=VERIFICATION_MODES, default=None,
                        help="how much frame evidence the batch records: full replays the source and the clip frames, "
                             "basic (default) only probes the encoded output, none skips even that probe")
    parser.add_argument("--jobs", type=int, default=None,
                        help="cut independent sources in parallel with this many workers; default: 1 (serial, same batch)")
    args = parser.parse_args()
    if args.write_audit and not args.audit_only:
        parser.error("--write-audit requires --audit-only")
    if args.replace_audit and not args.write_audit:
        parser.error("--replace-audit requires --write-audit")
    if args.write_audit and args.videos_dir is not None:
        parser.error("--write-audit cannot be combined with --videos-dir")
    if args.videos_dir is not None:
        if args.portable_audit:
            parser.error("--portable-audit cannot be combined with --videos-dir")
        if args.audit_only:
            parser.error("--audit-only cannot be combined with --videos-dir")
        if args.verification is not None:
            parser.error("--verification cannot be combined with --videos-dir")
        if args.jobs is not None:
            parser.error("--jobs cannot be combined with --videos-dir")
        if args.output_dir is None:
            parser.error("--videos-dir requires an explicit --output-dir")
        try:
            manifest = virtual.run(args.project_root, args.videos_dir, args.output_dir,
                                   plan_only=args.plan_only, resume=args.resume)
        except (base.PilotError, OSError, ValueError, KeyError, TypeError) as exc:
            parser.exit(1, str(exc) + "\n")
        print(base.canonical_bytes(virtual.summarize(manifest)).decode(), end="")
        return 0 if args.plan_only or manifest["complete"] else 2
    if args.portable_audit and not args.audit_only:
        parser.error("--portable-audit requires --audit-only")
    if args.audit_only:
        if args.plan_only or args.resume:
            parser.error("--audit-only cannot be combined with --plan-only or --resume")
        if args.verification is not None:
            parser.error("--verification cannot be combined with --audit-only")
        if args.jobs is not None:
            parser.error("--jobs cannot be combined with --audit-only")
    try:
        if args.audit_only:
            if args.write_audit:
                result, _record = _write_audit_record_with_result(
                    args.project_root, args.output_dir, portable=args.portable_audit,
                    replace=args.replace_audit)
            else:
                result = audit_batch(args.project_root, args.output_dir or args.project_root / "data/sub_video", portable=args.portable_audit)
            print(base.canonical_bytes(result).decode(), end="")
            return 0 if result.get("ok", True) else 1
        manifest = run(args.project_root, args.output_dir, plan_only=args.plan_only, resume=args.resume,
                       verification=args.verification or DEFAULT_VERIFICATION,
                       jobs=1 if args.jobs is None else args.jobs)
    except (base.PilotError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(base.canonical_bytes(summarize(manifest)).decode(), end="")
    return 0 if args.plan_only or manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
