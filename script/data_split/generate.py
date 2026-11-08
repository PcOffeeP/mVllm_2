#!/usr/bin/env python3
"""Generate a new, immutable three-fold split from explicitly supplied sources.

Standard library only; rules: docs/split/data-split-design.md (legacy: docs/data-split-design.md).
The CLI requires the current 110 IDs and 21 fixed test members. Small synthetic
examples may use validate_labels(..., expected_count=None) and Problem directly.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from fractions import Fraction


RULE_VERSION = "explicit-source-five-task-v1"
FIELDS = {
    "断裂状态": ("未断裂", "发生断裂", "已断裂", "无法确定"),
    "断裂模式": ("脆性断裂", "韧性断裂", "半脆半韧断裂", "无法确定", "无"),
    "断裂位置": ("标距内", "标距外非根部", "夹持根部", "无法确定", "无"),
    **{f"异常_{name}": ("是", "否", "无法判断") for name in
       ("未夹紧", "视频异常", "爆炸性断裂")},
    **{f"现象_{name}": ("是", "否", "无法判断") for name in
       ("伸长", "颈缩", "开裂", "界面分离", "断后脱夹")},
}
TASKS = (("断裂状态",), ("断裂模式",), ("断裂位置",),
         tuple(f for f in FIELDS if f.startswith("异常_")),
         tuple(f for f in FIELDS if f.startswith("现象_")))
ALIASES = {("断裂状态", "无法判断"): "无法确定",
           ("断裂模式", "无法识别"): "无法确定"}
UNCERTAIN = {"无", "无法确定", "无法判断"}
SEEDS = tuple(range(42, 142))


class SplitError(ValueError):
    """An input or publication condition prevents producing a formal split."""


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SplitError(f"JSON duplicate key: {key}")
        result[key] = value
    return result


def _json(content):
    try:
        return json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              SplitError(f"non-finite JSON value: {value}")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SplitError(f"invalid JSON: {exc}") from exc


def _ids(value, name, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise SplitError(f"{name}: nonempty video_ids list required")
    if any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in value):
        raise SplitError(f"{name}: invalid video ID")
    if len(value) != len(set(value)):
        raise SplitError(f"{name}: duplicate video ID")
    return value


def normalize_row(row):
    """Check model semantics; normalize only the two documented legacy aliases."""
    result = dict(row)
    video_id = row.get("id")
    if not isinstance(video_id, str) or not video_id.strip() or video_id != video_id.strip():
        raise SplitError(f"invalid id: {video_id!r}")
    for field, allowed in FIELDS.items():
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SplitError(f"{video_id}: incomplete label {field}")
        # Whitespace is not silently rewritten into a different annotation.
        value = ALIASES.get((field, value), value)
        if value not in allowed:
            raise SplitError(f"{video_id}: illegal {field}={value!r}")
        result[field] = value
    state = result["断裂状态"]
    fixed_none = state == "未断裂" or result["异常_未夹紧"] == "是"
    for field in ("断裂模式", "断裂位置"):
        if (result[field] == "无") != fixed_none:
            raise SplitError(f"{video_id}: fixed 无 combination conflict in {field}")
    if state == "未断裂" and result["异常_爆炸性断裂"] == "是":
        raise SplitError(f"{video_id}: 未断裂 conflicts with 爆炸性断裂")
    if state == "未断裂" and result["现象_断后脱夹"] == "是":
        raise SplitError(f"{video_id}: 未断裂 conflicts with 断后脱夹")
    expected_status = {"未断裂": "已标注·无断裂", "发生断裂": "已标注·有断裂",
                       "已断裂": "已标注·有断裂", "无法确定": "无法判读"}[state]
    if row.get("标注状态") != expected_status:
        raise SplitError(f"{video_id}: incomplete/conflicting 标注状态")
    if result["异常_未夹紧"] == "是" and row.get("断裂时间点", "无") != "无":
        raise SplitError(f"{video_id}: 未夹紧 requires 断裂时间点=无")
    return result


def validate_labels(rows, expected_count=110):
    if expected_count is not None and len(rows) != expected_count:
        raise SplitError(f"expected {expected_count} labels, got {len(rows)}")
    labels = {}
    for row in rows:
        normalized = normalize_row(row)
        if expected_count == 110 and not re.fullmatch(r"video_\d{4}", normalized["id"]):
            raise SplitError(f"invalid formal video ID: {normalized['id']}")
        if normalized["id"] in labels:
            raise SplitError(f"duplicate label ID: {normalized['id']}")
        labels[normalized["id"]] = normalized
    if not labels:
        raise SplitError("empty labels")
    return dict(sorted(labels.items()))


def validate_groups(payload, labels, test_ids):
    """Require complete explicit provenance; never infer independence from IDs."""
    if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
        raise SplitError('groups must be {"groups": [...]}')
    test = set(_ids(test_ids, "test", allow_empty=True))
    if not test <= set(labels):
        raise SplitError(f"unknown test IDs: {sorted(test - set(labels))}")
    seen, names, groups = set(), set(), []
    for group in payload["groups"]:
        if not isinstance(group, dict):
            raise SplitError("source group must be an object")
        name = group.get("group_id")
        if not isinstance(name, str) or not name.strip() or name != name.strip() or name in names:
            raise SplitError(f"invalid or duplicate group_id: {name!r}")
        ids = _ids(group.get("video_ids"), name)
        if seen.intersection(ids):
            raise SplitError(f"duplicate source membership: {sorted(seen.intersection(ids))}")
        if set(ids).intersection(test) and set(ids) - test:
            raise SplitError(f"source group crosses test/development: {name}: {ids}")
        seen.update(ids)
        names.add(name)
        groups.append({"group_id": name, "video_ids": sorted(ids)})
    if seen != set(labels):
        raise SplitError(f"source membership incomplete: missing={sorted(set(labels)-seen)}, "
                         f"unknown={sorted(seen-set(labels))}")
    return sorted(groups, key=lambda g: g["group_id"])


class Problem:
    """Development-only objective. Assignment indices follow sorted group_id."""

    def __init__(self, labels, groups):
        self.groups = sorted(groups, key=lambda g: g["group_id"])
        if not self.groups:
            raise SplitError("no development groups")
        self.tokens = [(field, value) for field, values in FIELDS.items() for value in values]
        lookup = {token: i for i, token in enumerate(self.tokens)}
        self.features = []
        for group in self.groups:
            evidence = {(f, labels[v][f]) for v in group["video_ids"] for f in FIELDS}
            self.features.append(tuple(sorted(lookup[t] for t in evidence)))
        self.support = [sum(i in fs for fs in self.features) for i in range(len(self.tokens))]
        pair_counts = Counter(pair for fs in self.features for pair in itertools.combinations(fs, 2))
        self.pairs = sorted(pair for pair, count in pair_counts.items() if count >= 6)
        self.pair_support = [pair_counts[p] for p in self.pairs]
        pair_lookup = {p: len(self.tokens) + i for i, p in enumerate(self.pairs)}
        self.features = [fs + tuple(pair_lookup[p] for p in itertools.combinations(fs, 2)
                                    if p in pair_lookup) for fs in self.features]
        self.all_support = self.support + self.pair_support
        self.sizes = [len(g["video_ids"]) for g in self.groups]
        self.video_count = sum(self.sizes)
        self.coverage = [i for i, (_, value) in enumerate(self.tokens)
                         if value not in UNCERTAIN and self.support[i] >= 2]
        coefficients = []
        for field, value in self.tokens:
            task = next(task for task in TASKS if field in task)
            weight = Fraction(1, 2) if value in UNCERTAIN else Fraction(1)
            coefficients.append(weight / (5 * len(task) * len(FIELDS[field])))
        tables = [[Fraction(abs(3*n-g), max(3, g)) * coefficient
                   for n in range(g+1)] for g, coefficient in zip(self.support, coefficients)]
        pair_tables = [[Fraction(abs(3*n-g), max(3, g) * max(1, len(self.pairs)))
                        for n in range(g+1)] for g in self.pair_support]
        self.field_scale = math.lcm(*(v.denominator for table in tables for v in table))
        self.pair_scale = math.lcm(*(v.denominator for table in pair_tables for v in table))
        self.tables = [[int(v*self.field_scale) for v in table] for table in tables]
        self.pair_tables = [[int(v*self.pair_scale) for v in table] for table in pair_tables]

    def counts(self, assignment):
        if len(assignment) != len(self.groups) or any(type(f) is not int or f not in range(3) for f in assignment):
            raise SplitError("assignment must give every development group exactly one fold")
        counts = [[0]*len(self.all_support) for _ in range(3)]
        sizes = [0, 0, 0]
        for i, fold in enumerate(assignment):
            sizes[fold] += self.sizes[i]
            for feature in self.features[i]:
                counts[fold][feature] += 1
        return counts, sizes

    def _score(self, counts, sizes, assignment, cutoff=None):
        gap = 0
        for i in self.coverage:
            g = self.support[i]
            ns = [counts[f][i] for f in range(3)]
            gap += sum(n == 0 or n == g for n in ns) if g >= 3 else 2-sum(n > 0 for n in ns)
        deviations = [abs(3*n-self.video_count) for n in sizes]
        prefix = (gap, max(deviations), sum(deviations))
        if cutoff is not None and prefix > cutoff[:3]:
            return prefix
        field = sum(self.tables[i][counts[f][i]] for i in range(len(self.tokens)) for f in range(3))
        prefix += (field,)
        if cutoff is not None and prefix > cutoff[:4]:
            return prefix
        pair = sum(self.pair_tables[i][counts[f][i+len(self.tokens)]]
                   for i in range(len(self.pairs)) for f in range(3))
        return prefix + (pair, tuple(assignment))

    def score(self, assignment):
        return self._score(*self.counts(assignment), assignment)

    def explain_score(self, score):
        def rational(v):
            return {"numerator": v.numerator, "denominator": v.denominator}
        return {"coverage_gap": score[0], "max_video_deviation": rational(Fraction(score[1], 3)),
                "sum_video_deviation": rational(Fraction(score[2], 3)),
                "field_deviation": rational(Fraction(score[3], self.field_scale)),
                "pair_deviation": rational(Fraction(score[4], self.pair_scale)),
                "group_fold_vector": list(score[5])}


def _initial(problem, seed):
    rng = random.Random(seed)
    assignment = [-1]*len(problem.groups)
    counts = [[0]*len(problem.all_support) for _ in range(3)]
    sizes = [0, 0, 0]
    # Label order is schema order after increasing rarity, then group_id order.
    tokens = sorted(range(len(problem.tokens)), key=lambda i: (problem.support[i], i))
    order = []
    for token in tokens:
        for i, features in enumerate(problem.features):
            if token in features and i not in order:
                order.append(i)
    for i in order:
        fold_order = list(range(3))
        rng.shuffle(fold_order)
        relevant = [t for t in problem.features[i] if t < len(problem.tokens)]
        # Seed changes fold preferences while retaining rarity-first group order.
        fold = min(fold_order, key=lambda f: (sum(Fraction(counts[f][t], max(1, problem.support[t]))
                                                 for t in relevant), sizes[f]))
        assignment[i] = fold
        sizes[fold] += problem.sizes[i]
        for t in problem.features[i]:
            counts[fold][t] += 1
    return assignment


def _improve(problem, assignment):
    counts, sizes = problem.counts(assignment)
    current = problem._score(counts, sizes, assignment)
    trace = [{"operation": "initial", "score": problem.explain_score(current)}]
    def move(i, old, new):
        sizes[old] -= problem.sizes[i]
        sizes[new] += problem.sizes[i]
        for t in problem.features[i]:
            counts[old][t] -= 1
            counts[new][t] += 1
        assignment[i] = new
    passes, attempts = 0, 0
    while True:
        passes += 1
        changed = False
        for i in range(len(assignment)):
            for target in range(3):
                old = assignment[i]
                if old == target:
                    continue
                move(i, old, target)
                attempts += 1
                score = problem._score(counts, sizes, assignment, current)
                if score < current:
                    current, changed = score, True
                    trace.append({"operation": "move", "group_id": problem.groups[i]["group_id"],
                                  "from": old, "to": target, "score": problem.explain_score(score)})
                else:
                    move(i, target, old)
        for i, j in itertools.combinations(range(len(assignment)), 2):
            a, b = assignment[i], assignment[j]
            if a == b:
                continue
            move(i, a, b)
            move(j, b, a)
            attempts += 1
            score = problem._score(counts, sizes, assignment, current)
            if score < current:
                current, changed = score, True
                trace.append({"operation": "swap", "group_ids": [problem.groups[i]["group_id"],
                              problem.groups[j]["group_id"]], "score": problem.explain_score(score)})
            else:
                move(j, a, b)
                move(i, b, a)
        if not changed:
            break
    return current, trace, passes, attempts


def search(problem, seeds=SEEDS):
    candidates = []
    best, best_seed = None, None
    for seed in seeds:
        initial = _initial(problem, seed)
        score, trace, passes, attempts = _improve(problem, initial)
        candidates.append({"seed": seed, "status": "completed", "passes": passes,
                           "evaluated_neighbors": attempts, "accepted_iterations": trace,
                           "score": problem.explain_score(score)})
        if best is None or score < best:
            best, best_seed = score, seed
    if best is None:
        raise SplitError("no search starts")
    return {"best_assignment": best[5], "best_seed": best_seed, "best_score": best,
            "candidates": candidates}


def _coverage_report(problem, assignment):
    counts, _ = problem.counts(assignment)
    result = []
    for i, (field, value) in enumerate(problem.tokens):
        g = problem.support[i]
        ns = [counts[f][i] for f in range(3)]
        certain = value not in UNCERTAIN
        gap = (sum(n == 0 or n == g for n in ns) if g >= 3 else
               2-sum(n > 0 for n in ns) if g == 2 else 0) if certain else 0
        result.append({"field": field, "value": value, "support_groups": g,
                       "val_groups": ns, "train_groups": [g-n for n in ns],
                       "coverage_gap": gap, "balance_weight": 1 if certain else 0.5,
                       "unweighted_relative_deviation": [str(Fraction(abs(3*n-g), max(3, g))) for n in ns],
                       "support_group_ids": [problem.groups[j]["group_id"] for j, fs in
                                             enumerate(problem.features) if i in fs],
                       "limitation": ("uncertain_or_not_applicable_no_coverage_requirement" if not certain else
                                      "quantity_insufficient_for_three_val_folds" if g < 3 else
                                      "search_did_not_find_full_coverage" if gap else "target_met")})
    return result


def _split_ids(payload, name):
    if not isinstance(payload, dict):
        raise SplitError(f"{name}: split must be object")
    ids = _ids(payload.get("video_ids"), name)
    if "count" in payload and (type(payload["count"]) is not int or payload["count"] != len(ids)):
        raise SplitError(f"{name}: count mismatch")
    return ids


def _csv_rows(content):
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)):
            raise SplitError("CSV missing/duplicate headers")
        if not {"id", "标注状态", *FIELDS} <= set(headers):
            raise SplitError("CSV missing required model/status columns")
        rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise SplitError("CSV row width mismatch")
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise SplitError(f"invalid label CSV: {exc}") from exc


def _publish_new_directory(source, destination):
    """Atomically rename without replacing even an empty competing directory.

    POSIX os.rename can replace an existing empty directory. The native exclusive
    rename flags close that race; ctypes is part of the Python standard library.
    Unsupported platforms fail closed rather than fall back to a replacing call.
    """
    if sys.platform == "win32":
        os.rename(source, destination)  # Windows rename rejects existing targets.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise SplitError("exclusive atomic rename unavailable on this platform")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise SplitError("exclusive atomic rename unavailable on this platform")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise SplitError("exclusive atomic rename unavailable on this platform")
    if result != 0:
        code = ctypes.get_errno() or errno.EIO
        raise OSError(code, os.strerror(code), str(destination))


def resolve_design_document(root):
    """Resolve the rules document without choosing between conflicting copies.

    Both supported layouts use the existing manifest input key
    ``docs_data-split-design.md``; moving an identical document does not rename
    that evidence field or change the explicit data-input interface.
    """
    root = Path(root)
    candidates = (root / "docs/split/data-split-design.md",
                  root / "docs/data-split-design.md")
    present = []
    for path in candidates:
        if path.exists():
            if not path.is_file():
                raise SplitError(f"split design document is not a file: {path}")
            present.append(path)
    if not present:
        raise SplitError("split design document not found; expected " +
                         " or ".join(str(path) for path in candidates))
    if len(present) == 2 and present[0].read_bytes() != present[1].read_bytes():
        raise SplitError("conflicting split design documents: " +
                         " and ".join(str(path) for path in present))
    return present[0]


def generate(labels_path, test_path, groups_path, output_dir, old_splits_dir=None):
    """Read explicit inputs, search 100 starts, then publish a new directory once.

    All output bytes are deterministic for identical files, code and environment.
    Only seven membership JSON files and a manifest are published. The manifest
    hashes every membership file; its own hash is returned to the caller,
    avoiding a self-referential hash. Existing destinations are always rejected.
    """
    output = Path(output_dir).absolute()
    if output.exists() or output.is_symlink():
        raise SplitError(f"output already exists: {output}")
    inputs = {"labels.csv": Path(labels_path), "test.json": Path(test_path),
              "groups.json": Path(groups_path)}
    root = Path(__file__).resolve().parents[2]
    inputs["docs_label.md"] = root / "docs/label.md"
    inputs["docs_data-split-design.md"] = resolve_design_document(root)
    inputs["generate.py"] = Path(__file__).resolve()
    if old_splits_dir is not None:
        for fold in range(3):
            for split in ("train", "val"):
                name = f"fold_{fold}_{split}.json"
                inputs[f"old_{name}"] = Path(old_splits_dir) / name
    resolved = {name: path.resolve(strict=True) for name, path in inputs.items()}
    output_real = output.resolve()
    if any(output_real == path or output_real in path.parents for path in resolved.values()):
        raise SplitError("output may not contain or overwrite an input")
    content = {name: path.read_bytes() for name, path in resolved.items()}
    raw_rows = _csv_rows(content["labels.csv"])
    labels = validate_labels(raw_rows)
    test_ids = _split_ids(_json(content["test.json"]), "test")
    if len(test_ids) != 21:
        raise SplitError(f"expected 21 fixed test members, got {len(test_ids)}")
    groups = validate_groups(_json(content["groups.json"]), labels, test_ids)
    test = set(test_ids)
    dev_ids = set(labels) - test
    dev_groups = [g for g in groups if not test.intersection(g["video_ids"])]
    problem = Problem(labels, dev_groups)
    result = search(problem)
    assignment = result["best_assignment"]
    splits = {"test": test_ids}
    for fold in range(3):
        val = {v for i, group in enumerate(problem.groups) if assignment[i] == fold for v in group["video_ids"]}
        splits[f"fold_{fold}_val"] = sorted(val)
        splits[f"fold_{fold}_train"] = sorted(dev_ids-val)
    if any(set(splits[f"fold_{f}_train"]) & set(splits[f"fold_{f}_val"]) or
           set(splits[f"fold_{f}_train"]) | set(splits[f"fold_{f}_val"]) != dev_ids for f in range(3)):
        raise SplitError("internal train/val partition failure")
    if Counter(v for f in range(3) for v in splits[f"fold_{f}_val"]) != Counter({v: 1 for v in dev_ids}):
        raise SplitError("internal once-only validation failure")
    warnings = ["explicit_source_table_is_user_evidence_not_media_deduplication",
                "historically_exposed_test_is_not_never_used_independent_test",
                "bounded_local_search_does_not_prove_global_optimality"]
    if old_splits_dir is None:
        warnings.append("old_fold_differences_not_verified")
    else:
        old = {name: _split_ids(_json(content[f"old_{name}.json"]), name)
               for name in splits if name != "test"}
        for f in range(3):
            a, b = set(old[f"fold_{f}_train"]), set(old[f"fold_{f}_val"])
            if a & b or a | b != dev_ids:
                raise SplitError(f"old fold {f} is not a complete isolated development partition")
        old_vals = [set(old[f"fold_{f}_val"]) for f in range(3)]
        if any(old_vals[a] & old_vals[b] for a, b in itertools.combinations(range(3), 2)):
            raise SplitError("old validation folds overlap")
    coverage = _coverage_report(problem, assignment)
    if any(c["coverage_gap"] for c in coverage):
        warnings.append("remaining_coverage_gaps_require_review_search_is_not_infeasibility_proof")
    counts, sizes = problem.counts(assignment)
    if max(abs(Fraction(s)-Fraction(problem.video_count, 3)) for s in sizes) > 2:
        warnings.append("validation_video_count_deviation_exceeds_two")
    payloads = {f"{name}.json": canonical_bytes({"split": name, "video_ids": ids, "count": len(ids),
                 "method": RULE_VERSION, "fold": int(name.split("_")[1]), "seed": result["best_seed"]})
                for name, ids in splits.items() if name != "test"}
    # Preserve test bytes, order, membership and metadata exactly.
    payloads["test.json"] = content["test.json"]
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False)
    manifest = {"rule_version": RULE_VERSION, "status": "generated_split_not_model_evaluation",
        "counts": {name: len(ids) for name, ids in splits.items()},
        "search_summary": {"start_count": len(SEEDS), "best_seed": result["best_seed"],
                           "best_score": problem.explain_score(result["best_score"]),
                           "global_optimality_proven": False, "test_labels_used_for_objective": False},
        "inputs": {name: {"sha256": sha256(data)} for name, data in sorted(content.items())},
        "outputs": {name: {"sha256": sha256(data)} for name, data in sorted(payloads.items())},
        "code_commit": git.stdout.strip() if git.returncode == 0 else None,
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                        "system": platform.system(), "machine": platform.machine()},
        "config": {"seeds": list(SEEDS), "folds": 3, "expected_labels": 110, "expected_test": 21,
            "label_order": [[f, list(v)] for f, v in FIELDS.items()], "tasks": TASKS,
            "objective_order": ["coverage_gap", "max_video_deviation", "sum_video_deviation",
                                "field_deviation", "pair_deviation", "group_fold_vector"],
            "field_formula": "sum_tasks(mean_fields(mean_all_allowed_values(weight * sum_folds(abs(3*n-g)/max(3,g))))) / 5",
            "pair_formula": "mean_pairs_support_ge_6(sum_folds(abs(3*n-g)/max(3,g)))",
            "initialization": "rare_label_then_group_id; local_seed_shuffles_fold_ties",
            "improvement": "stable_group_id_single_moves_then_pairs; strict_lex_improvement_until_no_improvement"},
        "hash_rule": "SHA-256 of exact file bytes; manifest excludes itself; no timestamps or absolute input paths",
        "manual_exceptions": [], "warnings": warnings}
    payloads["manifest.json"] = canonical_bytes(manifest)
    # A second layout copy may have appeared or changed during the search.
    resolve_design_document(root)
    # Re-read all inputs immediately before publication, including rules and code.
    if any(path.read_bytes() != content[name] for name, path in resolved.items()):
        raise SplitError("input changed during search; publication aborted")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    lock = output.parent / f".{output.name}.publish-lock"
    lock_owned = False
    try:
        for name, data in payloads.items():
            with (temporary / name).open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        lock_owned = True
        if output.exists() or output.is_symlink():
            raise SplitError(f"output appeared during search: {output}")
        # Staging can take time: check again while holding the publication lock,
        # immediately before making the directory visible. This lock coordinates
        # publishers; external input writers must still keep inputs immutable.
        resolve_design_document(root)
        if any(path.read_bytes() != content[name] for name, path in resolved.items()):
            raise SplitError("input changed while staging; publication aborted")
        # Under the exclusive sibling lock, the directory appears all at once.
        _publish_new_directory(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if lock_owned:
            lock.unlink()
    return {**manifest, "manifest_sha256": sha256(payloads["manifest.json"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--test-split", required=True, type=Path)
    parser.add_argument("--groups", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--old-splits-dir", type=Path,
                        help="explicit directory containing six prior train/val lists")
    args = parser.parse_args(argv)
    try:
        result = generate(args.labels, args.test_split, args.groups, args.output_dir, args.old_splits_dir)
    except (SplitError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "generated", "manifest_sha256": result["manifest_sha256"],
                      "warnings": result["warnings"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
