"""DEC-005 standalone frame-correspondence evidence extraction package."""
from __future__ import annotations

from .cli import main
from .evidence import (
    build_evidence_manifest,
    ensure_output_outside_git_repo,
    extract_evidence_bundle,
    render_index_markdown,
)
from .extractor import (
    AutoFrameExtractor,
    FfmpegFrameExtractor,
    FrameExtractor,
    MetadataOnlyExtractor,
    OpenCVFrameExtractor,
    build_extractor,
)
from .loader import (
    filter_records,
    load_input_records,
    load_roi_manifest,
    load_subvideo_manifest,
)
from .schema import (
    EVIDENCE_SCHEMA,
    EXPECTED_INPUT_RECORD_SCHEMA,
    MAPPING_DIRECTIONS,
    PROOF_DISCLAIMERS,
    PROOF_STRENGTH,
    RUN_INDEX_SCHEMA,
    EvidenceError,
    FrameExtractionResult,
)

__all__ = [
    "AutoFrameExtractor",
    "EVIDENCE_SCHEMA",
    "EXPECTED_INPUT_RECORD_SCHEMA",
    "EvidenceError",
    "FfmpegFrameExtractor",
    "FrameExtractionResult",
    "FrameExtractor",
    "MAPPING_DIRECTIONS",
    "MetadataOnlyExtractor",
    "OpenCVFrameExtractor",
    "PROOF_DISCLAIMERS",
    "PROOF_STRENGTH",
    "RUN_INDEX_SCHEMA",
    "build_evidence_manifest",
    "build_extractor",
    "ensure_output_outside_git_repo",
    "extract_evidence_bundle",
    "filter_records",
    "load_input_records",
    "load_roi_manifest",
    "load_subvideo_manifest",
    "main",
    "render_index_markdown",
]
