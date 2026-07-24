"""Evaluate the formal V4.1 visual-LoRA models with bnb 4-bit inference."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from finetune.run_v4_1_visual_three_fold import (
    EXPECTED_EVALUATION_COUNTS,
    FOLDS,
    RESULT_ROOT as BF16_RESULT_ROOT,
    RUN_ID,
)
from finetune.validation.model_runtime import FOUR_BIT_INFERENCE_PRECISION
from finetune.v4_1_runtime import RELEASE_ID, validate_release

ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
LOG_ROOT = FINETUNE / "run_logs" / RUN_ID / "four_bit_evaluation"
RESULT_ROOT = FINETUNE / "results" / RUN_ID / "four_bit_validation"
STATE_PATH = LOG_ROOT / "state.json"
INFERENCE_PRECISION = FOUR_BIT_INFERENCE_PRECISION
METRIC_NAMES = (
    "contract_valid_rate",
    "joint_correct_rate",
    "clip_state_correct_rate",
    "fracture_mechanism_correct_rate",
    "fracture_site_correct_rate",
    "special_case_correct_rate",
)
PREDICTION_FIELDS = (
    "clip_state",
    "fracture_mechanism",
    "fracture_site",
    "special_case",
)


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DOWNSAMPLE_MODE": "4x",
            "DISABLE_VERSION_CHECK": "1",
            "PYTHONPATH": f"{ROOT / 'LlamaFactory/src'}:{ROOT}",
        }
    )
    return env


def _write_state(status: str, stage: str, **extra: Any) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "tensile-v4.1-visual-4bit-evaluation/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
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


def _result_dir(fold_index: int) -> Path:
    return RESULT_ROOT / f"fold{fold_index}"


def _evaluation_complete(fold_index: int) -> bool:
    result_dir = _result_dir(fold_index)
    paths = (
        result_dir / "run_identity.json",
        result_dir / "evaluation_summary.json",
        result_dir / "evaluation_records.jsonl",
        result_dir / "runtime_failures.csv",
    )
    if not all(path.is_file() for path in paths):
        return False
    try:
        identity = _read_json(paths[0])
        summary = _read_json(paths[1])
        record_count = sum(
            bool(line.strip())
            for line in paths[2].read_text(encoding="utf-8").splitlines()
        )
    except (OSError, json.JSONDecodeError):
        return False
    expected = EXPECTED_EVALUATION_COUNTS[fold_index]
    return (
        identity.get("inference_precision") == INFERENCE_PRECISION
        and summary.get("inference_precision") == INFERENCE_PRECISION
        and summary.get("sample_count") == expected
        and summary.get("total_samples") == expected
        and summary.get("runtime_failure_count") == 0
        and record_count == expected
    )


def _run_logged(command: list[str], log_path: Path) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=_runtime_env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"命令退出码 {result.returncode}，请查看 {log_path}"
        )


def _evaluate(fold_index: int, model_dir: Path) -> None:
    if _evaluation_complete(fold_index):
        return
    _write_state("running", f"fold{fold_index}_evaluating")
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.run_v4_1_evaluation",
            "--fold",
            str(fold_index),
            "--model-dir",
            str(model_dir),
            "--out-dir",
            str(_result_dir(fold_index)),
            "--quantization-bit",
            "4",
        ],
        LOG_ROOT / f"fold{fold_index}_evaluate.log",
    )
    if not _evaluation_complete(fold_index):
        raise RuntimeError(f"fold{fold_index}: 4-bit 评测产物不完整")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _read_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        candidate_id = record.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in records:
            raise RuntimeError(
                f"{path}:{line_number}: invalid or duplicate candidate_id"
            )
        records[candidate_id] = record
    return records


def _prediction_state(record: Mapping[str, Any]) -> str:
    prediction = record.get("prediction")
    if not isinstance(prediction, Mapping):
        return "__invalid__"
    return str(prediction.get("clip_state"))


def compare_record_sets(
    bf16_records: Mapping[str, Mapping[str, Any]],
    four_bit_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if set(bf16_records) != set(four_bit_records):
        raise RuntimeError("BF16 与 4-bit 的候选集合不一致")
    total = len(bf16_records)
    exact_matches = 0
    strict_valid_matches = 0
    both_valid = 0
    field_matches: Counter[str] = Counter()
    transitions: dict[str, Counter[str]] = defaultdict(Counter)
    changed_candidate_ids: list[str] = []
    for candidate_id in sorted(bf16_records):
        bf16 = bf16_records[candidate_id]
        four_bit = four_bit_records[candidate_id]
        if bf16.get("target") != four_bit.get("target"):
            raise RuntimeError(f"{candidate_id}: target 不一致")
        if bf16.get("sampled_timestamps") != four_bit.get(
            "sampled_timestamps"
        ):
            raise RuntimeError(f"{candidate_id}: 输入帧时间戳不一致")
        bf16_valid = isinstance(bf16.get("prediction"), Mapping)
        four_bit_valid = isinstance(four_bit.get("prediction"), Mapping)
        strict_valid_matches += bf16_valid == four_bit_valid
        transitions[_prediction_state(bf16)][_prediction_state(four_bit)] += 1
        if not (bf16_valid and four_bit_valid):
            changed_candidate_ids.append(candidate_id)
            continue
        both_valid += 1
        bf16_prediction = bf16["prediction"]
        four_bit_prediction = four_bit["prediction"]
        if bf16_prediction == four_bit_prediction:
            exact_matches += 1
        else:
            changed_candidate_ids.append(candidate_id)
        for field in PREDICTION_FIELDS:
            field_matches[field] += (
                bf16_prediction.get(field) == four_bit_prediction.get(field)
            )
    return {
        "total_samples": total,
        "both_strict_valid_count": both_valid,
        "strict_valid_status_agreement_rate": (
            round(strict_valid_matches / total, 6) if total else None
        ),
        "exact_prediction_match_rate": (
            round(exact_matches / total, 6) if total else None
        ),
        "exact_prediction_match_rate_among_both_valid": (
            round(exact_matches / both_valid, 6) if both_valid else None
        ),
        "field_agreement_rates": {
            field: round(field_matches[field] / total, 6) if total else None
            for field in PREDICTION_FIELDS
        },
        "changed_candidate_count": len(changed_candidate_ids),
        "changed_candidate_ids": changed_candidate_ids,
        "clip_state_transition": {
            source: dict(sorted(targets.items()))
            for source, targets in sorted(transitions.items())
        },
    }


def _weighted_metrics(summaries: list[Mapping[str, Any]]) -> dict[str, float]:
    total = sum(int(summary["sample_count"]) for summary in summaries)
    return {
        name: round(
            sum(
                float(summary["metrics"][name])
                * int(summary["sample_count"])
                for summary in summaries
            )
            / total,
            6,
        )
        for name in METRIC_NAMES
    }


def _write_summaries() -> tuple[Path, Path]:
    four_bit_summaries = [
        _read_json(_result_dir(fold.index) / "evaluation_summary.json")
        for fold in FOLDS
    ]
    bf16_summaries = [
        _read_json(
            BF16_RESULT_ROOT / f"fold{fold.index}/evaluation_summary.json"
        )
        for fold in FOLDS
    ]
    four_bit_metrics = _weighted_metrics(four_bit_summaries)
    bf16_metrics = _weighted_metrics(bf16_summaries)
    summary_path = RESULT_ROOT / "three_fold_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "tensile-v4.1-visual-three-fold-summary/v1"
                ),
                "run_id": RUN_ID,
                "release_id": RELEASE_ID,
                "inference_precision": INFERENCE_PRECISION,
                "fold_count": len(FOLDS),
                "total_samples": sum(
                    int(summary["sample_count"])
                    for summary in four_bit_summaries
                ),
                "weighted_metrics": four_bit_metrics,
                "folds": [
                    {
                        "fold": fold.index,
                        "sample_count": summary["sample_count"],
                        "metrics": summary["metrics"],
                        "target_clip_state_distribution": summary[
                            "target_clip_state_distribution"
                        ],
                        "prediction_clip_state_distribution": summary[
                            "prediction_clip_state_distribution"
                        ],
                        "clip_state_confusion": summary[
                            "clip_state_confusion"
                        ],
                    }
                    for fold, summary in zip(
                        FOLDS,
                        four_bit_summaries,
                        strict=True,
                    )
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    bf16_records: dict[str, dict[str, Any]] = {}
    four_bit_records: dict[str, dict[str, Any]] = {}
    for fold in FOLDS:
        bf16_records.update(
            _read_records(
                BF16_RESULT_ROOT
                / f"fold{fold.index}/evaluation_records.jsonl"
            )
        )
        four_bit_records.update(
            _read_records(
                _result_dir(fold.index) / "evaluation_records.jsonl"
            )
        )
    consistency = compare_record_sets(bf16_records, four_bit_records)
    consistency.update(
        {
            "schema_version": "tensile-v4.1-bf16-4bit-consistency/v1",
            "run_id": RUN_ID,
            "release_id": RELEASE_ID,
            "bf16_metrics": bf16_metrics,
            "four_bit_metrics": four_bit_metrics,
            "metric_deltas_four_bit_minus_bf16": {
                name: round(
                    four_bit_metrics[name] - bf16_metrics[name],
                    6,
                )
                for name in METRIC_NAMES
            },
        }
    )
    consistency_path = RESULT_ROOT / "bf16_4bit_consistency.json"
    consistency_path.write_text(
        json.dumps(consistency, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary_path, consistency_path


def main() -> int:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    validate_release(ROOT, verify_media=True)
    try:
        for fold in FOLDS:
            if not fold.merged_dir.is_dir():
                raise RuntimeError(f"合并模型不存在: {fold.merged_dir}")
            _evaluate(fold.index, fold.merged_dir)
        summary_path, consistency_path = _write_summaries()
    except Exception as exc:
        _write_state(
            "failed",
            "four_bit_evaluation",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    _write_state(
        "completed",
        "four_bit_evaluation_complete",
        summary=str(summary_path),
        consistency=str(consistency_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
