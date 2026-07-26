#!/usr/bin/env python3
"""Run the Stage B source-aware 3k train, merge, and strict fold0 evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_source_aware_3k import build_source_aware_3k
from finetune.build_v4_1_visual_data_experiment import validate_adapter_coverage
from finetune.v4_1_runtime import validate_release
from pipeline.current_data import current_data_paths

FINETUNE = ROOT / "finetune"
CONFIG_ROOT = FINETUNE / "MiniCPM/config/active/v4_1_source_aware_3k"
RUN_MANIFEST_PATH = CONFIG_ROOT / "run_manifest.json"
SAVE_ROOT = ROOT / "LlamaFactory/saves/minicpmv4_5/lora"
RUN_ID = "v4_1_phase2_source_aware_3k_dd89b70e9d63"
RELEASE_ID = "v4.1.0-ecb5aeb9657c"
SAMPLING_ID = "source-aware-3k-dd89b70e9d63"
SEEDS = (3407, 3411)
EXPECTED_VALIDATION_COUNT = 425
ESTIMATED_ADAPTER_BYTES = 8 * 1024**3
ESTIMATED_MERGED_BYTES = 18 * 1024**3
DISK_RESERVE_BYTES = 10 * 1024**3
LOG_ROOT = FINETUNE / "run_logs" / RUN_ID
RESULT_ROOT = FINETUNE / "results" / RUN_ID
STATE_PATH = LOG_ROOT / "state.json"


class SourceAware3kRunError(RuntimeError):
    """The frozen Stage B run identity or runtime state is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kRunError(f"无法读取 JSON {path}: {exc}") from exc


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "WANDB_MODE": "offline",
            "DOWNSAMPLE_MODE": "4x",
            "DISABLE_VERSION_CHECK": "1",
            "PYTHONPATH": f"{ROOT / 'LlamaFactory/src'}:{ROOT}",
        }
    )
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
    return env


def _write_state(status: str, stage: str, **extra: Any) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-state/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "sampling_id": SAMPLING_ID,
        "status": status,
        "stage": stage,
        "orchestrator_pid": os.getpid(),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **extra,
    }
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def _run_logged(command: list[str], log_path: Path, *, cwd: Path) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_runtime_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise SourceAware3kRunError(
            f"命令退出码 {result.returncode}，请查看 {log_path}"
        )


def adapter_dir(seed: int) -> Path:
    return SAVE_ROOT / f"sft_tensile_{RUN_ID}_seed{seed}"


def merged_dir(seed: int) -> Path:
    return adapter_dir(seed).with_name(f"{adapter_dir(seed).name}_merged")


def result_dir(seed: int) -> Path:
    return RESULT_ROOT / f"seed{seed}" / "fold0"


def _training_complete(seed: int) -> bool:
    root = adapter_dir(seed)
    state_path = root / "trainer_state.json"
    required = (
        root / "train_results.json",
        root / "adapter_config.json",
        root / "adapter_model.safetensors",
    )
    if not state_path.is_file() or not all(path.is_file() for path in required):
        return False
    try:
        state = _read_json(state_path)
    except SourceAware3kRunError:
        return False
    return state.get("global_step") == 1125


def _merged_complete(seed: int) -> bool:
    root = merged_dir(seed)
    return (
        (root / "config.json").is_file()
        and (root / "tokenizer_config.json").is_file()
        and any(root.glob("model*.safetensors"))
    )


def _evaluation_complete(seed: int) -> bool:
    root = result_dir(seed)
    summary_path = root / "evaluation_summary.json"
    records_path = root / "evaluation_records.jsonl"
    failures_path = root / "runtime_failures.csv"
    if not all(
        path.is_file()
        for path in (summary_path, records_path, failures_path)
    ):
        return False
    try:
        summary = _read_json(summary_path)
        records = sum(
            bool(line.strip())
            for line in records_path.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, SourceAware3kRunError):
        return False
    return (
        summary.get("release_id") == RELEASE_ID
        and summary.get("sample_count") == EXPECTED_VALIDATION_COUNT
        and summary.get("total_samples") == EXPECTED_VALIDATION_COUNT
        and summary.get("runtime_failure_count") == 0
        and records == EXPECTED_VALIDATION_COUNT
    )


def _validate_config(
    seed: int,
    config: Mapping[str, Any],
    *,
    expected_dataset_dir: Path,
) -> None:
    expected = {
        "stage": "sft",
        "do_train": True,
        "do_eval": True,
        "finetuning_type": "lora",
        "lora_target": "all",
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.25,
        "additional_target": "resampler",
        "freeze_vision_tower": False,
        "freeze_multi_modal_projector": False,
        "quantization_bit": 4,
        "quantization_method": "bnb",
        "double_quantization": True,
        "upcast_layernorm": True,
        "dataset": f"tensile_v4_1_phase2_3k_seed{seed}",
        "eval_dataset": "tensile_v4_1_phase2_fold0_val",
        "video_maxlen": 8,
        "overwrite_output_dir": False,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "learning_rate": 0.000005,
        "num_train_epochs": 3,
        "lr_scheduler_type": "cosine",
        "warmup_ratio": 0.1,
        "bf16": True,
        "optim": "adamw_torch",
        "seed": seed,
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise SourceAware3kRunError(
                f"seed{seed} config {field} 漂移: "
                f"expected={value!r}, actual={config.get(field)!r}"
            )
    actual_dataset_dir = (
        FINETUNE / str(config.get("dataset_dir") or "")
    ).resolve()
    if actual_dataset_dir != expected_dataset_dir.resolve():
        raise SourceAware3kRunError(f"seed{seed} dataset_dir 未绑定 sampling_id")
    actual_media_dir = (
        FINETUNE / str(config.get("media_dir") or "")
    ).resolve()
    expected_media_dir = current_data_paths(ROOT).compatibility_workspace.resolve()
    if actual_media_dir != expected_media_dir:
        raise SourceAware3kRunError(f"seed{seed} media_dir 漂移")
    actual_output = (FINETUNE / str(config.get("output_dir") or "")).resolve()
    if actual_output != adapter_dir(seed).resolve():
        raise SourceAware3kRunError(f"seed{seed} output_dir 与运行身份不一致")
    steps = (
        math.ceil(3000 / int(config["gradient_accumulation_steps"]))
        * int(config["num_train_epochs"])
    )
    if steps != 1125:
        raise SourceAware3kRunError(f"seed{seed} optimizer steps 应为 1125")


def _gpu_preflight() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SourceAware3kRunError(f"nvidia-smi 失败: {result.stderr.strip()}")
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise SourceAware3kRunError(f"预期单 GPU，实际 {len(rows)}")
    fields = [field.strip() for field in rows[0].split(",")]
    if len(fields) != 4:
        raise SourceAware3kRunError("无法解析 nvidia-smi GPU 信息")
    free_mib = int(fields[3])
    if free_mib < 20_000:
        raise SourceAware3kRunError(f"GPU 可用显存不足: {free_mib} MiB")
    return {
        "index": int(fields[0]),
        "name": fields[1],
        "memory_total_mib": int(fields[2]),
        "memory_free_mib": free_mib,
    }


def _disk_preflight() -> dict[str, Any]:
    pending_adapters = sum(not _training_complete(seed) for seed in SEEDS)
    pending_merged = sum(not _merged_complete(seed) for seed in SEEDS)
    required = (
        pending_adapters * ESTIMATED_ADAPTER_BYTES
        + pending_merged * ESTIMATED_MERGED_BYTES
        + DISK_RESERVE_BYTES
    )
    usage = shutil.disk_usage(SAVE_ROOT)
    if usage.free < required:
        raise SourceAware3kRunError(
            "Stage B 剩余模型容量不足: "
            f"free={usage.free}, required={required}, "
            f"pending_adapters={pending_adapters}, "
            f"pending_merged={pending_merged}"
        )
    return {
        "filesystem_root": str(SAVE_ROOT.resolve()),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "required_bytes": required,
        "reserve_bytes": DISK_RESERVE_BYTES,
        "pending_adapter_count": pending_adapters,
        "pending_merged_count": pending_merged,
        "estimated_adapter_bytes_each": ESTIMATED_ADAPTER_BYTES,
        "estimated_merged_bytes_each": ESTIMATED_MERGED_BYTES,
    }


def _preflight(*, require_gpu: bool) -> dict[str, Any]:
    manifest = _read_json(RUN_MANIFEST_PATH)
    if (
        manifest.get("schema_version")
        != "tensile-vlm-v4.1-source-aware-3k-run/v1"
        or manifest.get("run_id") != RUN_ID
        or manifest.get("release_id") != RELEASE_ID
        or manifest.get("sampling_id") != SAMPLING_ID
        or manifest.get("expected_optimizer_steps_per_seed") != 1125
    ):
        raise SourceAware3kRunError("run manifest 身份或 optimizer steps 漂移")
    paths = current_data_paths(ROOT)
    release = validate_release(
        ROOT,
        verify_media=True,
        release_id=RELEASE_ID,
    )
    release_manifest = (
        paths.training_releases / RELEASE_ID / "manifest/release_manifest.json"
    )
    if _sha256(release_manifest) != manifest.get("release_manifest_sha256"):
        raise SourceAware3kRunError("release manifest SHA256 漂移")
    sampling_dir, sampling = build_source_aware_3k(
        release_dir=paths.training_releases / RELEASE_ID,
        media_root=paths.compatibility_workspace,
        output_root=paths.metadata / "v4_1/source_aware_3k",
        seeds=SEEDS,
        verify_media=True,
        validate_only=True,
    )
    sampling_manifest = sampling_dir / "sampling_manifest.json"
    if (
        sampling_dir.name != SAMPLING_ID
        or _sha256(sampling_manifest)
        != manifest.get("sampling_manifest_sha256")
        or sampling.get("expected_optimizer_steps_per_seed") != 1125
    ):
        raise SourceAware3kRunError("sampling artifact 身份、哈希或步数漂移")
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise SourceAware3kRunError(f"llamafactory-cli 不存在: {cli}")
    rows = []
    seed_manifest = manifest.get("seeds")
    if not isinstance(seed_manifest, Mapping):
        raise SourceAware3kRunError("run manifest seeds 缺失")
    for seed in SEEDS:
        entry = seed_manifest.get(str(seed))
        if not isinstance(entry, Mapping):
            raise SourceAware3kRunError(f"run manifest 缺少 seed{seed}")
        train_path = CONFIG_ROOT / str(entry.get("train_config") or "")
        merge_path = CONFIG_ROOT / str(entry.get("merge_config") or "")
        if (
            not train_path.is_file()
            or _sha256(train_path) != entry.get("train_config_sha256")
            or not merge_path.is_file()
            or _sha256(merge_path) != entry.get("merge_config_sha256")
        ):
            raise SourceAware3kRunError(f"seed{seed} 配置文件缺失或哈希漂移")
        try:
            config = yaml.safe_load(train_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SourceAware3kRunError(f"seed{seed} 训练配置非法: {exc}") from exc
        if not isinstance(config, Mapping):
            raise SourceAware3kRunError(f"seed{seed} 训练配置不是对象")
        _validate_config(seed, config, expected_dataset_dir=sampling_dir)
        if adapter_dir(seed).exists() and not _training_complete(seed):
            raise SourceAware3kRunError(
                f"拒绝接管不完整训练目录: {adapter_dir(seed)}"
            )
        if merged_dir(seed).exists() and not _merged_complete(seed):
            raise SourceAware3kRunError(
                f"拒绝接管不完整合并目录: {merged_dir(seed)}"
            )
        rows.append(
            {
                "seed": seed,
                "training": "complete" if _training_complete(seed) else "pending",
                "merge": "complete" if _merged_complete(seed) else "pending",
                "evaluation": (
                    "complete" if _evaluation_complete(seed) else "pending_or_resumable"
                ),
            }
        )
    return {
        "run_id": RUN_ID,
        "release": release,
        "sampling": sampling,
        "expected_optimizer_steps_per_seed": 1125,
        "llamafactory_cli": str(cli),
        "gpu": _gpu_preflight() if require_gpu else None,
        "disk": _disk_preflight(),
        "seeds": rows,
    }


def _train(seed: int) -> None:
    if _training_complete(seed):
        return
    _write_state("running", f"seed{seed}_training", seed=seed)
    _run_logged(
        [
            sys.executable,
            "train_with_contract.py",
            str((CONFIG_ROOT / f"train_seed{seed}.yaml").relative_to(FINETUNE)),
        ],
        LOG_ROOT / f"seed{seed}_train.log",
        cwd=FINETUNE,
    )
    if not _training_complete(seed):
        raise SourceAware3kRunError(
            f"seed{seed} 训练产物不完整或 global_step != 1125"
        )
    coverage = validate_adapter_coverage(adapter_dir(seed), visual=True)
    _write_state(
        "running",
        f"seed{seed}_training_complete",
        seed=seed,
        adapter_coverage=coverage,
    )


def _merge(seed: int) -> None:
    if _merged_complete(seed):
        return
    if not _training_complete(seed):
        raise SourceAware3kRunError(f"seed{seed} 尚未完成训练")
    _write_state("running", f"seed{seed}_merging", seed=seed)
    _run_logged(
        [
            str(Path(sys.executable).with_name("llamafactory-cli")),
            "export",
            str((CONFIG_ROOT / f"merge_seed{seed}.yaml").relative_to(FINETUNE)),
        ],
        LOG_ROOT / f"seed{seed}_merge.log",
        cwd=FINETUNE,
    )
    if not _merged_complete(seed):
        raise SourceAware3kRunError(f"seed{seed} 合并产物不完整")


def _evaluate(seed: int) -> None:
    if _evaluation_complete(seed):
        return
    if not _merged_complete(seed):
        raise SourceAware3kRunError(f"seed{seed} 尚未完成合并")
    _write_state(
        "running",
        f"seed{seed}_evaluating",
        seed=seed,
        result_dir=str(result_dir(seed)),
    )
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.run_v4_1_evaluation",
            "--fold",
            "0",
            "--release-id",
            RELEASE_ID,
            "--model-dir",
            str(merged_dir(seed)),
            "--out-dir",
            str(result_dir(seed)),
        ],
        LOG_ROOT / f"seed{seed}_evaluate.log",
        cwd=ROOT,
    )
    if not _evaluation_complete(seed):
        raise SourceAware3kRunError(f"seed{seed} 严格 BF16 评测产物不完整")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument(
        "--phase",
        choices=("train", "merge", "evaluate", "all"),
        default="all",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_gpu = args.validate_only or args.phase in ("train", "evaluate", "all")
    preflight = _preflight(require_gpu=require_gpu)
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0
    selected = (args.seed,) if args.seed is not None else SEEDS
    try:
        for seed in selected:
            if args.phase in ("train", "all"):
                _train(seed)
            if args.phase in ("merge", "all"):
                _merge(seed)
            if args.phase in ("evaluate", "all"):
                _evaluate(seed)
    except Exception as exc:
        _write_state(
            "failed",
            f"stage_b_{args.phase}",
            seeds=list(selected),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    _write_state(
        "completed",
        f"stage_b_{args.phase}_complete",
        seeds=list(selected),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
