# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/diagnostic_overfit.json`、`models/minicpmv4_5`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/minimal_overfit
#   - finetune/results/diagnostics/run_dataset_evaluation.py
# 已迁（原 finetune/results/diagnostics/ 下依赖，已落入本目录同名文件）：
#   - score_diagnostic_evaluation.py → 本目录 score_diagnostic_evaluation.py
#   - run_visual_counterfactuals.py → 本目录 run_visual_counterfactuals.py
# 因此正文中写死的 `finetune/results/diagnostics/score_diagnostic_evaluation.py`、`finetune/results/diagnostics/run_visual_counterfactuals.py` 路径已失效，应改按本目录同名文件解析。

#!/usr/bin/env python3
"""Merge, score, and run counterfactuals for the minimal overfit experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULT = ROOT / "finetune/results/diagnostics/minimal_overfit"
DEFAULT_ADAPTER = (
    ROOT / "LlamaFactory/saves/minicpmv4_5/lora/diagnostic_overfit"
)
DEFAULT_MERGED = (
    ROOT / "LlamaFactory/saves/minicpmv4_5/lora/diagnostic_overfit_merged"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--merged-dir", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--training-total-steps", type=int, default=120)
    parser.add_argument("--optimizer-reset", action="store_true")
    parser.add_argument("--training-config", type=Path)
    parser.add_argument("--force-merge", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment() -> dict[str, str]:
    env = os.environ.copy()
    project_source = ROOT / "LlamaFactory/src"
    paths = [str(project_source), str(ROOT)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = ":".join(paths)
    env["DISABLE_VERSION_CHECK"] = "1"
    return env


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=environment(), check=True)


def main() -> None:
    args = parse_args()
    result_dir = args.result_dir.resolve()
    adapter_dir = args.adapter_dir.resolve()
    merged_dir = args.merged_dir.resolve()
    dataset_file = result_dir / "data/diagnostic_overfit.json"
    adapter_file = adapter_dir / "adapter_model.safetensors"
    if not adapter_file.is_file():
        raise FileNotFoundError(f"training adapter is missing: {adapter_file}")
    if args.force_merge and merged_dir.exists():
        shutil.rmtree(merged_dir)
    if not (merged_dir / "model.safetensors.index.json").is_file():
        merge_config = {
            "model_name_or_path": str((ROOT / "models/minicpmv4_5").resolve()),
            "adapter_name_or_path": str(adapter_dir),
            "template": "minicpm_v",
            "finetuning_type": "lora",
            "trust_remote_code": True,
            "export_dir": str(merged_dir),
            "export_size": 2,
            "export_device": "cpu",
            "export_legacy_format": False,
        }
        runtime_merge_config = result_dir / "merge.runtime.yaml"
        runtime_merge_config.write_text(
            yaml.safe_dump(merge_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        run(
            [
                "llamafactory-cli",
                "export",
                str(runtime_merge_config.resolve()),
            ],
            cwd=ROOT / "finetune",
        )
    dataset_manifest = json.loads(
        (result_dir / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    training_config = (
        args.training_config.resolve()
        if args.training_config
        else result_dir / "train.yaml"
    )
    manifest = {
        "experiment_id": "minimal_overfit",
        "model_kind": "merged",
        "base_model": "models/minicpmv4_5",
        "adapter": str(adapter_dir),
        "adapter_sha256": sha256(adapter_file),
        "dataset": str(dataset_file),
        "dataset_sha256": sha256(dataset_file),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "prompt_hash": dataset_manifest["prompt_hash"],
        "training_config": str(training_config),
        "training_config_sha256": sha256(training_config),
        "postprocess_script_sha256": sha256(Path(__file__).resolve()),
        "training_total_steps": args.training_total_steps,
        "checkpoint_step": args.training_total_steps,
        "optimizer_reset_during_continuation": args.optimizer_reset,
    }
    manifest_path = result_dir / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evaluation_dir = result_dir / "training_set_evaluation"
    run(
        [
            sys.executable,
            str(
                (
                    ROOT
                    / "finetune/results/diagnostics/run_dataset_evaluation.py"
                ).resolve()
            ),
            "--dataset-file",
            str(dataset_file),
            "--model-dir",
            str(merged_dir),
            "--out-dir",
            str(evaluation_dir),
        ]
    )
    metrics_path = evaluation_dir / "diagnostic_metrics.json"
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
            str(evaluation_dir / "evaluation_records.jsonl"),
            "--output",
            str(metrics_path),
            "--model-manifest",
            str(manifest_path),
        ]
    )
    metrics: dict[str, Any] = json.loads(
        metrics_path.read_text(encoding="utf-8")
    )["metrics"]
    has_accuracy = metrics["has_fracture"]["accuracy"]
    interval_exact = metrics["positive_only"]["interval_exact_rate"]
    acceptance = bool(
        has_accuracy is not None
        and interval_exact is not None
        and has_accuracy >= 0.95
        and interval_exact >= 0.90
    )

    counterfactual_dir = result_dir / "counterfactuals"
    run(
        [
            sys.executable,
            str(
                (
                    ROOT
                    / "finetune/results/diagnostics/run_visual_counterfactuals.py"
                ).resolve()
            ),
            "--dataset-file",
            str(dataset_file),
            "--model-dir",
            str(merged_dir),
            "--out-dir",
            str(counterfactual_dir),
        ]
    )
    variant_metrics = {}
    for variant in ("original", "repeat_first", "reverse", "black"):
        variant_dir = counterfactual_dir / variant
        variant_score = variant_dir / "diagnostic_metrics.json"
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
                str(variant_dir / "evaluation_records.jsonl"),
                "--output",
                str(variant_score),
                "--model-manifest",
                str(manifest_path),
            ]
        )
        variant_metrics[variant] = json.loads(
            variant_score.read_text(encoding="utf-8")
        )["metrics"]
    sensitivity = json.loads(
        (counterfactual_dir / "counterfactual_sensitivity.json").read_text(
            encoding="utf-8"
        )
    )
    summary = {
        "acceptance_thresholds": {
            "has_fracture_accuracy": 0.95,
            "positive_interval_exact": 0.90,
        },
        "training_set": {
            "has_fracture_accuracy": has_accuracy,
            "positive_interval_exact": interval_exact,
            "accepted": acceptance,
        },
        "counterfactual_metrics": {
            variant: {
                "has_fracture_accuracy": values["has_fracture"]["accuracy"],
                "positive_interval_exact": values["positive_only"][
                    "interval_exact_rate"
                ],
                "joint_success": values["positive_only"]["joint_success_rate"],
            }
            for variant, values in variant_metrics.items()
        },
        "sensitivity": sensitivity["metrics"],
    }
    (result_dir / "minimal_overfit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not acceptance:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
