"""Unit tests for pure-CPU runtime verification and Qwen3-VL L4 patch tensor reconstruction."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import pytest
import yaml

from script.five_label_eval.errors import InputError
from script.five_label_sft.build_dataset import build_fold_sft_dataset
from script.five_label_sft.constants import RUNTIME_VERIFY_SCHEMA
from script.five_label_sft.data_guards import load_fold_isolation_context, select_confirmed_fold_train_samples
from script.five_label_sft.render_config import render_config_bundle
from script.five_label_sft.tests.test_build_dataset import _create_synthetic_repo, _write_fake_frames_and_manifest
from script.five_label_sft.tests.test_render_config import _create_verified_bundle
from script.five_label_sft.verify_runtime_input import (
    extract_decoded_video_timestamps,
    reconstruct_l4_frames_from_patches,
    run_runtime_verification,
)


def _forward_qwen3_vl_patchify(
    frames_rgb: list[np.ndarray],
    *,
    patch_size: int = 16,
    merge_size: int = 2,
    temporal_patch_size: int = 2,
    mean: tuple[float, float, float] = (0.5, 0.5, 0.5),
    std: tuple[float, float, float] = (0.5, 0.5, 0.5),
) -> tuple[np.ndarray, np.ndarray]:
    """Exact forward patchification mirroring Qwen3VLVideoProcessor / Qwen2VLImageProcessorFast."""
    arr = np.stack(frames_rgb, axis=0).astype(np.float32) / 255.0  # (T, H, W, 3)
    mean_arr = np.asarray(mean, dtype=np.float32).reshape(1, 1, 1, 3)
    std_arr = np.asarray(std, dtype=np.float32).reshape(1, 1, 1, 3)
    norm = (arr - mean_arr) / std_arr  # (T, H, W, 3)
    norm = norm.transpose(0, 3, 1, 2)  # (T, C, H, W)
    t, c, h, w = norm.shape
    gt = t // temporal_patch_size
    gh = h // patch_size
    gw = w // patch_size
    m = merge_size
    # Exact transformers 4.57.6 reshape & transpose:
    # (gt, tp, C, gh//m, m, p, gw//m, m, p) -> (gt, gh//m, gw//m, m, m, C, tp, p, p)
    patches = norm.reshape(gt, temporal_patch_size, c, gh // m, m, patch_size, gw // m, m, patch_size)
    patches = patches.transpose(0, 3, 6, 4, 7, 2, 1, 5, 8)
    flat = patches.reshape(gt * gh * gw, c * temporal_patch_size * patch_size * patch_size)
    grid = np.array([[gt, gh, gw]], dtype=np.int64)
    return flat, grid


def test_reconstruct_l4_video_16f_and_8f_bit_exact_roundtrip() -> None:
    rng = np.random.default_rng(20261128)
    for num_frames, (h, w) in ((16, (128, 96)), (8, (96, 64))):
        orig_frames = [rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8) for _ in range(num_frames)]
        pv, grid = _forward_qwen3_vl_patchify(orig_frames)
        recon = reconstruct_l4_frames_from_patches(pv, grid, modality="video")
        assert len(recon) == num_frames
        for idx, (orig, rec) in enumerate(zip(orig_frames, recon)):
            assert rec.shape == orig.shape
            assert rec.dtype == np.uint8
            assert int(np.max(np.abs(orig.astype(np.int16) - rec.astype(np.int16)))) == 0, f"mismatch at frame {idx}"


def test_reconstruct_l4_images_8f_bit_exact_and_duplicate_guard() -> None:
    rng = np.random.default_rng(77)
    orig_imgs = [rng.integers(0, 256, size=(96, 64, 3), dtype=np.uint8) for _ in range(8)]
    pv_list = []
    grid_list = []
    for img in orig_imgs:
        # Qwen2VLImageProcessorFast duplicates each image across temporal_patch_size=2.
        pv_i, grid_i = _forward_qwen3_vl_patchify([img, img])
        pv_list.append(pv_i)
        grid_list.append(grid_i)
    pv_all = np.concatenate(pv_list, axis=0)
    grid_all = np.concatenate(grid_list, axis=0)

    recon = reconstruct_l4_frames_from_patches(pv_all, grid_all, modality="images")
    assert len(recon) == 8
    for orig, rec in zip(orig_imgs, recon):
        assert np.array_equal(orig, rec)

    # Corrupt temporal duplicate (second copy differs from first) -> must fail closed!
    bad_pv_i, bad_grid_i = _forward_qwen3_vl_patchify([orig_imgs[0], orig_imgs[1]])
    with pytest.raises(InputError, match="temporal duplicate mismatch"):
        reconstruct_l4_frames_from_patches(bad_pv_i, bad_grid_i, modality="images")


def test_extract_decoded_video_timestamps() -> None:
    decoded = (
        "<|im_start|>user\n<0.2 seconds><|vision_start|><|video_pad|><|vision_end|>"
        "<1.2 seconds><|vision_start|><|video_pad|><|vision_end|>prompt"
    )
    assert extract_decoded_video_timestamps(decoded) == ["<0.2 seconds>", "<1.2 seconds>"]


def test_real_build_dataset_render_config_verify_runtime_both_channels(tmp_path: Path) -> None:
    """End-to-end contract test against REAL build_fold_sft_dataset + preflight_report.json (8f images & 16f video)."""
    fx = _create_synthetic_repo(tmp_path)
    root = fx["root"]
    ctx = load_fold_isolation_context(0, repo_root=root)
    samples, _ = select_confirmed_fold_train_samples(ctx)
    sample_meta = [
        {
            "candidate_id": s.candidate_id,
            "clip_sha256": s.clip_sha256,
            "total_frames": s.total_frames,
            "width": s.width,
            "height": s.height,
        }
        for s in samples
    ]

    # 1. Real 8f images channel (preflight grid_thw=[8, gh, gw], live Qwen2VLImageProcessorFast emits 8 x [1, gh, gw])
    fdir8, rec8 = _write_fake_frames_and_manifest(tmp_path / "l3_8f", ctx.manifest_sha256, sample_meta, 8)
    bundle8 = tmp_path / "bundle_img8"
    sum8 = build_fold_sft_dataset(
        fold=0,
        modality="images",
        num_frames=8,
        output_dir=bundle8,
        frames_manifest=rec8,
        frames_dir=fdir8,
        repo_root=root,
    )
    yaml8 = tmp_path / "fold0_img8.yaml"
    render_config_bundle(
        fold=0,
        modality="images",
        num_frames=8,
        dataset_dir=str(bundle8),
        dataset_name=sum8["dataset_name"],
        train_output_dir=str(tmp_path / "adapter_img8"),
        output_yaml=yaml8,
    )
    pf8 = json.loads((bundle8 / "preflight_report.json").read_text(encoding="utf-8"))
    pf8_by_cid = {r["candidate_id"]: r for r in pf8["samples"]}
    ds8 = json.loads((bundle8 / sum8["dataset_file"]).read_text(encoding="utf-8"))
    # Map frame_00 path -> candidate_id to simulate processor
    path_to_cid8 = {row["images"][0]: cid for row, cid in zip(ds8, sum8["exported_candidate_ids"])}

    def _images_runner(dataset_row: dict[str, Any]) -> dict[str, Any]:
        cid = path_to_cid8[dataset_row["images"][0]]
        pf = pf8_by_cid[cid]
        w, h = pf["resized_size"]
        _, gh, gw = pf["grid_thw"]
        frames = [np.full((h, w, 3), i * 15, dtype=np.uint8) for i in range(8)]
        return {
            "actual_grid_thw": [[1, gh, gw] for _ in range(8)],
            "actual_input_ids_len": pf["estimated_total_tokens"] - 10,
            "actual_pad_token_count": pf["visual_pad_tokens"],
            "actual_timestamps": [],
            "l4_frames": frames,
            "patch_size": 16,
        }

    out8 = tmp_path / "verify_img8"
    rep8 = run_runtime_verification(yaml_path=yaml8, output_dir=out8, processor_runner=_images_runner)
    assert rep8["schema"] == RUNTIME_VERIFY_SCHEMA
    assert rep8["passed_sample_count"] == 2
    assert rep8["grid_mismatch_count"] == 0
    assert rep8["truncation_count"] == 0
    assert rep8["timestamp_mismatch_count"] == 0
    for cid in sum8["exported_candidate_ids"]:
        w, h = pf8_by_cid[cid]["resized_size"]
        for i in range(8):
            with Image.open(out8 / "l4_reconstructed" / cid / f"frame_{i:02d}.png") as im:
                assert im.size == (w, h)

    # 2. Real 16f video channel (preflight grid_thw=[8, gh, gw], live Qwen3VLVideoProcessor emits [[8, gh, gw]])
    fdir16, rec16 = _write_fake_frames_and_manifest(tmp_path / "l3_16f", ctx.manifest_sha256, sample_meta, 16)
    bundle16 = tmp_path / "bundle_vid16"
    sum16 = build_fold_sft_dataset(
        fold=0,
        modality="video",
        num_frames=16,
        output_dir=bundle16,
        frames_manifest=rec16,
        frames_dir=fdir16,
        repo_root=root,
    )
    yaml16 = tmp_path / "fold0_vid16.yaml"
    render_config_bundle(
        fold=0,
        modality="video",
        num_frames=16,
        dataset_dir=str(bundle16),
        dataset_name=sum16["dataset_name"],
        train_output_dir=str(tmp_path / "adapter_vid16"),
        output_yaml=yaml16,
    )
    pf16 = json.loads((bundle16 / "preflight_report.json").read_text(encoding="utf-8"))
    pf16_by_cid = {r["candidate_id"]: r for r in pf16["samples"]}
    ds16 = json.loads((bundle16 / sum16["dataset_file"]).read_text(encoding="utf-8"))
    path_to_cid16 = {row["videos"][0][0]: cid for row, cid in zip(ds16, sum16["exported_candidate_ids"])}
    expected_ts16 = [f"<{idx + 0.25:.1f} seconds>" for idx in range(8)]

    def _video_runner(dataset_row: dict[str, Any]) -> dict[str, Any]:
        cid = path_to_cid16[dataset_row["videos"][0][0]]
        pf = pf16_by_cid[cid]
        w, h = pf["resized_size"]
        frames = [np.full((h, w, 3), i * 10, dtype=np.uint8) for i in range(16)]
        return {
            "actual_grid_thw": [list(pf["grid_thw"])],
            "actual_input_ids_len": pf["estimated_total_tokens"] - 10,
            "actual_pad_token_count": pf["visual_pad_tokens"],
            "actual_timestamps": expected_ts16,
            "l4_frames": frames,
            "patch_size": 16,
        }

    out16 = tmp_path / "verify_vid16"
    rep16 = run_runtime_verification(yaml_path=yaml16, output_dir=out16, processor_runner=_video_runner)
    assert rep16["passed_sample_count"] == 2
    assert rep16["grid_mismatch_count"] == 0
    assert rep16["truncation_count"] == 0
    assert rep16["timestamp_mismatch_count"] == 0

    # 3. Cross-modality YAML + bundle override MUST fail closed with InputError (not raw KeyError)
    with pytest.raises(InputError, match="modality='video' requires|modality mismatch"):
        run_runtime_verification(
            yaml_path=yaml8,
            dataset_dir_override=bundle16,
            output_dir=tmp_path / "verify_cross_mod",
            processor_runner=_video_runner,
        )

    # 4. Missing required YAML key MUST fail closed with InputError (not raw KeyError)
    bad_yaml = tmp_path / "missing_keys.yaml"
    bad_cfg = yaml.safe_load(yaml16.read_text(encoding="utf-8"))
    del bad_cfg["video_fps"]
    bad_yaml.write_text(yaml.safe_dump(bad_cfg), encoding="utf-8")
    with pytest.raises(InputError, match="video_fps"):
        run_runtime_verification(
            yaml_path=bad_yaml,
            output_dir=tmp_path / "verify_bad_yaml",
            processor_runner=_video_runner,
        )

    # 5. L4 output colliding with input L3 PNGs MUST fail closed even with overwrite=True
    colliding_out = fdir16.parent / "colliding_verify_out"
    l3_alias_root = colliding_out / "l4_reconstructed"
    # Build a bundle whose L3 frames literally reside under <colliding_out>/l4_reconstructed
    l3_alias_root.mkdir(parents=True)
    col_fdir, col_rec = _write_fake_frames_and_manifest(
        colliding_out / "_src_tmp", ctx.manifest_sha256, sample_meta, 16
    )
    # Move L3 frames into colliding_out/l4_reconstructed and rewrite manifest directly there
    import shutil
    for cid in sum16["exported_candidate_ids"]:
        shutil.copytree(col_fdir / cid, l3_alias_root / cid)
    col_bundle = tmp_path / "bundle_collide_l3"
    col_sum = build_fold_sft_dataset(
        fold=0,
        modality="video",
        num_frames=16,
        output_dir=col_bundle,
        frames_manifest=col_rec,
        frames_dir=l3_alias_root,
        repo_root=root,
    )
    col_yaml = tmp_path / "fold0_collide.yaml"
    render_config_bundle(
        fold=0,
        modality="video",
        num_frames=16,
        dataset_dir=str(col_bundle),
        dataset_name=col_sum["dataset_name"],
        train_output_dir=str(tmp_path / "adapter_collide"),
        output_yaml=col_yaml,
    )
    first_l3_png = l3_alias_root / sum16["exported_candidate_ids"][0] / "frame_00.png"
    orig_l3_bytes = first_l3_png.read_bytes()
    with pytest.raises(InputError, match="refusing to overwrite input file"):
        run_runtime_verification(
            yaml_path=col_yaml,
            output_dir=colliding_out,
            overwrite=True,
            processor_runner=_video_runner,
        )
    assert first_l3_png.read_bytes() == orig_l3_bytes


def test_run_runtime_verification_failure_guards(tmp_path: Path) -> None:
    ds_name = "tensile_five_label_fold0_video_16f"
    bundle_dir = _create_verified_bundle(
        tmp_path / "bundle_vid16",
        fold=0,
        modality="video",
        num_frames=16,
        dataset_name=ds_name,
    )
    yaml_path = tmp_path / "fold0_vid16.yaml"
    render_config_bundle(
        fold=0,
        modality="video",
        num_frames=16,
        dataset_dir=str(bundle_dir),
        dataset_name=ds_name,
        train_output_dir=str(tmp_path / "adapter_out"),
        output_yaml=yaml_path,
    )

    preflight = json.loads((bundle_dir / "preflight_report.json").read_text(encoding="utf-8"))
    pf_sample = preflight["samples"][0]
    expected_w, expected_h = pf_sample["resized_size"]
    expected_grid = pf_sample["grid_thw"]
    expected_pad = pf_sample["visual_pad_tokens"]
    expected_ts = [f"<{idx + 0.25:.1f} seconds>" for idx in range(8)]

    def _ok_runner(dataset_row: dict[str, Any]) -> dict[str, Any]:
        frames = [np.full((expected_h, expected_w, 3), i * 10, dtype=np.uint8) for i in range(16)]
        return {
            "actual_grid_thw": [list(expected_grid)],
            "actual_input_ids_len": 4096,
            "actual_pad_token_count": expected_pad,
            "actual_timestamps": expected_ts,
            "l4_frames": frames,
            "patch_size": 16,
        }

    # Failure 1: truncation (actual_input_ids_len > cutoff_len)
    def _trunc_runner(dataset_row: dict[str, Any]) -> dict[str, Any]:
        res = _ok_runner(dataset_row)
        res["actual_input_ids_len"] = 9000
        return res

    with pytest.raises(InputError, match="exceeds cutoff_len"):
        run_runtime_verification(
            yaml_path=yaml_path,
            output_dir=tmp_path / "verify_trunc",
            processor_runner=_trunc_runner,
        )

    # Failure 2: timestamp mismatch
    def _bad_ts_runner(dataset_row: dict[str, Any]) -> dict[str, Any]:
        res = _ok_runner(dataset_row)
        res["actual_timestamps"] = ["<0.0 seconds>"] * 8
        return res

    with pytest.raises(InputError, match="decoded video timestamps mismatch"):
        run_runtime_verification(
            yaml_path=yaml_path,
            output_dir=tmp_path / "verify_ts",
            processor_runner=_bad_ts_runner,
        )
