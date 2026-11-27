"""Offline Qwen3-VL visual token, cutoff_len, alignment, and short-clip preflight validator."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable

from script.five_label_eval.errors import InputError
from script.five_label_eval.frames import size_bucket
from script.five_label_eval.prompt_id import load_prompt

from .constants import (
    BASE_PROMPT_CHAR_LEN,
    BASE_PROMPT_TEMPLATE_TOKENS,
    DEFAULT_PROMPT_REL,
    IMAGE_WRAPPER_TOKENS_PER_FRAME,
    PREFLIGHT_REPORT_SCHEMA,
    QWEN3_VL_IMAGE_PROCESSOR_MAX_PIXELS,
    QWEN3_VL_IMAGE_PROCESSOR_MIN_PIXELS,
    QWEN3_VL_MERGE_SIZE,
    QWEN3_VL_PATCH_SIZE,
    QWEN3_VL_SPATIAL_FACTOR,
    QWEN3_VL_TEMPORAL_PATCH_SIZE,
    QWEN3_VL_VIDEO_PROCESSOR_MAX_PIXELS,
    QWEN3_VL_VIDEO_PROCESSOR_MIN_PIXELS,
    REPO_ROOT,
    SUPPORTED_MODALITIES,
    TARGET_JSON_TOKEN_BUDGET,
    VIDEO_WRAPPER_TOKENS_PER_PAIR,
    get_channel_preset,
)
from .data_guards import (
    SelectedTrainSample,
    load_fold_isolation_context,
    safe_write_bytes,
    select_confirmed_fold_train_samples,
    validate_safe_output_path,
)


def lf_preprocess_image_size(
    width: int,
    height: int,
    *,
    max_pixels: int,
    min_pixels: int,
) -> tuple[int, int, bool]:
    """Exact mirror of LlamaFactory ``Qwen2VLPlugin._preprocess_image`` (mm_plugin.py:218-235, 1934-1948).

    Returns ``(reg_width, reg_height, triggered_downscale)``.
    """
    if width <= 0 or height <= 0:
        raise InputError(f"image dimensions must be positive, got {width}x{height}")
    w, h = int(width), int(height)
    downscaled = False
    if w * h > max_pixels:
        downscaled = True
        resize_factor = math.sqrt(max_pixels / (w * h))
        w, h = int(w * resize_factor), int(h * resize_factor)
    if w * h < min_pixels:
        resize_factor = math.sqrt(min_pixels / (w * h))
        w, h = int(w * resize_factor), int(h * resize_factor)
    if min(w, h) < 28:
        w, h = max(w, 28), max(h, 28)
    if w / h > 200:
        w = h * 180
    if h / w > 200:
        h = w * 180
    return w, h, downscaled


def qwen3_vl_smart_resize_image(
    height: int,
    width: int,
    *,
    factor: int = QWEN3_VL_SPATIAL_FACTOR,
    min_pixels: int = QWEN3_VL_IMAGE_PROCESSOR_MIN_PIXELS,
    max_pixels: int = QWEN3_VL_IMAGE_PROCESSOR_MAX_PIXELS,
) -> tuple[int, int]:
    """Exact ``Qwen2VLImageProcessorFast.smart_resize`` geometry (patch_size=16, merge_size=2 -> factor=32)."""
    if height <= 0 or width <= 0:
        raise InputError(f"invalid image dimensions {width}x{height}")
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(factor, math.floor(height / beta / factor) * factor)
        w_bar = max(factor, math.floor(width / beta / factor) * factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def qwen3_vl_smart_resize_video(
    num_frames: int,
    height: int,
    width: int,
    *,
    temporal_factor: int = QWEN3_VL_TEMPORAL_PATCH_SIZE,
    factor: int = QWEN3_VL_SPATIAL_FACTOR,
    min_pixels: int = QWEN3_VL_VIDEO_PROCESSOR_MIN_PIXELS,
    max_pixels: int = QWEN3_VL_VIDEO_PROCESSOR_MAX_PIXELS,
) -> tuple[int, int, int]:
    """Exact ``Qwen3VLVideoProcessor.smart_resize`` geometry (t_bar, h_bar, w_bar)."""
    if num_frames <= 0 or height <= 0 or width <= 0:
        raise InputError(f"invalid video dimensions T={num_frames}, {width}x{height}")
    t_bar = max(temporal_factor, round(num_frames / temporal_factor) * temporal_factor)
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if t_bar * h_bar * w_bar > max_pixels:
        beta = math.sqrt((num_frames * height * width) / max_pixels)
        h_bar = max(factor, math.floor(height / beta / factor) * factor)
        w_bar = max(factor, math.floor(width / beta / factor) * factor)
    elif t_bar * h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (num_frames * height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return t_bar, h_bar, w_bar


def estimate_prompt_and_template_tokens(prompt_text: str | None = None) -> int:
    """Estimate Qwen3-VL prompt + chat template tokens anchored to DEC-008 empirical measurement."""
    if not prompt_text:
        return BASE_PROMPT_TEMPLATE_TOKENS
    extra_chars = max(0, len(prompt_text) - BASE_PROMPT_CHAR_LEN)
    # Conservative 1.25 tokens/char margin for any prompt expansion beyond five_label_v2.txt.
    return BASE_PROMPT_TEMPLATE_TOKENS + math.ceil(extra_chars * 1.25)


@dataclass(frozen=True)
class SamplePreflightResult:
    candidate_id: str
    source_id: str
    width: int
    height: int
    size_bucket: str
    total_frames: int
    modality: str
    num_frames: int
    lf_reg_width: int
    lf_reg_height: int
    resized_width: int
    resized_height: int
    grid_thw: tuple[int, int, int]
    vllm_grid_thw: tuple[int, int, int]
    vllm_grid_mismatch: bool
    visual_pad_tokens: int
    visual_wrapper_tokens: int
    prompt_template_tokens: int
    target_json_tokens: int
    estimated_total_tokens: int
    cutoff_len: int
    exceeds_cutoff: bool
    short_clip: bool
    lf_downscale_triggered: bool
    raw_frame_pixels: int
    effective_frame_pixels: int
    max_safe_train_frame_pixels: int | None
    exceeds_gpu_frame_pixel_guard: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_id": self.source_id,
            "width": self.width,
            "height": self.height,
            "raw_frame_pixels": self.raw_frame_pixels,
            "effective_frame_pixels": self.effective_frame_pixels,
            "size_bucket": self.size_bucket,
            "total_frames": self.total_frames,
            "modality": self.modality,
            "num_frames": self.num_frames,
            "lf_reg_size": [self.lf_reg_width, self.lf_reg_height],
            "resized_size": [self.resized_width, self.resized_height],
            "grid_thw": list(self.grid_thw),
            "vllm_grid_thw": list(self.vllm_grid_thw),
            "vllm_grid_mismatch": self.vllm_grid_mismatch,
            "visual_pad_tokens": self.visual_pad_tokens,
            "visual_wrapper_tokens": self.visual_wrapper_tokens,
            "prompt_template_tokens": self.prompt_template_tokens,
            "target_json_tokens": self.target_json_tokens,
            "estimated_total_tokens": self.estimated_total_tokens,
            "cutoff_len": self.cutoff_len,
            "exceeds_cutoff": self.exceeds_cutoff,
            "short_clip": self.short_clip,
            "lf_downscale_triggered": self.lf_downscale_triggered,
            "max_safe_train_frame_pixels": self.max_safe_train_frame_pixels,
            "exceeds_gpu_frame_pixel_guard": self.exceeds_gpu_frame_pixel_guard,
        }


def analyze_sample_preflight(
    *,
    candidate_id: str,
    source_id: str,
    width: int,
    height: int,
    total_frames: int,
    modality: str,
    num_frames: int,
    cutoff_len: int,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    max_safe_train_frame_pixels: int | None = None,
    prompt_template_tokens: int = BASE_PROMPT_TEMPLATE_TOKENS,
    target_json_tokens: int = TARGET_JSON_TOKEN_BUDGET,
) -> SamplePreflightResult:
    """Compute exact Qwen3-VL grid/visual tokens and cutoff_len compliance for one sample."""
    if modality not in SUPPORTED_MODALITIES:
        raise InputError(f"unsupported modality {modality!r}; expected one of {SUPPORTED_MODALITIES}")
    if isinstance(num_frames, bool) or not isinstance(num_frames, int) or num_frames <= 0:
        raise InputError(f"num_frames must be a positive integer, got {num_frames!r}")
    if modality == "video" and num_frames % QWEN3_VL_TEMPORAL_PATCH_SIZE != 0:
        raise InputError(
            f"video modality requires even num_frames (multiple of temporal_patch_size={QWEN3_VL_TEMPORAL_PATCH_SIZE}) "
            f"to avoid LlamaFactory mm_plugin.py silent last-frame duplication, got {num_frames}"
        )
    if isinstance(cutoff_len, bool) or not isinstance(cutoff_len, int) or cutoff_len <= 0:
        raise InputError(f"cutoff_len must be a positive integer, got {cutoff_len!r}")

    if modality == "images":
        max_px = image_max_pixels if image_max_pixels is not None else 1_200_000
        min_px = image_min_pixels if image_min_pixels is not None else 65_536
        reg_w, reg_h, downscaled = lf_preprocess_image_size(width, height, max_pixels=max_px, min_pixels=min_px)
        h_bar, w_bar = qwen3_vl_smart_resize_image(reg_h, reg_w)
        grid_t = num_frames
        grid_h = h_bar // QWEN3_VL_PATCH_SIZE
        grid_w = w_bar // QWEN3_VL_PATCH_SIZE
        vllm_h_bar, vllm_w_bar = qwen3_vl_smart_resize_image(height, width)
        vllm_grid_thw = (num_frames, vllm_h_bar // QWEN3_VL_PATCH_SIZE, vllm_w_bar // QWEN3_VL_PATCH_SIZE)
        per_frame_tokens = (grid_h // QWEN3_VL_MERGE_SIZE) * (grid_w // QWEN3_VL_MERGE_SIZE)
        visual_pad_tokens = num_frames * per_frame_tokens
        visual_wrapper_tokens = num_frames * IMAGE_WRAPPER_TOKENS_PER_FRAME
    else:
        max_px = video_max_pixels if video_max_pixels is not None else 1_200_000
        min_px = video_min_pixels if video_min_pixels is not None else 256
        reg_w, reg_h, downscaled = lf_preprocess_image_size(width, height, max_pixels=max_px, min_pixels=min_px)
        t_bar, h_bar, w_bar = qwen3_vl_smart_resize_video(num_frames, reg_h, reg_w)
        grid_t = t_bar // QWEN3_VL_TEMPORAL_PATCH_SIZE
        grid_h = h_bar // QWEN3_VL_PATCH_SIZE
        grid_w = w_bar // QWEN3_VL_PATCH_SIZE
        vllm_t_bar, vllm_h_bar, vllm_w_bar = qwen3_vl_smart_resize_video(num_frames, height, width)
        vllm_grid_thw = (
            vllm_t_bar // QWEN3_VL_TEMPORAL_PATCH_SIZE,
            vllm_h_bar // QWEN3_VL_PATCH_SIZE,
            vllm_w_bar // QWEN3_VL_PATCH_SIZE,
        )
        visual_pad_tokens = grid_t * (grid_h // QWEN3_VL_MERGE_SIZE) * (grid_w // QWEN3_VL_MERGE_SIZE)
        visual_wrapper_tokens = grid_t * VIDEO_WRAPPER_TOKENS_PER_PAIR

    grid_thw = (grid_t, grid_h, grid_w)
    vllm_grid_mismatch = grid_thw != vllm_grid_thw
    estimated_total = visual_pad_tokens + visual_wrapper_tokens + prompt_template_tokens + target_json_tokens
    raw_frame_pixels = width * height
    effective_frame_pixels = reg_w * reg_h
    exceeds_gpu_guard = (
        max_safe_train_frame_pixels is not None and effective_frame_pixels > max_safe_train_frame_pixels
    )
    return SamplePreflightResult(
        candidate_id=candidate_id,
        source_id=source_id,
        width=width,
        height=height,
        size_bucket=size_bucket(width),
        total_frames=total_frames,
        modality=modality,
        num_frames=num_frames,
        lf_reg_width=reg_w,
        lf_reg_height=reg_h,
        resized_width=w_bar,
        resized_height=h_bar,
        grid_thw=grid_thw,
        vllm_grid_thw=vllm_grid_thw,
        vllm_grid_mismatch=vllm_grid_mismatch,
        visual_pad_tokens=visual_pad_tokens,
        visual_wrapper_tokens=visual_wrapper_tokens,
        prompt_template_tokens=prompt_template_tokens,
        target_json_tokens=target_json_tokens,
        estimated_total_tokens=estimated_total,
        cutoff_len=cutoff_len,
        exceeds_cutoff=estimated_total > cutoff_len,
        short_clip=total_frames < num_frames,
        lf_downscale_triggered=downscaled,
        raw_frame_pixels=raw_frame_pixels,
        effective_frame_pixels=effective_frame_pixels,
        max_safe_train_frame_pixels=max_safe_train_frame_pixels,
        exceeds_gpu_frame_pixel_guard=exceeds_gpu_guard,
    )


def _percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, max(0, math.ceil(len(sorted_values) * pct) - 1))
    return sorted_values[idx]


def run_preflight_on_samples(
    samples: Iterable[SelectedTrainSample | dict[str, Any]],
    *,
    modality: str,
    num_frames: int,
    cutoff_len: int | None = None,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    max_safe_train_frame_pixels: int | None = None,
    prompt_text: str | None = None,
    fail_on_exceed: bool = True,
    fail_on_short_clip: bool = True,
    fail_on_gpu_pixel_guard: bool = True,
    fail_on_lf_downscale: bool = False,
) -> dict[str, Any]:
    """Run offline preflight checks across a sequence of samples and optionally fail closed."""
    preset = get_channel_preset(modality, num_frames)
    eff_cutoff = cutoff_len if cutoff_len is not None else preset.cutoff_len
    eff_img_max = image_max_pixels if image_max_pixels is not None else preset.image_max_pixels
    eff_img_min = image_min_pixels if image_min_pixels is not None else preset.image_min_pixels
    eff_vid_max = video_max_pixels if video_max_pixels is not None else preset.video_max_pixels
    eff_vid_min = video_min_pixels if video_min_pixels is not None else preset.video_min_pixels
    eff_gpu_px = (
        max_safe_train_frame_pixels
        if max_safe_train_frame_pixels is not None
        else preset.max_safe_train_frame_pixels
    )
    prompt_tokens = estimate_prompt_and_template_tokens(prompt_text)

    results: list[SamplePreflightResult] = []
    for item in samples:
        if isinstance(item, SelectedTrainSample):
            cid, sid, w, h, tf = item.candidate_id, item.source_id, item.width, item.height, item.total_frames
        elif isinstance(item, dict):
            cid = str(item["candidate_id"])
            sid = str(item.get("source_id") or item.get("source_video_id") or "")
            media = item.get("output", {}).get("media") if isinstance(item.get("output"), dict) else item
            w = int(media["width"])
            h = int(media["height"])
            tf = int(media["total_frames"])
        else:
            raise InputError(f"unsupported preflight item type: {type(item).__name__}")
        results.append(
            analyze_sample_preflight(
                candidate_id=cid,
                source_id=sid,
                width=w,
                height=h,
                total_frames=tf,
                modality=modality,
                num_frames=num_frames,
                cutoff_len=eff_cutoff,
                image_max_pixels=eff_img_max,
                image_min_pixels=eff_img_min,
                video_max_pixels=eff_vid_max,
                video_min_pixels=eff_vid_min,
                max_safe_train_frame_pixels=eff_gpu_px,
                prompt_template_tokens=prompt_tokens,
            )
        )

    exceeding = [r for r in results if r.exceeds_cutoff]
    short_clips = [r for r in results if r.short_clip]
    downscaled = [r for r in results if r.lf_downscale_triggered]
    vllm_mismatches = [r for r in results if r.vllm_grid_mismatch]
    gpu_guard_exceeding = [r for r in results if r.exceeds_gpu_frame_pixel_guard]

    vis_sorted = sorted(r.visual_pad_tokens for r in results)
    tot_sorted = sorted(r.estimated_total_tokens for r in results)
    tf_sorted = sorted(r.total_frames for r in results)
    top_samples = sorted(results, key=lambda r: (r.estimated_total_tokens, r.width * r.height, r.candidate_id), reverse=True)[:10]

    report: dict[str, Any] = {
        "schema": PREFLIGHT_REPORT_SCHEMA,
        "modality": modality,
        "num_frames": num_frames,
        "cutoff_len": eff_cutoff,
        "max_safe_train_frame_pixels": eff_gpu_px,
        "pixel_config": {
            "image_max_pixels": eff_img_max,
            "image_min_pixels": eff_img_min,
            "video_max_pixels": eff_vid_max,
            "video_min_pixels": eff_vid_min,
        },
        "sample_count": len(results),
        "min_total_frames": tf_sorted[0] if tf_sorted else None,
        "max_total_frames": tf_sorted[-1] if tf_sorted else None,
        "short_clip_count": len(short_clips),
        "short_clips": [r.to_dict() for r in short_clips],
        "exceeds_cutoff_count": len(exceeding),
        "exceeding_samples": [r.to_dict() for r in exceeding],
        "exceeds_gpu_frame_pixel_guard_count": len(gpu_guard_exceeding),
        "gpu_frame_pixel_guard_samples": [r.to_dict() for r in gpu_guard_exceeding],
        "lf_downscale_triggered_count": len(downscaled),
        "vllm_grid_mismatch_count": len(vllm_mismatches),
        "vllm_alignment_clean": len(vllm_mismatches) == 0 and len(downscaled) == 0,
        "visual_pad_tokens": {
            "min": vis_sorted[0] if vis_sorted else 0,
            "median": int(statistics.median(vis_sorted)) if vis_sorted else 0,
            "p95": _percentile(vis_sorted, 0.95),
            "mean": round(sum(vis_sorted) / len(vis_sorted), 2) if vis_sorted else 0.0,
            "max": vis_sorted[-1] if vis_sorted else 0,
        },
        "estimated_total_tokens": {
            "min": tot_sorted[0] if tot_sorted else 0,
            "median": int(statistics.median(tot_sorted)) if tot_sorted else 0,
            "p95": _percentile(tot_sorted, 0.95),
            "mean": round(sum(tot_sorted) / len(tot_sorted), 2) if tot_sorted else 0.0,
            "max": tot_sorted[-1] if tot_sorted else 0,
        },
        "top_samples_by_tokens": [r.to_dict() for r in top_samples],
    }

    if fail_on_short_clip and short_clips:
        preview = ", ".join(f"{r.candidate_id}(total_frames={r.total_frames}<{num_frames})" for r in short_clips[:10])
        raise InputError(f"preflight failed: {len(short_clips)} short clip(s) below num_frames={num_frames}: [{preview}]")
    if fail_on_gpu_pixel_guard and gpu_guard_exceeding:
        preview = ", ".join(
            f"{r.candidate_id}({r.lf_reg_width}x{r.lf_reg_height}={r.effective_frame_pixels}>{eff_gpu_px})"
            for r in gpu_guard_exceeding[:10]
        )
        raise InputError(
            f"preflight failed: {len(gpu_guard_exceeding)} sample(s) exceed RTX 4090 safe training "
            f"frame-pixel guard ({eff_gpu_px} px): [{preview}]"
        )
    if fail_on_exceed and exceeding:
        preview = ", ".join(
            f"{r.candidate_id}({r.width}x{r.height}, est={r.estimated_total_tokens}>{eff_cutoff})"
            for r in exceeding[:10]
        )
        raise InputError(f"preflight failed: {len(exceeding)} sample(s) exceed cutoff_len={eff_cutoff}: [{preview}]")
    if fail_on_lf_downscale and (downscaled or vllm_mismatches):
        bad = vllm_mismatches if vllm_mismatches else downscaled
        preview = ", ".join(
            f"{r.candidate_id}(lf={list(r.grid_thw)} vs vllm={list(r.vllm_grid_thw)})"
            for r in bad[:10]
        )
        raise InputError(
            f"preflight failed: {len(bad)} sample(s) break bit-exact LlamaFactory/vLLM "
            f"smart_resize alignment: [{preview}]"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, choices=(0, 1, 2), required=True, help="Target CV fold (0, 1, or 2)")
    parser.add_argument("--scope", choices=("confirmed_train", "all_clean_train", "all_clean_dev"), default="confirmed_train",
                        help="Sample scope to audit: currently confirmed fold train, all fold clean train (incl. future B3), or all clean dev")
    parser.add_argument("--modality", choices=SUPPORTED_MODALITIES, required=True, help="SFT modality channel")
    parser.add_argument("--num-frames", type=int, choices=(8, 16), required=True, help="Frames per sample")
    parser.add_argument("--cutoff-len", type=int, help="Override cutoff_len (defaults to channel preset)")
    parser.add_argument("--image-max-pixels", type=int, help="Override image_max_pixels (images mode)")
    parser.add_argument("--image-min-pixels", type=int, help="Override image_min_pixels (images mode)")
    parser.add_argument("--video-max-pixels", type=int, help="Override video_max_pixels (video mode)")
    parser.add_argument("--video-min-pixels", type=int, help="Override video_min_pixels (video mode)")
    parser.add_argument("--max-safe-train-frame-pixels", type=int, help="Override RTX 4090 safe single-frame pixel guard")
    parser.add_argument("--prompt", help="Prompt file path (defaults to five_label_v2.txt)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repository root path")
    parser.add_argument("--no-fail-on-exceed", action="store_true", help="Report cutoff_len violations without non-zero exit")
    parser.add_argument("--fail-on-lf-downscale", "--fail-on-vllm-mismatch", dest="fail_on_lf_downscale", action="store_true",
                        help="Fail closed if LlamaFactory pre-resize or vLLM grid mismatch occurs")
    parser.add_argument("--output", help="Optional JSON output file path (exclusive create)")
    args = parser.parse_args(argv)

    try:
        if args.output:
            validate_safe_output_path(args.output, label="preflight output")
        root = Path(args.repo_root).resolve()
        prompt_path = Path(args.prompt) if args.prompt else root / DEFAULT_PROMPT_REL
        prompt_text, _ = load_prompt(prompt_path)
        ctx = load_fold_isolation_context(args.fold, repo_root=root)

        if args.scope == "confirmed_train":
            samples: list[Any] = select_confirmed_fold_train_samples(ctx)[0]
        elif args.scope == "all_clean_train":
            samples = [
                row
                for cid, row in sorted(ctx.manifest_by_id.items())
                if row.get("source_video_id") in ctx.clean_train_sources
                and not ctx.exclusions.is_excluded(candidate_id=cid, source_id=row.get("source_video_id"))
            ]
        else:
            all_clean_dev_sources = (ctx.fold_train_sources | ctx.fold_val_sources) - ctx.exclusions.excluded_source_ids - ctx.exclusions.isolated_virtual_ids
            samples = [
                row
                for cid, row in sorted(ctx.manifest_by_id.items())
                if row.get("source_video_id") in all_clean_dev_sources
                and not ctx.exclusions.is_excluded(candidate_id=cid, source_id=row.get("source_video_id"))
            ]

        report = run_preflight_on_samples(
            samples,
            modality=args.modality,
            num_frames=args.num_frames,
            cutoff_len=args.cutoff_len,
            image_max_pixels=args.image_max_pixels,
            image_min_pixels=args.image_min_pixels,
            video_max_pixels=args.video_max_pixels,
            video_min_pixels=args.video_min_pixels,
            max_safe_train_frame_pixels=args.max_safe_train_frame_pixels,
            prompt_text=prompt_text,
            fail_on_exceed=not args.no_fail_on_exceed,
            fail_on_short_clip=True,
            fail_on_lf_downscale=args.fail_on_lf_downscale,
        )
        report["fold"] = args.fold
        report["scope"] = args.scope
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            safe_write_bytes(Path(args.output), rendered.encode("utf-8"), overwrite=False, label="preflight output")
        print(rendered, end="")
        return 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
