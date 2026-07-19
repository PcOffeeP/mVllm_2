from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_VIDEO_ROOT,
    SUPPORTED_DATASETS,
    TEST_GROUND_TRUTH_JSON,
    TEST_INPUTS_JSON,
    TEST_SUBVIDEO_GROUND_TRUTH_JSON,
    TEST_SUBVIDEO_INPUTS_JSON,
    VALIDATION_DATA_DIR,
)


@dataclass(frozen=True)
class EvalSample:
    sample_id: str
    video_id: str
    video_path: Path
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
        "fracture_between": item.get("gt_fracture_between", item.get("fracture_between")),
        "type": prediction_type,
        "location": location,
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
                metadata={
                    "ground_truth": _target_from_ground_truth(gt),
                    "source_video_id": item.get("source_video_id") or gt.get("source_video_id"),
                    "subvideo_id": item.get("subvideo_id") or gt.get("subvideo_id"),
                    "crop_type": item.get("crop_type") or gt.get("crop_type"),
                    "start_time": item.get("start_time", gt.get("start_time")),
                    "end_time": item.get("end_time", gt.get("end_time")),
                    "event_time": gt.get("gt_event_time", gt.get("event_time")),
                    "frame_mapping": item.get("frame_mapping"),
                    "processor_fingerprint": item.get("processor_fingerprint"),
                },
            )
        )
    return samples


def _parse_assistant_json(assistant_message: str) -> dict[str, Any]:
    """Parse assistant target from training sample.

    Supports the new format ``判断依据：...\n结果：{...}`` by extracting the JSON
    after ``结果：``. Falls back to parsing the whole message as JSON for legacy
    samples that only contain the JSON object.
    """
    content = assistant_message.strip()
    if "结果：" in content:
        json_part = content.split("结果：", 1)[1].strip()
        try:
            return json.loads(json_part)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Assistant result section is not valid JSON: {exc}\n"
                f"Content after '结果：': {json_part[:500]}"
            ) from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Assistant message does not contain '结果：' and is not valid JSON: {exc}\n"
            f"Content: {content[:500]}"
        ) from exc


def _load_fold_dataset(name: str, video_root: Path | None) -> list[EvalSample]:
    fold_match = re.fullmatch(r"fold_(\d+)_val", name)
    if fold_match is None:
        raise ValueError(f"Invalid validation dataset name: {name}")
    path = VALIDATION_DATA_DIR / f"fold_{fold_match.group(1)}.json"
    records = _read_json(path)
    samples: list[EvalSample] = []
    for index, record in enumerate(records):
        raw_video = record.get("videos", [None])[0]
        assistant_message = _assistant_content(record)
        assistant_json = _parse_assistant_json(assistant_message)
        video_path = _resolve_video_path(raw_video, Path(raw_video or f"sample_{index}").stem, video_root)
        video_id = video_path.stem
        source_match = re.match(r"(video_\d+)", video_id)
        source_video_id = source_match.group(1) if source_match else None
        samples.append(
            EvalSample(
                sample_id=video_id,
                video_id=video_id,
                video_path=video_path,
                metadata={
                    "source": str(path),
                    "row_index": index,
                    "source_video_id": source_video_id,
                    "subvideo_id": video_id,
                    "ground_truth": assistant_json,
                    "assistant_raw": assistant_message,
                    "assistant_json": assistant_json,
                },
            )
        )
    return samples


def _assistant_content(record: dict[str, Any]) -> str:
    for message in record.get("messages", []):
        if message.get("role") == "assistant":
            return str(message.get("content", ""))
    raise ValueError(f"Training-format record has no assistant target: {record!r}")
