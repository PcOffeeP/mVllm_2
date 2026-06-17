"""Meta-Agent iterative controller.

Implements the deterministic state machine described in
``docs/agent_iteration_design.md`` section 3.3.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from agent.inference import InferenceClient, LlamaFactoryInferenceClient, MockInferenceClient
from agent.llm import BaseAgentLLM
from agent.parser import ResultParser
from agent.prompts import (
    META_AGENT_SYSTEM_PROMPT,
    build_meta_agent_user_context,
    build_sample_and_infer_prompt,
)
from agent.sampling import FfmpegVideoClipBuilder, UniformVideoSampler, VideoClipBuilder, VideoSampler
from agent.schema import (
    BoundaryStatus,
    ConfidenceLevel,
    FinalOutput,
    FRACTURE_CLASSES,
    FractureType,
    LocationType,
    ModelOutput,
    NON_FRACTURE_CLASSES,
    SamplingStrategy,
)


logger = logging.getLogger(__name__)


TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "sample_and_infer",
            "description": "在指定时间区间内采样视频帧，调用微调模型进行推理",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_range": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "采样时间区间 [start_seconds, end_seconds]",
                    },
                    "num_frames": {
                        "type": "integer",
                        "description": "视频采样帧数上限，语义等同 video_maxlen",
                        "default": 36,
                    },
                    "video_fps": {
                        "type": "number",
                        "description": "视频采样帧率超参数，需与训练/推理解码配置保持一致",
                        "default": 8.0,
                    },
                    "sampling_strategy": {
                        "type": "string",
                        "enum": ["uniform", "adaptive"],
                        "description": "采样策略：uniform=均匀采样；adaptive=自适应采样（断裂点附近更密）。首版默认仅要求 uniform。",
                        "default": "uniform",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "发送给微调模型的完整 prompt",
                    },
                    "expected_schema": {
                        "type": "object",
                        "description": "期望模型输出的 JSON schema",
                    },
                },
                "required": ["sample_range", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate",
            "description": "终止迭代，返回最终分析结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "has_fracture": {
                        "type": "boolean",
                        "description": "是否存在断裂。false 表示当前视频/片段无断裂或属于异常样本",
                    },
                    "time_range": {
                        "anyOf": [
                            {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            {"type": "null"},
                        ],
                        "description": "最终断裂时间区间 [start_seconds, end_seconds]；has_fracture=false 时应置为 null",
                    },
                    "time_estimate": {
                        "anyOf": [
                            {"type": "number"},
                            {"type": "null"},
                        ],
                        "description": "断裂时间估计值（区间中点或模型最可能值）；has_fracture=false 时应置为 null",
                    },
                    "frame_range": {
                        "anyOf": [
                            {
                                "type": "array",
                                "items": {"type": "integer"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            {"type": "null"},
                        ],
                        "description": "最终断裂帧区间 [start_frame, end_frame]；has_fracture=false 时应置为 null",
                    },
                    "type": {
                        "type": "string",
                        "description": "断裂模式或异常类别",
                    },
                    "location": {
                        "type": "string",
                        "description": "标距内位置判断",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "最终置信度 0-1",
                    },
                    "confidence_level": {
                        "type": "string",
                        "enum": ["高", "中", "低", "不可信"],
                        "description": "置信度等级",
                    },
                },
                "required": [
                    "has_fracture",
                    "time_range",
                    "time_estimate",
                    "frame_range",
                    "type",
                    "location",
                    "confidence",
                    "confidence_level",
                ],
            },
        },
    },
]


class IterativeAgent:
    """Iterative frame-interval localization agent.

    The agent drives a Meta-Agent LLM through Native Function Calling.  State
    transitions, candidate interval updates, conflict handling and termination
    are enforced by this deterministic code layer, not delegated to the LLM.
    """

    def __init__(
        self,
        llm_client: BaseAgentLLM,
        video_meta: dict[str, Any],
        config: dict[str, Any],
        sampler: VideoSampler | None = None,
        clip_builder: VideoClipBuilder | None = None,
        inference_client: InferenceClient | None = None,
        event_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self.llm = llm_client
        self.video_meta = video_meta
        self.config = config
        self.history: list[dict[str, Any]] = []

        agent_cfg = config.get("agent", {})
        self.max_rounds = agent_cfg.get("max_rounds", 10)
        self.tolerance = agent_cfg.get("tolerance_seconds", 1.0)
        self.confidence_threshold = agent_cfg.get("confidence_threshold", 0.5)
        self.max_low_conf_rounds = agent_cfg.get("max_low_conf_rounds", 2)
        self.video_fps = agent_cfg.get("video_fps", 8.0)
        self.video_maxlen = agent_cfg.get("video_maxlen", 36)
        self.temperature = agent_cfg.get("temperature", 0.7)

        self.state = "INITIAL"
        duration = video_meta.get("duration", 0.0)
        self.candidate: list[float] = [0.0, duration]
        self.no_fracture_count = 0
        self.low_conf_count = 0
        self.conflict_count = 0
        self.focus_miss_count = 0
        self.last_boundary_status = "none"
        self.last_round_confidence_level = ConfidenceLevel.UNTRUSTED
        self.best_positive_round: dict[str, Any] | None = None

        self.sampler = sampler or UniformVideoSampler()
        self.clip_builder = clip_builder or FfmpegVideoClipBuilder()
        self.inference_client = inference_client or self._default_inference_client()
        self.event_callback = event_callback

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------
    def _emit(self, event_type: str, **payload: Any) -> None:
        """Emit an event to the optional UI callback."""
        if self.event_callback is None:
            return
        event: dict[str, Any] = {
            "event_type": event_type,
            "video_id": self.video_meta.get("video_id", "unknown"),
            **payload,
        }
        self.event_callback(event)

    @staticmethod
    def _to_json_value(value: Any) -> Any:
        """Convert a Pydantic model to a JSON-serializable dict if needed."""
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        """Run the iterative loop and return the final output dict."""
        messages = self._build_system_messages()
        self._emit(
            "video_started",
            video_path=self.video_meta.get("video_path"),
            duration_sec=self.video_meta.get("duration", 0.0),
            max_rounds=self.max_rounds,
            initial_candidate=list(self.candidate),
        )

        for round_idx in range(self.max_rounds):
            self._emit(
                "round_started",
                round=round_idx,
                display_round=round_idx + 1,
                state=self.state,
                candidate=list(self.candidate),
            )
            response = self.llm.chat_with_tools(
                messages=messages,
                tools=TOOLS_SCHEMA,
                temperature=self.temperature,
            )
            message = response.choices[0].message

            # The LLM must output tool_calls; plain text is not acceptable.
            if not getattr(message, "tool_calls", None):
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append(
                    {"role": "user", "content": "请使用 tool_calls 输出你的决策。"}
                )
                continue

            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            self._emit(
                "llm_tool_call",
                round=round_idx,
                display_round=round_idx + 1,
                tool_name=tool_name,
                tool_args=tool_args,
                reasoning=message.content or "",
            )

            if tool_name == "terminate":
                allowed, reason = self._can_terminate(tool_args, round_idx)
                self._emit(
                    "termination_requested",
                    round=round_idx,
                    display_round=round_idx + 1,
                    allowed=allowed,
                    reason=reason,
                    tool_args=tool_args,
                )
                if allowed:
                    self.state = "TERMINATED"
                    final_args = self._build_final_args(tool_args)
                    result = self._finalize(final_args)
                    self._emit("video_finished", result=result)
                    return result

                messages.append(self._assistant_tool_message(message, tool_call, tool_name))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            {"allowed": False, "reason": reason}, ensure_ascii=False
                        ),
                    }
                )
                continue

            if tool_name == "sample_and_infer":
                sample_range = list(tool_args["sample_range"])
                num_frames = int(tool_args.get("num_frames", self.video_maxlen))
                video_fps = float(tool_args.get("video_fps", self.video_fps))
                sampling_strategy = tool_args.get("sampling_strategy", "uniform")
                self._emit(
                    "sample_and_infer_started",
                    round=round_idx,
                    display_round=round_idx + 1,
                    sample_range=sample_range,
                    num_frames=num_frames,
                    video_fps=video_fps,
                    sampling_strategy=sampling_strategy,
                )

                result = self._execute_sample_and_infer(tool_args)
                self._emit(
                    "sample_and_infer_finished",
                    round=round_idx,
                    display_round=round_idx + 1,
                    model_output=self._to_json_value(result.get("model_output")),
                    inferred_time_range=result.get("inferred_time_range"),
                    inferred_frame_range=result.get("inferred_frame_range"),
                    boundary_status=result.get("boundary_status"),
                    parse_error=result.get("parse_error"),
                    round_confidence_level=result.get("round_confidence_level"),
                )

                previous_state = self.state
                previous_candidate = list(self.candidate)
                self._transition(result)
                self._emit(
                    "state_updated",
                    round=round_idx,
                    display_round=round_idx + 1,
                    previous_state=previous_state,
                    state=self.state,
                    previous_candidate=previous_candidate,
                    candidate=list(self.candidate),
                )
                self._log_round(round_idx, message, result)

                messages.append(self._assistant_tool_message(message, tool_call, tool_name))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

                if self.state == "TERMINATED":
                    result = self._force_terminate()
                    self._emit("video_finished", result=result)
                    return result

                messages.append({
                    "role": "user",
                    "content": build_meta_agent_user_context(
                        video_meta=self.video_meta,
                        config=self.config,
                        current_round=min(round_idx + 2, self.max_rounds),
                        candidate=self.candidate,
                        history=self.history,
                    ),
                })
                continue

            # Unknown tool: report and let the LLM retry.
            messages.append(self._assistant_tool_message(message, tool_call, tool_name))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(
                        {"error": f"未知工具: {tool_name}"}, ensure_ascii=False
                    ),
                }
            )

        result = self._force_terminate()
        self._emit("video_finished", result=result)
        return result

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------
    def _build_system_messages(self) -> list[dict[str, Any]]:
        """Return the initial message list with system + first user context."""
        return [
            {"role": "system", "content": META_AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_meta_agent_user_context(
                    video_meta=self.video_meta,
                    config=self.config,
                    current_round=1,
                    candidate=self.candidate,
                    history=self.history,
                ),
            },
        ]

    def _assistant_tool_message(
        self,
        message: Any,
        tool_call: Any,
        tool_name: str,
    ) -> dict[str, Any]:
        """Format an assistant message that includes a tool_call."""
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_call.function.arguments,
                    },
                }
            ],
        }

    # ------------------------------------------------------------------
    # Termination rules
    # ------------------------------------------------------------------
    def _can_terminate(self, args: dict[str, Any], round_idx: int) -> tuple[bool, str]:
        """Determine whether the current state allows termination."""
        has_fracture = args.get("has_fracture", True)

        # No-fracture path: only allowed in NO_FRACTURE state with global scope.
        if not has_fracture:
            is_global_scope = (
                self.candidate[0] <= 0.0
                and self.candidate[1] >= self.video_meta.get("duration", 0.0)
            )
            if self.state == "NO_FRACTURE" and is_global_scope:
                if self.no_fracture_count >= 2 or self.last_round_confidence_level == ConfidenceLevel.HIGH:
                    return True, "NO_FRACTURE 状态下连续 2 轮确认或高置信无断裂（全局范围）"
            return False, "无断裂判定尚未稳定，请继续验证（仅在 NO_FRACTURE 全局范围可终止）"

        # Fracture path: must converge or exhaust rounds.
        if self.state in ("NARROWING", "VERIFYING"):
            if self.last_boundary_status != "none":
                return False, "边界哨兵需先扩展采样区间并重新验证，不能单独终止"
            if self.candidate[1] - self.candidate[0] <= self.tolerance:
                if self.last_round_confidence_level == ConfidenceLevel.UNTRUSTED:
                    return False, "区间虽收敛但最新一轮置信度不可信，请继续验证"
                return True, "候选区间宽度 ≤ tolerance"
            if round_idx >= self.max_rounds - 1:
                return True, "达到 max_rounds"

        return False, "区间尚未收敛，请继续调用 sample_and_infer"

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def _transition(self, result: dict[str, Any]) -> None:
        """Update state, candidate interval and counters from a tool result."""
        if result.get("parse_error"):
            # Parse failures must not drive state transitions.  Record low
            # confidence and optionally fall back to avoid getting stuck.
            self.last_boundary_status = "none"
            self.last_round_confidence_level = ConfidenceLevel.UNTRUSTED
            self.low_conf_count += 1
            if self.low_conf_count >= self.max_low_conf_rounds:
                self.candidate = self._expand_candidate(self.candidate)
                self.low_conf_count = 0
                result["fallback"] = "parse_error_expanded_to_parent_range"
            return

        model_output = result.get("model_output", {})
        has_fracture = model_output.get("has_fracture", False)
        new_range = result.get("inferred_time_range")
        boundary_status = result.get("boundary_status", "none")
        confidence_level = result.get("round_confidence_level", "不可信")

        self.last_boundary_status = boundary_status

        # ------------------------------------------------------------------
        # No-fracture path
        # ------------------------------------------------------------------
        if not has_fracture:
            self.last_round_confidence_level = confidence_level

            is_global_scope = (
                self.state == "INITIAL"
                or (
                    self.candidate[0] <= 0.0
                    and self.candidate[1] >= self.video_meta.get("duration", 0.0)
                )
            )

            if is_global_scope:
                self.state = "NO_FRACTURE"
                self.no_fracture_count += 1
                return

            # Focused sub-interval returned false: expand and fall back.
            # This is a focus miss, not an inter-result conflict, so it uses a
            # separate counter to control the expansion amplitude.
            self.focus_miss_count += 1
            self.candidate = self._expand_candidate(self.candidate)
            result["fallback"] = "focus_false_expanded_to_parent_range"
            return

        # ------------------------------------------------------------------
        # Fracture path
        # ------------------------------------------------------------------
        self.no_fracture_count = 0
        if self.state in ("INITIAL", "NO_FRACTURE"):
            self.state = "NARROWING"

        # Boundary sentinel handling.
        if boundary_status == "left_sentinel":
            c0, c1 = self.candidate
            step = max(self.tolerance, (c1 - c0) * 0.1)
            self.candidate = [max(0.0, c0 - step), c1]
            result["boundary_handled"] = "expanded_left"
            self.last_round_confidence_level = confidence_level
            return
        if boundary_status == "right_sentinel":
            c0, c1 = self.candidate
            step = max(self.tolerance, (c1 - c0) * 0.1)
            duration = self.video_meta.get("duration", 0.0)
            self.candidate = [c0, min(duration, c1 + step)]
            result["boundary_handled"] = "expanded_right"
            self.last_round_confidence_level = confidence_level
            return

        # Normal interval update and conflict handling.
        if new_range:
            c0, c1 = self.candidate
            n0, n1 = new_range

            if c0 <= n0 and n1 <= c1:
                self.candidate = new_range
                self.conflict_count = 0
                self.low_conf_count = 0
                self.focus_miss_count = 0
            elif not (n1 < c0 or n0 > c1):
                self.candidate = [max(c0, n0), min(c1, n1)]
                self.conflict_count = 0
                self.low_conf_count = 0
                self.focus_miss_count = 0
            else:
                confidence = model_output.get("confidence", 0.5)
                if self._is_low_confidence(confidence):
                    self.low_conf_count += 1
                    result["conflict_handled"] = "discarded_low_confidence"
                else:
                    self.candidate = [min(c0, n0), max(c1, n1)]
                    self.conflict_count += 1
                    result["conflict_handled"] = "expanded_candidate"

                if self.low_conf_count >= self.max_low_conf_rounds:
                    self.candidate = self._expand_candidate(self.candidate)
                    self.low_conf_count = 0
                    result["fallback"] = "expanded_to_parent_range"

        # Enter verification when the interval is narrow enough.
        if self.state == "NARROWING" and (self.candidate[1] - self.candidate[0]) <= self.tolerance:
            self.state = "VERIFYING"

        # Irreconcilable conflicts force termination.
        if self.conflict_count >= 3:
            self.state = "TERMINATED"

        self.last_round_confidence_level = confidence_level

    def _expand_candidate(self, candidate: list[float]) -> list[float]:
        """Expand candidate interval by 1.5x around its center, clamped to [0, duration]."""
        width = candidate[1] - candidate[0]
        center = (candidate[0] + candidate[1]) / 2
        half = width * 0.75
        duration = self.video_meta.get("duration", 0.0)
        return [
            max(0.0, center - half),
            min(duration, center + half),
        ]

    # ------------------------------------------------------------------
    # Forced / final termination
    # ------------------------------------------------------------------
    def _round_has_fracture(self, entry: dict[str, Any]) -> bool:
        """Safely check whether a history entry has a positive fracture prediction."""
        model_output = entry.get("result", {}).get("model_output")
        return isinstance(model_output, dict) and model_output.get("has_fracture", False)

    def _build_final_args(self, requested: dict[str, Any]) -> dict[str, Any]:
        """Build the final ``terminate`` args from code-layer aggregation.

        The returned dict is authoritative: it ignores LLM-provided semantic
        fields (``type``, ``location``, ``time_range``, ``frame_range``,
        ``confidence``) when they conflict with the multi-round evidence stored
        in ``self.history``.
        """
        requested_has_fracture = requested.get("has_fracture", True)
        if requested_has_fracture:
            positive_rounds = [r for r in self.history if self._round_has_fracture(r)]
            if positive_rounds:
                return self._build_fracture_args(positive_rounds, requested)
        return self._build_non_fracture_args(requested)

    def _build_fracture_args(
        self,
        positive_rounds: list[dict[str, Any]],
        requested: dict[str, Any],
    ) -> dict[str, Any]:
        """Aggregate a final positive result from the best positive round."""
        best_round = self._select_best_round(positive_rounds)
        best_result = best_round["result"]
        best_model_output = best_result.get("model_output", {})
        best_frames = best_result.get("frames", [])

        # Time range fallback: inferred -> LLM requested -> candidate.
        best_time_range = best_result.get("inferred_time_range")
        if best_time_range is None:
            requested_time_range = requested.get("time_range")
            if requested_time_range is not None:
                logger.warning(
                    "Best positive round lacks inferred_time_range; falling back to "
                    "LLM requested time_range %s",
                    requested_time_range,
                )
                best_time_range = requested_time_range
            else:
                logger.warning(
                    "Best positive round lacks inferred_time_range and LLM did not "
                    "provide one; falling back to candidate %s",
                    self.candidate,
                )
                best_time_range = self.candidate

        # Frame range fallback: inferred -> LLM requested -> derive from frames/time range.
        best_frame_range = best_result.get("inferred_frame_range")
        if best_frame_range is None:
            requested_frame_range = requested.get("frame_range")
            if requested_frame_range is not None:
                logger.warning(
                    "Best positive round lacks inferred_frame_range; falling back to "
                    "LLM requested frame_range %s",
                    requested_frame_range,
                )
                best_frame_range = requested_frame_range
            elif best_time_range is not None and len(best_frames) >= 2:
                best_frame_range = self._time_range_to_frame_range(best_frames, best_time_range)
                if best_frame_range is None:
                    logger.warning(
                        "Could not derive frame_range from sampled frames for time_range %s",
                        best_time_range,
                    )

        # If the frame range is still unavailable, the output cannot satisfy the
        # fracture schema. Downgrade explicitly rather than failing silently in
        # _finalize.
        if best_frame_range is None:
            reason = "frame_range_unrecoverable"
            logger.warning(
                "Unable to recover frame_range for final fracture output; downgrading to no-fracture (%s)",
                reason,
            )
            return self._build_non_fracture_args(
                {"has_fracture": False, "downgrade_reason": reason}
            )

        voted_type = self._vote_field(
            [r["result"]["model_output"].get("type") for r in positive_rounds],
            valid_set=FRACTURE_CLASSES,
        )
        if voted_type is None:
            fallback_type = requested.get("type")
            if fallback_type in FRACTURE_CLASSES:
                voted_type = fallback_type
            else:
                fallback_type = best_model_output.get("type")
                if fallback_type in FRACTURE_CLASSES:
                    voted_type = fallback_type
                else:
                    reason = "all_fracture_types_invalid"
                    logger.warning(
                        "All positive round types and LLM requested type are invalid; "
                        "downgrading to no-fracture (%s)",
                        reason,
                    )
                    return self._build_non_fracture_args(
                        {"has_fracture": False, "downgrade_reason": reason}
                    )

        voted_location = self._vote_field(
            [r["result"]["model_output"].get("location") for r in positive_rounds],
            valid_set={LocationType.INSIDE, LocationType.OUTSIDE},
        )
        if voted_location is None:
            voted_location = LocationType.NA

        final_confidence = self._aggregate_confidence(positive_rounds)
        return {
            "has_fracture": True,
            "time_range": best_time_range,
            "time_estimate": self._estimate_time(best_time_range),
            "frame_range": best_frame_range,
            "type": voted_type,
            "location": voted_location,
            "confidence": final_confidence,
            "confidence_level": self._confidence_to_level(final_confidence),
        }

    def _build_non_fracture_args(self, requested: dict[str, Any]) -> dict[str, Any]:
        """Normalize a no-fracture termination result.

        The no-fracture class is constrained to the three valid non-fracture
        labels, ``location`` is forced to ``N/A``, interval fields are cleared,
        and ``confidence_level`` is capped at ``中`` because no positive
        evidence has been aggregated.
        """
        requested_type = requested.get("type")
        if requested_type in NON_FRACTURE_CLASSES:
            final_type = requested_type
            level = requested.get("confidence_level", ConfidenceLevel.UNTRUSTED)
            if level == ConfidenceLevel.HIGH:
                level = ConfidenceLevel.MEDIUM
        else:
            final_type = FractureType.NO_FRACTURE
            level = ConfidenceLevel.UNTRUSTED

        # Defensive cap: no positive evidence justifies a high confidence level.
        if level == ConfidenceLevel.HIGH:
            level = ConfidenceLevel.MEDIUM

        args: dict[str, Any] = {
            "has_fracture": False,
            "time_range": None,
            "time_estimate": None,
            "frame_range": None,
            "type": final_type,
            "location": LocationType.NA,
            "confidence": requested.get("confidence", 0.5),
            "confidence_level": level,
        }
        if "downgrade_reason" in requested:
            args["downgrade_reason"] = requested["downgrade_reason"]
        return args

    def _force_terminate(self) -> dict[str, Any]:
        """Construct a final output when rounds are exhausted or conflicts unresolvable."""
        positive_rounds = [r for r in self.history if self._round_has_fracture(r)]
        if self.state == "NO_FRACTURE" or not positive_rounds:
            # NO_FRACTURE state takes precedence over any positive history by design:
            # the state machine only enters NO_FRACTURE after globally scoped rounds
            # consistently report no fracture, so positive rounds in focused follow-ups
            # are treated as unstable noise and the agent is forced to output no fracture.
            if self.state == "NO_FRACTURE" and positive_rounds:
                logger.info(
                    "Force terminating in NO_FRACTURE state despite %d positive history "
                    "round(s); state machine priority treats NO_FRACTURE as authoritative.",
                    len(positive_rounds),
                )
            return self._finalize(self._build_non_fracture_args({"has_fracture": False}))
        return self._finalize(self._build_final_args({"has_fracture": True}))

    def _finalize(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return the final output including metadata and history."""
        has_fracture = args.get("has_fracture", False)
        output = {
            "video_id": self.video_meta.get("video_id", "unknown"),
            "has_fracture": has_fracture,
            "time_range": args.get("time_range") if has_fracture else None,
            "time_estimate": args.get("time_estimate") if has_fracture else None,
            "frame_range": args.get("frame_range") if has_fracture else None,
            "type": args.get("type", FractureType.NO_FRACTURE),
            "location": args.get("location", LocationType.NA),
            "confidence": args.get("confidence", 0.0),
            "confidence_level": args.get("confidence_level", ConfidenceLevel.UNTRUSTED),
            "rounds": len(self.history),
            "history": self.history,
        }
        downgrade_reason = args.get("downgrade_reason")
        if downgrade_reason is not None:
            output["downgrade_reason"] = downgrade_reason
        # Validate against the contract schema; on failure, downgrade to untrusted.
        try:
            FinalOutput(**output)
        except Exception as exc:
            reason = f"Final output schema validation failed: {exc}"
            logger.warning(reason)
            output["has_fracture"] = False
            output["time_range"] = None
            output["time_estimate"] = None
            output["frame_range"] = None
            output["type"] = FractureType.NO_FRACTURE
            output["location"] = LocationType.NA
            output["confidence"] = 0.0
            output["confidence_level"] = ConfidenceLevel.UNTRUSTED
            output["downgrade_reason"] = reason
        return output

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------
    def _select_best_round(self, positive_rounds: list[dict[str, Any]]) -> dict[str, Any]:
        """Select the best positive round by confidence level and interval width."""
        level_score = {"高": 3, "中": 2, "低": 1, "不可信": 0}

        def score(r: dict[str, Any]) -> tuple[int, float]:
            result = r.get("result", {})
            level = result.get("round_confidence_level", "不可信")
            rng = result.get("inferred_time_range")
            width = rng[1] - rng[0] if rng else float("inf")
            return (level_score.get(level, 0), -width)

        return max(positive_rounds, key=score)

    def _vote_field(self, values: list[Any], valid_set: set[str]) -> str | None:
        """Majority vote among valid values."""
        from collections import Counter

        filtered = [v for v in values if v in valid_set]
        if not filtered:
            return None
        return Counter(filtered).most_common(1)[0][0]

    def _estimate_time(self, time_range: list[float]) -> float:
        """Midpoint of a time range."""
        return (time_range[0] + time_range[1]) / 2

    def _time_range_to_frame_range(
        self, frames: list[dict[str, Any]], time_range: list[float]
    ) -> list[int] | None:
        """Recover original frame indices from timestamps in the sampled frames."""
        start_frame = next(
            (f["original_frame"] for f in frames if abs(f["timestamp"] - time_range[0]) < 1e-6),
            None,
        )
        end_frame = next(
            (f["original_frame"] for f in frames if abs(f["timestamp"] - time_range[1]) < 1e-6),
            None,
        )
        if start_frame is not None and end_frame is not None:
            return [start_frame, end_frame]
        return None

    def _aggregate_confidence(self, positive_rounds: list[dict[str, Any]]) -> float:
        """Average model confidence across positive rounds."""
        if not positive_rounds:
            return 0.0
        values = [
            r["result"]["model_output"].get("confidence", 0.0)
            for r in positive_rounds
        ]
        return round(sum(values) / len(values), 4)

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    def _execute_sample_and_infer(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run one round of sample + infer and assemble the tool result."""
        sample_range = list(args["sample_range"])
        video_maxlen = int(args.get("num_frames", self.video_maxlen))
        video_fps = float(args.get("video_fps", self.video_fps))
        strategy = args.get("sampling_strategy", "uniform")

        prompt = args.get("prompt") or build_sample_and_infer_prompt(
            sample_range=sample_range,
            config=self.config,
            previous_context=f"当前候选区间为 {self.candidate}",
        )

        frames = self.sampler.sample(
            video_path=self.video_meta["video_path"],
            sample_range=sample_range,
            num_frames=video_maxlen,
            video_fps=video_fps,
            strategy=strategy,
        )

        model_video_path = self.clip_builder.build(
            source_video=self.video_meta["video_path"],
            sample_range=sample_range,
            frames=frames,
            video_fps=video_fps,
            video_maxlen=video_maxlen,
            sampling_strategy=strategy,
        )

        model_output = self.inference_client.infer(model_video_path, prompt)

        result: dict[str, Any] = {
            "model_output": model_output,
            "frames": frames,
            "model_video_path": model_video_path,
            "sample_range": sample_range,
            "video_fps": video_fps,
            "video_maxlen": video_maxlen,
            "num_sample_frames": len(frames),
            "sampling_strategy": strategy,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "boundary_status": "none",
            "parse_error": None,
            "round_confidence_level": ConfidenceLevel.UNTRUSTED,
        }

        if not isinstance(model_output, dict):
            result["parse_error"] = "InferenceClient.infer 返回非字典，模型输出解析失败"
            return result

        confidence = model_output.get("confidence", 0.5)
        result["round_confidence_level"] = self._confidence_to_level(confidence)

        if model_output.get("has_fracture") and model_output.get("fracture_between"):
            fracture_between = model_output["fracture_between"]
            n = len(frames)

            # Guard against out-of-range fracture_between indices before any
            # index-based conversion.  Report a parse error and skip interval
            # updates rather than raising IndexError.
            if len(fracture_between) != 2:
                result["parse_error"] = f"fracture_between 长度必须为 2， got {fracture_between}"
                return result
            i, j = fracture_between
            if not (0 <= i < n and 0 <= j < n):
                result["parse_error"] = (
                    f"fracture_between {fracture_between} 超出采样帧索引范围 [0, {n - 1}]"
                )
                return result

            if n >= 1 and fracture_between == [0, 0]:
                result["boundary_status"] = "left_sentinel"
            elif n >= 1 and fracture_between == [n - 1, n - 1]:
                result["boundary_status"] = "right_sentinel"
            else:
                result["boundary_status"] = "none"

            result["inferred_time_range"] = self._convert_to_time_range(frames, fracture_between)
            result["inferred_frame_range"] = self._convert_to_frame_range(frames, fracture_between)

        return result

    def _is_low_confidence(self, confidence: float) -> bool:
        """Return whether ``confidence`` is below the configured threshold.

        The four-level ``round_confidence_level`` mapping remains hard-coded
        per ``docs/model_agent_interface.md`` section 4.4.  This threshold is
        used only by the Agent's internal fallback / conflict-handling logic.
        """
        return confidence < self.confidence_threshold

    def _confidence_to_level(self, confidence: float) -> str:
        """Map a numeric confidence to the four-level scale."""
        if confidence >= 0.90:
            return "高"
        if confidence >= 0.70:
            return "中"
        if confidence >= 0.50:
            return "低"
        return "不可信"

    def _convert_to_time_range(
        self, frames: list[dict[str, Any]], fracture_between: list[int]
    ) -> list[float]:
        """Map fracture_between indices to original video time range."""
        i, j = fracture_between
        return [frames[i]["timestamp"], frames[j]["timestamp"]]

    def _convert_to_frame_range(
        self, frames: list[dict[str, Any]], fracture_between: list[int]
    ) -> list[int]:
        """Map fracture_between indices to original video frame range."""
        i, j = fracture_between
        return [frames[i]["original_frame"], frames[j]["original_frame"]]

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _log_round(
        self,
        round_idx: int,
        message: Any,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Record one round for final output and debugging."""
        log_entry: dict[str, Any] = {
            "round": round_idx,
            "model": self.llm.model_name,
            "reasoning": message.content or "",
            "tool_calls": [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in (message.tool_calls or [])
            ],
        }
        if result is not None:
            log_entry["result"] = result
        self.history.append(log_entry)
        logger.info("Round %d: %s", round_idx, json.dumps(log_entry, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Default inference client
    # ------------------------------------------------------------------
    def _default_inference_client(self) -> InferenceClient:
        """Create a default inference client from config or environment."""
        if os.getenv("INFERENCE_MOCK") == "1":
            return MockInferenceClient({
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": "N/A",
                "confidence": 0.5,
            })
        return LlamaFactoryInferenceClient(
            model=self.config.get("backend", {}).get("name", "minicpmv4_6"),
        )
