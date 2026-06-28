from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, List, Tuple

from .common import (
    build_prompt,
    ensure_parent_dir,
    generate_frame_mapping,
    get_default_model_dir,
    infer_failure_reason,
    load_fold_samples,
    load_ground_truth,
    load_test_split_samples,
    load_test_inputs,
    load_test_ground_truth,
    load_video_metadata,
    normalize_prediction_label,
    parse_response_payload,
    parse_seconds,
    round_record_times,
    validate_interval_schema,
    validate_fold,
    validate_prompt_preset,
    validate_task,
)
from .config import (
    BASE_MODEL_DIR,
    DEFAULT_VIDEO_ROOT,
    GROUND_TRUTH_JSON,
    PROMPT_PRESETS,
    SUBVIDEOS_META_JSON,
    SUPPORTED_SPLITS,
    TEST_INPUTS_JSON,
    TEST_GROUND_TRUTH_JSON,
    VIDEO_MAX_FRAMES,
)
from pipeline.preprocessing.minicpm_preprocessor import configure_processor_max_frames

logger = logging.getLogger(__name__)

DEFAULT_GENERATION_CONFIG = {
    "do_sample": False,
    "num_beams": 1,
    "max_new_tokens": 256,
    "temperature": None,
    "top_p": None,
}


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
    parser = argparse.ArgumentParser(description="Run MiniCPM inference for evaluation.")
    parser.add_argument("--task", required=True, choices=("time", "type", "joint"))
    parser.add_argument("--fold", type=int, default=None, choices=(0, 1, 2), help="Fold number (0, 1, 2). Use --split instead for test.")
    parser.add_argument("--split", default=None, choices=SUPPORTED_SPLITS, help="Split name: fold_0_val, fold_1_val, fold_2_val, test. Overrides --fold when set.")
    parser.add_argument("--model-dir", default=None, help="Merged model directory. Defaults to configured path for the fold.")
    parser.add_argument("--model-name", default=None, help="Model name to embed in output records. Defaults to directory basename.")
    parser.add_argument("--video-root", default=str(DEFAULT_VIDEO_ROOT), help="Root directory containing the videos.")
    parser.add_argument("--prompt-preset", default="strict", choices=PROMPT_PRESETS, help="Prompt strategy preset.")
    parser.add_argument("--output", required=True, help="JSONL output path.")
    parser.add_argument("--max-samples", type=int, default=None, help="Limit samples for a dry-run.")
    return parser.parse_args()


def load_model(model_dir: str) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModel, AutoProcessor, AutoTokenizer, AutoImageProcessor
    from pathlib import Path

    model_path = _sanitize_model_path(model_dir)
    base_path = Path(BASE_MODEL_DIR)

    # Load processor components explicitly to ensure tokenizer is properly initialized
    processor_path = str(base_path) if base_path.exists() else model_path
    if base_path.exists():
        logger.info("Loading processor from base model: %s", base_path)
    
    # Load tokenizer and image_processor separately with trust_remote_code
    tokenizer = AutoTokenizer.from_pretrained(
        processor_path, trust_remote_code=True, local_files_only=True
    )
    image_processor = AutoImageProcessor.from_pretrained(
        processor_path, trust_remote_code=True, local_files_only=True
    )
    # Load processor for configuration
    processor = AutoProcessor.from_pretrained(
        processor_path, trust_remote_code=True, local_files_only=True
    )
    # Explicitly set tokenizer on processor (ensures it's properly initialized)
    processor.tokenizer = tokenizer
    
    configure_processor_max_frames(processor)

    # Set chat_template from tokenizer (always available, no .jinja file needed)
    if getattr(processor, "chat_template", None) is None and tokenizer.chat_template is not None:
        processor.chat_template = tokenizer.chat_template

    # Load model weights from merged model directory
    torch_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else "auto"
    model = AutoModel.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        device_map="auto",
        low_cpu_mem_usage=True,
    ).eval()

    # Monkey-patch: MiniCPM's _decode passes kwargs to self.llm.generate(),
    # which rejects non-standard keys from processor output.
    # Pop all processor keys except input_ids / attention_mask / pixel_values.
    original_decode = model._decode
    def _patched_decode(*args, **kwargs):
        for key in ["image_sizes", "temporal_ids", "image_bound", "tgt_sizes"]:
            kwargs.pop(key, None)
        return original_decode(*args, **kwargs)
    model._decode = _patched_decode

    return processor, model


def run_single_inference(model: Any, processor: Any, video_path: Path, prompt: str) -> Tuple[str, List[float]]:
    """Run inference on a single video sample.

    Returns:
        Tuple of (response_text, frame_timestamps):
          - response_text: raw decoded text from model
          - frame_timestamps: PTS timestamps of the sampled video frames
    """
    from .video_loader import load_video_frames
    import torch

    # Step 1: Load video frames as PIL Images + actual timestamps
    frames, temporal_ids, frame_timestamps = load_video_frames(str(video_path), max_frames=VIDEO_MAX_FRAMES)

    # Step 2: Build message with <image> placeholders (one per frame)
    image_tags = "".join("(<image>./</image>)" for _ in frames)
    content_str = f"{image_tags}\n{prompt}"
    messages = [{"role": "user", "content": content_str}]

    # Step 3: Render chat template (text only, no tokenization)
    prompt_text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    # Step 4: Processor encodes text + images together
    inputs = processor(
        text=prompt_text,
        images=frames,
        temporal_ids=temporal_ids,
        max_slice_nums=1,
        use_image_id=False,
        return_tensors="pt",
    ).to(model.device)

    # Step 5: Generate with torch.no_grad()
    inputs.pop("image_sizes", None)  # 必须在 generate 前弹出，与 chat() L437 一致
    gen_cfg = DEFAULT_GENERATION_CONFIG
    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            tokenizer=processor.tokenizer,  # 新增：显式传入 tokenizer
            do_sample=gen_cfg["do_sample"],
            num_beams=gen_cfg["num_beams"],
            max_new_tokens=gen_cfg["max_new_tokens"],
        )
    generated_ids = [
        output_ids[len(input_ids):]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]
    response_text = processor.batch_decode(
        generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0]

    return response_text, frame_timestamps


def _parse_pred_time_range(
    payload: dict[str, Any] | None,
    sampled_frames: list[dict] | None = None,
) -> list[int] | None:
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
    return [start_idx, end_idx]


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


def _load_full_frame_mappings(meta_path: Path) -> dict[str, list[dict[str, Any]]]:
    """从 subvideos_meta.json 加载所有 full video 的帧映射。
    
    返回 {source_video: frames_list} 索引，其中每条 frame 为：
    {"index": int, "original_frame": int, "timestamp": float}
    """
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    full_videos: dict[str, list[dict[str, Any]]] = {}
    for entry in data.get("subvideos", []):
        if entry.get("crop_type", "").startswith("full"):
            source = entry["source_video"]
            mapping = entry.get("actual_frame_mapping") or entry.get("sampled_frames", [])
            # 重命名 input_index → index，兼容下游 _resolve_frame_indices_to_time_range
            frames = [
                {
                    "index": f["input_index"],
                    "original_frame": f["original_frame"],
                    "timestamp": f["timestamp"],
                }
                for f in mapping
            ]
            full_videos[source] = frames
    return full_videos


def _map_fracture_between_to_time_sec(
    fracture_between: list[int] | None,
    sampled_frames: list[dict],
) -> tuple[float, float] | None:
    """Map fracture_between frame indices [i, i+1] to actual time range in seconds.
    
    Uses the frame mapping's timestamps. Returns (start_sec, end_sec) or None.
    """
    if not isinstance(fracture_between, list) or len(fracture_between) != 2:
        return None
    start_idx, end_idx = fracture_between
    if not (isinstance(start_idx, int) and isinstance(end_idx, int)):
        return None

    start_frame = next((f for f in sampled_frames if f.get("index") == start_idx), None)
    end_frame = next((f for f in sampled_frames if f.get("index") == end_idx), None)
    if start_frame is None or end_frame is None:
        return None

    start_ts = start_frame.get("timestamp")
    end_ts = end_frame.get("timestamp")
    if start_ts is None or end_ts is None:
        return None

    try:
        low = float(start_ts)
        high = float(end_ts)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(low) or not math.isfinite(high):
        return None
    if low > high:
        low, high = high, low
    return (low, high)


def main() -> None:
    args = parse_args()
    validate_task(args.task)
    validate_prompt_preset(args.prompt_preset)

    # Resolve split
    split = args.split
    fold = args.fold
    if split is None and fold is None:
        parser = argparse.ArgumentParser()
        parser.error("Either --split or --fold must be provided.")
    if split is not None:
        # Derive fold from split name if applicable
        if split.startswith("fold_") and split.endswith("_val"):
            fold = int(split.split("_")[1])
        else:
            fold = None
    elif fold is not None:
        split = f"fold_{fold}_val"
        validate_fold(fold)

    # Load samples based on split
    if split == "test":
        samples = load_test_split_samples()
    else:
        # fold_*_val split
        gt_map = load_ground_truth(Path(GROUND_TRUTH_JSON))
        samples = load_fold_samples(fold, gt_map)

    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    # Resolve model
    model_dir = args.model_dir or (get_default_model_dir(fold) if fold is not None else None)
    if model_dir is None:
        raise ValueError("--model-dir required for test split (no default fold).")

    model_name = args.model_name or Path(model_dir).name

    # Build prompt
    resolved_prompt_preset, prompt = build_prompt(args.task, args.prompt_preset)
    video_root = Path(args.video_root)
    output_path = Path(args.output)
    ensure_parent_dir(output_path)

    if resolved_prompt_preset != args.prompt_preset:
        print(f"[info] task={args.task} does not support fewshot directly, fallback to prompt preset={resolved_prompt_preset}")

    full_mappings = _load_full_frame_mappings(SUBVIDEOS_META_JSON)
    print(f"[info] loaded {len(full_mappings)} full video frame mappings from subvideos_meta.json")

    # Fill missing frame mappings from CSV metadata
    missing_mapping = [s.get("video_id") for s in samples if s.get("video_id") not in full_mappings]
    if missing_mapping:
        video_meta = load_video_metadata()
        generated = 0
        for vid in missing_mapping:
            if vid in video_meta:
                fm = generate_frame_mapping(video_meta[vid]["total_frames"], video_meta[vid]["fps"])
                full_mappings[vid] = fm
                generated += 1
        still_missing = len(missing_mapping) - generated
        if generated > 0:
            print(f"[info] generated {generated} frame mapping(s) from CSV metadata (total_frames + fps)")
        if still_missing > 0:
            print(f"[warn] {still_missing}/{len(samples)} videos still have no frame mapping. "
                  f"Interval metrics will be unavailable for these videos.")

    processor, model = load_model(model_dir)
    records: list[dict[str, Any]] = []

    for sample in samples:
        video_id = sample["video_id"]
        video_path = video_root / sample["video_name"]

        # Build record with ALL required fields (see specification)
        record = {
            "model_name": model_name,
            "model_dir": model_dir,
            "split": split,
            "fold": fold,
            "task": args.task,
            "prompt_preset": resolved_prompt_preset,
            "prompt_text": prompt,
            "generation_config": dict(DEFAULT_GENERATION_CONFIG),
            "video_id": video_id,
            "video_path": str(video_path),
            "raw_output": "",
            "json_valid": False,
            "schema_valid": False,
            "schema_errors": None,
            "pred_has_fracture": None,
            "pred_fracture_between": None,
            "pred_type_raw": None,
            "pred_type_norm": None,
            "pred_location": None,
            "pred_confidence_score": None,
            "pred_time_range_sec": None,
            "pred_time_range": None,  # Legacy compat
            "pred_time_midpoint_sec": None,
            # GT fields
            "gt_has_fracture": sample.get("gt_has_fracture"),
            "gt_fracture_between": None,  # Not available at video level
            "gt_type": sample.get("gt_type"),
            "gt_location": sample.get("gt_location"),
            "gt_time_sec": sample.get("gt_time_sec"),
            "time_available": sample.get("time_available", False),
            # Preprocessing
            "preprocessing": None,
            # Legacy fields for backward compat
            "pred_time_raw": None,
            "pred_time_sec": None,
            "pred_confidence_level": None,
            "elapsed_sec": 0.0,
            "failure_reason": None,
        }

        start = time.time()
        try:
            if not video_path.exists():
                raise RuntimeError(f"Video not found: {video_path}")

            # Get frame mapping
            sampled_frames = full_mappings.get(video_id)
            if sampled_frames is None:
                record["failure_reason"] = "frame_mapping_missing"
                record["preprocessing"] = {"max_frames": VIDEO_MAX_FRAMES, "frames": [], "frame_mapping_missing": True}
            else:
                record["preprocessing"] = {
                    "max_frames": len(sampled_frames),
                    "frames": sampled_frames,
                    "processor_fingerprint": "subvideos_meta_full",
                }

            response_text, actual_timestamps = run_single_inference(model, processor, video_path, prompt)
            record["raw_output"] = response_text
            record["preprocessing"]["actual_timestamps"] = actual_timestamps

            json_valid, payload = parse_response_payload(response_text)
            record["json_valid"] = json_valid

            if json_valid and payload is not None:
                # Parse all 5 interval fields
                record["pred_has_fracture"] = payload.get("has_fracture")
                record["pred_fracture_between"] = payload.get("fracture_between")
                record["pred_type_raw"] = payload.get("type")
                record["pred_type_norm"] = normalize_prediction_label(payload.get("type"))
                record["pred_location"] = payload.get("location")

                # Parse confidence
                conf = payload.get("confidence")
                if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                    if 0.0 <= conf <= 1.0:
                        record["pred_confidence_score"] = round(float(conf), 6)

                # Validate against interval schema
                schema_valid, schema_errors = validate_interval_schema(payload)
                record["schema_valid"] = schema_valid
                record["schema_errors"] = "; ".join(schema_errors) if schema_errors else None

                # Compute time range and midpoint from fracture_between + actual timestamps
                # Only derive if schema_valid, otherwise the prediction is not reliable
                if (
                    schema_valid
                    and record["pred_fracture_between"] is not None
                    and len(actual_timestamps) > 0
                ):
                    fb = record["pred_fracture_between"]
                    if (
                        isinstance(fb, list)
                        and len(fb) == 2
                        and isinstance(fb[0], int)
                        and isinstance(fb[1], int)
                        and 0 <= fb[0] < len(actual_timestamps)
                        and 0 <= fb[1] <= len(actual_timestamps)
                    ):
                        low = actual_timestamps[fb[0]]
                        high = actual_timestamps[fb[1]]
                        record["pred_time_range_sec"] = [low, high]
                        record["pred_time_range"] = [low, high]  # Legacy compat
                        record["pred_time_midpoint_sec"] = round((low + high) / 2, 6)

                # Legacy time field for backward compat
                record["pred_time_raw"] = payload.get("time")
                record["pred_time_sec"] = parse_seconds(payload.get("time"))

                # Confidence level
                conf_score = record.get("pred_confidence_score")
                if conf_score is not None:
                    if conf_score >= 0.9:
                        record["pred_confidence_level"] = "高"
                    elif conf_score >= 0.7:
                        record["pred_confidence_level"] = "中"
                    elif conf_score >= 0.5:
                        record["pred_confidence_level"] = "低"
                    else:
                        record["pred_confidence_level"] = "不可信"

        except Exception as exc:
            import traceback
            traceback.print_exc()
            record["raw_output"] = str(exc)
            record["failure_reason"] = "model_inference_failed" if video_path.exists() else "video_load_failed"

        record["elapsed_sec"] = round(time.time() - start, 6)
        if record["failure_reason"] is None:
            record["failure_reason"] = infer_failure_reason(record, args.task)
        records.append(round_record_times(record))

        print(
            f"[{args.task}] split={split} video={sample['video_name']} "
            f"json_valid={record['json_valid']} schema_valid={record['schema_valid']} "
            f"failure={record['failure_reason'] or 'ok'}"
        )

    # 结果文件路径
    results_path = output_path.parent / (output_path.stem + "_results.jsonl")

    with output_path.open("w", encoding="utf-8") as meta_f, results_path.open("w", encoding="utf-8") as res_f:
        for record in records:
            # 结果记录：video_id + 所有 pred_* + raw_output
            results_record = {
                "video_id": record.get("video_id"),
                "raw_output": record.get("raw_output"),
            }
            for k, v in record.items():
                if k.startswith("pred_") or k.startswith("confidence_"):
                    results_record[k] = v
            # 也对 "pred_time_range" 等非 pred_ 前缀的结果字段做处理
            for alt_field in ["pred_time_range", "pred_time_sec", "pred_time_raw"]:
                if alt_field in record:
                    results_record[alt_field] = record[alt_field]

            # 元信息记录：除结果字段外的所有字段
            meta_record = {k: v for k, v in record.items() if k not in results_record}
            meta_record["video_id"] = record.get("video_id")

            meta_f.write(json.dumps(meta_record, ensure_ascii=False, allow_nan=False) + "\n")
            res_f.write(json.dumps(results_record, ensure_ascii=False, allow_nan=False) + "\n")
    print(f"Wrote {len(records)} records to {output_path}")
    print(f"Wrote {len(records)} results records to {results_path}")


if __name__ == "__main__":
    main()
