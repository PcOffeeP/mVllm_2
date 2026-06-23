"""Meta-Agent iterative controller.

Implements the deterministic state machine described in
``docs/architecture/agent_iteration_design.md`` section 3.3, migrated to the
v2 ``ToolSampleAndInfer`` / v3 ``ToolTerminate`` / ``FinalOutput`` contract.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from agent.inference import (
    InferenceClient,
    InferenceResult,
    LlamaFactoryInferenceClient,
    MockInferenceClient,
    _validate_preprocessing_meta,
)
from agent.llm import BaseAgentLLM

from agent.prompts import (
    META_AGENT_SYSTEM_PROMPT,
    build_meta_agent_user_context,
    build_sample_and_infer_prompt,
)
from agent.sampling import ClipBuildResult, FfmpegVideoClipBuilder, VideoClipBuilder
from agent.schema import (
    FinalOutput,
    FRACTURE_CLASSES,
    LocationType,
    SampleAndInferResult,
    ToolSampleAndInfer,
    ToolTerminate,
    ValidationErrorInfo,
)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas for Native Function Calling
# ---------------------------------------------------------------------------
TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "sample_and_infer",
            "description": "在指定时间区间内采样视频帧，调用微调模型（MiniCPM-V）进行推理。源视频由 Runner 上下文绑定，模型处理器最多选择 8 帧；不允许通过本工具指定帧数、帧率或采样策略。",
            "parameters": ToolSampleAndInfer.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate",
            "description": "终止迭代，返回最终分析结果。程序从证据轮次派生 time_range 并执行终止门槛校验。",
            "parameters": ToolTerminate.model_json_schema(),
        },
    },
]

# ---------------------------------------------------------------------------
# Internal confidence helpers
# ---------------------------------------------------------------------------
def _confidence_to_level(confidence: float) -> str:
    """Map a numeric confidence to the four-level scale."""
    if confidence >= 0.90:
        return "高"
    if confidence >= 0.70:
        return "中"
    if confidence >= 0.50:
        return "低"
    return "不可信"


# ---------------------------------------------------------------------------
# IterativeAgent
# ---------------------------------------------------------------------------
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
        self.temperature = agent_cfg.get("temperature", 0.7)

        self.state = "INITIAL"
        duration = video_meta.get("duration", 0.0)
        self.candidate: list[float] = [0.0, duration]
        self.no_fracture_count = 0
        self.low_conf_count = 0
        self.conflict_count = 0
        self.focus_miss_count = 0
        self.last_round_confidence_level = "不可信"
        self.best_positive_round: dict[str, Any] | None = None

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
                self._emit(
                    "sample_and_infer_started",
                    round=round_idx,
                    display_round=round_idx + 1,
                    sample_range=sample_range,
                )

                internal_result = self._execute_sample_and_infer(tool_args)
                self._emit(
                    "sample_and_infer_finished",
                    round=round_idx,
                    display_round=round_idx + 1,
                    model_output=self._to_json_value(internal_result.get("model_output")),
                    inferred_time_range=internal_result.get("inferred_time_range"),
                    inferred_frame_range=internal_result.get("inferred_frame_range"),
                    validation_error=internal_result.get("validation_error"),
                    round_confidence_level=internal_result.get("round_confidence_level"),
                )

                previous_state = self.state
                previous_candidate = list(self.candidate)
                self._transition(internal_result)
                self._emit(
                    "state_updated",
                    round=round_idx,
                    display_round=round_idx + 1,
                    previous_state=previous_state,
                    state=self.state,
                    previous_candidate=previous_candidate,
                    candidate=list(self.candidate),
                )
                self._log_round(round_idx, message, internal_result)

                # Build compact result for LLM tool response.
                compact = self._build_compact_result(internal_result)
                messages.append(self._assistant_tool_message(message, tool_call, tool_name))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            self._to_json_value(compact), ensure_ascii=False
                        ),
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
    # Compact result builder (for LLM tool response)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_compact_result(internal: dict[str, Any]) -> SampleAndInferResult:
        """Build a ``SampleAndInferResult`` from the internal result dict.

        Only the six contract fields are exposed to the decision model.
        """
        validation_error = internal.get("validation_error")
        return SampleAndInferResult(
            ok=bool(internal.get("ok")),
            sample_range=internal.get("sample_range", [0.0, 0.0]),
            model_output=internal.get("model_output"),
            inferred_time_range=internal.get("inferred_time_range"),
            validation_error=(
                ValidationErrorInfo(**validation_error)
                if isinstance(validation_error, dict)
                else None
            ),
            attempts=int(internal.get("attempts", 1)),
        )

    # ------------------------------------------------------------------
    # Termination rules
    # ------------------------------------------------------------------
    def _can_terminate(self, args: dict[str, Any], round_idx: int) -> tuple[bool, str]:
        """Determine whether the current state allows termination.

        Uses ``ToolTerminate`` schema fields: ``status``, ``evidence_rounds``,
        ``unrecognized_reason``.
        """
        status = args.get("status")

        # -- unrecognized: model explicitly reports it cannot form a conclusion --
        if status == "unrecognized":
            unrecognized_reason = args.get("unrecognized_reason")
            valid_reasons = {
                "video_anomaly", "not_clamped", "conflicting_results",
                "invalid_model_output", "insufficient_confidence",
                "incomplete_coverage", "max_rounds",
            }
            if unrecognized_reason not in valid_reasons:
                return False, (
                    f"unrecognized_reason 无效: {unrecognized_reason}，"
                    f"须为 {sorted(valid_reasons)}"
                )
            return True, "模型明确报告无法识别"

        # -- no_fracture: must have global-scope evidence --
        if status == "no_fracture":
            is_global_scope = (
                self.candidate[0] <= 0.0
                and self.candidate[1] >= self.video_meta.get("duration", 0.0)
            )
            if self.state == "NO_FRACTURE" and is_global_scope:
                if self.no_fracture_count >= 2:
                    return True, "NO_FRACTURE 状态下连续 2 轮确认无断裂（全局范围）"
            return False, "无断裂判定尚未稳定，请继续验证（仅在 NO_FRACTURE 全局范围可终止）"

        # -- fracture: check evidence threshold and convergence --
        if status == "fracture":
            evidence_rounds: list[int] = args.get("evidence_rounds") or []
            if not evidence_rounds:
                return False, "evidence_rounds 不能为空"

            positive_evidence = [
                r for r in evidence_rounds
                if r < len(self.history) and self._round_has_fracture(self.history[r])
            ]
            if len(positive_evidence) < 2:
                return False, (
                    f"需要至少 2 轮断裂证据支撑，当前 evidence_rounds 中仅有 "
                    f"{len(positive_evidence)} 轮有效断裂记录"
                )

            # Must converge or exhaust rounds.
            if self.candidate[1] - self.candidate[0] <= self.tolerance:
                if self.last_round_confidence_level == "不可信":
                    return False, "区间虽收敛但最新一轮置信度不可信，请继续验证"
                return True, "候选区间宽度 ≤ tolerance"
            if round_idx >= self.max_rounds - 1:
                return True, "达到 max_rounds"

            return False, "区间尚未收敛，请继续调用 sample_and_infer"

        return False, f"未知 status: {status}"

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def _transition(self, result: dict[str, Any]) -> None:
        """Update state, candidate interval and counters from a tool result."""
        validation_error = result.get("validation_error")
        if validation_error:
            # Validation failures must not drive state transitions.  Record low
            # confidence and optionally fall back to avoid getting stuck.
            self.last_round_confidence_level = "不可信"
            self.low_conf_count += 1
            if self.low_conf_count >= self.max_low_conf_rounds:
                self.candidate = self._expand_candidate(self.candidate)
                self.low_conf_count = 0
                result["fallback"] = "validation_error_expanded_to_parent_range"
            return

        model_output = result.get("model_output", {})
        has_fracture = model_output.get("has_fracture", False)
        new_range = result.get("inferred_time_range")
        confidence_level = result.get("round_confidence_level", "不可信")

        # ------------------------------------------------------------------
        # has_fracture is None: video anomaly / cannot determine
        # Do not enter NO_FRACTURE state, do not increment counters.
        # ------------------------------------------------------------------
        if has_fracture is None:
            self.last_round_confidence_level = confidence_level
            # Stay in current state; anomaly_count tracking is optional.
            return

        # ------------------------------------------------------------------
        # No-fracture path (has_fracture is False)
        # ------------------------------------------------------------------
        if has_fracture is False:
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
        return isinstance(model_output, dict) and model_output.get("has_fracture", False) is True

    def _build_final_args(self, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Build the final result args from code-layer aggregation.

        Uses the LLM's ``terminate`` proposal as a guide but derives
        ``time_range`` and validates types against multi-round evidence.
        """
        status = tool_args.get("status")

        if status == "unrecognized":
            return {
                "status": "unrecognized",
                "time_range": None,
                "fracture_type": None,
                "location": None,
                "confidence": None,
                "unrecognized_reason": tool_args.get("unrecognized_reason", "max_rounds"),
            }

        if status == "no_fracture":
            return self._build_non_fracture_args(tool_args)

        if status == "fracture":
            positive_rounds = [r for r in self.history if self._round_has_fracture(r)]
            if positive_rounds:
                return self._build_fracture_args(positive_rounds, tool_args)
            # No positive evidence – downgrade.
            return self._build_non_fracture_args({
                "status": "no_fracture",
                "confidence": tool_args.get("confidence", 0.5),
                "downgrade_reason": "no_positive_evidence_for_fracture_status",
            })

        # Unknown status – fall back to no_fracture.
        logger.warning("Unknown terminate status %s; falling back to no_fracture", status)
        return self._build_non_fracture_args({
            "status": "no_fracture",
            "confidence": 0.0,
            "downgrade_reason": f"unknown_terminate_status_{status}",
        })

    def _build_fracture_args(
        self,
        positive_rounds: list[dict[str, Any]],
        tool_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Aggregate a final fracture result from the best positive round."""
        best_round = self._select_best_round(positive_rounds)
        best_result = best_round["result"]
        best_model_output = best_result.get("model_output", {})
        best_frames = best_result.get("manifest") or best_result.get("frames", [])

        # Time range: inferred from best round.
        best_time_range = best_result.get("inferred_time_range")
        if best_time_range is None:
            logger.warning(
                "Best positive round lacks inferred_time_range; "
                "falling back to candidate %s",
                self.candidate,
            )
            best_time_range = list(self.candidate)

        # Frame range: inferred from best round.
        best_frame_range = best_result.get("inferred_frame_range")
        if best_frame_range is None and best_time_range is not None and len(best_frames) >= 2:
            best_frame_range = self._time_range_to_frame_range(best_frames, best_time_range)

        voted_type = self._vote_field(
            [r["result"]["model_output"].get("type") for r in positive_rounds],
            valid_set=FRACTURE_CLASSES,
        )
        if voted_type is None:
            fallback_type = tool_args.get("fracture_type")
            if fallback_type in FRACTURE_CLASSES:
                voted_type = fallback_type
            else:
                fallback_type = best_model_output.get("type")
                if fallback_type in FRACTURE_CLASSES:
                    voted_type = fallback_type
                else:
                    reason = "all_fracture_types_invalid"
                    logger.warning(
                        "All positive round types and LLM fracture_type are invalid; "
                        "downgrading to no-fracture (%s)",
                        reason,
                    )
                    return self._build_non_fracture_args({
                        "status": "no_fracture",
                        "confidence": 0.0,
                        "downgrade_reason": reason,
                    })

        voted_location = self._vote_field(
            [r["result"]["model_output"].get("location") for r in positive_rounds],
            valid_set={LocationType.INSIDE, LocationType.OUTSIDE},
        )
        if voted_location is None:
            voted_location = None

        final_confidence = self._aggregate_confidence(positive_rounds)
        return {
            "status": "fracture",
            "time_range": best_time_range,
            "fracture_type": voted_type,
            "location": voted_location,
            "confidence": final_confidence,
            "unrecognized_reason": None,
            # Internal metadata for frame_range fallback in _finalize
            "_frame_range": best_frame_range,
        }

    def _build_non_fracture_args(self, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Normalize a no-fracture termination result.

        No-fracture class is constrained to valid non-fracture labels;
        ``location``, ``time_range`` and ``fracture_type`` are forced to
        ``None``.
        """
        args: dict[str, Any] = {
            "status": "no_fracture",
            "time_range": None,
            "fracture_type": None,
            "location": None,
            "confidence": tool_args.get("confidence", 0.5),
            "unrecognized_reason": None,
        }
        if "downgrade_reason" in tool_args:
            args["downgrade_reason"] = tool_args["downgrade_reason"]
        return args

    def _force_terminate(self) -> dict[str, Any]:
        """Construct a final output when rounds are exhausted or conflicts unresolvable."""
        positive_rounds = [r for r in self.history if self._round_has_fracture(r)]
        if self.state == "NO_FRACTURE" or not positive_rounds:
            if self.state == "NO_FRACTURE" and positive_rounds:
                logger.info(
                    "Force terminating in NO_FRACTURE state despite %d positive history "
                    "round(s); state machine priority treats NO_FRACTURE as authoritative.",
                    len(positive_rounds),
                )
            return self._finalize(self._build_non_fracture_args({
                "status": "no_fracture",
                "confidence": 0.0,
            }))
        return self._finalize(self._build_final_args({"status": "fracture"}))

    def _finalize(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return the final output dict including metadata and history.

        Validates the public fields against ``FinalOutput``; extra metadata
        (``rounds``, ``history``, ``downgrade_reason``, ``frame_range``) is
        appended after validation.
        """
        status = args.get("status", "no_fracture")
        output: dict[str, Any] = {
            "video_id": self.video_meta.get("video_id", "unknown"),
            "status": status,
            "time_range": args.get("time_range") if status == "fracture" else None,
            "fracture_type": args.get("fracture_type") if status == "fracture" else None,
            "location": args.get("location") if status == "fracture" else None,
            "confidence": args.get("confidence"),
            "unrecognized_reason": args.get("unrecognized_reason"),
        }
        # Validate against the contract schema; on failure, downgrade to unrecognized.
        try:
            FinalOutput(**output)
        except Exception as exc:
            reason = f"Final output schema validation failed: {exc}"
            logger.warning(reason)
            output["status"] = "unrecognized"
            output["time_range"] = None
            output["fracture_type"] = None
            output["location"] = None
            output["confidence"] = None
            output["unrecognized_reason"] = "invalid_model_output"
            output["downgrade_reason"] = reason

        # Append metadata.
        output["rounds"] = len(self.history)
        output["history"] = self.history
        downgrade_reason = args.get("downgrade_reason")
        if downgrade_reason is not None:
            output["downgrade_reason"] = downgrade_reason

        # Carry through frame_range for downstream consumers that still need it.
        frame_range = args.get("_frame_range")
        if frame_range is not None:
            output["frame_range"] = frame_range

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

    def _time_range_to_frame_range(
        self, frames: list[dict[str, Any]], time_range: list[float]
    ) -> list[int] | None:
        """Recover original frame indices from timestamps in the manifest/frames."""
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

    def _is_low_confidence(self, confidence: float) -> bool:
        """Return whether ``confidence`` is below the configured threshold."""
        return confidence < self.confidence_threshold

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    def _execute_sample_and_infer(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run one round of sample + infer and return the internal result.

        Builds a continuous clip via ``build_with_manifest``, sends it to the
        inference model, decodes the ``ModelOutput``, and maps
        ``fracture_between`` back to original video time/frame ranges using
        the clip manifest.
        """
        sample_range = list(args["sample_range"])
        prompt = args.get("prompt") or build_sample_and_infer_prompt(
            sample_range=sample_range,
            config=self.config,
            previous_context=f"当前候选区间为 {self.candidate}",
        )

        source_video = self.video_meta["video_path"]

        # Build continuous clip + manifest.
        try:
            clip_result: ClipBuildResult = self.clip_builder.build_with_manifest(
                source_video=source_video,
                sample_range=sample_range,
            )
        except Exception as exc:
            logger.warning("Clip build failed: %s", exc)
            return self._error_result(
                sample_range,
                code="sampling_error",
                message=f"无法构建临时视频片段: {exc}",
            )

        manifest = clip_result.manifest

        # Run inference.
        try:
            inference_result: InferenceResult = self.inference_client.infer(
                clip_result, prompt
            )
        except Exception as exc:
            logger.warning("Inference transport/execution failed: %s", exc)
            return self._error_result(
                sample_range,
                code="inference_transport",
                message=f"推理请求失败: {exc}",
                attempts=1,
            )

        # Build internal result base.
        result: dict[str, Any] = {
            "ok": inference_result.ok,
            "sample_range": sample_range,
            "model_output": inference_result.model_output,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "validation_error": None,
            "attempts": inference_result.attempts,
            "manifest": manifest,
            "model_video_path": clip_result.path,
            "round_confidence_level": "不可信",
        }

        # Handle inference failure.
        if not inference_result.ok:
            result["ok"] = False
            result["model_output"] = None
            err = inference_result.error
            result["validation_error"] = {
                "code": err.code if err else "inference_failed",
                "message": err.message if err else "模型输出解析失败",
                "field": err.field if err else None,
            }
            return result

        # Check server-side preprocessing metadata.
        # When the server adapter is not installed (preprocessing is None),
        # gracefully degrade by using the local manifest — existing tests
        # and development workflows depend on this.
        preprocessing = inference_result.preprocessing
        pp_error_code: str | None = None
        use_server_frames = False
        server_frames: list[dict[str, Any]] | None = None

        if preprocessing is not None:
            # Re-validate; even though infer() already logged warnings, we
            # need the specific error code for the result envelope.
            pp_error_code = _validate_preprocessing_meta(preprocessing)
            if pp_error_code is None:
                use_server_frames = True
                server_frames = preprocessing.get("frames", [])
                logger.info(
                    "Using server-provided frames (count=%d) for mapping",
                    len(server_frames),
                )
            else:
                logger.warning(
                    "Preprocessing metadata from server is invalid (%s), "
                    "will not use server frames for mapping",
                    pp_error_code,
                )
        else:
            logger.warning(
                "No preprocessing metadata from server. "
                "Using local manifest for fracture_between mapping."
            )

        # Derive confidence level.
        model_output = result["model_output"] or {}
        confidence = model_output.get("confidence", 0.5)
        result["round_confidence_level"] = _confidence_to_level(confidence)

        has_fracture = (
            model_output.get("has_fracture") is True
            and model_output.get("fracture_between") is not None
        )

        # ------------------------------------------------------------------
        # Case 1: Preprocessing present and valid — use server frames.
        # ------------------------------------------------------------------
        if use_server_frames and has_fracture:
            fracture_between = model_output["fracture_between"]
            n = len(server_frames)  # Server-reported frame count

            def _reject_indices(msg: str) -> dict[str, Any]:
                result["ok"] = False
                result["model_output"] = None
                result["inferred_time_range"] = None
                result["validation_error"] = {
                    "code": "invalid_index",
                    "message": msg,
                    "field": "fracture_between",
                }
                return result

            if len(fracture_between) != 2:
                return _reject_indices(
                    f"fracture_between 长度必须为 2，got {fracture_between}"
                )
            i, j = fracture_between
            if not (0 <= i < n and 0 <= j < n):
                return _reject_indices(
                    f"fracture_between {fracture_between} "
                    f"超出服务帧索引范围 [0, {n - 1}]"
                )
            if i == j:
                return _reject_indices(
                    f"fracture_between {fracture_between} "
                    f"必须是严格相邻的两帧 [i, i+1]"
                )

            # Map through server frames (authoritative frame table).
            result["inferred_time_range"] = [
                server_frames[i]["timestamp"],
                server_frames[j]["timestamp"],
            ]

            # Derive original_frame from the local manifest by matching
            # timestamps (server frames don't carry original_frame).
            def _lookup_original_frame(ts: float) -> int | None:
                for entry in manifest:
                    if abs(entry["timestamp"] - ts) < 0.0001:
                        return entry["original_frame"]
                return None

            orig_i = _lookup_original_frame(server_frames[i]["timestamp"])
            orig_j = _lookup_original_frame(server_frames[j]["timestamp"])
            if orig_i is not None and orig_j is not None:
                result["inferred_frame_range"] = [orig_i, orig_j]

            return result

        # ------------------------------------------------------------------
        # Case 2: Preprocessing present but invalid → hard error.
        # ------------------------------------------------------------------
        if pp_error_code is not None and preprocessing is not None:
            logger.warning(
                "Preprocessing metadata present but invalid (%s). "
                "Marking round as failed.",
                pp_error_code,
            )
            result["ok"] = False
            result["model_output"] = None
            result["inferred_time_range"] = None
            result["inferred_frame_range"] = None
            result["validation_error"] = {
                "code": pp_error_code,
                "message": f"服务端 preprocessing 元数据校验失败: {pp_error_code}",
                "field": "preprocessing",
            }
            return result

        # ------------------------------------------------------------------
        # Case 3: Preprocessing missing (server adapter not installed).
        # Graceful degradation: use local manifest, do NOT mark error.
        # ------------------------------------------------------------------
        if has_fracture:
            fracture_between = model_output["fracture_between"]
            n = len(manifest)

            def _reject_indices(msg: str) -> dict[str, Any]:
                result["ok"] = False
                result["model_output"] = None
                result["inferred_time_range"] = None
                result["validation_error"] = {
                    "code": "invalid_index",
                    "message": msg,
                    "field": "fracture_between",
                }
                return result

            if len(fracture_between) != 2:
                return _reject_indices(
                    f"fracture_between 长度必须为 2，got {fracture_between}"
                )
            i, j = fracture_between
            if not (0 <= i < n and 0 <= j < n):
                return _reject_indices(
                    f"fracture_between {fracture_between} "
                    f"超出采样帧索引范围 [0, {n - 1}]"
                )
            if i == j:
                return _reject_indices(
                    f"fracture_between {fracture_between} "
                    f"必须是严格相邻的两帧 [i, i+1]"
                )

            # Map through local manifest (existing behaviour).
            result["inferred_time_range"] = [
                manifest[i]["timestamp"],
                manifest[j]["timestamp"],
            ]
            result["inferred_frame_range"] = [
                manifest[i]["original_frame"],
                manifest[j]["original_frame"],
            ]

        return result

    def _error_result(
        self,
        sample_range: list[float],
        code: str,
        message: str,
        field: str | None = None,
        attempts: int = 1,
    ) -> dict[str, Any]:
        """Build an error internal result."""
        return {
            "ok": False,
            "sample_range": sample_range,
            "model_output": None,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "validation_error": {"code": code, "message": message, "field": field},
            "attempts": attempts,
            "manifest": [],
            "model_video_path": None,
            "round_confidence_level": "不可信",
        }

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
                "location": None,
                "confidence": 0.5,
            })
        return LlamaFactoryInferenceClient(
            model=self.config.get("backend", {}).get("name", "minicpmv4_6"),
        )
