"""Run resumable strict V4.1 inference on one released validation fold."""

from __future__ import annotations

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
    RELEASE_ID,
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

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pipeline/contracts/tensile_vlm_v4_1.json"
RUNTIME_CONTRACT_HASH = (
    "3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, required=True, choices=(0, 1, 2))
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--quantization-bit", type=int, choices=(4,))
    parser.add_argument("--adapter-dir", type=Path)
    parser.add_argument("--release-id", default=RELEASE_ID)
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
    release_id: str = RELEASE_ID,
) -> list[dict[str, Any]]:
    path = release_dir(ROOT, release_id) / f"datasets/validation/fold_{fold}.json"
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
    release_id: str = RELEASE_ID,
    quantization_bit: int | None = None,
    adapter_dir: Path | None = None,
    prompt_overlay_identity: Mapping[str, Any] | None = None,
    experiment_contract_identity: Mapping[str, Any] | None = None,
    contract_hash: str = RUNTIME_CONTRACT_HASH,
) -> dict[str, Any]:
    identity = {
        "schema_version": "tensile-v4.1-evaluation-run/v1",
        "release_id": release_id,
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
        current_data_paths(ROOT).compatibility_workspace,
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


def main() -> int:
    args = parse_args()
    validate_release(
        ROOT,
        verify_media=True,
        release_id=args.release_id,
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


if __name__ == "__main__":
    raise SystemExit(main())
