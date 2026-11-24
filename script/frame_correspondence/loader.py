"""Strict loader and validator for five-label-input-record/3 JSONL and optional manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from script.five_label_eval import frames as eval_frames
from script.five_label_eval.score import InputError

from .schema import (
    EXPECTED_INPUT_RECORD_SCHEMA,
    FORBIDDEN_FRAME_KEYS,
    FORBIDDEN_MAPPING_KEYS,
    EvidenceError,
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_v3_record_strict(record: dict[str, Any], location: str) -> None:
    """Enforce strict v3 schema, directional mapping keys, and four-layer lineage."""
    schema = record.get("record_schema")
    if schema != EXPECTED_INPUT_RECORD_SCHEMA:
        raise EvidenceError(
            f"{location}: record_schema {schema!r} != expected {EXPECTED_INPUT_RECORD_SCHEMA!r}; "
            f"v2/legacy or untyped records are explicitly rejected "
            f"(expected mapping keys: {list(eval_frames.MAPPING_NODE_KEYS)})"
        )

    for required_key in ("candidate_id", "input_id"):
        val = record.get(required_key)
        if not isinstance(val, str) or not val.strip():
            raise EvidenceError(f"{location}: {required_key!r} must be a non-empty string")

    frames = record.get("frames")
    if not isinstance(frames, list) or not frames:
        raise EvidenceError(f"{location}: frames must be a non-empty list of L3 model input frames")

    for order, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise EvidenceError(f"{location}: frames[{order}] must be an object")
        for forbidden_frame_key in FORBIDDEN_FRAME_KEYS:
            if forbidden_frame_key in frame:
                raise EvidenceError(
                    f"{location}: frames[{order}] contains deprecated key {forbidden_frame_key!r}; "
                    "use 'original_source_frame_index'"
                )
        mapping = frame.get("frame_index_mapping")
        if not isinstance(mapping, dict):
            raise EvidenceError(f"{location}: frames[{order}].frame_index_mapping must be an object")
        forbidden_present = [k for k in FORBIDDEN_MAPPING_KEYS if k in mapping]
        if forbidden_present:
            raise EvidenceError(
                f"{location}: frames[{order}].frame_index_mapping contains forbidden/legacy key(s) "
                f"{forbidden_present}; {EXPECTED_INPUT_RECORD_SCHEMA} requires "
                f"{list(eval_frames.MAPPING_NODE_KEYS)}"
            )
        missing_nodes = [k for k in eval_frames.MAPPING_NODE_KEYS if k not in mapping]
        if missing_nodes:
            raise EvidenceError(
                f"{location}: frames[{order}].frame_index_mapping missing required node(s) "
                f"{missing_nodes}; expected {list(eval_frames.MAPPING_NODE_KEYS)}"
            )
        unexpected_nodes = sorted(set(mapping) - set(eval_frames.MAPPING_NODE_KEYS))
        if unexpected_nodes:
            raise EvidenceError(
                f"{location}: frames[{order}].frame_index_mapping contains unexpected node(s) "
                f"{unexpected_nodes}; expected only {list(eval_frames.MAPPING_NODE_KEYS)}"
            )
        clip_to_model = mapping.get("clip_to_model_input")
        if not isinstance(clip_to_model, dict) or not isinstance(clip_to_model.get("kind"), str) or not clip_to_model["kind"].strip():
            raise EvidenceError(
                f"{location}: frames[{order}].frame_index_mapping.clip_to_model_input must be an object with non-empty 'kind'"
            )
        clip_to_roi = mapping.get("clip_to_roi")
        if not isinstance(clip_to_roi, dict) or not isinstance(clip_to_roi.get("kind"), str) or not clip_to_roi["kind"].strip():
            raise EvidenceError(
                f"{location}: frames[{order}].frame_index_mapping.clip_to_roi must be an object with non-empty 'kind'"
            )

    display_orders = [f.get("display_order") for f in frames]
    expected_orders = list(range(len(frames)))
    if any(isinstance(v, bool) or not isinstance(v, int) for v in display_orders) or display_orders != expected_orders:
        raise EvidenceError(
            f"{location}: frames[].display_order must be contiguous 0..{len(frames) - 1}, got {display_orders!r}"
        )

    lineage_failures = eval_frames.verify_lineage(record)
    if lineage_failures:
        raise EvidenceError(
            f"{location}: lineage verification failed: {' | '.join(lineage_failures)}"
        )


def load_input_records(path: Path | str) -> list[dict[str, Any]]:
    """Load and strictly validate a five-label-input-record/3 JSONL file."""
    target = Path(path)
    if not target.is_file():
        raise EvidenceError(f"input records file not found: {target}")
    try:
        records = eval_frames.read_records(target)
    except (InputError, OSError, UnicodeError) as exc:
        raise EvidenceError(f"failed to read input records from {target}: {exc}") from exc

    if not records:
        raise EvidenceError(f"input records file is empty: {target}")

    for idx, record in enumerate(records, 1):
        cid = record.get("candidate_id") if isinstance(record, dict) else None
        label = f"{target}#{idx}" + (f"({cid})" if isinstance(cid, str) and cid else "")
        _validate_v3_record_strict(record, label)

    return records


def record_run_id(record: dict[str, Any]) -> str | None:
    """Extract optional run_id from top-level or nested run metadata."""
    top = record.get("run_id")
    if isinstance(top, str) and top.strip():
        return top.strip()
    run_block = record.get("run")
    if isinstance(run_block, dict):
        nested = run_block.get("run_id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def filter_records(
    records: list[dict[str, Any]],
    *,
    clip_ids: list[str] | None = None,
    run_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter validated records by optional clip_id (candidate_id) and/or run_id."""
    selected = list(records)
    if clip_ids:
        wanted_clips = {c.strip() for c in clip_ids if c and c.strip()}
        selected = [
            rec
            for rec in selected
            if rec.get("candidate_id") in wanted_clips or rec.get("clip_id") in wanted_clips
        ]
    if run_ids:
        wanted_runs = {r.strip() for r in run_ids if r and r.strip()}
        selected = [rec for rec in selected if record_run_id(rec) in wanted_runs]
    if not selected:
        raise EvidenceError(
            f"no input records matched filters (clip_ids={clip_ids!r}, run_ids={run_ids!r})"
        )
    return selected


def load_subvideo_manifest(path: Path | str) -> dict[str, Any]:
    """Load an optional subvideo manifest JSON and index candidates + batch metadata."""
    target = Path(path)
    if not target.is_file():
        raise EvidenceError(f"subvideo manifest not found: {target}")
    try:
        raw = target.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"failed to parse subvideo manifest {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"subvideo manifest must be a JSON object: {target}")
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        raise EvidenceError(f"subvideo manifest missing 'candidates' list: {target}")
    by_id: dict[str, dict[str, Any]] = {}
    for row in candidates:
        if isinstance(row, dict) and isinstance(row.get("candidate_id"), str):
            by_id[row["candidate_id"]] = row
    sources_by_id: dict[str, dict[str, Any]] = {}
    sources = data.get("sources")
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, dict) and isinstance(src.get("video_id"), str):
                sources_by_id[src["video_id"]] = src
    return {
        "path": str(target),
        "sha256": sha256_bytes(raw),
        "schema": data.get("schema"),
        "verification": data.get("verification") if isinstance(data.get("verification"), dict) else {},
        "verification_mode": data.get("verification_mode"),
        "generation_validation": (
            data.get("generation_validation")
            if isinstance(data.get("generation_validation"), dict)
            else {}
        ),
        "candidates_by_id": by_id,
        "sources_by_id": sources_by_id,
    }


def load_roi_manifest(path: Path | str) -> dict[str, Any]:
    """Load an optional ROI manifest JSON and index video entries by video_id."""
    target = Path(path)
    if not target.is_file():
        raise EvidenceError(f"ROI manifest not found: {target}")
    try:
        raw = target.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"failed to parse ROI manifest {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"ROI manifest must be a JSON object: {target}")
    by_video_id: dict[str, dict[str, Any]] = {}
    for list_key in ("videos", "sources"):
        rows = data.get(list_key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("video_id"), str):
                    by_video_id.setdefault(row["video_id"], row)
    return {
        "path": str(target),
        "sha256": sha256_bytes(raw),
        "schema": data.get("schema"),
        "rule_version": data.get("rule_version"),
        "videos_by_id": by_video_id,
    }
