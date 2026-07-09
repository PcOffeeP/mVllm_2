from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .constants import PROJECT_ROOT, PROMPT_NAMES
from .datasets import load_dataset
from .model_runtime import load_model, run_model_on_video
from .prompts import get_prompt
from .run_evaluation import evaluate_sample, summarize, write_outputs


DEFAULT_BASE_MODEL = PROJECT_ROOT / "models" / "minicpm-v-4.5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the base model on the 22 original test videos with both prompt versions."
    )
    parser.add_argument("--model-dir", default=str(DEFAULT_BASE_MODEL), help="Base model directory.")
    parser.add_argument("--out-dir", default="finetune/results/base_prompt_format_test")
    parser.add_argument("--video-root", default=None)
    parser.add_argument("--max-samples", type=int, default=None, help="Optional local smoke limit. Default uses all 22 original videos.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_root = Path(args.video_root) if args.video_root else None
    samples = load_dataset("test", video_root=video_root)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    processor, model = load_model(args.model_dir)
    comparison: dict[str, Any] = {
        "dataset": "test",
        "sample_count": len(samples),
        "model_dir": args.model_dir,
        "prompts": {},
    }

    for prompt_name in PROMPT_NAMES:
        prompt_text = get_prompt(prompt_name)
        records = []
        for sample in samples:
            if not sample.video_path.exists():
                raw_output = ""
                runtime_error = f"video not found: {sample.video_path}"
            else:
                try:
                    raw_output = run_model_on_video(model, processor, sample.video_path, prompt_text)
                    runtime_error = None
                except Exception as exc:
                    raw_output = ""
                    runtime_error = f"{type(exc).__name__}: {exc}"
            records.append(evaluate_sample(sample, raw_output, runtime_error))

        prompt_out_dir = out_root / prompt_name
        write_outputs(
            out_dir=prompt_out_dir,
            records=records,
            dataset="test",
            model_dir=args.model_dir,
            prompt=prompt_name,
            prompt_text=prompt_text,
            predictions=None,
        )
        metrics = summarize(records)
        comparison["prompts"][prompt_name] = {
            "out_dir": str(prompt_out_dir),
            "format_valid_rate": metrics["format_valid_rate"],
            "format_valid_count": metrics["format_valid_count"],
            "runtime_error_count": metrics["runtime_error_count"],
            "schema_error_counts": metrics["schema_error_counts"],
        }

    (out_root / "prompt_format_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote prompt comparison to {out_root / 'prompt_format_comparison.json'}")


if __name__ == "__main__":
    main()
