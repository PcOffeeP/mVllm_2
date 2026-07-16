from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from .constants import PROJECT_ROOT, PROMPT_NAMES
from .datasets import load_dataset
from .model_runtime import load_model, run_model_on_video
from .prompts import (
    get_experiment_system_prompt,
    get_experiment_system_prompt_hash,
    get_prompt_library,
    get_user_prompt,
    get_user_prompt_template_count,
)
from .run_evaluation import evaluate_sample, summarize, write_outputs


DEFAULT_BASE_MODEL = PROJECT_ROOT / "models" / "minicpm-v-4.5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the base model on the original test videos with the medium variant system prompt and 4-field user prompt. "
        "Use --dataset to switch between test splits (e.g. test or test_subvideos)."
    )
    parser.add_argument("--model-dir", default=str(DEFAULT_BASE_MODEL), help="Base model directory.")
    parser.add_argument(
        "--dataset",
        default="test",
        help="Dataset split to evaluate (default: test). Supports test_subvideos.",
    )
    parser.add_argument(
        "--out-dir",
        default="finetune/results/base_prompt_format_{dataset}",
        help="Output directory. The {dataset} placeholder is replaced by the value of --dataset.",
    )
    parser.add_argument("--video-root", default=None)
    parser.add_argument("--max-samples", type=int, default=None, help="Optional local smoke limit. Default uses all 22 original videos.")
    parser.add_argument(
        "--user-prompt-seed",
        type=int,
        default=42,
        help="Random seed for per-sample user prompt template selection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_root = Path(args.video_root) if args.video_root else None
    samples = load_dataset(args.dataset, video_root=video_root)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    out_dir = args.out_dir.replace("{dataset}", args.dataset)
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    processor, model = load_model(args.model_dir)
    library = get_prompt_library()
    system_prompt = get_experiment_system_prompt("medium", library)
    system_prompt_hash = get_experiment_system_prompt_hash("medium", library)

    rng = random.Random(args.user_prompt_seed)
    template_count = get_user_prompt_template_count(library)

    comparison: dict[str, Any] = {
        "dataset": args.dataset,
        "sample_count": len(samples),
        "model_dir": args.model_dir,
        "system_prompt": system_prompt,
        "system_prompt_hash": system_prompt_hash,
        "prompts": {},
    }

    for prompt_name in PROMPT_NAMES:
        records = []
        prompt_text = None
        for sample in samples:
            template_index = rng.randrange(template_count)
            sample_prompt_text = get_user_prompt(template_index, library)
            if prompt_text is None:
                prompt_text = sample_prompt_text
            if not sample.video_path.exists():
                raw_output = ""
                runtime_error = f"video not found: {sample.video_path}"
            else:
                try:
                    raw_output = run_model_on_video(
                        model, processor, sample.video_path, sample_prompt_text, system_prompt=system_prompt
                    )
                    runtime_error = None
                except Exception as exc:
                    raw_output = ""
                    runtime_error = f"{type(exc).__name__}: {exc}"
            records.append(evaluate_sample(sample, raw_output, runtime_error))

        prompt_text = prompt_text or get_user_prompt(0, library)
        prompt_out_dir = out_root / prompt_name
        write_outputs(
            out_dir=prompt_out_dir,
            records=records,
            dataset=args.dataset,
            model_dir=args.model_dir,
            prompt=prompt_name,
            prompt_text=prompt_text,
            predictions=None,
            system_prompt=system_prompt,
            system_prompt_hash=system_prompt_hash,
        )
        metrics = summarize(records)
        comparison["prompts"][prompt_name] = {
            "out_dir": str(prompt_out_dir),
            "raw_output_rate": metrics["raw_output_rate"],
            "raw_output_count": metrics["raw_output_count"],
            "empty_output_count": metrics["empty_output_count"],
            "runtime_error_count": metrics["runtime_error_count"],
        }

    (out_root / "prompt_format_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote prompt comparison to {out_root / 'prompt_format_comparison.json'}")


if __name__ == "__main__":
    main()
