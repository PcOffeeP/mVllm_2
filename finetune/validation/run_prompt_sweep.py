"""Run reproducible Prompt Engineering and visual-evidence experiments.

The public CLI has two subcommands.  ``prompt`` compares natural, light and
strict prompt variants on Fold 0 validation data.  ``evidence`` compares the
light four-field protocol with an evidence-first five-field protocol on a
fixed, source-balanced pilot manifest.  GPU execution belongs on the training
computer; parsing, manifest construction and summaries are intentionally
testable without a model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shlex
import subprocess
import sys
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pipeline.scripts.quality_check import TARGET_SCHEMA_KEYS, _matches_legal_combination

from .constants import GENERATION_CONFIG, PROJECT_ROOT, SUPPORTED_DATASETS, VIDEO_MAX_FRAMES
from .datasets import EvalSample, load_dataset
from .model_runtime import ModelRunResult, load_model, run_model_on_video, run_model_on_video_detailed
from .prompts import (
    DEFAULT_PROMPT_LIBRARY_PATH,
    get_prompt_library,
    get_prompt_version,
    get_system_prompt,
    get_test_system_prompt,
    get_user_prompt,
    get_user_prompt_template_count,
    get_user_prompt_template_id,
)

OUTPUT_PROTOCOL_FOUR_FIELD = "four_field_json"
OUTPUT_PROTOCOL_FREE_TEXT = "free_text"
OUTPUT_PROTOCOL_EVIDENCE = "evidence_first_json"
EVIDENCE_KEYS = ["visual_evidence", "has_fracture", "fracture_between", "type", "location"]
DEFAULT_DATASET = "fold_0_val"
DEVELOPMENT_DATASETS = tuple(name for name in SUPPORTED_DATASETS if name.startswith("fold_") and name.endswith("_val"))
DEFAULT_USER_PROMPT_SEED = 42
EXPERIMENT_VARIANTS = {
    "prompt": ("natural", "light", "strict"),
    "evidence": ("light", "light_evidence"),
}
MAX_NEW_TOKENS = {"prompt": 256, "evidence": 512}

PILOT_TARGETS: dict[str, tuple[bool | None, str]] = {
    "video_0001": (True, "韧性断裂"),
    "video_0006": (True, "韧性断裂"),
    "video_0009": (True, "界面脱粘"),
    "video_0044": (True, "界面脱粘"),
    "video_0060": (True, "齐根断裂"),
    "video_0076": (True, "齐根断裂"),
    "video_0065": (True, "脆性断裂"),
    "video_0075": (True, "脆性断裂"),
    "video_0015": (False, "未断裂"),
    "video_0023": (False, "未断裂"),
    "video_0070": (False, "未断裂"),
    "video_0071": (False, "未断裂"),
    "video_0081": (False, "未断裂"),
    "video_0102": (False, "未断裂"),
    "video_0103": (False, "未断裂"),
    "video_0107": (False, "未断裂"),
    "video_0042": (None, "视频异常"),
}

KNOWN_NEGATIVE_DEMONSTRATION = (
    '{"has_fracture":false,"fracture_between":null,"type":"未断裂",'
    '"location":null,"confidence":0.9}'
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--prompt" in argv and (not argv or argv[0] not in EXPERIMENT_VARIANTS):
        return _parse_legacy_args(argv)

    parser = argparse.ArgumentParser(description="Run paired prompt or visual-evidence experiments.")
    subparsers = parser.add_subparsers(dest="experiment", required=True)
    for experiment in EXPERIMENT_VARIANTS:
        subparser = subparsers.add_parser(experiment)
        _add_common_arguments(subparser)
    args = parser.parse_args(argv)
    args.legacy_prompt = None
    args.variants = EXPERIMENT_VARIANTS[args.experiment]
    args.max_new_tokens = MAX_NEW_TOKENS[args.experiment]
    return args


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-dir", required=True, help="Loadable merged/base model directory.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, choices=DEVELOPMENT_DATASETS)
    parser.add_argument("--out-dir", default=None, help="Optional new output directory; never overwritten.")
    parser.add_argument("--max-samples", type=int, default=None, help="Local/training-machine smoke limit.")
    parser.add_argument("--video-root", default=None)
    parser.add_argument("--user-prompt-seed", type=int, default=DEFAULT_USER_PROMPT_SEED)


def _parse_legacy_args(argv: list[str]) -> argparse.Namespace:
    warnings.warn("--prompt user|system|test is deprecated; use the prompt/evidence subcommands.", DeprecationWarning)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dataset", required=True, choices=SUPPORTED_DATASETS)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--prompt", required=True, choices=("user", "system", "test"))
    args = parser.parse_args(argv)
    args.experiment = "legacy"
    args.legacy_prompt = args.prompt
    args.variants = (args.prompt,)
    args.max_new_tokens = GENERATION_CONFIG["max_new_tokens"]
    args.max_samples = None
    args.video_root = None
    args.user_prompt_seed = DEFAULT_USER_PROMPT_SEED
    return args


def get_experiment_variants(library: dict[str, Any]) -> dict[str, dict[str, Any]]:
    experiments = library.get("experiments", {}) or {}
    prompt_engineering = experiments.get("prompt_engineering", {}) if isinstance(experiments, dict) else {}
    variants = prompt_engineering.get("variants", {}) if isinstance(prompt_engineering, dict) else {}
    if not isinstance(variants, dict):
        raise ValueError("prompt_library experiments.prompt_engineering.variants must be a mapping")
    return variants


def stable_template_index(sample_id: str, seed: int, template_count: int) -> int:
    if template_count <= 0:
        raise ValueError("template_count must be positive")
    digest = hashlib.sha256(f"{seed}:{sample_id}".encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % template_count


def build_variant_condition(
    library: dict[str, Any], sample_id: str, variant: str, seed: int = DEFAULT_USER_PROMPT_SEED
) -> dict[str, Any]:
    variants = get_experiment_variants(library)
    if variant not in variants:
        raise ValueError(f"Unknown experiment variant {variant!r}; expected one of {sorted(variants)}")
    definition = variants[variant]
    template_index = stable_template_index(sample_id, seed, get_user_prompt_template_count(library))
    prompt_text = get_user_prompt(template_index, library)
    system_prompt = definition.get("system_prompt")
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise ValueError(f"variant {variant}.system_prompt must be a string or null")
    output_protocol = str(definition.get("output_protocol", ""))
    if output_protocol not in {OUTPUT_PROTOCOL_FREE_TEXT, OUTPUT_PROTOCOL_FOUR_FIELD, OUTPUT_PROTOCOL_EVIDENCE}:
        raise ValueError(f"variant {variant} has unsupported output_protocol {output_protocol!r}")
    template_id = get_user_prompt_template_id(template_index, library)
    return {
        "prompt_id": f"{template_id}__{variant}",
        "template_index": template_index,
        "template_id": template_id,
        "variant": variant,
        "output_protocol": output_protocol,
        "prompt_text": prompt_text,
        "prompt_hash": _sha256(prompt_text),
        "system_prompt": system_prompt.strip() if isinstance(system_prompt, str) else None,
        "system_prompt_hash": _sha256(system_prompt.strip()) if isinstance(system_prompt, str) else None,
    }


def build_prompt_conditions(
    library: dict[str, Any], template_indices: list[int], prompt_mode: str
) -> list[dict[str, Any]]:
    """Backward-compatible builder for the old user/system/test CLI."""
    output_protocol = OUTPUT_PROTOCOL_FOUR_FIELD if prompt_mode == "test" else OUTPUT_PROTOCOL_FREE_TEXT
    conditions: list[dict[str, Any]] = []
    for template_index in template_indices:
        template_id = get_user_prompt_template_id(template_index, library)
        prompt_text = get_user_prompt(template_index, library)
        conditions.append(
            {
                "prompt_id": f"{template_id}__{prompt_mode}",
                "template_id": template_id,
                "variant": prompt_mode,
                "output_protocol": output_protocol,
                "prompt_text": prompt_text,
                "prompt_hash": _sha256(prompt_text),
            }
        )
    return conditions


def inspect_four_field_output(raw_output: str) -> dict[str, Any]:
    return _inspect_json_output(raw_output, expected_keys=list(TARGET_SCHEMA_KEYS), evidence=False)


def inspect_evidence_output(raw_output: str) -> dict[str, Any]:
    return _inspect_json_output(raw_output, expected_keys=EVIDENCE_KEYS, evidence=True)


def _inspect_json_output(raw_output: str, expected_keys: list[str], evidence: bool) -> dict[str, Any]:
    cleaned = str(raw_output or "").strip()
    result: dict[str, Any] = {
        "json_valid": False,
        "schema_valid": False,
        "legal_combination_valid": False,
        "key_order_valid": False if evidence else None,
        "visual_evidence_non_empty": False if evidence else None,
        "parsed_output": None,
        "parsed_full_output": None,
        "parse_error": None,
    }
    if not cleaned:
        result["parse_error"] = "empty_output"
        return result
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        result["parse_error"] = f"JSONDecodeError: {exc.msg}"
        return result
    result["json_valid"] = True
    if not isinstance(parsed, dict):
        result["parse_error"] = "JSON value is not an object"
        return result
    result["parsed_full_output"] = parsed
    expected_set = set(expected_keys)
    if set(parsed) != expected_set:
        result["parse_error"] = f"schema keys must be {sorted(expected_set)}"
        return result
    if evidence:
        result["key_order_valid"] = list(parsed) == expected_keys
        visual_evidence = parsed.get("visual_evidence")
        result["visual_evidence_non_empty"] = isinstance(visual_evidence, str) and bool(visual_evidence.strip())
        if not result["visual_evidence_non_empty"]:
            result["parse_error"] = "visual_evidence must be a non-empty string"
            return result
        core = {key: parsed[key] for key in TARGET_SCHEMA_KEYS}
    else:
        core = parsed
    result["schema_valid"] = True
    result["parsed_output"] = core
    result["legal_combination_valid"] = bool(_matches_legal_combination(core))
    if not result["legal_combination_valid"]:
        result["parse_error"] = "illegal four-field value combination"
    return result


def inspect_output(raw_output: str, output_protocol: str) -> dict[str, Any]:
    if output_protocol == OUTPUT_PROTOCOL_FOUR_FIELD:
        return inspect_four_field_output(raw_output)
    if output_protocol == OUTPUT_PROTOCOL_EVIDENCE:
        return inspect_evidence_output(raw_output)
    if output_protocol == OUTPUT_PROTOCOL_FREE_TEXT:
        return {
            "json_valid": None,
            "schema_valid": None,
            "legal_combination_valid": None,
            "key_order_valid": None,
            "visual_evidence_non_empty": None,
            "parsed_output": None,
            "parsed_full_output": None,
            "parse_error": "free_text protocol is not automatically parsed",
        }
    raise ValueError(f"Unsupported output protocol {output_protocol!r}")


def evaluate_record(
    sample: EvalSample,
    condition: dict[str, Any],
    raw_output: str,
    runtime_error: str | None,
    run_result: ModelRunResult | None = None,
) -> dict[str, Any]:
    output_protocol = str(condition.get("output_protocol", OUTPUT_PROTOCOL_FOUR_FIELD))
    inspection = inspect_output(raw_output, output_protocol)
    record = {
        "sample_id": sample.sample_id,
        "video_id": sample.video_id,
        "video_path": str(sample.video_path),
        "source_video_id": source_video_id(sample),
        "subvideo_id": sample.metadata.get("subvideo_id"),
        "ground_truth": sample.metadata.get("ground_truth"),
        "prompt_id": condition["prompt_id"],
        "template_index": condition.get("template_index"),
        "template_id": condition["template_id"],
        "variant": condition["variant"],
        "output_protocol": output_protocol,
        "prompt_text": condition["prompt_text"],
        "prompt_hash": condition["prompt_hash"],
        "system_prompt": condition.get("system_prompt"),
        "system_prompt_hash": condition.get("system_prompt_hash"),
        "raw_output": raw_output,
        "runtime_error": runtime_error,
        "raw_output_non_empty": bool(str(raw_output or "").strip()),
        "generated_token_count": run_result.generated_token_count if run_result else None,
        "hit_token_limit": run_result.hit_token_limit if run_result else None,
        "sampled_timestamps": run_result.sampled_timestamps if run_result else [],
        "frame_paths": run_result.frame_paths if run_result else [],
        "copied_known_negative_demonstration": str(raw_output or "").strip() == KNOWN_NEGATIVE_DEMONSTRATION,
        **inspection,
    }
    if record["template_index"] is None:
        record.pop("template_index")
    return record


def source_video_id(sample: EvalSample) -> str:
    explicit = sample.metadata.get("source_video_id")
    if explicit:
        return str(explicit)
    stem = Path(sample.video_path).stem
    prefix = stem.split("_focus_", 1)[0]
    return prefix if prefix.startswith("video_") else sample.video_id


def summarize_condition(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    outputs = [str(record.get("raw_output") or "").strip() for record in records]
    non_empty = [value for value in outputs if value]
    frequencies = Counter(non_empty)
    most_common_output, most_common_count = frequencies.most_common(1)[0] if frequencies else (None, 0)
    parsed = [record["parsed_output"] for record in records if isinstance(record.get("parsed_output"), dict)]
    label_distribution = Counter(str(value.get("type")) for value in parsed)
    return {
        "total_samples": total,
        "source_count": len({str(record.get("source_video_id")) for record in records}),
        "runtime_error_count": sum(bool(record.get("runtime_error")) for record in records),
        "non_empty_output_rate": _rate(len(non_empty), total),
        "format_evaluable_count": sum(record.get("json_valid") is not None for record in records),
        "json_valid_rate": _optional_rate(records, "json_valid"),
        "schema_valid_rate": _optional_rate(records, "schema_valid"),
        "legal_combination_valid_rate": _optional_rate(records, "legal_combination_valid"),
        "key_order_valid_rate": _optional_rate(records, "key_order_valid"),
        "visual_evidence_non_empty_rate": _optional_rate(records, "visual_evidence_non_empty"),
        "hit_token_limit_count": sum(record.get("hit_token_limit") is True for record in records),
        "unique_non_empty_output_count": len(frequencies),
        "most_common_output": most_common_output,
        "most_common_output_rate": _rate(most_common_count, total),
        "label_distribution": dict(sorted(label_distribution.items())),
        **_classification_metrics(records),
    }


def _classification_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    protocol = str(records[0].get("output_protocol", OUTPUT_PROTOCOL_FOUR_FIELD)) if records else OUTPUT_PROTOCOL_FOUR_FIELD
    if protocol == OUTPUT_PROTOCOL_FREE_TEXT:
        return {
            "has_fracture_evaluable_count": 0,
            "has_fracture_accuracy": None,
            "has_fracture_precision": None,
            "has_fracture_recall": None,
            "has_fracture_f1": None,
            "predicted_positive_rate": None,
            **_empty_field_metrics(),
        }
    evaluable = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and isinstance(record["ground_truth"].get("has_fracture"), bool)
    ]
    common = _field_metrics(records)
    if not evaluable:
        return {
            "has_fracture_evaluable_count": 0,
            "has_fracture_accuracy": None,
            "has_fracture_precision": None,
            "has_fracture_recall": None,
            "has_fracture_f1": None,
            "predicted_positive_rate": None,
            **common,
        }
    tp = fp = fn = correct = positive = 0
    for record in evaluable:
        gt_positive = record["ground_truth"]["has_fracture"] is True
        parsed = record.get("parsed_output")
        pred_positive = isinstance(parsed, dict) and parsed.get("has_fracture") is True
        positive += int(pred_positive)
        correct += int(isinstance(parsed, dict) and parsed.get("has_fracture") == gt_positive)
        tp += int(gt_positive and pred_positive)
        fp += int(not gt_positive and pred_positive)
        fn += int(gt_positive and not pred_positive)
    return {
        "has_fracture_evaluable_count": len(evaluable),
        "has_fracture_accuracy": _rate(correct, len(evaluable)),
        "has_fracture_precision": _ratio(tp, tp + fp),
        "has_fracture_recall": _ratio(tp, tp + fn),
        "has_fracture_f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "predicted_positive_rate": _rate(positive, len(evaluable)),
        **common,
    }


def _field_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    type_records = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and isinstance(record["ground_truth"].get("type"), str)
        and record["ground_truth"]["type"] != "视频异常"
    ]
    location_records = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and record["ground_truth"].get("location") in {"inside_gauge", "outside_gauge"}
    ]
    interval_records = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and isinstance(record["ground_truth"].get("fracture_between"), list)
    ]
    joint_records = [record for record in records if _joint_target_is_evaluable(record.get("ground_truth"))]
    return {
        "type_evaluable_count": len(type_records),
        "type_accuracy": _field_accuracy(type_records, "type"),
        "location_evaluable_count": len(location_records),
        "location_accuracy": _field_accuracy(location_records, "location"),
        "fracture_between_evaluable_count": len(interval_records),
        "fracture_between_exact_match_rate": _field_accuracy(interval_records, "fracture_between"),
        "joint_evaluable_count": len(joint_records),
        "joint_success_rate": _joint_accuracy(joint_records),
    }


def _empty_field_metrics() -> dict[str, Any]:
    return {
        "type_evaluable_count": 0,
        "type_accuracy": None,
        "location_evaluable_count": 0,
        "location_accuracy": None,
        "fracture_between_evaluable_count": 0,
        "fracture_between_exact_match_rate": None,
        "joint_evaluable_count": 0,
        "joint_success_rate": None,
    }


def _field_accuracy(records: list[dict[str, Any]], field: str) -> float | None:
    correct = sum(
        isinstance(record.get("parsed_output"), dict)
        and record["parsed_output"].get(field) == record["ground_truth"].get(field)
        for record in records
    )
    return _rate(correct, len(records))


def _joint_target_is_evaluable(ground_truth: Any) -> bool:
    if not isinstance(ground_truth, dict) or not isinstance(ground_truth.get("has_fracture"), bool):
        return False
    if not isinstance(ground_truth.get("type"), str):
        return False
    return not (ground_truth["has_fracture"] is True and not isinstance(ground_truth.get("fracture_between"), list))


def _joint_accuracy(records: list[dict[str, Any]]) -> float | None:
    fields = ("has_fracture", "fracture_between", "type", "location")
    correct = sum(
        isinstance(record.get("parsed_output"), dict)
        and all(record["parsed_output"].get(field) == record["ground_truth"].get(field) for field in fields)
        for record in records
    )
    return _rate(correct, len(records))


def build_evidence_pilot(samples: list[EvalSample], seed: int = DEFAULT_USER_PROMPT_SEED) -> list[EvalSample]:
    selected: list[EvalSample] = []
    for source, (target_has_fracture, target_type) in PILOT_TARGETS.items():
        candidates = []
        for sample in samples:
            ground_truth = sample.metadata.get("ground_truth") or {}
            if source_video_id(sample) != source:
                continue
            if ground_truth.get("has_fracture") is target_has_fracture and ground_truth.get("type") == target_type:
                candidates.append(sample)
        if not candidates:
            raise ValueError(f"Evidence pilot has no {target_type} candidate for {source}")
        selected.append(min(candidates, key=lambda item: _sha256(f"{seed}:{item.sample_id}") or ""))
    return selected


def build_dataset_coverage(samples: list[EvalSample], dataset: str) -> dict[str, Any]:
    merged_sources = sorted({source_video_id(sample) for sample in samples})
    split_path = PROJECT_ROOT / "data" / "05_splits" / f"{dataset}.json"
    split_sources: list[str] = []
    if split_path.exists():
        payload = json.loads(split_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            split_sources = sorted(str(value) for value in payload.get("video_ids", []))
    missing = sorted(set(split_sources) - set(merged_sources))
    missing_audit = _audit_missing_sources(missing, dataset)
    return {
        "dataset": dataset,
        "sample_count": len(samples),
        "merged_source_count": len(merged_sources),
        "merged_sources": merged_sources,
        "split_path": str(split_path) if split_path.exists() else None,
        "split_source_count": len(split_sources) if split_sources else None,
        "split_sources": split_sources,
        "missing_from_merged": missing,
        "missing_source_audit": missing_audit,
        "blocking_coverage_issues": sorted(
            source for source, audit in missing_audit.items() if audit.get("expected_split_present")
        ),
        "unexpected_in_merged": sorted(set(merged_sources) - set(split_sources)) if split_sources else [],
    }


def _audit_missing_sources(missing_sources: list[str], dataset: str) -> dict[str, Any]:
    """Distinguish genuinely empty sources from stale split/export assignments."""
    metadata_path = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
    if not missing_sources or not metadata_path.exists():
        return {}
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    subvideos = payload.get("subvideos", []) if isinstance(payload, dict) else []
    audit: dict[str, Any] = {}
    for source in missing_sources:
        rows = [row for row in subvideos if isinstance(row, dict) and row.get("source_video") == source]
        selected_splits = sorted(
            {
                str(split)
                for row in rows
                for split in (row.get("selected_splits") or [])
            }
        )
        expected_split_present = dataset in selected_splits
        audit[source] = {
            "has_reviewed_subvideos": bool(rows),
            "reviewed_subvideo_count": len(rows),
            "selected_splits": selected_splits,
            "expected_split_present": expected_split_present,
            "reason": (
                "selected_for_split_but_missing_from_merged"
                if expected_split_present
                else "reviewed_but_not_selected_for_split"
                if rows
                else "no_reviewed_subvideos"
            ),
        }
    return audit


def build_model_manifest(model_dir: str) -> dict[str, Any]:
    path = Path(model_dir).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"model directory does not exist: {path}")
    config_path = path / "config.json"
    if not config_path.exists():
        raise ValueError(f"model directory is not directly loadable: missing {config_path}")
    if (path / "adapter_config.json").exists():
        raise ValueError(
            "adapter-only model directories are not supported; merge the adapter into its base model and pass the merged directory"
        )
    provenance_paths = [path / name for name in ("model_metadata.json", "merge_metadata.json") if (path / name).is_file()]
    if not provenance_paths:
        raise ValueError(
            "model provenance metadata is required: add model_metadata.json (base) or merge_metadata.json (merged)"
        )
    provenance_documents = [json.loads(candidate.read_text(encoding="utf-8")) for candidate in provenance_paths]
    if any(not isinstance(document, dict) for document in provenance_documents):
        raise ValueError("model provenance metadata must contain a JSON object")
    provenance = provenance_documents[0]
    if any(document != provenance for document in provenance_documents[1:]):
        raise ValueError("model_metadata.json and merge_metadata.json contain contradictory provenance")
    model_kind = provenance.get("model_kind")
    if model_kind not in {"base", "merged"}:
        raise ValueError("model provenance model_kind must be 'base' or 'merged'")
    provenance_base = provenance.get("base_model")
    if not isinstance(provenance_base, str) or not provenance_base.strip():
        raise ValueError("model provenance must include a non-empty base_model")
    if model_kind == "merged":
        if not isinstance(provenance.get("adapter_path"), str) or not provenance["adapter_path"].strip():
            raise ValueError("merged model provenance must include a non-empty adapter_path")
        checkpoint_step = provenance.get("checkpoint_step")
        if not isinstance(checkpoint_step, int) or isinstance(checkpoint_step, bool) or checkpoint_step < 0:
            raise ValueError("merged model provenance must include a non-negative integer checkpoint_step")
    interesting = (
        "config.json",
        "tokenizer_config.json",
        "generation_config.json",
        "trainer_state.json",
        "model.safetensors.index.json",
        "pytorch_model.bin.index.json",
        "merge_metadata.json",
        "model_metadata.json",
    )
    files = {}
    for name in interesting:
        candidate = path / name
        if candidate.is_file():
            files[name] = {"size": candidate.stat().st_size, "sha256": _hash_file(candidate)}
    weight_paths = sorted(
        {
            *path.glob("model*.safetensors"),
            *path.glob("pytorch_model*.bin"),
        },
        key=lambda candidate: candidate.name,
    )
    if not weight_paths:
        raise ValueError(
            "model directory is not directly loadable: no model.safetensors/model shards or pytorch_model.bin found"
        )
    weights = {
        candidate.name: {"size": candidate.stat().st_size, "sha256": _hash_file(candidate)}
        for candidate in weight_paths
    }
    config = json.loads(config_path.read_text(encoding="utf-8"))
    configured_base = config.get("_name_or_path")
    if configured_base and Path(str(configured_base)).name != Path(provenance_base).name:
        raise ValueError(
            f"model provenance base_model {provenance_base!r} contradicts config _name_or_path {configured_base!r}"
        )
    return {
        "model_dir": str(path),
        "model_name": path.name,
        "model_type": config.get("model_type"),
        "base_model": config.get("_name_or_path"),
        "model_kind": model_kind,
        "provenance": provenance,
        "provenance_files": [candidate.name for candidate in provenance_paths],
        "files": files,
        "weights": weights,
        "weight_file_count": len(weights),
        "weight_total_size": sum(item["size"] for item in weights.values()),
        "weights_hash": _sha256(json.dumps(weights, sort_keys=True)),
        "warnings": [
            message
            for condition, message in (
                (not (path / "tokenizer_config.json").exists(), "tokenizer_config.json is absent"),
            )
            if condition
        ],
    }


def default_out_dir(experiment: str, model_dir: str) -> Path:
    model_name = Path(model_dir).resolve().name.replace(" ", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "finetune" / "results" / "prompt_sweep" / experiment / f"{model_name}-{timestamp}"


def run_experiment(args: argparse.Namespace) -> Path:
    if args.experiment == "legacy":
        return _run_legacy(args)
    if args.experiment == "evidence" and args.dataset != DEFAULT_DATASET:
        raise ValueError("the fixed evidence pilot is defined only for fold_0_val")
    library = get_prompt_library()
    out_dir = Path(args.out_dir) if args.out_dir else default_out_dir(args.experiment, args.model_dir)
    if out_dir.exists():
        raise FileExistsError(f"output directory already exists: {out_dir}")
    out_dir.mkdir(parents=True)

    model_manifest = build_model_manifest(args.model_dir)
    all_samples = load_dataset(args.dataset, video_root=Path(args.video_root) if args.video_root else None)
    coverage = build_dataset_coverage(all_samples, args.dataset)
    selected = build_evidence_pilot(all_samples, args.user_prompt_seed) if args.experiment == "evidence" else list(all_samples)
    if args.max_samples is not None:
        selected = _limit_samples(selected, args.max_samples)
    if not selected:
        raise ValueError("experiment selected no samples")
    missing_media = [str(sample.video_path) for sample in selected if not sample.video_path.exists()]

    sample_manifest = {
        "experiment": args.experiment,
        "dataset": args.dataset,
        "seed": args.user_prompt_seed,
        "coverage": coverage,
        "dataset_hash": _hash_sample_manifest(all_samples),
        "samples": [_sample_manifest_entry(sample) for sample in selected],
    }
    sample_manifest["manifest_hash"] = _sha256(json.dumps(sample_manifest["samples"], ensure_ascii=False, sort_keys=True))
    generation_config = {**GENERATION_CONFIG, "max_new_tokens": args.max_new_tokens}
    experiment_manifest = {
        "experiment": args.experiment,
        "dataset": args.dataset,
        "variants": list(args.variants),
        "prompt_library_path": str(DEFAULT_PROMPT_LIBRARY_PATH),
        "prompt_version": get_prompt_version(library),
        "prompt_library_hash": _hash_file(DEFAULT_PROMPT_LIBRARY_PATH),
        "user_prompt_seed": args.user_prompt_seed,
        "video_max_frames": VIDEO_MAX_FRAMES,
        "generation_config": generation_config,
        "model_manifest_hash": _sha256(json.dumps(model_manifest, sort_keys=True)),
        "sample_manifest_hash": sample_manifest["manifest_hash"],
        "code_revision": _code_revision(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "missing_media": missing_media,
    }
    _write_json(out_dir / "model_manifest.json", model_manifest)
    _write_json(out_dir / "sample_manifest.json", sample_manifest)
    _write_json(out_dir / "experiment_manifest.json", experiment_manifest)
    (out_dir / "run_command.txt").write_text(
        shlex.join([sys.executable, "-m", "finetune.validation.run_prompt_sweep", *sys.argv[1:]]) + "\n",
        encoding="utf-8",
    )
    if coverage["blocking_coverage_issues"]:
        _write_preflight_failure(
            out_dir / "runtime_failures.csv",
            "dataset_coverage",
            "reviewed sources are missing from merged validation data: "
            + ", ".join(coverage["blocking_coverage_issues"]),
        )
        raise ValueError("Fold validation coverage is inconsistent; see sample_manifest.json")
    if missing_media:
        _write_preflight_failure(
            out_dir / "runtime_failures.csv", "missing_media", f"{len(missing_media)} selected video files are missing"
        )
        raise FileNotFoundError(f"{len(missing_media)} selected videos are missing; see experiment_manifest.json")

    try:
        processor, model = load_model(args.model_dir)
        _run_dry_run(model, processor, selected, args, library)
    except Exception as exc:
        _write_preflight_failure(
            out_dir / "runtime_failures.csv", "model_or_dry_run", f"{type(exc).__name__}: {exc}"
        )
        raise
    records = _run_full_sweep(model, processor, selected, args, library, out_dir)
    _write_outputs(out_dir, records, sample_manifest, experiment_manifest)
    return out_dir


def _limit_samples(samples: list[EvalSample], limit: int) -> list[EvalSample]:
    if limit < 2:
        raise ValueError("--max-samples must be at least 2 so dry run covers positive and negative samples")
    positive = next((sample for sample in samples if (sample.metadata.get("ground_truth") or {}).get("has_fracture") is True), None)
    negative = next((sample for sample in samples if (sample.metadata.get("ground_truth") or {}).get("has_fracture") is False), None)
    selected = [sample for sample in (positive, negative) if sample is not None]
    selected_ids = {sample.sample_id for sample in selected}
    selected.extend(sample for sample in samples if sample.sample_id not in selected_ids)
    return selected[:limit]


def _run_dry_run(model: Any, processor: Any, samples: list[EvalSample], args: argparse.Namespace, library: dict[str, Any]) -> None:
    positive = next((s for s in samples if (s.metadata.get("ground_truth") or {}).get("has_fracture") is True), None)
    negative = next((s for s in samples if (s.metadata.get("ground_truth") or {}).get("has_fracture") is False), None)
    dry_samples = [sample for sample in (positive, negative) if sample is not None]
    if len(dry_samples) < 2:
        raise ValueError("dry run requires one fracture and one non-fracture sample")
    for sample in dry_samples:
        for variant in args.variants:
            condition = build_variant_condition(library, sample.sample_id, variant, args.user_prompt_seed)
            result = run_model_on_video_detailed(
                model,
                processor,
                sample.video_path,
                condition["prompt_text"],
                system_prompt=condition["system_prompt"],
                max_new_tokens=args.max_new_tokens,
            )
            if not result.raw_output.strip():
                raise RuntimeError(f"dry run returned empty output for {sample.sample_id}/{variant}")


def _run_full_sweep(
    model: Any,
    processor: Any,
    samples: list[EvalSample],
    args: argparse.Namespace,
    library: dict[str, Any],
    out_dir: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    frames_root = out_dir / "frames"
    frames_root.mkdir()
    records_path = out_dir / "evaluation_records.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            for variant_index, variant in enumerate(args.variants):
                condition = build_variant_condition(library, sample.sample_id, variant, args.user_prompt_seed)
                frame_dir = frames_root / sample.sample_id if variant_index == 0 else None
                try:
                    result = run_model_on_video_detailed(
                        model,
                        processor,
                        sample.video_path,
                        condition["prompt_text"],
                        system_prompt=condition["system_prompt"],
                        max_new_tokens=args.max_new_tokens,
                        frame_dir=frame_dir,
                    )
                    if result.frame_paths:
                        result = ModelRunResult(
                            raw_output=result.raw_output,
                            sampled_timestamps=result.sampled_timestamps,
                            generated_token_count=result.generated_token_count,
                            hit_token_limit=result.hit_token_limit,
                            frame_paths=[Path(path).relative_to(out_dir).as_posix() for path in result.frame_paths],
                        )
                    runtime_error = None
                except Exception as exc:
                    result = None
                    runtime_error = f"{type(exc).__name__}: {exc}"
                record = evaluate_record(sample, condition, result.raw_output if result else "", runtime_error, result)
                record["model_dir"] = args.model_dir
                records.append(record)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
    return records


def _write_outputs(
    out_dir: Path,
    records: list[dict[str, Any]],
    sample_manifest: dict[str, Any],
    experiment_manifest: dict[str, Any],
) -> None:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_variant[str(record["variant"])].append(record)
    summary = {
        **experiment_manifest,
        "paired_design": True,
        "sample_count": len(sample_manifest["samples"]),
        "record_count": len(records),
        "conditions": [
            {"variant": variant, "metrics": summarize_condition(variant_records)}
            for variant, variant_records in sorted(by_variant.items())
        ],
        "paired_label_flips": _paired_label_flips(records),
        "notes": [
            "Natural/free-text is a capability probe and is not directly schema-scored against JSON variants.",
            "Treat source_video_id, not subvideo count, as the independent evidence unit.",
            "Format validity does not prove visual grounding or task correctness.",
        ],
    }
    _write_json(out_dir / "prompt_sweep_summary.json", summary)
    _write_json(out_dir / "source_level_summary.json", _source_level_summary(records))
    _write_manual_review_files(out_dir, records)
    _write_runtime_failures(out_dir / "runtime_failures.csv", records)


def _paired_label_flips(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sample: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        parsed = record.get("parsed_output")
        if isinstance(parsed, dict):
            by_sample[str(record["sample_id"])][str(record["variant"])] = parsed
    flips = []
    for sample_id, variants in sorted(by_sample.items()):
        names = sorted(variants)
        for left_index, left in enumerate(names):
            for right in names[left_index + 1 :]:
                if variants[left] != variants[right]:
                    flips.append({"sample_id": sample_id, "left": left, "right": right})
    return flips


def _source_level_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["source_video_id"]), str(record["variant"]))].append(record)
    sources: dict[str, Any] = defaultdict(dict)
    for (source, variant), source_records in sorted(grouped.items()):
        sources[source][variant] = summarize_condition(source_records)
    return {
        "source_count": len(sources),
        "sources": dict(sources),
        "warning": "Do not treat subvideos from the same source as independent observations.",
    }


def _write_manual_review_files(out_dir: Path, records: list[dict[str, Any]]) -> None:
    queue_path = out_dir / "manual_review_queue.csv"
    key: dict[str, Any] = {}
    with queue_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "review_id",
            "sample_id",
            "source_video_id",
            "raw_output",
            "contact_sheet",
            "stage1_format_valid",
            "stage1_grounded",
            "stage1_hallucinated",
            "stage1_self_consistent",
            "stage1_notes",
            "stage2_label_reasonable",
            "stage2_evidence_supports_labels",
            "stage2_notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, record in enumerate(records, start=1):
            review_id = f"review_{index:05d}"
            contact = Path("frames") / str(record["sample_id"]) / "contact_sheet.png"
            writer.writerow(
                {
                    "review_id": review_id,
                    "sample_id": record["sample_id"],
                    "source_video_id": record["source_video_id"],
                    "raw_output": record["raw_output"],
                    "contact_sheet": contact.as_posix() if (out_dir / contact).exists() else "",
                }
            )
            key[review_id] = {
                "variant": record["variant"],
                "ground_truth": record["ground_truth"],
                "parsed_output": record["parsed_output"],
            }
    _write_json(out_dir / "manual_review_key.json", key)


def _write_runtime_failures(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("sample_id", "variant", "video_path", "runtime_error"))
        writer.writeheader()
        for record in records:
            if record.get("runtime_error"):
                writer.writerow({key: record.get(key) for key in writer.fieldnames})


def _write_preflight_failure(path: Path, failure_type: str, message: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("sample_id", "variant", "video_path", "runtime_error"))
        writer.writeheader()
        writer.writerow({"sample_id": "", "variant": failure_type, "video_path": "", "runtime_error": message})


def _run_legacy(args: argparse.Namespace) -> Path:
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        raise FileExistsError(f"output directory already exists: {out_dir}")
    library = get_prompt_library()
    conditions = build_prompt_conditions(library, list(range(get_user_prompt_template_count(library))), args.prompt)
    system_prompt = None if args.prompt == "user" else get_system_prompt(library) if args.prompt == "system" else get_test_system_prompt(library)
    samples = load_dataset(args.dataset)
    out_dir.mkdir(parents=True)
    processor, model = load_model(args.model_dir)
    records = []
    for condition in conditions:
        legacy_condition = {**condition, "system_prompt": system_prompt, "system_prompt_hash": _sha256(system_prompt)}
        for sample in samples:
            try:
                raw_output = run_model_on_video(model, processor, sample.video_path, condition["prompt_text"], system_prompt=system_prompt)
                error = None
            except Exception as exc:
                raw_output = ""
                error = f"{type(exc).__name__}: {exc}"
            records.append(evaluate_record(sample, legacy_condition, raw_output, error))
    _write_json(
        out_dir / "prompt_sweep_summary.json",
        {
            "dataset": args.dataset,
            "model_dir": args.model_dir,
            "prompt_mode": args.prompt,
            "paired_design": True,
            "sample_count": len(samples),
            "record_count": len(records),
            "conditions": [
                {"prompt_id": condition["prompt_id"], "metrics": summarize_condition([r for r in records if r["prompt_id"] == condition["prompt_id"]])}
                for condition in conditions
            ],
        },
    )
    with (out_dir / "evaluation_records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_dir


def _sample_manifest_entry(sample: EvalSample) -> dict[str, Any]:
    return {
        "sample_id": sample.sample_id,
        "video_id": sample.video_id,
        "source_video_id": source_video_id(sample),
        "video_path": str(sample.video_path),
        "ground_truth": sample.metadata.get("ground_truth"),
    }


def _hash_sample_manifest(samples: Iterable[EvalSample]) -> str | None:
    payload = [_sample_manifest_entry(sample) for sample in samples]
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _code_revision() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _optional_rate(records: list[dict[str, Any]], field: str) -> float | None:
    values = [record.get(field) for record in records if isinstance(record.get(field), bool)]
    return _rate(sum(values), len(values))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _sha256(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value is not None else None


def main() -> None:
    args = parse_args()
    out_dir = run_experiment(args)
    print(f"Wrote {args.experiment} experiment to {out_dir}")


if __name__ == "__main__":
    main()
