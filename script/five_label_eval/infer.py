"""Run one inference request per input record via pluggable backends (fake / http / transformers).

All backends share the same manifest/record identity binding, exclusive non-overwriting
``predictions.jsonl`` output, four-state ``STATUS`` semantics, and strict single-JSON
``raw_output`` contract (no ``<answer>`` unwrapping, no sidecar label fields).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from . import paths
from .backends import InferenceBackend, InferenceRequest, normalize_result
from .backends.fake_backend import CATEGORY_ORDER, LEGAL, NON_ANSWERS, fake_raw_output
from .backends.http_backend import HttpBackend
from .backends.transformers_backend import SUPPORTED_MODEL_FAMILIES, TransformersBackend
from .frames import RECORD_SCHEMA, read_records, verify_lineage
from .prompt_id import load_prompt
from .score import InputError, decode_file, read_json, require_text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest_samples(manifest) -> dict[str, dict]:
    rows = manifest.get("samples") if isinstance(manifest, dict) else None
    if not isinstance(rows, list):
        raise InputError("manifest must contain samples array")
    return {row["candidate_id"]: row for row in rows if isinstance(row, dict) and "candidate_id" in row}


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


def _resolve_record_frames(record: dict, frames_dir: Path) -> tuple[tuple[Path, ...], tuple[float, ...]]:
    cid = record["candidate_id"]
    raw_frames = record.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise InputError(f"{cid}: input record has no frames")
    ordered = sorted(
        raw_frames,
        key=lambda item: item.get("display_order", -1) if isinstance(item, dict) else -1,
    )
    frame_paths: list[Path] = []
    frame_pts: list[float] = []
    for expected_order, entry in enumerate(ordered):
        if not isinstance(entry, dict):
            raise InputError(f"{cid}: frames[{expected_order}] must be object")
        if entry.get("display_order") != expected_order:
            raise InputError(
                f"{cid}: frames display_order must be contiguous 0..{len(ordered) - 1}, "
                f"got {entry.get('display_order')!r}"
            )
        image_name = entry.get("image")
        if not isinstance(image_name, str) or not image_name.strip():
            raise InputError(f"{cid}: frames[{expected_order}].image missing")
        img_path = frames_dir / cid / image_name
        if not img_path.is_file():
            raise InputError(f"{cid}: L3 frame PNG missing on disk: {img_path}")
        expected_sha = entry.get("sha256")
        if isinstance(expected_sha, str) and expected_sha:
            actual_sha = _sha256_file(img_path)
            if actual_sha != expected_sha:
                raise InputError(
                    f"{cid}: L3 frame PNG sha256 mismatch for {img_path}: "
                    f"expected {expected_sha}, got {actual_sha}"
                )
        frame_paths.append(img_path)
        pts = entry.get("pts_seconds")
        if isinstance(pts, (int, float)) and not isinstance(pts, bool):
            frame_pts.append(float(pts))
    return tuple(frame_paths), tuple(frame_pts)


def plan_predictions(records, manifest, run_id, prompt_id, model_id="fake") -> list[dict]:
    """Deterministic fake prediction planner (kept pure & backward compatible)."""
    require_text({"run_id": run_id}, "run_id", "run")
    require_text({"prompt_id": prompt_id}, "prompt_id", "run")
    samples = _validate_manifest_samples(manifest)
    predictions = []
    for index, record in enumerate(records):
        cid = _validate_record_against_manifest(record, samples)
        category = CATEGORY_ORDER[index % len(CATEGORY_ORDER)]
        predictions.append({
            "candidate_id": cid,
            "clip_sha256": record["clip_sha256"],
            "run_id": run_id,
            "model_id": model_id,
            "prompt_id": prompt_id,
            "input_id": record["input_id"],
            "request_id": f"{run_id}/{cid}",
            "raw_output": fake_raw_output(category),
            "status": category if category in NON_ANSWERS else "success",
            "input_review_id": None,
            "fake_category": category,
        })
    return predictions


def _extract_sampling_policy(records: list[dict]) -> dict[str, Any] | None:
    if not records:
        return None
    first = records[0]
    if isinstance(first.get("sampling"), dict):
        return dict(first["sampling"])
    frames = first.get("frames")
    if isinstance(frames, list) and frames and isinstance(frames[0], dict):
        mapping = frames[0].get("frame_index_mapping")
        if isinstance(mapping, dict) and isinstance(mapping.get("clip_to_model_input"), dict):
            c2m = mapping["clip_to_model_input"]
            return {
                "sampling_rule": c2m.get("sampling_rule"),
                "target_frame_count": c2m.get("target_frame_count", len(frames)),
                "short_clip_policy": c2m.get("short_clip_policy"),
                "resize": c2m.get("resize"),
            }
    return None


def run_inference(
    records: list[dict],
    manifest: dict,
    *,
    backend: InferenceBackend,
    run_id: str,
    prompt_id: str,
    prompt_text: str,
    model_id: str,
    frames_dir: Path,
    timeout_seconds: float = 600.0,
    decode_config: dict[str, Any] | None = None,
    output_path: Path | None = None,
    meta_output_path: Path | None = None,
    verify_record_lineage: bool = True,
) -> tuple[list[dict], dict[str, Any]]:
    """Validate all inputs up-front, run backend per candidate, and stream predictions."""
    require_text({"run_id": run_id}, "run_id", "run")
    require_text({"prompt_id": prompt_id}, "prompt_id", "run")
    require_text({"model_id": model_id}, "model_id", "run")
    if backend.backend_name != "fake" and model_id.strip() == "fake":
        raise InputError(f"{backend.backend_name} backend refuses --model-id fake")

    samples = _validate_manifest_samples(manifest)
    prepared: list[tuple[str, dict, tuple[Path, ...], tuple[float, ...]]] = []
    seen_cids: set[str] = set()
    for record in records:
        cid = _validate_record_against_manifest(record, samples)
        if cid in seen_cids:
            raise InputError(f"duplicate candidate_id in input records: {cid}")
        seen_cids.add(cid)
        if verify_record_lineage and "lineage_media" in record:
            if failures := verify_lineage(record):
                raise InputError(f"{cid}: lineage check failed before inference: {' | '.join(failures)}")
        frame_paths, frame_pts = _resolve_record_frames(record, frames_dir)
        prepared.append((cid, record, frame_paths, frame_pts))

    predictions: list[dict] = []
    request_metas: list[dict[str, Any]] = []
    stream = Path(output_path).open("x", encoding="utf-8") if output_path is not None else None
    try:
        for cid, record, frame_paths, frame_pts in prepared:
            req = InferenceRequest(
                candidate_id=cid,
                record=record,
                frame_paths=frame_paths,
                frame_pts_seconds=frame_pts,
                prompt_text=prompt_text,
                timeout_seconds=timeout_seconds,
                decode_config=dict(decode_config or {}),
            )
            result = normalize_result(backend.infer_one(req))
            row = {
                "candidate_id": cid,
                "clip_sha256": record["clip_sha256"],
                "run_id": run_id,
                "model_id": model_id,
                "prompt_id": prompt_id,
                "input_id": record["input_id"],
                "request_id": f"{run_id}/{cid}",
                "raw_output": result.raw_output,
                "status": result.status,
                "input_review_id": None,
            }
            predictions.append(row)
            request_metas.append({
                "candidate_id": cid,
                "request_id": row["request_id"],
                "input_id": row["input_id"],
                "status": result.status,
                "latency_seconds": result.latency_seconds,
                "error_detail": result.error_detail,
                "reasoning_content": result.reasoning_content,
                "extra_meta": result.extra_meta,
            })
            if stream is not None:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
    finally:
        if stream is not None:
            stream.close()

    run_meta: dict[str, Any] = {
        "run_id": run_id,
        "model_id": model_id,
        "prompt_id": prompt_id,
        "sampling_policy": _extract_sampling_policy(records),
        "backend_identity": backend.run_identity(),
        "total_requests": len(predictions),
        "status_counts": {
            status: sum(1 for row in predictions if row["status"] == status)
            for status in ("success", "request_failed", "timeout")
        },
        "requests": request_metas,
    }
    if meta_output_path is not None:
        with Path(meta_output_path).open("x", encoding="utf-8") as meta_stream:
            meta_stream.write(json.dumps(run_meta, ensure_ascii=False, indent=2) + "\n")
    return predictions, run_meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Scoring manifest to bind requests to")
    parser.add_argument("--candidate-ids", help="JSON array of candidate IDs selecting record order")
    parser.add_argument("--profile", help="Path profile; only needed to default --input-config")
    parser.add_argument("--model-id", default="fake")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prompt-file", required=True, help="Prompt text file; exact bytes sent and hashed")
    parser.add_argument("--input-config", help="frames records JSONL; defaults to profile output_dir/records.jsonl")
    parser.add_argument("--frames-dir", help="Directory holding <candidate_id>/frame_*.png; defaults to --input-config parent")
    parser.add_argument("--output", required=True, help="New predictions JSONL; never overwrites")
    parser.add_argument("--meta-output", help="Optional run metadata JSON path (defaults to <output>.meta.json for real backends)")
    parser.add_argument("--backend", default="fake", choices=("fake", "http", "transformers"))
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-request timeout in seconds")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
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
        help="Optional JSON mapping {relative_file: sha256} verified fail-closed before trust_remote_code",
    )
    args = parser.parse_args(argv)
    try:
        profiles = paths.load_profile(args.profile) if args.profile else None
        if not args.input_config and profiles is None:
            raise InputError("provide --input-config or --profile")
        input_config = Path(args.input_config) if args.input_config else profiles["output_dir"] / "records.jsonl"
        prompt_text, prompt_identity = load_prompt(args.prompt_file)
        records = read_records(input_config)
        if args.candidate_ids:
            selected = decode_file(Path(args.candidate_ids).read_text(encoding="utf-8"), args.candidate_ids)
            if not isinstance(selected, list) or not selected:
                raise InputError("candidate IDs must be a nonempty JSON array")
            by_id = {record.get("candidate_id"): record for record in records}
            duplicated = sorted(cid for cid in set(selected) if selected.count(cid) > 1)
            missing = [cid for cid in selected if cid not in by_id]
            if duplicated or missing:
                raise InputError(
                    f"duplicate candidate_id in candidate_ids: {duplicated}"
                    if duplicated
                    else f"candidate_id not found in input records: {missing}"
                )
            records = [by_id[cid] for cid in selected]

        manifest = read_json(args.manifest)
        if args.backend == "fake":
            if args.model_id != "fake":
                raise InputError("fake backend only accepts --model-id fake")
            predictions = plan_predictions(
                records, manifest, args.run_id, prompt_identity, model_id=args.model_id
            )
            with Path(args.output).open("x", encoding="utf-8") as stream:
                for row in predictions:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"Wrote {len(predictions)} predictions to {args.output}; backend={args.backend}; "
                f"prompt_id={prompt_identity}"
            )
            return 0

        frames_dir = Path(args.frames_dir) if args.frames_dir else input_config.parent
        meta_output = Path(args.meta_output) if args.meta_output else Path(f"{args.output}.meta.json")
        sampling_policy = _extract_sampling_policy(records)
        decode_config = {
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "seed": args.seed,
        }

        backend: InferenceBackend
        if args.backend == "http":
            if not args.endpoint:
                raise InputError("--endpoint is required for --backend http")
            backend = HttpBackend(
                endpoint=args.endpoint,
                model_id=args.model_id,
                api_model_name=args.api_model_name,
                api_key_env=args.api_key_env,
                timeout_seconds=args.timeout,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                seed=args.seed,
                max_pixels=args.max_pixels,
                sampling_policy=sampling_policy,
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
                seed=args.seed,
                max_pixels=args.max_pixels,
                max_slice_nums=args.max_slice_nums,
                sampling_policy=sampling_policy,
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
            )
        finally:
            backend.close()
        print(
            f"Wrote {len(predictions)} predictions to {args.output}; backend={args.backend}; "
            f"prompt_id={prompt_identity}; meta={meta_output}"
        )
        return 0
    except (InputError, OSError, UnicodeError, NotImplementedError, paths.EvalPathError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
