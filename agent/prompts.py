"""Prompt contract helpers shared by training and inference."""

from __future__ import annotations


SYSTEM_PROMPT = (
    "你是一个材料拉伸试验视频分析助手。"
    "你的任务是分析给定的视频片段，判断试样是否发生断裂。\n\n"
    "如果存在断裂，请回答：\n"
    "1. 断裂发生在哪两帧之间（用帧索引表示，如 [17, 18]）\n"
    "2. 断裂模式（若存在断裂，has_fracture=true，"
    "type 只能从 7 个断裂类中选：韧性断裂；脆性断裂；"
    "界面脱粘；齐根断裂；爆炸性断裂；半脆半韧断裂；"
    "界面脱粘、齐根断裂。其中组合标签 "
    "`界面脱粘、齐根断裂` 作为独立类别，与单独的 `界面脱粘`、`齐根断裂` 不同。"
    "若不存在断裂，has_fracture=false，"
    "type 只能从 3 个非断裂/异常类中选：未断裂；未夹紧；视频异常）\n"
    "3. 断裂位置是否在标距内（inside_gauge / outside_gauge / N/A）\n"
    "4. 你对判断的置信度（confidence，0.0 ~ 1.0 的浮点数）\n\n"
    "如果判断不存在断裂，has_fracture 为 false，fracture_between 为 null，"
    "type 只能取 `未断裂` / `未夹紧` / `视频异常` 三者之一（不允许输出 `none`；"
    '根据当前片段内容判断取值），location 填 "N/A"，'
    'confidence 仍需给出（表示你对"无断裂"判断的置信度）。\n\n'
    "输出必须为严格合法的 JSON 格式，不要包含任何其他解释文字。"
    "confidence 字段为必填项。\n"
    '输出 Schema：{"has_fracture": bool, "fracture_between": [int, int]或null, '
    '"type": str, "location": str, "confidence": float}'
)


def build_user_prompt(
    sample_range: list[float],
    num_frames: int,
    video_fps: float,
    sampling_strategy: str = "uniform",
    effective_frames: int | None = None,
) -> str:
    """Build the user prompt for one ``sample_and_infer`` round.

    The returned string is guaranteed to contain the ``<video>`` placeholder,
    the sampling interval, ``video_fps`` and the effective frame count.

    Args:
        sample_range: Start and end timestamps of the clip, in seconds.
        num_frames: Maximum number of frames the model can ingest.
        video_fps: Frame rate of the source video.
        sampling_strategy: Sampling strategy name (kept for API compatibility;
            no longer included in the prompt text).
        effective_frames: Exact frame count to report in the prompt. If ``None``,
            the value is estimated from ``duration * video_fps`` and clamped to
            ``num_frames``.
    """
    start, end = sample_range
    duration = end - start
    if effective_frames is None:
        effective_frames = max(1, int(duration * video_fps))
        effective_frames = min(effective_frames, num_frames)
    return (
        "<video>\n"
        f"请分析这段拉伸试验视频，判断是否存在断裂。当前区间为 [{start}, {end}] 秒，"
        f"按 video_fps={video_fps} 与 video_maxlen={num_frames} 实际采样 {effective_frames} 帧。"
    )
