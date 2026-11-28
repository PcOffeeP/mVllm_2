"""Full-K-row L0->L1->L2->L3->L4 visual correspondence contact sheet & NCC auditor.

Renders ALL K frames (full 8 rows for 8f, full 16 rows for 16f — NEVER truncated) across
5 columns (``L0 原视频 | L1 ROI | L2 子视频 | L3 预抽 PNG | L4 模型张量还原图``; degrades to
4 columns when ``--l4-dir`` is not supplied), computes lightweight 64x64 grayscale zero-mean
NCC across consecutive layers (handling ``data/roi/manifest.json`` crop + pad geometry),
highlights any pair below threshold (default 0.80) in red, and writes ``correspondence_audit.json``.

DEC-005 Boundary:
    仅供人工视觉核验与错位预警，不构成 ``full`` 逐帧机器重放证明。
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from script.five_label_eval.errors import InputError
from script.five_label_eval.frames import size_bucket
from script.five_label_eval.score import decode_file

from .constants import (
    CORRESPONDENCE_AUDIT_SCHEMA,
    DEFAULT_NCC_THRESHOLD,
    DEFAULT_ROI_MANIFEST_REL,
    REPO_ROOT,
    RUNTIME_VERIFY_SCHEMA,
)
from .data_guards import (
    assert_no_input_output_collision,
    assert_no_symlink_components,
    safe_write_bytes,
    sha256_bytes,
    sha256_file,
    validate_safe_output_path,
    validate_safe_path_component,
)
from .verify_runtime_input import load_frame_lineage_jsonl

DEC005_BOUNDARY_NOTICE_ZH = "仅供人工视觉核验与错位预警，不构成 full 逐帧机器重放证明（DEC-005 边界）"
DEC005_BOUNDARY_NOTICE_ASCII = (
    "DEC-005 BOUNDARY: Visual human audit & misalignment warning ONLY - "
    "NOT a machine-level 'full' replay proof."
)
_PAD_FILTER_RE = re.compile(r"pad=(\d+):(\d+):(\d+):(\d+)")

_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
_LATIN_FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _load_font(size: int) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, bool]:
    """Load a legible TrueType font; returns ``(font, supports_cjk)`` so Linux never renders tofu boxes."""
    for path in _CJK_FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size), True
            except OSError:
                continue
    for path in _LATIN_FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size), False
            except OSError:
                continue
    return ImageFont.load_default(), False


def load_roi_geometry_map(roi_manifest_path: Path | str) -> dict[str, dict[str, Any]]:
    """Load ``video_id -> output.geometry`` from ``data/roi/manifest.json``."""
    p = Path(roi_manifest_path)
    if p.is_symlink() or not p.is_file():
        raise InputError(f"missing non-symlink ROI manifest: {p}")
    data = decode_file(p.read_text(encoding="utf-8"), str(p))
    videos = data.get("videos") if isinstance(data, dict) else None
    if not isinstance(videos, list):
        raise InputError(f"{p}: ROI manifest missing videos list")
    out: dict[str, dict[str, Any]] = {}
    for entry in videos:
        if not isinstance(entry, dict):
            continue
        vid = entry.get("video_id")
        output = entry.get("output")
        geom = output.get("geometry") if isinstance(output, dict) else None
        if isinstance(vid, str) and isinstance(geom, dict):
            out[vid] = geom
    return out


def compute_ncc_64x64(img_a: Image.Image, img_b: Image.Image) -> float:
    """Compute lightweight 64x64 grayscale zero-mean normalized cross-correlation in [-1.0, 1.0]."""
    arr_a = np.asarray(img_a.convert("L").resize((64, 64), Image.Resampling.BILINEAR), dtype=np.float64)
    arr_b = np.asarray(img_b.convert("L").resize((64, 64), Image.Resampling.BILINEAR), dtype=np.float64)
    a0 = arr_a - arr_a.mean()
    b0 = arr_b - arr_b.mean()
    denom = float(np.linalg.norm(a0) * np.linalg.norm(b0))
    if denom == 0.0:
        return 1.0 if np.allclose(arr_a, arr_b) else 0.0
    score = float(np.dot(a0.ravel(), b0.ravel()) / denom)
    return float(np.clip(score, -1.0, 1.0))


def align_l0_and_l1_for_ncc(
    l0_img: Image.Image,
    l1_img: Image.Image,
    roi_geometry: dict[str, Any] | None,
) -> tuple[Image.Image, Image.Image]:
    """Crop L0 by ``effective_pixel_box`` and strip ``pad_pixels`` from L1 so NCC compares true content pixels."""
    if not roi_geometry:
        return l0_img, l1_img

    l0_w, l0_h = l0_img.size
    box = roi_geometry.get("effective_pixel_box")
    if isinstance(box, dict) and all(isinstance(box.get(k), int) for k in ("x", "y", "width", "height")):
        x0 = max(0, min(l0_w - 1, int(box["x"])))
        y0 = max(0, min(l0_h - 1, int(box["y"])))
        x1 = max(x0 + 1, min(l0_w, x0 + int(box["width"])))
        y1 = max(y0 + 1, min(l0_h, y0 + int(box["height"])))
        l0_crop = l0_img.crop((x0, y0, x1, y1))
    else:
        l0_crop = l0_img

    l1_w, l1_h = l1_img.size
    pad_left = pad_top = pad_right = pad_bottom = 0
    pad_pixels = roi_geometry.get("pad_pixels")
    if isinstance(pad_pixels, dict) and all(isinstance(pad_pixels.get(k), int) for k in ("left", "top", "right", "bottom")):
        pad_left = max(0, int(pad_pixels["left"]))
        pad_top = max(0, int(pad_pixels["top"]))
        pad_right = max(0, int(pad_pixels["right"]))
        pad_bottom = max(0, int(pad_pixels["bottom"]))
    elif isinstance(roi_geometry.get("filter"), str):
        m = _PAD_FILTER_RE.search(roi_geometry["filter"])
        if m:
            pad_w, pad_h, pad_x, pad_y = (int(m.group(i)) for i in range(1, 5))
            pad_left = max(0, pad_x)
            pad_top = max(0, pad_y)
            pad_right = max(0, pad_w - pad_x - l0_crop.size[0])
            pad_bottom = max(0, pad_h - pad_y - l0_crop.size[1])

    if pad_left or pad_top or pad_right or pad_bottom:
        cx0 = min(l1_w - 1, pad_left)
        cy0 = min(l1_h - 1, pad_top)
        cx1 = max(cx0 + 1, l1_w - pad_right)
        cy1 = max(cy0 + 1, l1_h - pad_bottom)
        l1_content = l1_img.crop((cx0, cy0, cx1, cy1))
    else:
        l1_content = l1_img

    return l0_crop, l1_content


def extract_video_frames_ffmpeg(
    video_path: Path,
    frame_indices: list[int],
    *,
    ffmpeg_bin: str = "ffmpeg",
) -> dict[int, Image.Image]:
    """Extract exact 0-based frames from ``video_path`` in one single ``ffmpeg`` pass."""
    if not video_path.is_file():
        raise InputError(f"missing video file for frame extraction: {video_path}")
    unique_sorted = sorted(set(int(i) for i in frame_indices))
    if not unique_sorted:
        return {}
    if any(i < 0 for i in unique_sorted):
        raise InputError(f"negative frame index requested for {video_path}: {unique_sorted}")

    select_expr = "+".join(f"eq(n\\,{idx})" for idx in unique_sorted)
    with tempfile.TemporaryDirectory(prefix="sft_sheet_extract_") as tmp_dir:
        out_pattern = str(Path(tmp_dir) / "out_%04d.png")
        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"select='{select_expr}'",
            "-vsync",
            "0",
            "-frame_pts",
            "0",
            out_pattern,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise InputError(
                f"ffmpeg failed extracting frames {unique_sorted} from {video_path} "
                f"(rc={proc.returncode}): {proc.stderr.strip()}"
            )
        extracted_files = sorted(Path(tmp_dir).glob("out_*.png"))
        if len(extracted_files) != len(unique_sorted):
            raise InputError(
                f"ffmpeg extracted {len(extracted_files)} frames != requested {len(unique_sorted)} "
                f"from {video_path} (indices={unique_sorted})"
            )
        out: dict[int, Image.Image] = {}
        for idx, png_path in zip(unique_sorted, extracted_files):
            with Image.open(png_path) as im:
                out[idx] = im.convert("RGB").copy()
        return out


def select_representative_lineage_rows(
    lineage_rows: list[dict[str, Any]],
    *,
    sample_count: int = 6,
    roi_geometry_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Stratified auto-picker covering extreme durations, resolutions, width buckets, fps, and padded ROIs."""
    if sample_count <= 0:
        raise InputError(f"sample_count must be positive, got {sample_count}")
    if len(lineage_rows) <= sample_count:
        return list(lineage_rows)

    picked: list[dict[str, Any]] = []
    picked_ids: set[str] = set()

    def _add(row: dict[str, Any]) -> None:
        cid = row["candidate_id"]
        if cid not in picked_ids and len(picked) < sample_count:
            picked.append(row)
            picked_ids.add(cid)

    # 1. Shortest & longest clip duration (total_frames).
    _add(min(lineage_rows, key=lambda r: (int(r["total_frames"]), r["candidate_id"])))
    _add(max(lineage_rows, key=lambda r: (int(r["total_frames"]), r["candidate_id"])))
    # 2. Smallest & largest resolution area (width * height).
    _add(min(lineage_rows, key=lambda r: (int(r["width"]) * int(r["height"]), r["candidate_id"])))
    _add(max(lineage_rows, key=lambda r: (int(r["width"]) * int(r["height"]), r["candidate_id"])))

    # 3. At least one padded ROI source (e.g., video_0021) if present.
    if roi_geometry_map:
        for row in lineage_rows:
            geom = roi_geometry_map.get(row["source_id"]) or {}
            pad = geom.get("pad_pixels") or {}
            if any(isinstance(v, int) and v > 0 for v in pad.values()):
                _add(row)
                break

    # 4. Distinct fps values (e.g., 25 / 30 / 60 fps).
    seen_fps = {round(float(r["fps"]), 2) for r in picked}
    for row in lineage_rows:
        rfps = round(float(row["fps"]), 2)
        if rfps not in seen_fps:
            _add(row)
            seen_fps.add(rfps)

    # 5. Distinct width buckets (w_le_200, w_200_400, w_gt_400).
    seen_buckets = {size_bucket(int(r["width"])) for r in picked}
    for row in lineage_rows:
        wb = size_bucket(int(row["width"]))
        if wb not in seen_buckets:
            _add(row)
            seen_buckets.add(wb)

    # 6. Fill remaining slots evenly across sorted candidates (preferring distinct sources).
    seen_sources = {r["source_id"] for r in picked}
    for row in lineage_rows:
        if len(picked) >= sample_count:
            break
        if row["source_id"] not in seen_sources:
            _add(row)
            seen_sources.add(row["source_id"])
    for row in lineage_rows:
        if len(picked) >= sample_count:
            break
        _add(row)

    return picked


def _fit_image_into_box(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    canvas = Image.new("RGB", (target_w, target_h), color=(18, 18, 22))
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return canvas
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
    off_x = (target_w - new_w) // 2
    off_y = (target_h - new_h) // 2
    canvas.paste(resized, (off_x, off_y))
    return canvas


def render_contact_sheet_png(
    *,
    lineage_row: dict[str, Any],
    row_frames: list[dict[str, Image.Image]],
    frame_audits: list[dict[str, Any]],
    has_l4: bool,
    ncc_threshold: float = DEFAULT_NCC_THRESHOLD,
    cell_width: int = 240,
    cell_height: int = 280,
) -> bytes:
    """Render full-K-row (8 or 16 rows, NEVER truncated) x 5-col (or 4-col) contact sheet PNG bytes."""
    frames_meta = lineage_row["frames"]
    num_rows = len(frames_meta)
    if num_rows != len(row_frames) or num_rows != len(frame_audits):
        raise InputError(
            f"{lineage_row['candidate_id']}: row count mismatch "
            f"(lineage={num_rows}, images={len(row_frames)}, audits={len(frame_audits)})"
        )
    if num_rows <= 0 or num_rows != int(lineage_row["num_frames"]):
        raise InputError(
            f"{lineage_row['candidate_id']}: refusing truncated/empty sheet "
            f"(rendered rows={num_rows}, lineage num_frames={lineage_row['num_frames']})"
        )

    font_title, has_cjk = _load_font(16)
    font_sub, _ = _load_font(13)
    font_cell, _ = _load_font(11)

    if has_cjk:
        col_specs = [
            ("L0", "L0 原视频"),
            ("L1", "L1 ROI"),
            ("L2", "L2 子视频"),
            ("L3", "L3 预抽 PNG"),
        ]
        if has_l4:
            col_specs.append(("L4", "L4 模型张量还原图"))
        boundary_line = f"{DEC005_BOUNDARY_NOTICE_ZH} | {DEC005_BOUNDARY_NOTICE_ASCII}"
    else:
        col_specs = [
            ("L0", "L0 Original"),
            ("L1", "L1 ROI"),
            ("L2", "L2 Sub-video"),
            ("L3", "L3 Pre-extracted PNG"),
        ]
        if has_l4:
            col_specs.append(("L4", "L4 Model Tensor Reconstructed"))
        boundary_line = DEC005_BOUNDARY_NOTICE_ASCII

    num_cols = len(col_specs)
    pad = 8
    header_h = 84
    col_header_h = 30
    cell_label_h = 44
    row_block_h = cell_label_h + cell_height

    canvas_w = pad + num_cols * (cell_width + pad)
    canvas_h = header_h + col_header_h + pad + num_rows * (row_block_h + pad)
    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(24, 26, 32))
    draw = ImageDraw.Draw(canvas)

    # Top banner
    all_ncc_scores = [
        score
        for fa in frame_audits
        for score in fa["ncc"].values()
        if isinstance(score, (int, float))
    ]
    alert_count = sum(len(fa["alerts"]) for fa in frame_audits)
    min_ncc = min(all_ncc_scores) if all_ncc_scores else None
    banner_bg = (90, 24, 28) if alert_count > 0 else (28, 42, 62)
    draw.rectangle([(0, 0), (canvas_w, header_h)], fill=banner_bg)

    ver_method = (lineage_row.get("lineage_verification") or {}).get("method", "unverified")
    title_text = (
        f"Candidate: {lineage_row['candidate_id']}  |  Source: {lineage_row['source_id']}  |  "
        f"Channel: {lineage_row['modality']} {num_rows}f (ALL {num_rows} rows)  |  "
        f"{lineage_row['width']}x{lineage_row['height']} @ {lineage_row['fps']}fps"
    )
    min_ncc_str = f"{min_ncc:.4f}" if min_ncc is not None else "n/a"
    stats_text = (
        f"Lineage verification: {ver_method}  |  NCC min={min_ncc_str} "
        f"(threshold={ncc_threshold:.2f}, alerts={alert_count})"
    )
    draw.text((12, 8), title_text, fill=(245, 248, 255), font=font_title)
    draw.text((12, 34), stats_text, fill=(255, 196, 120) if alert_count > 0 else (180, 235, 195), font=font_sub)
    draw.text((12, 56), boundary_line, fill=(255, 224, 140), font=font_cell)

    # Column headers
    col_y0 = header_h
    draw.rectangle([(0, col_y0), (canvas_w, col_y0 + col_header_h)], fill=(36, 40, 50))
    for col_idx, (_, col_title) in enumerate(col_specs):
        cx = pad + col_idx * (cell_width + pad)
        draw.text((cx + 6, col_y0 + 7), col_title, fill=(235, 240, 248), font=font_sub)

    # Full K rows (0 .. K-1)
    pair_key_for_col = {
        "L0": None,
        "L1": "l1_vs_l0_crop",
        "L2": "l2_vs_l1",
        "L3": "l3_vs_l2",
        "L4": "l4_vs_l3",
    }
    for row_idx, (fmeta, imgs, faudit) in enumerate(zip(frames_meta, row_frames, frame_audits)):
        ry = header_h + col_header_h + pad + row_idx * (row_block_h + pad)
        ts_label = fmeta.get("injected_timestamp_label")
        pts = fmeta.get("pts_seconds")
        pts_str = f"pts={pts:.3f}s" if isinstance(pts, (int, float)) else ""
        ts_str = f" {ts_label}" if isinstance(ts_label, str) else ""

        for col_idx, (layer_key, _) in enumerate(col_specs):
            cx = pad + col_idx * (cell_width + pad)
            img = imgs[layer_key]
            pair_key = pair_key_for_col[layer_key]
            ncc_val = faudit["ncc"].get(pair_key) if pair_key else None
            is_alert = pair_key in faudit["alerts"] if pair_key else False

            # Label bar
            bar_fill = (128, 22, 26) if is_alert else (34, 38, 46)
            draw.rectangle([(cx, ry), (cx + cell_width, ry + cell_label_h)], fill=bar_fill)

            if layer_key == "L0":
                idx_val = fmeta.get("verified_original_frame_index")
                tag = "ver" if idx_val is not None else "drv"
                if idx_val is None:
                    idx_val = fmeta.get("derived_original_frame_index")
                line1 = f"#{row_idx:02d} L0 f={idx_val}({tag}) {img.size[0]}x{img.size[1]}"
                line2 = f"source={lineage_row['source_id']}"
            elif layer_key == "L1":
                idx_val = fmeta.get("verified_roi_frame_index")
                tag = "ver" if idx_val is not None else "drv"
                if idx_val is None:
                    idx_val = fmeta.get("derived_roi_frame_index")
                line1 = f"#{row_idx:02d} L1 f={idx_val}({tag}) {img.size[0]}x{img.size[1]}"
                line2 = f"NCC(L1/L0)={ncc_val:.3f}" if isinstance(ncc_val, float) else "NCC(L1/L0)=skip"
            elif layer_key == "L2":
                clip_idx = fmeta.get("clip_frame_index")
                line1 = f"#{row_idx:02d} L2 f={clip_idx} {img.size[0]}x{img.size[1]}"
                line2 = f"NCC(L2/L1)={ncc_val:.3f}" if isinstance(ncc_val, float) else "NCC(L2/L1)=skip"
            elif layer_key == "L3":
                clip_idx = fmeta.get("clip_frame_index")
                line1 = f"#{row_idx:02d} L3 f={clip_idx} {img.size[0]}x{img.size[1]}"
                ncc_part = f"NCC(L3/L2)={ncc_val:.3f}" if isinstance(ncc_val, float) else "NCC(L3/L2)=skip"
                line2 = f"{ncc_part} {pts_str}".strip()
            else:  # L4
                line1 = f"#{row_idx:02d} L4 {img.size[0]}x{img.size[1]}{ts_str}"
                line2 = f"NCC(L4/L3)={ncc_val:.3f}" if isinstance(ncc_val, float) else "NCC(L4/L3)=skip"

            text_color2 = (255, 160, 160) if is_alert else ((155, 238, 175) if isinstance(ncc_val, float) else (190, 200, 215))
            draw.text((cx + 4, ry + 4), line1, fill=(242, 245, 250), font=font_cell)
            draw.text((cx + 4, ry + 22), line2, fill=text_color2, font=font_cell)

            fitted = _fit_image_into_box(img, cell_width, cell_height)
            canvas.paste(fitted, (cx, ry + cell_label_h))
            border_color = (235, 55, 55) if is_alert else (64, 70, 82)
            border_width = 3 if is_alert else 1
            draw.rectangle(
                [(cx, ry), (cx + cell_width - 1, ry + row_block_h - 1)],
                outline=border_color,
                width=border_width,
            )

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _resolve_target_frame_index(frame_meta: dict[str, Any], *, verified_key: str, derived_key: str, cid: str) -> int:
    val = frame_meta.get(verified_key)
    if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
        return val
    val = frame_meta.get(derived_key)
    if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
        return val
    raise InputError(f"{cid}: frames[{frame_meta.get('display_order')}] missing both {verified_key} and {derived_key}")


def _load_and_verify_runtime_report_for_l4(
    *,
    runtime_report_path: Path,
    lineage_path: Path,
    lineage_rows: list[dict[str, Any]],
) -> dict[str, dict[int, str]]:
    """Verify ``runtime_verify_report.json`` matches ``frame_lineage.jsonl`` (preventing 8f/16f L4 mixups)."""
    if runtime_report_path.is_symlink() or not runtime_report_path.is_file():
        raise InputError(f"missing non-symlink runtime_verify_report.json: {runtime_report_path}")
    report = decode_file(runtime_report_path.read_text(encoding="utf-8"), str(runtime_report_path))
    if not isinstance(report, dict) or report.get("schema") != RUNTIME_VERIFY_SCHEMA:
        raise InputError(f"{runtime_report_path}: invalid runtime_verify_report schema")
    if report.get("failed_sample_count") != 0:
        raise InputError(
            f"{runtime_report_path}: refusing to pair L4 frames from failed runtime verify report "
            f"(failed_sample_count={report.get('failed_sample_count')!r})"
        )
    bundle_ver = report.get("bundle_verification")
    actual_lineage_sha = sha256_file(lineage_path)
    if not isinstance(bundle_ver, dict) or bundle_ver.get("frame_lineage_sha256") != actual_lineage_sha:
        raise InputError(
            f"{runtime_report_path}: frame_lineage_sha256 mismatch against {lineage_path} "
            f"(report={bundle_ver.get('frame_lineage_sha256') if isinstance(bundle_ver, dict) else None!r}, "
            f"actual={actual_lineage_sha!r}); refusing to mix L4 frames across bundles/channels"
        )
    expected_mod = lineage_rows[0]["modality"]
    expected_nf = int(lineage_rows[0]["num_frames"])
    if report.get("modality") != expected_mod or report.get("num_frames") != expected_nf:
        raise InputError(
            f"{runtime_report_path}: channel mismatch ({report.get('modality')}/{report.get('num_frames')}f "
            f"!= lineage {expected_mod}/{expected_nf}f)"
        )
    l4_sha_index: dict[str, dict[int, str]] = {}
    for sample_rec in report.get("samples") or []:
        if not isinstance(sample_rec, dict):
            continue
        cid = sample_rec.get("candidate_id")
        files = sample_rec.get("l4_reconstructed_files")
        if isinstance(cid, str) and isinstance(files, list):
            l4_sha_index[cid] = {
                int(item["display_order"]): str(item["sha256"])
                for item in files
                if isinstance(item, dict) and isinstance(item.get("display_order"), int) and isinstance(item.get("sha256"), str)
            }
    return l4_sha_index


def build_contact_sheets_and_audit(
    *,
    lineage_path: Path | str,
    output_dir: Path | str,
    l4_dir: Path | str | None = None,
    runtime_report_path: Path | str | None = None,
    roi_manifest_path: Path | str | None = None,
    repo_root: Path = REPO_ROOT,
    l0_dir: Path | str | None = None,
    l1_dir: Path | str | None = None,
    l2_dir: Path | str | None = None,
    candidate_ids: list[str] | None = None,
    sample_count: int = 6,
    ncc_mode: str = "all",
    ncc_threshold: float = DEFAULT_NCC_THRESHOLD,
    cell_width: int = 240,
    cell_height: int = 280,
    overwrite: bool = False,
    frame_extractor: Callable[[Path, list[int]], dict[int, Image.Image]] | None = None,
) -> dict[str, Any]:
    """Generate full-K-row L0..L4 contact sheets and ``correspondence_audit.json``."""
    if ncc_mode not in ("all", "endpoints"):
        raise InputError(f"ncc_mode must be 'all' or 'endpoints', got {ncc_mode!r}")
    if not (-1.0 <= ncc_threshold <= 1.0):
        raise InputError(f"ncc_threshold must be in [-1.0, 1.0], got {ncc_threshold!r}")

    root = Path(repo_root).resolve()
    lin_path = Path(lineage_path)
    out_dir = Path(output_dir)
    validate_safe_output_path(out_dir, label="output_dir")
    assert_no_symlink_components(out_dir, label="output_dir")

    roi_path = Path(roi_manifest_path) if roi_manifest_path is not None else root / DEFAULT_ROI_MANIFEST_REL
    roi_geom_map = load_roi_geometry_map(roi_path)
    l0_root = Path(l0_dir) if l0_dir is not None else root / "data" / "videos"
    l1_root = Path(l1_dir) if l1_dir is not None else root / "data" / "roi" / "videos"
    l2_root = Path(l2_dir) if l2_dir is not None else root / "data" / "sub_video" / "videos"
    l4_root = Path(l4_dir) if l4_dir is not None else None
    has_l4 = l4_root is not None

    lineage_rows = load_frame_lineage_jsonl(lin_path)

    # Cross-check runtime_verify_report.json when explicitly provided or co-located beside l4_dir.
    l4_sha_index: dict[str, dict[int, str]] | None = None
    effective_runtime_report: Path | None = None
    if runtime_report_path is not None:
        if not has_l4:
            raise InputError("--runtime-report requires --l4-dir")
        effective_runtime_report = Path(runtime_report_path)
    elif l4_root is not None:
        candidate_report = l4_root.resolve().parent / "runtime_verify_report.json"
        if candidate_report.exists():
            effective_runtime_report = candidate_report
    if effective_runtime_report is not None:
        l4_sha_index = _load_and_verify_runtime_report_for_l4(
            runtime_report_path=effective_runtime_report,
            lineage_path=lin_path,
            lineage_rows=lineage_rows,
        )
    if candidate_ids:
        wanted = list(dict.fromkeys(candidate_ids))
        by_cid = {r["candidate_id"]: r for r in lineage_rows}
        missing = [c for c in wanted if c not in by_cid]
        if missing:
            raise InputError(f"requested --candidate-ids absent from {lin_path}: {missing}")
        selected = [by_cid[c] for c in wanted]
    else:
        selected = select_representative_lineage_rows(
            lineage_rows,
            sample_count=sample_count,
            roi_geometry_map=roi_geom_map,
        )

    extractor = frame_extractor if frame_extractor is not None else extract_video_frames_ffmpeg
    audit_path = out_dir / "correspondence_audit.json"
    assert_no_input_output_collision([audit_path], [lin_path, roi_path], context="contact_sheet")

    candidate_audits: list[dict[str, Any]] = []
    all_alerts: list[dict[str, Any]] = []

    for lrow in selected:
        cid = validate_safe_path_component(lrow.get("candidate_id"), "candidate_id")
        sid = validate_safe_path_component(lrow.get("source_id"), "source_id")
        modality = validate_safe_path_component(lrow.get("modality"), "modality")
        num_frames = int(lrow["num_frames"])
        frames_meta = lrow["frames"]
        if len(frames_meta) != num_frames:
            raise InputError(f"{cid}: frame_lineage has {len(frames_meta)} frames != num_frames={num_frames}")

        l0_indices = [
            _resolve_target_frame_index(fm, verified_key="verified_original_frame_index", derived_key="derived_original_frame_index", cid=cid)
            for fm in frames_meta
        ]
        l1_indices = [
            _resolve_target_frame_index(fm, verified_key="verified_roi_frame_index", derived_key="derived_roi_frame_index", cid=cid)
            for fm in frames_meta
        ]
        l2_indices = [int(fm["clip_frame_index"]) for fm in frames_meta]

        l0_frames_map = extractor(l0_root / f"{sid}.mp4", l0_indices)
        l1_frames_map = extractor(l1_root / f"{sid}.mp4", l1_indices)
        l2_frames_map = extractor(l2_root / f"{cid}.mp4", l2_indices)

        roi_geom = roi_geom_map.get(sid)
        audit_orders = set(range(num_frames)) if ncc_mode == "all" else {0, num_frames - 1}

        row_images: list[dict[str, Image.Image]] = []
        frame_audits: list[dict[str, Any]] = []
        cand_alerts: list[dict[str, Any]] = []

        for order, fm in enumerate(frames_meta):
            l3_path = Path(fm["emitted_path"])
            if l3_path.is_symlink() or not l3_path.is_file():
                raise InputError(f"{cid}: missing non-symlink L3 PNG at {l3_path}")
            with Image.open(l3_path) as im_l3:
                l3_img = im_l3.convert("RGB").copy()

            imgs_for_row: dict[str, Image.Image] = {
                "L0": l0_frames_map[l0_indices[order]],
                "L1": l1_frames_map[l1_indices[order]],
                "L2": l2_frames_map[l2_indices[order]],
                "L3": l3_img,
            }
            if has_l4:
                assert l4_root is not None
                l4_path = l4_root / cid / f"frame_{order:02d}.png"
                if l4_path.is_symlink() or not l4_path.is_file():
                    raise InputError(f"{cid}: missing non-symlink L4 reconstructed PNG at {l4_path}")
                if l4_sha_index is not None:
                    expected_l4_sha = (l4_sha_index.get(cid) or {}).get(order)
                    if expected_l4_sha is None:
                        raise InputError(
                            f"{cid}: frame {order} absent from verified runtime_verify_report.json"
                        )
                    actual_l4_sha = sha256_file(l4_path)
                    if actual_l4_sha != expected_l4_sha:
                        raise InputError(
                            f"{cid}: L4 PNG sha256 mismatch at {l4_path} "
                            f"(expected {expected_l4_sha}, got {actual_l4_sha})"
                        )
                with Image.open(l4_path) as im_l4:
                    imgs_for_row["L4"] = im_l4.convert("RGB").copy()

            ncc_scores: dict[str, float | None] = {
                "l1_vs_l0_crop": None,
                "l2_vs_l1": None,
                "l3_vs_l2": None,
            }
            if has_l4:
                ncc_scores["l4_vs_l3"] = None

            row_alert_keys: list[str] = []
            if order in audit_orders:
                l0_crop, l1_unpadded = align_l0_and_l1_for_ncc(imgs_for_row["L0"], imgs_for_row["L1"], roi_geom)
                ncc_scores["l1_vs_l0_crop"] = round(compute_ncc_64x64(l1_unpadded, l0_crop), 6)
                ncc_scores["l2_vs_l1"] = round(compute_ncc_64x64(imgs_for_row["L2"], imgs_for_row["L1"]), 6)
                ncc_scores["l3_vs_l2"] = round(compute_ncc_64x64(imgs_for_row["L3"], imgs_for_row["L2"]), 6)
                if has_l4:
                    ncc_scores["l4_vs_l3"] = round(compute_ncc_64x64(imgs_for_row["L4"], imgs_for_row["L3"]), 6)

                for pair_key, score in ncc_scores.items():
                    if score is not None and score < ncc_threshold:
                        row_alert_keys.append(pair_key)
                        alert_obj = {
                            "candidate_id": cid,
                            "source_id": sid,
                            "display_order": order,
                            "pair": pair_key,
                            "ncc": score,
                            "threshold": ncc_threshold,
                        }
                        cand_alerts.append(alert_obj)
                        all_alerts.append(alert_obj)

            row_images.append(imgs_for_row)
            frame_audits.append(
                {
                    "display_order": order,
                    "l0_frame_index": l0_indices[order],
                    "l1_frame_index": l1_indices[order],
                    "l2_frame_index": l2_indices[order],
                    "audited": order in audit_orders,
                    "ncc": ncc_scores,
                    "alerts": row_alert_keys,
                }
            )

        sheet_bytes = render_contact_sheet_png(
            lineage_row=lrow,
            row_frames=row_images,
            frame_audits=frame_audits,
            has_l4=has_l4,
            ncc_threshold=ncc_threshold,
            cell_width=cell_width,
            cell_height=cell_height,
        )
        sheet_path = out_dir / f"{cid}_contact_sheet_{modality}_{num_frames}f.png"
        assert_no_input_output_collision([sheet_path], [lin_path, roi_path], context="contact_sheet")
        safe_write_bytes(sheet_path, sheet_bytes, overwrite=overwrite, label="contact_sheet_png")

        numeric_scores = [
            s
            for fa in frame_audits
            for s in fa["ncc"].values()
            if isinstance(s, (int, float))
        ]
        candidate_audits.append(
            {
                "candidate_id": cid,
                "source_id": sid,
                "modality": modality,
                "num_frames": num_frames,
                "rendered_rows": len(row_images),
                "columns": 5 if has_l4 else 4,
                "sheet_path": str(sheet_path.resolve()),
                "sheet_sha256": sha256_bytes(sheet_bytes),
                "min_ncc": min(numeric_scores) if numeric_scores else None,
                "alert_count": len(cand_alerts),
                "alerts": cand_alerts,
                "frames": frame_audits,
            }
        )

    audit_report: dict[str, Any] = {
        "schema": CORRESPONDENCE_AUDIT_SCHEMA,
        "dec005_boundary_notice": DEC005_BOUNDARY_NOTICE_ZH,
        "dec005_boundary_notice_ascii": DEC005_BOUNDARY_NOTICE_ASCII,
        "lineage_path": str(lin_path.resolve()),
        "roi_manifest_path": str(roi_path.resolve()),
        "l4_dir": str(l4_root.resolve()) if l4_root is not None else None,
        "columns": 5 if has_l4 else 4,
        "ncc_mode": ncc_mode,
        "ncc_threshold": ncc_threshold,
        "candidate_count": len(candidate_audits),
        "selected_candidate_ids": [c["candidate_id"] for c in candidate_audits],
        "alert_count": len(all_alerts),
        "alerts": all_alerts,
        "candidates": candidate_audits,
    }
    safe_write_bytes(
        audit_path,
        (json.dumps(audit_report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
        overwrite=overwrite,
        label="correspondence_audit",
    )
    return audit_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage", required=True, help="Path to frame_lineage.jsonl from build_dataset.py")
    parser.add_argument("--output-dir", required=True, help="Output directory for full-K-row PNG sheets and correspondence_audit.json")
    parser.add_argument("--l4-dir", help="Optional l4_reconstructed/ directory from verify_runtime_input.py (enables 5th L4 column)")
    parser.add_argument("--runtime-report", help="Optional runtime_verify_report.json to verify L4 lineage/channel/SHA-256 (auto-detected beside --l4-dir if present)")
    parser.add_argument("--roi-manifest", help="Optional override for data/roi/manifest.json")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repository root path")
    parser.add_argument("--l0-dir", help="Optional override for L0 original videos directory")
    parser.add_argument("--l1-dir", help="Optional override for L1 ROI videos directory")
    parser.add_argument("--l2-dir", help="Optional override for L2 sub-videos directory")
    parser.add_argument("--candidate-ids", help="Optional comma-separated candidate_ids (otherwise stratified auto-pick)")
    parser.add_argument("--sample-count", type=int, default=6, help="Number of stratified samples when --candidate-ids is omitted (default 6)")
    parser.add_argument("--ncc-mode", choices=("all", "endpoints"), default="all", help="Audit all K frames or only endpoints (default all)")
    parser.add_argument("--ncc-threshold", type=float, default=DEFAULT_NCC_THRESHOLD, help=f"NCC alert threshold (default {DEFAULT_NCC_THRESHOLD})")
    parser.add_argument("--cell-width", type=int, default=240, help="Width of each cell in pixels (default 240)")
    parser.add_argument("--cell-height", type=int, default=280, help="Height of each cell in pixels (default 280)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args(argv)

    try:
        cids = [c.strip() for c in args.candidate_ids.split(",") if c.strip()] if args.candidate_ids else None
        report = build_contact_sheets_and_audit(
            lineage_path=args.lineage,
            output_dir=args.output_dir,
            l4_dir=args.l4_dir,
            runtime_report_path=args.runtime_report,
            roi_manifest_path=args.roi_manifest,
            repo_root=Path(args.repo_root),
            l0_dir=args.l0_dir,
            l1_dir=args.l1_dir,
            l2_dir=args.l2_dir,
            candidate_ids=cids,
            sample_count=args.sample_count,
            ncc_mode=args.ncc_mode,
            ncc_threshold=args.ncc_threshold,
            cell_width=args.cell_width,
            cell_height=args.cell_height,
            overwrite=args.overwrite,
        )
        print(
            f"Wrote {report['candidate_count']} full-K-row {report['columns']}-col contact sheet(s) "
            f"and correspondence_audit.json (alerts={report['alert_count']}, threshold={report['ncc_threshold']}) "
            f"-> {args.output_dir}"
        )
        return 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
