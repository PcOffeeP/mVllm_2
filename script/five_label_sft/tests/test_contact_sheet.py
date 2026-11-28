"""Unit tests for full-K-row L0..L4 contact sheets and 64x64 NCC correspondence auditing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import pytest

from script.five_label_eval.errors import InputError
from script.five_label_sft.constants import CORRESPONDENCE_AUDIT_SCHEMA, FRAME_LINEAGE_SCHEMA, RUNTIME_VERIFY_SCHEMA
from script.five_label_sft.data_guards import sha256_file
from script.five_label_sft.contact_sheet import (
    DEC005_BOUNDARY_NOTICE_ZH,
    align_l0_and_l1_for_ncc,
    build_contact_sheets_and_audit,
    compute_ncc_64x64,
    select_representative_lineage_rows,
)


def _textured_image(width: int, height: int, seed: int) -> Image.Image:
    """Create a deterministic structured RGB image with strong spatial gradients for NCC testing."""
    yy, xx = np.mgrid[0:height, 0:width]
    r = ((xx * 3 + seed * 37) % 256).astype(np.uint8)
    g = ((yy * 5 + seed * 53) % 256).astype(np.uint8)
    b = (((xx ^ yy) * 2 + seed * 19) % 256).astype(np.uint8)
    return Image.fromarray(np.stack([r, g, b], axis=-1), mode="RGB")


def _write_synthetic_lineage_fixture(
    tmp_path: Path,
    *,
    modality: str,
    num_frames: int,
    with_l4: bool,
    corrupt_l3_order: int | None = None,
) -> tuple[Path, Path, Path | None, dict[tuple[str, int], Image.Image]]:
    l3_dir = tmp_path / "l3_pngs" / "video_0021_fracture_01"
    l3_dir.mkdir(parents=True)
    l4_root = tmp_path / "l4_pngs" if with_l4 else None
    if l4_root is not None:
        (l4_root / "video_0021_fracture_01").mkdir(parents=True)

    # Padded ROI like video_0021: L0 is 120x160, ROI keeps full 120x160 and adds left=20, right=20 -> 160x160
    roi_manifest = {
        "schema": "tensile-roi/1",
        "videos": [
            {
                "video_id": "video_0021",
                "output": {
                    "geometry": {
                        "filter": "pad=160:160:20:0:color=black,setsar=1",
                        "output_resolution": [160, 160],
                        "effective_pixel_box": {"x": 0, "y": 0, "width": 120, "height": 160},
                        "pad_pixels": {"top": 0, "bottom": 0, "left": 20, "right": 20},
                    }
                },
            }
        ],
    }
    roi_path = tmp_path / "roi_manifest.json"
    roi_path.write_text(json.dumps(roi_manifest), encoding="utf-8")

    frame_store: dict[tuple[str, int], Image.Image] = {}
    frame_rows: list[dict[str, Any]] = []
    for order in range(num_frames):
        clip_idx = order * 4
        roi_idx = 50 + clip_idx
        l0_img = _textured_image(120, 160, seed=order + 1)
        # Construct padded L1: black canvas 160x160 with L0 pasted at x=20
        l1_img = Image.new("RGB", (160, 160), color=(0, 0, 0))
        l1_img.paste(l0_img, (20, 0))
        l2_img = l1_img.copy()

        l3_img = l2_img.copy()
        if corrupt_l3_order == order:
            # Inverted frame -> NCC ~ -1.0 (< 0.80), must raise alert!
            l3_img = Image.fromarray(255 - np.asarray(l2_img), mode="RGB")

        l3_path = (l3_dir / f"frame_{order:02d}.png").resolve()
        l3_img.save(l3_path, format="PNG")
        if l4_root is not None:
            l4_img = l3_img.resize((128, 128), Image.Resampling.BILINEAR)
            l4_img.save(l4_root / "video_0021_fracture_01" / f"frame_{order:02d}.png", format="PNG")

        frame_store[("L0", roi_idx)] = l0_img
        frame_store[("L1", roi_idx)] = l1_img
        frame_store[("L2", clip_idx)] = l2_img

        frame_rows.append(
            {
                "display_order": order,
                "emitted_path": str(l3_path),
                "png_sha256": "a" * 64,
                "clip_frame_index": clip_idx,
                "pts_seconds": round(clip_idx / 30.0, 3),
                "verified_roi_frame_index": None,
                "verified_original_frame_index": None,
                "derived_roi_frame_index": roi_idx,
                "derived_original_frame_index": roi_idx,
                "derived_index_status": "derived_planned",
                "temporal_pair_index": order // 2 if modality == "video" else None,
                "injected_timestamp_sec": ((order // 2) + 0.25) if modality == "video" else None,
                "injected_timestamp_label": f"<{(order // 2) + 0.25:.1f} seconds>" if modality == "video" else None,
                "frame_index_mapping": None,
            }
        )

    lineage_row = {
        "schema": FRAME_LINEAGE_SCHEMA,
        "sample_index": 0,
        "candidate_id": "video_0021_fracture_01",
        "source_id": "video_0021",
        "input_id": "input@sha256:" + "b" * 64,
        "modality": modality,
        "num_frames": num_frames,
        "video_fps": 2.0 if modality == "video" else None,
        "clip_sha256": "c" * 64,
        "manifest_sha256": "d" * 64,
        "review_id": "rev-1",
        "review_revision_sha256": "e" * 64,
        "width": 160,
        "height": 160,
        "total_frames": 100,
        "fps": 30.0,
        "source_start_frame": 50,
        "lineage_verification": {"method": "unverified", "verdict_id": "unverified", "failed_conditions": []},
        "frames": frame_rows,
    }
    lineage_path = tmp_path / "frame_lineage.jsonl"
    lineage_path.write_text(json.dumps(lineage_row, ensure_ascii=False) + "\n", encoding="utf-8")
    return lineage_path, roi_path, l4_root, frame_store


def test_align_l0_and_l1_handles_crop_pad_and_no_crop() -> None:
    l0 = _textured_image(200, 300, seed=3)
    crop = l0.crop((30, 40, 150, 200))  # 120x160
    l1 = Image.new("RGB", (160, 170), color=(0, 0, 0))
    l1.paste(crop, (20, 5))

    geom = {
        "effective_pixel_box": {"x": 30, "y": 40, "width": 120, "height": 160},
        "pad_pixels": {"left": 20, "right": 20, "top": 5, "bottom": 5},
    }
    l0_aligned, l1_aligned = align_l0_and_l1_for_ncc(l0, l1, geom)
    assert l0_aligned.size == (120, 160)
    assert l1_aligned.size == (120, 160)
    assert compute_ncc_64x64(l1_aligned, l0_aligned) > 0.999

    # video_0093-style no_crop (effective_pixel_box=None) with pad_pixels only
    l1_nocrop = Image.new("RGB", (240, 306), color=(0, 0, 0))
    l1_nocrop.paste(l0, (20, 3))
    geom_nocrop = {"pad_pixels": {"left": 20, "right": 20, "top": 3, "bottom": 3}}
    l0_nc, l1_nc = align_l0_and_l1_for_ncc(l0, l1_nocrop, geom_nocrop)
    assert l0_nc.size == l1_nc.size == (200, 300)
    assert compute_ncc_64x64(l1_nc, l0_nc) > 0.999


def test_contact_sheet_renders_all_16_rows_5_cols_and_all_8_rows_4_cols(tmp_path: Path) -> None:
    # 1. 16f video WITH L4 -> full 16 rows x 5 columns, 0 alerts
    lin16, roi16, l4_16, store16 = _write_synthetic_lineage_fixture(
        tmp_path / "f16", modality="video", num_frames=16, with_l4=True
    )
    l0_dir = tmp_path / "f16/l0"
    l1_dir = tmp_path / "f16/l1"
    l2_dir = tmp_path / "f16/l2"

    def _extractor16(vpath: Path, indices: list[int]) -> dict[int, Image.Image]:
        if vpath.parent == l0_dir:
            layer = "L0"
        elif vpath.parent == l1_dir:
            layer = "L1"
        else:
            layer = "L2"
        return {i: store16[(layer, i)] for i in indices}

    out16 = tmp_path / "sheets_16f"
    audit16 = build_contact_sheets_and_audit(
        lineage_path=lin16,
        output_dir=out16,
        l4_dir=l4_16,
        roi_manifest_path=roi16,
        l0_dir=l0_dir,
        l1_dir=l1_dir,
        l2_dir=l2_dir,
        cell_width=120,
        cell_height=140,
        frame_extractor=_extractor16,
    )
    assert audit16["schema"] == CORRESPONDENCE_AUDIT_SCHEMA
    assert DEC005_BOUNDARY_NOTICE_ZH in audit16["dec005_boundary_notice"]
    assert audit16["columns"] == 5
    assert audit16["alert_count"] == 0
    cand16 = audit16["candidates"][0]
    assert cand16["rendered_rows"] == 16
    assert cand16["min_ncc"] > 0.99
    with Image.open(cand16["sheet_path"]) as im16:
        # 5 cols * (120+8) + 8 = 648; header(84)+col(30)+8 + 16*(44+140+8) = 122 + 3072 = 3194
        assert im16.size == (648, 3194)

    # 2. 8f images WITHOUT L4 -> degrades to full 8 rows x 4 columns + red alert on corrupted frame 3
    lin8, roi8, _, store8 = _write_synthetic_lineage_fixture(
        tmp_path / "f8", modality="images", num_frames=8, with_l4=False, corrupt_l3_order=3
    )
    l0_8, l1_8, l2_8 = tmp_path / "f8/l0", tmp_path / "f8/l1", tmp_path / "f8/l2"

    def _extractor8(vpath: Path, indices: list[int]) -> dict[int, Image.Image]:
        layer = "L0" if vpath.parent == l0_8 else ("L1" if vpath.parent == l1_8 else "L2")
        return {i: store8[(layer, i)] for i in indices}

    out8 = tmp_path / "sheets_8f"
    audit8 = build_contact_sheets_and_audit(
        lineage_path=lin8,
        output_dir=out8,
        l4_dir=None,
        roi_manifest_path=roi8,
        l0_dir=l0_8,
        l1_dir=l1_8,
        l2_dir=l2_8,
        cell_width=120,
        cell_height=140,
        frame_extractor=_extractor8,
    )
    assert audit8["columns"] == 4
    assert audit8["alert_count"] == 1
    assert audit8["alerts"][0]["display_order"] == 3
    assert audit8["alerts"][0]["pair"] == "l3_vs_l2"
    assert audit8["alerts"][0]["ncc"] < 0.80
    cand8 = audit8["candidates"][0]
    assert cand8["rendered_rows"] == 8
    with Image.open(cand8["sheet_path"]) as im8:
        # 4 cols * (120+8) + 8 = 520; 122 + 8*(44+140+8) = 1658
        assert im8.size == (520, 1658)

    # 3. Endpoints mode only audits frame 0 and K-1 (so frame 3 corruption is not audited in endpoints mode)
    out8_ep = tmp_path / "sheets_8f_ep"
    audit8_ep = build_contact_sheets_and_audit(
        lineage_path=lin8,
        output_dir=out8_ep,
        l4_dir=None,
        roi_manifest_path=roi8,
        l0_dir=l0_8,
        l1_dir=l1_8,
        l2_dir=l2_8,
        ncc_mode="endpoints",
        frame_extractor=_extractor8,
    )
    audited_orders = [f["display_order"] for f in audit8_ep["candidates"][0]["frames"] if f["audited"]]
    assert audited_orders == [0, 7]
    assert audit8_ep["alert_count"] == 0


def test_stratified_selector_and_protected_output_guard(tmp_path: Path) -> None:
    rows = [
        {"candidate_id": "c_short", "source_id": "v1", "total_frames": 45, "width": 160, "height": 200, "fps": 30.0},
        {"candidate_id": "c_long", "source_id": "v2", "total_frames": 500, "width": 300, "height": 400, "fps": 30.0},
        {"candidate_id": "c_tiny", "source_id": "v3", "total_frames": 100, "width": 100, "height": 120, "fps": 30.0},
        {"candidate_id": "c_huge", "source_id": "v4", "total_frames": 100, "width": 804, "height": 1072, "fps": 30.0},
        {"candidate_id": "c_pad", "source_id": "v5", "total_frames": 120, "width": 500, "height": 600, "fps": 30.0},
        {"candidate_id": "c_fps60", "source_id": "v6", "total_frames": 120, "width": 250, "height": 300, "fps": 60.0},
        {"candidate_id": "c_extra", "source_id": "v7", "total_frames": 120, "width": 260, "height": 300, "fps": 30.0},
    ]
    roi_map = {"v5": {"pad_pixels": {"left": 10, "right": 10, "top": 0, "bottom": 0}}}
    picked = select_representative_lineage_rows(rows, sample_count=6, roi_geometry_map=roi_map)
    picked_ids = {r["candidate_id"] for r in picked}
    assert picked_ids == {"c_short", "c_long", "c_tiny", "c_huge", "c_pad", "c_fps60"}

    # Protected output path must fail closed
    lin, roi, l4_dir, store = _write_synthetic_lineage_fixture(tmp_path / "p", modality="images", num_frames=8, with_l4=True)
    with pytest.raises(InputError, match="protected path"):
        build_contact_sheets_and_audit(
            lineage_path=lin,
            output_dir=tmp_path / "data/sub_video/evil_sheets",
            roi_manifest_path=roi,
        )

    # Runtime report cross-check blocks channel/lineage mixups and tampered L4 PNGs
    assert l4_dir is not None
    cid = "video_0021_fracture_01"
    good_rt_report = {
        "schema": RUNTIME_VERIFY_SCHEMA,
        "modality": "images",
        "num_frames": 8,
        "failed_sample_count": 0,
        "bundle_verification": {"frame_lineage_sha256": sha256_file(lin)},
        "samples": [
            {
                "candidate_id": cid,
                "l4_reconstructed_files": [
                    {
                        "display_order": i,
                        "sha256": sha256_file(l4_dir / cid / f"frame_{i:02d}.png"),
                    }
                    for i in range(8)
                ],
            }
        ],
    }
    rt_path = l4_dir.parent / "runtime_verify_report.json"
    rt_path.write_text(json.dumps(good_rt_report), encoding="utf-8")

    l0_p, l1_p, l2_p = tmp_path / "p/l0", tmp_path / "p/l1", tmp_path / "p/l2"
    def _ext_p(vpath: Path, indices: list[int]) -> dict[int, Image.Image]:
        layer = "L0" if vpath.parent == l0_p else ("L1" if vpath.parent == l1_p else "L2")
        return {i: store[(layer, i)] for i in indices}

    # Matching co-located runtime_verify_report.json passes
    ok_audit = build_contact_sheets_and_audit(
        lineage_path=lin,
        output_dir=tmp_path / "p_ok",
        l4_dir=l4_dir,
        roi_manifest_path=roi,
        l0_dir=l0_p,
        l1_dir=l1_p,
        l2_dir=l2_p,
        frame_extractor=_ext_p,
    )
    assert ok_audit["columns"] == 5

    # Mismatched lineage SHA-256 (e.g. mixing 16f L4 into 8f lineage) fails closed
    bad_rt = json.loads(rt_path.read_text(encoding="utf-8"))
    bad_rt["bundle_verification"]["frame_lineage_sha256"] = "0" * 64
    rt_path.write_text(json.dumps(bad_rt), encoding="utf-8")
    with pytest.raises(InputError, match="frame_lineage_sha256 mismatch"):
        build_contact_sheets_and_audit(
            lineage_path=lin,
            output_dir=tmp_path / "p_bad_rt",
            l4_dir=l4_dir,
            roi_manifest_path=roi,
            l0_dir=l0_p,
            l1_dir=l1_p,
            l2_dir=l2_p,
            frame_extractor=_ext_p,
        )
