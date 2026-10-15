"""Pure development baselines and paired semantic comparisons.

No model, media file, or test truth is loaded here. Callers freeze the actual
media manifests and provide the same complete sample list on both sides.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from typing import Any

from finetune.eval_semantics import FIELDS, PROTOCOL, extract_semantics, score_semantic_records
from pipeline.v4_1_labels import canonicalize_v4_1_labels
from versioning.ids import parse_data_id

BASELINE_SCHEMA = "tensile-vlm/v4.1-majority-baseline"
COMPARISON_SCHEMA = "tensile-vlm/v4.1-paired-comparison"
COMPARISON_KEYS = frozenset({"media_sampling", "prompt", "decode", "scorer"})


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("baseline evidence must contain finite JSON values") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _identity(row: Mapping) -> str:
    value = row.get("candidate_id", row.get("sample_id"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("each fixed sample requires candidate_id or sample_id")
    return value


def build_majority_baseline(development_records: Sequence[Mapping], *,
                            development_data_id: str, fit_split: str) -> dict:
    """Freeze a joint-label mode using explicitly identified development truth.

    Validation fitting is reported explicitly, and is not evidence of generalization.
    The modal *complete tuple* preserves the V4.1 field relationships. Ties use
    canonical JSON lexical order, never evaluation outcomes.
    """
    parse_data_id(development_data_id)
    if fit_split not in {"train", "validation"}:
        raise ValueError("majority baseline may only fit development train or validation")
    if not development_records:
        raise ValueError("majority baseline requires development records")
    counts, sample_ids = Counter(), []
    for row in development_records:
        if "split" in row and row["split"] != fit_split:
            raise ValueError("majority fit split disagrees with the development record")
        if "data_version" in row and row["data_version"] != development_data_id:
            raise ValueError("majority fit data identity disagrees with the development record")
        labels = canonicalize_v4_1_labels(row["target"])
        counts[_canonical(labels)] += 1
        if "candidate_id" in row or "sample_id" in row:
            sample_ids.append(_identity(row))
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("duplicate majority fit sample identity")
    winner = min(counts, key=lambda label: (-counts[label], label))
    frozen = {
        "schema_version": BASELINE_SCHEMA,
        "method": "joint_label_mode",
        "tie_break": "canonical_json_lexical_order",
        "development_data_id": development_data_id,
        "fit_split": fit_split,
        "fit_sample_count": len(development_records),
        "fit_sample_ids": sorted(sample_ids),
        "fit_sample_ids_complete": len(sample_ids) == len(development_records),
        "target_counts": [{"target": json.loads(label), "count": counts[label]} for label in sorted(counts)],
        "prediction": json.loads(winner),
        "generalization_claim": "not_established_by_baseline",
    }
    return {**frozen, "fit_digest": _digest(frozen)}


def _validate_baseline(frozen: Mapping) -> None:
    if not isinstance(frozen, Mapping):
        raise ValueError("majority baseline must be a frozen mapping")
    unsigned = {key: value for key, value in frozen.items() if key != "fit_digest"}
    if frozen.get("fit_digest") != _digest(unsigned):
        raise ValueError("majority baseline frozen parameters drift")
    expected = {"schema_version", "method", "tie_break", "development_data_id", "fit_split",
                "fit_sample_count", "fit_sample_ids", "fit_sample_ids_complete", "target_counts",
                "prediction", "generalization_claim", "fit_digest"}
    if set(frozen) != expected or frozen["schema_version"] != BASELINE_SCHEMA:
        raise ValueError("unsupported majority baseline schema")
    counts = {}
    for entry in frozen["target_counts"]:
        if not isinstance(entry, Mapping) or set(entry) != {"target", "count"}:
            raise ValueError("invalid majority target counts")
        if type(entry["count"]) is not int or entry["count"] <= 0:
            raise ValueError("invalid majority target count")
        label = _canonical(canonicalize_v4_1_labels(entry["target"]))
        if label in counts:
            raise ValueError("duplicate majority target counts")
        counts[label] = entry["count"]
    if not counts:
        raise ValueError("empty majority target counts")
    parse_data_id(frozen["development_data_id"])
    if frozen["fit_split"] not in {"train", "validation"}:
        raise ValueError("majority fit must use development data")
    sample_count = sum(counts.values())
    expected_parameters = {"method": "joint_label_mode", "tie_break": "canonical_json_lexical_order",
                           "fit_sample_count": sample_count,
                           "target_counts": [{"target": json.loads(label), "count": counts[label]} for label in sorted(counts)],
                           "prediction": json.loads(min(counts, key=lambda label: (-counts[label], label))),
                           "generalization_claim": "not_established_by_baseline"}
    for key, expected_value in expected_parameters.items():
        if _canonical(frozen[key]) != _canonical(expected_value):
            raise ValueError(f"majority frozen parameter mismatch: {key}")
    ids = frozen["fit_sample_ids"]
    if (not isinstance(ids, list) or any(not isinstance(value, str) or not value.strip() for value in ids)
            or ids != sorted(set(ids)) or len(ids) > sample_count
            or type(frozen["fit_sample_ids_complete"]) is not bool
            or frozen["fit_sample_ids_complete"] != (len(ids) == sample_count)):
        raise ValueError("invalid majority fit sample identities")


def majority_baseline_records(frozen: Mapping, evaluation_records: Sequence[Mapping]) -> list[dict]:
    """Apply frozen labels without reading evaluation targets to choose predictions.

    These are explicitly synthetic predictions, so their JSON validity or runtime
    does not measure a model's output reliability or service performance.
    """
    _validate_baseline(frozen)
    if not evaluation_records:
        raise ValueError("majority evaluation requires the complete non-empty sample list")
    result, seen = [], set()
    for row in evaluation_records:
        identity = _identity(row)
        if identity in seen:
            raise ValueError("duplicate majority evaluation sample identity")
        seen.add(identity)
        copied = deepcopy(dict(row))
        # Remove any previous response/judge evidence instead of accidentally
        # scoring it as the majority predictor.
        for key in ("semantics", "blind_review", "scores", "parse_error", "runtime_error",
                    "generated_token_count", "hit_token_limit", "sampled_timestamps"):
            copied.pop(key, None)
        copied.update({"raw_output": _canonical(frozen["prediction"]),
                       "prediction": deepcopy(frozen["prediction"]), "strict_valid": True,
                       "baseline_kind": "synthetic_majority", "baseline_fit_digest": frozen["fit_digest"],
                       "baseline_fit_overlap": True if identity in frozen["fit_sample_ids"] else
                           (False if frozen["fit_sample_ids_complete"] else None)})
        result.append(copied)
    return result


def _comparison_config(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or set(value) != COMPARISON_KEYS:
        raise ValueError("comparison config requires media_sampling, prompt, decode and scorer")
    if any(item is None or item == "" or item == {} or item == [] for item in value.values()):
        raise ValueError("comparison conditions must be explicitly frozen and non-empty")
    if any(not isinstance(value[key], Mapping) for key in ("media_sampling", "prompt", "decode")):
        raise ValueError("media sampling, Prompt and decode require frozen configuration mappings")
    scorer = value["scorer"]
    protocol = scorer.get("protocol") if isinstance(scorer, Mapping) else scorer
    if protocol != PROTOCOL:
        raise ValueError("paired comparison requires the actual semantic-v4.1 scorer")
    _canonical(value)
    return deepcopy(dict(value))


def _indexed_records(records: Sequence[Mapping]) -> dict[str, dict]:
    if not records:
        raise ValueError("paired comparison requires complete non-empty records")
    result = {}
    for row in records:
        identity = _identity(row)
        if identity in result:
            raise ValueError("duplicate paired sample identity")
        if not any(isinstance(row.get(key), str) and row[key].strip() for key in ("video_path", "media_sha256")):
            raise ValueError("paired samples require an explicit media identity")
        if "raw_output" not in row:
            raise ValueError("paired samples require frozen raw output, including failed outputs")
        result[identity] = {**row, "sample_id": row.get("sample_id", identity)}
    return result


def compare_paired_records(base_records: Sequence[Mapping], trained_records: Sequence[Mapping], *,
                           base_config: Mapping, trained_config: Mapping,
                           absolute_gate_result: Mapping | None = None) -> dict:
    """Compare every fixed sample, keeping absolute gates separate from changes.

    Input paths/digests are compared as frozen identities, not read from disk.
    Formal callers must have verified media bytes against their frozen manifests.
    A failed call's output remains in the denominator and is never filtered.
    """
    base_conditions = _comparison_config(base_config)
    trained_conditions = _comparison_config(trained_config)
    if _canonical(base_conditions) != _canonical(trained_conditions):
        raise ValueError("paired media sampling, Prompt, decode or scorer mismatch")
    left, right = _indexed_records(base_records), _indexed_records(trained_records)
    if set(left) != set(right):
        raise ValueError("paired sample identities must match the complete fixed list")
    for identity in left:
        for key in ("candidate_id", "sample_id", "video_path", "media_sha256",
                    "source_video", "source_group", "source_id", "target"):
            if (key in left[identity]) != (key in right[identity]) or _canonical(left[identity].get(key)) != _canonical(right[identity].get(key)):
                raise ValueError(f"paired sample {identity} has mismatched {key}")
        # A call that failed before decoding may have no sampled-frame receipt.
        # Keep that failure; when both sides have receipts they must agree.
        left_frames, right_frames = left[identity].get("sampled_timestamps"), right[identity].get("sampled_timestamps")
        if left_frames and right_frames and _canonical(left_frames) != _canonical(right_frames):
            raise ValueError(f"paired sample {identity} has mismatched sampled_timestamps")
    # The scorer revalidates deterministic/closed review evidence and never trusts
    # caller-provided correctness flags.
    base_summary = score_semantic_records(list(left.values()), bootstrap=False)
    trained_summary = score_semantic_records(list(right.values()), bootstrap=False)
    changes = {field: Counter({"improved": 0, "regressed": 0, "unchanged_correct": 0,
                              "unchanged_incorrect": 0}) for field in (*FIELDS, "joint")}
    samples = []
    measurement_complete = True
    for identity, base in left.items():
        trained = right[identity]
        correctness = []
        sample_complete = True
        for row in (base, trained):
            semantics = extract_semantics(row["raw_output"], runtime_error=row.get("runtime_error"),
                                          blind_review=row.get("blind_review"))
            fields = semantics["fields"]
            sample_complete = sample_complete and semantics.get("review_complete", True)
            correct = {field: field in fields and fields[field] == row["target"][field] for field in FIELDS}
            correct["joint"] = all(correct.values())
            correctness.append(correct)
        outcomes = {}
        for field in changes:
            before, after = (correct[field] for correct in correctness)
            outcome = ("unchanged_correct" if before else "improved") if after else ("regressed" if before else "unchanged_incorrect")
            changes[field][outcome] += 1
            outcomes[field] = outcome
        measurement_complete = measurement_complete and sample_complete
        samples.append({"sample_id": identity,
                        "outcomes": outcomes if sample_complete else {field: "measurement_incomplete" for field in changes},
                        "provisional_outcomes": outcomes if not sample_complete else None,
                        "measurement_complete": sample_complete,
                        "base_runtime_failure": bool(base.get("runtime_error")),
                        "trained_runtime_failure": bool(trained.get("runtime_error"))})
    total = len(left)
    paired = {field: {**dict(counts), "net_correct_delta": counts["improved"] - counts["regressed"],
                      "net_correct_rate_delta": (counts["improved"] - counts["regressed"]) / total}
              for field, counts in changes.items()}
    delta = {key: trained_summary["metrics"][key] - value
             if value is not None and trained_summary["metrics"][key] is not None else None
             for key, value in base_summary["metrics"].items()}
    if absolute_gate_result is not None and not isinstance(absolute_gate_result, Mapping):
        raise ValueError("absolute gate result must be an independently computed mapping")
    return {"schema_version": COMPARISON_SCHEMA, "sample_count": total,
            "conditions": base_conditions, "conditions_sha256": _digest(base_conditions),
            "base": base_summary, "trained": trained_summary, "metric_delta": delta,
            "paired": paired if measurement_complete else None,
            "provisional_paired": paired if not measurement_complete else None,
            "measurement_complete": measurement_complete, "samples": samples,
            "absolute_gate_result": deepcopy(absolute_gate_result),
            "relative_improvement_is_gate": False}
