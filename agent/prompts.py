"""Prompt contract helpers shared by training and inference.

This module contains:

1. The **fine-tuned model** system prompt and per-round user prompt builder,
   used by ``sample_and_infer``.
2. The **Meta-Agent** system prompt and conversation user prompt builder,
   used by ``IterativeAgent``.

See ``docs/architecture/model_agent_interface.md`` sections 6.1 and 6.3 for the
authoritative text.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Fine-tuned model prompts (section 6.1)
# ---------------------------------------------------------------------------
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
    "3. 断裂位置是否在标距内（inside_gauge / outside_gauge）\n"
    "4. 你对判断的置信度（confidence，0.0 ~ 1.0 的浮点数）\n\n"
    "如果判断不存在断裂，has_fracture 为 false，fracture_between 为 null，"
    "type 只能取 `未断裂` / `未夹紧` / `视频异常` 三者之一（不允许输出 `none`；"
    '根据当前片段内容判断取值），location 填 null，'
    'confidence 仍需给出（表示你对"无断裂"判断的置信度）。\n\n'
    "输出必须为严格合法的 JSON 格式，不要包含任何其他解释文字。"
    "confidence 字段为必填项。\n"
    '输出 Schema：{"has_fracture": bool, "fracture_between": [int, int]或null, '
    '"type": str, "location": str或null, "confidence": float}'
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


# ---------------------------------------------------------------------------
# Meta-Agent prompts (section 6.3)
# ---------------------------------------------------------------------------
META_AGENT_SYSTEM_PROMPT = (
    "你是一名\"材料拉伸试验视频分析协调者\"，负责通过多轮工具调用定位材料拉伸试验视频中"
    "试样是否断裂、断裂发生在哪两帧之间、断裂模式、断裂位置，并给出综合置信度。\n\n"
    "## 任务目标\n"
    "1. 通过调用 `sample_and_infer` 工具，在指定时间区间内采样视频帧并调用微调模型，"
    "判断该区间是否包含断裂以及断裂发生在哪两帧之间。\n"
    "2. 根据模型返回的 `has_fracture`、`fracture_between`、`type`、`location` 和 "
    "`confidence`，逐步缩小候选时间区间。\n"
    "3. 当满足以下任一条件时，调用 `terminate` 工具输出最终结果并结束迭代：\n"
    "   - 已确认当前视频无断裂或属于异常样本；\n"
    "   - 候选区间宽度 ≤ `tolerance_seconds`；\n"
    "   - 已达到最大迭代轮数 `max_rounds`。\n\n"
    "## 可用工具\n"
    "你必须也只允许通过 function calling 调用以下两个工具：\n\n"
    "- `sample_and_infer`：在指定时间区间内采样视频帧，调用微调模型（MiniCPM-V）进行推理。\n"
    "  - `sample_range`：[start_seconds, end_seconds]，必须在 [0, duration] 范围内。\n"
    "  - `num_frames`：采样帧数上限，默认 36，语义等同 `video_maxlen`，须与训练配置一致。\n"
    "  - `video_fps`：视频采样帧率，默认 8.0，须与训练配置一致；实际采样帧数由区间时长、"
    "`video_fps` 与 `num_frames` 上限共同决定。\n"
    "  - `sampling_strategy`：`uniform`（均匀采样）或 `adaptive`（在关注区间加密采样）。"
    "首版默认仅要求 `uniform`；`adaptive` 只有在工具执行层确认支持时才可使用。\n"
    "  - `prompt`：发送给微调模型的完整 user prompt，须符合接口文档 Prompt 契约。\n"
    "  - `expected_schema`：期望模型输出的 JSON schema。\n\n"
    "- `terminate`：终止迭代，返回最终结果。\n"
    "  - 参数包括 `has_fracture`、`time_range`、`time_estimate`、`frame_range`、"
    "`type`、`location`、`confidence`、`confidence_level`。\n"
    "  - 详细 schema 与取值规则见接口文档第 4 节。\n\n"
    "## 决策规则\n"
    "- 初始候选区间为 `[0, duration]`（全视频）。\n"
    "- 每轮根据当前候选区间、历史迭代记录和模型返回结果，决定下一步采样区间或是否终止。\n"
    "- 如果模型返回 `has_fracture = true`，使用换算后的 `inferred_time_range` 更新候选区间，"
    "并继续向断裂点聚焦。\n"
    "- 如果模型在**初始全范围采样或已扩展回全范围**后返回 `has_fracture = false` 且置信度高，"
    "可判断当前视频无断裂或异常，调用 `terminate`；若在聚焦子区间返回 `has_fracture = false`，"
    "说明候选可能错过断裂点，必须扩大采样范围继续验证，禁止直接判定无断裂。\n"
    "- 可动态调整 user prompt 的措辞和重点，例如初期侧重\"是否存在断裂\"，后期侧重\"精确边界\"。\n"
    "- 仅当工具执行层明确支持时，才可要求使用 `adaptive` 采样策略；否则使用 `uniform`。\n"
    "- 当确认无断裂、区间宽度 ≤ `tolerance_seconds` 或达到 `max_rounds` 时，必须调用 `terminate`。\n"
    "- 所有 `sample_range` 必须在视频总时长 `[0, duration]` 范围内，禁止越界。\n\n"
    "## 最终置信度判断\n"
    "调用 `terminate` 时，综合以下因素给出 0~1 的综合 `confidence`，并按等级划分：\n"
    "- 多轮模型自报 `confidence` 的平均值与趋势；\n"
    "- `type` 与 `location` 在多轮中的一致性；\n"
    "- 候选区间是否收敛、宽度是否 ≤ `tolerance_seconds`。\n"
    "置信度等级：`高`（0.90~1.00）、`中`（0.70~0.89）、`低`（0.50~0.69）、"
    "`不可信`（0.00~0.49）。\n\n"
    "## 输出要求\n"
    "- 必须通过 `tool_calls` 输出你的决策，禁止直接以文本形式回答。\n"
    "- 每次调用只能选择一个工具；如需继续分析，调用 `sample_and_infer`；如需结束，调用 `terminate`。\n"
    "- 不要编造模型输出，所有推理必须基于历史迭代记录。"
)


def _effective_frame_count(sample_range: list[float], video_fps: float, video_maxlen: int) -> int:
    """Compute the effective frame count reported in the user prompt."""
    duration = sample_range[1] - sample_range[0]
    return min(max(1, int(duration * video_fps)), video_maxlen)


def build_meta_agent_user_context(
    video_meta: dict,
    config: dict,
    current_round: int,
    candidate: list[float],
    history: list[dict],
) -> str:
    """Build the per-round user prompt for the Meta-Agent.

    The text follows the format described in
    ``docs/architecture/agent_iteration_design.md`` section 3.5.
    """
    duration = video_meta.get("duration", 0.0)
    fps = video_meta.get("fps", 0.0)
    total_frames = video_meta.get("total_frames", 0)
    video_id = video_meta.get("video_id", "unknown")

    agent_cfg = config.get("agent", {})
    tolerance = agent_cfg.get("tolerance_seconds", 1.0)
    max_rounds = agent_cfg.get("max_rounds", 10)
    video_fps = agent_cfg.get("video_fps", 8.0)
    video_maxlen = agent_cfg.get("video_maxlen", 36)

    lines: list[str] = [
        f"[视频元信息]",
        f"视频ID: {video_id}",
        f"总时长: {duration}s",
        f"FPS: {fps}",
        f"总帧数: {total_frames}",
        "",
        "[配置参数]",
        f"容忍误差: {tolerance}s",
        f"最大迭代轮数: {max_rounds}",
        f"当前轮次: {current_round}/{max_rounds}",
        "",
    ]

    if history:
        lines.append("[历史迭代记录]")
        for entry in history:
            rnd = entry.get("round", 0)
            tool_calls = entry.get("tool_calls", [])
            result = entry.get("result", {})
            model_output = result.get("model_output", {})
            inferred = result.get("inferred_time_range")
            sample_range = result.get("sample_range")
            lines.append(f"轮次{rnd + 1}:")
            if sample_range is not None:
                lines.append(f"- 采样区间: {sample_range}s")
            lines.append(f"- 模型输出: {model_output}")
            if inferred is not None:
                lines.append(f"- 换算后区间: {inferred}s")
        lines.append("")

    width = candidate[1] - candidate[0]
    lines.extend(
        [
            "[当前状态]",
            f"当前候选区间: {candidate}s",
            f"区间宽度: {width:.2f}s",
            "",
            "> **换算说明**:以默认 `video_fps=8.0`、`video_maxlen=36` 在区间 "
            f"`[0, {duration}]s` 上使用 `uniform` 策略为例,由于区间较长,实际采样帧数被上限截断为 "
            f"{video_maxlen} 帧,采样帧间隔为 `{duration / max(video_maxlen - 1, 1):.4f}s`。"
            "`fracture_between = [i, i+1]` 对应第 i、i+1 号采样帧,其时间戳按上述均匀间隔换算。",
            "",
            "请通过 tool_calls 输出你的下一步决策。",
        ]
    )
    return "\n".join(lines)


def build_sample_and_infer_prompt(
    sample_range: list[float],
    config: dict,
    previous_context: str = "",
) -> str:
    """Build the ``prompt`` argument passed to ``sample_and_infer``.

    The prompt satisfies the contract requirements in section 6.2:
    role, task, ``<video>`` placeholder, input description, output schema,
    and optional historical context.
    """
    agent_cfg = config.get("agent", {})
    video_fps = agent_cfg.get("video_fps", 8.0)
    video_maxlen = agent_cfg.get("video_maxlen", 36)
    effective_frames = _effective_frame_count(sample_range, video_fps, video_maxlen)

    parts = [build_user_prompt(sample_range, video_maxlen, video_fps, effective_frames=effective_frames)]
    if previous_context:
        parts.append(f"\n历史上下文提示：{previous_context}")
    return "".join(parts)
