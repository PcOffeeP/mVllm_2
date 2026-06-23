from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import json

import pytest

from agent.inference import InferenceResult
from agent.iterative_agent import IterativeAgent
from agent.llm import BaseAgentLLM
from agent.sampling import ClipBuildResult


class StaticLLM(BaseAgentLLM):
    """LLM that returns a fixed sequence of tool_calls responses."""

    def __init__(self, sequence: list[tuple[str, dict[str, Any]]]) -> None:
        self.sequence = sequence
        self.index = 0

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        name, args = self.sequence[self.index]
        self.index = min(self.index + 1, len(self.sequence) - 1)

        tool_call = MagicMock()
        tool_call.id = f"call_{self.index}"
        tool_call.type = "function"
        tool_call.function.name = name
        tool_call.function.arguments = __import__("json").dumps(args)

        message = MagicMock()
        message.content = f"calling {name}"
        message.tool_calls = [tool_call]

        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def model_name(self) -> str:
        return "static/test"


class FakeClipBuilder:
    """Clip builder that returns a ``ClipBuildResult`` with a synthetic manifest."""

    def __init__(self, video_fps: float = 8.0):
        self.video_fps = video_fps

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
        video_fps: float = 8.0,
        video_maxlen: int = 36,
        sampling_strategy: str = "uniform",
    ) -> ClipBuildResult:
        start, end = sample_range
        duration = end - start
        n = max(1, min(video_maxlen, int(duration * video_fps)))
        step = duration / max(n - 1, 1)
        manifest = [
            {
                "temp_index": k,
                "original_frame": int(round((start + k * step) * video_fps)),
                "timestamp": round(start + k * step, 6),
            }
            for k in range(n)
        ]
        return ClipBuildResult(
            path=f"clip_{start}_{end}.mp4",
            manifest=manifest,
        )


class FakeInferenceClient:
    """Returns canned ``InferenceResult`` objects."""

    def __init__(self, responses: list):
        self.responses = responses
        self.index = 0

    def infer(self, video_input, prompt) -> InferenceResult:
        resp = self.responses[self.index]
        self.index = min(self.index + 1, len(self.responses) - 1)

        if isinstance(resp, InferenceResult):
            return resp

        if isinstance(resp, dict):
            return InferenceResult(ok=True, model_output=resp, attempts=1)

        if resp is None:
            return InferenceResult(
                ok=False,
                model_output=None,
                error=MagicMock(code="inference_failed", message="模型输出解析失败", field=None),
                attempts=1,
            )

        # String: parse via ResultParser to produce ok/error.
        from agent.parser import ResultParser
        parsed = ResultParser.parse(resp)
        if parsed.ok:
            return InferenceResult(ok=True, model_output=parsed.data, attempts=1)
        return InferenceResult(ok=False, error=parsed.error, attempts=1)


def make_config():
    return {
        "agent": {
            "tolerance_seconds": 1.0,
            "max_rounds": 5,
            "confidence_threshold": 0.5,
            "max_low_conf_rounds": 2,
            "temperature": 0.0,
        }
    }


def test_iterative_agent_terminates_on_converged_fracture():
    video_meta = {"video_id": "v001", "duration": 100.0, "video_path": "v001.mp4"}
    config = make_config()

    # Model returns fracture between frames 17-18 of 36.
    # With video_fps=8, duration=100, effective frames = min(36, 800) = 36.
    # Timestamps: k * 100 / 35. fracture_between [17,18] -> [48.571429, 51.428571].
    responses = [
        {
            "has_fracture": True,
            "fracture_between": [17, 18],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
        },
        {
            "has_fracture": True,
            "fracture_between": [17, 18],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
        },
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    assert result["location"] == "inside_gauge"
    assert result["rounds"] == 2
    assert result["confidence"] is not None


def test_iterative_agent_no_fracture_global_scope():
    video_meta = {"video_id": "v002", "duration": 60.0, "video_path": "v002.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "no_fracture"
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert result["time_range"] is None
    assert result["rounds"] == 2


def test_iterative_agent_rejects_early_terminate_until_converged():
    """Early fracture termination without convergence must be rejected."""
    video_meta = {"video_id": "v003", "duration": 100.0, "video_path": "v003.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        # Round 0: sample full range.
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Round 1: LLM tries to terminate with only 1 evidence round -> rejected.
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        # Round 2: sample narrowed range.
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        # Round 3: terminate with 2 evidence rounds -> allowed.
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["rounds"] == 2


def test_iterative_agent_handles_parse_error():
    video_meta = {"video_id": "v005", "duration": 100.0, "video_path": "v005.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    # First response is a parse failure as a string.
    responses = [
        "this is not valid json",
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    # The first round must carry a validation_error description.
    assert result["history"][0]["result"]["validation_error"]
    assert "invalid" in str(result["history"][0]["result"]["validation_error"]).lower()


def test_iterative_agent_rejects_boundary_sentinel_as_parse_error():
    """A boundary sentinel [0,0] / [N-1,N-1] is rejected as a strict-adjacency parse error."""
    video_meta = {"video_id": "v004", "duration": 100.0, "video_path": "v004.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4
    config["agent"]["tolerance_seconds"] = 5.0

    responses = [
        # Round 0: full range, valid fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.85},
        # Round 1: focused interval returns illegal boundary sentinel.
        # The parser rejects [0,0] because it's not strictly adjacent [i, i+1].
        {"has_fracture": True, "fracture_between": [0, 0], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.85},
        # Round 2: focused interval returns valid left-edge adjacent pair.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.90},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "脆性断裂",
            "location": "inside_gauge",
            "confidence": 0.90,
            "evidence_rounds": [0, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "脆性断裂"
    # Round 1 must carry a validation_error for the non-adjacent sentinel.
    assert result["history"][1]["result"]["validation_error"]
    assert "严格相邻" in result["history"][1]["result"]["validation_error"]["message"]
    assert result["rounds"] == 3


def test_iterative_agent_focus_false_expands_candidate():
    """A focused sub-interval returning has_fracture=false is a focus miss, not a conflict."""
    video_meta = {"video_id": "v006", "duration": 100.0, "video_path": "v006.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        # Round 0: full range, fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        # Round 1: focused interval returns false -> focus miss, expand candidate.
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.80},
        # Round 2: expanded interval returns a converged normal interval.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [47.857143, 52.142857], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    # Focus misses must not pollute the conflict counter.
    assert agent.conflict_count == 0
    assert result["history"][1]["result"].get("fallback") == "focus_false_expanded_to_parent_range"


def test_iterative_agent_conflict_expands_candidate():
    """A high-confidence result outside the candidate triggers conflict expansion."""
    video_meta = {"video_id": "v007", "duration": 100.0, "video_path": "v007.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        # Round 0: full range, fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        # Round 1: wider interval returns a range entirely left of the candidate.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.88},
        # Round 2: re-sample the expanded candidate and converge.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [40.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [40.0, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    assert result["history"][1]["result"].get("conflict_handled") == "expanded_candidate"


def test_iterative_agent_low_confidence_fallback():
    """Repeated low-confidence conflicts are discarded until fallback expansion."""
    video_meta = {"video_id": "v008", "duration": 100.0, "video_path": "v008.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5
    config["agent"]["confidence_threshold"] = 0.5

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.3},
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.3},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [40.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [40.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [47.857143, 52.142857], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 3],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    assert result["history"][2]["result"].get("conflict_handled") == "discarded_low_confidence"
    assert result["history"][2]["result"].get("fallback") == "expanded_to_parent_range"


def test_iterative_agent_out_of_bounds_fracture_between():
    """An out-of-range fracture_between must become a validation_error, not an IndexError."""
    video_meta = {"video_id": "v009", "duration": 100.0, "video_path": "v009.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": True, "fracture_between": [100, 101], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    # The first round must carry an out-of-range validation_error and no interval.
    assert result["history"][0]["result"]["validation_error"]
    assert "超出采样帧索引范围" in result["history"][0]["result"]["validation_error"]["message"]
    assert result["history"][0]["result"]["inferred_time_range"] is None
    assert result["history"][0]["result"]["inferred_frame_range"] is None


def test_iterative_agent_inference_returns_none_is_parse_error():
    """If InferenceClient.infer returns ok=False, the agent records a validation error."""
    video_meta = {"video_id": "v010", "duration": 100.0, "video_path": "v010.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    responses = [
        None,  # signals inference failure
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    assert result["history"][0]["result"]["validation_error"]
    assert result["history"][0]["result"]["model_output"] is None


class RecordingLLM(BaseAgentLLM):
    """LLM that records the messages seen on every call."""

    def __init__(self, sequence: list[tuple[str, dict[str, Any]]]) -> None:
        self.sequence = sequence
        self.index = 0
        self.calls: list[list[dict[str, Any]]] = []

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls.append(deepcopy(messages))
        name, args = self.sequence[self.index]
        self.index = min(self.index + 1, len(self.sequence) - 1)

        tool_call = MagicMock()
        tool_call.id = f"call_{self.index}"
        tool_call.type = "function"
        tool_call.function.name = name
        tool_call.function.arguments = json.dumps(args)

        message = MagicMock()
        message.content = f"calling {name}"
        message.tool_calls = [tool_call]

        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def model_name(self) -> str:
        return "static/test"


def test_terminate_uses_code_layer_aggregation_not_llm_args():
    """LLM terminate args disagreeing with history must be overridden by code-layer aggregation."""
    video_meta = {"video_id": "v101", "duration": 100.0, "video_path": "v101.mp4"}
    config = make_config()

    # Both positive rounds predict 脆性断裂; round 1 is narrower and becomes best.
    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [15, 16], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.91},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",  # LLM proposes wrong type
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    # Code-layer aggregation should pick the majority vote (脆性断裂), not LLM's 韧性断裂.
    assert result["fracture_type"] == "脆性断裂"
    # The time_range must come from the best (narrower) round.
    best_round = result["history"][1]["result"]
    assert result["time_range"] == best_round["inferred_time_range"]


def test_no_fracture_terminate_uses_contract_schema():
    """No-fracture termination produces FinalOutput-compatible fields."""
    video_meta = {"video_id": "v102", "duration": 60.0, "video_path": "v102.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "no_fracture"
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert result["time_range"] is None
    assert result["unrecognized_reason"] is None


def test_each_round_appends_updated_state_context():
    """After every sample_and_infer round a fresh user context must be appended."""
    video_meta = {"video_id": "v103", "duration": 100.0, "video_path": "v103.mp4"}
    config = make_config()

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [15, 16], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = RecordingLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    agent.run()
    # Three LLM calls: initial, after round 0, after round 1.
    assert len(llm.calls) == 3

    # Initial call only has system + first user context.
    assert len(llm.calls[0]) == 2

    # Second call must include the updated state context after round 0.
    assert len(llm.calls[1]) == 5
    assert llm.calls[1][-1]["role"] == "user"
    assert "当前候选区间" in llm.calls[1][-1]["content"]

    # Third call must include the state context after round 1 (narrower candidate).
    assert len(llm.calls[2]) == 8
    assert llm.calls[2][-1]["role"] == "user"
    assert "当前候选区间" in llm.calls[2][-1]["content"]


def test_positive_without_inferred_range_fallback():
    """Positive round without inferred ranges falls back to candidate range."""
    video_meta = {"video_id": "v201", "duration": 100.0, "video_path": "v201.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    positive_rounds = [
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": None,
                "inferred_frame_range": None,
            }
        }
    ]

    # No inferred ranges -> fall back to candidate.
    tool_args = {
        "status": "fracture",
        "fracture_type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
    }
    args = agent._build_fracture_args(positive_rounds, tool_args)
    assert args["status"] == "fracture"
    assert args["time_range"] == [0.0, 100.0]  # candidate fallback
    assert args["fracture_type"] == "韧性断裂"


def test_build_fracture_args_all_invalid_types_fallback():
    """When all positive round types are invalid, downgrade to no-fracture."""
    video_meta = {"video_id": "v202", "duration": 100.0, "video_path": "v202.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    positive_rounds = [
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "invalid_type",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": [10.0, 20.0],
                "inferred_frame_range": [80, 160],
            }
        }
    ]
    tool_args = {
        "status": "fracture",
        "fracture_type": "another_invalid_type",
        "location": "inside_gauge",
        "confidence": 0.92,
    }

    args = agent._build_fracture_args(positive_rounds, tool_args)
    assert args["status"] == "no_fracture"
    assert args["fracture_type"] is None
    assert args.get("downgrade_reason") is not None

    # _finalize must preserve the downgrade reason and output a valid unrecognized or no-fracture result.
    final = agent._finalize(args)
    assert final["status"] in ("no_fracture", "unrecognized")
    assert final["time_range"] is None
    assert "downgrade_reason" in final


def test_force_terminate_no_fracture_state_ignores_positive_history(caplog):
    """NO_FRACTURE state forces a no-fracture output even if history contains positive rounds."""
    video_meta = {"video_id": "v203", "duration": 100.0, "video_path": "v203.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )
    agent.state = "NO_FRACTURE"
    agent.history = [
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                }
            }
        }
    ]

    with caplog.at_level("INFO", logger="agent.iterative_agent"):
        result = agent._force_terminate()

    assert result["status"] == "no_fracture"
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert "NO_FRACTURE" in caplog.text
    assert "state machine priority" in caplog.text


def test_unrecognized_termination():
    """Model explicitly reports unrecognized -> agent accepts the termination."""
    video_meta = {"video_id": "v300", "duration": 100.0, "video_path": "v300.mp4"}
    config = make_config()

    responses = [
        {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.7},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "unrecognized",
            "unrecognized_reason": "video_anomaly",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    assert result["unrecognized_reason"] == "video_anomaly"
    assert result["time_range"] is None
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert result["confidence"] is None


def test_unrecognized_termination_invalid_reason_rejected():
    """Invalid unrecognized_reason is rejected by _can_terminate."""
    video_meta = {"video_id": "v301", "duration": 100.0, "video_path": "v301.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.7},
        {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.7},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "unrecognized",
            "unrecognized_reason": "bad_reason",
        }),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # With invalid unrecognized_reason, the terminate is rejected.
    # After max_rounds, force_terminate kicks in with no positive rounds -> no_fracture.
    assert result["status"] in ("no_fracture", "unrecognized")


# ---------------------------------------------------------------------------
# Preprocessing metadata integration
# ---------------------------------------------------------------------------
def test_iterative_agent_uses_server_frames_when_preprocessing_valid():
    """With valid server preprocessing, fracture_between maps via server frames."""
    video_meta = {"video_id": "v400", "duration": 100.0, "video_path": "v400.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    # Server frames (3 frames selected by MiniCPM-V processor).
    server_frames = [
        {"index": 0, "timestamp": 0.0},
        {"index": 1, "timestamp": 0.5},
        {"index": 2, "timestamp": 1.0},
    ]
    preprocessing = {
        "request_id": "uuid-400",
        "processor_version": "minicpmv4.6/0.1",
        "max_frames": 8,
        "frames": server_frames,
    }

    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            preprocessing=preprocessing,
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [0.0, 0.5], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    # The time_range should be derived from server frames [0, 1] -> [0.0, 0.5]
    assert result["time_range"] == [0.0, 0.5]

    # Round 0 should use server timestamps, not local manifest.
    round0 = result["history"][0]["result"]
    assert round0["inferred_time_range"] == [0.0, 0.5]


def test_iterative_agent_missing_preprocessing_graceful_fallback():
    """Missing preprocessing (server adapter not deployed) gracefully falls back to local manifest."""
    video_meta = {"video_id": "v401", "duration": 100.0, "video_path": "v401.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    # No preprocessing — InferenceResult.preprocessing defaults to None.
    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [17, 18],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            # preprocessing=None by default
        ),
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            # preprocessing=None by default
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # Status must be fracture (not error) — graceful fallback works.
    assert result["status"] == "fracture"
    # The time_range should use local manifest mapping.
    assert result["time_range"] is not None


def test_iterative_agent_invalid_preprocessing_max_frames_not_8_errors():
    """Preprocessing with max_frames != 8 causes round failure."""
    video_meta = {"video_id": "v402", "duration": 100.0, "video_path": "v402.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    preprocessing = {
        "request_id": "uuid-402",
        "processor_version": "wrong-version",
        "max_frames": 4,  # Not 8
        "frames": [{"index": 0, "timestamp": 0.0}],
    }

    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            preprocessing=preprocessing,  # Present but invalid
        ),
        # Second round: fallback with valid output so agent can continue.
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [17, 18],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            # no preprocessing (graceful fallback)
        ),
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [1],
        }),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [1, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # The agent should still reach a conclusion despite the invalid preprocessing on round 0.
    assert result["status"] == "fracture"
    # Round 0 should have a validation error.
    round0 = result["history"][0]["result"]
    assert not round0["ok"]
    assert round0["validation_error"] is not None


def test_iterative_agent_too_many_frames_preprocessing_error():
    """Preprocessing with >8 frames causes round failure."""
    video_meta = {"video_id": "v403", "duration": 100.0, "video_path": "v403.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    preprocessing = {
        "request_id": "uuid-403",
        "processor_version": "minicpmv4.6/0.1",
        "max_frames": 8,
        "frames": [{"index": i, "timestamp": float(i)} for i in range(9)],  # 9 frames > 8
    }

    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            preprocessing=preprocessing,
        ),
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.95,
            },
            attempts=1,
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # Should reach a conclusion despite round 0 error.
    assert result["status"] in ("fracture", "no_fracture")
    round0 = result["history"][0]["result"]
    assert not round0["ok"]
