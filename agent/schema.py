"""Pydantic models that formalize the model/agent interface contract.

See ``docs/architecture/model_agent_interface.md`` for the authoritative definitions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FractureType(StrEnum):
    """Fracture mode / anomaly class values allowed by the contract."""

    TOUGH = "韧性断裂"
    BRITTLE = "脆性断裂"
    INTERFACE_DEBOND = "界面脱粘"
    ROOT = "齐根断裂"
    EXPLOSIVE = "爆炸性断裂"
    MIXED = "半脆半韧断裂"
    INTERFACE_DEBOND_AND_ROOT = "界面脱粘、齐根断裂"
    NO_FRACTURE = "未断裂"
    NOT_CLAMPED = "未夹紧"
    VIDEO_ABNORMAL = "视频异常"


FRACTURE_CLASSES = {
    FractureType.TOUGH,
    FractureType.BRITTLE,
    FractureType.INTERFACE_DEBOND,
    FractureType.ROOT,
    FractureType.EXPLOSIVE,
    FractureType.MIXED,
    FractureType.INTERFACE_DEBOND_AND_ROOT,
}

NON_FRACTURE_CLASSES = {
    FractureType.NO_FRACTURE,
    FractureType.NOT_CLAMPED,
    FractureType.VIDEO_ABNORMAL,
}


class LocationType(StrEnum):
    """Gauge-length location judgment."""

    INSIDE = "inside_gauge"
    OUTSIDE = "outside_gauge"


class ConfidenceLevel(StrEnum):
    """Four-level confidence grading used by the Agent."""

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"
    UNTRUSTED = "不可信"


class BoundaryStatus(StrEnum):
    """Boundary sentinel status for a ``fracture_between`` prediction."""

    NONE = "none"
    LEFT_SENTINEL = "left_sentinel"
    RIGHT_SENTINEL = "right_sentinel"


class SamplingStrategy(StrEnum):
    """Sampling strategy requested by the Agent."""

    UNIFORM = "uniform"
    ADAPTIVE = "adaptive"


class ModelOutput(BaseModel):
    """Single-round model output JSON schema (section 2 of the contract)."""

    model_config = ConfigDict(use_enum_values=False)

    has_fracture: bool
    fracture_between: list[int] | None = None
    type: FractureType
    location: str | None
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_fracture_consistency(self) -> Self:
        if self.has_fracture:
            if self.fracture_between is None:
                raise ValueError("fracture_between is required when has_fracture is true")
            if len(self.fracture_between) != 2:
                raise ValueError("fracture_between must be a two-element list [i, i+1]")
            i, j = self.fracture_between
            if j != i + 1:
                raise ValueError("fracture_between must be strictly adjacent [i, i+1]")
            if self.type not in FRACTURE_CLASSES:
                raise ValueError(
                    f"type must be one of the 7 fracture classes when has_fracture is true, got {self.type}"
                )
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError(
                    f"location must be inside_gauge or outside_gauge when has_fracture is true, got {self.location}"
                )
        else:
            if self.fracture_between is not None:
                raise ValueError("fracture_between must be null when has_fracture is false")
            if self.type not in NON_FRACTURE_CLASSES:
                raise ValueError(
                    f"type must be one of 未断裂/未夹紧/视频异常 when has_fracture is false, got {self.type}"
                )
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is false")
        return self


class ToolSampleAndInfer(BaseModel):
    """Schema for the ``sample_and_infer`` tool (section 3)."""

    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    num_frames: int = Field(default=36, ge=1)
    video_fps: float = Field(default=8.0, gt=0.0)
    sampling_strategy: SamplingStrategy = Field(default=SamplingStrategy.UNIFORM)
    prompt: str
    expected_schema: dict[str, Any] | None = None


class ToolTerminate(BaseModel):
    """Schema for the ``terminate`` tool (section 4)."""

    has_fracture: bool
    time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    time_estimate: float | None = None
    frame_range: list[int] | None = Field(None, min_length=2, max_length=2)
    type: FractureType
    location: str | None
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel

    @model_validator(mode="after")
    def _validate_terminate_consistency(self) -> Self:
        if self.has_fracture:
            if self.time_range is None or self.time_estimate is None or self.frame_range is None:
                raise ValueError("time_range, time_estimate and frame_range are required when has_fracture is true")
            if self.type not in FRACTURE_CLASSES:
                raise ValueError("type must be a fracture class when has_fracture is true")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError(
                    f"location must be inside_gauge or outside_gauge when has_fracture is true, got {self.location}"
                )
        else:
            if self.time_range is not None or self.time_estimate is not None or self.frame_range is not None:
                raise ValueError("time_range, time_estimate and frame_range must be null when has_fracture is false")
            if self.type not in NON_FRACTURE_CLASSES:
                raise ValueError("type must be 未断裂/未夹紧/视频异常 when has_fracture is false")
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is false")
        return self


class SampleAndInferResult(BaseModel):
    """Structured result returned by the tool execution layer (section 5.3)."""

    model_output: dict[str, Any]
    frames: list[dict[str, Any]]
    model_video_path: str
    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    video_fps: float
    video_maxlen: int
    num_sample_frames: int
    sampling_strategy: SamplingStrategy
    inferred_time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    inferred_frame_range: list[int] | None = Field(None, min_length=2, max_length=2)
    boundary_status: BoundaryStatus
    parse_error: str | None = None
    round_confidence_level: ConfidenceLevel


class FinalOutput(BaseModel):
    """Final Agent output delivered to downstream consumers (section 7)."""

    video_id: str
    has_fracture: bool
    time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    time_estimate: float | None = None
    frame_range: list[int] | None = Field(None, min_length=2, max_length=2)
    type: FractureType
    location: str | None
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    rounds: int = Field(..., ge=0)
    history: list[dict[str, Any]]

    @model_validator(mode="after")
    def _validate_final_output_consistency(self) -> Self:
        if self.has_fracture:
            if self.time_range is None or self.time_estimate is None or self.frame_range is None:
                raise ValueError("time_range, time_estimate and frame_range are required when has_fracture is true")
            if self.type not in FRACTURE_CLASSES:
                raise ValueError("type must be a fracture class when has_fracture is true")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError(
                    f"location must be inside_gauge or outside_gauge when has_fracture is true, got {self.location}"
                )
        else:
            if self.time_range is not None or self.time_estimate is not None or self.frame_range is not None:
                raise ValueError("time_range, time_estimate and frame_range must be null when has_fracture is false")
            if self.type not in NON_FRACTURE_CLASSES:
                raise ValueError("type must be 未断裂/未夹紧/视频异常 when has_fracture is false")
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is false")
        return self
