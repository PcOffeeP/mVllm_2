from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import json

import pytest

from agent.iterative_agent import IterativeAgent
from agent.llm import BaseAgentLLM


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


class FakeSampler:
    def sample(self, video_path, sample_range, num_frames, video_fps, strategy):
        start, end = sample_range
        n = max(1, min(num_frames, int((end - start) * video_fps)))
        step = (end - start) / max(n - 1, 1)
        return [
            {
                "input_index": k,
                "original_frame": int(round((start + k * step) * video_fps)),
                "timestamp": round(start + k * step, 6),
                "frame_path": f"frame_{k}.jpg",
            }
            for k in range(n)
        ]


class FakeClipBuilder:
    def build(self, source_video, sample_range, frames, video_fps, video_maxlen, sampling_strategy):
        return f"clip_{sample_range[0]}_{sample_range[1]}.mp4"


class FakeInferenceClient:
    def __init__(self, responses):
        self.responses = responses
        self.index = 0

    def infer(self, video_path, prompt):
        resp = self.responses[self.index]
        self.index = min(self.index + 1, len(self.responses) - 1)
        return resp


def make_config():
    return {
        "agent": {
            "tolerance_seconds": 1.0,
            "max_rounds": 5,
            "confidence_threshold": 0.5,
            "max_low_conf_rounds": 2,
            "video_fps": 8.0,
            "video_maxlen": 36,
            "temperature": 0.0,
        }
    }


def test_iterative_agent_terminates_on_converged_fracture():
    video_meta = {"video_id": "v001", "duration": 100.0, "video_path": "v001.mp4"}
    config = make_config()

    # First round: full range, model says fracture between frames 17-18 of 36.
    # With duration 100 and video_fps=8, effective frames = min(36, 800) = 36.
    # Timestamps are uniform: k * 100 / 35.  fracture_between [17,18] -> [48.57, 51.43].
    responses = [
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
            "has_fracture": True,
            "time_range": [48.571429, 51.428571],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
    assert result["location"] == "inside_gauge"
    assert result["rounds"] == 1
    assert result["confidence_level"] == "高"


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
            "has_fracture": False,
            "time_range": None,
            "time_estimate": None,
            "frame_range": None,
            "type": "未断裂",
            "location": None,
            "confidence": 0.95,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is False
    assert result["type"] == "未断裂"
    assert result["location"] is None
    assert result["time_range"] is None
    assert result["rounds"] == 2


def test_iterative_agent_rejects_early_terminate_until_converged():
    video_meta = {"video_id": "v003", "duration": 100.0, "video_path": "v003.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        # Round 0: sample full range.
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Round 1: LLM tries to terminate with a wide interval -> rejected.
        ("terminate", {
            "has_fracture": True,
            "time_range": [48.57, 51.43],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
        # Round 2: sample narrowed range and then terminate.
        ("sample_and_infer", {"sample_range": [48.57, 51.43], "prompt": "analyze"}),
        ("terminate", {
            "has_fracture": True,
            "time_range": [48.57, 51.43],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["rounds"] == 2


def test_iterative_agent_handles_parse_error():
    video_meta = {"video_id": "v005", "duration": 100.0, "video_path": "v005.mp4"}
    config = make_config()
    # Use a relaxed tolerance so the narrowed interval is considered converged.
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    # First response is a real parse failure: a non-JSON string.  The Agent
    # must record a non-empty parse_error and not crash.
    responses = [
        "this is not valid json",
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "has_fracture": True,
            "time_range": [48.571429, 51.428571],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # After parse errors, the agent eventually gets a valid positive result.
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
    # The first round must carry a parse_error description.
    assert result["history"][0]["result"]["parse_error"]
    assert "解析失败" in result["history"][0]["result"]["parse_error"]


def test_iterative_agent_rejects_boundary_sentinel_as_parse_error():
    """A boundary sentinel [0,0] / [N-1,N-1] is rejected as a strict-adjacency parse error."""
    video_meta = {"video_id": "v004", "duration": 100.0, "video_path": "v004.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4
    config["agent"]["tolerance_seconds"] = 5.0

    responses = [
        # Round 0: full range, valid fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.85},
        # Round 1: focused interval returns illegal boundary sentinel -> parse error.
        {"has_fracture": True, "fracture_between": [0, 0], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.85},
        # Round 2: focused interval returns valid left-edge adjacent pair.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.90},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "has_fracture": True,
            "time_range": [48.571429, 48.707484],
            "time_estimate": 48.6394565,
            "frame_range": [389, 390],
            "type": "脆性断裂",
            "location": "inside_gauge",
            "confidence": 0.90,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "脆性断裂"
    # Round 1 must carry a parse_error for the non-adjacent boundary sentinel.
    assert result["history"][1]["result"]["parse_error"]
    assert "严格相邻" in result["history"][1]["result"]["parse_error"]
    assert result["history"][1]["result"]["boundary_status"] == "none"
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
            "has_fracture": True,
            "time_range": [50.064935, 50.194805],
            "time_estimate": 50.12987,
            "frame_range": [401, 402],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
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
            "has_fracture": True,
            "time_range": [45.551027, 45.877558],
            "time_estimate": 45.714293,
            "frame_range": [364, 367],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
    assert result["history"][1]["result"].get("conflict_handled") == "expanded_candidate"


def test_iterative_agent_low_confidence_fallback():
    """Repeated low-confidence conflicts are discarded until fallback expansion."""
    video_meta = {"video_id": "v008", "duration": 100.0, "video_path": "v008.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5
    config["agent"]["confidence_threshold"] = 0.5

    responses = [
        # Round 0: full range, fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        # Round 1: low-confidence out-of-candidate result -> discarded.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.3},
        # Round 2: another low-confidence out-of-candidate result -> trigger fallback.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.3},
        # Round 3: expanded interval returns a converged normal interval.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [40.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [40.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [47.857143, 52.142857], "prompt": "analyze"}),
        ("terminate", {
            "has_fracture": True,
            "time_range": [50.064935, 50.194805],
            "time_estimate": 50.12987,
            "frame_range": [401, 402],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
    # Round 2 must record the low-confidence fallback expansion.
    assert result["history"][2]["result"].get("conflict_handled") == "discarded_low_confidence"
    assert result["history"][2]["result"].get("fallback") == "expanded_to_parent_range"


def test_iterative_agent_out_of_bounds_fracture_between():
    """An out-of-range fracture_between must become a parse_error, not an IndexError."""
    video_meta = {"video_id": "v009", "duration": 100.0, "video_path": "v009.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    responses = [
        # Round 0: model returns indices far beyond the sampled frames.
        {"has_fracture": True, "fracture_between": [100, 101], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        # Round 1: valid result.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "has_fracture": True,
            "time_range": [48.571429, 51.428571],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
    # The first round must carry an out-of-range parse_error and no interval.
    assert result["history"][0]["result"]["parse_error"]
    assert "超出采样帧索引范围" in result["history"][0]["result"]["parse_error"]
    assert result["history"][0]["result"]["inferred_time_range"] is None
    assert result["history"][0]["result"]["inferred_frame_range"] is None


def test_iterative_agent_inference_returns_none_is_parse_error():
    """If InferenceClient.infer returns None, the agent records a parse error."""
    video_meta = {"video_id": "v010", "duration": 100.0, "video_path": "v010.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    responses = [
        None,
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "has_fracture": True,
            "time_range": [48.571429, 51.428571],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"
    assert result["history"][0]["result"]["parse_error"]
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
    """LLM terminate args disagreeing with history must be overridden."""
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
            "has_fracture": True,
            "time_range": [48.571429, 51.428571],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is True
    assert result["type"] == "脆性断裂"
    # The output must come from the best (narrower) round, not the LLM terminate args.
    best_round = result["history"][1]["result"]
    assert result["time_range"] == best_round["inferred_time_range"]
    assert result["frame_range"] == best_round["inferred_frame_range"]
    assert result["time_range"] != [48.571429, 51.428571]


def test_no_fracture_terminate_rejects_invalid_type_and_high_confidence():
    """No-fracture termination with invalid type/high confidence must be sanitized."""
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
            "has_fracture": False,
            "time_range": None,
            "time_estimate": None,
            "frame_range": None,
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.95,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["has_fracture"] is False
    assert result["type"] == "未断裂"
    assert result["location"] is None
    assert result["time_range"] is None
    assert result["frame_range"] is None
    assert result["confidence_level"] != "高"


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
            "has_fracture": True,
            "time_range": [48.571429, 51.428571],
            "time_estimate": 50.0,
            "frame_range": [389, 411],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "confidence_level": "高",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
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
    assert "[48.571429, 51.428571]" in llm.calls[1][-1]["content"]

    # Third call must include the state context after round 1 (narrower candidate).
    assert len(llm.calls[2]) == 8
    assert llm.calls[2][-1]["role"] == "user"
    assert "当前候选区间" in llm.calls[2][-1]["content"]


def test_positive_without_inferred_range_fallback():
    """Positive round without inferred ranges falls back to LLM requested ranges or candidate.

    The fracture output must not be silently downgraded when the ranges can be recovered.
    """
    video_meta = {"video_id": "v201", "duration": 100.0, "video_path": "v201.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
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
                "frames": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": None,
                "inferred_frame_range": None,
            }
        }
    ]

    # Case 1: LLM requested ranges are available -> use them.
    requested_with_range = {
        "has_fracture": True,
        "time_range": [10.0, 20.0],
        "time_estimate": 15.0,
        "frame_range": [80, 160],
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
        "confidence_level": "高",
    }
    args = agent._build_fracture_args(positive_rounds, requested_with_range)
    assert args["has_fracture"] is True
    assert args["time_range"] == [10.0, 20.0]
    assert args["frame_range"] == [80, 160]
    assert args["type"] == "韧性断裂"

    # Case 2: No LLM requested ranges -> fall back to candidate for time_range.
    # Provide sampled frames that cover the full candidate so frame_range can be
    # recovered from the candidate time_range.
    positive_rounds[0]["result"]["frames"] = [
        {"timestamp": 0.0, "original_frame": 0},
        {"timestamp": 100.0, "original_frame": 800},
    ]
    requested_without_range = {
        "has_fracture": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
        "confidence_level": "高",
    }
    args = agent._build_fracture_args(positive_rounds, requested_without_range)
    assert args["has_fracture"] is True
    assert args["time_range"] == [0.0, 100.0]
    assert args["frame_range"] == [0, 800]

    # Case 3: Neither requested frame_range nor derivable frames -
    # downgrade explicitly instead of silently losing the fracture.
    positive_rounds[0]["result"]["frames"] = [
        {"timestamp": 10.0, "original_frame": 80},
        {"timestamp": 20.0, "original_frame": 160},
    ]
    args = agent._build_fracture_args(positive_rounds, requested_without_range)
    assert args["has_fracture"] is False
    assert args.get("downgrade_reason") == "frame_range_unrecoverable"


def test_build_fracture_args_all_invalid_types_fallback():
    """When all positive round types and the requested type are invalid, downgrade to no-fracture."""
    video_meta = {"video_id": "v202", "duration": 100.0, "video_path": "v202.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
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
                "frames": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": [10.0, 20.0],
                "inferred_frame_range": [80, 160],
            }
        }
    ]
    requested = {
        "has_fracture": True,
        "time_range": [10.0, 20.0],
        "time_estimate": 15.0,
        "frame_range": [80, 160],
        "type": "another_invalid_type",
        "location": "inside_gauge",
        "confidence": 0.92,
        "confidence_level": "高",
    }

    args = agent._build_fracture_args(positive_rounds, requested)
    assert args["has_fracture"] is False
    assert args["type"] in {"未断裂", "未夹紧", "视频异常"}
    assert args.get("downgrade_reason") is not None

    # _finalize must preserve the downgrade reason and output a valid no-fracture result.
    final = agent._finalize(args)
    assert final["has_fracture"] is False
    assert final["time_range"] is None
    assert final["frame_range"] is None
    assert "downgrade_reason" in final


def test_force_terminate_no_fracture_state_ignores_positive_history(caplog):
    """NO_FRACTURE state forces a no-fracture output even if history contains positive rounds.

    The log message must explain that this is intentional state-machine priority.
    """
    video_meta = {"video_id": "v203", "duration": 100.0, "video_path": "v203.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        sampler=FakeSampler(),
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

    assert result["has_fracture"] is False
    assert result["type"] == "未断裂"
    assert result["location"] is None
    assert "NO_FRACTURE" in caplog.text
    assert "state machine priority" in caplog.text
