from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from common import (
    build_prompt,
    ensure_parent_dir,
    get_default_model_dir,
    infer_failure_reason,
    load_fold_samples,
    load_ground_truth,
    normalize_prediction_label,
    parse_seconds,
    round_record_times,
    validate_fold,
    validate_prompt_preset,
    validate_task,
)
from config import (
    DEFAULT_VIDEO_ROOT,
    GROUND_TRUTH_JSON,
    PROMPT_PRESETS,
    VIDEO_MAX_FRAMES,
)
from pipeline.preprocessing import FrameMapping
from pipeline.preprocessing.minicpm_preprocessor import (
    MiniCPMVideoPreprocessor,
    configure_processor_max_frames,
)
from agent.parser import ResultParser

logger = logging.getLogger(__name__)


def _sanitize_model_path(model_path: str) -> str:
    """如果模型路径的目录名包含点号（会导致 trust_remote_code 模块导入失败），
    自动创建无点号的符号链接并返回新路径。如果链接已存在则复用。"""
    path = Path(model_path).resolve()
    dir_name = path.name
    if "." in dir_name or "-" in dir_name:
        safe_name = dir_name.replace(".", "_").replace("-", "_")
        safe_path = path.parent / safe_name
        if not safe_path.exists():
            safe_path.symlink_to(path, target_is_directory=True)
        return str(safe_path)
    return str(model_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MiniCPM inference for one task and one fold.")
    parser.add_argument("--task", required=True, choices=("time", "type", "joint"))
    parser.add_argument("--fold", required=True, type=int, choices=(0, 1, 2))
    parser.add_argument("--model-dir", default=None, help="Merged model directory. Defaults to the configured path for the fold.")
    parser.add_argument("--video-root", default=str(DEFAULT_VIDEO_ROOT), help="Root directory containing the videos.")
    parser.add_argument("--prompt-preset", default="strict", choices=PROMPT_PRESETS, help="Prompt strategy preset.")
    parser.add_argument("--output", required=True, help="JSONL output path.")
    parser.add_argument("--max-samples", type=int, default=None, help="Limit samples for a dry-run.")
    return parser.parse_args()


def load_model(model_dir: str) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    model_path = _sanitize_model_path(model_dir)
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    configure_processor_max_frames(processor)
    torch_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else "auto"
    model = AutoModelForImageTextToText.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        local_files_only=True,
    )
    if not torch.cuda.is_available():
        model = model.to(device="cpu")
    model.eval()
    return processor, model


def run_single_inference(model: Any, processor: Any, video_path: Path, prompt: str) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "video", "url": str(video_path.resolve())},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    downsample_mode = os.getenv("DOWNSAMPLE_MODE", "4x")
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        downsample_mode=downsample_mode,
        max_num_frames=VIDEO_MAX_FRAMES,
        stack_frames=1,
        max_slice_nums=1,
        use_image_id=False,
    ).to(model.device)
    generated_ids = model.generate(**inputs, downsample_mode=downsample_mode, max_new_tokens=512)
    generated_ids = [
        output_ids[len(input_ids) :] for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]
    return processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]


def _get_video_duration(video_path: Path) -> float | None:
    """Return the video duration in seconds using ffprobe, or None if unavailable."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        if math.isfinite(duration) and duration > 0:
            return duration
    except Exception:
        pass
    return None


def _parse_pred_time_range(
    payload: dict[str, Any] | None,
    sampled_frames: list[FrameMapping] | None = None,
) -> list[float] | None:
    """Map strict adjacent indices through actual processor frame metadata."""
    if payload is None or payload.get("has_fracture") is not True:
        return None
    fracture_between = payload.get("fracture_between")
    if (
        not isinstance(fracture_between, list)
        or len(fracture_between) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in fracture_between)
        or sampled_frames is None
    ):
        return None
    start_idx, end_idx = fracture_between
    if end_idx != start_idx + 1 or not (0 <= start_idx < end_idx < len(sampled_frames)):
        return None
    return [
        round(sampled_frames[start_idx].timestamp, 6),
        round(sampled_frames[end_idx].timestamp, 6),
    ]


def _map_confidence_level(score: float) -> str:
    """Map a numeric confidence score to the four-level grading."""
    if score >= 0.9:
        return "高"
    if score >= 0.7:
        return "中"
    if score >= 0.5:
        return "低"
    return "不可信"


def _parse_confidence(payload: dict[str, Any] | None) -> tuple[float, str]:
    """Parse confidence score/level from model payload.

    New protocol numeric ``confidence`` is preferred, followed by legacy
    ``confidence_score`` / ``final_confidence`` and string
    ``confidence_level``.  NaN/inf or out-of-range values trigger a warning
    and are sanitized to keep JSONL records finite.
    """
    score: float | None = None
    source: str | None = None
    if payload is not None:
        for key in ("confidence", "confidence_score", "final_confidence"):
            value = payload.get(key)
            if value is not None:
                try:
                    score = float(value)
                    source = key
                    break
                except (TypeError, ValueError):
                    logger.warning(
                        "Unparseable confidence value from '%s': %r, falling back to default",
                        key,
                        value,
                    )

        if score is not None:
            if not math.isfinite(score):
                logger.warning(
                    "Invalid confidence value from '%s': %r is not finite, falling back to 0.5",
                    source,
                    score,
                )
                score = 0.5
            elif score < 0.0 or score > 1.0:
                logger.warning(
                    "Confidence value from '%s' out of [0, 1]: %r, clipping",
                    source,
                    score,
                )
                score = max(0.0, min(1.0, score))

        if score is None:
            level = payload.get("confidence_level") or payload.get("confidence")
            if isinstance(level, str) and level in ("高", "中", "低", "不可信"):
                score = {"高": 0.9, "中": 0.6, "低": 0.3, "不可信": 0.25}[level]

    if score is None:
        score = 0.5
    return round(score, 6), _map_confidence_level(score)


_ALLOWED_LOCATIONS = {"inside_gauge", "outside_gauge", "N/A"}


def _parse_location(payload: dict[str, Any] | None) -> str | None:
    """Normalize model-reported location per the interface contract.

    Negative samples (``has_fracture=false``) must report ``"N/A"``.
    Any other value outside the allowed set is treated as unknown.
    """
    if payload is None:
        return None
    if payload.get("has_fracture") is False:
        return "N/A"
    location = payload.get("location")
    if location in _ALLOWED_LOCATIONS:
        return location
    return None


def main() -> None:
    args = parse_args()
    validate_task(args.task)
    validate_fold(args.fold)
    validate_prompt_preset(args.prompt_preset)

    gt_map = load_ground_truth(Path(GROUND_TRUTH_JSON))
    samples = load_fold_samples(args.fold, gt_map)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    model_dir = args.model_dir or get_default_model_dir(args.fold)
    resolved_prompt_preset, prompt = build_prompt(args.task, args.prompt_preset)
    video_root = Path(args.video_root)
    output_path = Path(args.output)
    ensure_parent_dir(output_path)

    if resolved_prompt_preset != args.prompt_preset:
        print(f"[info] task={args.task} does not support fewshot directly, fallback to prompt preset={resolved_prompt_preset}")

    processor, model = load_model(model_dir)
    frame_mapper = MiniCPMVideoPreprocessor(model_dir, processor=processor)
    records: list[dict[str, Any]] = []
    for sample in samples:
        video_path = video_root / sample["video_name"]
        record = {
            "fold": args.fold,
            "task": args.task,
            "video_id": sample["video_id"],
            "video_path": str(video_path),
            "model_dir": model_dir,
            "prompt_preset": resolved_prompt_preset,
            "prompt_text": prompt,
            "raw_output": "",
            "json_valid": False,
            "pred_time_raw": None,
            "pred_time_sec": None,
            "pred_time_range": None,
            "pred_confidence_score": None,
            "pred_confidence_level": None,
            "pred_has_fracture": None,
            "pred_location": None,
            "pred_type_raw": None,
            "pred_type_norm": None,
            "gt_time_sec": sample["gt_time_sec"],
            "gt_type": sample["gt_type"],
            "time_available": sample["time_available"],
            "material": sample["material"],
            "clarity": sample["clarity"],
            "failure_reason": None,
        }
        start = time.time()
        try:
            if not video_path.exists():
                raise RuntimeError(f"Video not found: {video_path}")
            duration_sec = _get_video_duration(video_path)
            if duration_sec is None:
                raise RuntimeError("Unable to determine video duration for actual frame mapping")
            sampled_frames = frame_mapper.sample(video_path.as_posix(), 0.0, duration_sec)
            record["preprocessing"] = {
                "processor_version": frame_mapper.get_info().version,
                "max_frames": frame_mapper.get_info().max_frames,
                "frames": [
                    {
                        "index": frame.input_index,
                        "original_frame": frame.original_frame,
                        "timestamp": frame.timestamp,
                    }
                    for frame in sampled_frames
                ],
            }
            response_text = run_single_inference(model, processor, video_path, prompt)
            record["raw_output"] = response_text
            parsed = ResultParser.parse(response_text)
            payload = parsed.data
            record["json_valid"] = parsed.ok
            if parsed.ok and payload is not None:
                record["pred_has_fracture"] = payload.get("has_fracture")
                record["pred_location"] = _parse_location(payload)
                record["pred_time_raw"] = payload.get("time")
                record["pred_time_sec"] = parse_seconds(payload.get("time"))

                record["pred_time_range"] = _parse_pred_time_range(payload, sampled_frames)
                record["pred_confidence_score"], record["pred_confidence_level"] = _parse_confidence(payload)
                record["pred_type_raw"] = payload.get("type")
                record["pred_type_norm"] = normalize_prediction_label(payload.get("type"))

        except Exception as exc:
            record["raw_output"] = str(exc)
            record["failure_reason"] = "model_inference_failed" if video_path.exists() else "video_load_failed"
        if record["pred_confidence_score"] is None:
            record["pred_confidence_score"], record["pred_confidence_level"] = _parse_confidence(None)
        record["elapsed_sec"] = round(time.time() - start, 6)
        if record["failure_reason"] is None:
            record["failure_reason"] = infer_failure_reason(record, args.task)
        records.append(round_record_times(record))
        print(
            f"[{args.task}] fold={args.fold} video={sample['video_name']} "
            f"json_valid={record['json_valid']} failure={record['failure_reason'] or 'ok'}"
        )

    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
