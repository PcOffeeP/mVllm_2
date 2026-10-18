# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/06_merged/fold_0_train.json`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/control_experiments

#!/usr/bin/env python3
"""Prepare source-paired, interval-balanced data and Stage 5 configs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = Path("finetune/results/diagnostics/control_experiments")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--train-file", type=Path, default=Path("data/06_merged/fold_0_train.json")
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-interval", type=int, default=12)
    parser.add_argument("--max-positive-per-source", type=int, default=4)
    return parser.parse_args()


def target(record: dict[str, Any]) -> dict[str, Any]:
    value = next(
        str(message["content"])
        for message in record["messages"]
        if message.get("role") == "assistant"
    ).strip()
    if "结果：" in value:
        value = value.split("结果：", 1)[1].strip()
    return json.loads(value)


def source_id(record: dict[str, Any]) -> str:
    stem = Path(record["videos"][0]).stem
    match = re.match(r"(video_\d+)", stem)
    return match.group(1) if match else stem


def crop_family(record: dict[str, Any]) -> str:
    stem = Path(record["videos"][0]).stem
    for family in ("focus", "neg_before", "neg_after", "full"):
        if f"_{family}" in stem:
            return family
    return "other"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_balanced(
    records: list[dict[str, Any]], per_interval: int, max_per_source: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    positives: dict[tuple[int, int], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    negatives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (record["videos"][0], json.dumps(target(record), sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        value = target(record)
        source = source_id(record)
        if value.get("has_fracture") is True:
            interval = value.get("fracture_between")
            if (
                isinstance(interval, list)
                and len(interval) == 2
                and interval[1] == interval[0] + 1
                and 0 <= interval[0] <= 6
            ):
                positives[tuple(interval)][source].append(record)
        elif value.get("has_fracture") is False:
            negatives[source].append(record)

    selected_positive: list[dict[str, Any]] = []
    selected_by_source: Counter[str] = Counter()
    interval_counts: Counter[tuple[int, int]] = Counter()
    for interval in [(left, left + 1) for left in range(7)]:
        by_source = positives[interval]
        offsets: Counter[str] = Counter()
        while interval_counts[interval] < per_interval:
            candidates = [
                source
                for source, items in by_source.items()
                if offsets[source] < len(items)
                and selected_by_source[source] < max_per_source
                and selected_by_source[source] < len(negatives.get(source, []))
            ]
            if not candidates:
                raise ValueError(
                    f"cannot select {per_interval} source-paired positives for {interval}; "
                    f"reached {interval_counts[interval]}"
                )
            candidates.sort(
                key=lambda source: (
                    selected_by_source[source],
                    offsets[source],
                    source,
                )
            )
            source = candidates[0]
            record = by_source[source][offsets[source]]
            offsets[source] += 1
            selected_by_source[source] += 1
            interval_counts[interval] += 1
            selected_positive.append(record)

    selected_negative: list[dict[str, Any]] = []
    for source, count in sorted(selected_by_source.items()):
        candidates = sorted(negatives[source], key=lambda item: item["videos"][0])
        selected_negative.extend(candidates[:count])
    if len(selected_positive) != len(selected_negative):
        raise AssertionError("positive/negative source pairing failed")
    selected = selected_positive + selected_negative
    selected.sort(
        key=lambda record: (
            source_id(record),
            not bool(target(record).get("has_fracture")),
            record["videos"][0],
        )
    )
    positive_source_counts = Counter(source_id(record) for record in selected_positive)
    negative_source_counts = Counter(source_id(record) for record in selected_negative)
    if positive_source_counts != negative_source_counts:
        raise AssertionError("per-source label counts are not paired")
    stats = {
        "sample_count": len(selected),
        "positive_count": len(selected_positive),
        "negative_count": len(selected_negative),
        "interval_counts": {
            f"{left}-{right}": count
            for (left, right), count in sorted(interval_counts.items())
        },
        "source_count": len(positive_source_counts),
        "positive_per_source": dict(sorted(positive_source_counts.items())),
        "negative_per_source": dict(sorted(negative_source_counts.items())),
        "crop_family_by_label": {
            "positive": dict(
                Counter(crop_family(record) for record in selected_positive)
            ),
            "negative": dict(
                Counter(crop_family(record) for record in selected_negative)
            ),
        },
        "pairing_definition": (
            "Every selected source contributes the same number of positive focus and "
            "negative pre-event clips; this controls camera/source identity while "
            "retaining genuine pre-event negatives."
        ),
    }
    return selected, stats


def dataset_registration(file_name: str) -> dict[str, Any]:
    return {
        "file_name": file_name,
        "formatting": "sharegpt",
        "columns": {"messages": "messages", "videos": "videos"},
        "tags": {
            "role_tag": "role",
            "content_tag": "content",
            "user_tag": "user",
            "assistant_tag": "assistant",
            "observation_tag": "observation",
            "function_tag": "function_call",
            "system_tag": "system",
        },
    }


def base_config(output_name: str) -> dict[str, Any]:
    return {
        "model_name_or_path": "../models/minicpmv4_5",
        "trust_remote_code": True,
        "flash_attn": "sdpa",
        "stage": "sft",
        "do_train": True,
        "do_eval": False,
        "finetuning_type": "lora",
        "lora_rank": 8,
        "lora_alpha": 16,
        "quantization_bit": None,
        "template": "minicpm_v",
        "media_dir": "..",
        "cutoff_len": 2048,
        "video_maxlen": 8,
        "preprocessing_num_workers": 4,
        "overwrite_cache": True,
        "output_dir": f"../LlamaFactory/saves/minicpmv4_5/lora/{output_name}",
        "logging_steps": 5,
        "save_strategy": "epoch",
        "save_total_limit": 3,
        "eval_strategy": "no",
        "load_best_model_at_end": False,
        "plot_loss": True,
        "overwrite_output_dir": True,
        "per_device_train_batch_size": 1,
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "learning_rate": 0.000005,
        "num_train_epochs": 3,
        "lr_scheduler_type": "cosine",
        "warmup_ratio": 0.1,
        "bf16": True,
        "max_grad_norm": 1.0,
        "adam_beta2": 0.95,
        "optim": "paged_adamw_8bit",
        "gradient_checkpointing": True,
        "ddp_timeout": 1800,
        "seed": 3407,
    }


def main() -> None:
    args = parse_args()
    source_path = (ROOT / args.train_file).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    data_dir = output_dir / "data"
    config_dir = output_dir / "configs"
    data_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    records = json.loads(source_path.read_text(encoding="utf-8"))
    selected, stats = build_balanced(
        records, args.per_interval, args.max_positive_per_source
    )
    dataset_path = data_dir / "source_paired_interval_balanced.json"
    dataset_path.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    prompt_material = json.dumps(
        {
            role: sorted(
                {
                    str(message["content"])
                    for record in selected
                    for message in record["messages"]
                    if message.get("role") == role
                }
            )
            for role in ("system", "user")
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    prompt_hash = hashlib.sha256(prompt_material).hexdigest()
    info = {
        "control_visual_verified_train": dataset_registration(
            "temporal_reindexed.visual_verified.json"
        ),
        "fold0_val": {
            **dataset_registration("../../../../../data/06_merged/fold_0_val.json")
        },
    }
    (data_dir / "dataset_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    experiments: dict[str, dict[str, Any]] = {}
    for experiment in ("E1", "E2", "E3"):
        config = base_config(f"diagnostic_control_{experiment.lower()}")
        config.update(
            {
                "dataset": "control_visual_verified_train",
                "eval_dataset": "fold0_val",
                "dataset_dir": "results/diagnostics/control_experiments/data",
                "lora_dropout": 0.25 if experiment == "E1" else 0.1,
                "weight_decay": 0.2 if experiment in {"E1", "E2"} else 0.01,
            }
        )
        path = config_dir / f"{experiment.lower()}.yaml"
        path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        experiments[experiment] = {
            "config": str(path.relative_to(ROOT)),
            "config_sha256": sha256(path),
            "change": {
                "data": (
                    "visually verified, source-paired, temporal-reindexed, "
                    "interval-balanced"
                ),
                "lora_dropout": config["lora_dropout"],
                "weight_decay": config["weight_decay"],
                "learning_rate": config["learning_rate"],
            },
        }

    e4 = base_config("diagnostic_control_e4_lr1e5")
    e4.update(
        {
            "dataset": "tensile_video_interval_fold0_train",
            "eval_dataset": "tensile_video_interval_fold0_val",
            "dataset_dir": ".",
            "lora_dropout": 0.25,
            "weight_decay": 0.2,
            "learning_rate": 0.00001,
        }
    )
    e4_path = config_dir / "e4.yaml"
    e4_path.write_text(
        yaml.safe_dump(e4, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    experiments["E4"] = {
        "config": str(e4_path.relative_to(ROOT)),
        "config_sha256": sha256(e4_path),
        "change": {
            "data": "original E0 data",
            "lora_dropout": 0.25,
            "weight_decay": 0.2,
            "learning_rate": 0.00001,
            "comparison": "E0 used 5e-6",
        },
    }
    manifest = {
        "source": str(source_path.relative_to(ROOT)),
        "source_sha256": sha256(source_path),
        "balanced_dataset": str(dataset_path.relative_to(ROOT)),
        "balanced_dataset_sha256": sha256(dataset_path),
        "prompt_hash": prompt_hash,
        "selection": stats,
        "E0": {
            "status": "existing baseline",
            "adapter": "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_v3",
            "actual_final_checkpoint": 350,
            "learning_rate": 0.000005,
        },
        "experiments": experiments,
        "model_selection_metric": "validation source_macro_has_fracture_f1",
        "warning": (
            "Stage 2 visual audit gate must be cleared before launching these configs. "
            "Preparation does not authorize training on visually unverified positives."
        ),
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
