"""DEC-005 standalone frame-correspondence evidence extraction package."""
from __future__ import annotations

from .cli import main
from .evidence import (
    build_evidence_manifest,
    count_candidate_run_input_ids,
    count_candidate_runs,
    ensure_output_outside_git_repo,
    extract_evidence_bundle,
    render_index_markdown,
    validate_output_path,
)
from .extractor import (
    AutoFrameExtractor,
    FfmpegFrameExtractor,
    FrameExtractor,
    L3ImageResolution,
    MetadataOnlyExtractor,
    OpenCVFrameExtractor,
    build_extractor,
    resolve_l3_image,
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
    "L3ImageResolution",
    "MAPPING_DIRECTIONS",
    "MetadataOnlyExtractor",
    "OpenCVFrameExtractor",
    "PROOF_DISCLAIMERS",
    "PROOF_STRENGTH",
    "RUN_INDEX_SCHEMA",
    "build_evidence_manifest",
    "build_extractor",
    "count_candidate_run_input_ids",
    "count_candidate_runs",
    "ensure_output_outside_git_repo",
    "extract_evidence_bundle",
    "filter_records",
    "load_input_records",
    "load_roi_manifest",
    "load_subvideo_manifest",
    "main",
    "render_index_markdown",
    "resolve_l3_image",
    "validate_output_path",
]
