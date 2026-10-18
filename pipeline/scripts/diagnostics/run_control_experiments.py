# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`models/minicpmv4_5`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/control_experiments
#   - finetune/results/diagnostics/checkpoint_comparison/full_run_exact/final

#!/usr/bin/env python3
"""Run gated Stage 5 controlled trainings and task-level model selection."""

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
RESULT_ROOT = ROOT / "finetune/results/diagnostics/control_experiments"
BASE_MODEL = ROOT / "models/minicpmv4_5"
EXPERIMENTS = ("E1", "E2", "E3", "E4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments", nargs="+", choices=EXPERIMENTS, default=list(EXPERIMENTS))
    parser.add_argument(
        "--visual-gate",
        type=Path,
        default=RESULT_ROOT / "visual_gate/visual_gate_summary.json",
    )
    parser.add_argument("--keep-merged", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment() -> dict[str, str]:
    env = os.environ.copy()
    sources = [str(ROOT / "LlamaFactory/src"), str(ROOT)]
    if env.get("PYTHONPATH"):
        sources.append(env["PYTHONPATH"])
    env.update(
        {
            "PYTHONPATH": ":".join(sources),
            "DISABLE_VERSION_CHECK": "1",
            "DOWNSAMPLE_MODE": "4x",
            "WANDB_MODE": "offline",
        }
    )
    return env


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=environment(), check=True)


def adapter_output(config: dict[str, Any]) -> Path:
    return (ROOT / "finetune" / config["output_dir"]).resolve()


def evaluate_experiment(
    experiment: str,
    config_path: Path,
    experiment_spec: dict[str, Any],
    prompt_hash: str,
    dataset_hash: str,
    keep_merged: bool,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    adapter_dir = adapter_output(config)
    adapter_file = adapter_dir / "adapter_model.safetensors"
    output_dir = RESULT_ROOT / "runs" / experiment.lower()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not adapter_file.is_file():
        run(
            [
                sys.executable,
                "train_with_contract.py",
                str(config_path.relative_to(ROOT / "finetune")),
            ],
            cwd=ROOT / "finetune",
        )
    if not adapter_file.is_file():
        raise FileNotFoundError(f"adapter missing after training: {adapter_file}")

    merged_dir = output_dir / "_merged_model"
    if not (merged_dir / "model.safetensors.index.json").is_file():
        merge_config = {
            "model_name_or_path": str(BASE_MODEL),
            "adapter_name_or_path": str(adapter_dir),
            "template": "minicpm_v",
            "finetuning_type": "lora",
            "trust_remote_code": True,
            "export_dir": str(merged_dir),
            "export_size": 2,
            "export_device": "cpu",
            "export_legacy_format": False,
        }
        merge_path = output_dir / "merge.yaml"
        merge_path.write_text(
            yaml.safe_dump(merge_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        run(["llamafactory-cli", "export", str(merge_path)])

    trainer_state = json.loads(
        (adapter_dir / "trainer_state.json").read_text(encoding="utf-8")
    )
    model_manifest = {
        "experiment_id": experiment,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dataset_sha256": dataset_hash,
        "checkpoint_step": trainer_state.get("global_step"),
        "prompt_hash": prompt_hash,
        "training_config": str(config_path.relative_to(ROOT)),
        "training_config_sha256": sha256(config_path),
        "adapter": str(adapter_dir),
        "adapter_sha256": sha256(adapter_file),
        "controlled_change": experiment_spec["change"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(model_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evaluation_dir = output_dir / "fold_0_val"
    if not (evaluation_dir / "evaluation_records.jsonl").is_file():
        run(
            [
                sys.executable,
                "-m",
                "finetune.validation.run_evaluation",
                "--dataset",
                "fold_0_val",
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
            str(RESULT_ROOT.parent / "score_diagnostic_evaluation.py"),
            "--records",
            str(evaluation_dir / "evaluation_records.jsonl"),
            "--output",
            str(metrics_path),
            "--model-manifest",
            str(manifest_path),
        ]
    )
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))["metrics"]
    row = {
        "experiment_id": experiment,
        "has_fracture_f1": metrics["has_fracture"]["f1"],
        "has_fracture_recall": metrics["has_fracture"]["recall"],
        "type_macro_f1": metrics["positive_only"]["type_macro_f1"],
        "interval_exact": metrics["positive_only"]["interval_exact_rate"],
        "interval_pm1": metrics["positive_only"]["interval_pm1_rate"],
        "joint_success": metrics["positive_only"]["joint_success_rate"],
        "source_macro_has_fracture_f1": metrics["source_level"][
            "source_macro_has_fracture_f1"
        ],
        "source_clip_gap_pp": metrics["source_level"][
            "source_macro_minus_clip_macro_pp"
        ],
        "legal_combination_rate": metrics["legal_combination_rate"],
    }
    if not keep_merged:
        shutil.rmtree(merged_dir)
    return row


def baseline_row() -> dict[str, Any]:
    path = (
        ROOT
        / "finetune/results/diagnostics/checkpoint_comparison/full_run_exact/final/"
        "diagnostic_metrics.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))["metrics"]
    return {
        "experiment_id": "E0",
        "has_fracture_f1": data["has_fracture"]["f1"],
        "has_fracture_recall": data["has_fracture"]["recall"],
        "type_macro_f1": data["positive_only"]["type_macro_f1"],
        "interval_exact": data["positive_only"]["interval_exact_rate"],
        "interval_pm1": data["positive_only"]["interval_pm1_rate"],
        "joint_success": data["positive_only"]["joint_success_rate"],
        "source_macro_has_fracture_f1": data["source_level"][
            "source_macro_has_fracture_f1"
        ],
        "source_clip_gap_pp": data["source_level"][
            "source_macro_minus_clip_macro_pp"
        ],
        "legal_combination_rate": data["legal_combination_rate"],
    }


def main() -> None:
    args = parse_args()
    gate_path = args.visual_gate.resolve()
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("approved_for_training") is not True:
        raise RuntimeError(
            f"visual data gate is not approved: {gate_path}; "
            f"decision={gate.get('decision')}"
        )
    manifest = json.loads(
        (RESULT_ROOT / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    rows = [baseline_row()]
    for experiment in args.experiments:
        spec = manifest["experiments"][experiment]
        config_path = ROOT / spec["config"]
        dataset_hash = (
            manifest["source_sha256"]
            if experiment == "E4"
            else gate["repaired_dataset_sha256"]
        )
        rows.append(
            evaluate_experiment(
                experiment,
                config_path,
                spec,
                manifest["prompt_hash"],
                dataset_hash,
                args.keep_merged,
            )
        )
        (RESULT_ROOT / "control_comparison.partial.json").write_text(
            json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    best = max(rows, key=lambda row: row["source_macro_has_fracture_f1"])
    summary = {
        "selection_metric": "validation source_macro_has_fracture_f1",
        "selected_experiment": best["experiment_id"],
        "selected_score": best["source_macro_has_fracture_f1"],
        "rows": rows,
        "visual_gate": gate,
    }
    (RESULT_ROOT / "control_comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
