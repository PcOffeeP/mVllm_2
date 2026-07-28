"""Deterministic source-level split and capacity-aware sampling helpers.

The current three-fold identity must preserve the already-trained fold0.  The
remaining development sources are assigned to folds 1 and 2 deterministically;
silently repartitioning fold0 would invalidate the seed3407 reuse gate.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from pipeline.v4_1_labels import CLIP_STATES

ROWS_PER_EPOCH = 3000
SOURCE_COUNT_CAP = 150
SIGNATURE_COUNT_CAP = 3
CLIP_STATE_ORDER = ("未断裂", "临界未断裂", "发生断裂", "已断裂", "无法判断")


def candidate_id(item: Mapping[str, Any]) -> str:
    return str(item["candidate_id"])


def freeze_source_folds(
    candidates: Iterable[Mapping[str, Any]],
    seed: int = 3407,
    *,
    fold0_validation_sources: Iterable[str] | None = None,
) -> dict[int, set[str]]:
    sources = sorted({str(x["source_video"]) for x in candidates})
    if fold0_validation_sources is None:
        random.Random(seed).shuffle(sources)
        return {fold: set(sources[fold::3]) for fold in range(3)}
    fold0 = {str(source) for source in fold0_validation_sources}
    unknown = fold0 - set(sources)
    if not fold0 or unknown:
        raise ValueError(f"fold0 validation sources are empty or unknown: {sorted(unknown)}")
    remaining = [source for source in sources if source not in fold0]
    random.Random(seed).shuffle(remaining)
    folds = {0: fold0, 1: set(remaining[::2]), 2: set(remaining[1::2])}
    if set.union(*folds.values()) != set(sources):
        raise AssertionError("frozen source folds do not cover development sources")
    return folds


def _state(item: Mapping[str, Any]) -> str:
    state = str((item.get("labels") or {}).get("clip_state") or "")
    if state not in CLIP_STATES:
        raise ValueError(f"unsupported clip_state: {state!r}")
    return state


def _signature(item: Mapping[str, Any]) -> str:
    value = str(item.get("effective_frame_signature") or item["candidate_id"])
    if not value:
        raise ValueError("candidate has no effective-frame signature")
    return value


def _desired_state_quotas(training: Sequence[Mapping[str, Any]], rows: int) -> dict[str, int]:
    """Return the preregistered target before capacity redistribution."""
    present = [
        state
        for state in CLIP_STATE_ORDER
        if any(_state(item) == state for item in training)
    ]
    if not present:
        raise ValueError("training candidate pool is empty")
    quotas = {state: 0 for state in present}
    if "未断裂" in quotas:
        quotas["未断裂"] = min(900, rows)
    remainder = rows - sum(quotas.values())
    other = [state for state in present if state != "未断裂"]
    recipients = other or present
    for index in range(remainder):
        quotas[recipients[index % len(recipients)]] += 1
    return quotas


def _capacity_aware_multiset(
    training: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    rows: int,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    if len(training) > rows:
        raise ValueError("unique training candidates exceed row budget")
    ordered = sorted(training, key=candidate_id)
    source_counts = Counter(str(item["source_video"]) for item in ordered)
    signature_counts = Counter(_signature(item) for item in ordered)
    if max(source_counts.values(), default=0) > SOURCE_COUNT_CAP:
        raise ValueError("unique coverage exceeds source cap")
    if max(signature_counts.values(), default=0) > SIGNATURE_COUNT_CAP:
        raise ValueError("unique coverage exceeds signature cap")

    desired = _desired_state_quotas(ordered, rows)
    actual = Counter(_state(item) for item in ordered)
    selected = list(ordered)
    repeat_counts = Counter(candidate_id(item) for item in ordered)
    rng = random.Random(seed)
    tie_break = {candidate_id(item): rng.random() for item in ordered}

    while len(selected) < rows:
        eligible: dict[str, list[Mapping[str, Any]]] = {}
        for item in ordered:
            source = str(item["source_video"])
            signature = _signature(item)
            if source_counts[source] >= SOURCE_COUNT_CAP:
                continue
            if signature_counts[signature] >= SIGNATURE_COUNT_CAP:
                continue
            eligible.setdefault(_state(item), []).append(item)
        if not eligible:
            raise ValueError("source/signature caps cannot satisfy 3000-row budget")
        under_target = [
            state for state in eligible if actual[state] < desired.get(state, 0)
        ]
        states = under_target or list(eligible)
        chosen_state = min(
            states,
            key=lambda state: (
                actual[state] - desired.get(state, 0),
                actual[state],
                state,
            ),
        )
        item = min(
            eligible[chosen_state],
            key=lambda candidate: (
                repeat_counts[candidate_id(candidate)],
                tie_break[candidate_id(candidate)],
                candidate_id(candidate),
            ),
        )
        selected.append(item)
        actual[chosen_state] += 1
        repeat_counts[candidate_id(item)] += 1
        source_counts[str(item["source_video"])] += 1
        signature_counts[_signature(item)] += 1

    rng.shuffle(selected)
    reason = (
        "none"
        if all(actual[state] == desired.get(state, 0) for state in actual)
        else "deterministic_capacity_constrained_redistribution"
    )
    return selected, {
        "target_state_quota": dict(sorted(desired.items())),
        "actual_state_quota": dict(sorted(actual.items())),
        "state_quota_delta": {
            state: actual[state] - desired.get(state, 0)
            for state in sorted(set(desired) | set(actual))
        },
        "capacity_reallocation_reason": reason,
        "source_count_cap": SOURCE_COUNT_CAP,
        "signature_count_cap": SIGNATURE_COUNT_CAP,
        "max_source_count": max(source_counts.values()),
        "max_signature_count": max(signature_counts.values()),
    }


def build_fold(
    candidates: list[Mapping[str, Any]],
    fold: int,
    seed: int,
    rows: int = ROWS_PER_EPOCH,
    *,
    fold0_validation_sources: Iterable[str] | None = None,
) -> dict[str, Any]:
    if fold not in (0, 1, 2):
        raise ValueError("fold must be 0, 1, or 2")
    folds = freeze_source_folds(
        candidates,
        seed,
        fold0_validation_sources=fold0_validation_sources,
    )
    validation = [x for x in candidates if str(x["source_video"]) in folds[fold]]
    training = [x for x in candidates if str(x["source_video"]) not in folds[fold]]
    multiset, quota = _capacity_aware_multiset(training, seed=seed, rows=rows)
    ids = [candidate_id(x) for x in multiset]
    return {
        "train": training,
        "validation": validation,
        "multiset": multiset,
        "sampling_manifest": {
            "fold": fold,
            "seed": seed,
            "target_rows": rows,
            "unique_coverage_count": len(training),
            **quota,
            "candidate_multiset_sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest(),
            "candidate_order_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
            "validation_sources_by_fold": {
                str(index): sorted(values) for index, values in folds.items()
            },
            "validation_sources": sorted(folds[fold]),
            "development_source_count": len(set.union(*folds.values())),
        },
    }
