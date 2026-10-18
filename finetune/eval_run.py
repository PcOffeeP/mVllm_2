"""Run resumable strict V4.1 inference on one released validation fold."""

from __future__ import annotations

import sys


def main() -> int:
    message = (
        "此历史训练/评测 CLI 已停用。请使用 python -m versioning eval "
        "prepare / validate / run / export，显式指定 --root 和完整版本身份。"
        "参数与冻结输入说明见 versioning/SCRIPTS.md；不接受旧 YAML 或裸模型路径直接启动。"
    )
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from finetune.v4_1_runtime import (
    CONTRACT_VERSION,
    _load_active_release_id,
    RELEASE_SCHEMA_VERSION,
    V4_1FinetuneError,
    parse_v4_1_output,
    release_dir,
    score_v4_1_prediction,
    summarize_v4_1_scores,
    validate_release,
    validate_training_row,
)
from finetune.validation.model_runtime import (
    FOUR_BIT_ADAPTER_INFERENCE_PRECISION,
    FOUR_BIT_INFERENCE_PRECISION,
    load_model,
    run_model_on_video_detailed,
)
from pipeline.current_data import current_data_paths
from pipeline.data_roots import resolve_workspace_artifact
from pipeline.prompt_control import load_experiment_contract
from pipeline.prompt_control.core import PromptControlError, sha256_file
from pipeline.v4_1_production_contract import EXPECTED_CONTRACT_HASH

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pipeline/contracts/tensile_vlm_v4_1.json"
RUNTIME_CONTRACT_HASH = EXPECTED_CONTRACT_HASH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, required=True, choices=(0, 1, 2))
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--quantization-bit", type=int, choices=(4,))
    parser.add_argument("--adapter-dir", type=Path)
    parser.add_argument("--release-id", default=None)
    parser.add_argument(
        "--expected-contract-hash",
        default=None,
        help="待评测 release 必须绑定的训练契约 hash",
    )
    parser.add_argument(
        "--expected-release-schema",
        default=None,
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument(
        "--experiment-contract",
        type=Path,
        help="新 V4.1 实验必须使用的自包含 Prompt contract",
    )
    prompt_group.add_argument(
        "--analysis-prompt-overlay",
        type=Path,
        help="仅用于复现历史 overlay 实验；新实验禁止使用",
    )
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_contract(
    prompt_overlay_path: Path | None = None,
    *,
    experiment_contract_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    contract = _read_json(CONTRACT_PATH)
    normalized = dict(contract) if isinstance(contract, Mapping) else {}
    normalized.pop("contract_hash", None)
    actual_hash = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if (
        not isinstance(contract, dict)
        or contract.get("contract_version") != CONTRACT_VERSION
        or contract.get("contract_hash") != actual_hash
        or actual_hash != RUNTIME_CONTRACT_HASH
    ):
        raise RuntimeError("V4.1 contract identity drifted")
    analysis = contract.get("analysis")
    if not isinstance(analysis, Mapping):
        raise RuntimeError("V4.1 contract analysis section is missing")
    if prompt_overlay_path is not None and experiment_contract_path is not None:
        raise RuntimeError("Prompt overlay 与 experiment contract 不能同时使用")
    if experiment_contract_path is not None:
        try:
            experiment = load_experiment_contract(experiment_contract_path)
        except PromptControlError as exc:
            raise RuntimeError(str(exc)) from exc
        if experiment.get("generation") != analysis.get("generation"):
            raise RuntimeError("experiment contract generation 与 V4.1 contract 不一致")
        prompt = experiment["prompt"]
        revised = dict(contract)
        revised["analysis"] = {
            **dict(analysis),
            "system_prompt": prompt["system_prompt"],
            "user_prompt": prompt["user_prompt"],
        }
        identity = {
            "schema_version": experiment["schema_version"],
            "path": str(Path(experiment_contract_path).resolve()),
            "file_sha256": sha256_file(Path(experiment_contract_path)),
            "experiment_contract_sha256": experiment[
                "experiment_contract_sha256"
            ],
            "prompt_revision_id": prompt["revision_id"],
            "prompt_manifest_sha256": prompt["prompt_manifest_sha256"],
            "prompt_content_sha256": prompt["prompt_content_sha256"],
        }
        return revised, identity
    if prompt_overlay_path is None:
        return contract, None
    overlay = _read_json(prompt_overlay_path)
    overlay_analysis = (
        overlay.get("analysis") if isinstance(overlay, Mapping) else None
    )
    if (
        not isinstance(overlay, Mapping)
        or overlay.get("schema_version")
        != "tensile-vlm-v4.1-analysis-prompt-overlay/v1"
        or overlay.get("base_contract_version") != CONTRACT_VERSION
        or not isinstance(overlay.get("prompt_revision_id"), str)
        or not isinstance(overlay_analysis, Mapping)
        or not isinstance(overlay_analysis.get("system_prompt"), str)
        or not isinstance(overlay_analysis.get("user_prompt"), str)
        or overlay_analysis.get("generation") != analysis.get("generation")
    ):
        raise RuntimeError("V4.1 analysis prompt overlay identity drifted")
    base_hash = overlay.get("base_contract_hash")
    promoted_overlay = (
        base_hash != actual_hash and dict(overlay_analysis) == dict(analysis)
    )
    if base_hash != actual_hash and not promoted_overlay:
        raise RuntimeError("V4.1 analysis prompt overlay base contract drifted")
    revised = dict(contract)
    revised["analysis"] = dict(overlay_analysis)
    identity = {
        "prompt_revision_id": overlay["prompt_revision_id"],
        "prompt_overlay_sha256": _sha256(prompt_overlay_path),
        "promoted_to_contract_hash": actual_hash,
        "historical_base_contract_hash": base_hash,
    }
    return revised, identity


def load_validation_samples(
    fold: int,
    *,
    release_id: str | None = None,
) -> list[dict[str, Any]]:
    path = release_dir(ROOT, release_id or _load_active_release_id()) / f"datasets/validation/fold_{fold}.json"
    rows = _read_json(path)
    if not isinstance(rows, list):
        raise RuntimeError(f"validation dataset must be a list: {path}")
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        video_path, labels = validate_training_row(
            row,
            f"fold_{fold}_val",
            index,
        )
        candidate_id = Path(video_path).stem
        if candidate_id in seen:
            raise RuntimeError(f"duplicate validation candidate: {candidate_id}")
        seen.add(candidate_id)
        source_match = re.match(r"(video_\d+)", candidate_id)
        samples.append(
            {
                "candidate_id": candidate_id,
                "source_video": source_match.group(1) if source_match else None,
                "video_path": video_path,
                "target": labels,
            }
        )
    return samples


def _run_identity(
    fold: int,
    model_dir: Path,
    sample_count: int,
    *,
    release_id: str | None = None,
    quantization_bit: int | None = None,
    adapter_dir: Path | None = None,
    prompt_overlay_identity: Mapping[str, Any] | None = None,
    experiment_contract_identity: Mapping[str, Any] | None = None,
    contract_hash: str = RUNTIME_CONTRACT_HASH,
) -> dict[str, Any]:
    identity = {
        "schema_version": "tensile-v4.1-evaluation-run/v1",
        "release_id": release_id or _load_active_release_id(),
        "contract_version": CONTRACT_VERSION,
        "contract_hash": contract_hash,
        "fold": fold,
        "model_dir": str(model_dir.resolve()),
        "sample_count": sample_count,
    }
    if adapter_dir is not None:
        identity["adapter_dir"] = str(adapter_dir.resolve())
    if prompt_overlay_identity is not None:
        identity["analysis_prompt_overlay"] = dict(prompt_overlay_identity)
    if experiment_contract_identity is not None:
        identity["experiment_contract"] = dict(experiment_contract_identity)
    if quantization_bit is not None:
        identity["inference_precision"] = (
            FOUR_BIT_ADAPTER_INFERENCE_PRECISION
            if adapter_dir is not None
            else FOUR_BIT_INFERENCE_PRECISION
        )
    return identity


def _prepare_output(out_dir: Path, identity: Mapping[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    identity_path = out_dir / "run_identity.json"
    if identity_path.exists():
        if _read_json(identity_path) != identity:
            raise RuntimeError(f"evaluation run identity drifted: {out_dir}")
    else:
        identity_path.write_text(
            json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return out_dir / "evaluation_records.jsonl"


def _load_existing_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path}:{line_no}: invalid JSONL") from exc
        candidate_id = record.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in records:
            raise RuntimeError(f"{path}:{line_no}: invalid or duplicate candidate_id")
        records[candidate_id] = record
    return records


def evaluate_one(
    *,
    sample: Mapping[str, Any],
    model: Any,
    processor: Any,
    system_prompt: str,
    user_prompt: str,
    media_root: Path | None = None,
) -> dict[str, Any]:
    runtime_error: str | None = None
    parse_error: str | None = None
    prediction: dict[str, Any] | None = None
    raw_output = ""
    sampled_timestamps: list[float] | None = None
    generated_token_count: int | None = None
    hit_token_limit: bool | None = None
    video_path = resolve_workspace_artifact(
        str(sample["video_path"]),
        media_root if media_root is not None else current_data_paths(ROOT).root,
    )
    try:
        result = run_model_on_video_detailed(
            model,
            processor,
            video_path,
            user_prompt,
            system_prompt=system_prompt,
        )
        raw_output = result.raw_output
        sampled_timestamps = result.sampled_timestamps
        generated_token_count = result.generated_token_count
        hit_token_limit = result.hit_token_limit
        try:
            prediction = parse_v4_1_output(raw_output)
        except V4_1FinetuneError as exc:
            parse_error = str(exc)
    except Exception as exc:
        runtime_error = f"{type(exc).__name__}: {exc}"
    score = score_v4_1_prediction(sample["target"], prediction)
    return {
        "candidate_id": sample["candidate_id"],
        "source_video": sample["source_video"],
        "video_path": sample["video_path"],
        "target": sample["target"],
        "raw_output": raw_output,
        "prediction": prediction,
        "strict_valid": prediction is not None,
        "parse_error": parse_error,
        "runtime_error": runtime_error,
        "sampled_timestamps": sampled_timestamps,
        "generated_token_count": generated_token_count,
        "hit_token_limit": hit_token_limit,
        "scores": score,
    }


def summarize_records(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    scores = [record["scores"] for record in records]
    strict_valid = sum(record.get("strict_valid") is True for record in records)
    runtime_failures = sum(bool(record.get("runtime_error")) for record in records)
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    target_states: Counter[str] = Counter()
    prediction_states: Counter[str] = Counter()
    for record in records:
        target_state = str(record["target"]["clip_state"])
        prediction = record.get("prediction")
        predicted_state = (
            str(prediction["clip_state"])
            if isinstance(prediction, Mapping)
            else "__invalid__"
        )
        confusion[target_state][predicted_state] += 1
        target_states[target_state] += 1
        prediction_states[predicted_state] += 1
    return {
        "total_samples": len(records),
        "runtime_failure_count": runtime_failures,
        "strict_valid_count": strict_valid,
        "strict_valid_rate": (
            round(strict_valid / len(records), 6) if records else None
        ),
        "metrics": summarize_v4_1_scores(scores),
        "target_clip_state_distribution": dict(sorted(target_states.items())),
        "prediction_clip_state_distribution": dict(
            sorted(prediction_states.items())
        ),
        "clip_state_confusion": {
            target: dict(sorted(counts.items()))
            for target, counts in sorted(confusion.items())
        },
    }


def evaluation_succeeded(summary: Mapping[str, Any]) -> bool:
    total = summary.get("total_samples")
    return (
        isinstance(total, int)
        and total > 0
        and summary.get("runtime_failure_count") == 0
    )


def _write_final_outputs(
    out_dir: Path,
    identity: Mapping[str, Any],
    records: list[dict[str, Any]],
) -> None:
    summary = {
        **identity,
        **summarize_records(records),
    }
    (out_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "runtime_failures.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["candidate_id", "video_path", "runtime_error"],
        )
        writer.writeheader()
        for record in records:
            if record.get("runtime_error"):
                writer.writerow(
                    {
                        "candidate_id": record["candidate_id"],
                        "video_path": record["video_path"],
                        "runtime_error": record["runtime_error"],
                    }
                )


def _legacy_main() -> int:
    args = parse_args()
    validate_release(
        ROOT,
        verify_media=True,
        release_id=args.release_id,
        expected_contract_hash=args.expected_contract_hash,
        expected_schema_version=args.expected_release_schema,
    )
    contract, prompt_identity = _load_contract(
        args.analysis_prompt_overlay,
        experiment_contract_path=args.experiment_contract,
    )
    samples = load_validation_samples(args.fold, release_id=args.release_id)
    if args.max_samples is not None:
        if args.max_samples <= 0:
            raise ValueError("--max-samples must be positive")
        samples = samples[: args.max_samples]
    identity = _run_identity(
        args.fold,
        args.model_dir,
        len(samples),
        release_id=args.release_id,
        quantization_bit=args.quantization_bit,
        adapter_dir=args.adapter_dir,
        prompt_overlay_identity=(
            prompt_identity if args.analysis_prompt_overlay is not None else None
        ),
        experiment_contract_identity=(
            prompt_identity if args.experiment_contract is not None else None
        ),
        contract_hash=str(contract["contract_hash"]),
    )
    records_path = _prepare_output(args.out_dir, identity)
    existing = _load_existing_records(records_path)
    expected_ids = {sample["candidate_id"] for sample in samples}
    if set(existing) - expected_ids:
        raise RuntimeError("evaluation records contain candidates outside selected dataset")
    if len(existing) == len(samples):
        ordered = [existing[sample["candidate_id"]] for sample in samples]
        _write_final_outputs(args.out_dir, identity, ordered)
        summary = summarize_records(ordered)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if evaluation_succeeded(summary) else 1

    processor, model = load_model(
        str(args.model_dir),
        quantization_bit=args.quantization_bit,
        adapter_dir=str(args.adapter_dir) if args.adapter_dir else None,
    )
    analysis = contract["analysis"]
    with records_path.open("a", encoding="utf-8") as handle:
        for index, sample in enumerate(samples, start=1):
            if sample["candidate_id"] in existing:
                continue
            record = evaluate_one(
                sample=sample,
                model=model,
                processor=processor,
                system_prompt=analysis["system_prompt"],
                user_prompt=analysis["user_prompt"],
            )
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            existing[record["candidate_id"]] = record
            print(
                f"progress={len(existing)}/{len(samples)} "
                f"candidate_id={record['candidate_id']} "
                f"strict_valid={record['strict_valid']} "
                f"joint={record['scores']['joint_correct']}",
                flush=True,
            )
    ordered = [existing[sample["candidate_id"]] for sample in samples]
    _write_final_outputs(args.out_dir, identity, ordered)
    summary = summarize_records(ordered)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if evaluation_succeeded(summary) else 1



# Formal readable-identity evaluation. Legacy main above remains an audit entry
# until M7; it is never called by the versioning commands below.
FORMAL_GENERATION = {"do_sample": False, "num_beams": 1, "max_new_tokens": 256, "video_max_frames": 8}
FORMAL_METRICS = {
    "contract_valid_rate": "strictly valid predictions / selected samples",
    "joint_correct_rate": "jointly correct predictions / selected samples",
    **{f"{field}_correct_rate": f"correct {field} predictions / selected samples"
       for field in ("clip_state", "fracture_mechanism", "fracture_site", "special_case")},
}
SEMANTIC_METRICS = {
    "strict_valid_rate": "raw strict JSON/schema valid predictions / every frozen sample; diagnostic only",
    "joint_correct_rate": "all four explicitly expressed fields correct / every frozen sample",
    **{f"{field}_correct_rate": "explicit correct field / every frozen sample; missing differs from null"
       for field in ("clip_state", "fracture_mechanism", "fracture_site", "special_case")},
    "four_state_macro_recall": "unweighted recall over four supported GT states, excluding GT unknown; per-fold gate",
    "per_state_recall": "correct state / all corresponding GT state samples; every fold checked separately",
    "fracture_mechanism_macro_f1": "macro F1 over contract non-null classes on fixed GT non-null mechanism subset",
    "fracture_site_macro_f1": "macro F1 over contract non-null classes on fixed GT non-null site subset",
    "special_case_precision_recall": "per non-null class, all fixed samples including false positives; diagnostic only",
    "group_bootstrap": "95 percent percentile CI, independent frozen groups resampled jointly, 2000 replicates, seed 3407; undefined draws retained",
    "missing_support": "insufficient evidence; no automatic pass or post-hoc class/sample exclusion",
    "review_incomplete": "final visual metrics unavailable until prediction-only review is complete",
}



def _formal_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _formal_workspace(root: Path, eval_version: str) -> Path:
    from versioning.ids import parse_eval_id
    parse_eval_id(eval_version)
    root = Path(root).absolute()
    path = root / "workspace/evaluations" / eval_version
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("evaluation workspace must not contain symlinks")
    return path



def _implementation_matches(value: Mapping, source: str, digest: str) -> bool:
    from versioning.eval_compatibility import evaluation_adapter_matches
    current_digest = _sha256(ROOT / source)
    return (current_digest == digest or
            evaluation_adapter_matches(source, scorer=value.get("config", {}).get("scorer"),
                frozen_digest=digest, current_digest=current_digest))


def _historical_strict_comparison(current: dict, frozen: Mapping) -> dict:
    """Map only audited implementation identities, preserving every other byte."""
    if frozen.get("config", {}).get("scorer") not in {"strict-v4.1", "semantic-v4.1"}:
        return current
    from versioning.eval_compatibility import evaluation_adapter_matches
    copied = json.loads(_formal_bytes(current))
    for source, digest in frozen.get("implementation_sha256", {}).items():
        if evaluation_adapter_matches(source, scorer=frozen["config"]["scorer"], frozen_digest=digest,
                current_digest=current["implementation_sha256"].get(source)):
            copied["implementation_sha256"][source] = digest
    return copied


def _formal_config(config: Mapping[str, Any]) -> dict[str, Any]:
    import math
    expected = {"scope", "split", "artifact_kind", "scorer", "sample_selection",
                "quantization_bit", "generation", "thresholds", "aggregation"}
    semantic_holdout = isinstance(config, Mapping) and config.get("scorer") == "semantic-holdout-v4.1"
    semantic = isinstance(config, Mapping) and config.get("scorer") in {"semantic-v4.1", "semantic-holdout-v4.1"}
    optional = {"source_groups", "prompt_version", "fold", "blind_policy"} if semantic else set()
    if semantic_holdout:
        optional |= {"review_runtime", "aggregate_authorization", "device", "runtime_variant", "review_tokenizers"}
    if not isinstance(config, Mapping) or not expected <= set(config) or set(config) - expected - optional:
        raise ValueError(f"evaluation config requires exactly {sorted(expected)}")
    result = json.loads(_formal_bytes(dict(config)))
    if (result["scope"] not in ("single_fold", "cross_validation", "full")
        or not isinstance(result["split"], str) or not result["split"].strip()
        or (result["scope"] == "full" and result["split"] == "validation")
        or (result["scope"] != "full" and result["split"] != "validation")):
        raise ValueError("evaluation requires validation folds or full with an independent holdout split")
    if result["aggregation"] != "pooled":
        raise ValueError("aggregation must explicitly select pooled validation rows")
    if result["artifact_kind"] not in (("adapter", "merged", "model") if semantic else ("adapter", "merged")):
        raise ValueError("artifact_kind must be adapter or merged")
    if result["scorer"] not in ("strict-v4.1", "semantic-v4.1", "semantic-holdout-v4.1") or result["sample_selection"] != "all":
        raise ValueError("formal evaluation requires strict-v4.1 and all samples in each selected validation fold")
    if result["quantization_bit"] is not None and (type(result["quantization_bit"]) is not int or result["quantization_bit"] != 4):
        raise ValueError("quantization_bit must be null or 4")
    if _formal_bytes(result["generation"]) != _formal_bytes(FORMAL_GENERATION):
        raise ValueError("generation must match the actual strict V4.1 runtime")
    thresholds = result["thresholds"]
    if semantic_holdout:
        from finetune.eval_review import validate_semantic_holdout_config
        validate_semantic_holdout_config(result)
        return result
    if semantic:
        if result["scope"] == "full":
            raise ValueError("semantic holdout requires its separately authorized protocol")
        expected_thresholds = {"four_state_macro_recall": 0.65, "per_state_recall": 0.50,
            "joint_correct_rate": 0.50, "fracture_mechanism_macro_f1": 0.50,
            "fracture_site_macro_f1": 0.60}
        if thresholds != expected_thresholds:
            raise ValueError("semantic development thresholds must match the frozen protocol")
        if result.get("blind_policy") is not None:
            from finetune.eval_semantics import freeze_blind_policy
            freeze_blind_policy(result["blind_policy"])
        groups = result.get("source_groups")
        if not isinstance(groups, dict) or not groups or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in groups.items()):
            raise ValueError("semantic evaluation requires explicit complete candidate source_groups")
        if "fold" in result and (type(result["fold"]) is not int or result["fold"] not in (0, 1, 2)):
            raise ValueError("fold must be 0, 1 or 2")
        return result
    if result["scope"] == "full":
        from finetune.holdout_metrics import validate_thresholds
        validate_thresholds(thresholds)
        return result
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("explicit non-empty thresholds are required")
    for metric, value in thresholds.items():
        if metric not in FORMAL_METRICS or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("thresholds must name supported rates with finite minimum values in [0, 1]")
    return result



def _validate_source_groups(files: Mapping[str, bytes], groups: Mapping[str, str]) -> None:
    """Freeze declared independent groups; never infer independence from windows."""
    observed = set()
    validation_groups = []
    source_assignments = {}
    for fold in range(3):
        members = {}
        for split in ("train", "validation"):
            rows = json.loads(files[f"datasets/{split}/fold_{fold}.json"])
            selected = set()
            for index, row in enumerate(rows):
                video, _ = validate_training_row(row, split, index)
                candidate = Path(video).stem
                observed.add(candidate)
                if candidate not in groups:
                    raise ValueError(f"source_groups missing candidate: {candidate}")
                source = re.match(r"(video_\d+)", candidate)
                if source:
                    previous = source_assignments.setdefault(source.group(1), groups[candidate])
                    if previous != groups[candidate]:
                        raise ValueError("one source cannot be split across independent source_groups")
                selected.add(groups[candidate])
            members[split] = selected
        if members["train"] & members["validation"]:
            raise ValueError("source_groups leak across train/validation within a fold")
        if any(members["validation"] & other for other in validation_groups):
            raise ValueError("source_groups overlap across validation folds")
        validation_groups.append(members["validation"])
    if observed != set(groups):
        raise ValueError("source_groups must exactly cover the development candidate universe")


def _semantic_summary(value, records):
    from finetune.eval_semantics import development_gates, score_semantic_records
    folds = {fold: [r for r in records if r["fold"] == fold] for fold in value["folds"]}
    gates = development_gates(folds)
    pooled = gates["pooled"]
    from finetune.eval_baselines import majority_baseline_records
    majority = {}
    for fold, rows in folds.items():
        baseline_rows = majority_baseline_records(value["majority_baselines"][f"fold{fold}"], rows)
        majority[f"fold{fold}"] = score_semantic_records(baseline_rows, bootstrap=False)
    metrics = {k: float(v) for k, v in pooled["metrics"].items()
               if type(v) in (int, float)}
    outcome = "passed" if gates["outcome"] == "passed" else "failed"
    return {**summarize_records(records), "semantic": pooled, "development_gates": gates,
            "majority_baseline": majority,
            "scoring_protocol": "semantic-v4.1", "outcome": outcome}, metrics, outcome


def _formal_summary(value, records):
    if value["config"]["scorer"] == "semantic-v4.1":
        return _semantic_summary(value, records)
    summary = summarize_records(records)
    metrics = {key: summary["metrics"][key] for key in FORMAL_METRICS}
    outcome = "passed" if all(metrics[k] >= t for k, t in value["config"]["thresholds"].items()) else "failed"
    return summary, metrics, outcome


def _formal_artifact_key(value, fold):
    return "base" if value["model"].get("source_kind") == "base" else f"fold{fold}"

def _model_binding(record) -> dict[str, Any]:
    # Aliases, eval_id and promotion tags can change independently of the
    # registered training artifacts. They are not part of evaluation input.
    binding = {key: getattr(record, key) for key in (
        "model_id", "version", "run_id", "train_id", "data_version", "prompt_version",
        "git_commit", "base_model", "source_scope", "artifacts")}
    if getattr(record, "source_kind", "trained") == "base" or getattr(record, "source_evidence", None):
        binding.update(source_kind=record.source_kind, source_evidence=record.source_evidence)
    return binding


def _formal_input(*, root: Path, eval_version: str, model_version: str,
                  model_version_number: int, data_version: str, config: Mapping[str, Any],
                  git_commit: str, media_root: Path, inputs_path: Path | None = None,
                  pre_registration: Path | None = None, executor: str | None = None,
                  prompt_checkout_root: Path | None = None) -> dict[str, Any]:
    if isinstance(config, Mapping) and config.get("scope") == "full":
        from finetune.eval_holdout import build_holdout_input
        return build_holdout_input(root=root, eval_version=eval_version, model_version=model_version,
            model_version_number=model_version_number, data_version=data_version, config=config,
            git_commit=git_commit, media_root=media_root, inputs_path=inputs_path,
            pre_registration=pre_registration, executor=executor,
            prompt_checkout_root=prompt_checkout_root)
    if pre_registration is not None or executor is not None:
        raise ValueError("holdout authorization arguments require full holdout evaluation")
    from versioning.ids import parse_eval_id, parse_model_id, parse_data_id
    from versioning.data_release import load_release_metadata
    from versioning.registry import open_registry_store, validate_model_for_evaluation
    from versioning.prompts import load_prompt, verify_prompt_checkout_copy
    from finetune.train_build_dataset import build_versioned_datasets

    protocols = {parse_eval_id(eval_version).protocol, parse_model_id(model_version).protocol,
                 parse_data_id(data_version).protocol}
    if protocols != {"v4.1"}:
        raise ValueError("eval/model/data must use the same supported v4.1 protocol")
    if type(model_version_number) is not int or model_version_number < 1:
        raise ValueError("numeric MLflow Model Version must be a positive integer")
    config = _formal_config(config)
    if not isinstance(git_commit, str) or not git_commit.strip():
        raise ValueError("git_commit is required")
    root = Path(root).absolute()
    _formal_workspace(root, eval_version)
    meta = load_release_metadata(root / "data", data_version)
    if meta.purpose == "holdout":
        raise ValueError("holdout actual execution is not connected; refusing before truth access or model loading")
    # No caller-supplied model directory: the complete registered identity is
    # checked before artifacts are materialized or any weight path is resolved.
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    model = validate_model_for_evaluation(registry, model_version, model_version_number)
    semantic = config["scorer"] == "semantic-v4.1"
    is_base = getattr(model, "source_kind", "trained") == "base"
    diagnostic = model.source_scope == "diagnostic_fold"
    if is_base:
        if not semantic or config["artifact_kind"] != "model" or not config.get("prompt_version"):
            raise ValueError("base evaluation requires semantic protocol, model artifacts and explicit prompt_version")
        if config["scope"] == "single_fold" and "fold" not in config:
            raise ValueError("single-fold base comparison requires explicit fold")
        folds = [0, 1, 2] if config["scope"] == "cross_validation" else [config["fold"]]
    elif diagnostic:
        if not semantic or config["scope"] != "single_fold":
            raise ValueError("completed-fold diagnostics require semantic single_fold evaluation")
        folds = [model.source_evidence["fold"]]
        if "fold" in config and config["fold"] != folds[0]:
            raise ValueError("explicit evaluation fold differs from completed-fold source")
    else:
        if model.source_scope != config["scope"]:
            raise ValueError("evaluation scope does not match registered model scope")
        folds = [0, 1, 2] if model.source_scope == "cross_validation" else [0]
    if any(config["artifact_kind"] not in model.artifacts["base" if is_base else f"fold{i}"] for i in folds):
        raise ValueError("selected artifact kind is missing from a registered fold")
    prompt_version = config["prompt_version"] if is_base else model.prompt_version
    if not is_base and "prompt_version" in config and config["prompt_version"] != prompt_version:
        raise ValueError("trained evaluation must inherit the registered training Prompt")
    # Prompt 的 store 副本与 Git checkout 副本必须逐字节一致。prompt_version
    # 一旦确定就校验，先于 build_versioned_datasets 与任何评测产物落盘，
    # 与训练侧 prepare 同构。
    verify_prompt_checkout_copy(root, prompt_version, checkout_root=prompt_checkout_root)
    if model.source_scope == "single_fold" and model.deploy_target != model.artifacts["fold0"][config["artifact_kind"]]:
        raise ValueError("evaluated artifact must match the registered deploy_target")
    contract, _ = _load_contract()
    from finetune.validation.constants import GENERATION_CONFIG, VIDEO_MAX_FRAMES
    if {**GENERATION_CONFIG, "video_max_frames": VIDEO_MAX_FRAMES} != FORMAL_GENERATION:
        raise ValueError("runtime generation implementation drift")
    files, binding = build_versioned_datasets(root=root, data_version=data_version,
        prompt_version=prompt_version, media_root=media_root, inputs_path=inputs_path)
    prompt = load_prompt(root, prompt_version)
    if semantic:
        _validate_source_groups(files, config["source_groups"])
    samples = {}
    for fold in folds:
        rows = json.loads(files[f"datasets/validation/fold_{fold}.json"])
        selected, seen = [], set()
        for index, row in enumerate(rows):
            video, labels = validate_training_row(row, f"fold{fold}", index)
            candidate = Path(video).stem
            if candidate in seen:
                raise ValueError("duplicate validation candidate identity")
            seen.add(candidate)
            source = re.match(r"(video_\d+)", candidate)
            selected.append({"candidate_id": candidate, "source_video": source.group(1) if source else None,
                             "video_path": video, "target": labels,
                             **({"source_group": config["source_groups"][candidate]} if semantic else {})})
        if not selected:
            raise ValueError("formal evaluation requires non-empty folds")
        samples[f"fold{fold}"] = selected
    sources = ["finetune/eval_run.py", "finetune/v4_1_runtime.py", "pipeline/v4_1_labels.py",
               "finetune/validation/model_runtime.py", "finetune/validation/constants.py",
               "finetune/validation/video_loader.py", "pipeline/preprocessing/minicpm_preprocessor.py"]
    baselines = {}
    if semantic:
        from finetune.eval_semantics import default_rules
        from finetune.eval_baselines import build_majority_baseline
        sources.extend(["finetune/eval_semantics.py", "finetune/eval_baselines.py"])
        for fold in folds:
            training_rows = []
            for i, row in enumerate(json.loads(files[f"datasets/train/fold_{fold}.json"])):
                video, labels = validate_training_row(row, "train", i)
                training_rows.append({"candidate_id": Path(video).stem, "target": labels})
            baselines[f"fold{fold}"] = build_majority_baseline(training_rows,
                development_data_id=data_version, fit_split="train")
    return {"schema_version": "tensile-vlm/v4.1-evaluation", "eval_version": eval_version,
        "model": _model_binding(model), "data_version": data_version, "config": config,
        "git_commit": git_commit, "inputs_path": str(Path(inputs_path).absolute()) if inputs_path else None,
        "media_root": str(Path(media_root).absolute()), "data_binding": binding, "folds": folds,
        "samples": samples, "prompt": {"version": prompt_version,
            "system_prompt": prompt.system_prompt, "user_prompt": prompt.user_prompt,
            "output_fields": list(prompt.output_fields)},
        "contract_hash": contract["contract_hash"], "metric_definitions": SEMANTIC_METRICS if semantic else FORMAL_METRICS,
        "aggregation": ("complete sample-level pooled F1/joint plus separate state gates in every fold; "
                        "three complete folds and supported classes required; no mean-of-fold-F1; no rounding at thresholds"
                        if semantic else "pooled validation rows across the selected folds; all minimum thresholds must be met"),
        "implementation_sha256": {source: _sha256(ROOT / source) for source in sources},
        **({"scoring_protocol": "semantic-v4.1", "semantic_rules": default_rules(),
            "majority_baselines": baselines,
            "semantic_review_runtime": {"provider": "local-ollama", "context_tokens": 8192,
                "max_output_tokens": 512, "temperature": 0, "thinking": "off-when-supported",
                "timeout_seconds": 120, "runtime_failure_retries": 1, "concurrent_models": 1,
                "cloud_fallback": False, "overlong_input": "no-truncation-blind-review-or-incomplete"}}
           if semantic else {})}


def prepare_versioned_evaluation(**kwargs) -> Path:
    import fcntl
    import tempfile
    import shutil
    value = _formal_input(**kwargs)
    workspace = _formal_workspace(kwargs["root"], kwargs["eval_version"])
    workspace.mkdir(parents=True, exist_ok=True)
    payload = _formal_bytes(value)
    with (workspace / ".prepare.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = workspace / "input"
        if target.exists():
            current = verify_versioned_evaluation(root=kwargs["root"], eval_version=kwargs["eval_version"],
                prompt_checkout_root=kwargs.get("prompt_checkout_root"))
            if _formal_bytes(_historical_strict_comparison(value, current)) != _formal_bytes(current):
                raise ValueError("frozen evaluation input conflict")
            return target / "evaluation.yaml"
        staging = Path(tempfile.mkdtemp(prefix=".input-", dir=workspace))
        try:
            (staging / "evaluation.yaml").write_bytes(payload)
            (staging / "sha256").write_text(hashlib.sha256(payload).hexdigest())
            for path in staging.iterdir():
                path.chmod(0o444)
            os.rename(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return target / "evaluation.yaml"


def verify_versioned_evaluation(*, root: Path, eval_version: str, live: bool = True,
                                prompt_checkout_root: Path | None = None) -> dict[str, Any]:
    folder = _formal_workspace(root, eval_version) / "input"
    if folder.is_symlink() or not folder.is_dir() or {p.name for p in folder.iterdir()} != {"evaluation.yaml", "sha256"}:
        raise ValueError("frozen evaluation input is missing or malformed")
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o222:
            raise ValueError("frozen evaluation files must be regular and read-only")
    payload = (folder / "evaluation.yaml").read_bytes()
    if hashlib.sha256(payload).hexdigest() != (folder / "sha256").read_text():
        raise ValueError("frozen evaluation input digest drift")
    value = json.loads(payload)
    if value["eval_version"] != eval_version:
        raise ValueError("frozen evaluation identity drift")
    if live:
        media_root = _restored_evaluation_media_root(root, value)
        current = _formal_input(root=root, eval_version=eval_version,
            model_version=value["model"]["model_id"], model_version_number=value["model"]["version"],
            data_version=value["data_version"], config=value["config"], git_commit=value["git_commit"],
            media_root=media_root, inputs_path=Path(value["inputs_path"]) if value["inputs_path"] else None,
            prompt_checkout_root=prompt_checkout_root,
            **({"pre_registration": Path(root).absolute() / "evaluations/staging" / eval_version / "authorization/pre_registration.yaml",
                "executor": value["authorization"]["executor"]} if "authorization" in value else {}))
        if media_root != Path(value["media_root"]):
            # Only a catalog-bound managed media locator changes. Frozen
            # input, identity, rule, model, claim and consumption bytes do not.
            current["media_root"] = value["media_root"]
        if _formal_bytes(_historical_strict_comparison(current, value)) != payload:
            raise ValueError("frozen evaluation input or upstream content drift")
    return value


def _restored_evaluation_media_root(root: Path, value: Mapping[str, Any]) -> Path:
    if value.get("schema_version") != "tensile-vlm/v4.1-holdout-evaluation":
        return Path(value["media_root"])
    from versioning.backup import restored_holdout_media_root
    return restored_holdout_media_root(root, value)


def _weight_inventory(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("registered model weight directory is missing or contains symlinks")
    result = {}
    for file in sorted(path.rglob("*")):
        if file.is_symlink():
            raise ValueError("model artifacts must not contain symlinks")
        if file.is_file():
            result[str(file.relative_to(path))] = {"size": file.stat().st_size, "sha256": _sha256(file)}
    if not result:
        raise ValueError("registered model weight directory is empty")
    return result


def _write_formal_json(path: Path, value: Any) -> None:
    path.write_bytes(_formal_bytes(value))


def _checked_loader_path(path: Path) -> str:
    from finetune.validation.model_runtime import _sanitize_model_path
    selected = _sanitize_model_path(str(path))
    if Path(selected).resolve() != path.resolve():
        raise ValueError("loader path alias does not resolve to the registered weight directory")
    return selected


def _execute_formal_fold(value, fold, model_dir, adapter_dir, output):
    """Invoke the established loader and strict scorer on the frozen fold."""
    output.mkdir(parents=True, exist_ok=False)
    selected_model = _checked_loader_path(model_dir)
    selected_adapter = _checked_loader_path(adapter_dir) if adapter_dir else None
    processor, model = load_model(selected_model, quantization_bit=value["config"]["quantization_bit"],
                                 adapter_dir=selected_adapter)
    records = []
    try:
        with (output / "records.jsonl").open("x") as handle, (output / "failures.jsonl").open("x") as failures:
            for sample in value["samples"][f"fold{fold}"]:
                record = evaluate_one(sample=sample, model=model, processor=processor,
                    system_prompt=value["prompt"]["system_prompt"], user_prompt=value["prompt"]["user_prompt"],
                    media_root=Path(value["media_root"]))
                record["fold"] = fold
                if "source_group" in sample:
                    record["source_group"] = sample["source_group"]
                    from finetune.eval_semantics import extract_semantics
                    record["semantics"] = extract_semantics(record["raw_output"],
                        runtime_error=record["runtime_error"], rules=value["semantic_rules"])
                encoded = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                if record["runtime_error"] or record["parse_error"]:
                    failures.write(encoded)
                    failures.flush()
                    os.fsync(failures.fileno())
                records.append(record)
    finally:
        del model, processor
        # Releasing one fold before loading the next avoids keeping three
        # model instances alive. CUDA is touched only when already initialized.
        import gc
        import sys
        gc.collect()
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            torch.cuda.empty_cache()
    _write_formal_json(output / "summary.json", summarize_records(records))
    return records


def execute_versioned_evaluation(*, root: Path, eval_version: str,
                                prompt_checkout_root: Path | None = None):
    import fcntl
    import tempfile
    from versioning.backup import scoped_mlflow_client
    from versioning.registry import open_registry_store, materialize_model
    from versioning.mlflow_eval import (open_eval_store, create_eval_run, execute_eval_fold_run,
        log_eval_aggregate, log_eval_summary, transition_eval_state, get_eval_run)

    value = verify_versioned_evaluation(root=root, eval_version=eval_version,
        prompt_checkout_root=prompt_checkout_root)
    if value["config"]["scope"] == "full":
        from finetune.eval_holdout import execute_holdout_inference
        return execute_holdout_inference(root=root, eval_version=eval_version,
            prompt_checkout_root=prompt_checkout_root)
    workspace = _formal_workspace(root, eval_version)
    with (workspace / ".execution.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("evaluation is already executing") from exc
        value = verify_versioned_evaluation(root=root, eval_version=eval_version,
            prompt_checkout_root=prompt_checkout_root)
        output = workspace / "output"
        if output.exists():
            raise ValueError("existing evaluation output requires recovery; use export for a completed run")
        store = open_eval_store(Path(root) / "workspace/mlflow")
        client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
        input_sha = hashlib.sha256(_formal_bytes(value)).hexdigest()
        parent = create_eval_run(store, eval_version, model_id=value["model"]["model_id"],
            model_version_number=value["model"]["version"], data_version=value["data_version"],
            config=f"sha256:{input_sha}", git_commit=value["git_commit"], scope=value["config"]["scope"],
            split="validation", data_root=Path(root) / "data",
            purpose="development", protocol=value["config"]["scorer"])
        try:
            output.mkdir()
            client.log_artifact(parent.run_id, str(workspace / "input/evaluation.yaml"), artifact_path="input")
            registry = open_registry_store(store.root, data_root=Path(root) / "data")
            # A fresh private materialization cannot silently reuse an old model cache.
            with tempfile.TemporaryDirectory(prefix=".weights-", dir=workspace) as cache:
                materialized = materialize_model(registry, value["model"]["model_id"], Path(cache))
                verify_versioned_evaluation(root=root, eval_version=eval_version,
                    prompt_checkout_root=prompt_checkout_root)
                all_records, weight_inputs = [], {}
                for fold in value["folds"]:
                    verify_versioned_evaluation(root=root, eval_version=eval_version,
                        prompt_checkout_root=prompt_checkout_root)
                    declared = value["model"]["artifacts"][_formal_artifact_key(value, fold)][value["config"]["artifact_kind"]]
                    artifact = materialized / declared
                    adapter = artifact if value["config"]["artifact_kind"] == "adapter" else None
                    base = Path(value["model"]["base_model"]) if adapter else artifact
                    weight_inputs[f"fold{fold}"] = {"model_artifact": declared,
                        "model_files": _weight_inventory(base),
                        "adapter_files": _weight_inventory(adapter) if adapter else None}
                    # Capture the actual files before first loading the fold.
                    _write_formal_json(output / "evaluation.yaml", {**value, "weights": weight_inputs})
                    client.log_artifact(parent.run_id, str(output / "evaluation.yaml"))
                    fold_output = output / f"fold{fold}"
                    def execute():
                        verify_versioned_evaluation(root=root, eval_version=eval_version,
                            prompt_checkout_root=prompt_checkout_root)
                        records = _execute_formal_fold(value, fold, base, adapter, fold_output)
                        client.log_artifacts(parent.run_id, str(fold_output), artifact_path=f"fold{fold}")
                        verify_versioned_evaluation(root=root, eval_version=eval_version,
                            prompt_checkout_root=prompt_checkout_root)
                        _checked_loader_path(base)
                        if adapter is not None:
                            _checked_loader_path(adapter)
                        if (_weight_inventory(base) != weight_inputs[f"fold{fold}"]["model_files"]
                            or (adapter is not None and _weight_inventory(adapter) != weight_inputs[f"fold{fold}"]["adapter_files"])):
                            raise ValueError("loaded model weights drifted during evaluation")
                        summary = summarize_records(records)
                        if len(records) != len(value["samples"][f"fold{fold}"]) or not evaluation_succeeded(summary):
                            raise RuntimeError("evaluation execution incomplete: runtime failures")
                        all_records.extend(records)
                        if value["config"]["scorer"] == "semantic-v4.1":
                            from finetune.eval_semantics import score_semantic_records
                            return {k: float(v) for k, v in score_semantic_records(records, bootstrap=False)["metrics"].items()
                                    if type(v) in (int, float)}
                        return {key: summary["metrics"][key] for key in FORMAL_METRICS}
                    execute_eval_fold_run(store, eval_version, fold, executor=execute,
                        model_artifact=f"runs:/{value['model']['run_id']}/{declared.removeprefix('artifacts/')}",
                        data_split=f"{value['data_version']}/validation/fold{fold}",
                        sample_count=len(value["samples"][f"fold{fold}"]),
                        records=f"runs:/{parent.run_id}/fold{fold}/records.jsonl",
                        failures=f"runs:/{parent.run_id}/fold{fold}/failures.jsonl")
                if value["config"]["scorer"] == "semantic-v4.1":
                    raw_path = output / "raw_records.jsonl"
                    raw_path.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in all_records))
                    raw_path.chmod(0o444)
                    client.log_artifact(parent.run_id, str(raw_path))
                    client.log_param(parent.run_id, "sha256_raw_records.jsonl", _sha256(raw_path))
                    client.log_param(parent.run_id, "sha256_inference_evaluation.yaml", _sha256(output / "evaluation.yaml"))
                    if any(not r["semantics"]["review_complete"] for r in all_records):
                        raise EvaluationReviewPending("raw inference is frozen; import blind reviews with eval score, without rerunning inference")
                parent = get_eval_run(store, eval_version)
                _finish_formal_evaluation(value, all_records, output, store, parent, input_sha)

        except BaseException as exc:
            if isinstance(exc, EvaluationReviewPending):
                raise
            try:
                current = get_eval_run(store, eval_version)
                if current.workflow_state == "running" and current.outcome is None:
                    transition_eval_state(store, eval_version, "failed", run_status="FAILED")
            except Exception as tracking_error:
                exc.add_note(f"Failed to persist evaluation failure: {tracking_error}")
            raise
        export_versioned_evaluation(root=root, eval_version=eval_version)
        return get_eval_run(store, eval_version)



class EvaluationReviewPending(ValueError):
    """Inference is complete and frozen; only prediction-blind review may resume."""


def _finish_formal_evaluation(value, records, output, store, parent, input_sha):
    from versioning.backup import scoped_mlflow_client
    from versioning.mlflow_eval import log_eval_aggregate, log_eval_summary, transition_eval_state
    client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
    summary, metrics, outcome = _formal_summary(value, records)
    summary.update(outcome=outcome, input_sha256=input_sha)
    attempts, _ = _read_review_attempts(output, client.get_run(parent.run_id).data.params)
    if attempts:
        summary["blind_import_audit"] = _review_attempt_audit(attempts)
    if value["config"]["scorer"] == "semantic-v4.1":
        from finetune.eval_semantics import score_semantic_records
        for fold, child in parent.folds.items():
            rows = [r for r in records if r["fold"] == fold]
            final_semantic = output / f"fold{fold}" / "semantic_records.jsonl"
            final_semantic.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows))
            client.log_artifact(parent.run_id, str(final_semantic), artifact_path=f"fold{fold}")
            for k, v in score_semantic_records(rows, bootstrap=False)["metrics"].items():
                if type(v) in (int, float):
                    client.log_metric(child.run_id, k, v)
    _write_formal_json(output / "summary.json", summary)
    for name, rows in (("records.jsonl", records), ("failures.jsonl", [r for r in records if r["runtime_error"] or r["parse_error"]])):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows))
    for name in ("evaluation.yaml", "summary.json", "records.jsonl", "failures.jsonl"):
        client.log_artifact(parent.run_id, str(output / name))
        client.log_param(parent.run_id, f"sha256_{name}", _sha256(output / name))
    if value["config"]["scope"] == "cross_validation":
        log_eval_aggregate(store, value["eval_version"], metrics, folds=tuple(value["folds"]))
    else:
        log_eval_summary(store, value["eval_version"], metrics)
    transition_eval_state(store, value["eval_version"], "completed", outcome=outcome)



def _judgments(evidence):
    values = list(evidence["initial"])
    for phase in ("arbiter_independent", "arbitration", "human"):
        if evidence.get(phase) is not None:
            values.append(evidence[phase])
    return {(value["actor_id"], value["phase"]): value for value in values}


def _review_attempt_audit(attempts):
    """Check immutable adopted answers and the single infrastructure retry budget."""
    observed, seals, last_keys = {}, {}, {}
    for attempt in attempts:
        for raw_digest, evidence in attempt.items():
            current = _judgments(evidence)
            if not last_keys.get(raw_digest, set()) <= set(current):
                raise ValueError("review attempt discarded an earlier judgment phase")
            for actor_phase, judgment in current.items():
                key = (raw_digest, *actor_phase)
                history = observed.setdefault(key, [])
                if history and history[-1]["sha256"] != judgment["sha256"]:
                    if history[-1]["status"] == "completed":
                        raise ValueError("completed blind judgment cannot be replaced or selected again")
                    if len(history) >= 2:
                        raise ValueError("blind infrastructure failure allows at most one retry")
                if not history or history[-1]["sha256"] != judgment["sha256"]:
                    history.append(judgment)
                seals[judgment["sha256"]] = judgment
            last_keys[raw_digest] = set(current)
    return {"attempt_count": len(attempts), "unique_judgment_count": len(seals),
            "infrastructure_failure_count": sum(v["status"] == "infrastructure_failure" for v in seals.values()),
            "cost": sum(v["cost"] for v in seals.values()),
            "elapsed_seconds": sum(v["elapsed_seconds"] for v in seals.values()),
            "elapsed_definition": "sum of all unique sealed attempt durations (compute work), not wall-clock latency"}


def _read_review_attempts(folder, params, *, pending=None):
    names = sorted(key for key in params if key.startswith("sha256_review_attempt_"))
    attempts, paths = [], {}
    expected = [f"sha256_review_attempt_{i:04d}" for i in range(1, len(names) + 1)]
    if names != expected:
        raise ValueError("blind review attempt chain has gaps")
    directory = folder / "review_attempts"
    if directory.exists():
        expected_files = {f"{i:04d}.json" for i in range(1, len(names) + 1)}
        actual_files = {p.name for p in directory.iterdir()}
        next_file = directory / f"{len(names) + 1:04d}.json"
        recoverable = (pending is not None and actual_files == expected_files | {next_file.name}
                       and not next_file.is_symlink() and next_file.read_bytes() == _formal_bytes(pending))
        if directory.is_symlink() or (actual_files != expected_files and not recoverable):
            raise ValueError("blind review attempt chain has uncommitted or missing files")
    for i, key in enumerate(names, 1):
        name = f"review_attempts/{i:04d}.json"
        path = folder / name
        if path.is_symlink() or _sha256(path) != params[key]:
            raise ValueError("blind review attempt digest drift")
        attempts.append(json.loads(path.read_bytes()))
        paths[name] = path
    return attempts, paths

def resume_versioned_evaluation(*, root: Path, eval_version: str, blind_reviews: Path,
                                prompt_checkout_root: Path | None = None) -> Path:
    """Import sealed prediction-only reviews and score the same frozen raw bytes."""
    import fcntl
    from versioning.backup import scoped_mlflow_client
    from finetune.eval_semantics import extract_semantics
    from versioning.mlflow_eval import open_eval_store, get_eval_run
    value = verify_versioned_evaluation(root=root, eval_version=eval_version,
        prompt_checkout_root=prompt_checkout_root)
    if value["config"]["scorer"] != "semantic-v4.1" or not value["config"].get("blind_policy"):
        raise ValueError("blind resume requires semantic evaluation with a pre-frozen blind_policy")
    workspace = _formal_workspace(root, eval_version)
    with (workspace / ".execution.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = open_eval_store(Path(root) / "workspace/mlflow")
        parent = get_eval_run(store, eval_version)
        if parent.workflow_state != "running" or parent.outcome is not None or set(parent.folds) != set(value["folds"]) or any(r.status != "FINISHED" for r in parent.folds.values()):
            raise ValueError("only completed inference awaiting review can resume scoring")
        client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
        output = workspace / "output"
        params = client.get_run(parent.run_id).data.params
        from versioning.registry import _run_artifact_root
        artifact_root = _run_artifact_root(store, parent.run_id)
        if any(_sha256(folder / "raw_records.jsonl") != params.get("sha256_raw_records.jsonl") or
               _sha256(folder / "evaluation.yaml") != params.get("sha256_inference_evaluation.yaml")
               for folder in (output, artifact_root)):
            raise ValueError("frozen inference bytes drifted before review import")
        records = [json.loads(line) for line in (output / "raw_records.jsonl").read_text().splitlines()]
        reviews = json.loads(Path(blind_reviews).read_bytes())
        if not isinstance(reviews, dict):
            raise ValueError("blind_reviews must map raw_sha256 to sealed evidence")
        pending = {r["semantics"]["raw_sha256"] for r in records if not r["semantics"]["review_complete"]}
        if set(reviews) != pending:
            raise ValueError("blind review import must exactly cover pending frozen raw digests")
        incomplete = False
        for row in records:
            key = row["semantics"]["raw_sha256"]
            if key not in pending:
                continue
            evidence = reviews[key]
            if evidence.get("policy") != value["config"]["blind_policy"]:
                raise ValueError("blind review policy differs from pre-inference policy")
            row["blind_review"] = evidence
            row["semantics"] = extract_semantics(row["raw_output"], runtime_error=row["runtime_error"],
                rules=value["semantic_rules"], blind_review=evidence)
            incomplete |= not row["semantics"]["review_complete"]
        attempts, _ = _read_review_attempts(output, params, pending=reviews)
        tracked_attempts, _ = _read_review_attempts(artifact_root, params, pending=reviews)
        if tracked_attempts != attempts:
            raise ValueError("local and tracked blind review attempt chains differ")
        is_repeat = bool(attempts and attempts[-1] == reviews)
        proposed = attempts if is_repeat else [*attempts, reviews]
        _review_attempt_audit(proposed)
        if not is_repeat:
            from versioning.manifest import _publish_immutable
            attempt_path = output / "review_attempts" / f"{len(proposed):04d}.json"
            _publish_immutable(attempt_path, _formal_bytes(reviews), label="sealed blind review attempt")
            attempt_path.chmod(0o444)
            client.log_artifact(parent.run_id, str(attempt_path), artifact_path="review_attempts")
            client.log_param(parent.run_id, f"sha256_review_attempt_{len(proposed):04d}", _sha256(attempt_path))
        if incomplete:
            raise EvaluationReviewPending("sealed review attempt is retained but incomplete; only one infrastructure retry per actor/phase is allowed")
        review_path = output / "blind_reviews.json"
        from versioning.manifest import _publish_immutable
        _publish_immutable(review_path, _formal_bytes(reviews), label="sealed blind review")
        client.log_artifact(parent.run_id, str(review_path))
        client.log_param(parent.run_id, "sha256_blind_reviews.json", _sha256(review_path))
        _finish_formal_evaluation(value, records, output, store, parent, hashlib.sha256(_formal_bytes(value)).hexdigest())
    return export_versioned_evaluation(root=root, eval_version=eval_version)

def validate_evaluation_execution_artifacts(*, store, record) -> dict[str, Any]:
    """Read-only check of actual MLflow inputs/results and evaluated weight bytes."""
    from versioning.backup import scoped_mlflow_client
    from versioning.registry import _run_artifact_root, _artifact_tree, validate_model_for_evaluation

    client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
    artifact_root = _run_artifact_root(store, record.run_id)
    _artifact_tree(artifact_root)
    value = json.loads((artifact_root / "input/evaluation.yaml").read_bytes())
    if value.get("schema_version") == "tensile-vlm/v4.1-performance-evaluation":
        from finetune.eval_performance import validate_performance_execution
        if getattr(record, "purpose", None) != "performance" or getattr(record, "protocol", None) != "performance-v1":
            raise ValueError("performance purpose/protocol binding differs")
        return validate_performance_execution(store=store, record=record, value=value, artifact_root=artifact_root)
    if value.get("schema_version") == "tensile-vlm/v4.1-holdout-evaluation":
        from finetune.eval_holdout import validate_holdout_execution
        if value.get("config", {}).get("scorer") == "semantic-holdout-v4.1" and (
                getattr(record, "purpose", None) != "quality" or
                getattr(record, "protocol", None) != "semantic-holdout-v4.1"):
            raise ValueError("semantic holdout purpose/protocol binding differs")
        return validate_holdout_execution(store=store, record=record, value=value, artifact_root=artifact_root)
    if getattr(record, "purpose", "legacy") not in {"legacy", "development"}:
        raise ValueError("development execution cannot provide quality/performance evidence")
    if getattr(record, "purpose", "legacy") == "development" and record.protocol != value.get("config", {}).get("scorer"):
        raise ValueError("development protocol binding differs")
    if value.get("eval_version") != record.eval_id:
        raise ValueError("execution evidence evaluation identity differs")
    if _formal_config(value["config"]) != value["config"]:
        raise ValueError("execution evidence evaluation policy differs")
    expected_definitions = SEMANTIC_METRICS if value["config"]["scorer"] == "semantic-v4.1" else FORMAL_METRICS
    if value.get("metric_definitions") != expected_definitions:
        raise ValueError("execution evidence metric definitions differ from frozen protocol")
    sources = {"finetune/eval_run.py", "finetune/v4_1_runtime.py", "pipeline/v4_1_labels.py",
               "finetune/validation/model_runtime.py", "finetune/validation/constants.py",
               "finetune/validation/video_loader.py", "pipeline/preprocessing/minicpm_preprocessor.py"}
    if value["config"]["scorer"] == "semantic-v4.1":
        sources.update({"finetune/eval_semantics.py", "finetune/eval_baselines.py"})
    if set(value["implementation_sha256"]) != sources or any(
        not _implementation_matches(value, source, digest) for source, digest in value["implementation_sha256"].items()
    ):
        raise ValueError("execution evidence requires the frozen scorer implementation")
    model = validate_model_for_evaluation(store, record.model_id, record.model_version_number)
    if _model_binding(model) != value["model"]:
        raise ValueError("execution evidence registered model binding differs")
    digest = hashlib.sha256(_formal_bytes(value)).hexdigest()
    if (record.config != f"sha256:{digest}" or record.model_id != value["model"]["model_id"]
        or record.model_version_number != value["model"]["version"] or record.data_version != value["data_version"]
        or record.git_commit != value["git_commit"] or record.scope != value["config"]["scope"]
        or set(record.folds) != set(value["folds"])):
        raise ValueError("completed evaluation does not match frozen input")
    params = client.get_run(record.run_id).data.params
    paths = {}
    for name in ("evaluation.yaml", "summary.json", "records.jsonl", "failures.jsonl"):
        path = artifact_root / name
        if _sha256(path) != params.get(f"sha256_{name}"):
            raise ValueError("completed evaluation artifact digest mismatch")
        paths[name] = path
    if value["config"]["scorer"] == "semantic-v4.1":
        for name in ("raw_records.jsonl", *(["blind_reviews.json"] if "sha256_blind_reviews.json" in params else [])):
            path = artifact_root / name
            if _sha256(path) != params.get(f"sha256_{name}"):
                raise ValueError("frozen raw or blind review digest differs")
            paths[name] = path
    attempts, attempt_paths = _read_review_attempts(artifact_root, params)
    paths.update(attempt_paths)
    evaluation = json.loads(paths["evaluation.yaml"].read_bytes())
    if {key: evaluation.get(key) for key in value} != value:
        raise ValueError("persisted evaluation input mismatch")
    summary = json.loads(paths["summary.json"].read_bytes())
    records = [json.loads(line) for line in paths["records.jsonl"].read_text().splitlines()]
    expected = [(fold, s) for fold in value["folds"] for s in value["samples"][f"fold{fold}"]]
    if len(records) != len(expected):
        raise ValueError("completed evaluation sample count mismatch")
    for row, (fold, sample) in zip(records, expected, strict=True):
        if row.get("fold") != fold or any(row.get(k) != v for k, v in sample.items()):
            raise ValueError("completed evaluation sample binding mismatch")
        parsed = None
        try:
            parsed = parse_v4_1_output(row["raw_output"])
        except V4_1FinetuneError:
            pass
        if row["prediction"] != parsed or row["strict_valid"] != (parsed is not None) or row["scores"] != score_v4_1_prediction(row["target"], parsed):
            raise ValueError("completed evaluation scoring mismatch")
    if value["config"]["scorer"] == "semantic-v4.1":
        from finetune.eval_semantics import extract_semantics
        raw_rows = [json.loads(line) for line in paths["raw_records.jsonl"].read_text().splitlines()]
        reviews = json.loads(paths["blind_reviews.json"].read_bytes()) if "blind_reviews.json" in paths else {}
        if bool(attempts) != bool(reviews) or (attempts and attempts[-1] != reviews):
            raise ValueError("final adopted blind reviews differ from immutable attempt chain")
        pending_raw = {r["semantics"]["raw_sha256"]: r for r in raw_rows if not r["semantics"]["review_complete"]}
        for attempt in attempts:
            if set(attempt) != set(pending_raw):
                raise ValueError("blind attempt changed the original pending raw denominator")
            for raw_digest, evidence in attempt.items():
                if evidence.get("policy") != value["config"].get("blind_policy"):
                    raise ValueError("blind attempt policy drift")
                raw = pending_raw[raw_digest]
                extract_semantics(raw["raw_output"], runtime_error=raw["runtime_error"],
                    rules=value["semantic_rules"], blind_review=evidence)
        if len(raw_rows) != len(records):
            raise ValueError("frozen raw denominator mismatch")
        for row, raw in zip(records, raw_rows, strict=True):
            original = {k: v for k, v in row.items() if k not in {"semantics", "blind_review"}}
            if original != {k: v for k, v in raw.items() if k != "semantics"}:
                raise ValueError("semantic import changed frozen inference records")
            if row.get("blind_review") is not None:
                if (row["blind_review"] != reviews.get(raw["semantics"]["raw_sha256"]) or
                    row["blind_review"].get("policy") != value["config"].get("blind_policy")):
                    raise ValueError("sealed review evidence/policy mismatch")
            if not row.get("semantics", {}).get("review_complete"):
                raise ValueError("completed evaluation has unfinished semantic review")
            recomputed_semantic = extract_semantics(row["raw_output"], runtime_error=row["runtime_error"],
                rules=value["semantic_rules"], blind_review=row.get("blind_review"))
            if row.get("semantics") != recomputed_semantic:
                raise ValueError("completed evaluation semantic evidence differs from frozen raw/rules")
    if value["config"]["scorer"] == "semantic-v4.1":
        from finetune.eval_semantics import score_semantic_records
        for fold, child in record.folds.items():
            selected = [r for r in records if r["fold"] == fold]
            expected_metrics = {k: float(v) for k, v in score_semantic_records(selected, bootstrap=False)["metrics"].items()
                                if type(v) in (int, float)}
            semantic_file = artifact_root / f"fold{fold}/semantic_records.jsonl"
            original_file = artifact_root / f"fold{fold}/records.jsonl"
            if (child.sample_count != len(selected) or dict(child.metrics) != expected_metrics or
                [json.loads(line) for line in semantic_file.read_text().splitlines()] != selected or
                [json.loads(line) for line in original_file.read_text().splitlines()] != [r for r in raw_rows if r["fold"] == fold]):
                raise ValueError("per-fold semantic evidence/metrics/denominator mismatch")
    recomputed, metrics, outcome = _formal_summary(value, records)
    if attempts:
        recomputed["blind_import_audit"] = _review_attempt_audit(attempts)
    if (not evaluation_succeeded(recomputed) or any(summary.get(k) != v for k, v in recomputed.items())
        or summary.get("input_sha256") != digest or summary.get("outcome") != outcome
        or record.outcome != outcome or dict(record.metrics) != metrics):
        raise ValueError("completed evaluation summary/outcome mismatch")
    failures = [json.loads(line) for line in paths["failures.jsonl"].read_text().splitlines()]
    if failures != [row for row in records if row["runtime_error"] or row["parse_error"]]:
        raise ValueError("completed evaluation failure records mismatch")
    weights = evaluation.get("weights", {})
    if set(weights) != {f"fold{fold}" for fold in value["folds"]}:
        raise ValueError("execution evidence evaluated weight inventory is incomplete")
    model_root = _run_artifact_root(store, model.run_id)
    kind = value["config"]["artifact_kind"]
    if model.source_scope == "single_fold" and model.deploy_target != model.artifacts["fold0"][kind]:
        raise ValueError("evaluated artifact must match the registered deploy_target")
    for fold in value["folds"]:
        declared = model.artifacts[_formal_artifact_key(value, fold)][kind]
        used = weights[f"fold{fold}"]
        if used.get("model_artifact") != declared:
            raise ValueError("execution evidence evaluated artifact differs")
        artifact_files = _artifact_tree(model_root / declared.removeprefix("artifacts/"))
        if kind == "adapter":
            if artifact_files != used.get("adapter_files") or _artifact_tree(Path(model.base_model)) != used.get("model_files"):
                raise ValueError("execution evidence evaluated weights drifted")
        elif artifact_files != used.get("model_files") or used.get("adapter_files") is not None:
            raise ValueError("execution evidence evaluated weights drifted")
    return {"version": record.eval_id,
        "protocol": "tensile-vlm/v4.1", "state": "sealed", "record_validity": record.record_validity,
        "model_version": record.model_id, "mlflow_model_version": record.model_version_number,
        "data_version": record.data_version, "split": "validation", "model_scope": record.scope,
        "sample_count": len(records), "outcome": record.outcome, "run_id": record.run_id,
        "input_sha256": digest,
        **({"scoring_protocol": "semantic-v4.1", "semantic_rules_sha256":
            hashlib.sha256(_formal_bytes(value["semantic_rules"])).hexdigest(),
            "development_evidence_status": recomputed["development_gates"]["outcome"]}
           if value["config"]["scorer"] == "semantic-v4.1" else {}),
        "artifacts": {name: {"uri": f"runs:/{record.run_id}/{name}",
            "sha256": (params[f"sha256_review_attempt_{Path(name).stem}"] if name.startswith("review_attempts/")
                       else params[f"sha256_{name}"])} for name in paths}}


def export_versioned_evaluation(*, root: Path, eval_version: str) -> Path:
    from versioning.mlflow_eval import open_eval_store, validate_eval_for_conclusion
    from versioning.registry import open_registry_store
    from versioning.manifest import _publish_immutable
    value = verify_versioned_evaluation(root=root, eval_version=eval_version, live=False)
    store = open_registry_store(Path(root) / "workspace/mlflow", data_root=Path(root) / "data")
    record = validate_eval_for_conclusion(open_eval_store(store.root), eval_version)
    document = validate_evaluation_execution_artifacts(store=store, record=record)
    if document["input_sha256"] != hashlib.sha256(_formal_bytes(value)).hexdigest():
        raise ValueError("local frozen input differs from actual execution evidence")
    target = Path(root) / "records/evaluations" / eval_version / "manifest.yaml"
    return _publish_immutable(target, _formal_bytes(document), label="evaluation manifest")


def compare_versioned_evaluations(*, root: Path, eval_version: str, baseline_eval_version: str) -> Path:
    """Publish a paired development comparison from two complete formal Runs."""
    from versioning.ids import parse_eval_id
    from versioning.registry import open_registry_store, _run_artifact_root
    from versioning.mlflow_eval import open_eval_store, validate_eval_for_conclusion
    from versioning.manifest import _publish_immutable
    from finetune.eval_baselines import compare_paired_records
    parse_eval_id(eval_version)
    parse_eval_id(baseline_eval_version)
    store = open_registry_store(Path(root) / "workspace/mlflow", data_root=Path(root) / "data")
    eval_store = open_eval_store(store.root)
    inputs, rows, manifests = {}, {}, {}
    for role, identity in (("base", baseline_eval_version), ("trained", eval_version)):
        record = validate_eval_for_conclusion(eval_store, identity)
        manifest = validate_evaluation_execution_artifacts(store=store, record=record)
        artifact = _run_artifact_root(store, record.run_id)
        frozen = json.loads((artifact / "input/evaluation.yaml").read_bytes())
        if frozen["config"]["scorer"] != "semantic-v4.1" or frozen["config"]["split"] != "validation":
            raise ValueError("paired comparison requires semantic development evidence")
        is_base = frozen["model"].get("source_kind") == "base"
        if (role == "base") != is_base:
            raise ValueError("paired comparison requires a real registered base and a trained model")
        inputs[role], manifests[role] = frozen, manifest
        rows[role] = [json.loads(line) for line in (artifact / "records.jsonl").read_text().splitlines()]
    if _weight_inventory(Path(inputs["trained"]["model"]["base_model"])) != inputs["base"]["model"]["source_evidence"]["base_files"]:
        raise ValueError("paired baseline differs from the trained model's actual frozen base bytes")
    def conditions(value):
        return {"media_sampling": {"data_version": value["data_version"],
                    "media": value["data_binding"]["media"], "video_max_frames": value["config"]["generation"]["video_max_frames"]},
                "prompt": value["prompt"],
                "decode": {"generation": value["config"]["generation"], "quantization_bit": value["config"]["quantization_bit"]},
                "scorer": {"protocol": "semantic-v4.1", "rules": value["semantic_rules"]}}
    result = compare_paired_records(rows["base"], rows["trained"],
        base_config=conditions(inputs["base"]), trained_config=conditions(inputs["trained"]),
        absolute_gate_result={role: manifest["outcome"] for role, manifest in manifests.items()})
    payload = {"schema_version": "tensile-development-paired-comparison/v1", "base_eval": baseline_eval_version,
               "trained_eval": eval_version, "evidence": manifests, "comparison": result}
    return _publish_immutable(Path(root) / "records/evaluations" / eval_version / "paired" / f"{baseline_eval_version}.json",
        _formal_bytes(payload), label="paired development comparison")
