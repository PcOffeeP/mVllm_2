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
    parse_response_payload,
    parse_seconds,
    parse_time_range,
    round_record_times,
    validate_fold,
    validate_prompt_preset,
    validate_task,
)
from config import (
    DEFAULT_VIDEO_ROOT,
    FRACTURE_CLASSES,
    GROUND_TRUTH_JSON,
    NON_FRACTURE_CLASSES,
    PROMPT_PRESETS,
    VIDEO_MAX_FRAMES,
)

logger = logging.getLogger(__name__)


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

    processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
    torch_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else "auto"
    model = AutoModelForImageTextToText.from_pretrained(
        model_dir,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        device_map="auto" if torch.cuda.is_available() else None,
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
    duration_sec: float | None = None,
    max_num_frames: int = VIDEO_MAX_FRAMES,
) -> list[float] | None:
    """Parse predicted time range from model payload.

    The new interval protocol (``has_fracture`` + ``fracture_between``) is
    preferred.  Frame indices are converted to seconds with the uniform
    sampling formula, assuming the processor samples ``max_num_frames`` frames
    uniformly across ``[0, duration_sec]``.  The actual frame sequence may
    differ depending on decoder/sampling strategy.  Legacy fields are kept as
    compatibility fallbacks.

    Within the new protocol, a zero-width interval is only accepted at the
    boundaries (``[0, 0]`` or ``[max_idx, max_idx]``); any other ``[k, k]``
    pair is rejected.
    """
    # New interval protocol.
    if payload is not None and payload.get("has_fracture") is True and duration_sec is not None:
        fracture_between = payload.get("fracture_between")
        if fracture_between is None:
            return None
        if isinstance(fracture_between, (list, tuple)) and len(fracture_between) == 2:
            try:
                start_idx = int(fracture_between[0])
                end_idx = int(fracture_between[1])
            except (TypeError, ValueError):
                start_idx = end_idx = None
            max_idx = max_num_frames - 1
            if start_idx is None or end_idx is None:
                return None
            if not (0 <= start_idx <= max_idx and 0 <= end_idx <= max_idx):
                return None
            if end_idx == start_idx + 1:
                # Adjacent frames form a non-empty interval.
                pass
            elif end_idx == start_idx and (start_idx == 0 or start_idx == max_idx):
                # Boundary zero-width sentinel only.
                pass
            else:
                return None
            if max_num_frames <= 1:
                return [0.0, round(duration_sec, 6)]
            # Uniform sampling assumption: k-th sampled frame is at
            # k * duration / (max_num_frames - 1).
            step = duration_sec / (max_num_frames - 1)
            return [round(start_idx * step, 6), round(end_idx * step, 6)]

    # Legacy interval fields compatibility.
    parsed: tuple[float, float] | None = None
    if payload is not None:
        for key in ("time_range", "time_range_sec", "time_interval"):
            value = payload.get(key)
            if value is not None:
                parsed = parse_time_range(value)
                if parsed is not None:
                    break
    if parsed is not None and math.isfinite(parsed[0]) and math.isfinite(parsed[1]):
        return [parsed[0], parsed[1]]

    # No explicit interval available; do not fabricate a placeholder window.
    return None


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
                    pass

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
            response_text = run_single_inference(model, processor, video_path, prompt)
            record["raw_output"] = response_text
            json_valid, payload = parse_response_payload(response_text)
            record["json_valid"] = json_valid
            if json_valid and payload is not None:
                record["pred_has_fracture"] = payload.get("has_fracture")
                record["pred_location"] = payload.get("location")
                record["pred_time_raw"] = payload.get("time")
                record["pred_time_sec"] = parse_seconds(payload.get("time"))

                # Resolve video duration only when the new interval protocol
                # may be used; old-protocol payloads fall back to legacy fields.
                duration_sec = None
                if "fracture_between" in payload or "has_fracture" in payload:
                    duration_sec = _get_video_duration(video_path)

                record["pred_time_range"] = _parse_pred_time_range(payload, duration_sec)
                record["pred_confidence_score"], record["pred_confidence_level"] = _parse_confidence(payload)
                record["pred_type_raw"] = payload.get("type")
                record["pred_type_norm"] = normalize_prediction_label(payload.get("type"))

                if record["pred_has_fracture"] is None:
                    pred_type = record["pred_type_norm"]
                    if pred_type in NON_FRACTURE_CLASSES:
                        record["pred_has_fracture"] = False
                    elif pred_type in FRACTURE_CLASSES or record["pred_time_sec"] is not None:
                        record["pred_has_fracture"] = True
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
