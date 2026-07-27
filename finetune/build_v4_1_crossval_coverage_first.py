"""Deterministic source-level split and capacity-aware sampling helpers."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any, Iterable, Mapping


def candidate_id(item: Mapping[str, Any]) -> str:
    return str(item["candidate_id"])


def freeze_source_folds(candidates: Iterable[Mapping[str, Any]], seed: int = 3407) -> dict[int, set[str]]:
    sources = sorted({str(x["source_video"]) for x in candidates})
    random.Random(seed).shuffle(sources)
    return {fold: set(sources[fold::3]) for fold in range(3)}


def build_fold(candidates: list[Mapping[str, Any]], fold: int, seed: int, rows: int = 3000) -> dict[str, Any]:
    if fold not in (0, 1, 2):
        raise ValueError("fold must be 0, 1, or 2")
    folds = freeze_source_folds(candidates)
    validation = [x for x in candidates if str(x["source_video"]) in folds[fold]]
    training = [x for x in candidates if str(x["source_video"]) not in folds[fold]]
    if len(training) > rows:
        raise ValueError("unique training candidates exceed row budget")
    rng = random.Random(seed)
    multiset = list(training)
    by_state: dict[str, list[Mapping[str, Any]]] = {}
    for item in training:
        by_state.setdefault(str((item.get("labels") or {}).get("clip_state")), []).append(item)
    states = sorted(by_state)
    cursor = 0
    while len(multiset) < rows:
        state = states[cursor % len(states)]
        pool = by_state[state]
        multiset.append(pool[rng.randrange(len(pool))])
        cursor += 1
    rng.shuffle(multiset)
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
            "actual_state_quota": dict(Counter(str((x.get("labels") or {}).get("clip_state")) for x in multiset)),
            "candidate_multiset_sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest(),
            "candidate_order_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
            "validation_sources": sorted(folds[fold]),
            "capacity_reallocation_reason": "deterministic_round_robin_over_available_states",
        },
    }
