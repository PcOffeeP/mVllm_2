"""Pure-CPU LlamaFactory + Qwen3-VL runtime input verifier and L4 patch-tensor reconstructor.

Loads the final SFT dataset bundle + rendered LlamaFactory QLoRA YAML on CPU
(``CUDA_VISIBLE_DEVICES=""``), executes the exact ``Qwen3VLPlugin`` + ``qwen3_vl_nothink``
preprocessing pipeline, and verifies:

1. Actual ``video_grid_thw`` / ``image_grid_thw`` matches ``preflight_report.json`` (0 mismatch).
2. Actual untruncated ``input_ids`` length <= ``cutoff_len`` (0 truncation).
3. Actual ``<|video_pad|>`` / ``<|image_pad|>`` counts and decoded ``<t.t seconds>`` timestamps
   match ``frame_lineage.jsonl`` 1:1.
4. Reconstructs all K L4 RGB frames directly from flattened ``pixel_values`` /
   ``pixel_values_videos`` tensors (verified exact Qwen3-VL axis order) and dumps them as PNGs.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

import numpy as np
from PIL import Image
import yaml

from script.five_label_eval.errors import InputError
from script.five_label_eval.score import decode_file

from .constants import (
    FRAME_LINEAGE_SCHEMA,
    QWEN3_VL_MERGE_SIZE,
    QWEN3_VL_PATCH_SIZE,
    QWEN3_VL_TEMPORAL_PATCH_SIZE,
    RUNTIME_VERIFY_SCHEMA,
    SUPPORTED_MODALITIES,
)
from .data_guards import (
    assert_no_input_output_collision,
    assert_no_symlink_components,
    safe_write_bytes,
    sha256_bytes,
    validate_safe_output_path,
    validate_safe_path_component,
)
from .render_config import verify_dataset_bundle

TIMESTAMP_LABEL_RE = re.compile(r"<\d+(?:\.\d+)? seconds>")
DEFAULT_IMAGE_MEAN = (0.5, 0.5, 0.5)
DEFAULT_IMAGE_STD = (0.5, 0.5, 0.5)


def _to_numpy_float32(arr: Any) -> np.ndarray:
    if hasattr(arr, "detach"):
        arr = arr.detach().cpu().numpy()
    return np.asarray(arr, dtype=np.float32)


def _to_numpy_int64(arr: Any) -> np.ndarray:
    if hasattr(arr, "detach"):
        arr = arr.detach().cpu().numpy()
    return np.asarray(arr, dtype=np.int64)


def reconstruct_l4_frames_from_patches(
    pixel_values: Any,
    grid_thw: Any,
    *,
    modality: str,
    patch_size: int = QWEN3_VL_PATCH_SIZE,
    merge_size: int = QWEN3_VL_MERGE_SIZE,
    temporal_patch_size: int = QWEN3_VL_TEMPORAL_PATCH_SIZE,
    image_mean: tuple[float, float, float] = DEFAULT_IMAGE_MEAN,
    image_std: tuple[float, float, float] = DEFAULT_IMAGE_STD,
) -> list[np.ndarray]:
    """Reconstruct all K L4 RGB frames ``(H, W, 3) uint8`` from flattened Qwen3-VL patch tensors.

    Uses the verified Qwen3-VL ``Qwen2VLImageProcessorFast`` / ``Qwen3VLVideoProcessor``
    permutation (transformers 4.57.6):
        ``(gt, gh // m, gw // m, m, m, C=3, tp=2, p=16, p=16)``
        -> ``transpose(0, 6, 1, 3, 7, 2, 4, 8, 5)``
        -> ``reshape(gt * tp, gh * p, gw * p, 3)``
    where channel ``C`` precedes ``temporal_patch_size`` ``tp``.
    """
    if modality not in SUPPORTED_MODALITIES:
        raise InputError(f"unsupported modality {modality!r}")
    pv = _to_numpy_float32(pixel_values)
    grid = _to_numpy_int64(grid_thw)
    if grid.ndim == 1:
        if grid.shape != (3,):
            raise InputError(f"grid_thw must have shape (N, 3) or (3,), got {grid.shape}")
        grid = grid.reshape(1, 3)
    if grid.ndim != 2 or grid.shape[1] != 3 or grid.shape[0] == 0:
        raise InputError(f"grid_thw must have shape (N, 3) with N >= 1, got {grid.shape}")

    expected_patch_dim = 3 * temporal_patch_size * patch_size * patch_size
    if pv.ndim != 2 or pv.shape[1] != expected_patch_dim:
        raise InputError(
            f"pixel_values must have shape (N_patches, {expected_patch_dim}), got {pv.shape}"
        )

    mean = np.asarray(image_mean, dtype=np.float32).reshape(1, 1, 1, 3)
    std = np.asarray(image_std, dtype=np.float32).reshape(1, 1, 1, 3)
    m = int(merge_size)
    p = int(patch_size)
    tp = int(temporal_patch_size)

    def _decode_block(block: np.ndarray, gt: int, gh: int, gw: int) -> np.ndarray:
        if gt <= 0 or gh <= 0 or gw <= 0:
            raise InputError(f"grid_thw dimensions must be positive, got {(gt, gh, gw)}")
        if gh % m != 0 or gw % m != 0:
            raise InputError(f"grid_thw spatial dims {(gh, gw)} must be divisible by merge_size={m}")
        expected_rows = gt * gh * gw
        if block.shape[0] != expected_rows:
            raise InputError(f"patch row count {block.shape[0]} != gt*gh*gw ({expected_rows})")
        x = block.reshape(gt, gh // m, gw // m, m, m, 3, tp, p, p)
        x = x.transpose(0, 6, 1, 3, 7, 2, 4, 8, 5).reshape(gt * tp, gh * p, gw * p, 3)
        rgb = np.clip(np.round((x * std + mean) * 255.0), 0.0, 255.0).astype(np.uint8)
        return rgb

    if modality == "video":
        if grid.shape[0] != 1:
            raise InputError(f"video modality expects single video grid_thw (1, 3), got {grid.shape}")
        gt, gh, gw = (int(grid[0, 0]), int(grid[0, 1]), int(grid[0, 2]))
        rgb_seq = _decode_block(pv, gt, gh, gw)
        return [rgb_seq[idx].copy() for idx in range(rgb_seq.shape[0])]

    # modality == "images": concatenate K images, each duplicated along tp=2 with gt=1.
    frames: list[np.ndarray] = []
    offset = 0
    for img_idx in range(grid.shape[0]):
        gt, gh, gw = (int(grid[img_idx, 0]), int(grid[img_idx, 1]), int(grid[img_idx, 2]))
        if gt != 1:
            raise InputError(f"images[{img_idx}] expected gt=1, got {gt}")
        n_rows = gt * gh * gw
        block = pv[offset : offset + n_rows]
        if block.shape[0] != n_rows:
            raise InputError(
                f"pixel_values truncated at images[{img_idx}]: needed {n_rows} rows at offset {offset}, "
                f"total rows={pv.shape[0]}"
            )
        offset += n_rows
        rgb_pair = _decode_block(block, gt, gh, gw)
        for dup_idx in range(1, rgb_pair.shape[0]):
            if not np.array_equal(rgb_pair[0], rgb_pair[dup_idx]):
                max_diff = int(np.max(np.abs(rgb_pair[0].astype(np.int16) - rgb_pair[dup_idx].astype(np.int16))))
                raise InputError(
                    f"images[{img_idx}] temporal duplicate mismatch across tp={tp} "
                    f"(max_abs_diff={max_diff}); patch axis order may have drifted"
                )
        frames.append(rgb_pair[0].copy())
    if offset != pv.shape[0]:
        raise InputError(f"pixel_values has trailing unconsumed rows: consumed {offset} != total {pv.shape[0]}")
    return frames


def extract_decoded_video_timestamps(decoded_text: str) -> list[str]:
    """Extract ordered ``<t.t seconds>`` temporal markers from decoded Qwen3-VL prompt text."""
    return TIMESTAMP_LABEL_RE.findall(decoded_text)


def load_frame_lineage_jsonl(path: Path | str) -> list[dict[str, Any]]:
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise InputError(f"missing non-symlink frame_lineage.jsonl: {p}")
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"{p}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict) or obj.get("schema") != FRAME_LINEAGE_SCHEMA:
            raise InputError(f"{p}:{lineno}: invalid frame_lineage schema")
        rows.append(obj)
    if not rows:
        raise InputError(f"{p}: frame_lineage.jsonl is empty")
    return rows


def _expected_pair_timestamps_from_lineage(sample_lineage: dict[str, Any]) -> list[str]:
    seen_pairs: dict[int, str] = {}
    for frame in sample_lineage["frames"]:
        pair_idx = frame.get("temporal_pair_index")
        label = frame.get("injected_timestamp_label")
        if not isinstance(pair_idx, int) or not isinstance(label, str):
            raise InputError(
                f"{sample_lineage['candidate_id']}: missing temporal_pair_index/injected_timestamp_label in frame_lineage.jsonl"
            )
        if pair_idx in seen_pairs and seen_pairs[pair_idx] != label:
            raise InputError(
                f"{sample_lineage['candidate_id']}: conflicting timestamps for temporal_pair_index={pair_idx}"
            )
        seen_pairs[pair_idx] = label
    return [seen_pairs[idx] for idx in sorted(seen_pairs)]


def verify_sample_runtime_outputs(
    *,
    sample_lineage: dict[str, Any],
    preflight_entry: dict[str, Any],
    modality: str,
    cutoff_len: int,
    actual_grid_thw: list[list[int]],
    actual_input_ids_len: int,
    actual_pad_token_count: int,
    actual_timestamps: list[str],
    l4_frames: list[np.ndarray],
    patch_size: int = QWEN3_VL_PATCH_SIZE,
) -> dict[str, Any]:
    """Compare live LlamaFactory processor outputs against preflight geometry and ``frame_lineage.jsonl``."""
    cid = validate_safe_path_component(sample_lineage.get("candidate_id"), "candidate_id")
    sid = validate_safe_path_component(sample_lineage.get("source_id"), "source_id")
    num_frames = int(sample_lineage["num_frames"])

    raw_grid = preflight_entry.get("grid_thw")
    if not isinstance(raw_grid, list) or len(raw_grid) != 3 or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw_grid):
        raise InputError(f"{cid}: preflight entry missing valid 3-element integer grid_thw: {raw_grid!r}")
    expected_single_grid = [int(x) for x in raw_grid]

    resized_size = preflight_entry.get("resized_size")
    if (
        not isinstance(resized_size, list)
        or len(resized_size) != 2
        or not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in resized_size)
    ):
        raise InputError(f"{cid}: preflight entry missing valid resized_size [width, height]: {resized_size!r}")
    expected_resized_w, expected_resized_h = int(resized_size[0]), int(resized_size[1])

    if modality == "video":
        expected_grid_list = [expected_single_grid]
    else:
        if expected_single_grid[0] != num_frames:
            raise InputError(
                f"{cid}: images preflight grid_thw[0]={expected_single_grid[0]} != num_frames={num_frames}"
            )
        # Qwen2VLImageProcessorFast emits one [1, gh, gw] row per image frame.
        expected_grid_list = [[1, expected_single_grid[1], expected_single_grid[2]] for _ in range(num_frames)]

    expected_pad_tokens = int(preflight_entry["visual_pad_tokens"])

    errors: list[str] = []
    grid_match = actual_grid_thw == expected_grid_list
    if not grid_match:
        errors.append(f"grid_thw mismatch: actual={actual_grid_thw} != preflight={expected_grid_list}")

    within_cutoff = actual_input_ids_len <= cutoff_len
    if not within_cutoff:
        errors.append(f"actual input_ids length {actual_input_ids_len} exceeds cutoff_len {cutoff_len}")

    pad_match = actual_pad_token_count == expected_pad_tokens
    if not pad_match:
        errors.append(
            f"visual pad token count mismatch: actual={actual_pad_token_count} != preflight={expected_pad_tokens}"
        )

    expected_timestamps: list[str] = []
    timestamps_match = True
    if modality == "video":
        expected_timestamps = _expected_pair_timestamps_from_lineage(sample_lineage)
        timestamps_match = actual_timestamps == expected_timestamps
        if not timestamps_match:
            errors.append(
                f"decoded video timestamps mismatch: actual={actual_timestamps} != lineage={expected_timestamps}"
            )
    else:
        if actual_timestamps:
            timestamps_match = False
            errors.append(f"unexpected video timestamps in images mode: {actual_timestamps}")

    frame_count_match = len(l4_frames) == num_frames
    if not frame_count_match:
        errors.append(f"reconstructed L4 frame count {len(l4_frames)} != num_frames {num_frames}")

    l4_shapes = [list(f.shape) for f in l4_frames]
    expected_shape = [expected_resized_h, expected_resized_w, 3]
    shape_match = all(s == expected_shape for s in l4_shapes)
    if not shape_match:
        errors.append(
            f"reconstructed L4 frame shape mismatch: expected {expected_shape} "
            f"(grid*patch_size={expected_single_grid[1]*patch_size}x{expected_single_grid[2]*patch_size}), "
            f"got {l4_shapes[:2]}"
        )

    return {
        "candidate_id": cid,
        "source_id": sid,
        "sample_index": sample_lineage["sample_index"],
        "modality": modality,
        "num_frames": num_frames,
        "passed": len(errors) == 0,
        "errors": errors,
        "expected_grid_thw": expected_grid_list,
        "actual_grid_thw": actual_grid_thw,
        "grid_match": grid_match,
        "cutoff_len": cutoff_len,
        "actual_input_ids_len": actual_input_ids_len,
        "estimated_total_tokens": preflight_entry.get("estimated_total_tokens"),
        "within_cutoff": within_cutoff,
        "expected_pad_tokens": expected_pad_tokens,
        "actual_pad_tokens": actual_pad_token_count,
        "pad_match": pad_match,
        "expected_timestamps": expected_timestamps,
        "actual_timestamps": actual_timestamps,
        "timestamps_match": timestamps_match,
        "l4_frame_count": len(l4_frames),
        "l4_frame_shape": l4_shapes[0] if l4_shapes else None,
    }


def _encode_png_bytes(rgb_array: np.ndarray) -> bytes:
    buf = BytesIO()
    Image.fromarray(rgb_array, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _build_llamafactory_cpu_runner(cfg: dict[str, Any], *, modality: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a pure-CPU LlamaFactory + Qwen3-VL processor runner (lazy imports for Mac offline tests)."""
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    from llamafactory.data.template import get_template_and_fix_tokenizer
    from llamafactory.hparams import DataArguments
    from transformers import AutoProcessor

    model_path = cfg["model_name_or_path"]
    template_name = cfg.get("template", "qwen3_vl_nothink")
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=False)
    tokenizer = processor.tokenizer

    if modality == "images":
        setattr(processor, "image_max_pixels", int(cfg["image_max_pixels"]))
        setattr(processor, "image_min_pixels", int(cfg["image_min_pixels"]))
    else:
        setattr(processor, "video_max_pixels", int(cfg["video_max_pixels"]))
        setattr(processor, "video_min_pixels", int(cfg["video_min_pixels"]))
        setattr(processor, "video_fps", float(cfg["video_fps"]))
        setattr(processor, "video_maxlen", int(cfg.get("video_maxlen", 128)))

    data_args = DataArguments(
        template=template_name,
        cutoff_len=int(cfg["cutoff_len"]),
    )
    template = get_template_and_fix_tokenizer(tokenizer, data_args)
    plugin = template.mm_plugin

    vis_proc = processor.image_processor if modality == "images" else processor.video_processor
    patch_size = int(getattr(vis_proc, "patch_size", QWEN3_VL_PATCH_SIZE))
    merge_size = int(getattr(vis_proc, "merge_size", QWEN3_VL_MERGE_SIZE))
    temporal_patch_size = int(getattr(vis_proc, "temporal_patch_size", QWEN3_VL_TEMPORAL_PATCH_SIZE))
    raw_mean = getattr(vis_proc, "image_mean", DEFAULT_IMAGE_MEAN)
    raw_std = getattr(vis_proc, "image_std", DEFAULT_IMAGE_STD)
    image_mean = (float(raw_mean[0]), float(raw_mean[1]), float(raw_mean[2]))
    image_std = (float(raw_std[0]), float(raw_std[1]), float(raw_std[2]))

    pad_token_str = "<|image_pad|>" if modality == "images" else "<|video_pad|>"
    pad_token_id = tokenizer.convert_tokens_to_ids(pad_token_str)
    if not isinstance(pad_token_id, int) or pad_token_id < 0:
        raise InputError(f"tokenizer failed to resolve {pad_token_str!r} token id: {pad_token_id!r}")

    def _run_one(dataset_row: dict[str, Any]) -> dict[str, Any]:
        raw_messages = dataset_row["messages"]
        images = list(dataset_row.get("images") or [])
        videos = list(dataset_row.get("videos") or [])

        processed_messages = plugin.process_messages(raw_messages, images, videos, [], processor)
        mm_inputs = plugin._get_mm_inputs(images, videos, [], processor)
        encoded_pairs = template.encode_multiturn(tokenizer, processed_messages, None, None)
        if not encoded_pairs:
            raise InputError("template.encode_multiturn returned empty encoded_pairs")
        untruncated_ids: list[int] = []
        source_ids_all: list[int] = []
        for src_ids, tgt_ids in encoded_pairs:
            source_ids_all.extend(src_ids)
            untruncated_ids.extend(src_ids)
            untruncated_ids.extend(tgt_ids)
        if getattr(template, "efficient_eos", False):
            untruncated_ids.append(int(tokenizer.eos_token_id))

        pad_count = sum(1 for tok in untruncated_ids if tok == pad_token_id)
        decoded_source = tokenizer.decode(source_ids_all, skip_special_tokens=False)
        timestamps = extract_decoded_video_timestamps(decoded_source)

        if modality == "video":
            grid = _to_numpy_int64(mm_inputs["video_grid_thw"])
            pv = mm_inputs["pixel_values_videos"]
        else:
            grid = _to_numpy_int64(mm_inputs["image_grid_thw"])
            pv = mm_inputs["pixel_values"]

        l4_frames = reconstruct_l4_frames_from_patches(
            pv,
            grid,
            modality=modality,
            patch_size=patch_size,
            merge_size=merge_size,
            temporal_patch_size=temporal_patch_size,
            image_mean=image_mean,
            image_std=image_std,
        )
        return {
            "actual_grid_thw": [[int(v) for v in row] for row in grid.reshape(-1, 3).tolist()],
            "actual_input_ids_len": len(untruncated_ids),
            "actual_pad_token_count": pad_count,
            "actual_timestamps": timestamps,
            "l4_frames": l4_frames,
            "patch_size": patch_size,
        }

    return _run_one


def _validate_yaml_for_modality(
    cfg: dict[str, Any],
    *,
    modality: str,
    yaml_path: Path,
    require_model_path: bool,
) -> tuple[str, int]:
    """Validate required YAML keys and enforce strict modality alignment (fail-closed InputError)."""
    dataset_name = cfg.get("dataset")
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise InputError(f"{yaml_path}: missing or invalid 'dataset' key")
    cutoff_len = cfg.get("cutoff_len")
    if isinstance(cutoff_len, bool) or not isinstance(cutoff_len, int) or cutoff_len <= 0:
        raise InputError(f"{yaml_path}: missing or invalid positive integer 'cutoff_len': {cutoff_len!r}")
    if require_model_path:
        model_path = cfg.get("model_name_or_path")
        if not isinstance(model_path, str) or not model_path.strip():
            raise InputError(f"{yaml_path}: missing or invalid 'model_name_or_path'")

    if modality == "images":
        for req_key in ("image_max_pixels", "image_min_pixels"):
            val = cfg.get(req_key)
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise InputError(
                    f"{yaml_path}: modality='images' requires positive integer {req_key}, got {val!r}"
                )
        for bad_key in ("video_max_pixels", "video_min_pixels", "video_fps"):
            if cfg.get(bad_key) is not None:
                raise InputError(
                    f"{yaml_path}: YAML/bundle modality mismatch — bundle is 'images' but YAML sets {bad_key}={cfg.get(bad_key)!r}"
                )
    elif modality == "video":
        for req_key in ("video_max_pixels", "video_min_pixels"):
            val = cfg.get(req_key)
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise InputError(
                    f"{yaml_path}: modality='video' requires positive integer {req_key}, got {val!r}"
                )
        vfps = cfg.get("video_fps")
        if isinstance(vfps, bool) or not isinstance(vfps, (int, float)) or float(vfps) <= 0:
            raise InputError(
                f"{yaml_path}: modality='video' requires positive number video_fps, got {vfps!r}"
            )
        for bad_key in ("image_max_pixels", "image_min_pixels"):
            if cfg.get(bad_key) is not None:
                raise InputError(
                    f"{yaml_path}: YAML/bundle modality mismatch — bundle is 'video' but YAML sets {bad_key}={cfg.get(bad_key)!r}"
                )
    else:
        raise InputError(f"unsupported modality {modality!r}")
    return dataset_name, cutoff_len


def run_runtime_verification(
    *,
    yaml_path: Path | str,
    output_dir: Path | str,
    dataset_dir_override: Path | str | None = None,
    candidate_ids: list[str] | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    processor_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute pure-CPU runtime verification against a rendered YAML + verified SFT bundle."""
    y_path = Path(yaml_path)
    if y_path.is_symlink() or not y_path.is_file():
        raise InputError(f"missing non-symlink YAML config: {y_path}")
    cfg = yaml.safe_load(y_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise InputError(f"{y_path}: invalid YAML config")

    out_dir = Path(output_dir)
    validate_safe_output_path(out_dir, label="output_dir")
    assert_no_symlink_components(out_dir, label="output_dir")

    raw_ds_dir = dataset_dir_override if dataset_dir_override is not None else cfg.get("dataset_dir")
    if not isinstance(raw_ds_dir, (str, Path)) or not str(raw_ds_dir).strip():
        raise InputError(f"{y_path}: missing 'dataset_dir' (or pass --dataset-dir)")
    ds_dir = Path(raw_ds_dir)
    summary_path = ds_dir / "build_summary.json"
    if summary_path.is_symlink() or not summary_path.is_file():
        raise InputError(f"dataset_dir missing non-symlink build_summary.json: {summary_path}")
    summary = decode_file(summary_path.read_text(encoding="utf-8"), str(summary_path))
    if not isinstance(summary, dict):
        raise InputError(f"{summary_path}: invalid build_summary.json object")
    for req_sum_key in ("fold", "modality", "num_frames"):
        if req_sum_key not in summary:
            raise InputError(f"{summary_path}: missing required key {req_sum_key!r}")
    fold = int(summary["fold"])
    modality = str(summary["modality"])
    num_frames = int(summary["num_frames"])

    dataset_name, cutoff_len = _validate_yaml_for_modality(
        cfg,
        modality=modality,
        yaml_path=y_path,
        require_model_path=processor_runner is None,
    )

    bundle_ver = verify_dataset_bundle(
        dataset_dir=ds_dir,
        fold=fold,
        modality=modality,
        num_frames=num_frames,
        dataset_name=dataset_name,
        cutoff_len=cutoff_len,
        image_max_pixels=cfg.get("image_max_pixels"),
        image_min_pixels=cfg.get("image_min_pixels"),
        video_max_pixels=cfg.get("video_max_pixels"),
        video_min_pixels=cfg.get("video_min_pixels"),
        video_fps=cfg.get("video_fps"),
    )

    resolved_ds_dir = Path(bundle_ver["resolved_dataset_dir"])
    dataset_path = resolved_ds_dir / bundle_ver["dataset_file"]
    preflight_path = resolved_ds_dir / "preflight_report.json"
    lineage_path = resolved_ds_dir / "frame_lineage.jsonl"

    dataset_rows = decode_file(dataset_path.read_text(encoding="utf-8"), str(dataset_path))
    preflight = decode_file(preflight_path.read_text(encoding="utf-8"), str(preflight_path))
    lineage_rows = load_frame_lineage_jsonl(lineage_path)
    raw_pf_samples = preflight.get("samples") if isinstance(preflight, dict) else None
    if not isinstance(raw_pf_samples, list) or not raw_pf_samples:
        raise InputError(
            f"{preflight_path}: missing non-empty per-sample 'samples' list; re-export bundle with build_dataset.py"
        )
    preflight_by_cid = {
        row["candidate_id"]: row
        for row in raw_pf_samples
        if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)
    }

    selected_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = list(zip(lineage_rows, dataset_rows))
    if candidate_ids:
        wanted = set(candidate_ids)
        selected_pairs = [(lr, dr) for lr, dr in selected_pairs if lr["candidate_id"] in wanted]
        found = {lr["candidate_id"] for lr, _ in selected_pairs}
        missing = sorted(wanted - found)
        if missing:
            raise InputError(f"requested --candidate-ids absent from bundle: {missing}")
    if limit is not None:
        if limit <= 0:
            raise InputError(f"--limit must be positive, got {limit}")
        selected_pairs = selected_pairs[:limit]
    if not selected_pairs:
        raise InputError("no samples selected for runtime verification")

    l4_root = out_dir / "l4_reconstructed"
    report_path = out_dir / "runtime_verify_report.json"

    # Enumerate EVERY planned output (report + all K reconstructed L4 PNGs per candidate)
    # and EVERY input file (including every L3 PNG referenced by the dataset bundle) BEFORE writing.
    planned_outputs: list[Path] = [report_path]
    for lineage_row, _ in selected_pairs:
        cid_safe = validate_safe_path_component(lineage_row.get("candidate_id"), "candidate_id")
        validate_safe_path_component(lineage_row.get("source_id"), "source_id")
        for idx in range(num_frames):
            planned_outputs.append(l4_root / cid_safe / f"frame_{idx:02d}.png")

    all_input_paths: list[Path | str | None] = [
        y_path,
        summary_path,
        dataset_path,
        preflight_path,
        lineage_path,
    ]
    verified_shas = summary.get("verified_frame_sha256s")
    if isinstance(verified_shas, dict):
        all_input_paths.extend(verified_shas.keys())
    for drow in dataset_rows:
        if isinstance(drow, dict):
            if modality == "images" and isinstance(drow.get("images"), list):
                all_input_paths.extend(drow["images"])
            elif modality == "video" and isinstance(drow.get("videos"), list):
                for seq in drow["videos"]:
                    if isinstance(seq, list):
                        all_input_paths.extend(seq)

    assert_no_input_output_collision(
        planned_outputs,
        all_input_paths,
        context="verify_runtime_input",
    )

    runner = processor_runner if processor_runner is not None else _build_llamafactory_cpu_runner(cfg, modality=modality)

    sample_reports: list[dict[str, Any]] = []
    failed_cids: list[str] = []

    for lineage_row, dataset_row in selected_pairs:
        cid = validate_safe_path_component(lineage_row.get("candidate_id"), "candidate_id")
        validate_safe_path_component(lineage_row.get("source_id"), "source_id")
        pf_entry = preflight_by_cid.get(cid)
        if pf_entry is None:
            raise InputError(f"{cid}: missing from {preflight_path}")
        live = runner(dataset_row)
        l4_frames: list[np.ndarray] = live["l4_frames"]
        ver = verify_sample_runtime_outputs(
            sample_lineage=lineage_row,
            preflight_entry=pf_entry,
            modality=modality,
            cutoff_len=cutoff_len,
            actual_grid_thw=live["actual_grid_thw"],
            actual_input_ids_len=int(live["actual_input_ids_len"]),
            actual_pad_token_count=int(live["actual_pad_token_count"]),
            actual_timestamps=list(live["actual_timestamps"]),
            l4_frames=l4_frames,
            patch_size=int(live.get("patch_size", QWEN3_VL_PATCH_SIZE)),
        )

        dumped_files: list[dict[str, Any]] = []
        for idx, frame_rgb in enumerate(l4_frames):
            out_png = l4_root / cid / f"frame_{idx:02d}.png"
            png_bytes = _encode_png_bytes(frame_rgb)
            safe_write_bytes(out_png, png_bytes, overwrite=overwrite, label="l4_reconstructed_png")
            dumped_files.append(
                {
                    "display_order": idx,
                    "path": str(out_png.resolve()),
                    "width": int(frame_rgb.shape[1]),
                    "height": int(frame_rgb.shape[0]),
                    "sha256": sha256_bytes(png_bytes),
                }
            )
        ver["l4_reconstructed_files"] = dumped_files
        if not ver["passed"]:
            failed_cids.append(cid)
        sample_reports.append(ver)

    actual_lens = [r["actual_input_ids_len"] for r in sample_reports]
    report: dict[str, Any] = {
        "schema": RUNTIME_VERIFY_SCHEMA,
        "yaml_path": str(y_path.resolve()),
        "dataset_dir": str(resolved_ds_dir),
        "dataset_name": dataset_name,
        "fold": fold,
        "modality": modality,
        "num_frames": num_frames,
        "cutoff_len": cutoff_len,
        "cpu_only_enforced": processor_runner is None,
        "bundle_verification": bundle_ver,
        "verified_sample_count": len(sample_reports),
        "passed_sample_count": len(sample_reports) - len(failed_cids),
        "failed_sample_count": len(failed_cids),
        "failed_candidate_ids": failed_cids,
        "grid_mismatch_count": sum(1 for r in sample_reports if not r["grid_match"]),
        "truncation_count": sum(1 for r in sample_reports if not r["within_cutoff"]),
        "pad_mismatch_count": sum(1 for r in sample_reports if not r["pad_match"]),
        "timestamp_mismatch_count": sum(1 for r in sample_reports if not r["timestamps_match"]),
        "actual_input_ids_len": {
            "min": min(actual_lens),
            "max": max(actual_lens),
        },
        "l4_reconstructed_dir": str(l4_root.resolve()),
        "samples": sample_reports,
    }
    safe_write_bytes(
        report_path,
        (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
        overwrite=overwrite,
        label="runtime_verify_report",
    )

    if failed_cids:
        first_err = next(r["errors"] for r in sample_reports if not r["passed"])
        raise InputError(
            f"runtime verification FAILED on {len(failed_cids)}/{len(sample_reports)} sample(s) "
            f"(first={failed_cids[0]}: {first_err}); see {report_path}"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", required=True, help="Rendered LlamaFactory QLoRA YAML path")
    parser.add_argument("--output-dir", required=True, help="Directory for l4_reconstructed/ PNGs and runtime_verify_report.json")
    parser.add_argument("--dataset-dir", help="Optional override for dataset_dir in YAML")
    parser.add_argument("--candidate-ids", help="Optional comma-separated candidate_id subset to verify")
    parser.add_argument("--limit", type=int, help="Optional maximum number of samples to verify")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args(argv)

    try:
        cids = [c.strip() for c in args.candidate_ids.split(",") if c.strip()] if args.candidate_ids else None
        report = run_runtime_verification(
            yaml_path=args.yaml,
            output_dir=args.output_dir,
            dataset_dir_override=args.dataset_dir,
            candidate_ids=cids,
            limit=args.limit,
            overwrite=args.overwrite,
        )
        print(
            f"OK: verified {report['passed_sample_count']}/{report['verified_sample_count']} samples "
            f"(modality={report['modality']}, {report['num_frames']}f, "
            f"max_input_ids={report['actual_input_ids_len']['max']}/{report['cutoff_len']}, "
            f"grid_mismatch=0, truncation=0, timestamps_mismatch=0) -> {args.output_dir}"
        )
        return 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
