"""Unit tests for Qwen3-VL offline token/cutoff_len/alignment preflight validator."""
from __future__ import annotations

from pathlib import Path

import pytest

from script.five_label_eval.errors import InputError
from script.five_label_eval.prompt_id import load_prompt
from script.five_label_sft.constants import BASE_PROMPT_TEMPLATE_TOKENS, DEFAULT_PROMPT_REL, REPO_ROOT
from script.five_label_sft.preflight import (
    analyze_sample_preflight,
    estimate_prompt_and_template_tokens,
    lf_preprocess_image_size,
    main as preflight_main,
    qwen3_vl_smart_resize_image,
    qwen3_vl_smart_resize_video,
    run_preflight_on_samples,
)


@pytest.mark.parametrize(
    ("width", "height", "video_max_pixels", "num_frames", "exp_reg", "exp_grid", "exp_resized", "exp_tokens"),
    [
        # Verified empirical CPU probe measurements from board #5 (vlm-sft transformers 4.57.6 & vLLM 0.34.0)
        (804, 1072, 65_536, 8, (221, 295), (4, 18, 14), (224, 288), 252),
        (804, 1072, 262_144, 8, (443, 591), (4, 36, 28), (448, 576), 1_008),
        (804, 1072, 262_144, 16, (443, 591), (8, 36, 28), (448, 576), 2_016),
        (804, 1072, 589_824, 8, (665, 886), (4, 56, 42), (672, 896), 2_352),
        (804, 1072, 589_824, 16, (665, 886), (8, 56, 42), (672, 896), 4_704),
        (804, 1072, 1_048_576, 8, (804, 1072), (4, 68, 50), (800, 1088), 3_400),
        (804, 1072, 1_048_576, 16, (804, 1072), (8, 68, 50), (800, 1088), 6_800),
        (60, 80, 1_200_000, 8, (60, 80), (4, 4, 4), (64, 64), 16),
        (60, 80, 1_200_000, 16, (60, 80), (8, 4, 4), (64, 64), 32),
        (150, 200, 1_200_000, 8, (150, 200), (4, 12, 10), (160, 192), 120),
        (150, 200, 1_200_000, 16, (150, 200), (8, 12, 10), (160, 192), 240),
        (924, 1232, 1_200_000, 16, (924, 1232), (8, 76, 58), (928, 1216), 8_816),
    ],
)
def test_video_smart_resize_matches_measured_probes(
    width: int,
    height: int,
    video_max_pixels: int,
    num_frames: int,
    exp_reg: tuple[int, int],
    exp_grid: tuple[int, int, int],
    exp_resized: tuple[int, int],
    exp_tokens: int,
) -> None:
    res = analyze_sample_preflight(
        candidate_id="probe_clip",
        source_id="video_0021",
        width=width,
        height=height,
        total_frames=180,
        modality="video",
        num_frames=num_frames,
        cutoff_len=12288,
        video_max_pixels=video_max_pixels,
        video_min_pixels=256,
    )
    assert (res.lf_reg_width, res.lf_reg_height) == exp_reg
    assert res.grid_thw == exp_grid
    assert (res.resized_width, res.resized_height) == exp_resized
    assert res.visual_pad_tokens == exp_tokens
    assert res.lf_downscale_triggered == (width * height > video_max_pixels)


def test_images_8f_smart_resize_matches_dec008_baseline() -> None:
    # Smallest clip (60x80) upscaled to image_min_pixels=65536 -> 70 tokens/frame * 8 = 560 tokens
    small = analyze_sample_preflight(
        candidate_id="video_0054_coverage_03",
        source_id="video_0054",
        width=60,
        height=80,
        total_frames=600,
        modality="images",
        num_frames=8,
        cutoff_len=8192,
        image_max_pixels=1_200_000,
        image_min_pixels=65_536,
    )
    assert small.visual_pad_tokens == 560
    assert not small.exceeds_cutoff

    # Largest dev clip (804x1072) -> 850 tokens/frame * 8 = 6,800 tokens
    large = analyze_sample_preflight(
        candidate_id="video_0021_coverage_01",
        source_id="video_0021",
        width=804,
        height=1072,
        total_frames=180,
        modality="images",
        num_frames=8,
        cutoff_len=8192,
        image_max_pixels=1_200_000,
        image_min_pixels=65_536,
    )
    assert large.visual_pad_tokens == 6_800
    assert large.visual_wrapper_tokens == 16
    assert large.estimated_total_tokens <= 8192
    assert not large.exceeds_cutoff


def test_preflight_fails_closed_on_cutoff_exceeded() -> None:
    samples = [
        {"candidate_id": "big_clip", "source_id": "video_0021", "width": 804, "height": 1072, "total_frames": 180}
    ]
    with pytest.raises(InputError, match="exceed cutoff_len=4096"):
        run_preflight_on_samples(
            samples,
            modality="video",
            num_frames=16,
            cutoff_len=4096,
            fail_on_exceed=True,
        )


def test_preflight_fails_closed_on_short_clip() -> None:
    samples = [
        {"candidate_id": "short_clip", "source_id": "video_0021", "width": 200, "height": 200, "total_frames": 12}
    ]
    with pytest.raises(InputError, match="short clip"):
        run_preflight_on_samples(
            samples,
            modality="video",
            num_frames=16,
            cutoff_len=12288,
            fail_on_short_clip=True,
        )


def test_preflight_rejects_odd_num_frames_in_video_mode() -> None:
    with pytest.raises(InputError, match="even num_frames"):
        analyze_sample_preflight(
            candidate_id="clip_odd",
            source_id="video_0021",
            width=200,
            height=200,
            total_frames=60,
            modality="video",
            num_frames=9,
            cutoff_len=8192,
        )


def test_preflight_flags_lf_downscale_alignment_mismatch() -> None:
    samples = [
        {"candidate_id": "big_clip", "source_id": "video_0021", "width": 804, "height": 1072, "total_frames": 180}
    ]
    report = run_preflight_on_samples(
        samples,
        modality="video",
        num_frames=16,
        cutoff_len=12288,
        video_max_pixels=262_144,
        fail_on_lf_downscale=False,
    )
    assert report["lf_downscale_triggered_count"] == 1
    assert report["vllm_alignment_clean"] is False

    with pytest.raises(InputError, match="smart_resize alignment"):
        run_preflight_on_samples(
            samples,
            modality="video",
            num_frames=16,
            cutoff_len=12288,
            video_max_pixels=262_144,
            fail_on_lf_downscale=True,
        )


def test_lf_preprocess_and_smart_resize_edge_bounds() -> None:
    w, h, down = lf_preprocess_image_size(10, 10, max_pixels=1_200_000, min_pixels=256)
    assert min(w, h) >= 28
    assert not down
    h_bar, w_bar = qwen3_vl_smart_resize_image(1072, 804)
    assert (w_bar, h_bar) == (800, 1088)
    t_bar, vh, vw = qwen3_vl_smart_resize_video(16, 1072, 804)
    assert (t_bar, vw, vh) == (16, 800, 1088)


def test_prompt_token_calibration_matches_five_label_v2() -> None:
    prompt_text, _ = load_prompt(REPO_ROOT / DEFAULT_PROMPT_REL)
    assert estimate_prompt_and_template_tokens(prompt_text) == BASE_PROMPT_TEMPLATE_TOKENS
    assert estimate_prompt_and_template_tokens(prompt_text + "x" * 100) > BASE_PROMPT_TEMPLATE_TOKENS


def test_preflight_fails_closed_on_rtx4090_frame_pixel_guard_16f_video() -> None:
    # 924x1232 = 1,138,368 px > 865,000 px RTX 4090 16f QLoRA guard -> must fail closed even with cutoff_len=12288
    oversized = [
        {"candidate_id": "synth_924x1232", "source_id": "video_9999", "width": 924, "height": 1232, "total_frames": 180}
    ]
    with pytest.raises(InputError, match="RTX 4090 safe training frame-pixel guard"):
        run_preflight_on_samples(
            oversized,
            modality="video",
            num_frames=16,
            cutoff_len=12288,
            fail_on_gpu_pixel_guard=True,
        )

    # 924x1232 with explicit safe downscale video_max_pixels=786_432 (768x1024 <= 865_000 px) passes 4090 guard
    downscaled_report = run_preflight_on_samples(
        oversized,
        modality="video",
        num_frames=16,
        cutoff_len=8192,
        video_max_pixels=786_432,
        fail_on_gpu_pixel_guard=True,
        fail_on_lf_downscale=False,
    )
    assert downscaled_report["exceeds_gpu_frame_pixel_guard_count"] == 0
    assert downscaled_report["exceeds_cutoff_count"] == 0
    assert downscaled_report["vllm_grid_mismatch_count"] == 1
    assert downscaled_report["vllm_alignment_clean"] is False

    # Clean dev max 804x1072 = 861,888 px <= 865,000 px passes under default cutoff_len=8192
    dev_max = [
        {"candidate_id": "video_0021_coverage_01", "source_id": "video_0021", "width": 804, "height": 1072, "total_frames": 180}
    ]
    report = run_preflight_on_samples(dev_max, modality="video", num_frames=16)
    assert report["cutoff_len"] == 8192
    assert report["exceeds_cutoff_count"] == 0
    assert report["exceeds_gpu_frame_pixel_guard_count"] == 0
    assert report["vllm_grid_mismatch_count"] == 0
    assert report["vllm_alignment_clean"] is True


def test_preflight_detects_video_min_pixels_upscale_vllm_mismatch() -> None:
    small = [
        {"candidate_id": "video_0054_coverage_03", "source_id": "video_0054", "width": 60, "height": 80, "total_frames": 600}
    ]
    report = run_preflight_on_samples(
        small,
        modality="video",
        num_frames=16,
        video_min_pixels=65_536,
        fail_on_lf_downscale=False,
    )
    assert report["vllm_grid_mismatch_count"] == 1
    assert report["vllm_alignment_clean"] is False

    with pytest.raises(InputError, match="smart_resize alignment"):
        run_preflight_on_samples(
            small,
            modality="video",
            num_frames=16,
            video_min_pixels=65_536,
            fail_on_lf_downscale=True,
        )


def test_preflight_detects_images_8f_two_stage_upscale_interpolation_history() -> None:
    # 60x80 < image_min_pixels=65536 undergoes LlamaFactory pre-upscale (221x295 -> 224x320) vs vLLM direct (60x80 -> 224x320).
    # Grids match ([8, 20, 14]), so vllm_grid_aligned=True, but bit-exact vllm_alignment_clean MUST be False!
    small = [
        {"candidate_id": "video_0054_coverage_03", "source_id": "video_0054", "width": 60, "height": 80, "total_frames": 600}
    ]
    report = run_preflight_on_samples(
        small,
        modality="images",
        num_frames=8,
        fail_on_lf_downscale=False,
    )
    assert report["vllm_grid_aligned"] is True
    assert report["vllm_grid_mismatch_count"] == 0
    assert report["lf_preprocess_resized_count"] == 1
    assert report["vllm_alignment_clean"] is False

    with pytest.raises(InputError, match="smart_resize alignment"):
        run_preflight_on_samples(
            small,
            modality="images",
            num_frames=8,
            fail_on_lf_downscale=True,
        )


def test_preflight_cli_refuses_protected_output_path() -> None:
    rc = preflight_main(
        [
            "--fold",
            "0",
            "--scope",
            "confirmed_train",
            "--modality",
            "video",
            "--num-frames",
            "16",
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            "data//splits/evil_preflight.json",
        ]
    )
    assert rc == 2


def test_preflight_cli_real_repo_fold0_all_clean_dev(tmp_path: Path) -> None:
    out_file = tmp_path / "preflight_dev.json"
    rc = preflight_main(
        [
            "--fold",
            "0",
            "--scope",
            "all_clean_dev",
            "--modality",
            "video",
            "--num-frames",
            "16",
            "--repo-root",
            str(REPO_ROOT),
            "--fail-on-lf-downscale",
            "--output",
            str(out_file),
        ]
    )
    assert rc == 0
    assert out_file.is_file()
