from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schema import (
    BoundaryStatus,
    ConfidenceLevel,
    FinalOutput,
    FractureType,
    LocationType,
    ModelOutput,
    SampleAndInferResult,
    SamplingStrategy,
    ToolSampleAndInfer,
    ToolTerminate,
)


def test_model_output_positive_serialization():
    output = ModelOutput(
        has_fracture=True,
        fracture_between=[17, 18],
        type=FractureType.TOUGH,
        location=LocationType.INSIDE,
        confidence=0.92,
    )
    data = output.model_dump()
    assert data["has_fracture"] is True
    assert data["fracture_between"] == [17, 18]
    assert data["type"] == "韧性断裂"
    assert data["location"] == "inside_gauge"
    assert data["confidence"] == pytest.approx(0.92)


def test_model_output_accepts_string_enums():
    output = ModelOutput(
        has_fracture=False,
        fracture_between=None,
        type="未断裂",
        location="N/A",
        confidence=0.95,
    )
    assert output.type == FractureType.NO_FRACTURE
    assert output.location == LocationType.NA


def test_model_output_rejects_invalid_type_for_fracture():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 18],
            type="未断裂",
            location=LocationType.INSIDE,
            confidence=0.92,
        )


def test_model_output_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 18],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=1.5,
        )


def test_model_output_rejects_bad_fracture_between_format():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 19],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=0.92,
        )


def test_has_fracture_false_constraints():
    positive = ModelOutput(
        has_fracture=False,
        fracture_between=None,
        type=FractureType.VIDEO_ABNORMAL,
        location=LocationType.NA,
        confidence=0.88,
    )
    assert positive.type == FractureType.VIDEO_ABNORMAL

    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=False,
            fracture_between=[0, 1],
            type=FractureType.NO_FRACTURE,
            location=LocationType.NA,
            confidence=0.88,
        )

    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=False,
            fracture_between=None,
            type=FractureType.TOUGH,
            location=LocationType.NA,
            confidence=0.88,
        )

    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=False,
            fracture_between=None,
            type=FractureType.NO_FRACTURE,
            location=LocationType.OUTSIDE,
            confidence=0.88,
        )


def test_tool_sample_and_infer_defaults():
    tool = ToolSampleAndInfer(
        sample_range=[0.0, 500.0],
        prompt="请分析视频",
    )
    assert tool.num_frames == 36
    assert tool.video_fps == pytest.approx(8.0)
    assert tool.sampling_strategy == SamplingStrategy.UNIFORM


def test_tool_terminate_positive():
    tool = ToolTerminate(
        has_fracture=True,
        time_range=[242.86, 257.14],
        time_estimate=250.0,
        frame_range=[7286, 7714],
        type=FractureType.TOUGH,
        location=LocationType.INSIDE,
        confidence=0.79,
        confidence_level=ConfidenceLevel.MEDIUM,
    )
    assert tool.confidence_level == ConfidenceLevel.MEDIUM


def test_tool_terminate_false_constraints():
    with pytest.raises(ValidationError):
        ToolTerminate(
            has_fracture=False,
            time_range=[242.86, 257.14],
            time_estimate=250.0,
            frame_range=[7286, 7714],
            type=FractureType.NO_FRACTURE,
            location=LocationType.NA,
            confidence=0.79,
            confidence_level=ConfidenceLevel.MEDIUM,
        )


def test_sample_and_infer_result():
    result = SampleAndInferResult(
        model_output={"has_fracture": True, "fracture_between": [17, 18]},
        frames=[{"input_index": 0, "original_frame": 4317, "timestamp": 143.9}],
        model_video_path="data/runtime/agent_clips/video_0001_round0.mp4",
        sample_range=[143.9, 146.9],
        video_fps=8.0,
        video_maxlen=36,
        num_sample_frames=24,
        sampling_strategy=SamplingStrategy.UNIFORM,
        boundary_status=BoundaryStatus.NONE,
        round_confidence_level=ConfidenceLevel.HIGH,
    )
    assert result.num_sample_frames == 24


def test_final_output_false_constraints():
    with pytest.raises(ValidationError):
        FinalOutput(
            video_id="video_0001",
            has_fracture=False,
            time_range=[242.86, 257.14],
            time_estimate=250.0,
            frame_range=[7286, 7714],
            type=FractureType.NO_FRACTURE,
            location=LocationType.NA,
            confidence=0.79,
            confidence_level=ConfidenceLevel.MEDIUM,
            rounds=1,
            history=[],
        )
