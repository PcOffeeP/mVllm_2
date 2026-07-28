"""Build the unique-coverage plus balanced-repeat full-development multiset."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any, Mapping


def build_full_development(candidates: list[Mapping[str, Any]], seed: int = 3407, rows: int = 3000) -> dict[str, Any]:
    by_id = {str(x["candidate_id"]): x for x in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("duplicate published candidate_id")
    if len(by_id) > rows:
        raise ValueError("published development set exceeds per-epoch row budget")
    unique = [by_id[x] for x in sorted(by_id)]
    rng = random.Random(seed)
    repeat = []
    cursor = 0
    states: dict[str, list[Mapping[str, Any]]] = {}
    for item in unique:
        states.setdefault(str((item.get("labels") or {}).get("clip_state")), []).append(item)
    keys = sorted(states)
    while len(unique) + len(repeat) < rows:
        pool = states[keys[cursor % len(keys)]]
        repeat.append(pool[rng.randrange(len(pool))])
        cursor += 1
    rows_out = unique + repeat
    rng.shuffle(rows_out)
    ids = [str(x["candidate_id"]) for x in unique]
    return {
        "rows": rows_out,
        "manifest": {
            "schema_version": "tensile-vlm-v4.1-full-development-dataset/v1",
            "candidate_count": len(unique),
            "unique_coverage_count": len(unique),
            "unique_coverage_rate": 1.0,
            "repeat_count": len(repeat),
            "candidate_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
            "state_totals": dict(Counter(str((x.get("labels") or {}).get("clip_state")) for x in rows_out)),
            "sealed_intersection_count": 0,
            "held_out_semantics_included": False,
        },
    }
