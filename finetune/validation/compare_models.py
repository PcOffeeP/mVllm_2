from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .common import (
    compute_interval_metrics,
    compute_joint_interval_metrics,
    compute_type_metrics,
    read_jsonl,
    write_csv,
    write_json,
)
from .config import FRACTURE_CLASSES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare multiple model inference results.")
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="Model results in name=path.jsonl format, e.g., base=results/base_test.jsonl finetuned=results/finetuned_test.jsonl",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for comparison artifacts.",
    )
    return parser.parse_args()


def _parse_inputs(inputs: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Parse --inputs arguments: name=path format.
    
    Returns {model_name: records_list}.
    Validates that all files exist and load correctly.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for inp in inputs:
        if "=" not in inp:
            raise ValueError(f"Invalid input format: {inp!r}. Use name=path.jsonl")
        name, path_str = inp.split("=", 1)
        name = name.strip()
        path = Path(path_str.strip())
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
        records = read_jsonl([str(path)])
        if not records:
            raise ValueError(f"Input file is empty: {path}")
        result[name] = records
    return result


def _check_common_video_ids(model_data: dict[str, list[dict[str, Any]]]) -> set[str]:
    """Verify all models cover the SAME set of records.
    
    Validates:
    - Every record must have a non-empty video_id
    - No duplicate video_ids within a model
    - Record count equals unique video_id count (no extra records)
    - All models have identical video_id sets
    
    Raises ValueError on any violation.
    """
    id_sets: dict[str, set[str]] = {}
    for name, records in model_data.items():
        video_ids: list[str] = []
        for i, r in enumerate(records):
            vid = r.get("video_id")
            if not vid or not str(vid).strip():
                raise ValueError(
                    f"Record {i} in model '{name}' has missing or empty video_id. "
                    f"Every record must have a non-empty video_id."
                )
            video_ids.append(str(vid).strip())
        
        unique_ids = set(video_ids)
        
        # Check for duplicates
        if len(video_ids) != len(unique_ids):
            from collections import Counter
            dupes = [vid for vid, count in Counter(video_ids).items() if count > 1]
            raise ValueError(
                f"Model '{name}' has duplicate video_ids: {dupes}. "
                f"Each video_id must appear exactly once."
            )
        
        # Record count must match unique count (no ghost records)
        if len(records) != len(unique_ids):
            raise ValueError(
                f"Model '{name}' has {len(records)} records but only {len(unique_ids)} unique video_ids. "
                f"Every record must have a unique, non-empty video_id."
            )
        
        id_sets[name] = unique_ids
    
    # Check cross-model identity
    names = list(id_sets.keys())
    reference = id_sets[names[0]]
    
    for name in names[1:]:
        current = id_sets[name]
        if current != reference:
            missing = reference - current
            extra = current - reference
            msg = (
                f"Video ID mismatch between models. "
                f"{name} has {len(current)} IDs but {names[0]} has {len(reference)} IDs. "
            )
            if missing:
                msg += f"Missing from {name}: {sorted(missing)}. "
            if extra:
                msg += f"Extra in {name}: {sorted(extra)}. "
            msg += "All models must cover the exact same set of video_ids for fair comparison."
            raise ValueError(msg)
    
    return reference


def _check_generation_config(records: list[dict[str, Any]]) -> dict:
    """Check all records share the same generation_config. Returns the config dict.
    
    Raises ValueError if any record is missing generation_config, if configs differ,
    or if required keys (do_sample, num_beams, max_new_tokens) are absent.
    """
    REQUIRED_GEN_KEYS = {"do_sample", "num_beams", "max_new_tokens"}
    config_strs = set()
    for r in records:
        cfg = r.get("generation_config")
        if cfg is None or not cfg:
            raise ValueError(
                f"Record {r.get('video_id', '???')} is missing generation_config. "
                "Every record must have a non-empty generation_config."
            )
        # Check required keys exist
        missing_keys = REQUIRED_GEN_KEYS - set(cfg.keys())
        if missing_keys:
            raise ValueError(
                f"Record {r.get('video_id', '???')} has incomplete generation_config. "
                f"Missing required keys: {sorted(missing_keys)}. "
                f"Required keys: {sorted(REQUIRED_GEN_KEYS)}."
            )
        # Only compare the required keys for consistency
        normalized = {k: cfg[k] for k in REQUIRED_GEN_KEYS if k in cfg}
        config_strs.add(json.dumps(normalized, sort_keys=True))
    if len(config_strs) > 1:
        raise ValueError(
            f"Inconsistent generation_config within model: {len(config_strs)} different configs found."
        )
    return json.loads(next(iter(config_strs)))


def _validate_consistency(model_data: dict[str, list[dict[str, Any]]]) -> None:
    """Validate cross-model consistency: no duplicates, same protocol."""
    # Check for duplicate video_ids within each model
    for name, records in model_data.items():
        video_ids = [r.get("video_id") for r in records]
        seen = set()
        dupes = set()
        for vid in video_ids:
            if vid in seen:
                dupes.add(vid)
            seen.add(vid)
        if dupes:
            raise ValueError(
                f"Model '{name}' has duplicate video_ids: {sorted(dupes)}. "
                "Each video_id must appear exactly once."
            )
    
    # Check protocol consistency across models
    model_names = list(model_data.keys())
    ref_name = model_names[0]
    ref_records = model_data[ref_name]
    
    def _get_consistent_field(records, field, model_name):
        """Get the unique value of a field across all records.
        
        Raises ValueError if any record is missing the field or values differ.
        """
        values = set()
        for r in records:
            v = r.get(field)
            if v is None:
                raise ValueError(
                    f"Record {r.get('video_id', '???')} in model '{model_name}' "
                    f"is missing required field '{field}'. "
                    f"Every record must have a non-null {field}."
                )
            values.add(str(v))
        if len(values) > 1:
            raise ValueError(
                f"Inconsistent '{field}' within model '{model_name}': {values}. "
                f"All records must have the same {field}."
            )
        return list(values)[0]
    
    ref_prompt_preset = _get_consistent_field(ref_records, "prompt_preset", ref_name)
    ref_task = _get_consistent_field(ref_records, "task", ref_name)
    ref_split = _get_consistent_field(ref_records, "split", ref_name)
    
    for name in model_names[1:]:
        records = model_data[name]
        prompt_preset = _get_consistent_field(records, "prompt_preset", name)
        task = _get_consistent_field(records, "task", name)
        split = _get_consistent_field(records, "split", name)
        
        if prompt_preset != ref_prompt_preset:
            raise ValueError(
                f"Inconsistent prompt_preset: '{ref_name}'={ref_prompt_preset}, "
                f"'{name}'={prompt_preset}. All models must use the same prompt_preset."
            )
        if task != ref_task:
            raise ValueError(
                f"Inconsistent task: '{ref_name}'={ref_task}, "
                f"'{name}'={task}. All models must use the same task."
            )
        if split != ref_split:
            raise ValueError(
                f"Inconsistent split: '{ref_name}'={ref_split}, "
                f"'{name}'={split}. All models must use the same split."
            )
    
    print(f"[info] Protocol consistent across {len(model_names)} models: "
          f"preset={ref_prompt_preset}, task={ref_task}, split={ref_split}")

    # Check generation_config consistency across models
    ref_gen_cfg_str = json.dumps(_check_generation_config(ref_records), sort_keys=True)
    for name in model_names[1:]:
        records = model_data[name]
        gen_cfg_str = json.dumps(_check_generation_config(records), sort_keys=True)
        if gen_cfg_str != ref_gen_cfg_str:
            raise ValueError(
                f"Inconsistent generation_config: '{ref_name}' has {ref_gen_cfg_str}, "
                f"'{name}' has {gen_cfg_str}. All models must use the same generation parameters "
                f"(do_sample, num_beams, max_new_tokens, etc.) for fair comparison."
            )


def _compute_model_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute all summary metrics for one model."""
    total = len(records)
    
    # Basic validity
    json_valid = sum(1 for r in records if r.get("json_valid", False))
    schema_valid = sum(1 for r in records if r.get("schema_valid", False))
    
    # Has_fracture accuracy
    hf_correct = sum(
        1 for r in records
        if r.get("gt_has_fracture") == r.get("pred_has_fracture")
    )
    has_fracture_accuracy = hf_correct / total if total else 0.0
    
    # Type metrics
    type_metrics, _, _ = compute_type_metrics(records)
    
    # Interval metrics
    interval_metrics, _ = compute_interval_metrics(records)
    
    # Joint interval metrics
    joint_metrics, _ = compute_joint_interval_metrics(records)
    
    summary = {
        "total_samples": total,
        "json_valid_rate": round(json_valid / total, 6) if total else 0.0,
        "schema_valid_rate": round(schema_valid / total, 6) if total else 0.0,
        "has_fracture_accuracy": round(has_fracture_accuracy, 6),
        "type_accuracy": type_metrics.get("accuracy", 0.0),
        "macro_f1": type_metrics.get("macro_f1", 0.0),
        "false_positive_rate": type_metrics.get("false_positive_rate", 0.0),
        "false_negative_rate": type_metrics.get("false_negative_rate", 0.0),
        "interval_hit_rate": interval_metrics.get("interval_hit_rate"),
        "midpoint_mae": interval_metrics.get("midpoint_mae"),
        "midpoint_mse": interval_metrics.get("midpoint_mse"),
        "within_1s": interval_metrics.get("within_1s"),
        "within_3s": interval_metrics.get("within_3s"),
        "within_5s": interval_metrics.get("within_5s"),
        "joint_success_rate": joint_metrics.get("joint_success_rate", 0.0),
        "unparseable_or_invalid_rate": interval_metrics.get("unparseable_or_invalid_rate", 0.0),
    }
    return summary


def _compute_delta(summary_a: dict[str, Any], summary_b: dict[str, Any]) -> dict[str, Any]:
    """Compute delta (B - A) between two model summaries.
    
    For rate/metric values, shows the difference.
    """
    delta = {}
    for key in summary_a:
        val_a = summary_a[key]
        val_b = summary_b.get(key)
        if val_a is not None and val_b is not None:
            if isinstance(val_a, (int, float)):
                delta[key] = round(val_b - val_a, 6)
            elif isinstance(val_a, str):
                delta[key] = f"{val_a} -> {val_b}" if val_b else val_a
            else:
                delta[key] = val_b
        elif val_b is not None:
            delta[key] = val_b
        else:
            delta[key] = None
    return delta


def _build_paired_samples(
    model_data: dict[str, list[dict[str, Any]]],
    common_ids: set[str],
) -> list[dict[str, Any]]:
    """Build paired per-video comparison table.
    
    For each video_id, show GT, and whether each model was correct.
    """
    # Index by video_id for each model
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for name, records in model_data.items():
        for r in records:
            vid = r.get("video_id")
            if vid in common_ids:
                if vid not in indexed:
                    indexed[vid] = {}
                indexed[vid][name] = r
    
    rows = []
    for vid in sorted(common_ids):
        if vid not in indexed:
            continue
        model_records = indexed[vid]
        
        # Get GT info from first available model record
        gt_type = None
        gt_hf = None
        for r in model_records.values():
            gt_type = r.get("gt_type")
            gt_hf = r.get("gt_has_fracture")
            if gt_type is not None:
                break
        
        row: dict[str, Any] = {
            "video_id": vid,
            "gt_type": gt_type,
            "gt_has_fracture": gt_hf,
        }
        
        model_names = list(model_data.keys())
        for name in model_names:
            r = model_records.get(name)
            if r is not None:
                # Correctness: joint success per the definition
                correct = _is_joint_correct(r)
                row[f"{name}_correct"] = correct
                row[f"{name}_type"] = r.get("pred_type_norm")
                row[f"{name}_schema_valid"] = r.get("schema_valid", False)
            else:
                row[f"{name}_correct"] = False
                row[f"{name}_type"] = None
                row[f"{name}_schema_valid"] = False
        
        # Determine improvement/regression
        if len(model_names) >= 2:
            base_name = model_names[0]
            finetuned_name = model_names[1]
            base_correct = row.get(f"{base_name}_correct", False)
            ft_correct = row.get(f"{finetuned_name}_correct", False)
            if base_correct and not ft_correct:
                row["change"] = "regression"
            elif not base_correct and ft_correct:
                row["change"] = "improvement"
            elif base_correct == ft_correct:
                row["change"] = "same"
            else:
                row["change"] = "unknown"
        
        rows.append(row)
    
    return rows


def _is_joint_correct(record: dict[str, Any]) -> bool:
    """Determine if a single record is 'joint correct' per interval protocol."""
    if not record.get("schema_valid", False) or not record.get("json_valid", False):
        return False
    gt_type = record.get("gt_type")
    pred_type = record.get("pred_type_norm")
    gt_hf = record.get("gt_has_fracture")
    pred_hf = record.get("pred_has_fracture")
    
    # has_fracture correct?
    if gt_hf != pred_hf:
        return False
    
    if gt_type in FRACTURE_CLASSES:
        # Type correct?
        if pred_type != gt_type:
            return False
        # Interval hit?
        if record.get("time_available"):
            tr = record.get("pred_time_range_sec")
            if tr is None:
                return False
            # Must be a length-2 list/tuple of finite numbers
            if not isinstance(tr, (list, tuple)) or len(tr) != 2:
                return False
            try:
                low, high = float(tr[0]), float(tr[1])
                if not math.isfinite(low) or not math.isfinite(high):
                    return False
            except (TypeError, ValueError):
                return False
            gt_time = record.get("gt_time_sec")
            if gt_time is None:
                return False
            if not (low <= gt_time <= high):
                return False
        return True
    else:
        # Non-fracture: should not have fracture_between
        if record.get("pred_fracture_between") is not None:
            return False
        return True


def _build_by_type_delta(
    model_data: dict[str, list[dict[str, Any]]],
    common_ids: set[str],
) -> list[dict[str, Any]]:
    """Build per-gt_type comparison delta table."""
    # Group records by gt_type
    by_type: dict[str, dict[str, int]] = {}
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for name, records in model_data.items():
        for r in records:
            vid = r.get("video_id")
            if vid not in common_ids:
                continue
            if vid not in indexed:
                indexed[vid] = {}
            indexed[vid][name] = r
    
    for vid in common_ids:
        if vid not in indexed:
            continue
        gt_type = None
        for r in indexed[vid].values():
            gt_type = r.get("gt_type")
            if gt_type:
                break
        if gt_type is None:
            continue
        if gt_type not in by_type:
            by_type[gt_type] = {"total": 0}
        by_type[gt_type]["total"] += 1
        
        for name in model_data:
            r = indexed[vid].get(name)
            if r is not None and _is_joint_correct(r):
                by_type[gt_type][f"{name}_correct"] = by_type[gt_type].get(f"{name}_correct", 0) + 1
    
    rows = []
    model_names = list(model_data.keys())
    for gt_type in sorted(by_type.keys()):
        row: dict[str, Any] = {"gt_type": gt_type, "total": by_type[gt_type]["total"]}
        for name in model_names:
            correct = by_type[gt_type].get(f"{name}_correct", 0)
            total = by_type[gt_type]["total"]
            row[f"{name}_accuracy"] = round(correct / total, 6) if total else 0.0
            row[f"{name}_correct_count"] = correct
        
        if len(model_names) >= 2:
            acc_base = row.get(f"{model_names[0]}_accuracy", 0.0)
            acc_ft = row.get(f"{model_names[1]}_accuracy", 0.0)
            row["delta"] = round(acc_ft - acc_base, 6)
        
        rows.append(row)
    
    return rows


def _gteq(a: Any, b: Any) -> bool:
    """Compare two values for equality, with tolerance for floats."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
        return abs(a - b) < 1e-6
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    return a == b


def _validate_gt_consistency(model_data: dict[str, list[dict[str, Any]]]) -> None:
    """Verify that GT fields are consistent across all models for every common video_id.
    
    Fields checked: gt_type, gt_has_fracture, gt_time_sec, time_available, gt_location.
    """
    GT_FIELDS = ["gt_type", "gt_has_fracture", "gt_time_sec", "time_available", "gt_location"]
    
    # Index all records by video_id for each model
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for name, records in model_data.items():
        for r in records:
            vid = r.get("video_id")
            if vid is not None:
                if vid not in indexed:
                    indexed[vid] = {}
                indexed[vid][name] = r
    
    model_names = list(model_data.keys())
    ref_name = model_names[0]
    
    for vid in sorted(indexed):
        ref_record = indexed[vid].get(ref_name)
        if ref_record is None:
            continue
        for name in model_names[1:]:
            other_record = indexed[vid].get(name)
            if other_record is None:
                continue
            for field in GT_FIELDS:
                ref_val = ref_record.get(field)
                other_val = other_record.get(field)
                if not _gteq(ref_val, other_val):
                    raise ValueError(
                        f"Ground truth mismatch for video_id '{vid}': "
                        f"'{ref_name}' has {field}={ref_val!r}, "
                        f"'{name}' has {field}={other_val!r}. "
                        f"All models must use identical ground truth labels."
                    )


def main() -> None:
    args = parse_args()
    model_data = _parse_inputs(args.inputs)
    
    if len(model_data) < 2:
        print(f"[warn] Only {len(model_data)} model(s) provided. Delta comparison requires at least 2.")
    
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Verify common video_ids
    common_ids = _check_common_video_ids(model_data)
    
    # Verify protocol consistency
    _validate_consistency(model_data)
    
    # Verify ground truth consistency
    _validate_gt_consistency(model_data)
    
    print(f"[info] Common video_ids: {len(common_ids)}")
    
    # Compute per-model summaries
    summaries: dict[str, dict[str, Any]] = {}
    for name, records in model_data.items():
        summary = _compute_model_summary(records)
        summaries[name] = summary
        write_json(out_dir / f"{name}_summary.json", summary)
        print(f"[info] {name}: interval_hit={summary.get('interval_hit_rate')}, "
              f"midpoint_mae={summary.get('midpoint_mae')}, "
              f"joint_success_rate={summary.get('joint_success_rate')}")
    
    # Build combined summary
    model_names = list(model_data.keys())
    combined: dict[str, Any] = {"models": {}}
    for name in model_names:
        combined["models"][name] = summaries[name]
    
    # Compute deltas if 2+ models
    if len(model_names) >= 2:
        base_name = model_names[0]
        for other_name in model_names[1:]:
            delta = _compute_delta(summaries[base_name], summaries[other_name])
            combined[f"delta_{other_name}_vs_{base_name}"] = delta
    
    write_json(out_dir / "model_summary.json", combined)
    
    # Delta summary (if exactly 2 models, write as separate file too)
    if len(model_names) == 2:
        delta = _compute_delta(summaries[model_names[0]], summaries[model_names[1]])
        write_json(out_dir / "delta_summary.json", delta)
        print(f"[info] Delta ({model_names[1]} - {model_names[0]}):")
        for key, val in sorted(delta.items()):
            if val is not None:
                print(f"  {key}: {val}")
    
    # Paired samples table
    paired = _build_paired_samples(model_data, common_ids)
    if paired:
        paired_fields = ["video_id", "gt_type", "gt_has_fracture"]
        for name in model_names:
            paired_fields.append(f"{name}_correct")
            paired_fields.append(f"{name}_type")
            paired_fields.append(f"{name}_schema_valid")
        if len(model_names) >= 2:
            paired_fields.append("change")
        write_csv(out_dir / "paired_samples.csv", paired_fields, paired)
    
    # By-type delta
    by_type_rows = _build_by_type_delta(model_data, common_ids)
    if by_type_rows:
        by_type_fields = ["gt_type", "total"]
        for name in model_names:
            by_type_fields.append(f"{name}_accuracy")
            by_type_fields.append(f"{name}_correct_count")
        if len(model_names) >= 2:
            by_type_fields.append("delta")
        write_csv(out_dir / "by_type_delta.csv", by_type_fields, by_type_rows)
    
    print(f"Wrote comparison artifacts to {out_dir}")


if __name__ == "__main__":
    main()
