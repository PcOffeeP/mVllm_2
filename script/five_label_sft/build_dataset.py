"""Dual-channel (8f images / 16f <video>) Fold SFT ShareGPT dataset builder."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any

from script.five_label_eval.errors import InputError
from script.five_label_eval.exclusions import candidate_ids_sha256
from script.five_label_eval.frames import (
    DEFAULT_RESIZE,
    RECORD_SCHEMA,
    SAMPLING_RULE,
    SHORT_CLIP_POLICY,
    sample_frame_indices,
    size_bucket,
)
from script.five_label_eval.prompt_id import load_prompt
from script.five_label_eval.score import FIELDS, decode_file, extract, flatten

from .constants import (
    BUILD_SUMMARY_SCHEMA,
    DEFAULT_PROMPT_REL,
    REPO_ROOT,
    SUPPORTED_FOLDS,
    SUPPORTED_MODALITIES,
    SUPPORTED_NUM_FRAMES,
    WIDTH_BUCKETS,
    get_channel_preset,
)
from .data_guards import (
    FoldIsolationContext,
    RESERVED_DATASET_NAMES,
    SelectedTrainSample,
    assert_no_fold_leakage,
    assert_no_symlink_components,
    load_fold_isolation_context,
    safe_write_bytes,
    select_confirmed_fold_train_samples,
    sha256_bytes,
    sha256_file,
    validate_dataset_name,
    validate_safe_output_path,
)
from .preflight import run_preflight_on_samples

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NATURAL_TOKEN_RE = re.compile(r"(\d+)")


def _natural_sort_key(name: str) -> list[tuple[int, int | str]]:
    return [
        (0, int(tok)) if tok.isdigit() else (1, tok)
        for tok in _NATURAL_TOKEN_RE.split(name)
        if tok
    ]


def _validate_safe_component(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise InputError(f"{label} must be a single safe path component, got {value!r}")
    return value


def _rel_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _load_frames_manifest(path: Path) -> dict[str, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read frames manifest {path}: {exc}") from exc
    by_cid: dict[str, dict[str, Any]] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        obj = decode_file(raw, f"{path}:{lineno}")
        if not isinstance(obj, dict):
            raise InputError(f"{path}:{lineno}: expected JSON object")
        cid = obj.get("candidate_id")
        if not isinstance(cid, str) or not cid.strip():
            raise InputError(f"{path}:{lineno}: missing candidate_id")
        if cid in by_cid:
            raise InputError(f"{path}:{lineno}: duplicate candidate_id {cid!r}")
        by_cid[cid] = obj
    return by_cid


def _format_emitted_frame_path(
    *,
    resolved_path: Path | None,
    candidate_id: str,
    image_name: str,
    frames_dir: Path | None,
    frame_path_prefix: str | None,
) -> str:
    if frame_path_prefix is not None:
        prefix = frame_path_prefix.rstrip("/")
        return f"{prefix}/{candidate_id}/{image_name}"
    if resolved_path is not None:
        return str(resolved_path)
    base = str(frames_dir.resolve()) if frames_dir is not None else "DRY_RUN_FRAMES"
    return f"{base.rstrip('/')}/{candidate_id}/{image_name}"


def _verify_png_file(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_size: tuple[int, int] | None = None,
    context: str,
) -> None:
    if path.is_symlink():
        raise InputError(f"{context}: L3 frame PNG must not be a symlink: {path}")
    if not path.is_file():
        raise InputError(f"{context}: L3 frame PNG missing on disk: {path}")
    raw = path.read_bytes()
    if not raw.startswith(PNG_MAGIC):
        raise InputError(f"{context}: L3 frame is not a valid PNG file: {path}")
    if expected_size is not None:
        if len(raw) < 24 or raw[12:16] != b"IHDR":
            raise InputError(f"{context}: L3 frame PNG missing valid IHDR header: {path}")
        png_w, png_h = struct.unpack("!II", raw[16:24])
        if (png_w, png_h) != expected_size:
            raise InputError(
                f"{context}: L3 frame PNG dimensions {png_w}x{png_h} != manifest {expected_size[0]}x{expected_size[1]} ({path})"
            )
    if expected_sha256 is not None:
        actual = sha256_bytes(raw)
        if actual != expected_sha256:
            raise InputError(
                f"{context}: L3 frame PNG sha256 mismatch for {path}: "
                f"expected {expected_sha256}, got {actual}"
            )


def _resolve_sample_frames_from_manifest(
    sample: SelectedTrainSample,
    record: dict[str, Any],
    *,
    ctx: FoldIsolationContext,
    num_frames: int,
    frames_dir: Path,
    frame_path_prefix: str | None,
    allow_missing_frames_dry_run: bool,
) -> tuple[list[str], dict[str, str]]:
    cid = _validate_safe_component(sample.candidate_id, "candidate_id")
    if record.get("record_schema") != RECORD_SCHEMA:
        raise InputError(f"{cid}: record_schema {record.get('record_schema')!r} != {RECORD_SCHEMA!r}")
    if record.get("manifest_sha256") != ctx.manifest_sha256:
        raise InputError(
            f"{cid}: record manifest_sha256 {record.get('manifest_sha256')!r} != {ctx.manifest_sha256!r}"
        )
    if record.get("clip_sha256") != sample.clip_sha256:
        raise InputError(
            f"{cid}: record clip_sha256 {record.get('clip_sha256')!r} != {sample.clip_sha256!r}"
        )
    sampling = record.get("sampling")
    if not isinstance(sampling, dict):
        raise InputError(f"{cid}: record missing sampling metadata")
    expected_sampling = {
        "sampling_rule": SAMPLING_RULE,
        "target_frame_count": num_frames,
        "short_clip_policy": SHORT_CLIP_POLICY,
        "resize": DEFAULT_RESIZE,
    }
    actual_sampling = {k: sampling.get(k) for k in expected_sampling}
    if actual_sampling != expected_sampling:
        raise InputError(f"{cid}: sampling policy {actual_sampling!r} != required {expected_sampling!r}")

    raw_frames = record.get("frames")
    if not isinstance(raw_frames, list) or len(raw_frames) != num_frames:
        raise InputError(
            f"{cid}: expected exactly {num_frames} frames in record, got "
            f"{len(raw_frames) if isinstance(raw_frames, list) else type(raw_frames).__name__}"
        )
    ordered = sorted(raw_frames, key=lambda item: item.get("display_order", -1) if isinstance(item, dict) else -1)
    expected_indices = sample_frame_indices(sample.total_frames, num_frames)
    actual_indices = [item.get("clip_frame_index") if isinstance(item, dict) else None for item in ordered]
    if actual_indices != expected_indices:
        raise InputError(
            f"{cid}: clip_frame_index sequence {actual_indices} != {expected_indices} "
            f"for total_frames={sample.total_frames}, num_frames={num_frames}"
        )

    root_dir = frames_dir.resolve()
    raw_clip_dir = frames_dir / cid
    if not allow_missing_frames_dry_run:
        if raw_clip_dir.is_symlink():
            raise InputError(f"{cid}: candidate frame directory must not be a symlink: {raw_clip_dir}")
        clip_dir = raw_clip_dir.resolve()
        try:
            clip_dir.relative_to(root_dir)
        except ValueError as exc:
            raise InputError(f"{cid}: candidate frame directory escapes frames_dir: {clip_dir}") from exc
    else:
        clip_dir = raw_clip_dir.resolve()

    seen_names: set[str] = set()
    emitted: list[str] = []
    verified_shas: dict[str, str] = {}
    for expected_order, entry in enumerate(ordered):
        if not isinstance(entry, dict):
            raise InputError(f"{cid}: frames[{expected_order}] must be object")
        if entry.get("display_order") != expected_order:
            raise InputError(
                f"{cid}: frames display_order must be contiguous 0..{num_frames - 1}, got {entry.get('display_order')!r}"
            )
        image_name = _validate_safe_component(entry.get("image"), f"{cid}: frames[{expected_order}].image")
        if image_name in seen_names:
            raise InputError(f"{cid}: duplicate frame image filename {image_name!r}")
        seen_names.add(image_name)
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            raise InputError(f"{cid}: frames[{expected_order}].sha256 missing or invalid")

        raw_img_path = clip_dir / image_name
        if not allow_missing_frames_dry_run:
            if raw_img_path.is_symlink():
                raise InputError(f"{cid}: L3 frame PNG must not be a symlink: {raw_img_path}")
            resolved_img = raw_img_path.resolve()
            try:
                resolved_img.relative_to(clip_dir)
            except ValueError as exc:
                raise InputError(f"{cid}: L3 frame PNG escapes candidate directory: {resolved_img}") from exc
            _verify_png_file(
                resolved_img,
                expected_sha256=expected_sha,
                expected_size=(sample.width, sample.height),
                context=cid,
            )
            emitted_path = _format_emitted_frame_path(
                resolved_path=resolved_img,
                candidate_id=cid,
                image_name=image_name,
                frames_dir=frames_dir,
                frame_path_prefix=frame_path_prefix,
            )
            emitted.append(emitted_path)
            verified_shas[emitted_path] = expected_sha
        else:
            emitted.append(
                _format_emitted_frame_path(
                    resolved_path=None,
                    candidate_id=cid,
                    image_name=image_name,
                    frames_dir=frames_dir,
                    frame_path_prefix=frame_path_prefix,
                )
            )
    return emitted, verified_shas


def _resolve_sample_frames_from_dir(
    sample: SelectedTrainSample,
    *,
    num_frames: int,
    frames_dir: Path | None,
    frame_path_prefix: str | None,
    allow_missing_frames_dry_run: bool,
) -> list[str]:
    cid = _validate_safe_component(sample.candidate_id, "candidate_id")
    if frames_dir is None:
        if not allow_missing_frames_dry_run:
            raise InputError(
                "missing --frames-dir or --frames-manifest; pass real L3 frames or --allow-missing-frames-dry-run"
            )
        return [
            _format_emitted_frame_path(
                resolved_path=None,
                candidate_id=cid,
                image_name=f"frame_{idx:02d}.png",
                frames_dir=None,
                frame_path_prefix=frame_path_prefix,
            )
            for idx in range(num_frames)
        ]

    root_dir = frames_dir.resolve()
    raw_clip_dir = frames_dir / cid
    if not raw_clip_dir.exists():
        if allow_missing_frames_dry_run:
            return [
                _format_emitted_frame_path(
                    resolved_path=None,
                    candidate_id=cid,
                    image_name=f"frame_{idx:02d}.png",
                    frames_dir=frames_dir,
                    frame_path_prefix=frame_path_prefix,
                )
                for idx in range(num_frames)
            ]
        raise InputError(f"{cid}: candidate frame directory missing on disk: {raw_clip_dir}")

    if raw_clip_dir.is_symlink():
        raise InputError(f"{cid}: candidate frame directory must not be a symlink: {raw_clip_dir}")
    clip_dir = raw_clip_dir.resolve()
    try:
        clip_dir.relative_to(root_dir)
    except ValueError as exc:
        raise InputError(f"{cid}: candidate frame directory escapes frames_dir: {clip_dir}") from exc
    if not clip_dir.is_dir():
        raise InputError(f"{cid}: expected candidate frame directory, got file: {clip_dir}")

    pngs = sorted((p for p in clip_dir.iterdir() if p.suffix.lower() == ".png"), key=lambda p: _natural_sort_key(p.name))
    if len(pngs) != num_frames:
        raise InputError(f"{cid}: expected exactly {num_frames} PNG frames in {clip_dir}, found {len(pngs)}")

    emitted: list[str] = []
    for raw_img in pngs:
        image_name = _validate_safe_component(raw_img.name, f"{cid}: frame filename")
        if raw_img.is_symlink():
            raise InputError(f"{cid}: L3 frame PNG must not be a symlink: {raw_img}")
        resolved_img = raw_img.resolve()
        try:
            resolved_img.relative_to(clip_dir)
        except ValueError as exc:
            raise InputError(f"{cid}: L3 frame PNG escapes candidate directory: {resolved_img}") from exc
        _verify_png_file(resolved_img, expected_sha256=None, context=cid)
        emitted.append(
            _format_emitted_frame_path(
                resolved_path=resolved_img,
                candidate_id=cid,
                image_name=image_name,
                frames_dir=frames_dir,
                frame_path_prefix=frame_path_prefix,
            )
        )
    return emitted


def build_sharegpt_record(
    *,
    modality: str,
    num_frames: int,
    prompt_text: str,
    target_json: str,
    frame_paths: list[str],
) -> dict[str, Any]:
    """Construct and validate one LlamaFactory ShareGPT multimodal SFT example.

    Strictly avoids inserting a ``system`` turn in ``messages[0]`` so zero-shot prompt
    alignment is preserved and LlamaFactory ``mm_plugin.py:2427`` ``video_metadata[idx]``
    IndexError is avoided.
    """
    if modality not in SUPPORTED_MODALITIES:
        raise InputError(f"unsupported modality {modality!r}")
    if len(frame_paths) != num_frames:
        raise InputError(f"expected {num_frames} frame paths, got {len(frame_paths)}")
    if "<image>" in prompt_text or "<video>" in prompt_text:
        raise InputError("prompt text must not contain literal <image> or <video> media placeholders")

    parsed = extract(target_json)
    if not parsed["strict_format_valid"] or parsed["issues"] or parsed["conflicts"]:
        raise InputError(
            f"refusing to emit non-strict target JSON: issues={parsed['issues']!r}, conflicts={parsed['conflicts']!r}"
        )

    if modality == "images":
        user_content = ("<image>" * num_frames) + "\n" + prompt_text
        record: dict[str, Any] = {
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": target_json},
            ],
            "images": list(frame_paths),
        }
        assert record["messages"][0]["content"].count("<image>") == num_frames
        assert record["messages"][0]["content"].count("<video>") == 0
    else:
        user_content = "<video>\n" + prompt_text
        record = {
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": target_json},
            ],
            "videos": [list(frame_paths)],
        }
        assert record["messages"][0]["content"].count("<video>") == 1
        assert record["messages"][0]["content"].count("<image>") == 0

    return record


def build_dataset_info_fragment(*, dataset_name: str, file_name: str, modality: str) -> dict[str, Any]:
    """Build LlamaFactory ``dataset_info.json`` entry matching ``mllm_demo`` / ``mllm_video_demo``."""
    if modality not in SUPPORTED_MODALITIES:
        raise InputError(f"unsupported modality {modality!r}")
    media_col = "images" if modality == "images" else "videos"
    return {
        dataset_name: {
            "file_name": file_name,
            "formatting": "sharegpt",
            "columns": {
                "messages": "messages",
                media_col: media_col,
            },
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
            },
        }
    }


def _compute_distributions(samples: list[SelectedTrainSample]) -> dict[str, Any]:
    wb_clips: Counter[str] = Counter()
    wb_sources: dict[str, set[str]] = defaultdict(set)
    roles: Counter[str] = Counter()
    label_counts: dict[str, Counter[str]] = {field: Counter() for field in FIELDS}

    for s in samples:
        wb = size_bucket(s.width)
        wb_clips[wb] += 1
        wb_sources[wb].add(s.source_id)
        roles[s.role] += 1
        flat = flatten(s.labels)
        for field in FIELDS:
            label_counts[field][str(flat[field])] += 1

    return {
        "size_buckets": {
            wb: {"candidates": wb_clips[wb], "sources": len(wb_sources[wb])}
            for wb in WIDTH_BUCKETS
        },
        "roles": dict(sorted(roles.items())),
        "labels": {field: dict(sorted(label_counts[field].items())) for field in FIELDS},
    }


def build_fold_sft_dataset(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    output_dir: Path | str,
    dataset_name: str | None = None,
    frames_manifest: Path | str | None = None,
    frames_dir: Path | str | None = None,
    frame_path_prefix: str | None = None,
    allow_missing_frames_dry_run: bool = False,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path | None = None,
    reviews_path: Path | None = None,
    splits_dir: Path | None = None,
    exclusions_path: Path | None = None,
    eval_dev_path: Path | None = None,
    eval_test_path: Path | None = None,
    prompt_path: Path | None = None,
    cutoff_len: int | None = None,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    max_safe_train_frame_pixels: int | None = None,
    fail_on_lf_downscale: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Build and write a leakage-free Fold k SFT dataset bundle to ``output_dir``."""
    preset = get_channel_preset(modality, num_frames)
    validate_safe_output_path(output_dir, label="output_dir")
    root = Path(repo_root).resolve()
    out_dir = Path(output_dir)
    if out_dir.is_symlink():
        raise InputError(f"output_dir must not be a symlink: {out_dir}")
    ds_name = validate_dataset_name(
        dataset_name or f"tensile_five_label_fold{fold}_{modality}_{num_frames}f",
        label="dataset_name",
    )
    if frames_manifest is None and not allow_missing_frames_dry_run:
        raise InputError(
            "non-dry-run export requires --frames-manifest (records*.jsonl from frames.py) "
            "to cryptographically bind L3 PNG frames to manifest_sha256, clip_sha256, sampling order, "
            "and per-frame sha256; pass --allow-missing-frames-dry-run only for offline dry-run audits"
        )
    if frame_path_prefix is not None and not allow_missing_frames_dry_run:
        raise InputError(
            "--frame-path-prefix is forbidden in non-dry-run export because emitted paths must "
            "exactly match the SHA-256-verified local L3 PNG paths; run export directly on the "
            "target host or pass --allow-missing-frames-dry-run for offline dry-run audits"
        )

    p_path = Path(prompt_path) if prompt_path is not None else root / DEFAULT_PROMPT_REL
    if not p_path.is_file():
        raise InputError(f"missing prompt file: {p_path}")
    prompt_text, prompt_id = load_prompt(p_path)

    ctx = load_fold_isolation_context(
        fold,
        repo_root=root,
        manifest_path=manifest_path,
        reviews_path=reviews_path,
        splits_dir=splits_dir,
        exclusions_path=exclusions_path,
        eval_dev_path=eval_dev_path,
        eval_test_path=eval_test_path,
    )
    samples, guard_meta = select_confirmed_fold_train_samples(ctx)

    # Re-assert leakage invariants explicitly right before building records.
    isolation_checks = assert_no_fold_leakage(ctx, samples, context=f"build_dataset:fold_{fold}")

    # Offline token/cutoff_len & short-clip preflight (fail-closed).
    preflight_report = run_preflight_on_samples(
        samples,
        modality=modality,
        num_frames=num_frames,
        cutoff_len=cutoff_len if cutoff_len is not None else preset.cutoff_len,
        image_max_pixels=image_max_pixels,
        image_min_pixels=image_min_pixels,
        video_max_pixels=video_max_pixels,
        video_min_pixels=video_min_pixels,
        max_safe_train_frame_pixels=max_safe_train_frame_pixels,
        prompt_text=prompt_text,
        fail_on_exceed=True,
        fail_on_short_clip=True,
        fail_on_gpu_pixel_guard=True,
        fail_on_lf_downscale=fail_on_lf_downscale,
    )
    preflight_report["fold"] = fold
    preflight_report["scope"] = "confirmed_train"

    manifest_records: dict[str, dict[str, Any]] | None = None
    f_manifest_path = Path(frames_manifest) if frames_manifest is not None else None
    f_dir_path = Path(frames_dir) if frames_dir is not None else None
    if f_manifest_path is not None:
        manifest_records = _load_frames_manifest(f_manifest_path)
        if f_dir_path is None:
            f_dir_path = f_manifest_path.resolve().parent

    dataset_rows: list[dict[str, Any]] = []
    verified_frame_sha256s: dict[str, str] = {}
    for sample in samples:
        if manifest_records is not None:
            rec = manifest_records.get(sample.candidate_id)
            if rec is None:
                raise InputError(f"{sample.candidate_id}: missing from --frames-manifest {f_manifest_path}")
            assert f_dir_path is not None
            frame_paths, sample_shas = _resolve_sample_frames_from_manifest(
                sample,
                rec,
                ctx=ctx,
                num_frames=num_frames,
                frames_dir=f_dir_path,
                frame_path_prefix=frame_path_prefix,
                allow_missing_frames_dry_run=allow_missing_frames_dry_run,
            )
            verified_frame_sha256s.update(sample_shas)
        else:
            frame_paths = _resolve_sample_frames_from_dir(
                sample,
                num_frames=num_frames,
                frames_dir=f_dir_path,
                frame_path_prefix=frame_path_prefix,
                allow_missing_frames_dry_run=allow_missing_frames_dry_run,
            )
        dataset_rows.append(
            build_sharegpt_record(
                modality=modality,
                num_frames=num_frames,
                prompt_text=prompt_text,
                target_json=sample.target_json,
                frame_paths=frame_paths,
            )
        )

    dataset_file_name = f"{ds_name}.json"
    dataset_info = build_dataset_info_fragment(
        dataset_name=ds_name,
        file_name=dataset_file_name,
        modality=modality,
    )

    dataset_bytes = (json.dumps(dataset_rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    dataset_info_bytes = (json.dumps(dataset_info, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    preflight_bytes = (json.dumps(preflight_report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")

    summary: dict[str, Any] = {
        "schema": BUILD_SUMMARY_SCHEMA,
        "dataset_name": ds_name,
        "dataset_file": dataset_file_name,
        "fold": fold,
        "modality": modality,
        "num_frames": num_frames,
        "dry_run_missing_frames": bool(allow_missing_frames_dry_run),
        "strict_target_json_verified": True,
        "inputs": {
            "manifest_path": _rel_or_abs(ctx.manifest_path, root),
            "manifest_sha256": ctx.manifest_sha256,
            "reviews_path": _rel_or_abs(ctx.reviews_path, root),
            "reviews_sha256": ctx.reviews_sha256,
            "dev_exclusions_path": ctx.exclusions.path or _rel_or_abs(ctx.exclusions_path, root),
            "dev_exclusions_sha256": ctx.exclusions.sha256,
            "dev_exclusions_extra_path": ctx.exclusions.extra_path,
            "dev_exclusions_extra_sha256": ctx.exclusions.extra_sha256,
            "fold_train_path": _rel_or_abs(ctx.fold_train_path, root),
            "fold_train_sha256": ctx.fold_train_sha256,
            "fold_val_path": _rel_or_abs(ctx.fold_val_path, root),
            "fold_val_sha256": ctx.fold_val_sha256,
            "test_path": _rel_or_abs(ctx.test_path, root),
            "test_sha256": ctx.test_sha256,
            "eval_dev_path": _rel_or_abs(ctx.eval_dev_path, root),
            "eval_dev_sha256": ctx.eval_dev_sha256,
            "eval_test_path": _rel_or_abs(ctx.eval_test_path, root),
            "eval_test_sha256": ctx.eval_test_sha256,
            "prompt_path": _rel_or_abs(p_path, root),
            "prompt_id": prompt_id,
            "label_rules_sha256": ctx.label_rules_sha256,
            "split_identity_sha256": ctx.split_identity_sha256,
            "frames_manifest_path": str(f_manifest_path) if f_manifest_path is not None else None,
            "frames_manifest_sha256": sha256_file(f_manifest_path) if f_manifest_path is not None else None,
            "frames_dir": str(f_dir_path) if f_dir_path is not None else None,
        },
        "isolation_checks": isolation_checks,
        "skipped_revisions": guard_meta["skipped"],
        "distributions": _compute_distributions(samples),
        "fingerprints": {
            "dataset_sha256": sha256_bytes(dataset_bytes),
            "dataset_info_sha256": sha256_bytes(dataset_info_bytes),
            "preflight_report_sha256": sha256_bytes(preflight_bytes),
            "candidate_ids_sha256": candidate_ids_sha256([s.candidate_id for s in samples]),
        },
        "preflight_summary": {
            "cutoff_len": preflight_report["cutoff_len"],
            "max_safe_train_frame_pixels": preflight_report["max_safe_train_frame_pixels"],
            "min_total_frames": preflight_report["min_total_frames"],
            "short_clip_count": preflight_report["short_clip_count"],
            "exceeds_cutoff_count": preflight_report["exceeds_cutoff_count"],
            "exceeds_gpu_frame_pixel_guard_count": preflight_report["exceeds_gpu_frame_pixel_guard_count"],
            "lf_downscale_triggered_count": preflight_report["lf_downscale_triggered_count"],
            "lf_preprocess_resized_count": preflight_report["lf_preprocess_resized_count"],
            "vllm_grid_mismatch_count": preflight_report["vllm_grid_mismatch_count"],
            "vllm_grid_aligned": preflight_report["vllm_grid_aligned"],
            "vllm_alignment_clean": preflight_report["vllm_alignment_clean"],
            "visual_pad_tokens": preflight_report["visual_pad_tokens"],
            "estimated_total_tokens": preflight_report["estimated_total_tokens"],
        },
        "exported_source_ids": sorted({s.source_id for s in samples}),
        "exported_candidate_ids": [s.candidate_id for s in samples],
        "verified_frame_sha256s": dict(sorted(verified_frame_sha256s.items())),
    }
    summary_bytes = (json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")

    targets = [
        (out_dir / dataset_file_name, dataset_bytes, "dataset_json"),
        (out_dir / "dataset_info.json", dataset_info_bytes, "dataset_info"),
        (out_dir / "build_summary.json", summary_bytes, "build_summary"),
        (out_dir / "preflight_report.json", preflight_bytes, "preflight_report"),
    ]
    resolved_targets_ci = [str(p.resolve()).lower() for p, _, _ in targets]
    if len(set(resolved_targets_ci)) != len(targets):
        raise InputError(f"output artifact paths collide (case-insensitive): {[str(p) for p, _, _ in targets]}")
    for path, _, label in targets:
        validate_safe_output_path(path, label=label)
        assert_no_symlink_components(path, label=label)
    if not overwrite:
        existing = [str(p) for p, _, _ in targets if p.exists()]
        if existing:
            raise InputError(f"refusing to overwrite existing output files (pass --overwrite to force): {existing}")
    else:
        existing_summary_path = out_dir / "build_summary.json"
        if existing_summary_path.is_file() and not existing_summary_path.is_symlink():
            try:
                prev_summary = decode_file(existing_summary_path.read_text(encoding="utf-8"), str(existing_summary_path))
            except (InputError, OSError, UnicodeError):
                prev_summary = None
            if isinstance(prev_summary, dict) and prev_summary.get("fold") not in (None, fold):
                raise InputError(
                    f"refusing to overwrite existing fold_{prev_summary.get('fold')} bundle in {out_dir} "
                    f"with fold_{fold} export; use a fold-specific output directory"
                )

    out_dir.mkdir(parents=True, exist_ok=True)
    for path, content, label in targets:
        safe_write_bytes(path, content, overwrite=overwrite, label=label)

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, choices=SUPPORTED_FOLDS, required=True, help="CV fold (0, 1, or 2)")
    parser.add_argument("--modality", choices=SUPPORTED_MODALITIES, required=True, help="Channel modality: images or video")
    parser.add_argument("--num-frames", type=int, choices=SUPPORTED_NUM_FRAMES, required=True, help="Number of L3 frames per clip")
    parser.add_argument("--output-dir", required=True, help="Directory to write dataset JSON, dataset_info.json, and summaries")
    parser.add_argument("--dataset-name", help="LlamaFactory dataset key (default: tensile_five_label_fold{k}_{modality}_{K}f)")
    parser.add_argument("--frames-manifest", help="Optional records*.jsonl from script/five_label_eval/frames.py")
    parser.add_argument("--frames-dir", help="Directory containing <candidate_id>/*.png L3 frames")
    parser.add_argument("--frame-path-prefix", help="Optional path prefix emitted in ShareGPT JSON (e.g. training-machine absolute dir)")
    parser.add_argument("--allow-missing-frames-dry-run", action="store_true",
                        help="Allow dry-run export without L3 PNG files on disk (marks dry_run_missing_frames=true)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repository root path")
    parser.add_argument("--manifest", help="Override data/sub_video/manifest.json path")
    parser.add_argument("--reviews", help="Override data/subvideo-review/reviews.json path")
    parser.add_argument("--splits-dir", help="Override data/splits/three-fold directory")
    parser.add_argument("--exclusions", help="Override data/splits/dev-exclusions.json path")
    parser.add_argument("--eval-dev", help="Override data/eval-subsets/eval-dev-v1.json path")
    parser.add_argument("--eval-test", help="Override data/eval-subsets/eval-test-v1.json path")
    parser.add_argument("--prompt", help="Override five_label_v2.txt path")
    parser.add_argument("--cutoff-len", type=int, help="Override cutoff_len preflight limit")
    parser.add_argument("--image-max-pixels", type=int, help="Override image_max_pixels (images mode)")
    parser.add_argument("--image-min-pixels", type=int, help="Override image_min_pixels (images mode)")
    parser.add_argument("--video-max-pixels", type=int, help="Override video_max_pixels (video mode)")
    parser.add_argument("--video-min-pixels", type=int, help="Override video_min_pixels (video mode)")
    parser.add_argument("--max-safe-train-frame-pixels", type=int, help="Override RTX 4090 safe single-frame pixel guard")
    parser.add_argument("--fail-on-lf-downscale", "--fail-on-vllm-mismatch", dest="fail_on_lf_downscale", action="store_true",
                        help="Fail closed if any sample triggers LlamaFactory pre-resize or vLLM grid mismatch")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files in --output-dir")
    args = parser.parse_args(argv)

    try:
        summary = build_fold_sft_dataset(
            fold=args.fold,
            modality=args.modality,
            num_frames=args.num_frames,
            output_dir=Path(args.output_dir),
            dataset_name=args.dataset_name,
            frames_manifest=Path(args.frames_manifest) if args.frames_manifest else None,
            frames_dir=Path(args.frames_dir) if args.frames_dir else None,
            frame_path_prefix=args.frame_path_prefix,
            allow_missing_frames_dry_run=args.allow_missing_frames_dry_run,
            repo_root=Path(args.repo_root),
            manifest_path=Path(args.manifest) if args.manifest else None,
            reviews_path=Path(args.reviews) if args.reviews else None,
            splits_dir=Path(args.splits_dir) if args.splits_dir else None,
            exclusions_path=Path(args.exclusions) if args.exclusions else None,
            eval_dev_path=Path(args.eval_dev) if args.eval_dev else None,
            eval_test_path=Path(args.eval_test) if args.eval_test else None,
            prompt_path=Path(args.prompt) if args.prompt else None,
            cutoff_len=args.cutoff_len,
            image_max_pixels=args.image_max_pixels,
            image_min_pixels=args.image_min_pixels,
            video_max_pixels=args.video_max_pixels,
            video_min_pixels=args.video_min_pixels,
            max_safe_train_frame_pixels=args.max_safe_train_frame_pixels,
            fail_on_lf_downscale=args.fail_on_lf_downscale,
            overwrite=args.overwrite,
        )
        print(
            f"Wrote {args.output_dir}/{summary['dataset_file']} "
            f"(fold={summary['fold']}, modality={summary['modality']}, num_frames={summary['num_frames']}, "
            f"samples={summary['isolation_checks']['exported_candidate_count']}, "
            f"sources={summary['isolation_checks']['exported_source_count']}/{summary['isolation_checks']['clean_train_source_pool_count']}, "
            f"dry_run={summary['dry_run_missing_frames']}, "
            f"max_est_tokens={summary['preflight_summary']['estimated_total_tokens']['max']}/{summary['preflight_summary']['cutoff_len']})"
        )
        return 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
