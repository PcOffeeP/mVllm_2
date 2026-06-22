from __future__ import annotations

from agent.prompts import SYSTEM_PROMPT, build_user_prompt


def test_system_prompt_is_stable():
    assert "材料拉伸试验视频分析助手" in SYSTEM_PROMPT
    assert "输出必须为严格合法的 JSON 格式" in SYSTEM_PROMPT
    assert "has_fracture" in SYSTEM_PROMPT
    assert "fracture_between" in SYSTEM_PROMPT
    assert "N/A" not in SYSTEM_PROMPT
    assert "location 填 null" in SYSTEM_PROMPT
    assert "location\": str或null" in SYSTEM_PROMPT


def test_build_user_prompt_contains_video_placeholder_and_range():
    prompt = build_user_prompt(
        sample_range=[143.9, 146.9],
        num_frames=36,
        video_fps=8.0,
        sampling_strategy="uniform",
    )
    assert "<video>" in prompt
    assert "[143.9, 146.9]" in prompt
    assert "video_fps=8.0" in prompt
    assert "video_maxlen=36" in prompt
    assert "实际采样 24 帧" in prompt
    assert "uniform" not in prompt
    assert "采样策略" not in prompt


def test_build_user_prompt_uses_provided_effective_frames():
    prompt = build_user_prompt(
        sample_range=[143.9, 146.9],
        num_frames=36,
        video_fps=8.0,
        effective_frames=12,
    )
    assert "实际采样 12 帧" in prompt
    assert "实际采样 24 帧" not in prompt
