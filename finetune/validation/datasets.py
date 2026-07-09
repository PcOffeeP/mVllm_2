from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_VIDEO_ROOT,
    MERGED_DATA_DIR,
    SUPPORTED_DATASETS,
    TEST_GROUND_TRUTH_JSON,
    TEST_INPUTS_JSON,
    TEST_SUBVIDEO_GROUND_TRUTH_JSON,
    TEST_SUBVIDEO_INPUTS_JSON,
)
from .schema import unavailable


@dataclass(frozen=True)
class EvalSample:
    sample_id: str
    video_id: str
    video_path: Path
    target: dict[str, Any]
    metadata: dict[str, Any]


def load_dataset(name: str, video_root: Path | None = None) -> list[EvalSample]:
    if name == "test":
        return _load_test_dataset(TEST_INPUTS_JSON, TEST_GROUND_TRUTH_JSON, video_root)
    if name == "test_subvideos":
        return _load_test_dataset(TEST_SUBVIDEO_INPUTS_JSON, TEST_SUBVIDEO_GROUND_TRUTH_JSON, video_root)
    if name.startswith("fold_") and name.endswith("_val"):
        return _load_fold_dataset(name, video_root)
    raise ValueError(f"Unsupported dataset: {name}. Expected one of {SUPPORTED_DATASETS}.")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_video_path(raw_path: str | None, video_id: str, video_root: Path | None) -> Path:
    if raw_path:
        path = Path(raw_path)
    else:
        path = Path(f"{video_id}.mp4")
    if path.is_absolute():
        return path
    if str(path).startswith("data/"):
        return DEFAULT_VIDEO_ROOT.parents[1] / path
    return (video_root or DEFAULT_VIDEO_ROOT) / path


def _target_from_ground_truth(item: dict[str, Any]) -> dict[str, Any]:
    prediction_type = item.get("gt_type", item.get("type"))
    has_fracture = item.get("gt_has_fracture", item.get("has_fracture"))
    if prediction_type == "视频异常":
        has_fracture = None
    location = item.get("gt_location", item.get("location"))
    if location == "N/A":
        location = None
    return {
        "has_fracture": has_fracture,
        "fracture_between": item.get("gt_fracture_between", item.get("fracture_between", unavailable())),
        "type": prediction_type,
        "location": location,
        "confidence": unavailable(),
    }


def _load_test_dataset(inputs_path: Path, ground_truth_path: Path, video_root: Path | None) -> list[EvalSample]:
    inputs = _read_json(inputs_path)
    ground_truth = {item["video_id"]: item for item in _read_json(ground_truth_path)}
    samples: list[EvalSample] = []
    for item in inputs:
        video_id = item["video_id"]
        gt = ground_truth.get(video_id)
        if gt is None:
            raise ValueError(f"Missing ground truth for {video_id} in {ground_truth_path}")
        samples.append(
            EvalSample(
                sample_id=item.get("id", video_id),
                video_id=video_id,
                video_path=_resolve_video_path(item.get("video_path"), video_id, video_root),
                target=_target_from_ground_truth(gt),
                metadata={
                    "source_video_id": item.get("source_video_id") or gt.get("source_video_id"),
                    "subvideo_id": item.get("subvideo_id") or gt.get("subvideo_id"),
                    "crop_type": item.get("crop_type") or gt.get("crop_type"),
                    "frame_mapping": item.get("frame_mapping"),
                    "processor_fingerprint": item.get("processor_fingerprint"),
                },
            )
        )
    return samples


def _load_fold_dataset(name: str, video_root: Path | None) -> list[EvalSample]:
    path = MERGED_DATA_DIR / f"{name}.json"
    records = _read_json(path)
    samples: list[EvalSample] = []
    for index, record in enumerate(records):
        raw_video = record.get("videos", [None])[0]
        assistant_message = _assistant_content(record)
        target = json.loads(assistant_message)
        video_path = _resolve_video_path(raw_video, Path(raw_video or f"sample_{index}").stem, video_root)
        video_id = video_path.stem
        samples.append(
            EvalSample(
                sample_id=video_id,
                video_id=video_id,
                video_path=video_path,
                target={**target, "confidence": unavailable()},
                metadata={"source": str(path), "row_index": index},
            )
        )
    return samples


def _assistant_content(record: dict[str, Any]) -> str:
    for message in record.get("messages", []):
        if message.get("role") == "assistant":
            return str(message.get("content", ""))
    raise ValueError(f"Training-format record has no assistant target: {record!r}")
