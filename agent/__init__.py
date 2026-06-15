"""Shared agent/model interface contract package."""

from __future__ import annotations

from agent.adapter import FOLD_ADAPTER_PATHS, get_adapter_path, list_supported_folds
from agent.inference import InferenceClient
from agent.parser import ResultParser
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from agent.sampling import (
    VideoClipBuilder,
    VideoSampler,
    fracture_between_to_frame_range,
    fracture_between_to_time_range,
    frame_to_time,
    is_boundary_sentinel,
    time_to_frame,
)
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


__version__ = "0.1.0"

__all__ = [
    "FOLD_ADAPTER_PATHS",
    "SYSTEM_PROMPT",
    "BoundaryStatus",
    "ConfidenceLevel",
    "FinalOutput",
    "FractureType",
    "InferenceClient",
    "LocationType",
    "ModelOutput",
    "ResultParser",
    "SampleAndInferResult",
    "SamplingStrategy",
    "ToolSampleAndInfer",
    "ToolTerminate",
    "VideoClipBuilder",
    "VideoSampler",
    "build_user_prompt",
    "fracture_between_to_frame_range",
    "fracture_between_to_time_range",
    "frame_to_time",
    "get_adapter_path",
    "is_boundary_sentinel",
    "list_supported_folds",
    "time_to_frame",
]
