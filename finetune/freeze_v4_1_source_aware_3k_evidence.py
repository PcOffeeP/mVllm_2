#!/usr/bin/env python3
"""Freeze content-addressed Stage B evidence after both seeds pass every gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_visual_data_experiment import validate_adapter_coverage
from finetune.run_v4_1_source_aware_3k import (
    CONFIG_ROOT,
    LOG_ROOT,
    RELEASE_ID,
    RESULT_ROOT,
    RUN_ID,
    RUN_MANIFEST_PATH,
    SAMPLING_ID,
    SEEDS,
    adapter_dir,
    merged_dir,
)
from pipeline.current_data import current_data_paths

MODEL_METADATA_NAMES = {
    "adapter_config.json",
    "all_results.json",
    "chat_template.jinja",
    "config.json",
    "eval_results.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "processor_config.json",
    "tokenizer_config.json",
    "train_results.json",
    "trainer_state.json",
}


class StageBEvidenceError(ValueError):
    """Stage B is incomplete, failed, drifted, or cannot be frozen safely."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageBEvidenceError(f"无法读取 JSON {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StageBEvidenceError(f"证据文件不存在: {path}")
    return {
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _aggregate_identity(files: Mapping[str, Mapping[str, Any]]) -> str:
    payload = json.dumps(
        files,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise StageBEvidenceError("无法读取训练仓库 HEAD")
    return result.stdout.strip()


def _selected_model_files(path: Path, *, full: bool) -> list[Path]:
    if not path.is_dir():
        raise StageBEvidenceError(f"模型目录不存在: {path}")
    selected = []
    for child in sorted(path.iterdir()):
        if not child.is_file():
            continue
        if child.name in MODEL_METADATA_NAMES:
            selected.append(child)
        elif full and child.suffix == ".safetensors":
            selected.append(child)
    if not selected:
        raise StageBEvidenceError(f"模型目录缺少身份文件: {path}")
    return selected


def _model_identity(path: Path, *, full: bool) -> dict[str, Any]:
    files = {
        child.name: _identity(child)
        for child in _selected_model_files(path, full=full)
    }
    return {
        "path_at_freeze": str(path.resolve()),
        "hash_mode": "full" if full else "metadata",
        "files": files,
        "aggregate_sha256": _aggregate_identity(files),
    }


def _verify_trainer_state(path: Path) -> dict[str, Any]:
    state = _read_json(path)
    if not isinstance(state, Mapping) or state.get("global_step") != 1125:
        raise StageBEvidenceError(f"{path}: global_step 必须为 1125")
    log_history = state.get("log_history")
    if not isinstance(log_history, list) or not log_history:
        raise StageBEvidenceError(f"{path}: log_history 缺失")
    return {
        "global_step": state["global_step"],
        "epoch": state.get("epoch"),
        "best_model_checkpoint": state.get("best_model_checkpoint"),
        "best_metric": state.get("best_metric"),
    }


def _verify_gate_report(path: Path) -> dict[str, Any]:
    report = _read_json(path)
    if (
        not isinstance(report, Mapping)
        or report.get("schema_version")
        != "tensile-vlm-v4.1-source-aware-3k-gates/v1"
        or report.get("run_id") != RUN_ID
        or report.get("release_id") != RELEASE_ID
        or report.get("passed") is not True
    ):
        raise StageBEvidenceError("Stage B gate report 未通过或身份漂移")
    seeds = report.get("seeds")
    if (
        not isinstance(seeds, list)
        or [item.get("seed") for item in seeds if isinstance(item, Mapping)]
        != list(SEEDS)
        or any(item.get("passed") is not True for item in seeds)
    ):
        raise StageBEvidenceError("Stage B 两个 seed 未全部通过")
    return dict(report)


def _collect_result_files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    gate_path = RESULT_ROOT / "stage_b_gate_report.json"
    _verify_gate_report(gate_path)
    files[str(gate_path.relative_to(ROOT))] = _identity(gate_path)
    for seed in SEEDS:
        root = RESULT_ROOT / f"seed{seed}/fold0"
        training_manifest = (
            RESULT_ROOT / f"seed{seed}/training_run_manifest.json"
        )
        training_payload = _read_json(training_manifest)
        if (
            not isinstance(training_payload, Mapping)
            or training_payload.get("seed") != seed
            or training_payload.get("training_code_commit")
            != "f6ba152121d394141ddddaf73926e3a9c065d0a8"
            or training_payload.get("launch_run_manifest_sha256")
            != "9f7a025a676310b0bda8495f715caaf2a219933247542693aac3471f44558db6"
            or training_payload.get("actual_optimizer_steps") != 1125
        ):
            raise StageBEvidenceError(f"seed{seed} 训练 run manifest 非法")
        files[str(training_manifest.relative_to(ROOT))] = _identity(
            training_manifest
        )
        for name in (
            "run_identity.json",
            "evaluation_records.jsonl",
            "evaluation_summary.json",
            "runtime_failures.csv",
        ):
            path = root / name
            files[str(path.relative_to(ROOT))] = _identity(path)
        summary = _read_json(root / "evaluation_summary.json")
        if (
            summary.get("release_id") != RELEASE_ID
            or summary.get("sample_count") != 425
            or summary.get("total_samples") != 425
            or summary.get("strict_valid_rate") != 1.0
            or summary.get("runtime_failure_count") != 0
        ):
            raise StageBEvidenceError(f"seed{seed} 严格评测摘要不满足冻结门")
        record_count = sum(
            bool(line.strip())
            for line in (root / "evaluation_records.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if record_count != 425:
            raise StageBEvidenceError(f"seed{seed} 逐样本记录数不是 425")
    return files


def _collect_run_files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in (
        RUN_MANIFEST_PATH,
        *(CONFIG_ROOT / f"train_seed{seed}.yaml" for seed in SEEDS),
        *(CONFIG_ROOT / f"merge_seed{seed}.yaml" for seed in SEEDS),
    ):
        files[str(path.relative_to(ROOT))] = _identity(path)
    for seed in SEEDS:
        for name in (
            f"seed{seed}_train.log",
            f"seed{seed}_merge.log",
            f"seed{seed}_evaluate.log",
        ):
            path = LOG_ROOT / name
            files[str(path.relative_to(ROOT))] = _identity(path)
    return files


def _sampling_identity() -> dict[str, Any]:
    paths = current_data_paths(ROOT)
    root = paths.metadata / "v4_1/source_aware_3k" / SAMPLING_ID
    summary = _read_json(root / "summary.json")
    if (
        not isinstance(summary, Mapping)
        or summary.get("sampling_id") != SAMPLING_ID
        or summary.get("release_id") != RELEASE_ID
        or summary.get("expected_optimizer_steps_per_seed") != 1125
    ):
        raise StageBEvidenceError("sampling summary 身份或步数漂移")
    files = {}
    for entry in summary.get("files") or []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise StageBEvidenceError("sampling summary files 非法")
        path = root / entry["path"]
        identity = _identity(path)
        if (
            identity["size_bytes"] != entry.get("size_bytes")
            or identity["sha256"] != entry.get("sha256")
        ):
            raise StageBEvidenceError(f"sampling 文件漂移: {path}")
        files[entry["path"]] = identity
    summary_identity = _identity(root / "summary.json")
    return {
        "path_at_freeze": str(root.resolve()),
        "summary": summary_identity,
        "files": files,
        "aggregate_sha256": _aggregate_identity(files),
    }


def build_manifest(*, model_hash_mode: str) -> tuple[str, dict[str, Any]]:
    if model_hash_mode not in {"full", "metadata"}:
        raise StageBEvidenceError("model_hash_mode 必须是 full 或 metadata")
    full = model_hash_mode == "full"
    result_files = _collect_result_files()
    run_files = _collect_run_files()
    models = {}
    trainer_states = {}
    adapter_coverage = {}
    for seed in SEEDS:
        trainer_states[str(seed)] = _verify_trainer_state(
            adapter_dir(seed) / "trainer_state.json"
        )
        adapter_coverage[str(seed)] = validate_adapter_coverage(
            adapter_dir(seed),
            visual=True,
        )
        models[f"seed{seed}_adapter"] = _model_identity(
            adapter_dir(seed),
            full=full,
        )
        models[f"seed{seed}_merged_bf16"] = _model_identity(
            merged_dir(seed),
            full=full,
        )
    sampling = _sampling_identity()
    manifest = {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-evidence/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "sampling_id": SAMPLING_ID,
        "training_repo_commit": _git_head(),
        "model_hash_mode": model_hash_mode,
        "trainer_states": trainer_states,
        "adapter_coverage": adapter_coverage,
        "sampling_artifact": sampling,
        "run_files": run_files,
        "result_files": result_files,
        "model_artifacts": models,
        "run_files_aggregate_sha256": _aggregate_identity(run_files),
        "result_files_aggregate_sha256": _aggregate_identity(result_files),
        "model_artifacts_aggregate_sha256": _aggregate_identity(
            {
                name: {
                    "size_bytes": 0,
                    "sha256": value["aggregate_sha256"],
                }
                for name, value in models.items()
            }
        ),
    }
    seed = {
        "schema_version": manifest["schema_version"],
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "sampling_id": SAMPLING_ID,
        "training_repo_commit": manifest["training_repo_commit"],
        "model_hash_mode": model_hash_mode,
        "sampling_aggregate_sha256": sampling["aggregate_sha256"],
        "run_files_aggregate_sha256": manifest["run_files_aggregate_sha256"],
        "result_files_aggregate_sha256": manifest[
            "result_files_aggregate_sha256"
        ],
        "model_artifacts_aggregate_sha256": manifest[
            "model_artifacts_aggregate_sha256"
        ],
    }
    evidence_id = (
        "stage-b-evidence-"
        + hashlib.sha256(
            json.dumps(
                seed,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:12]
    )
    manifest["evidence_id"] = evidence_id
    return evidence_id, manifest


def _write_immutable(target: Path, manifest: Mapping[str, Any]) -> None:
    content = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    if target.exists():
        path = target / "evidence_manifest.json"
        if not path.is_file() or path.read_bytes() != content:
            raise StageBEvidenceError(f"拒绝覆盖已有 Stage B evidence: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        (staging / "evidence_manifest.json").write_bytes(content)
        os.replace(staging, target)
    finally:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=RESULT_ROOT / "evidence_freeze",
    )
    parser.add_argument(
        "--model-hash-mode",
        choices=("full", "metadata"),
        default="full",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_id, manifest = build_manifest(
        model_hash_mode=args.model_hash_mode,
    )
    output_dir = args.output_root / evidence_id
    if not args.validate_only:
        _write_immutable(output_dir, manifest)
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "frozen",
                "output_dir": str(output_dir),
                "evidence_id": evidence_id,
                "manifest": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
