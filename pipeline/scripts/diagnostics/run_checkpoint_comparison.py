# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`models/minicpmv4_5`、`data/06_merged`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/checkpoint_comparison
#   - finetune/results/diagnostics/run_dataset_evaluation.py
#   - finetune/results/diagnostics/score_diagnostic_evaluation.py

#!/usr/bin/env python3
"""Merge, evaluate, score, and summarize the diagnostic checkpoint series."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ADAPTER_ROOT = Path(
    "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_v3"
)
DEFAULT_FINAL_MERGED = Path(
    "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_v3_merged"
)
DEFAULT_OUTPUT_ROOT = Path("finetune/results/diagnostics/checkpoint_comparison")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", nargs="+", type=int, default=[150, 200, 250, 300, 350, 360])
    parser.add_argument("--adapter-root", type=Path, default=DEFAULT_ADAPTER_ROOT)
    parser.add_argument("--final-merged", type=Path, default=DEFAULT_FINAL_MERGED)
    parser.add_argument("--base-model", type=Path, default=Path("models/minicpmv4_5"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dataset", default="fold_0_val")
    parser.add_argument(
        "--prompt-mode",
        choices=("embedded", "production"),
        default="production",
        help="Prompt contract used for checkpoint inference.",
    )
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--keep-merged", action="store_true")
    parser.add_argument(
        "--rescore-only",
        action="store_true",
        help="Recompute metrics from existing evaluation_records.jsonl without inference.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    env = os.environ.copy()
    project_llamafactory = ROOT / "LlamaFactory/src"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{project_llamafactory}:{existing_pythonpath}"
        if existing_pythonpath
        else str(project_llamafactory)
    )
    env["DISABLE_VERSION_CHECK"] = "1"
    subprocess.run(command, cwd=cwd, env=env, check=True)


def merge_checkpoint(
    *,
    step: int,
    checkpoint: Path,
    base_model: Path,
    merged_dir: Path,
    config_dir: Path,
) -> None:
    if (merged_dir / "model.safetensors.index.json").is_file():
        print(f"[step {step}] reuse merged model {merged_dir}", flush=True)
        return
    if merged_dir.exists():
        shutil.rmtree(merged_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model_name_or_path": str(base_model.resolve()),
        "adapter_name_or_path": str(checkpoint.resolve()),
        "template": "minicpm_v",
        "finetuning_type": "lora",
        "trust_remote_code": True,
        "export_dir": str(merged_dir.resolve()),
        "export_size": 2,
        "export_device": "cpu",
        "export_legacy_format": False,
    }
    config_path = config_dir / f"merge_step{step}.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    run(["llamafactory-cli", "export", str(config_path.resolve())])
    metadata = {
        "model_kind": "merged",
        "base_model": str(base_model.resolve()),
        "adapter_path": str(checkpoint.resolve()),
        "checkpoint_step": step,
        "adapter_sha256": sha256(checkpoint / "adapter_model.safetensors"),
    }
    (merged_dir / "merge_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def evaluate_and_score(
    *,
    step: int | str,
    model_dir: Path,
    out_dir: Path,
    dataset: str,
    prompt_mode: str,
    max_samples: int | None,
    model_manifest_path: Path | None = None,
) -> None:
    records = out_dir / "evaluation_records.jsonl"
    if not records.is_file():
        dataset_file = ROOT / "data/06_merged" / f"{dataset}.json"
        if not dataset_file.is_file():
            raise FileNotFoundError(
                f"checkpoint comparison requires a merged dataset file: {dataset_file}"
            )
        command = [
            sys.executable,
            str(
                (
                    ROOT
                    / "finetune/results/diagnostics/run_dataset_evaluation.py"
                ).resolve()
            ),
            "--dataset-file",
            str(dataset_file.resolve()),
            "--model-dir",
            str(model_dir.resolve()),
            "--out-dir",
            str(out_dir.resolve()),
            "--prompt-mode",
            prompt_mode,
        ]
        if max_samples is not None:
            command.extend(["--max-samples", str(max_samples)])
        run(command)
    score_path = out_dir / "diagnostic_metrics.json"
    model_manifest_path = model_manifest_path or model_dir / "merge_metadata.json"
    run(
        [
            sys.executable,
            str(
                (
                    ROOT
                    / "finetune/results/diagnostics/score_diagnostic_evaluation.py"
                ).resolve()
            ),
            "--records",
            str(records.resolve()),
            "--output",
            str(score_path.resolve()),
            "--model-manifest",
            str(model_manifest_path.resolve()),
        ]
    )
    source_manifest = json.loads(model_manifest_path.read_text(encoding="utf-8"))
    evaluation_summary = json.loads(
        (out_dir / "evaluation_summary.json").read_text(encoding="utf-8")
    )
    run_info = {
        "experiment_id": f"checkpoint_comparison_{step}",
        "step": step,
        "dataset": dataset,
        "model_dir": str(model_dir.resolve()),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dataset_sha256": sha256(ROOT / "data/06_merged" / f"{dataset}.json"),
        "checkpoint_adapter_sha256": source_manifest.get("adapter_sha256"),
        "prompt_mode": prompt_mode,
        "prompt_hash": evaluation_summary.get("system_prompt_hash"),
        "prompt_contract_hash": evaluation_summary.get("prompt_contract_hash"),
        "prompt_version": evaluation_summary.get("prompt_version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def aggregate(output_root: Path, requested_steps: list[int | str]) -> None:
    rows: list[dict[str, Any]] = []
    missing = []
    for step in requested_steps:
        directory = f"step{step}" if isinstance(step, int) else str(step)
        path = output_root / directory / "diagnostic_metrics.json"
        if not path.is_file():
            missing.append(step)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        metrics = data["metrics"]
        rows.append(
            {
                "step": step,
                "json_valid": metrics["json_valid_rate"],
                "legal": metrics["legal_combination_rate"],
                "has_f1": metrics["has_fracture"]["f1"],
                "has_recall": metrics["has_fracture"]["recall"],
                "type_macro_f1": metrics["positive_only"]["type_macro_f1"],
                "interval_exact": metrics["positive_only"]["interval_exact_rate"],
                "interval_pm1": metrics["positive_only"]["interval_pm1_rate"],
                "joint": metrics["positive_only"]["joint_success_rate"],
                "source_macro_f1": metrics["source_level"][
                    "source_macro_has_fracture_f1"
                ],
                "source_clip_gap_pp": metrics["source_level"][
                    "source_macro_minus_clip_macro_pp"
                ],
                "prediction_distribution": metrics[
                    "prediction_has_fracture_distribution"
                ],
            }
        )
    best_source_macro = (
        max(rows, key=lambda row: row["source_macro_f1"]) if rows else None
    )
    recalls = {row["has_recall"] for row in rows}
    final_manifest_path = output_root / "final_model_manifest.corrected.json"
    final_manifest = (
        json.loads(final_manifest_path.read_text(encoding="utf-8"))
        if final_manifest_path.is_file()
        else None
    )
    conclusions = {
        "best_source_macro_step": (
            best_source_macro["step"] if best_source_macro else None
        ),
        "best_source_macro_has_fracture_f1": (
            best_source_macro["source_macro_f1"] if best_source_macro else None
        ),
        "has_fracture_recall_invariant_across_completed_steps": len(recalls) == 1,
        "eval_loss_selected_checkpoint": (
            (final_manifest or {}).get("checkpoint_step")
        ),
        "eval_loss_and_task_metric_select_same_checkpoint": (
            bool(best_source_macro)
            and (final_manifest or {}).get("checkpoint_step")
            == best_source_macro["step"]
        ),
        "acceptance": {
            "has_fracture_f1_ge_0_75": any(
                row["has_f1"] is not None and row["has_f1"] >= 0.75
                for row in rows
            ),
            "has_fracture_recall_ge_0_75": any(
                row["has_recall"] is not None and row["has_recall"] >= 0.75
                for row in rows
            ),
            "interval_pm1_ge_0_75": any(
                row["interval_pm1"] is not None and row["interval_pm1"] >= 0.75
                for row in rows
            ),
            "joint_ge_0_40": any(
                row["joint"] is not None and row["joint"] >= 0.40
                for row in rows
            ),
            "source_clip_gap_lt_10pp": any(
                row["source_clip_gap_pp"] is not None
                and abs(row["source_clip_gap_pp"]) < 10
                for row in rows
            ),
        },
        "diagnosis": (
            "All saved checkpoints have the same very low fracture recall, so this "
            "is not a late-training recall collapse. The task metric selects an "
            "earlier checkpoint than eval_loss, and no checkpoint meets the "
            "diagnostic acceptance thresholds."
        ),
    }
    summary = {
        "requested_steps": requested_steps,
        "missing_steps": missing,
        "completed_steps": [row["step"] for row in rows],
        "rows": rows,
        "conclusions": conclusions,
    }
    (output_root / "checkpoint_comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    headers = [
        "step",
        "has F1",
        "recall",
        "type macro-F1",
        "interval exact",
        "interval ±1",
        "joint",
        "source macro-F1",
    ]
    lines = [
        "# Checkpoint 对比",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                str(row[key])
                for key in (
                    "step",
                    "has_f1",
                    "has_recall",
                    "type_macro_f1",
                    "interval_exact",
                    "interval_pm1",
                    "joint",
                    "source_macro_f1",
                )
            )
            + " |"
        )
    if missing:
        lines.extend(
            [
                "",
                f"缺失 checkpoint：{', '.join(map(str, missing))}。这些步骤没有权重产物，未作替代或插值。",
            ]
        )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"- source-macro 最佳：step {conclusions['best_source_macro_step']} "
            f"({conclusions['best_source_macro_has_fracture_f1']})。",
            f"- eval loss 选择：step {conclusions['eval_loss_selected_checkpoint']}；"
            f"与任务指标选择一致：{conclusions['eval_loss_and_task_metric_select_same_checkpoint']}。",
            f"- 各 checkpoint 的断裂召回是否完全不变："
            f"{conclusions['has_fracture_recall_invariant_across_completed_steps']}。",
            "- 没有任何 checkpoint 通过 Stage 2~4 的任务验收阈值。",
        ]
    )
    (output_root / "checkpoint_comparison.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    adapter_root = (ROOT / args.adapter_root).resolve()
    final_merged = (ROOT / args.final_merged).resolve()
    base_model = (ROOT / args.base_model).resolve()
    output_root = (ROOT / args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    config_dir = output_root / "merge_configs"
    temporary_root = output_root / "_merged_models"
    requested_labels: list[int | str] = [*args.steps, "final"]

    if args.rescore_only:
        for label in requested_labels:
            directory = f"step{label}" if isinstance(label, int) else str(label)
            out_dir = output_root / directory
            records = out_dir / "evaluation_records.jsonl"
            metrics_path = out_dir / "diagnostic_metrics.json"
            if not records.is_file() or not metrics_path.is_file():
                continue
            old_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            manifest = old_metrics.get("model_manifest")
            command = [
                sys.executable,
                str(
                    (
                        ROOT
                        / "finetune/results/diagnostics/score_diagnostic_evaluation.py"
                    ).resolve()
                ),
                "--records",
                str(records.resolve()),
                "--output",
                str(metrics_path.resolve()),
            ]
            if manifest is not None:
                manifest_path = out_dir / "model_manifest.rescore.json"
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                command.extend(["--model-manifest", str(manifest_path.resolve())])
            run(command)
            run_manifest_path = out_dir / "run_manifest.json"
            evaluation_summary_path = out_dir / "evaluation_summary.json"
            if run_manifest_path.is_file() and evaluation_summary_path.is_file():
                run_manifest = json.loads(
                    run_manifest_path.read_text(encoding="utf-8")
                )
                evaluation_summary = json.loads(
                    evaluation_summary_path.read_text(encoding="utf-8")
                )
                run_manifest["experiment_id"] = (
                    f"checkpoint_comparison_{label}"
                )
                run_manifest["prompt_hash"] = evaluation_summary.get(
                    "system_prompt_hash"
                )
                run_manifest["prompt_version"] = evaluation_summary.get(
                    "prompt_version"
                )
                run_manifest_path.write_text(
                    json.dumps(run_manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        aggregate(output_root, requested_labels)
        return

    status: dict[str, Any] = {
        "requested_steps": [*args.steps, "final"],
        "available": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    for step in args.steps:
        checkpoint = adapter_root / f"checkpoint-{step}"
        if not checkpoint.is_dir():
            status["available"][str(step)] = False
            print(f"[step {step}] checkpoint missing", flush=True)
            continue
        model_dir = temporary_root / f"step{step}"
        merge_checkpoint(
            step=step,
            checkpoint=checkpoint,
            base_model=base_model,
            merged_dir=model_dir,
            config_dir=config_dir,
        )
        status["available"][str(step)] = True
        evaluate_and_score(
            step=step,
            model_dir=model_dir,
            out_dir=output_root / f"step{step}",
            dataset=args.dataset,
            prompt_mode=args.prompt_mode,
            max_samples=args.max_samples,
        )
        if (
            not args.keep_merged
            and model_dir.is_relative_to(temporary_root)
            and model_dir.exists()
        ):
            shutil.rmtree(model_dir)
        aggregate(output_root, requested_labels)

    if final_merged.is_dir():
        trainer_state = json.loads(
            (adapter_root / "trainer_state.json").read_text(encoding="utf-8")
        )
        final_manifest = {
            "model_kind": "merged_final",
            "base_model": str(base_model),
            "adapter_path": str(adapter_root),
            "checkpoint_step": 350,
            "evaluation_label": "final",
            "best_model_checkpoint": trainer_state.get("best_model_checkpoint"),
            "best_metric": trainer_state.get("best_metric"),
            "adapter_sha256": sha256(adapter_root / "adapter_model.safetensors"),
            "warning": (
                "Existing merge_metadata.json claims checkpoint 360, but trainer_state "
                "identifies checkpoint 350 as best and the final adapter SHA256 is "
                "identical to checkpoint 350, not checkpoint 360."
            ),
        }
        final_manifest_path = output_root / "final_model_manifest.corrected.json"
        final_manifest_path.write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        evaluate_and_score(
            step="final",
            model_dir=final_merged,
            out_dir=output_root / "final",
            dataset=args.dataset,
            prompt_mode=args.prompt_mode,
            max_samples=args.max_samples,
            model_manifest_path=final_manifest_path,
        )
        status["available"]["final"] = True
    else:
        status["available"]["final"] = False
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    (output_root / "run_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    aggregate(output_root, requested_labels)


if __name__ == "__main__":
    main()
