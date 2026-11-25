"""Build and verify frozen §5 evaluation subset files (eval-dev-v1 and eval-test-v1).

Reads ``data/sub_video/manifest.json``, ``data/subvideo-review/reviews.json``,
``data/subvideo-review/batches.json``, ``data/splits/three-fold/*.json``,
``docs/label.md``, and ``data/splits/dev-exclusions.json`` (DEC-007) to
deterministically produce and verify:

- ``data/eval-subsets/eval-dev-v1.json``: all clean confirmed dev clips (210 clips / 87 sources)
- ``data/eval-subsets/eval-test-v1.json``: all confirmed fixed test clips (314 clips / 21 sources)

Human-review validity reuses ``ReviewApp.matches`` from
``script/subvideo_review/server.py`` (checking ``review_subject_sha256``,
``label_rules_sha256``, ``split_identity_sha256``, ``clip_sha256``, ``source_id``,
and ``source_type``) so isolated historical revisions are never treated as active
confirmations.

Because ``reviews.json`` is append-only (B3 and later batches will append newer
revisions), v1 pins ``reviews_cutoff_created_at`` and ``reviews_cutoff_sha256``
plus independent immutable v1 input/member fingerprints so ``--verify`` remains
stable across later B3 appends while failing closed on any drift in v1 inputs,
label rules, splits, or membership.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from script.subvideo_review.errors import ReviewError
from script.subvideo_review.server import ReviewApp

from .exclusions import (
    DEFAULT_EXCLUSIONS_PATH,
    EVAL_SUBSET_SCHEMA,
    REPO_ROOT,
    V1_PINNED_INPUTS,
    V1_PINNED_MEMBERS,
    V1_REVIEWS_CUTOFF_CREATED_AT,
    DevExclusions,
    candidate_ids_sha256,
    load_dev_exclusions,
)
from .frames import SIZE_BUCKET_SOURCE, size_bucket
from .score import InputError, decode_file

FROZEN_DATE = "2026-11-25"
V1_PINNED_REVIEWS_PATH = "data/subvideo-review/reviews.json"
WIDTH_BUCKETS = ("w_le_200", "w_200_400", "w_gt_400")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_ids_sha256(cids: list[str]) -> str:
    return candidate_ids_sha256(cids)


def _rel_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _latest_confirmed_for_manifest(
    reviews_obj: dict[str, Any],
    manifest_sha256: str,
    *,
    review_candidates: dict[str, dict[str, Any]],
    cutoff_created_at: str | None = None,
) -> tuple[dict[str, dict[str, Any]], str, str]:
    """Return ``(confirmed_by_cid, effective_cutoff_created_at, cutoff_slice_sha256)``.

    Only revisions matching ``ReviewApp.matches(row, review_candidates[cid])``
    (which checks ``review_subject_sha256``, ``clip_sha256``, ``source_id``,
    ``source_type``) and ``manifest_sha256`` at or before ``cutoff_created_at``
    are accepted as current confirmations.
    """
    revisions = reviews_obj.get("revisions")
    if not isinstance(revisions, list):
        raise InputError("reviews.json must contain revisions array")
    eligible_rows: list[dict[str, Any]] = []
    latest: dict[str, dict[str, Any]] = {}
    max_created_at = ""
    for row in revisions:
        if not isinstance(row, dict):
            continue
        if row.get("manifest_sha256") != manifest_sha256:
            continue
        cid = row.get("candidate_id")
        if not isinstance(cid, str) or not cid:
            continue
        candidate = review_candidates.get(cid)
        if candidate is None or not ReviewApp.matches(row, candidate):
            continue
        created_at = row.get("created_at")
        if not isinstance(created_at, str) or not created_at.strip():
            raise InputError(f"review revision missing created_at: {row.get('review_id')!r}")
        if cutoff_created_at is not None and created_at > cutoff_created_at:
            continue
        eligible_rows.append(row)
        if created_at > max_created_at:
            max_created_at = created_at
        latest[cid] = row
    effective_cutoff = cutoff_created_at if cutoff_created_at is not None else max_created_at
    slice_bytes = json.dumps(eligible_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    slice_sha = hashlib.sha256(slice_bytes).hexdigest()
    confirmed = {
        cid: row
        for cid, row in latest.items()
        if row.get("review_status") == "confirmed"
    }
    return confirmed, effective_cutoff, slice_sha


def _summarize_subset(
    cids: list[str],
    by_id: dict[str, dict[str, Any]],
    *,
    fold_val_sources: dict[int, set[str]] | None,
    batch_composition: dict[str, int],
) -> dict[str, Any]:
    sources = sorted({by_id[cid]["source_video_id"] for cid in cids})
    wb_clips: Counter[str] = Counter()
    wb_sources: dict[str, set[str]] = defaultdict(set)
    role_counts: Counter[str] = Counter()
    fold_clips: Counter[int] = Counter()
    fold_sources: dict[int, set[str]] = defaultdict(set)

    for cid in cids:
        cand = by_id[cid]
        src = cand["source_video_id"]
        width = cand["output"]["media"]["width"]
        wb = size_bucket(width)
        wb_clips[wb] += 1
        wb_sources[wb].add(src)
        role_counts[cand["role"]] += 1
        if fold_val_sources is not None:
            for fold_idx, fold_set in fold_val_sources.items():
                if src in fold_set:
                    fold_clips[fold_idx] += 1
                    fold_sources[fold_idx].add(src)

    summary: dict[str, Any] = {
        "candidate_count": len(cids),
        "source_count": len(sources),
        "batch_composition": batch_composition,
        "size_bucket_source": SIZE_BUCKET_SOURCE,
        "size_buckets": {
            wb: {"candidates": wb_clips[wb], "sources": len(wb_sources[wb])}
            for wb in WIDTH_BUCKETS
        },
        "roles": dict(sorted(role_counts.items())),
    }
    if fold_val_sources is not None:
        summary["folds"] = {
            str(k): {"candidates": fold_clips[k], "sources": len(fold_sources[k])}
            for k in sorted(fold_val_sources)
        }
    else:
        summary["folds"] = None
    return summary


def _assert_v1_pins(eval_dev: dict[str, Any], eval_test: dict[str, Any]) -> None:
    """Enforce immutable v1 input fingerprints and membership pins fail-closed."""
    for subset in (eval_dev, eval_test):
        sid = subset["subset_id"]
        inputs = subset["inputs"]
        for key, expected_val in V1_PINNED_INPUTS.items():
            actual_val = inputs.get(key)
            if actual_val != expected_val:
                raise InputError(
                    f"{sid}: pinned v1 input {key} mismatch (expected {expected_val!r}, got {actual_val!r}); "
                    "v1 is immutable — upstream data or rule changes require a new subset version"
                )
        member_pin = V1_PINNED_MEMBERS[sid]
        cids = subset["candidate_ids"]
        sources = subset["source_ids"]
        if len(cids) != member_pin["candidate_count"] or len(sources) != member_pin["source_count"]:
            raise InputError(
                f"{sid}: pinned v1 counts mismatch (expected {member_pin['candidate_count']}/{member_pin['source_count']}, "
                f"got {len(cids)}/{len(sources)})"
            )
        actual_member_sha = _candidate_ids_sha256(cids)
        if actual_member_sha != member_pin["candidate_ids_sha256"]:
            raise InputError(
                f"{sid}: pinned v1 member fingerprint mismatch "
                f"(expected {member_pin['candidate_ids_sha256']}, got {actual_member_sha})"
            )


def build_frozen_subsets(
    *,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path | None = None,
    reviews_path: Path | None = None,
    batches_path: Path | None = None,
    splits_dir: Path | None = None,
    exclusions_path: Path | None = None,
    frozen_date: str = FROZEN_DATE,
    reviews_cutoff_created_at: str | None = V1_REVIEWS_CUTOFF_CREATED_AT,
    pinned_reviews_file_sha256: str | None = None,
    pinned_reviews_path: str | None = None,
    enforce_v1_pins: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build ``(eval_dev_v1, eval_test_v1)`` deterministically with DEC-007 and ReviewApp identity enforced."""
    m_path = manifest_path or repo_root / "data/sub_video/manifest.json"
    r_path = reviews_path or repo_root / "data/subvideo-review/reviews.json"
    b_path = batches_path or repo_root / "data/subvideo-review/batches.json"
    s_dir = splits_dir or repo_root / "data/splits/three-fold"
    e_path = exclusions_path or (repo_root / "data/splits/dev-exclusions.json" if repo_root != REPO_ROOT else DEFAULT_EXCLUSIONS_PATH)

    manifest_sha = _sha256_file(m_path)
    reviews_sha = pinned_reviews_file_sha256 if pinned_reviews_file_sha256 is not None else _sha256_file(r_path)
    batches_sha = _sha256_file(b_path)
    splits_manifest_path = s_dir / "manifest.json"
    splits_manifest_sha = _sha256_file(splits_manifest_path)

    try:
        review_app = ReviewApp(repo_root, manifest=m_path, records=r_path)
    except (ReviewError, OSError, ValueError) as exc:
        raise InputError(f"failed to initialize ReviewApp identity context: {exc}") from exc

    manifest_obj = decode_file(m_path.read_text(encoding="utf-8"), str(m_path))
    reviews_obj = decode_file(r_path.read_text(encoding="utf-8"), str(r_path))
    batches_obj = decode_file(b_path.read_text(encoding="utf-8"), str(b_path))
    exclusions: DevExclusions = load_dev_exclusions(e_path)

    by_id: dict[str, dict[str, Any]] = {}
    for row in manifest_obj.get("candidates", []):
        by_id[row["candidate_id"]] = row

    test_sources = set(decode_file((s_dir / "test.json").read_text(encoding="utf-8"), str(s_dir / "test.json"))["video_ids"])
    fold_val_sources: dict[int, set[str]] = {}
    for k in (0, 1, 2):
        fold_val_sources[k] = set(
            decode_file((s_dir / f"fold_{k}_val.json").read_text(encoding="utf-8"), str(s_dir / f"fold_{k}_val.json"))["video_ids"]
        )

    confirmed, effective_cutoff, cutoff_sha = _latest_confirmed_for_manifest(
        reviews_obj,
        manifest_sha,
        review_candidates=review_app.candidates,
        cutoff_created_at=reviews_cutoff_created_at,
    )
    unknown = sorted(cid for cid in confirmed if cid not in by_id)
    if unknown:
        raise InputError(f"confirmed candidate IDs missing from manifest: {unknown}")

    dev_confirmed_raw = sorted(
        cid for cid in confirmed if by_id[cid]["source_video_id"] not in test_sources
    )
    test_confirmed = sorted(
        cid for cid in confirmed if by_id[cid]["source_video_id"] in test_sources
    )

    # Enforce DEC-007 on dev pool and verify zero overlap with test pool.
    dev_clean_rows, dev_excluded_rows = exclusions.filter_candidates(
        [by_id[cid] for cid in dev_confirmed_raw]
    )
    dev_clean_ids = sorted(row["candidate_id"] for row in dev_clean_rows)
    dev_excluded_ids = sorted(row["candidate_id"] for row in dev_excluded_rows)

    if not dev_clean_ids or not test_confirmed:
        raise InputError(
            f"cannot freeze empty eval subset (eval-dev-v1={len(dev_clean_ids)}, eval-test-v1={len(test_confirmed)}); "
            "check manifest, label rules, splits, and review_subject_sha256 identity"
        )

    exclusions.assert_no_excluded([by_id[cid] for cid in dev_clean_ids], context="eval-dev-v1")
    exclusions.assert_no_excluded([by_id[cid] for cid in test_confirmed], context="eval-test-v1")

    batch_by_id = {b["batch_id"]: b for b in batches_obj.get("batches", [])}
    b0_ids = set(batch_by_id["B0"]["selection"]["ids"])
    b2_ids = set(batch_by_id["B2"]["selection"]["ids"])
    dev_clean_set = set(dev_clean_ids)
    dev_batch_comp = {
        "B0": len(dev_clean_set & b0_ids),
        "B2_clean": len(dev_clean_set & b2_ids),
        "trial_outside_batch": len(dev_clean_set - b0_ids - b2_ids),
    }

    inputs_common = {
        "manifest_path": _rel_path(m_path, repo_root),
        "manifest_sha256": manifest_sha,
        "reviews_path": pinned_reviews_path if pinned_reviews_path is not None else _rel_path(r_path, repo_root),
        "reviews_sha256": reviews_sha,
        "reviews_cutoff_created_at": effective_cutoff,
        "reviews_cutoff_sha256": cutoff_sha,
        "dev_exclusions_path": _rel_path(e_path, repo_root),
        "dev_exclusions_sha256": exclusions.sha256,
        "splits_manifest_path": _rel_path(splits_manifest_path, repo_root),
        "splits_manifest_sha256": splits_manifest_sha,
        "split_identity_sha256": review_app.split_identity_sha256,
        "label_rules_sha256": review_app.label_rules_sha256,
        "batches_path": _rel_path(b_path, repo_root),
        "batches_sha256": batches_sha,
    }

    eval_dev_v1 = {
        "schema": EVAL_SUBSET_SCHEMA,
        "subset_id": "eval-dev-v1",
        "frozen_date": frozen_date,
        "split": "dev_all_clean",
        "source_type": "real",
        "purpose_boundary": {
            "allowed_uses": [
                "base_model_dev_evaluation",
                "prompt_iteration",
                "hyperparameter_and_error_analysis",
                "three_fold_dev_diagnostics",
            ],
            "forbidden_uses": [
                "final_sealed_test_reporting",
                "mixing_with_eval_test_v1",
                "including_dec007_excluded_sources",
            ],
            "note": (
                "Frozen clean development evaluation subset (dev_all_clean: B0 + trial + clean B2) "
                "with DEC-007 near-duplicate sources video_0006 and video_0079 strictly excluded. "
                "Immutable once frozen; any change requires a new subset version and run_id."
            ),
        },
        "inputs": inputs_common,
        "exclusions_applied": {
            "decision_id": exclusions.decision_id,
            "excluded_source_ids": sorted(exclusions.excluded_source_ids),
            "excluded_confirmed_candidate_ids": dev_excluded_ids,
        },
        "summary": _summarize_subset(
            dev_clean_ids,
            by_id,
            fold_val_sources=fold_val_sources,
            batch_composition=dev_batch_comp,
        ),
        "source_ids": sorted({by_id[cid]["source_video_id"] for cid in dev_clean_ids}),
        "candidate_ids": dev_clean_ids,
    }

    eval_test_v1 = {
        "schema": EVAL_SUBSET_SCHEMA,
        "subset_id": "eval-test-v1",
        "frozen_date": frozen_date,
        "split": "test_B1",
        "source_type": "real",
        "purpose_boundary": {
            "allowed_uses": [
                "sealed_final_model_evaluation_only",
            ],
            "forbidden_uses": [
                "prompt_selection",
                "hyperparameter_tuning",
                "iterative_model_development",
                "training_or_validation_selection",
            ],
            "note": (
                "Sealed fixed test evaluation subset (test_B1, 314 clips / 21 sources). "
                "Strictly forbidden for prompt selection, tuning, or iterative development. "
                "Immutable once frozen; any change requires a new subset version and run_id."
            ),
        },
        "inputs": inputs_common,
        "exclusions_applied": {
            "decision_id": exclusions.decision_id,
            "excluded_source_ids": sorted(exclusions.excluded_source_ids),
            "excluded_confirmed_candidate_ids": [],
        },
        "summary": _summarize_subset(
            test_confirmed,
            by_id,
            fold_val_sources=None,
            batch_composition={"B1": len(test_confirmed)},
        ),
        "source_ids": sorted({by_id[cid]["source_video_id"] for cid in test_confirmed}),
        "candidate_ids": test_confirmed,
    }
    if enforce_v1_pins:
        _assert_v1_pins(eval_dev_v1, eval_test_v1)
    return eval_dev_v1, eval_test_v1


def verify_frozen_subsets(
    output_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path | None = None,
    reviews_path: Path | None = None,
    batches_path: Path | None = None,
    splits_dir: Path | None = None,
    exclusions_path: Path | None = None,
) -> list[tuple[Path, str, int]]:
    """Verify frozen v1 files against independent v1 pins and cutoff-bounded rebuild."""
    dev_path = output_dir / "eval-dev-v1.json"
    test_path = output_dir / "eval-test-v1.json"
    for path in (dev_path, test_path):
        if not path.is_file():
            raise InputError(f"missing frozen subset file: {path}")

    existing_dev = decode_file(dev_path.read_text(encoding="utf-8"), str(dev_path))
    existing_test = decode_file(test_path.read_text(encoding="utf-8"), str(test_path))
    if not isinstance(existing_dev, dict) or not isinstance(existing_test, dict):
        raise InputError("frozen subset must be a JSON object")
    if existing_dev.get("subset_id") != "eval-dev-v1" or existing_test.get("subset_id") != "eval-test-v1":
        raise InputError("unexpected subset_id in frozen v1 files")
    dev_inputs = existing_dev.get("inputs")
    test_inputs = existing_test.get("inputs")
    if not isinstance(dev_inputs, dict) or not isinstance(test_inputs, dict):
        raise InputError("frozen subset missing inputs object")

    # Verify the on-disk files themselves match independent v1 pins before rebuilding.
    _assert_v1_pins(existing_dev, existing_test)

    expected_dev, expected_test = build_frozen_subsets(
        repo_root=repo_root,
        manifest_path=manifest_path,
        reviews_path=reviews_path,
        batches_path=batches_path,
        splits_dir=splits_dir,
        exclusions_path=exclusions_path,
        frozen_date=FROZEN_DATE,
        reviews_cutoff_created_at=V1_REVIEWS_CUTOFF_CREATED_AT,
        pinned_reviews_file_sha256=V1_PINNED_INPUTS["reviews_sha256"],
        pinned_reviews_path=V1_PINNED_REVIEWS_PATH,
        enforce_v1_pins=True,
    )
    results: list[tuple[Path, str, int]] = []
    for path, expected in ((dev_path, expected_dev), (test_path, expected_test)):
        actual_bytes = path.read_bytes()
        expected_bytes = _serialize(expected).encode("utf-8")
        if actual_bytes != expected_bytes:
            raise InputError(f"frozen subset mismatch: {path} differs from cutoff-bounded rebuild")
        results.append((path, hashlib.sha256(actual_bytes).hexdigest(), len(expected["candidate_ids"])))
    return results


def _serialize(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "data" / "eval-subsets"),
        help="Directory for eval-dev-v1.json and eval-test-v1.json",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing frozen files match pinned v1 contract and cutoff-bounded rebuild byte-for-byte",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing frozen files (default refuses overwrite)",
    )
    args = parser.parse_args(argv)
    try:
        out_dir = Path(args.output_dir)
        if args.verify:
            for path, digest, count in verify_frozen_subsets(out_dir):
                print(f"OK {path.name}: sha256={digest} count={count}")
            return 0

        eval_dev, eval_test = build_frozen_subsets()
        targets = (
            (out_dir / "eval-dev-v1.json", eval_dev),
            (out_dir / "eval-test-v1.json", eval_test),
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        mode = "w" if args.overwrite else "x"
        for path, payload in targets:
            text = _serialize(payload)
            with path.open(mode, encoding="utf-8") as stream:
                stream.write(text)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            print(
                f"Wrote {path}: candidates={payload['summary']['candidate_count']} "
                f"sources={payload['summary']['source_count']} sha256={digest}"
            )
        return 0
    except (InputError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
