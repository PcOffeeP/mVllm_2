# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/06_merged/fold_0_train.json`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/minimal_overfit

#!/usr/bin/env python3
"""Build a deterministic 16-example memorization dataset and training config."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = Path("finetune/results/diagnostics/minimal_overfit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=Path("data/06_merged/fold_0_train.json")
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def assistant_target(record: dict[str, Any]) -> dict[str, Any]:
    for message in record["messages"]:
        if message.get("role") == "assistant":
            content = str(message["content"]).strip()
            if "结果：" in content:
                content = content.split("结果：", 1)[1].strip()
            return json.loads(content)
    raise ValueError("record has no assistant message")


def source_id(record: dict[str, Any]) -> str:
    video = Path(record["videos"][0]).stem
    match = re.match(r"(video_\d+)", video)
    return match.group(1) if match else video


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_records(records: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    positives: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]] = defaultdict(
        list
    )
    negatives: list[tuple[int, dict[str, Any]]] = []
    seen_video: set[str] = set()
    for index, record in enumerate(records):
        video = record["videos"][0]
        if video in seen_video:
            continue
        seen_video.add(video)
        target = assistant_target(record)
        if target.get("has_fracture") is True:
            interval = target.get("fracture_between")
            if (
                isinstance(interval, list)
                and len(interval) == 2
                and interval[1] == interval[0] + 1
                and 0 <= interval[0] <= 6
            ):
                positives[tuple(interval)].append((index, record))
        elif target.get("has_fracture") is False:
            negatives.append((index, record))

    chosen_positive: list[tuple[int, dict[str, Any]]] = []
    used_sources: set[str] = set()
    for left in range(7):
        candidates = positives[(left, left + 1)]
        if not candidates:
            raise ValueError(f"no positive candidate for interval [{left},{left + 1}]")
        candidates.sort(
            key=lambda pair: (
                source_id(pair[1]) in used_sources,
                source_id(pair[1]),
                pair[1]["videos"][0],
            )
        )
        picked = candidates[0]
        chosen_positive.append(picked)
        used_sources.add(source_id(picked[1]))

    extras = [
        pair
        for interval in sorted(positives)
        for pair in positives[interval]
        if pair not in chosen_positive
    ]
    extras.sort(
        key=lambda pair: (
            source_id(pair[1]) in used_sources,
            source_id(pair[1]),
            pair[1]["videos"][0],
        )
    )
    chosen_positive.append(extras[0])

    positive_sources = {source_id(record) for _, record in chosen_positive}
    negatives.sort(
        key=lambda pair: (
            source_id(pair[1]) in positive_sources,
            source_id(pair[1]),
            pair[1]["videos"][0],
        )
    )
    chosen_negative: list[tuple[int, dict[str, Any]]] = []
    negative_sources: set[str] = set()
    for pair in negatives:
        src = source_id(pair[1])
        if src in negative_sources:
            continue
        chosen_negative.append(pair)
        negative_sources.add(src)
        if len(chosen_negative) == 8:
            break
    if len(chosen_negative) < 8:
        for pair in negatives:
            if pair not in chosen_negative:
                chosen_negative.append(pair)
            if len(chosen_negative) == 8:
                break
    if len(chosen_negative) != 8:
        raise ValueError("fewer than 8 unique negative videos")

    selected = chosen_positive + chosen_negative
    selected.sort(key=lambda pair: (not assistant_target(pair[1])["has_fracture"], pair[0]))
    return selected


def main() -> None:
    args = parse_args()
    source_path = (ROOT / args.source).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    records = json.loads(source_path.read_text(encoding="utf-8"))
    selected = select_records(records)

    dataset_path = data_dir / "diagnostic_overfit.json"
    dataset_path.write_text(
        json.dumps([record for _, record in selected], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    dataset_info = {
        "diagnostic_overfit": {
            "file_name": "diagnostic_overfit.json",
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
    }
    (data_dir / "dataset_info.json").write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_rows = []
    for position, (source_index, record) in enumerate(selected):
        target = assistant_target(record)
        manifest_rows.append(
            {
                "position": position,
                "source_row_index": source_index,
                "video": record["videos"][0],
                "source_video_id": source_id(record),
                "target": target,
            }
        )
    system_prompts = sorted(
        {
            str(message["content"])
            for _, record in selected
            for message in record["messages"]
            if message.get("role") == "system"
        }
    )
    user_prompts = sorted(
        {
            str(message["content"])
            for _, record in selected
            for message in record["messages"]
            if message.get("role") == "user"
        }
    )
    prompt_material = json.dumps(
        {"system": system_prompts, "user": user_prompts},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    manifest = {
        "source": str(source_path.relative_to(ROOT)),
        "source_sha256": sha256(source_path),
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_sha256": sha256(dataset_path),
        "prompt_hash": hashlib.sha256(prompt_material).hexdigest(),
        "system_prompt_count": len(system_prompts),
        "user_prompt_count": len(user_prompts),
        "sample_count": len(selected),
        "positive_count": sum(
            row["target"]["has_fracture"] is True for row in manifest_rows
        ),
        "negative_count": sum(
            row["target"]["has_fracture"] is False for row in manifest_rows
        ),
        "covered_intervals": sorted(
            {
                tuple(row["target"]["fracture_between"])
                for row in manifest_rows
                if row["target"]["has_fracture"] is True
            }
        ),
        "rows": manifest_rows,
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    config = {
        "model_name_or_path": "../models/minicpmv4_5",
        "trust_remote_code": True,
        "flash_attn": "sdpa",
        "stage": "sft",
        "do_train": True,
        "do_eval": True,
        "finetuning_type": "lora",
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.0,
        "quantization_bit": None,
        "dataset": "diagnostic_overfit",
        "eval_dataset": "diagnostic_overfit",
        "dataset_dir": "results/diagnostics/minimal_overfit/data",
        "template": "minicpm_v",
        "media_dir": "..",
        "cutoff_len": 2048,
        "video_maxlen": 8,
        "preprocessing_num_workers": 4,
        "overwrite_cache": True,
        "output_dir": "../LlamaFactory/saves/minicpmv4_5/lora/diagnostic_overfit",
        "logging_steps": 2,
        "save_strategy": "steps",
        "save_steps": 20,
        "save_total_limit": 3,
        "eval_strategy": "steps",
        "eval_steps": 20,
        "load_best_model_at_end": False,
        "plot_loss": True,
        "overwrite_output_dir": True,
        "per_device_train_batch_size": 1,
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": 4,
        "learning_rate": 0.0001,
        "max_steps": 120,
        "lr_scheduler_type": "constant",
        "warmup_ratio": 0.0,
        "bf16": True,
        "max_grad_norm": 1.0,
        "weight_decay": 0.0,
        "adam_beta2": 0.95,
        "optim": "paged_adamw_8bit",
        "gradient_checkpointing": True,
        "ddp_timeout": 1800,
        "seed": 3407,
    }
    (output_dir / "train.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    resume_config = {
        **config,
        "max_steps": 240,
        "overwrite_output_dir": False,
    }
    (output_dir / "train_resume_240.yaml").write_text(
        yaml.safe_dump(resume_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    safe_continue_config = {
        **config,
        "adapter_name_or_path": (
            "../LlamaFactory/saves/minicpmv4_5/lora/"
            "diagnostic_overfit/checkpoint-120"
        ),
        "output_dir": (
            "../LlamaFactory/saves/minicpmv4_5/lora/"
            "diagnostic_overfit_continued_240"
        ),
        "max_steps": 120,
        "overwrite_output_dir": True,
    }
    (output_dir / "train_continue_240_safe.yaml").write_text(
        yaml.safe_dump(safe_continue_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    merge_config = {
        "model_name_or_path": "../models/minicpmv4_5",
        "adapter_name_or_path": (
            "../LlamaFactory/saves/minicpmv4_5/lora/diagnostic_overfit"
        ),
        "template": "minicpm_v",
        "finetuning_type": "lora",
        "trust_remote_code": True,
        "export_dir": (
            "../LlamaFactory/saves/minicpmv4_5/lora/diagnostic_overfit_merged"
        ),
        "export_size": 2,
        "export_device": "cpu",
        "export_legacy_format": False,
    }
    (output_dir / "merge.yaml").write_text(
        yaml.safe_dump(merge_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(json.dumps({k: manifest[k] for k in ("sample_count", "positive_count", "negative_count", "covered_intervals", "dataset_sha256")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
