"""Pydantic models that formalize the model/agent interface contract.

See ``docs/IMPLEMENTATIONS/model-agent-contract.md`` for the authoritative
definitions. This module implements the v2 model output, tool schemas and
public result envelopes used by the iterative localization pipeline.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


FRACTURE_CLASSES: set[str] = {
    FractureType.TOUGH,
    FractureType.BRITTLE,
    FractureType.INTERFACE_DEBOND,
    FractureType.ROOT,
    FractureType.EXPLOSIVE,
    FractureType.MIXED,
    FractureType.INTERFACE_DEBOND_AND_ROOT,
}

NON_FRACTURE_CLASSES: set[str] = {
    FractureType.NO_FRACTURE,
    FractureType.NOT_CLAMPED,
}

ALL_MODEL_OUTPUT_TYPES: set[str] = FRACTURE_CLASSES | NON_FRACTURE_CLASSES | {FractureType.VIDEO_ABNORMAL}


class LocationType(StrEnum):
    """Gauge-length location judgment."""

    INSIDE = "inside_gauge"
    OUTSIDE = "outside_gauge"


# ---------------------------------------------------------------------------
# Legacy enums kept for backward-compatible imports. They are no longer used
# by ModelOutput or any public v2/v3 contract model.
# ---------------------------------------------------------------------------
class ConfidenceLevel(StrEnum):
    """Four-level confidence grading (legacy, retained for import stability)."""

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"
    UNTRUSTED = "不可信"


class BoundaryStatus(StrEnum):
    """Boundary sentinel status (legacy, retained for import stability)."""

    NONE = "none"
    LEFT_SENTINEL = "left_sentinel"
    RIGHT_SENTINEL = "right_sentinel"


class SamplingStrategy(StrEnum):
    """Sampling strategy requested by the Agent (legacy, retained for imports)."""

    UNIFORM = "uniform"
    ADAPTIVE = "adaptive"


# ---------------------------------------------------------------------------
# v2 model output
# ---------------------------------------------------------------------------
class ModelOutput(BaseModel):
    """Single-round fine-tuned model output JSON schema.

    The object always contains exactly the five fields below and must belong
    to one of the five legal combinations described in the contract.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    has_fracture: bool | None
    fracture_between: list[int] | None = None
    type: FractureType
    location: str | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _reject_bool_confidence(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("confidence must be a JSON number, not a boolean")
        return value

    @field_validator("fracture_between", mode="before")
    @classmethod
    def _reject_bool_indexes(cls, value: Any) -> Any:
        if isinstance(value, list) and any(isinstance(item, bool) for item in value):
            raise ValueError("fracture_between indexes must be integers, not booleans")
        return value

    @model_validator(mode="after")
    def _validate_five_legal_combinations(self) -> Self:
        # Combination 1: normal fracture with locatable boundary.
        if self.has_fracture is True and self.type in FRACTURE_CLASSES:
            if self.fracture_between is None:
                raise ValueError("fracture_between is required for a normal fracture prediction")
            if len(self.fracture_between) != 2:
                raise ValueError("fracture_between must contain exactly two integers [i, i+1]")
            i, j = self.fracture_between
            if j != i + 1 or i < 0:
                raise ValueError("fracture_between must be strictly adjacent [i, i+1] with i >= 0")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError(
                    "location must be inside_gauge or outside_gauge for a normal fracture prediction"
                )
            return self

        # Combination 5: video anomaly but fracture presence is confirmed.
        if self.has_fracture is True and self.type == FractureType.VIDEO_ABNORMAL:
            if self.fracture_between is not None:
                raise ValueError(
                    "fracture_between must be null for video anomaly with confirmed fracture"
                )
            if self.location is not None:
                raise ValueError("location must be null for video anomaly")
            return self

        # Combinations 2 & 3: confirmed no fracture / not clamped.
        if self.has_fracture is False:
            if self.fracture_between is not None:
                raise ValueError("fracture_between must be null when has_fracture is false")
            if self.type not in {FractureType.NO_FRACTURE, FractureType.NOT_CLAMPED}:
                raise ValueError(
                    "type must be 未断裂 or 未夹紧 when has_fracture is false, "
                    f"got {self.type}"
                )
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is false")
            return self

        # Combination 4: video anomaly, fracture presence unknown.
        if self.has_fracture is None:
            if self.fracture_between is not None:
                raise ValueError("fracture_between must be null when has_fracture is null")
            if self.type != FractureType.VIDEO_ABNORMAL:
                raise ValueError(
                    "type must be 视频异常 when has_fracture is null, "
                    f"got {self.type}"
                )
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is null")
            return self

        raise ValueError(f"illegal combination: has_fracture={self.has_fracture}, type={self.type}")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
class ToolSampleAndInfer(BaseModel):
    """Schema for the ``sample_and_infer`` tool (v2).

    The decision model may only provide the inspection interval and the
    complete user prompt. All sampling hyperparameters are removed from the
    public tool contract.
    """

    model_config = ConfigDict(extra="forbid")

    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    prompt: str = Field(..., min_length=1)


class ToolTerminate(BaseModel):
    """Schema for the ``terminate`` tool (v3).

    The decision model proposes a final status, the semantic fields and the
    evidence rounds that support the proposal. The program later derives the
    concrete ``time_range`` and validates the proposal against the evidence
    threshold rules.
    """

    model_config = ConfigDict(extra="forbid")

    status: str
    fracture_type: str | None = None
    location: str | None = None
    confidence: float | None = None
    unrecognized_reason: str | None = None
    evidence_rounds: list[int] | None = None

    @model_validator(mode="after")
    def _validate_status(self) -> Self:
        valid_statuses = {"fracture", "no_fracture", "unrecognized"}
        if self.status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}, got {self.status}")

        if self.status == "fracture":
            if self.fracture_type not in FRACTURE_CLASSES:
                raise ValueError("fracture_type must be one of the 7 fracture classes")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError("location must be inside_gauge or outside_gauge for fracture status")
            if self.confidence is None:
                raise ValueError("confidence is required for fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for fracture status")
            if not self.evidence_rounds:
                raise ValueError("evidence_rounds is required for fracture status")

        elif self.status == "no_fracture":
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for no_fracture status")
            if self.location is not None:
                raise ValueError("location must be null for no_fracture status")
            if self.confidence is None:
                raise ValueError("confidence is required for no_fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for no_fracture status")

        else:  # unrecognized
            if self.unrecognized_reason is None:
                raise ValueError("unrecognized_reason is required for unrecognized status")
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for unrecognized status")
            if self.location is not None:
                raise ValueError("location must be null for unrecognized status")
            if self.confidence is not None:
                raise ValueError("confidence must be null for unrecognized status")
            if self.evidence_rounds is not None:
                raise ValueError("evidence_rounds must be null for unrecognized status")

        return self


# ---------------------------------------------------------------------------
# Tool results and diagnostics
# ---------------------------------------------------------------------------
class ValidationErrorInfo(BaseModel):
    """Stable validation error object exposed to the decision model."""

    code: str
    message: str
    field: str | None = None


class SampleAndInferResult(BaseModel):
    """Compact tool result visible to the decision model (v2).

    This object deliberately excludes temporary paths, full frame tables and
    raw HTTP payloads. Those details live in ``SampleAndInferDiagnostics``.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    model_output: dict[str, Any] | None = None
    inferred_time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    validation_error: ValidationErrorInfo | None = None
    attempts: int = Field(..., ge=1, le=3)

    @model_validator(mode="after")
    def _validate_result_consistency(self) -> Self:
        if self.ok:
            if self.validation_error is not None:
                raise ValueError("validation_error must be null when ok is true")
        else:
            if self.model_output is not None:
                raise ValueError("model_output must be null when ok is false")
            if self.inferred_time_range is not None:
                raise ValueError("inferred_time_range must be null when ok is false")
            if self.validation_error is None:
                raise ValueError("validation_error is required when ok is false")
        return self


class SampleAndInferDiagnostics(BaseModel):
    """Internal diagnostics for a single ``sample_and_infer`` execution."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    processor_version: str | None = None
    video_maxlen: int | None = None
    sampled_frames: list[dict[str, Any]] | None = None
    temp_video_manifest: list[dict[str, Any]] | None = None
    internal_frame_range: list[int] | None = None
    temp_video_hash: str | None = None
    temp_video_bytes: int | None = None
    mime_type: str | None = None
    base64_length: int | None = None
    raw_http_response: dict[str, Any] | None = None
    transport_retries: int = 0
    correction_retries: int = 0
    elapsed_seconds: float | None = None
    error: ValidationErrorInfo | None = None


# ---------------------------------------------------------------------------
# Final public result and Runner envelope
# ---------------------------------------------------------------------------
class FinalOutput(BaseModel):
    """Final public result delivered to downstream consumers (v3)."""

    model_config = ConfigDict(extra="forbid")

    video_id: str
    status: str
    time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    fracture_type: str | None = None
    location: str | None = None
    confidence: float | None = None
    unrecognized_reason: str | None = None

    @model_validator(mode="after")
    def _validate_public_result(self) -> Self:
        valid_statuses = {"fracture", "no_fracture", "unrecognized"}
        if self.status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}, got {self.status}")

        if self.status == "fracture":
            if self.time_range is None:
                raise ValueError("time_range is required for fracture status")
            if self.fracture_type not in FRACTURE_CLASSES:
                raise ValueError("fracture_type must be one of the 7 fracture classes")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE, "unknown"}:
                raise ValueError("location must be inside_gauge, outside_gauge or unknown")
            if self.confidence is None:
                raise ValueError("confidence is required for fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for fracture status")

        elif self.status == "no_fracture":
            if self.time_range is not None:
                raise ValueError("time_range must be null for no_fracture status")
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for no_fracture status")
            if self.location is not None:
                raise ValueError("location must be null for no_fracture status")
            if self.confidence is None:
                raise ValueError("confidence is required for no_fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for no_fracture status")

        else:  # unrecognized
            if self.unrecognized_reason is None:
                raise ValueError("unrecognized_reason is required for unrecognized status")
            if self.time_range is not None:
                raise ValueError("time_range must be null for unrecognized status")
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for unrecognized status")
            if self.location is not None:
                raise ValueError("location must be null for unrecognized status")
            if self.confidence is not None:
                raise ValueError("confidence must be null for unrecognized status")

        return self


class RunnerError(BaseModel):
    """Structured Runner failure envelope."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    code: str
    message: str


class RunnerResult(BaseModel):
    """Runner execution envelope that separates success from infrastructure failure."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: FinalOutput | None = None
    error: RunnerError | None = None
