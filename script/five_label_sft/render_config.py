"""Render LlamaFactory 4-bit QLoRA YAML and paired vLLM LoRA evaluation commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable

import yaml

from script.five_label_eval.errors import InputError
from script.five_label_eval.score import decode_file

from .constants import (
    ADAPTER_PROVENANCE_SCHEMA,
    BUILD_SUMMARY_SCHEMA,
    CONFIG_MANIFEST_SCHEMA,
    CUDA_ALLOC_CONF,
    DEFAULT_BASE_MODEL_PATH,
    DEFAULT_SERVED_MODEL_NAME,
    DEFAULT_TEMPLATE,
    FRAME_LINEAGE_SCHEMA,
    PURE_SYSTEM_PATH,
    SUPPORTED_FOLDS,
    SUPPORTED_MODALITIES,
    SUPPORTED_NUM_FRAMES,
    VLM_EVAL_VLLM_BIN,
    VLM_SFT_LLAMAFACTORY_CLI,
    VLM_SFT_PYTHON_BIN,
    get_channel_preset,
)
from .data_guards import (
    assert_no_input_output_collision,
    assert_no_symlink_components,
    safe_write_bytes,
    sha256_file,
    validate_dataset_name,
    validate_fold,
    validate_safe_output_path,
)

ADAPTER_PROVENANCE_FILENAME = "sft_adapter_provenance.json"


def _require_pos_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputError(f"{name} must be a positive integer, got {value!r}")
    return value


def _require_pos_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise InputError(f"{name} must be a positive finite number, got {value!r}")
    return float(value)


def _validate_train_output_dir(output_dir: str) -> str:
    return validate_safe_output_path(output_dir, label="train_output_dir")


def _assert_clean_train_output_dir(output_dir: Path | str) -> None:
    """Refuse pre-existing checkpoints/adapters in ``output_dir`` to prevent cross-fold auto-resume."""
    out_path = Path(output_dir)
    if out_path.is_symlink():
        raise InputError(f"train_output_dir must not be a symlink: {out_path}")
    if not out_path.exists():
        return
    if not out_path.is_dir():
        raise InputError(f"train_output_dir exists as a non-directory file: {out_path}")
    existing_artifacts = sorted(
        p.name
        for p in out_path.iterdir()
        if p.name.startswith("checkpoint-")
        or p.name
        in (
            "adapter_model.safetensors",
            "adapter_model.bin",
            "adapter_config.json",
            "trainer_state.json",
            ADAPTER_PROVENANCE_FILENAME,
        )
    )
    if existing_artifacts:
        raise InputError(
            f"refusing to reuse train_output_dir {out_path} containing existing checkpoint/adapter "
            f"artifacts {existing_artifacts[:5]} (prevents silent cross-fold auto-resume)"
        )


def _verify_referenced_frame_pngs(
    dataset_path: Path,
    summary: dict[str, Any],
    *,
    modality: str,
) -> tuple[int, list[dict[str, Any]]]:
    """Re-verify every L3 PNG path referenced in the dataset JSON against ``verified_frame_sha256s``."""
    raw_map = summary.get("verified_frame_sha256s")
    if not isinstance(raw_map, dict) or not raw_map:
        raise InputError(
            "build_summary.json missing non-empty verified_frame_sha256s; re-export with build_dataset.py"
        )
    rows = decode_file(dataset_path.read_text(encoding="utf-8"), str(dataset_path))
    if not isinstance(rows, list) or not rows:
        raise InputError(f"{dataset_path}: expected non-empty ShareGPT dataset list")

    seen_paths: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InputError(f"{dataset_path}[{idx}]: expected object")
        if modality == "images":
            frame_list = row.get("images")
        else:
            videos = row.get("videos")
            frame_list = videos[0] if isinstance(videos, list) and len(videos) == 1 else None
        if not isinstance(frame_list, list) or not frame_list:
            raise InputError(f"{dataset_path}[{idx}]: missing media frame path list")
        for fpath_str in frame_list:
            if not isinstance(fpath_str, str) or not fpath_str.strip():
                raise InputError(f"{dataset_path}[{idx}]: invalid frame path {fpath_str!r}")
            expected_sha = raw_map.get(fpath_str)
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise InputError(
                    f"{dataset_path}[{idx}]: frame path absent from build_summary verified_frame_sha256s: {fpath_str!r}"
                )
            if fpath_str in seen_paths:
                continue
            seen_paths.add(fpath_str)
            fp = Path(fpath_str)
            if not fp.is_absolute():
                raise InputError(f"{dataset_path}[{idx}]: formal training frame path must be absolute: {fpath_str!r}")
            if fp.is_symlink() or not fp.is_file():
                raise InputError(f"verified training frame missing or symlink on disk: {fp}")
            raw_bytes = fp.read_bytes()
            if not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise InputError(f"verified training frame is not a valid PNG: {fp}")
            actual_sha = sha256_file(fp)
            if actual_sha != expected_sha:
                raise InputError(
                    f"training frame PNG sha256 mismatch for {fp}: expected {expected_sha}, got {actual_sha}"
                )
    return len(seen_paths), rows


def _verify_frame_lineage_jsonl(
    lineage_path: Path,
    dataset_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    modality: str,
    num_frames: int,
) -> int:
    """Cross-check ``frame_lineage.jsonl`` 1:1 against ShareGPT dataset rows and ``build_summary.json``."""
    raw_lines = [line for line in lineage_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(raw_lines) != len(dataset_rows):
        raise InputError(
            f"{lineage_path}: row count ({len(raw_lines)}) != dataset row count ({len(dataset_rows)})"
        )
    expected_cids = summary.get("exported_candidate_ids")
    if not isinstance(expected_cids, list) or len(expected_cids) != len(raw_lines):
        raise InputError(f"{lineage_path}: build_summary exported_candidate_ids count mismatch")
    manifest_sha = (summary.get("inputs") or {}).get("manifest_sha256")
    verified_shas = summary.get("verified_frame_sha256s") or {}
    expected_fps = summary.get("video_fps")

    for idx, (line, drow, expected_cid) in enumerate(zip(raw_lines, dataset_rows, expected_cids)):
        try:
            lrow = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"{lineage_path}:{idx + 1}: invalid JSON: {exc}") from exc
        if not isinstance(lrow, dict) or lrow.get("schema") != FRAME_LINEAGE_SCHEMA:
            raise InputError(f"{lineage_path}:{idx + 1}: invalid schema {lrow.get('schema') if isinstance(lrow, dict) else None!r}")
        if lrow.get("sample_index") != idx:
            raise InputError(f"{lineage_path}:{idx + 1}: sample_index {lrow.get('sample_index')!r} != {idx}")
        if lrow.get("candidate_id") != expected_cid:
            raise InputError(f"{lineage_path}:{idx + 1}: candidate_id {lrow.get('candidate_id')!r} != {expected_cid!r}")
        if lrow.get("modality") != modality or lrow.get("num_frames") != num_frames:
            raise InputError(
                f"{lineage_path}:{idx + 1}: modality/num_frames mismatch "
                f"({lrow.get('modality')!r}/{lrow.get('num_frames')!r} vs {modality!r}/{num_frames!r})"
            )
        if manifest_sha and lrow.get("manifest_sha256") != manifest_sha:
            raise InputError(f"{lineage_path}:{idx + 1}: manifest_sha256 mismatch")
        if modality == "video" and expected_fps is not None and lrow.get("video_fps") != expected_fps:
            raise InputError(
                f"{lineage_path}:{idx + 1}: video_fps {lrow.get('video_fps')!r} != build_summary {expected_fps!r}"
            )

        expected_frames = drow["images"] if modality == "images" else drow["videos"][0]
        lframes = lrow.get("frames")
        if not isinstance(lframes, list) or len(lframes) != num_frames:
            raise InputError(f"{lineage_path}:{idx + 1}: expected {num_frames} frames, got {type(lframes).__name__}")
        for order, (lf, expected_path) in enumerate(zip(lframes, expected_frames)):
            if not isinstance(lf, dict):
                raise InputError(f"{lineage_path}:{idx + 1}: frames[{order}] must be object")
            if lf.get("display_order") != order:
                raise InputError(f"{lineage_path}:{idx + 1}: frames[{order}].display_order != {order}")
            if lf.get("emitted_path") != expected_path:
                raise InputError(
                    f"{lineage_path}:{idx + 1}: frames[{order}].emitted_path {lf.get('emitted_path')!r} "
                    f"!= dataset path {expected_path!r}"
                )
            if lf.get("png_sha256") != verified_shas.get(expected_path):
                raise InputError(
                    f"{lineage_path}:{idx + 1}: frames[{order}].png_sha256 mismatch against verified_frame_sha256s"
                )
    return len(raw_lines)


def verify_dataset_bundle(
    *,
    dataset_dir: Path | str,
    fold: int,
    modality: str,
    num_frames: int,
    dataset_name: str,
    cutoff_len: int,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    video_fps: float | None = None,
) -> dict[str, Any]:
    """Fail-closed cross-check of ``build_summary.json``, ``dataset_info.json``, ``preflight_report.json``, ``frame_lineage.jsonl``, and dataset JSON.

    Prevents cross-fold leakage (e.g., training Fold 1 config on Fold 0 dataset), modality/frame
    mismatch, pixel/cutoff/fps drift vs verified preflight/lineage, tampered dataset bytes, or dry-run bundles.
    """
    raw_dir = Path(dataset_dir)
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise InputError(
            f"dataset_dir does not exist or is not a regular directory: {raw_dir}; "
            "export a verified dataset bundle with build_dataset.py first (or pass --allow-remote-dataset-dir "
            "only when rendering a template for a remote host path)"
        )
    bundle_dir = raw_dir.resolve()

    summary_path = bundle_dir / "build_summary.json"
    info_path = bundle_dir / "dataset_info.json"
    preflight_path = bundle_dir / "preflight_report.json"
    lineage_path = bundle_dir / "frame_lineage.jsonl"
    for label, p in (
        ("build_summary.json", summary_path),
        ("dataset_info.json", info_path),
        ("preflight_report.json", preflight_path),
        ("frame_lineage.jsonl", lineage_path),
    ):
        if p.is_symlink() or not p.is_file():
            raise InputError(f"dataset bundle missing required non-symlink {label}: {p}")

    summary = decode_file(summary_path.read_text(encoding="utf-8"), str(summary_path))
    info = decode_file(info_path.read_text(encoding="utf-8"), str(info_path))
    preflight = decode_file(preflight_path.read_text(encoding="utf-8"), str(preflight_path))
    if not isinstance(summary, dict) or summary.get("schema") != BUILD_SUMMARY_SCHEMA:
        raise InputError(
            f"{summary_path}: invalid build_summary schema {summary.get('schema') if isinstance(summary, dict) else None!r}"
        )
    if summary.get("dry_run_missing_frames") is not False:
        raise InputError(
            f"{summary_path}: refusing to render runnable training config for dry-run dataset "
            "(dry_run_missing_frames=true)"
        )
    if summary.get("strict_target_json_verified") is not True:
        raise InputError(f"{summary_path}: dataset bundle missing strict_target_json_verified=true")

    for field, expected in (
        ("fold", fold),
        ("modality", modality),
        ("num_frames", num_frames),
        ("dataset_name", dataset_name),
    ):
        actual = summary.get(field)
        if actual != expected:
            raise InputError(
                f"dataset bundle mismatch in {summary_path}: {field}={actual!r} != requested {expected!r}"
            )
    if modality == "video" and video_fps is not None and summary.get("video_fps") is not None:
        if float(summary["video_fps"]) != float(video_fps):
            raise InputError(
                f"dataset bundle video_fps mismatch in {summary_path}: "
                f"summary={summary['video_fps']!r} != YAML {video_fps!r}"
            )

    isolation = summary.get("isolation_checks")
    if not isinstance(isolation, dict):
        raise InputError(f"{summary_path}: missing isolation_checks")
    for overlap_key in (
        "fold_val_source_overlap",
        "test_source_overlap",
        "eval_test_v1_source_overlap",
        "eval_test_v1_candidate_overlap",
        "eval_dev_v1_fold_val_candidate_overlap",
        "dec007_excluded_overlap",
    ):
        if isolation.get(overlap_key) != 0:
            raise InputError(f"{summary_path}: isolation_checks.{overlap_key} != 0 ({isolation.get(overlap_key)!r})")

    if not isinstance(info, dict) or dataset_name not in info or not isinstance(info[dataset_name], dict):
        raise InputError(f"{info_path}: dataset_name {dataset_name!r} not registered in dataset_info.json")
    entry = info[dataset_name]
    if entry.get("formatting") != "sharegpt":
        raise InputError(f"{info_path}: expected formatting='sharegpt', got {entry.get('formatting')!r}")
    expected_media_col = "images" if modality == "images" else "videos"
    cols = entry.get("columns")
    if not isinstance(cols, dict) or cols.get("messages") != "messages" or cols.get(expected_media_col) != expected_media_col:
        raise InputError(f"{info_path}: columns mismatch for modality={modality!r}: {cols!r}")
    dataset_file = summary.get("dataset_file")
    if not isinstance(dataset_file, str) or entry.get("file_name") != dataset_file:
        raise InputError(
            f"{info_path}: file_name {entry.get('file_name')!r} != build_summary dataset_file {dataset_file!r}"
        )

    fingerprints = summary.get("fingerprints")
    if not isinstance(fingerprints, dict):
        raise InputError(f"{summary_path}: missing fingerprints")
    actual_info_sha = sha256_file(info_path)
    if fingerprints.get("dataset_info_sha256") != actual_info_sha:
        raise InputError(
            f"{info_path}: sha256 mismatch (expected {fingerprints.get('dataset_info_sha256')!r}, got {actual_info_sha!r})"
        )
    actual_preflight_sha = sha256_file(preflight_path)
    if fingerprints.get("preflight_report_sha256") != actual_preflight_sha:
        raise InputError(
            f"{preflight_path}: sha256 mismatch (expected {fingerprints.get('preflight_report_sha256')!r}, got {actual_preflight_sha!r})"
        )
    actual_lineage_sha = sha256_file(lineage_path)
    if fingerprints.get("frame_lineage_sha256") != actual_lineage_sha:
        raise InputError(
            f"{lineage_path}: sha256 mismatch (expected {fingerprints.get('frame_lineage_sha256')!r}, got {actual_lineage_sha!r})"
        )
    dataset_path = bundle_dir / dataset_file
    if dataset_path.is_symlink() or not dataset_path.is_file():
        raise InputError(f"dataset bundle missing required non-symlink dataset file: {dataset_path}")
    actual_ds_sha = sha256_file(dataset_path)
    if fingerprints.get("dataset_sha256") != actual_ds_sha:
        raise InputError(
            f"{dataset_path}: sha256 mismatch (expected {fingerprints.get('dataset_sha256')!r}, got {actual_ds_sha!r})"
        )

    # Verify YAML pixel parameters and cutoff_len match the verified preflight report (no silent drift).
    if not isinstance(preflight, dict):
        raise InputError(f"{preflight_path}: invalid preflight_report JSON object")
    for count_key in ("short_clip_count", "exceeds_cutoff_count", "exceeds_gpu_frame_pixel_guard_count"):
        if preflight.get(count_key) != 0:
            raise InputError(f"{preflight_path}: {count_key} != 0 ({preflight.get(count_key)!r})")
    pixel_cfg = preflight.get("pixel_config")
    if not isinstance(pixel_cfg, dict):
        raise InputError(f"{preflight_path}: missing pixel_config")
    expected_pixels = (
        {"image_max_pixels": image_max_pixels, "image_min_pixels": image_min_pixels}
        if modality == "images"
        else {"video_max_pixels": video_max_pixels, "video_min_pixels": video_min_pixels}
    )
    for px_key, yaml_val in expected_pixels.items():
        if pixel_cfg.get(px_key) != yaml_val:
            raise InputError(
                f"pixel config mismatch vs verified {preflight_path}: YAML {px_key}={yaml_val!r} != "
                f"preflight {pixel_cfg.get(px_key)!r}; re-export or re-run preflight with matching pixel settings"
            )
    est = preflight.get("estimated_total_tokens")
    if not isinstance(est, dict) or not isinstance(est.get("max"), int):
        raise InputError(f"{preflight_path}: missing estimated_total_tokens.max")
    if cutoff_len < est["max"]:
        raise InputError(
            f"cutoff_len ({cutoff_len}) is smaller than dataset max estimated tokens ({est['max']})"
        )

    verified_frame_count, dataset_rows = _verify_referenced_frame_pngs(dataset_path, summary, modality=modality)
    _verify_frame_lineage_jsonl(
        lineage_path,
        dataset_rows,
        summary,
        modality=modality,
        num_frames=num_frames,
    )

    return {
        "verified": True,
        "resolved_dataset_dir": str(bundle_dir),
        "dataset_file": dataset_file,
        "build_summary_sha256": sha256_file(summary_path),
        "dataset_sha256": actual_ds_sha,
        "dataset_info_sha256": actual_info_sha,
        "preflight_report_sha256": actual_preflight_sha,
        "frame_lineage_sha256": actual_lineage_sha,
        "verified_frame_count": verified_frame_count,
        "exported_candidate_count": isolation.get("exported_candidate_count"),
        "exported_source_count": isolation.get("exported_source_count"),
    }


def _load_and_verify_commands_and_yaml(
    commands_json_path: Path | str,
    *,
    expected_yaml_path: Path | str | None = None,
) -> tuple[Path, dict[str, Any], Path, dict[str, Any], str]:
    cmd_path = Path(commands_json_path)
    if cmd_path.is_symlink() or not cmd_path.is_file():
        raise InputError(f"missing non-symlink commands manifest: {cmd_path}")
    commands = decode_file(cmd_path.read_text(encoding="utf-8"), str(cmd_path))
    if not isinstance(commands, dict) or commands.get("schema") != CONFIG_MANIFEST_SCHEMA:
        raise InputError(f"{cmd_path}: invalid commands manifest schema")

    pinned = commands.get("dataset_bundle_verification")
    if not isinstance(pinned, dict) or pinned.get("verified") is not True:
        raise InputError(f"{cmd_path}: refusing to use unverified/remote dataset config")

    yaml_path_str = commands.get("yaml_path")
    if not isinstance(yaml_path_str, str) or not yaml_path_str.strip():
        raise InputError(f"{cmd_path}: missing yaml_path")
    yaml_path = Path(yaml_path_str)
    if expected_yaml_path is not None:
        if Path(expected_yaml_path).resolve() != yaml_path.resolve():
            raise InputError(
                f"launch YAML mismatch: --verify-yaml {Path(expected_yaml_path).resolve()} != "
                f"commands manifest yaml_path {yaml_path.resolve()}"
            )
    if yaml_path.is_symlink() or not yaml_path.is_file():
        raise InputError(f"{cmd_path}: rendered YAML missing or symlink: {yaml_path}")
    expected_yaml_sha = commands.get("yaml_sha256")
    actual_yaml_sha = sha256_file(yaml_path)
    if expected_yaml_sha != actual_yaml_sha:
        raise InputError(
            f"{yaml_path}: YAML sha256 mismatch (expected {expected_yaml_sha!r}, got {actual_yaml_sha!r})"
        )

    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise InputError(f"{yaml_path}: invalid YAML config")

    out_dir_str = cfg.get("output_dir")
    if not isinstance(out_dir_str, str) or not Path(out_dir_str).is_absolute():
        raise InputError(f"{yaml_path}: output_dir must be a pinned absolute path, got {out_dir_str!r}")
    validate_safe_output_path(out_dir_str, label="train_output_dir")
    return cmd_path.resolve(), commands, yaml_path.resolve(), cfg, actual_yaml_sha


def verify_rendered_launch(
    commands_json_path: Path | str,
    *,
    expected_yaml_path: Path | str | None = None,
) -> dict[str, Any]:
    """Re-verify rendered YAML and pinned dataset bundle hashes immediately before training launch.

    Fail-closed guard preventing a stale YAML from ever launching against an overwritten or
    swapped fold dataset directory, or validating a different YAML than the one being launched.
    """
    _, commands, yaml_path, cfg, _ = _load_and_verify_commands_and_yaml(
        commands_json_path,
        expected_yaml_path=expected_yaml_path,
    )
    pinned = commands["dataset_bundle_verification"]
    _assert_clean_train_output_dir(cfg["output_dir"])

    live = verify_dataset_bundle(
        dataset_dir=cfg["dataset_dir"],
        fold=commands["fold"],
        modality=commands["modality"],
        num_frames=commands["num_frames"],
        dataset_name=cfg["dataset"],
        cutoff_len=cfg["cutoff_len"],
        image_max_pixels=cfg.get("image_max_pixels"),
        image_min_pixels=cfg.get("image_min_pixels"),
        video_max_pixels=cfg.get("video_max_pixels"),
        video_min_pixels=cfg.get("video_min_pixels"),
        video_fps=cfg.get("video_fps"),
    )
    for key in (
        "resolved_dataset_dir",
        "build_summary_sha256",
        "dataset_sha256",
        "dataset_info_sha256",
        "preflight_report_sha256",
        "frame_lineage_sha256",
    ):
        if live.get(key) != pinned.get(key):
            raise InputError(
                f"pre-launch dataset verification failed for {yaml_path}: {key} drifted "
                f"(pinned={pinned.get(key)!r}, live={live.get(key)!r}); re-render config before training"
            )
    return live


def _find_adapter_weights_file(adapter_dir: Path) -> Path:
    for candidate_name in ("adapter_model.safetensors", "adapter_model.bin"):
        p = adapter_dir / candidate_name
        if p.is_symlink():
            raise InputError(f"adapter weights file must not be a symlink: {p}")
        if p.is_file():
            return p
    raise InputError(
        f"adapter directory {adapter_dir} missing trained weights "
        "(expected adapter_model.safetensors or adapter_model.bin)"
    )


def _seal_adapter_provenance_after_verified_run(
    *,
    cmd_path: Path,
    commands: dict[str, Any],
    yaml_path: Path,
    cfg: dict[str, Any],
    yaml_sha: str,
    live_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Internal provenance sealer invoked ONLY inside ``run_verified_training`` after rc==0."""
    adapter_dir = Path(cfg["output_dir"])
    if adapter_dir.is_symlink() or not adapter_dir.is_dir():
        raise InputError(f"trained adapter output_dir missing or symlink: {adapter_dir}")
    adapter_cfg_path = adapter_dir / "adapter_config.json"
    if adapter_cfg_path.is_symlink() or not adapter_cfg_path.is_file():
        raise InputError(f"trained adapter missing non-symlink adapter_config.json: {adapter_cfg_path}")
    weights_path = _find_adapter_weights_file(adapter_dir)

    adapter_cfg = decode_file(adapter_cfg_path.read_text(encoding="utf-8"), str(adapter_cfg_path))
    if isinstance(adapter_cfg, dict) and isinstance(adapter_cfg.get("r"), int):
        if adapter_cfg["r"] != cfg.get("lora_rank"):
            raise InputError(
                f"{adapter_cfg_path}: adapter rank r={adapter_cfg['r']} != YAML lora_rank={cfg.get('lora_rank')}"
            )

    prov_path = adapter_dir / ADAPTER_PROVENANCE_FILENAME
    if prov_path.exists() or prov_path.is_symlink():
        raise InputError(f"refusing to overwrite pre-existing adapter provenance: {prov_path}")

    provenance = {
        "schema": ADAPTER_PROVENANCE_SCHEMA,
        "fold": commands["fold"],
        "modality": commands["modality"],
        "num_frames": commands["num_frames"],
        "lora_module_name": commands["lora_module_name"],
        "dataset_name": cfg["dataset"],
        "dataset_dir": live_bundle["resolved_dataset_dir"],
        "dataset_sha256": live_bundle["dataset_sha256"],
        "frame_lineage_sha256": live_bundle["frame_lineage_sha256"],
        "yaml_path": str(yaml_path),
        "yaml_sha256": yaml_sha,
        "commands_json_path": str(cmd_path),
        "commands_json_sha256": sha256_file(cmd_path),
        "adapter_dir": str(adapter_dir.resolve()),
        "adapter_config_sha256": sha256_file(adapter_cfg_path),
        "adapter_weights_file": weights_path.name,
        "adapter_weights_sha256": sha256_file(weights_path),
        "eval_scope_warning": commands["eval_scope_warning"],
    }
    assert_no_input_output_collision(
        [prov_path],
        [cmd_path, yaml_path, adapter_cfg_path, weights_path],
        context="run_verified_training",
    )
    safe_write_bytes(
        prov_path,
        (json.dumps(provenance, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
        overwrite=False,
        label="adapter_provenance",
    )
    return provenance


def _default_llamafactory_train_runner(yaml_path: Path) -> int:
    env = os.environ.copy()
    env["PYTORCH_CUDA_ALLOC_CONF"] = CUDA_ALLOC_CONF
    proc = subprocess.run([VLM_SFT_LLAMAFACTORY_CLI, "train", str(yaml_path)], env=env, check=False)
    return int(proc.returncode)


def run_verified_training(
    commands_json_path: Path | str,
    *,
    expected_yaml_path: Path | str | None = None,
    train_runner: Callable[[Path], int] | None = None,
) -> dict[str, Any]:
    """Controlled end-to-end training launcher: verify clean dir & bundle -> train -> seal provenance.

    Binds ``sft_adapter_provenance.json`` strictly to a verified clean-directory launch and a
    zero-exit training subprocess in the same controlled execution (no standalone stamp CLI).
    """
    cmd_path, commands, yaml_path, cfg, yaml_sha = _load_and_verify_commands_and_yaml(
        commands_json_path,
        expected_yaml_path=expected_yaml_path,
    )
    live_bundle = verify_rendered_launch(cmd_path, expected_yaml_path=yaml_path)

    runner = train_runner if train_runner is not None else _default_llamafactory_train_runner
    rc = int(runner(yaml_path))
    if rc != 0:
        raise InputError(f"training process failed with exit code {rc}; adapter provenance NOT sealed")

    return _seal_adapter_provenance_after_verified_run(
        cmd_path=cmd_path,
        commands=commands,
        yaml_path=yaml_path,
        cfg=cfg,
        yaml_sha=yaml_sha,
        live_bundle=live_bundle,
    )


def verify_serve_launch(
    commands_json_path: Path | str,
    *,
    expected_fold: int | None = None,
    expected_adapter_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Fail-closed pre-serve provenance guard preventing cross-fold or swapped LoRA adapter serving."""
    cmd_path, commands, yaml_path, cfg, yaml_sha = _load_and_verify_commands_and_yaml(commands_json_path)
    if expected_fold is not None:
        validate_fold(expected_fold)
        if commands["fold"] != expected_fold:
            raise InputError(
                f"pre-serve fold mismatch: commands manifest is fold_{commands['fold']} != requested fold_{expected_fold}"
            )

    adapter_dir = Path(cfg["output_dir"])
    if expected_adapter_dir is not None:
        if Path(expected_adapter_dir).resolve() != adapter_dir.resolve():
            raise InputError(
                f"pre-serve adapter_dir mismatch: requested {Path(expected_adapter_dir).resolve()} != "
                f"YAML output_dir {adapter_dir.resolve()}"
            )
    if adapter_dir.is_symlink() or not adapter_dir.is_dir():
        raise InputError(f"pre-serve adapter directory missing or symlink: {adapter_dir}")

    prov_path = adapter_dir / ADAPTER_PROVENANCE_FILENAME
    if prov_path.is_symlink() or not prov_path.is_file():
        raise InputError(
            f"missing non-symlink {ADAPTER_PROVENANCE_FILENAME} in {adapter_dir}; "
            "stamp provenance immediately after training before serving LoRA"
        )
    prov = decode_file(prov_path.read_text(encoding="utf-8"), str(prov_path))
    if not isinstance(prov, dict) or prov.get("schema") != ADAPTER_PROVENANCE_SCHEMA:
        raise InputError(f"{prov_path}: invalid adapter provenance schema")

    pinned = commands["dataset_bundle_verification"]
    expected_checks = {
        "fold": commands["fold"],
        "modality": commands["modality"],
        "num_frames": commands["num_frames"],
        "lora_module_name": commands["lora_module_name"],
        "dataset_name": cfg["dataset"],
        "dataset_dir": pinned["resolved_dataset_dir"],
        "dataset_sha256": pinned["dataset_sha256"],
        "frame_lineage_sha256": pinned["frame_lineage_sha256"],
        "yaml_path": str(yaml_path),
        "yaml_sha256": yaml_sha,
        "commands_json_path": str(cmd_path),
        "commands_json_sha256": sha256_file(cmd_path),
        "adapter_dir": str(adapter_dir.resolve()),
    }
    for key, exp_val in expected_checks.items():
        if prov.get(key) != exp_val:
            raise InputError(
                f"pre-serve adapter provenance mismatch in {prov_path}: {key}={prov.get(key)!r} != expected {exp_val!r}"
            )

    adapter_cfg_path = adapter_dir / "adapter_config.json"
    if adapter_cfg_path.is_symlink() or not adapter_cfg_path.is_file():
        raise InputError(f"pre-serve adapter missing non-symlink adapter_config.json: {adapter_cfg_path}")
    actual_cfg_sha = sha256_file(adapter_cfg_path)
    if prov.get("adapter_config_sha256") != actual_cfg_sha:
        raise InputError(f"{adapter_cfg_path}: sha256 mismatch against provenance")
    adapter_cfg = decode_file(adapter_cfg_path.read_text(encoding="utf-8"), str(adapter_cfg_path))
    if isinstance(adapter_cfg, dict) and isinstance(adapter_cfg.get("r"), int):
        if adapter_cfg["r"] != cfg.get("lora_rank"):
            raise InputError(
                f"{adapter_cfg_path}: adapter rank r={adapter_cfg['r']} != YAML lora_rank={cfg.get('lora_rank')}"
            )

    weights_file = prov.get("adapter_weights_file")
    if weights_file not in ("adapter_model.safetensors", "adapter_model.bin"):
        raise InputError(f"{prov_path}: invalid adapter_weights_file {weights_file!r}")
    weights_path = adapter_dir / weights_file
    if weights_path.is_symlink() or not weights_path.is_file():
        raise InputError(f"pre-serve adapter weights missing or symlink: {weights_path}")
    actual_weights_sha = sha256_file(weights_path)
    if prov.get("adapter_weights_sha256") != actual_weights_sha:
        raise InputError(f"{weights_path}: sha256 mismatch against provenance")

    return prov


def build_qlora_config(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    dataset_dir: str,
    dataset_name: str,
    train_output_dir: str,
    model_name_or_path: str = DEFAULT_BASE_MODEL_PATH,
    cutoff_len: int | None = None,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    video_fps: float | None = None,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    learning_rate: float = 1.0e-4,
    num_train_epochs: float = 3.0,
    gradient_accumulation_steps: int = 8,
    logging_steps: int = 5,
    save_strategy: str = "epoch",
    seed: int = 42,
) -> dict[str, Any]:
    """Build a LlamaFactory 4-bit QLoRA config dict aligned with DEC-008 and #5."""
    fold = validate_fold(fold)
    preset = get_channel_preset(modality, num_frames)
    clean_output_dir = _validate_train_output_dir(train_output_dir)

    if not isinstance(dataset_dir, str) or not dataset_dir.strip():
        raise InputError("dataset_dir must be non-empty")
    dataset_name = validate_dataset_name(dataset_name, label="dataset_name")
    if not isinstance(model_name_or_path, str) or not model_name_or_path.strip():
        raise InputError("model_name_or_path must be non-empty")

    eff_cutoff = _require_pos_int(cutoff_len if cutoff_len is not None else preset.cutoff_len, "cutoff_len")
    _require_pos_int(lora_rank, "lora_rank")
    _require_pos_int(lora_alpha, "lora_alpha")
    if (
        isinstance(lora_dropout, bool)
        or not isinstance(lora_dropout, (int, float))
        or not math.isfinite(lora_dropout)
        or not (0.0 <= lora_dropout < 1.0)
    ):
        raise InputError(f"lora_dropout must be in [0, 1), got {lora_dropout!r}")
    _require_pos_float(learning_rate, "learning_rate")
    _require_pos_float(num_train_epochs, "num_train_epochs")
    _require_pos_int(gradient_accumulation_steps, "gradient_accumulation_steps")
    _require_pos_int(logging_steps, "logging_steps")

    if modality == "images" and any(v is not None for v in (video_max_pixels, video_min_pixels, video_fps)):
        raise InputError("video_max_pixels/video_min_pixels/video_fps cannot be set when modality='images'")
    if modality == "video" and any(v is not None for v in (image_max_pixels, image_min_pixels)):
        raise InputError("image_max_pixels/image_min_pixels cannot be set when modality='video'")

    cfg: dict[str, Any] = {
        # Model & template (DEC-008 §1, §3)
        "model_name_or_path": model_name_or_path,
        "template": DEFAULT_TEMPLATE,
        "quantization_bit": 4,
        "quantization_method": "bnb",
        "trust_remote_code": False,
        # Method: 4-bit QLoRA
        "stage": "sft",
        "do_train": True,
        "finetuning_type": "lora",
        "lora_rank": lora_rank,
        "lora_alpha": lora_alpha,
        "lora_dropout": lora_dropout,
        "lora_target": "all",
        # Dataset (strictly Fold k clean train only)
        "dataset_dir": dataset_dir,
        "dataset": dataset_name,
        "cutoff_len": eff_cutoff,
        "overwrite_cache": True,
        "preprocessing_num_workers": 4,
    }

    if modality == "images":
        img_max = _require_pos_int(image_max_pixels if image_max_pixels is not None else preset.image_max_pixels, "image_max_pixels")
        img_min = _require_pos_int(image_min_pixels if image_min_pixels is not None else preset.image_min_pixels, "image_min_pixels")
        if img_min > img_max:
            raise InputError(f"image_min_pixels ({img_min}) must be <= image_max_pixels ({img_max})")
        cfg["image_max_pixels"] = img_max
        cfg["image_min_pixels"] = img_min
    else:
        vid_max = _require_pos_int(video_max_pixels if video_max_pixels is not None else preset.video_max_pixels, "video_max_pixels")
        vid_min = _require_pos_int(video_min_pixels if video_min_pixels is not None else preset.video_min_pixels, "video_min_pixels")
        if vid_min > vid_max:
            raise InputError(f"video_min_pixels ({vid_min}) must be <= video_max_pixels ({vid_max})")
        eff_fps = _require_pos_float(video_fps if video_fps is not None else preset.video_fps, "video_fps")
        cfg["video_max_pixels"] = vid_max
        cfg["video_min_pixels"] = vid_min
        cfg["video_fps"] = eff_fps

    cfg.update(
        {
            # Output
            "output_dir": clean_output_dir,
            "logging_steps": logging_steps,
            "save_strategy": save_strategy,
            "plot_loss": True,
            "overwrite_output_dir": False,
            # Train (DEC-008 §3 RTX 4090 24GB golden recipe)
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "learning_rate": learning_rate,
            "num_train_epochs": num_train_epochs,
            "lr_scheduler_type": "cosine",
            "warmup_ratio": 0.1,
            "bf16": True,
            "gradient_checkpointing": True,
            "optim": "paged_adamw_8bit",
            "ddp_timeout": 180000000,
            "seed": seed,
            "report_to": "none",
        }
    )
    return cfg


def build_runtime_commands(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    yaml_path: str,
    commands_json_path: str | None = None,
    train_output_dir: str,
    model_name_or_path: str = DEFAULT_BASE_MODEL_PATH,
    served_model_name: str = DEFAULT_SERVED_MODEL_NAME,
    lora_module_name: str | None = None,
    lora_rank: int = 16,
    port: int = 18080,
    vllm_max_model_len: int | None = None,
    video_fps: float | None = None,
    gpu_memory_utilization: float = 0.88,
) -> dict[str, Any]:
    """Build exact manual training & vLLM LoRA serving commands with DEC-008 PATH isolation."""
    fold = validate_fold(fold)
    preset = get_channel_preset(modality, num_frames)
    _validate_train_output_dir(train_output_dir)
    _require_pos_int(lora_rank, "lora_rank")
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise InputError(f"port must be an integer in [1, 65535], got {port!r}")
    if (
        isinstance(gpu_memory_utilization, bool)
        or not isinstance(gpu_memory_utilization, (int, float))
        or not math.isfinite(gpu_memory_utilization)
        or not (0.0 < gpu_memory_utilization <= 1.0)
    ):
        raise InputError(f"gpu_memory_utilization must be in (0, 1], got {gpu_memory_utilization!r}")
    adapter_name = lora_module_name or f"qwen3vl-fold{fold}-{modality}-{num_frames}f"
    max_model_len = _require_pos_int(
        vllm_max_model_len if vllm_max_model_len is not None else preset.vllm_max_model_len,
        "vllm_max_model_len",
    )
    eff_fps = _require_pos_float(video_fps if video_fps is not None else (preset.video_fps or 2.0), "video_fps")

    raw_train_cmd = (
        f"PYTORCH_CUDA_ALLOC_CONF={CUDA_ALLOC_CONF} "
        f"{VLM_SFT_LLAMAFACTORY_CLI} train {shlex.quote(yaml_path)}"
    )
    if commands_json_path is not None:
        train_cmd = (
            f"{VLM_SFT_PYTHON_BIN} -m script.five_label_sft.render_config "
            f"--run-verified-train {shlex.quote(commands_json_path)} "
            f"--verify-yaml {shlex.quote(yaml_path)}"
        )
    else:
        train_cmd = raw_train_cmd

    vllm_parts = [
        f"PATH={shlex.quote(PURE_SYSTEM_PATH)}",
        VLM_EVAL_VLLM_BIN,
        "serve",
        shlex.quote(model_name_or_path),
        "--served-model-name",
        shlex.quote(served_model_name),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--dtype",
        "bfloat16",
        "--gpu-memory-utilization",
        str(gpu_memory_utilization),
        "--max-model-len",
        str(max_model_len),
        "--max-num-seqs",
        "1",
        "--enable-lora",
        "--max-lora-rank",
        str(lora_rank),
        "--lora-modules",
        shlex.quote(f"{adapter_name}={train_output_dir}"),
    ]

    if modality == "images":
        vllm_parts.extend(
            [
                "--limit-mm-per-prompt",
                shlex.quote(json.dumps({"image": num_frames, "video": 0})),
            ]
        )
    else:
        vllm_parts.extend(
            [
                "--limit-mm-per-prompt",
                shlex.quote(json.dumps({"video": 1, "image": 0})),
                "--media-io-kwargs",
                shlex.quote(json.dumps({"video": {"num_frames": -1, "fps": eff_fps}})),
                "--mm-processor-kwargs",
                shlex.quote(json.dumps({"videos_kwargs": {"do_sample_frames": False, "cap_pixels_per_frame": False}})),
            ]
        )

    raw_vllm_serve_cmd = " \\\n  ".join(vllm_parts)
    if commands_json_path is not None:
        verify_serve_cmd = (
            f"{VLM_SFT_PYTHON_BIN} -m script.five_label_sft.render_config "
            f"--verify-serve-commands-json {shlex.quote(commands_json_path)} "
            f"--expected-fold {fold} "
            f"--expected-adapter-dir {shlex.quote(train_output_dir)}"
        )
        vllm_serve_cmd = f"{verify_serve_cmd} && \\\n  {raw_vllm_serve_cmd}"
    else:
        vllm_serve_cmd = raw_vllm_serve_cmd

    return {
        "schema": CONFIG_MANIFEST_SCHEMA,
        "fold": fold,
        "modality": modality,
        "num_frames": num_frames,
        "lora_module_name": adapter_name,
        "path_isolation_warning": (
            "DEC-008 §2: vLLM in vlm-eval MUST run with pure system PATH (excluding vlm-sft/bin/ninja) "
            "to prevent FlashInfer JIT nvcc --compress-mode=size crashes."
        ),
        "eval_scope_warning": (
            f"DEC-008 §5: Evaluate fold_{fold} adapter ONLY on eval-dev-v1 ∩ fold_{fold}_val "
            "(29 clean val sources). NEVER touch eval-test-v1."
        ),
        "train_command_manual_only": train_cmd,
        "vllm_serve_lora_command": vllm_serve_cmd,
    }


def render_config_bundle(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    dataset_dir: str,
    dataset_name: str,
    train_output_dir: str,
    output_yaml: Path | str,
    model_name_or_path: str = DEFAULT_BASE_MODEL_PATH,
    cutoff_len: int | None = None,
    vllm_max_model_len: int | None = None,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    video_fps: float | None = None,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    learning_rate: float = 1.0e-4,
    num_train_epochs: float = 3.0,
    gradient_accumulation_steps: int = 8,
    port: int = 18080,
    allow_remote_dataset_dir: bool = False,
    overwrite: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write LlamaFactory YAML and companion runtime command JSON."""
    cfg = build_qlora_config(
        fold=fold,
        modality=modality,
        num_frames=num_frames,
        dataset_dir=dataset_dir,
        dataset_name=dataset_name,
        train_output_dir=train_output_dir,
        model_name_or_path=model_name_or_path,
        cutoff_len=cutoff_len,
        image_max_pixels=image_max_pixels,
        image_min_pixels=image_min_pixels,
        video_max_pixels=video_max_pixels,
        video_min_pixels=video_min_pixels,
        video_fps=video_fps,
        lora_rank=lora_rank,
        lora_alpha=lora_alpha,
        learning_rate=learning_rate,
        num_train_epochs=num_train_epochs,
        gradient_accumulation_steps=gradient_accumulation_steps,
    )
    if not allow_remote_dataset_dir:
        bundle_verification = verify_dataset_bundle(
            dataset_dir=dataset_dir,
            fold=fold,
            modality=modality,
            num_frames=num_frames,
            dataset_name=dataset_name,
            cutoff_len=cfg["cutoff_len"],
            image_max_pixels=cfg.get("image_max_pixels"),
            image_min_pixels=cfg.get("image_min_pixels"),
            video_max_pixels=cfg.get("video_max_pixels"),
            video_min_pixels=cfg.get("video_min_pixels"),
            video_fps=cfg.get("video_fps"),
        )
        # Pin exact verified absolute dataset_dir and train_output_dir in YAML so cwd changes or
        # pre-existing cross-fold checkpoints can never silently contaminate training.
        cfg["dataset_dir"] = bundle_verification["resolved_dataset_dir"]
        resolved_train_out = str(Path(train_output_dir).resolve())
        validate_safe_output_path(resolved_train_out, label="train_output_dir")
        _assert_clean_train_output_dir(resolved_train_out)
        cfg["output_dir"] = resolved_train_out
        effective_train_output_dir = resolved_train_out
    else:
        bundle_verification = {
            "verified": False,
            "warning": "allow_remote_dataset_dir=True: dataset_dir was NOT locally cross-checked against build_summary.json",
        }
        effective_train_output_dir = train_output_dir

    yaml_path = Path(output_yaml)
    if yaml_path.suffix not in (".yaml", ".yml"):
        raise InputError(f"output_yaml must have a lowercase .yaml or .yml suffix, got {yaml_path!r}")
    commands_path = Path(f"{yaml_path}.commands.json")
    if str(yaml_path.resolve()).lower() == str(commands_path.resolve()).lower():
        raise InputError(f"output_yaml collides with companion commands path: {yaml_path}")
    for label, p in (("output_yaml", yaml_path), ("commands_json", commands_path)):
        validate_safe_output_path(p, label=label)
        assert_no_symlink_components(p, label=label)

    if bundle_verification.get("verified") is True:
        bdir = Path(bundle_verification["resolved_dataset_dir"])
        bundle_inputs = [
            bdir / name
            for name in (
                "build_summary.json",
                "dataset_info.json",
                "preflight_report.json",
                "frame_lineage.jsonl",
                bundle_verification["dataset_file"],
            )
        ]
        assert_no_input_output_collision(
            [yaml_path, commands_path],
            bundle_inputs,
            context="render_config",
        )

    resolved_yaml_str = str(yaml_path.resolve())
    resolved_commands_str = str(commands_path.resolve())
    commands = build_runtime_commands(
        fold=fold,
        modality=modality,
        num_frames=num_frames,
        yaml_path=resolved_yaml_str,
        commands_json_path=resolved_commands_str if not allow_remote_dataset_dir else None,
        train_output_dir=effective_train_output_dir,
        model_name_or_path=model_name_or_path,
        lora_rank=lora_rank,
        port=port,
        vllm_max_model_len=vllm_max_model_len,
        video_fps=video_fps,
    )
    commands["yaml_path"] = resolved_yaml_str
    commands["dataset_bundle_verification"] = bundle_verification

    if not overwrite:
        existing = [str(p) for p in (yaml_path, commands_path) if p.exists()]
        if existing:
            raise InputError(f"refusing to overwrite existing config files (pass --overwrite): {existing}")

    header = (
        f"# Auto-generated by script/five_label_sft/render_config.py (fold={fold}, modality={modality}, {num_frames}f)\n"
        f"# Launch manually with: {commands['train_command_manual_only']}\n"
        f"# DEC-008 §5: Train strictly on clean fold_{fold}_train; evaluate only on eval-dev-v1 ∩ fold_{fold}_val.\n"
    )
    yaml_text = header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    yaml_bytes = yaml_text.encode("utf-8")
    commands["yaml_sha256"] = hashlib.sha256(yaml_bytes).hexdigest()
    commands_text = json.dumps(commands, ensure_ascii=False, indent=2) + "\n"
    safe_write_bytes(yaml_path, yaml_bytes, overwrite=overwrite, label="output_yaml")
    safe_write_bytes(commands_path, commands_text.encode("utf-8"), overwrite=overwrite, label="commands_json")
    return cfg, commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-commands-json", help="Pre-launch verification mode: verify rendered YAML & dataset bundle hashes before training")
    parser.add_argument("--run-verified-train", help="Controlled launch mode: verify clean dir/bundle, run llamafactory-cli train, and seal provenance only on rc=0")
    parser.add_argument("--verify-serve-commands-json", help="Pre-serve verification mode: verify adapter provenance & fold match before vllm serve")
    parser.add_argument("--verify-yaml", help="Explicit YAML path being launched (must match commands manifest yaml_path)")
    parser.add_argument("--expected-fold", type=int, choices=SUPPORTED_FOLDS, help="Expected fold for --verify-serve-commands-json")
    parser.add_argument("--expected-adapter-dir", help="Expected adapter directory for --verify-serve-commands-json")
    parser.add_argument("--fold", type=int, choices=SUPPORTED_FOLDS, help="CV fold (0, 1, or 2)")
    parser.add_argument("--modality", choices=SUPPORTED_MODALITIES, help="Channel modality: images or video")
    parser.add_argument("--num-frames", type=int, choices=SUPPORTED_NUM_FRAMES, help="Number of L3 frames per clip")
    parser.add_argument("--dataset-dir", help="Directory containing dataset_info.json and dataset JSON")
    parser.add_argument("--dataset-name", help="Dataset key in dataset_info.json (default: tensile_five_label_fold{k}_{modality}_{K}f)")
    parser.add_argument("--train-output-dir", help="Adapter output directory (e.g. trains/sft-fold0-video16f/adapter)")
    parser.add_argument("--output-yaml", help="Target YAML file path (.yaml/.yml; also writes .commands.json)")
    parser.add_argument("--model-name-or-path", default=DEFAULT_BASE_MODEL_PATH, help="Base model path on training machine")
    parser.add_argument("--cutoff-len", type=int, help="Override cutoff_len")
    parser.add_argument("--vllm-max-model-len", type=int, help="Override vLLM --max-model-len")
    parser.add_argument("--image-max-pixels", type=int, help="Override image_max_pixels (images mode)")
    parser.add_argument("--image-min-pixels", type=int, help="Override image_min_pixels (images mode)")
    parser.add_argument("--video-max-pixels", type=int, help="Override video_max_pixels (video mode)")
    parser.add_argument("--video-min-pixels", type=int, help="Override video_min_pixels (video mode)")
    parser.add_argument("--video-fps", type=float, help="Override video_fps (video mode; default 2.0)")
    parser.add_argument("--lora-rank", type=int, default=16, help="LoRA rank (default 16)")
    parser.add_argument("--lora-alpha", type=int, default=32, help="LoRA alpha (default 32)")
    parser.add_argument("--learning-rate", type=float, default=1.0e-4, help="Learning rate (default 1e-4)")
    parser.add_argument("--num-train-epochs", type=float, default=3.0, help="Epochs (default 3.0)")
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8, help="Grad accumulation steps (default 8)")
    parser.add_argument("--port", type=int, default=18080, help="Loopback vLLM serving port (default 18080)")
    parser.add_argument(
        "--allow-remote-dataset-dir",
        action="store_true",
        help="Skip local build_summary.json/dataset_info.json verification when rendering for a remote host path",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args(argv)

    try:
        modes = sum(
            bool(x)
            for x in (args.verify_commands_json, args.run_verified_train, args.verify_serve_commands_json)
        )
        if modes > 1:
            raise InputError(
                "pass at most one of --verify-commands-json, --run-verified-train, --verify-serve-commands-json"
            )
        if args.verify_commands_json:
            live = verify_rendered_launch(args.verify_commands_json, expected_yaml_path=args.verify_yaml)
            print(
                f"OK: pre-launch verification passed for {args.verify_commands_json} "
                f"(dataset_sha256={live['dataset_sha256'][:12]}..., lineage_sha256={live['frame_lineage_sha256'][:12]}...)"
            )
            return 0
        if args.run_verified_train:
            prov = run_verified_training(args.run_verified_train, expected_yaml_path=args.verify_yaml)
            print(
                f"OK: verified training succeeded and sealed provenance in {prov['adapter_dir']}/{ADAPTER_PROVENANCE_FILENAME} "
                f"(fold={prov['fold']}, weights={prov['adapter_weights_file']})"
            )
            return 0
        if args.verify_serve_commands_json:
            prov = verify_serve_launch(
                args.verify_serve_commands_json,
                expected_fold=args.expected_fold,
                expected_adapter_dir=args.expected_adapter_dir,
            )
            print(
                f"OK: pre-serve adapter provenance verified for fold_{prov['fold']} "
                f"({prov['lora_module_name']} @ {prov['adapter_dir']})"
            )
            return 0
        missing = [
            flag
            for flag, val in (
                ("--fold", args.fold),
                ("--modality", args.modality),
                ("--num-frames", args.num_frames),
                ("--dataset-dir", args.dataset_dir),
                ("--train-output-dir", args.train_output_dir),
                ("--output-yaml", args.output_yaml),
            )
            if val is None
        ]
        if missing:
            raise InputError(f"missing required arguments: {', '.join(missing)}")
        ds_name = args.dataset_name or f"tensile_five_label_fold{args.fold}_{args.modality}_{args.num_frames}f"
        cfg, commands = render_config_bundle(
            fold=args.fold,
            modality=args.modality,
            num_frames=args.num_frames,
            dataset_dir=args.dataset_dir,
            dataset_name=ds_name,
            train_output_dir=args.train_output_dir,
            output_yaml=Path(args.output_yaml),
            model_name_or_path=args.model_name_or_path,
            cutoff_len=args.cutoff_len,
            vllm_max_model_len=args.vllm_max_model_len,
            image_max_pixels=args.image_max_pixels,
            image_min_pixels=args.image_min_pixels,
            video_max_pixels=args.video_max_pixels,
            video_min_pixels=args.video_min_pixels,
            video_fps=args.video_fps,
            lora_rank=args.lora_rank,
            lora_alpha=args.lora_alpha,
            learning_rate=args.learning_rate,
            num_train_epochs=args.num_train_epochs,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            port=args.port,
            allow_remote_dataset_dir=args.allow_remote_dataset_dir,
            overwrite=args.overwrite,
        )
        print(
            f"Wrote {args.output_yaml} and {args.output_yaml}.commands.json "
            f"(fold={args.fold}, modality={args.modality}, num_frames={args.num_frames}, "
            f"cutoff_len={cfg['cutoff_len']}, lora={commands['lora_module_name']})"
        )
        return 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
