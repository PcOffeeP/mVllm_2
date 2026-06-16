"""Shared agent/model interface contract package."""

from __future__ import annotations

from agent.adapter import FOLD_ADAPTER_PATHS, get_adapter_path, list_supported_folds
from agent.inference import InferenceClient, LlamaFactoryInferenceClient, MockInferenceClient
from agent.iterative_agent import IterativeAgent, TOOLS_SCHEMA
from agent.llm import AgentLLMFactory, BaseAgentLLM, LocalClient, RemoteAPIClient
from agent.parser import ResultParser
from agent.prompts import (
    META_AGENT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_meta_agent_user_context,
    build_sample_and_infer_prompt,
    build_user_prompt,
)
from agent.sampling import (
    FfmpegVideoClipBuilder,
    UniformVideoSampler,
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
    "AgentLLMFactory",
    "BaseAgentLLM",
    "BoundaryStatus",
    "ConfidenceLevel",
    "FOLD_ADAPTER_PATHS",
    "FfmpegVideoClipBuilder",
    "FinalOutput",
    "FractureType",
    "InferenceClient",
    "IterativeAgent",
    "LocalClient",
    "LlamaFactoryInferenceClient",
    "LocationType",
    "META_AGENT_SYSTEM_PROMPT",
    "MockInferenceClient",
    "ModelOutput",
    "RemoteAPIClient",
    "ResultParser",
    "SampleAndInferResult",
    "SamplingStrategy",
    "SYSTEM_PROMPT",
    "ToolSampleAndInfer",
    "ToolTerminate",
    "TOOLS_SCHEMA",
    "UniformVideoSampler",
    "VideoClipBuilder",
    "VideoSampler",
    "build_meta_agent_user_context",
    "build_sample_and_infer_prompt",
    "build_user_prompt",
    "fracture_between_to_frame_range",
    "fracture_between_to_time_range",
    "frame_to_time",
    "get_adapter_path",
    "is_boundary_sentinel",
    "list_supported_folds",
    "time_to_frame",
]
