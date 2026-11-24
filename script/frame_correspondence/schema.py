"""Schema constants, DEC-005 proof-boundary definitions, and error types."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from script.five_label_eval.frames import (
    LEGACY_MAPPING_KEYS,
    MAPPING_NODE_KEYS,
    RECORD_SCHEMA,
)

EVIDENCE_SCHEMA = "frame-correspondence-evidence/1"
RUN_INDEX_SCHEMA = "frame-correspondence-run-index/1"
EXPECTED_INPUT_RECORD_SCHEMA = RECORD_SCHEMA

PROOF_STRENGTH = "manual_visual_evidence_only"

# Strictly aligned with docs/eval/input-record.md §10 (five-label-input-record/3).
MAPPING_DIRECTIONS: dict[str, str] = {
    "clip_to_model_input": "L2->L3",
    "clip_to_roi": "L2->L1",
    "roi_to_original": "L1->L0",
}

# Legacy v2 keys plus reversed/deprecated names that must be explicitly rejected.
FORBIDDEN_MAPPING_KEYS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *LEGACY_MAPPING_KEYS,
            "original_to_roi",
            "roi_to_clip",
            "model_input_to_clip",
            "source_to_roi",
        )
    )
)

FORBIDDEN_FRAME_KEYS: tuple[str, ...] = ("source_frame_index",)

# DEC-005 disclaimers rendered in both machine-readable manifest and human index.md.
PROOF_DISCLAIMERS: tuple[str, ...] = (
    "本产物仅为按次人工可查视觉证据，不构成帧级重放通过，不得表述为「已验证帧对应」。",
    "本产物与 full 收据（机器证明）互不替代；不做像素比对、不做自动相似度判定、不由 Agent 判「像不像」。",
    "导出画面只反映按记录抽取的帧图像，不还原模型内部视觉编码、切片或张量布局。",
)

ExtractionStatus = Literal["extracted", "copied", "skipped", "metadata_only"]


class EvidenceError(Exception):
    """Raised when input records, manifests, filters, or output paths fail validation."""


@dataclass(frozen=True)
class FrameExtractionResult:
    """Structured outcome of attempting to materialize one layer's frame image."""

    status: ExtractionStatus
    output_path: Path | None = None
    pts_seconds: float | None = None
    image_sha256: str | None = None
    backend: str | None = None
    skip_reason: str | None = None
