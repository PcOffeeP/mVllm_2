"""Run one inference request per input record via pluggable backends (fake / http / transformers).

All backends share the same manifest/record identity binding, exclusive non-overwriting
``predictions.jsonl`` output, four-state ``STATUS`` semantics, and strict single-JSON
``raw_output`` contract (no ``<answer>`` unwrapping, no sidecar label fields).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from . import paths
from .exclusions import DevExclusions, load_candidate_selection, load_dev_exclusions, verify_frozen_subset_samples
from .backends import (
    InferenceBackend,
    InferenceRequest,
    MODALITY_TEXT_ONLY,
    modality_for_no_image,
    normalize_result,
)
from .backends.fake_backend import CATEGORY_ORDER, LEGAL, NON_ANSWERS, FakeBackend, fake_raw_output
from .backends.transformers_backend import SUPPORTED_MODEL_FAMILIES, TransformersBackend
from .frames import (
    DEFAULT_CLIPS_PER_RECORD,
    DEFAULT_RESIZE,
    RECORD_SCHEMA,
    SAMPLING_RULE,
    SHORT_CLIP_POLICY,
    compute_record_input_id,
    read_records,
    sample_frame_indices,
    verify_lineage,
)
from .prompt_id import load_prompt
from .score import InputError, decode_file, read_json, require_text

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SHA256_RE = re.compile(r"[a-f0-9]{64}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_safe_component(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise InputError(f"{label} must be a single safe path component, got {value!r}")


def _dumps_jsonl_line(obj: dict[str, Any]) -> str:
    """Serialize one JSONL object, escaping Unicode line separators so splitlines() never splits a record."""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .replace("\u0085", "\\u0085")
    )


def _validate_manifest_samples(
    manifest,
    *,
    exclusions: DevExclusions | None = None,
    enforce_exclusions: bool = True,
) -> dict[str, dict]:
    rows = manifest.get("samples") if isinstance(manifest, dict) else None
    if not isinstance(rows, list):
        raise InputError("manifest must contain samples array")
    samples: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or "candidate_id" not in row:
            continue
        cid = row["candidate_id"]
        if cid in samples:
            raise InputError(f"duplicate candidate_id in manifest: {cid}")
        samples[cid] = row
    if enforce_exclusions:
        active_exclusions = exclusions if exclusions is not None else load_dev_exclusions()
        active_exclusions.assert_no_excluded(list(samples.values()), context="infer manifest")
    return samples


def _validate_record_against_manifest(record: Any, samples: dict[str, dict]) -> str:
    if not isinstance(record, dict):
        raise InputError("input record must be object")
    for key in ("candidate_id", "clip_sha256", "input_id", "manifest_sha256", "record_schema"):
        require_text(record, key, "input record")
    cid = record["candidate_id"]
    sample = samples.get(cid)
    if sample is None:
        raise InputError(f"input record candidate absent from manifest: {cid}")
    for key, want in (
        ("clip_sha256", sample.get("clip_sha256")),
        ("record_schema", RECORD_SCHEMA),
        ("manifest_sha256", sample.get("manifest_sha256")),
    ):
        if record[key] != want:
            raise InputError(f"{cid}: record {key} {record[key]!r} != expected {want!r}")
    return cid


def _record_sampling_policy(record: dict) -> dict[str, Any]:
    cid = record.get("candidate_id", "<unknown>")
    sampling = record.get("sampling")
    if isinstance(sampling, dict):
        policy = {
            "sampling_rule": sampling.get("sampling_rule"),
            "target_frame_count": sampling.get("target_frame_count"),
            "short_clip_policy": sampling.get("short_clip_policy"),
            "resize": sampling.get("resize"),
        }
    else:
        frames = record.get("frames")
        c2m = (
            frames[0].get("frame_index_mapping", {}).get("clip_to_model_input")
            if isinstance(frames, list) and frames and isinstance(frames[0], dict)
            else None
        )
        if not isinstance(c2m, dict):
            raise InputError(f"{cid}: missing sampling metadata; re-extract with 8-frame frames.py")
        policy = {
            "sampling_rule": c2m.get("sampling_rule"),
            "target_frame_count": c2m.get("target_frame_count"),
            "short_clip_policy": c2m.get("short_clip_policy"),
            "resize": c2m.get("resize"),
        }
    expected = {
        "sampling_rule": SAMPLING_RULE,
        "target_frame_count": DEFAULT_CLIPS_PER_RECORD,
        "short_clip_policy": SHORT_CLIP_POLICY,
        "resize": DEFAULT_RESIZE,
    }
    if policy != expected:
        raise InputError(
            f"{cid}: sampling policy {policy!r} != required 8-frame contract {expected!r}; "
            "re-extract records with frames.py default 8-frame settings"
        )
    return policy


def _effective_input_id(record: dict, *, no_image: bool) -> str:
    """Return canonical prediction input_id: paired record input_id for Run A, prefixed for Run B."""
    base_id = record["input_id"]
    return f"no_image:{base_id}" if no_image else base_id


def _validate_record_frame_metadata(record: dict) -> list[dict]:
    """Validate ordered 8-frame record metadata without reading PNG bytes from disk."""
    cid = record["candidate_id"]
    _validate_safe_component(cid, "candidate_id")
    raw_frames = record.get("frames")
    if not isinstance(raw_frames, list) or len(raw_frames) != DEFAULT_CLIPS_PER_RECORD:
        got = len(raw_frames) if isinstance(raw_frames, list) else type(raw_frames).__name__
        raise InputError(
            f"{cid}: real inference requires exactly {DEFAULT_CLIPS_PER_RECORD} frames "
            f"(got {got}); re-extract records with frames.py default 8-frame settings"
        )
    ordered = sorted(
        raw_frames,
        key=lambda item: item.get("display_order", -1) if isinstance(item, dict) else -1,
    )
    lineage_media = record.get("lineage_media") if isinstance(record.get("lineage_media"), dict) else {}
    l2_layer = lineage_media.get("l2") if isinstance(lineage_media.get("l2"), dict) else {}
    media = record.get("media") if isinstance(record.get("media"), dict) else {}
    l2_total = l2_layer.get("total_frames") if "total_frames" in l2_layer else media.get("total_frames")
    if not isinstance(l2_total, int) or isinstance(l2_total, bool) or l2_total < len(ordered):
        raise InputError(
            f"{cid}: L2 total_frames must be an integer >= {len(ordered)} for {SAMPLING_RULE} "
            f"(got {l2_total!r}; short clips are fail-closed)"
        )
    expected_indices = sample_frame_indices(l2_total, len(ordered))
    actual_indices = [item.get("clip_frame_index") if isinstance(item, dict) else None for item in ordered]
    if actual_indices != expected_indices:
        raise InputError(
            f"{cid}: clip_frame_index sequence {actual_indices} does not match "
            f"{SAMPLING_RULE} for total_frames={l2_total} (expected {expected_indices})"
        )
    seen_images: set[str] = set()
    for expected_order, entry in enumerate(ordered):
        if not isinstance(entry, dict):
            raise InputError(f"{cid}: frames[{expected_order}] must be object")
        if entry.get("display_order") != expected_order:
            raise InputError(
                f"{cid}: frames display_order must be contiguous 0..{len(ordered) - 1}, "
                f"got {entry.get('display_order')!r}"
            )
        image_name = entry.get("image")
        _validate_safe_component(image_name, f"{cid}: frames[{expected_order}].image")
        if image_name in seen_images:
            raise InputError(f"{cid}: duplicate frame image filename across sampled frames: {image_name!r}")
        seen_images.add(image_name)
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            raise InputError(
                f"{cid}: frames[{expected_order}].sha256 missing or invalid; "
                "re-extract records with frames.py so every L3 PNG is digest-pinned"
            )
    return ordered


def _resolve_record_frames(
    record: dict, frames_dir: Path
) -> tuple[tuple[Path, ...], tuple[float, ...], tuple[bytes, ...]]:
    cid = record["candidate_id"]
    ordered = _validate_record_frame_metadata(record)
    root_dir = frames_dir.resolve()
    raw_clip_dir = frames_dir / cid
    if raw_clip_dir.is_symlink():
        raise InputError(f"{cid}: candidate frame directory must not be a symlink: {raw_clip_dir}")
    clip_dir = raw_clip_dir.resolve()
    try:
        clip_dir.relative_to(root_dir)
    except ValueError as exc:
        raise InputError(f"{cid}: candidate frame directory escapes frames_dir: {clip_dir}") from exc

    frame_paths: list[Path] = []
    frame_pts: list[float] = []
    frame_bytes: list[bytes] = []
    for entry in ordered:
        image_name = entry["image"]
        raw_img_path = clip_dir / image_name
        if raw_img_path.is_symlink():
            raise InputError(f"{cid}: L3 frame PNG must not be a symlink: {raw_img_path}")
        img_path = raw_img_path.resolve()
        try:
            img_path.relative_to(clip_dir)
        except ValueError as exc:
            raise InputError(f"{cid}: L3 frame PNG escapes candidate directory: {img_path}") from exc
        if not img_path.is_file():
            raise InputError(f"{cid}: L3 frame PNG missing on disk: {img_path}")

        expected_sha = entry["sha256"]
        raw_bytes = img_path.read_bytes()
        if not raw_bytes.startswith(PNG_MAGIC):
            raise InputError(f"{cid}: L3 frame is not a valid PNG file: {img_path}")
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        if actual_sha != expected_sha:
            raise InputError(
                f"{cid}: L3 frame PNG sha256 mismatch for {img_path}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        frame_paths.append(img_path)
        frame_bytes.append(raw_bytes)
        pts = entry.get("pts_seconds")
        if isinstance(pts, (int, float)) and not isinstance(pts, bool):
            frame_pts.append(float(pts))
    return tuple(frame_paths), tuple(frame_pts), tuple(frame_bytes)


def _resolve_and_verify_frozen_subset(
    records: list[dict],
    samples: dict[str, dict],
    manifest: dict,
    *,
    eval_subset_id: str | None = None,
) -> str | None:
    """Resolve eval_subset_id from explicit arg, manifest, and records; verify frozen v1 manifest up-front."""
    seen: set[str] = set()
    if eval_subset_id is not None:
        if not isinstance(eval_subset_id, str) or not eval_subset_id.strip():
            raise InputError(f"eval_subset_id must be nonempty string, got {eval_subset_id!r}")
        seen.add(eval_subset_id)
    manifest_subset_id = manifest.get("eval_subset_id") if isinstance(manifest, dict) else None
    if manifest_subset_id is not None:
        if not isinstance(manifest_subset_id, str) or not manifest_subset_id.strip():
            raise InputError(f"manifest eval_subset_id must be nonempty string, got {manifest_subset_id!r}")
        seen.add(manifest_subset_id)
    for rec in records:
        if isinstance(rec, dict) and rec.get("eval_subset_id") is not None:
            rec_sid = rec["eval_subset_id"]
            if not isinstance(rec_sid, str) or not rec_sid.strip():
                raise InputError(f"record eval_subset_id must be nonempty string, got {rec_sid!r}")
            seen.add(rec_sid)
    if len(seen) > 1:
        raise InputError(f"infer eval_subset_id mismatch across inputs: {sorted(seen)}")
    effective = next(iter(seen)) if seen else None
    if effective is not None:
        verify_frozen_subset_samples(effective, samples.values(), context="infer manifest")
    return effective


def plan_predictions(
    records,
    manifest,
    run_id,
    prompt_id,
    model_id="fake",
    *,
    exclusions: DevExclusions | None = None,
    enforce_exclusions: bool = True,
    eval_subset_id: str | None = None,
    no_image: bool = False,
) -> list[dict]:
    """Deterministic fake prediction planner (kept pure & backward compatible)."""
    require_text({"run_id": run_id}, "run_id", "run")
    require_text({"prompt_id": prompt_id}, "prompt_id", "run")
    samples = _validate_manifest_samples(manifest, exclusions=exclusions, enforce_exclusions=enforce_exclusions)
    effective_subset_id = _resolve_and_verify_frozen_subset(
        records, samples, manifest, eval_subset_id=eval_subset_id
    )
    predictions = []
    for index, record in enumerate(records):
        cid = _validate_record_against_manifest(record, samples)
        category = CATEGORY_ORDER[index % len(CATEGORY_ORDER)]
        row = {
            "candidate_id": cid,
            "clip_sha256": record["clip_sha256"],
            "run_id": run_id,
            "model_id": model_id,
            "prompt_id": prompt_id,
            "input_id": _effective_input_id(record, no_image=no_image),
            "request_id": f"{run_id}/{cid}",
            "raw_output": fake_raw_output(category),
            "status": category if category in NON_ANSWERS else "success",
            "input_review_id": None,
            "fake_category": category,
        }
        if effective_subset_id is not None:
            row["eval_subset_id"] = effective_subset_id
        predictions.append(row)
    return predictions


def _extract_sampling_policy(records: list[dict]) -> dict[str, Any] | None:
    if not records:
        return None
    first_policy = _record_sampling_policy(records[0])
    for rec in records[1:]:
        _record_sampling_policy(rec)
    return first_policy


def run_inference(
    records: list[dict],
    manifest: dict,
    *,
    backend: InferenceBackend,
    run_id: str,
    prompt_id: str,
    prompt_text: str,
    model_id: str,
    frames_dir: Path | None = None,
    timeout_seconds: float = 600.0,
    decode_config: dict[str, Any] | None = None,
    output_path: Path | None = None,
    meta_output_path: Path | None = None,
    verify_record_lineage: bool = True,
    exclusions: DevExclusions | None = None,
    enforce_exclusions: bool = True,
    eval_subset_id: str | None = None,
    no_image: bool = False,
) -> tuple[list[dict], dict[str, Any]]:
    """Validate all inputs up-front, reserve outputs exclusively, run backend, and stream predictions."""
    require_text({"run_id": run_id}, "run_id", "run")
    require_text({"prompt_id": prompt_id}, "prompt_id", "run")
    require_text({"model_id": model_id}, "model_id", "run")
    if not isinstance(no_image, bool):
        raise InputError(f"no_image must be a boolean, got {no_image!r}")
    if not no_image and getattr(backend, "no_image", False):
        raise InputError("backend has no_image=True but run_inference was called with no_image=False")
    if not no_image and frames_dir is None:
        raise InputError("frames_dir is required when no_image=False")
    if backend.backend_name != "fake" and model_id.strip() == "fake":
        raise InputError(f"{backend.backend_name} backend refuses --model-id fake")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise InputError(f"timeout_seconds must be a positive finite number, got {timeout_seconds!r}")
    if isinstance(decode_config, dict):
        if "temperature" in decode_config and decode_config["temperature"] is not None:
            temp_val = decode_config["temperature"]
            if isinstance(temp_val, bool) or not isinstance(temp_val, (int, float)) or not math.isfinite(temp_val) or temp_val < 0:
                raise InputError(f"temperature must be a finite number >= 0, got {temp_val!r}")
        if "max_tokens" in decode_config and decode_config["max_tokens"] is not None:
            max_tok_val = decode_config["max_tokens"]
            if isinstance(max_tok_val, bool) or not isinstance(max_tok_val, int) or max_tok_val <= 0:
                raise InputError(f"max_tokens must be a positive integer, got {max_tok_val!r}")
        if "top_p" in decode_config and decode_config["top_p"] is not None:
            top_p_val = decode_config["top_p"]
            if (
                isinstance(top_p_val, bool)
                or not isinstance(top_p_val, (int, float))
                or not math.isfinite(top_p_val)
                or top_p_val <= 0
                or top_p_val > 1.0
            ):
                raise InputError(f"top_p must be a finite number in (0, 1], got {top_p_val!r}")
        if "seed" in decode_config and decode_config["seed"] is not None:
            seed_val = decode_config["seed"]
            if isinstance(seed_val, bool) or not isinstance(seed_val, int):
                raise InputError(f"seed must be an integer when set, got {seed_val!r}")

    samples = _validate_manifest_samples(manifest, exclusions=exclusions, enforce_exclusions=enforce_exclusions)
    effective_subset_id = _resolve_and_verify_frozen_subset(
        records, samples, manifest, eval_subset_id=eval_subset_id
    )
    prepared: list[tuple[str, dict, tuple[Path, ...], tuple[float, ...]]] = []
    seen_cids: set[str] = set()
    batch_sampling_policy: dict[str, Any] | None = None
    for record in records:
        cid = _validate_record_against_manifest(record, samples)
        if cid in seen_cids:
            raise InputError(f"duplicate candidate_id in input records: {cid}")
        seen_cids.add(cid)
        if verify_record_lineage:
            if failures := verify_lineage(record):
                raise InputError(f"{cid}: lineage check failed before inference: {' | '.join(failures)}")
        policy = _record_sampling_policy(record)
        if batch_sampling_policy is None:
            batch_sampling_policy = policy
        if no_image:
            # Strictly pair Run B against the validated 8-frame record metadata and input_id
            # without reading PNG pixels from disk.
            _validate_record_frame_metadata(record)
            expected_input_id = compute_record_input_id(record)
            if record.get("input_id") != expected_input_id:
                raise InputError(
                    f"{cid}: record input_id does not match declared ordered frame metadata "
                    f"(expected {expected_input_id}, got {record.get('input_id')!r})"
                )
            prepared.append((cid, record, (), ()))
        else:
            assert frames_dir is not None
            frame_paths, frame_pts, frame_bytes = _resolve_record_frames(record, frames_dir)
            actual_frame_shas = [hashlib.sha256(raw).hexdigest() for raw in frame_bytes]
            expected_input_id = compute_record_input_id(record, frame_sha256s=actual_frame_shas)
            if record.get("input_id") != expected_input_id:
                raise InputError(
                    f"{cid}: record input_id does not match verified ordered frame digests "
                    f"(expected {expected_input_id}, got {record.get('input_id')!r})"
                )
            # Do not retain raw PNG bytes across the entire batch (prevents OOM on large sets);
            # each candidate's 8 PNGs are re-read and digest-verified right before its infer_one().
            prepared.append((cid, record, frame_paths, frame_pts))

    # Reserve both exclusive output files BEFORE issuing any backend requests.
    stream = None
    meta_target = Path(meta_output_path) if meta_output_path is not None else None
    try:
        if output_path is not None:
            stream = Path(output_path).open("x", encoding="utf-8")
        if meta_target is not None:
            with meta_target.open("x", encoding="utf-8") as init_meta:
                init_meta.write("{}\n")
                init_meta.flush()
    except Exception:
        if stream is not None:
            stream.close()
        raise

    predictions: list[dict] = []
    request_metas: list[dict[str, Any]] = []
    raw_decode = dict(decode_config or {})

    def _effective_decode_config(backend_id: Any) -> dict[str, Any]:
        backend_decode = (
            backend_id.get("decode_config")
            if isinstance(backend_id, dict) and isinstance(backend_id.get("decode_config"), dict)
            else {}
        )
        merged: dict[str, Any] = {
            "temperature": raw_decode.get("temperature", backend_decode.get("temperature")),
            "max_tokens": raw_decode.get("max_tokens", backend_decode.get("max_tokens")),
            "top_p": raw_decode.get("top_p", backend_decode.get("top_p")),
            "seed": raw_decode.get("seed", backend_decode.get("seed")),
        }
        for key, value in raw_decode.items():
            if key not in merged:
                merged[key] = value
        return merged

    def _build_run_meta(run_status: str) -> dict[str, Any]:
        raw_backend_id = backend.run_identity()
        backend_identity = dict(raw_backend_id) if isinstance(raw_backend_id, dict) else raw_backend_id
        if no_image and isinstance(backend_identity, dict):
            backend_identity["no_image"] = True
            backend_identity["modality"] = MODALITY_TEXT_ONLY
        meta: dict[str, Any] = {
            "run_id": run_id,
            "model_id": model_id,
            "prompt_id": prompt_id,
            "run_status": run_status,
            "no_image": no_image,
            "modality": modality_for_no_image(no_image),
            "decode_config": _effective_decode_config(backend_identity),
            "sampling_policy": batch_sampling_policy,
            "backend_identity": backend_identity,
            "total_requests": len(predictions),
            "status_counts": {
                status: sum(1 for row in predictions if row["status"] == status)
                for status in ("success", "request_failed", "timeout")
            },
            "requests": request_metas,
        }
        if effective_subset_id is not None:
            meta["eval_subset_id"] = effective_subset_id
        return meta

    def _checkpoint_meta(run_status: str) -> dict[str, Any]:
        payload = _build_run_meta(run_status)
        if meta_target is not None:
            serialized = (
                json.dumps(payload, ensure_ascii=False, indent=2)
                .encode("utf-8", errors="replace")
                .decode("utf-8")
                + "\n"
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{meta_target.name}.",
                suffix=".tmp",
                dir=str(meta_target.parent),
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_stream:
                    tmp_stream.write(serialized)
                    tmp_stream.flush()
                    os.fsync(tmp_stream.fileno())
                os.replace(tmp_path, meta_target)
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        return payload

    completed = False
    run_meta = _checkpoint_meta("running")
    try:
        for cid, record, _preflight_paths, _preflight_pts in prepared:
            if no_image:
                frame_paths: tuple[Path, ...] = ()
                frame_pts: tuple[float, ...] = ()
                frame_bytes: tuple[bytes, ...] = ()
            else:
                assert frames_dir is not None
                frame_paths, frame_pts, frame_bytes = _resolve_record_frames(record, frames_dir)
            req = InferenceRequest(
                candidate_id=cid,
                record=record,
                frame_paths=frame_paths,
                frame_pts_seconds=frame_pts,
                prompt_text=prompt_text,
                timeout_seconds=timeout_seconds,
                decode_config=dict(raw_decode),
                frame_bytes=frame_bytes,
                no_image=no_image,
            )
            result = normalize_result(backend.infer_one(req))
            row = {
                "candidate_id": cid,
                "clip_sha256": record["clip_sha256"],
                "run_id": run_id,
                "model_id": model_id,
                "prompt_id": prompt_id,
                "input_id": _effective_input_id(record, no_image=no_image),
                "request_id": f"{run_id}/{cid}",
                "raw_output": result.raw_output,
                "status": result.status,
                "input_review_id": None,
            }
            if effective_subset_id is not None:
                row["eval_subset_id"] = effective_subset_id
            if stream is not None:
                stream.write(_dumps_jsonl_line(row) + "\n")
                stream.flush()
            predictions.append(row)
            req_meta: dict[str, Any] = {
                "candidate_id": cid,
                "request_id": row["request_id"],
                "input_id": row["input_id"],
                "status": result.status,
                "latency_seconds": result.latency_seconds,
                "error_detail": result.error_detail,
                "reasoning_content": result.reasoning_content,
                "extra_meta": result.extra_meta,
            }
            if no_image:
                req_meta["paired_record_input_id"] = record["input_id"]
            request_metas.append(req_meta)
            run_meta = _checkpoint_meta("running")

        completed = True
        run_meta = _checkpoint_meta("completed")
    finally:
        if not completed:
            try:
                _checkpoint_meta("interrupted")
            except OSError:
                pass
        if stream is not None:
            stream.close()

    return predictions, run_meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Scoring manifest to bind requests to")
    parser.add_argument("--candidate-ids", help="JSON array or frozen eval-subset JSON of candidate IDs selecting record order")
    parser.add_argument("--profile", help="Path profile; only needed to default --input-config")
    parser.add_argument("--model-id", default="fake")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prompt-file", required=True, help="Prompt text file; exact bytes sent and hashed")
    parser.add_argument("--input-config", help="frames records JSONL; defaults to profile output_dir/records.jsonl")
    parser.add_argument("--frames-dir", help="Directory holding <candidate_id>/frame_*.png; defaults to --input-config parent")
    parser.add_argument("--output", required=True, help="New predictions JSONL; never overwrites")
    parser.add_argument("--meta-output", help="Optional run metadata JSON path (defaults to <output>.meta.json for real backends or --no-image)")
    parser.add_argument("--backend", default="fake", choices=("fake", "http", "transformers"))
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Run B pure-text prior control: keep full paired validation, send zero images to the model",
    )
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-request timeout in seconds")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--top-p", type=float, default=None, help="Optional nucleus sampling top_p in (0, 1]")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-pixels", type=int, default=None, help="Processor-side max_pixels recorded in run identity")
    # HTTP backend options
    parser.add_argument("--endpoint", help="OpenAI-compatible base URL (required for --backend http)")
    parser.add_argument("--api-model-name", help="Model name sent in HTTP payload (defaults to --model-id)")
    parser.add_argument("--api-key-env", help="Environment variable holding optional Bearer token")
    # Transformers backend options
    parser.add_argument("--model-path", help="Local weights directory (required for --backend transformers)")
    parser.add_argument(
        "--model-family",
        choices=SUPPORTED_MODEL_FAMILIES,
        help="Explicit Tier 1 model family override (auto-detected if omitted)",
    )
    parser.add_argument("--max-slice-nums", type=int, default=None, help="MiniCPM-V-4.5 max_slice_nums (default: 1)")
    parser.add_argument(
        "--trusted-sha256-file",
        help="JSON mapping {relative_file: sha256} verified fail-closed before trust_remote_code (required for local loading)",
    )
    parser.add_argument("--exclusions", help="DEC-007 dev-exclusions JSON; defaults to data/splits/dev-exclusions.json")
    parser.add_argument("--allow-excluded", action="store_true", help="Disable DEC-007 exclusion guard (forensic use only)")
    args = parser.parse_args(argv)
    try:
        profiles = paths.load_profile(args.profile) if args.profile else None
        if not args.input_config and profiles is None:
            raise InputError("provide --input-config or --profile")
        input_config = Path(args.input_config) if args.input_config else profiles["output_dir"] / "records.jsonl"
        prompt_text, prompt_identity = load_prompt(args.prompt_file)
        exclusions = None if args.allow_excluded else load_dev_exclusions(args.exclusions)
        records = read_records(input_config)
        selection = None
        if args.candidate_ids:
            selection = load_candidate_selection(args.candidate_ids)
            selected = selection.candidate_ids
            if exclusions is not None:
                exclusions.assert_no_excluded(selected, context="infer candidate_ids")
            by_id: dict[Any, dict] = {}
            for record in records:
                rcid = record.get("candidate_id") if isinstance(record, dict) else None
                if rcid in by_id:
                    raise InputError(f"duplicate candidate_id in input records: {rcid}")
                by_id[rcid] = record
            duplicated = sorted(cid for cid in set(selected) if selected.count(cid) > 1)
            missing = [cid for cid in selected if cid not in by_id]
            if duplicated or missing:
                raise InputError(
                    f"duplicate candidate_id in candidate_ids: {duplicated}"
                    if duplicated
                    else f"candidate_id not found in input records: {missing}"
                )
            records = [by_id[cid] for cid in selected]
            for record in records:
                selection.assert_manifest_sha256(
                    record.get("manifest_sha256", ""),
                    context=f"infer record {record.get('candidate_id')}",
                )

        manifest = read_json(args.manifest)
        manifest_subset_id = manifest.get("eval_subset_id") if isinstance(manifest, dict) else None
        if manifest_subset_id is not None and (not isinstance(manifest_subset_id, str) or not manifest_subset_id.strip()):
            raise InputError(f"manifest eval_subset_id must be nonempty string, got {manifest_subset_id!r}")
        selection_subset_id = selection.subset_id if selection is not None else None
        if selection_subset_id is not None and manifest_subset_id is not None and selection_subset_id != manifest_subset_id:
            raise InputError(
                f"infer eval_subset_id mismatch: --candidate-ids={selection_subset_id!r} != manifest={manifest_subset_id!r}"
            )
        effective_subset_id = selection_subset_id or manifest_subset_id
        manifest_samples = _validate_manifest_samples(
            manifest, exclusions=exclusions, enforce_exclusions=not args.allow_excluded
        )
        if effective_subset_id is not None:
            verify_frozen_subset_samples(
                effective_subset_id,
                manifest_samples.values(),
                context="infer manifest",
            )
        if selection is not None:
            selected_set = set(selection.candidate_ids)
            if selection.expected_manifest_sha256 is not None and set(manifest_samples) != selected_set:
                extra = sorted(set(manifest_samples) - selected_set)
                missing_in_manifest = sorted(selected_set - set(manifest_samples))
                raise InputError(
                    f"infer manifest samples do not match frozen subset {selection.subset_id or 'tensile-eval-subset/1'} "
                    f"(extra={len(extra)} {extra[:5]}, missing={len(missing_in_manifest)} {missing_in_manifest[:5]}); "
                    "build a subset-scoped scoring manifest with manifest_convert --candidate-ids"
                )
            selection.assert_samples_match_source_manifest(
                [sample for sample in manifest_samples.values() if sample.get("candidate_id") in selected_set],
                context="infer manifest",
            )
        decode_config = {
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "top_p": args.top_p,
            "seed": args.seed,
        }
        if args.backend == "fake":
            if args.model_id != "fake":
                raise InputError("fake backend only accepts --model-id fake")
            if args.no_image:
                meta_output = Path(args.meta_output) if args.meta_output else Path(f"{args.output}.meta.json")
                fake_backend = FakeBackend(model_id=args.model_id, no_image=True)
                try:
                    predictions, _ = run_inference(
                        records,
                        manifest,
                        backend=fake_backend,
                        run_id=args.run_id,
                        prompt_id=prompt_identity,
                        prompt_text=prompt_text,
                        model_id=args.model_id,
                        frames_dir=None,
                        timeout_seconds=args.timeout,
                        decode_config=decode_config,
                        output_path=Path(args.output),
                        meta_output_path=meta_output,
                        exclusions=exclusions,
                        enforce_exclusions=not args.allow_excluded,
                        eval_subset_id=effective_subset_id,
                        no_image=True,
                    )
                finally:
                    fake_backend.close()
                print(
                    f"Wrote {len(predictions)} predictions to {args.output}; backend={args.backend}; "
                    f"prompt_id={prompt_identity}; meta={meta_output}; modality={MODALITY_TEXT_ONLY}"
                )
                return 0
            predictions = plan_predictions(
                records,
                manifest,
                args.run_id,
                prompt_identity,
                model_id=args.model_id,
                exclusions=exclusions,
                enforce_exclusions=not args.allow_excluded,
                eval_subset_id=effective_subset_id,
            )
            out_path = Path(args.output)
            meta_stream = None
            pred_stream = None
            try:
                pred_stream = out_path.open("x", encoding="utf-8")
                if args.meta_output:
                    meta_stream = Path(args.meta_output).open("x", encoding="utf-8")
                for row in predictions:
                    pred_stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                if meta_stream is not None:
                    fake_backend = FakeBackend(model_id=args.model_id, no_image=False)
                    meta_payload: dict[str, Any] = {
                        "run_id": args.run_id,
                        "model_id": args.model_id,
                        "prompt_id": prompt_identity,
                        "run_status": "completed",
                        "no_image": False,
                        "modality": modality_for_no_image(False),
                        "decode_config": decode_config,
                        "sampling_policy": None,
                        "backend_identity": fake_backend.run_identity(),
                        "total_requests": len(predictions),
                        "status_counts": {
                            status: sum(1 for row in predictions if row["status"] == status)
                            for status in ("success", "request_failed", "timeout")
                        },
                        "requests": [
                            {
                                "candidate_id": row["candidate_id"],
                                "request_id": row["request_id"],
                                "input_id": row["input_id"],
                                "status": row["status"],
                                "latency_seconds": 0.0,
                                "error_detail": None,
                                "reasoning_content": None,
                                "extra_meta": {"fake_category": row["fake_category"]},
                            }
                            for row in predictions
                        ],
                    }
                    if effective_subset_id is not None:
                        meta_payload["eval_subset_id"] = effective_subset_id
                    meta_stream.write(json.dumps(meta_payload, ensure_ascii=False, indent=2) + "\n")
            except Exception:
                if pred_stream is not None:
                    pred_stream.close()
                    out_path.unlink(missing_ok=True)
                if meta_stream is not None:
                    meta_stream.close()
                raise
            else:
                if pred_stream is not None:
                    pred_stream.close()
                if meta_stream is not None:
                    meta_stream.close()
            print(
                f"Wrote {len(predictions)} predictions to {args.output}; backend={args.backend}; "
                f"prompt_id={prompt_identity}"
            )
            return 0

        frames_dir = Path(args.frames_dir) if args.frames_dir else input_config.parent
        meta_output = Path(args.meta_output) if args.meta_output else Path(f"{args.output}.meta.json")
        sampling_policy = _extract_sampling_policy(records)

        backend: InferenceBackend
        if args.backend == "http":
            if not args.endpoint:
                raise InputError("--endpoint is required for --backend http")
            try:
                from .backends.http_backend import HttpBackend
            except ImportError as exc:
                raise InputError(f"http backend requires httpx to be installed: {exc}") from exc
            backend = HttpBackend(
                endpoint=args.endpoint,
                model_id=args.model_id,
                api_model_name=args.api_model_name,
                api_key_env=args.api_key_env,
                timeout_seconds=args.timeout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                top_p=args.top_p,
                seed=args.seed,
                max_pixels=args.max_pixels,
                sampling_policy=sampling_policy,
                no_image=args.no_image,
            )
        else:
            if not args.model_path:
                raise InputError("--model-path is required for --backend transformers")
            trusted_sha = read_json(args.trusted_sha256_file) if args.trusted_sha256_file else None
            backend = TransformersBackend(
                model_id=args.model_id,
                model_path=args.model_path,
                model_family=args.model_family,
                timeout_seconds=args.timeout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                top_p=args.top_p,
                seed=args.seed,
                max_pixels=args.max_pixels,
                max_slice_nums=args.max_slice_nums,
                sampling_policy=sampling_policy,
                no_image=args.no_image,
                trusted_files_sha256=trusted_sha,
            )

        try:
            predictions, _ = run_inference(
                records,
                manifest,
                backend=backend,
                run_id=args.run_id,
                prompt_id=prompt_identity,
                prompt_text=prompt_text,
                model_id=args.model_id,
                frames_dir=frames_dir,
                timeout_seconds=args.timeout,
                decode_config=decode_config,
                output_path=Path(args.output),
                meta_output_path=meta_output,
                exclusions=exclusions,
                enforce_exclusions=not args.allow_excluded,
                eval_subset_id=effective_subset_id,
                no_image=args.no_image,
            )
        finally:
            backend.close()
        modality_suffix = f"; modality={MODALITY_TEXT_ONLY}" if args.no_image else ""
        print(
            f"Wrote {len(predictions)} predictions to {args.output}; backend={args.backend}; "
            f"prompt_id={prompt_identity}; meta={meta_output}{modality_suffix}"
        )
        return 0
    except (InputError, OSError, UnicodeError, NotImplementedError, paths.EvalPathError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
