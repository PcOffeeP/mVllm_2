from __future__ import annotations

import argparse
import json
import os
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
    round_record_times,
    validate_fold,
    validate_prompt_preset,
    validate_task,
)
from config import DEFAULT_VIDEO_ROOT, GROUND_TRUTH_JSON, PROMPT_PRESETS, VIDEO_MAX_FRAMES


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
                record["pred_time_raw"] = payload.get("time")
                record["pred_time_sec"] = parse_seconds(payload.get("time"))
                record["pred_type_raw"] = payload.get("type")
                record["pred_type_norm"] = normalize_prediction_label(payload.get("type"))
        except Exception as exc:
            record["raw_output"] = str(exc)
            record["failure_reason"] = "model_inference_failed" if video_path.exists() else "video_load_failed"
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
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
