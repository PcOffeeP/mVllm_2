"""Freeze lightweight, content-addressed evidence for the formal V4.1 visual run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


VARIANTS = {
    "merged_bf16": "three_fold_validation",
    "merged_requantized_4bit": "four_bit_validation",
    "adapter_direct_4bit": "four_bit_adapter_validation",
}
CLIP_STATES = ("未断裂", "临界未断裂", "发生断裂", "已断裂", "无法判断")
FOUR_OBSERVED_STATES = ("未断裂", "临界未断裂", "发生断裂", "已断裂")
FRACTURE_STATES = ("临界未断裂", "发生断裂", "已断裂")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--ablation-root", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--model-hash-mode",
        choices=("full", "metadata"),
        default="full",
        help="Use metadata in unit tests; formal evidence must use full.",
    )
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> dict[str, Any]:
    return {
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _aggregate_identity(files: dict[str, dict[str, Any]]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in seen:
            raise RuntimeError(f"{path}:{line_no}: invalid or duplicate candidate_id")
        seen.add(candidate_id)
        records.append(row)
    return records


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _class_metrics(
    records: Iterable[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    rows = list(records)
    true_positive = 0
    false_positive = 0
    false_negative = 0
    support = 0
    predicted = 0
    for row in rows:
        target = row["target"]["clip_state"]
        prediction = row.get("prediction")
        predicted_state = prediction.get("clip_state") if isinstance(prediction, dict) else "__invalid__"
        support += target == label
        predicted += predicted_state == label
        true_positive += target == label and predicted_state == label
        false_positive += target != label and predicted_state == label
        false_negative += target == label and predicted_state != label
    precision = _rate(true_positive, true_positive + false_positive)
    recall = _rate(true_positive, true_positive + false_negative)
    f1 = (
        round(2 * precision * recall / (precision + recall), 6)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "support": support,
        "predicted": predicted,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _macro_recall(class_metrics: dict[str, dict[str, Any]], labels: Iterable[str]) -> float | None:
    recalls = [class_metrics[label]["recall"] for label in labels]
    present = [value for value in recalls if value is not None]
    return round(sum(present) / len(present), 6) if present else None


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    class_metrics = {label: _class_metrics(records, label) for label in CLIP_STATES}
    special_targets = Counter(
        str(row["target"].get("special_case"))
        for row in records
    )
    return {
        "sample_count": len(records),
        "unique_candidate_count": len({row["candidate_id"] for row in records}),
        "strict_invalid_count": sum(row.get("strict_valid") is not True for row in records),
        "runtime_failure_count": sum(bool(row.get("runtime_error")) for row in records),
        "hit_token_limit_count": sum(row.get("hit_token_limit") is True for row in records),
        "clip_state_class_metrics": class_metrics,
        "fracture_three_state_macro_recall": _macro_recall(class_metrics, FRACTURE_STATES),
        "four_observed_state_macro_recall": _macro_recall(class_metrics, FOUR_OBSERVED_STATES),
        "target_special_case_distribution": dict(sorted(special_targets.items())),
    }


def _runtime_failure_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as source:
        return sum(1 for _ in csv.DictReader(source))


def _collect_result_variant(
    run_root: Path,
    relative_dir: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    variant_root = run_root / relative_dir
    all_records: list[dict[str, Any]] = []
    seen_across_folds: set[str] = set()
    result_files: dict[str, dict[str, Any]] = {}
    folds: dict[str, Any] = {}
    for fold in range(3):
        fold_root = variant_root / f"fold{fold}"
        record_path = fold_root / "evaluation_records.jsonl"
        records = _load_records(record_path)
        overlap = seen_across_folds.intersection(row["candidate_id"] for row in records)
        if overlap:
            raise RuntimeError(f"{variant_root}: candidates overlap across folds: {sorted(overlap)[:3]}")
        seen_across_folds.update(row["candidate_id"] for row in records)
        all_records.extend(records)
        failure_path = fold_root / "runtime_failures.csv"
        if _runtime_failure_count(failure_path) != 0:
            raise RuntimeError(f"{failure_path}: runtime failures are not zero")
        folds[f"fold{fold}"] = _summarize_records(records)
        for path in (
            record_path,
            fold_root / "evaluation_summary.json",
            fold_root / "run_identity.json",
            failure_path,
        ):
            result_files[str(path.relative_to(run_root))] = _file_identity(path)
    for name in ("three_fold_summary.json", "bf16_4bit_consistency.json"):
        path = variant_root / name
        if path.exists():
            result_files[str(path.relative_to(run_root))] = _file_identity(path)
    return {
        "folds": folds,
        "aggregate": _summarize_records(all_records),
    }, all_records, result_files


def _invalid_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    invalid = [row for row in records if row.get("strict_valid") is not True]
    missing_special = [
        row
        for row in invalid
        if isinstance(row.get("raw_output"), str)
        and '"special_case"' not in row["raw_output"]
    ]
    details = [
        {
            "candidate_id": row["candidate_id"],
            "source_video": row.get("source_video"),
            "target_clip_state": row["target"]["clip_state"],
            "parse_error": row.get("parse_error"),
            "generated_token_count": row.get("generated_token_count"),
            "hit_token_limit": row.get("hit_token_limit"),
            "raw_output": row.get("raw_output"),
        }
        for row in invalid
    ]
    return {
        "strict_invalid_count": len(invalid),
        "runtime_failure_count": sum(bool(row.get("runtime_error")) for row in invalid),
        "hit_token_limit_count": sum(row.get("hit_token_limit") is True for row in invalid),
        "missing_special_case_field_count": len(missing_special),
        "parse_error_distribution": dict(
            sorted(Counter(str(row.get("parse_error")) for row in invalid).items())
        ),
        "target_clip_state_distribution": dict(
            sorted(Counter(row["target"]["clip_state"] for row in invalid).items())
        ),
        "source_video_distribution": dict(
            sorted(Counter(str(row.get("source_video")) for row in invalid).items())
        ),
        "root_cause": (
            "All strict-invalid outputs omitted the required special_case field; "
            "none hit the generation token limit or raised a runtime error."
            if invalid and len(missing_special) == len(invalid)
            else "Mixed causes; inspect details."
        ),
        "policy": (
            "Keep strict-invalid. Do not auto-fill special_case=null in the parser; "
            "that would hide a model contract failure."
        ),
        "details": details,
    }


def _selected_model_files(path: Path, *, full: bool) -> list[Path]:
    selected: list[Path] = []
    for child in sorted(path.iterdir()):
        if not child.is_file():
            continue
        if child.name in MODEL_METADATA_NAMES:
            selected.append(child)
        elif full and child.suffix == ".safetensors":
            selected.append(child)
    if not selected:
        raise RuntimeError(f"no identity files found in model directory: {path}")
    return selected


def _model_identity(path: Path, *, full: bool) -> dict[str, Any]:
    files = {
        child.name: _file_identity(child)
        for child in _selected_model_files(path, full=full)
    }
    return {
        "path_at_freeze": str(path),
        "hash_mode": "full" if full else "metadata",
        "files": files,
        "aggregate_sha256": _aggregate_identity(files),
    }


def _discover_model_paths(run_root: Path) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    for variant_name, relative_dir in VARIANTS.items():
        for fold in range(3):
            identity = _read_json(run_root / relative_dir / f"fold{fold}" / "run_identity.json")
            model_dir = Path(identity["model_dir"])
            role = "base" if identity.get("adapter_dir") else "merged"
            discovered[f"{role}_fold{fold}_{variant_name}"] = model_dir
            if identity.get("adapter_dir"):
                discovered[f"adapter_fold{fold}"] = Path(identity["adapter_dir"])
    unique_by_path: dict[str, Path] = {}
    for path in discovered.values():
        unique_by_path[str(path.resolve())] = path
    return {
        f"artifact_{index:02d}": path
        for index, path in enumerate(sorted(unique_by_path.values(), key=lambda item: str(item)))
    }


def freeze(args: argparse.Namespace) -> None:
    run_root = args.run_root.resolve()
    ablation_root = args.ablation_root.resolve()
    output_dir = args.output_dir.resolve()
    repo_root = Path(__file__).resolve().parents[2]
    contract = _read_json(args.contract)
    release = _read_json(args.release_manifest)
    if contract.get("contract_version") != "tensile-vlm/v4.1":
        raise RuntimeError("unexpected contract version")
    metrics: dict[str, Any] = {}
    all_variant_records: dict[str, list[dict[str, Any]]] = {}
    result_files: dict[str, dict[str, Any]] = {}
    for variant_name, relative_dir in VARIANTS.items():
        summary, records, files = _collect_result_variant(run_root, relative_dir)
        metrics[variant_name] = summary
        all_variant_records[variant_name] = records
        result_files.update(files)

    ablation_files: dict[str, dict[str, Any]] = {}
    for path in sorted(ablation_root.glob("**/*")):
        if path.is_file() and path.name in {
            "comparison_summary.json",
            "evaluation_records.jsonl",
            "evaluation_summary.json",
            "run_identity.json",
            "runtime_failures.csv",
        }:
            ablation_files[str(path.relative_to(ablation_root))] = _file_identity(path)

    full_hashes = args.model_hash_mode == "full"
    models = {
        name: _model_identity(path.resolve(), full=full_hashes)
        for name, path in _discover_model_paths(run_root).items()
    }
    manifest = {
        "schema_version": "tensile-v4.1-evidence-freeze/v1",
        "run_id": run_root.name,
        "release_id": release.get("release_id"),
        "release_manifest": _file_identity(args.release_manifest),
        "contract_version": contract["contract_version"],
        "contract_hash": contract["contract_hash"],
        "contract_artifact": _file_identity(args.contract),
        "training_repo_commit": _git_head(repo_root),
        "result_files": result_files,
        "ablation_files": ablation_files,
        "model_artifacts": models,
    }
    manifest["result_files_aggregate_sha256"] = _aggregate_identity(result_files)
    manifest["ablation_files_aggregate_sha256"] = _aggregate_identity(ablation_files)
    manifest["model_artifacts_aggregate_sha256"] = _aggregate_identity(
        {
            name: {"sha256": value["aggregate_sha256"], "size_bytes": 0}
            for name, value in models.items()
        }
    )
    _write_json(output_dir / "evidence_manifest.json", manifest)
    _write_json(output_dir / "metrics_report.json", metrics)
    _write_json(
        output_dir / "invalid_output_analysis.json",
        _invalid_analysis(all_variant_records["merged_bf16"]),
    )


def main() -> None:
    freeze(parse_args())


if __name__ == "__main__":
    main()
