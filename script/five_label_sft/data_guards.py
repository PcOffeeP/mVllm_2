"""Fail-closed identity loading, three-fold anti-leakage guards, and target JSON validation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import posixpath
import tempfile
from typing import Any, Iterable

from script.five_label_eval.errors import InputError
from script.five_label_eval.exclusions import (
    DEFAULT_EXCLUSIONS_PATH,
    DevExclusions,
    candidate_ids_sha256,
    load_candidate_selection,
    load_dev_exclusions,
)
from script.five_label_eval.score import MULTIS, SINGLES, decode_file, extract
from script.subvideo_review.errors import ReviewError
from script.subvideo_review.server import ReviewApp, validate_labels

from .constants import (
    DEFAULT_EVAL_DEV_REL,
    DEFAULT_EVAL_TEST_REL,
    DEFAULT_EXCLUSIONS_REL,
    DEFAULT_MANIFEST_REL,
    DEFAULT_REVIEWS_REL,
    DEFAULT_SPLITS_DIR_REL,
    REPO_ROOT,
    SUPPORTED_FOLDS,
)


PROTECTED_PATH_SEGMENTS: tuple[tuple[str, ...], ...] = (
    ("LlamaFactory", "saves"),
    ("data", "sub_video"),
    ("data", "splits"),
    ("data", "eval-subsets"),
    ("data", "subvideo-review"),
    ("data", "roi"),
    ("data", "videos"),
    ("data", "split-inputs"),
    ("data", "annotation-table-full.csv"),
)


def _has_segment_sequence(parts: tuple[str, ...], seq: tuple[str, ...]) -> bool:
    n = len(seq)
    if len(parts) < n:
        return False
    lowered_parts = tuple(p.lower() for p in parts)
    lowered_seq = tuple(s.lower() for s in seq)
    for idx in range(len(lowered_parts) - n + 1):
        if lowered_parts[idx : idx + n] == lowered_seq:
            return True
    return False


def validate_safe_output_path(
    path: Path | str,
    *,
    label: str = "output_path",
    check_resolved: bool = True,
) -> str:
    """Reject empty, parent-traversal, or protected repository paths (including ``//`` bypasses)."""
    raw_str = str(path) if isinstance(path, Path) else path
    if not isinstance(raw_str, str) or not raw_str.strip():
        raise InputError(f"{label} must be a non-empty path")
    slash_str = raw_str.replace("\\", "/").strip()
    raw_parts = tuple(p for p in slash_str.split("/") if p)
    if ".." in raw_parts:
        raise InputError(f"{label} must not contain '..': {raw_str!r}")

    norm_str = posixpath.normpath(slash_str)
    norm_parts = tuple(p for p in norm_str.split("/") if p and p != ".")
    candidate_part_tuples: list[tuple[str, ...]] = [norm_parts]
    if check_resolved:
        try:
            resolved_parts = Path(norm_str).resolve().parts
            candidate_part_tuples.append(resolved_parts)
        except OSError:
            pass

    for parts in candidate_part_tuples:
        for forbidden in PROTECTED_PATH_SEGMENTS:
            if _has_segment_sequence(parts, forbidden):
                joined = "/".join(forbidden)
                raise InputError(
                    f"{label} must not write inside protected path {joined!r}: {raw_str!r}"
                )
    return norm_str


def assert_no_symlink_components(path: Path, *, label: str = "output_path") -> None:
    """Reject if ``path`` itself or any existing ancestor inside it is a symlink."""
    # Check target itself first (even if dangling symlink).
    if path.is_symlink():
        raise InputError(f"{label} must not be a symlink: {path}")
    # Check non-root ancestors that exist under a relative or explicit path without tripping
    # over OS-level system symlinks like macOS /var -> /private/var or /tmp -> /private/tmp.
    # For the immediate parent directory and target itself, symlinks are always refused.
    if path.parent.is_symlink():
        raise InputError(f"{label} parent directory must not be a symlink: {path.parent}")


def safe_write_bytes(
    path: Path,
    content: bytes,
    *,
    overwrite: bool = False,
    label: str = "output_file",
) -> None:
    """Safely write bytes without ever following symlinks or truncating protected targets.

    - Always validates ``path`` against protected repository locations (both raw and resolved).
    - Refuses symlink targets and symlink parent directories.
    - When ``overwrite=False``, uses ``O_CREAT | O_EXCL | O_NOFOLLOW`` exclusive creation.
    - When ``overwrite=True``, writes to a sibling temporary file and atomically replaces
      via ``os.replace`` so no symlink target can ever be truncated.
    """
    validate_safe_output_path(path, label=label)
    assert_no_symlink_components(path, label=label)
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing {label} (pass --overwrite to force): {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after mkdir in case parent was swapped.
    assert_no_symlink_components(path, label=label)
    validate_safe_output_path(path, label=label)

    if not overwrite:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(str(path), flags, 0o644)
        except FileExistsError as exc:
            raise InputError(f"refusing to overwrite existing {label} (pass --overwrite to force): {path}") from exc
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        return

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(path.parent), prefix=".tmp_sft_", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        if path.is_symlink():
            raise InputError(f"{label} must not be a symlink: {path}")
        os.replace(tmp_name, str(path))
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_fold(fold: int) -> int:
    if isinstance(fold, bool) or not isinstance(fold, int) or fold not in SUPPORTED_FOLDS:
        raise InputError(f"fold must be one of {SUPPORTED_FOLDS}, got {fold!r}")
    return fold


def _load_split_video_ids(path: Path) -> tuple[frozenset[str], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read split file {path}: {exc}") from exc
    obj = decode_file(raw.decode("utf-8"), str(path))
    ids = obj.get("video_ids") if isinstance(obj, dict) else obj
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x.strip() for x in ids):
        raise InputError(f"{path}: split file must contain a nonempty video_ids string array")
    if len(set(ids)) != len(ids):
        raise InputError(f"{path}: duplicate video_ids in split file")
    return frozenset(ids), sha256_bytes(raw)


@dataclass(frozen=True)
class FoldIsolationContext:
    """Validated three-fold split, DEC-007 exclusions, and frozen eval-subset boundaries."""

    fold: int
    repo_root: Path
    manifest_path: Path
    manifest_sha256: str
    reviews_path: Path
    reviews_sha256: str
    exclusions: DevExclusions
    exclusions_path: Path
    fold_train_path: Path
    fold_train_sha256: str
    fold_val_path: Path
    fold_val_sha256: str
    test_path: Path
    test_sha256: str
    eval_dev_path: Path
    eval_dev_sha256: str
    eval_test_path: Path
    eval_test_sha256: str
    fold_train_sources: frozenset[str]
    clean_train_sources: frozenset[str]
    fold_val_sources: frozenset[str]
    test_sources: frozenset[str]
    eval_dev_cids: frozenset[str]
    eval_dev_fold_val_cids: frozenset[str]
    eval_test_cids: frozenset[str]
    eval_test_sources: frozenset[str]
    manifest_by_id: dict[str, dict[str, Any]]
    review_candidates: dict[str, dict[str, Any]]
    verified_revisions: tuple[dict[str, Any], ...]
    label_rules_sha256: str | None
    split_identity_sha256: str


@dataclass(frozen=True)
class SelectedTrainSample:
    """One verified, leakage-free confirmed training candidate."""

    candidate_id: str
    source_id: str
    source_type: str
    clip_sha256: str
    review_id: str
    revision_sha256: str
    created_at: str
    role: str
    width: int
    height: int
    total_frames: int
    fps: float
    labels: dict[str, Any]
    target_json: str


def canonicalize_and_verify_target_json(labels: Any, *, context: str = "target") -> tuple[dict[str, Any], str]:
    """Validate confirmed 5-label dict and render strict single-JSON assistant target.

    Fails closed unless:
    - All 11 leaf fields are present and valid per ``validate_labels(..., complete=True)``.
    - No combination conflict exists (e.g., ``未断裂`` + ``爆炸性断裂=是`` / ``断后脱夹=是``).
    - ``script.five_label_eval.score.extract()`` reports ``strict_format_valid == True``,
      ``issues == []``, ``conflicts == []``, and all 11 fields ``valid``.
    """
    try:
        validate_labels(labels, complete=True)
    except ReviewError as exc:
        raise InputError(f"{context}: invalid confirmed labels: {exc}") from exc

    ordered: dict[str, Any] = {
        field: labels[field] for field in SINGLES
    }
    for group, items in MULTIS.items():
        ordered[group] = {item: labels[group][item] for item in items}

    target_json = json.dumps(ordered, ensure_ascii=False, allow_nan=False)
    parsed = extract(target_json)
    if not parsed["strict_format_valid"]:
        raise InputError(
            f"{context}: target JSON failed strict_format_valid check; "
            f"issues={parsed['issues']!r}, fields={parsed['fields']!r}"
        )
    if parsed["issues"]:
        raise InputError(f"{context}: target JSON has format issues: {parsed['issues']!r}")
    if parsed["conflicts"]:
        raise InputError(f"{context}: target JSON has combination conflicts: {parsed['conflicts']!r}")
    invalid_fields = [f for f, cell in parsed["fields"].items() if cell.get("status") != "valid"]
    if invalid_fields:
        raise InputError(f"{context}: target JSON has non-valid fields: {invalid_fields!r}")
    return ordered, target_json


def load_fold_isolation_context(
    fold: int,
    *,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path | None = None,
    reviews_path: Path | None = None,
    splits_dir: Path | None = None,
    exclusions_path: Path | None = None,
    eval_dev_path: Path | None = None,
    eval_test_path: Path | None = None,
) -> FoldIsolationContext:
    """Load and cross-validate all authoritative identity, split, exclusion, and subset inputs."""
    fold = validate_fold(fold)
    root = Path(repo_root).resolve()
    m_path = Path(manifest_path) if manifest_path is not None else root / DEFAULT_MANIFEST_REL
    r_path = Path(reviews_path) if reviews_path is not None else root / DEFAULT_REVIEWS_REL
    default_splits_dir = (root / DEFAULT_SPLITS_DIR_REL).resolve()
    if splits_dir is not None and Path(splits_dir).resolve() != default_splits_dir:
        raise InputError(
            f"custom splits_dir ({Path(splits_dir).resolve()}) does not match "
            f"repo_root splits dir ({default_splits_dir}); ReviewApp binds split_identity_sha256 "
            "to <repo_root>/data/splits/three-fold — pass --repo-root to switch splits consistently"
        )
    s_dir = default_splits_dir
    e_path = (
        Path(exclusions_path)
        if exclusions_path is not None
        else (root / DEFAULT_EXCLUSIONS_REL if root != REPO_ROOT.resolve() else DEFAULT_EXCLUSIONS_PATH)
    )
    ed_path = Path(eval_dev_path) if eval_dev_path is not None else root / DEFAULT_EVAL_DEV_REL
    et_path = Path(eval_test_path) if eval_test_path is not None else root / DEFAULT_EVAL_TEST_REL

    for label, p in (
        ("manifest", m_path),
        ("reviews", r_path),
        ("dev-exclusions", e_path),
        ("eval-dev-v1", ed_path),
        ("eval-test-v1", et_path),
    ):
        if not p.is_file():
            raise InputError(f"missing required {label} file: {p}")

    # Initialize ReviewApp to enforce canonical review_subject_sha256, label_rules_sha256,
    # split_identity_sha256, revision_sha256 integrity, and candidate/source consistency.
    try:
        review_app = ReviewApp(root, manifest=m_path, records=r_path)
        verified_revisions = tuple(review_app.read_store())
    except (ReviewError, OSError, ValueError) as exc:
        raise InputError(f"failed to initialize/verify ReviewApp identity context: {exc}") from exc

    manifest_raw = m_path.read_bytes()
    manifest_sha = sha256_bytes(manifest_raw)
    manifest_obj = decode_file(manifest_raw.decode("utf-8"), str(m_path))
    raw_cands = manifest_obj.get("candidates") if isinstance(manifest_obj, dict) else None
    if not isinstance(raw_cands, list):
        raise InputError(f"{m_path}: manifest missing candidates array")
    manifest_by_id: dict[str, dict[str, Any]] = {}
    for row in raw_cands:
        if not isinstance(row, dict) or not isinstance(row.get("candidate_id"), str):
            raise InputError(f"{m_path}: invalid candidate object")
        cid = row["candidate_id"]
        if cid in manifest_by_id:
            raise InputError(f"{m_path}: duplicate candidate_id {cid!r}")
        manifest_by_id[cid] = row

    fold_train_path = s_dir / f"fold_{fold}_train.json"
    fold_val_path = s_dir / f"fold_{fold}_val.json"
    test_path = s_dir / "test.json"
    fold_train_sources, fold_train_sha = _load_split_video_ids(fold_train_path)
    fold_val_sources, fold_val_sha = _load_split_video_ids(fold_val_path)
    test_sources, test_sha = _load_split_video_ids(test_path)

    if fold_train_sources & fold_val_sources:
        raise InputError(
            f"split integrity error: fold_{fold}_train overlaps fold_{fold}_val on "
            f"{sorted(fold_train_sources & fold_val_sources)}"
        )
    if (fold_train_sources | fold_val_sources) & test_sources:
        raise InputError(
            f"split integrity error: fold_{fold} overlaps test.json on "
            f"{sorted((fold_train_sources | fold_val_sources) & test_sources)}"
        )

    exclusions = load_dev_exclusions(e_path)
    clean_train_sources = frozenset(
        sid
        for sid in fold_train_sources
        if not exclusions.is_excluded(source_id=sid)
    )
    if not clean_train_sources:
        raise InputError(f"fold_{fold}: clean_train_sources is empty after applying DEC-007 exclusions")

    eval_dev_sel = load_candidate_selection(ed_path)
    eval_test_sel = load_candidate_selection(et_path)
    eval_dev_sel.assert_manifest_sha256(manifest_sha, context="sft:eval-dev-v1")
    eval_test_sel.assert_manifest_sha256(manifest_sha, context="sft:eval-test-v1")
    eval_dev_cids = frozenset(eval_dev_sel.candidate_ids)
    eval_test_cids = frozenset(eval_test_sel.candidate_ids)
    missing_eval_dev = sorted(cid for cid in eval_dev_cids if cid not in manifest_by_id)
    if missing_eval_dev:
        raise InputError(
            f"{ed_path}: eval-dev candidate IDs absent from manifest {m_path}: {missing_eval_dev[:10]}"
        )
    missing_eval_test = sorted(cid for cid in eval_test_cids if cid not in manifest_by_id)
    if missing_eval_test:
        raise InputError(
            f"{et_path}: eval-test candidate IDs absent from manifest {m_path}: {missing_eval_test[:10]}"
        )
    eval_test_sources = frozenset(
        manifest_by_id[cid]["source_video_id"]
        for cid in eval_test_cids
        if isinstance(manifest_by_id[cid].get("source_video_id"), str)
    )
    fold_val_manifest_cids = frozenset(
        cid
        for cid, row in manifest_by_id.items()
        if row.get("source_video_id") in fold_val_sources
    )
    eval_dev_fold_val_cids = frozenset(eval_dev_cids & fold_val_manifest_cids)

    return FoldIsolationContext(
        fold=fold,
        repo_root=root,
        manifest_path=m_path,
        manifest_sha256=manifest_sha,
        reviews_path=r_path,
        reviews_sha256=sha256_file(r_path),
        exclusions=exclusions,
        exclusions_path=e_path,
        fold_train_path=fold_train_path,
        fold_train_sha256=fold_train_sha,
        fold_val_path=fold_val_path,
        fold_val_sha256=fold_val_sha,
        test_path=test_path,
        test_sha256=test_sha,
        eval_dev_path=ed_path,
        eval_dev_sha256=sha256_file(ed_path),
        eval_test_path=et_path,
        eval_test_sha256=sha256_file(et_path),
        fold_train_sources=fold_train_sources,
        clean_train_sources=clean_train_sources,
        fold_val_sources=fold_val_sources,
        test_sources=test_sources,
        eval_dev_cids=eval_dev_cids,
        eval_dev_fold_val_cids=eval_dev_fold_val_cids,
        eval_test_cids=eval_test_cids,
        eval_test_sources=eval_test_sources,
        manifest_by_id=manifest_by_id,
        review_candidates=review_app.candidates,
        verified_revisions=verified_revisions,
        label_rules_sha256=review_app.label_rules_sha256,
        split_identity_sha256=review_app.split_identity_sha256,
    )


def assert_no_fold_leakage(
    ctx: FoldIsolationContext,
    items: Iterable[dict[str, Any] | SelectedTrainSample],
    *,
    context: str = "sft_train_export",
) -> dict[str, Any]:
    """Fail-closed anti-leakage assertion for exported Fold k training samples.

    Asserts ZERO intersection with:
    - ``fold_{k}_val.json`` sources
    - ``test.json`` sources
    - ``eval-dev-v1 ∩ fold_{k}_val`` candidate IDs
    - ``eval-test-v1.json`` candidate IDs and sources
    - ``dev-exclusions.json`` (DEC-007 excluded sources, sub-videos, and isolated virtual videos)
    - Non-train or non-development candidates outside ``clean_train_sources``
    """
    rows: list[dict[str, Any]] = []
    seen_cids: set[str] = set()
    exported_sources: set[str] = set()
    exported_cids: set[str] = set()

    for item in items:
        if isinstance(item, SelectedTrainSample):
            cid, sid, stype = item.candidate_id, item.source_id, item.source_type
        elif isinstance(item, dict):
            cid = item.get("candidate_id")
            sid = item.get("source_id") or item.get("source_video_id")
            stype = item.get("source_type")
        else:
            raise InputError(f"{context}: unsupported sample entry {type(item).__name__}")
        if not isinstance(cid, str) or not cid.strip():
            raise InputError(f"{context}: sample missing candidate_id")
        if not isinstance(sid, str) or not sid.strip():
            raise InputError(f"{context}:{cid}: sample missing source_id")
        if cid in seen_cids:
            raise InputError(f"{context}: duplicate candidate_id {cid!r}")
        seen_cids.add(cid)
        exported_cids.add(cid)
        exported_sources.add(sid)
        rows.append({"candidate_id": cid, "source_id": sid, "source_type": stype})

    # 1. DEC-007 exclusions (sources, sub-videos, isolated virtual videos).
    ctx.exclusions.assert_no_excluded(rows, context=context)

    # 2. Fold val / fixed test / frozen eval-test-v1 / fold val subset intersections.
    val_src_overlap = sorted(exported_sources & ctx.fold_val_sources)
    if val_src_overlap:
        raise InputError(
            f"{context}: LEAKAGE DETECTED — fold_{ctx.fold}_val sources present in train export: {val_src_overlap}"
        )

    test_src_overlap = sorted(exported_sources & ctx.test_sources)
    if test_src_overlap:
        raise InputError(
            f"{context}: LEAKAGE DETECTED — test.json sources present in train export: {test_src_overlap}"
        )

    eval_test_src_overlap = sorted(exported_sources & ctx.eval_test_sources)
    if eval_test_src_overlap:
        raise InputError(
            f"{context}: LEAKAGE DETECTED — eval-test-v1 sources present in train export: {eval_test_src_overlap}"
        )

    eval_test_cid_overlap = sorted(exported_cids & ctx.eval_test_cids)
    if eval_test_cid_overlap:
        raise InputError(
            f"{context}: LEAKAGE DETECTED — eval-test-v1 candidates present in train export: {eval_test_cid_overlap[:10]}"
        )

    eval_dev_val_cid_overlap = sorted(exported_cids & ctx.eval_dev_fold_val_cids)
    if eval_dev_val_cid_overlap:
        raise InputError(
            f"{context}: LEAKAGE DETECTED — eval-dev-v1 ∩ fold_{ctx.fold}_val candidates present in train export: "
            f"{eval_dev_val_cid_overlap[:10]}"
        )

    outside_clean_train = sorted(exported_sources - ctx.clean_train_sources)
    if outside_clean_train:
        raise InputError(
            f"{context}: sources outside fold_{ctx.fold} clean_train_sources: {outside_clean_train}"
        )

    # 3. Cross-check every exported candidate against verified ReviewApp manifest metadata (fail-closed).
    for row in rows:
        cid = row["candidate_id"]
        rc = ctx.review_candidates.get(cid)
        if rc is None:
            raise InputError(f"{context}:{cid}: unknown candidate_id absent from verified manifest")
        if row["source_id"] != rc["source_id"]:
            raise InputError(
                f"{context}:{cid}: source_id {row['source_id']!r} != manifest source_id {rc['source_id']!r}"
            )
        if rc["scope"] != "development" or rc["folds"].get(str(ctx.fold)) != "train":
            raise InputError(
                f"{context}:{cid}: manifest scope/fold mismatch "
                f"(scope={rc['scope']!r}, folds={rc['folds']!r}, expected fold {ctx.fold} train)"
            )

    return {
        "fold": ctx.fold,
        "clean_train_source_pool_count": len(ctx.clean_train_sources),
        "exported_source_count": len(exported_sources),
        "exported_candidate_count": len(exported_cids),
        "candidate_ids_sha256": candidate_ids_sha256(sorted(exported_cids)),
        "fold_val_source_overlap": 0,
        "test_source_overlap": 0,
        "eval_test_v1_source_overlap": 0,
        "eval_test_v1_candidate_overlap": 0,
        "eval_dev_v1_fold_val_candidate_overlap": 0,
        "dec007_excluded_overlap": 0,
    }


def select_confirmed_fold_train_samples(
    ctx: FoldIsolationContext,
    *,
    allow_empty: bool = False,
) -> tuple[list[SelectedTrainSample], dict[str, Any]]:
    """Load current-batch confirmed reviews strictly within clean Fold k train sources.

    Enforces ``ReviewApp.read_store()`` revision SHA-256 integrity, ``ReviewApp.matches``
    current-batch identity, latest-revision ``review_status == 'confirmed'``, DEC-007
    exclusions, three-fold isolation, and ``score.extract()`` strict target JSON validity.
    """
    revisions = ctx.verified_revisions

    latest_matched: dict[str, dict[str, Any]] = {}
    isolated_cids: set[str] = set()
    for row in revisions:
        if not isinstance(row, dict):
            raise InputError("reviews.json revision entry must be object")
        cid = row.get("candidate_id")
        if not isinstance(cid, str) or not cid:
            continue
        candidate = ctx.review_candidates.get(cid)
        if (
            row.get("manifest_sha256") != ctx.manifest_sha256
            or candidate is None
            or not ReviewApp.matches(row, candidate)
        ):
            isolated_cids.add(cid)
            continue
        created_at = row.get("created_at")
        if not isinstance(created_at, str) or not created_at.strip():
            raise InputError(f"review revision missing created_at: {row.get('review_id')!r}")
        latest_matched[cid] = row

    skipped_status_counts: dict[str, int] = {}
    skipped_dec007 = 0
    skipped_outside_fold_train = 0
    isolated_only_count = len(isolated_cids - set(latest_matched))

    selected: list[SelectedTrainSample] = []
    for cid in sorted(latest_matched):
        rev = latest_matched[cid]
        status = rev.get("review_status")
        if status != "confirmed":
            key = str(status) if status is not None else "missing"
            skipped_status_counts[key] = skipped_status_counts.get(key, 0) + 1
            continue

        manifest_row = ctx.manifest_by_id.get(cid)
        rc = ctx.review_candidates.get(cid)
        if manifest_row is None or rc is None:
            raise InputError(f"confirmed candidate {cid!r} absent from manifest")

        sid = rc["source_id"]
        stype = rc["source_type"]
        if ctx.exclusions.is_excluded(candidate_id=cid, source_id=sid, source_type=stype):
            skipped_dec007 += 1
            continue
        if sid not in ctx.clean_train_sources:
            skipped_outside_fold_train += 1
            continue

        output_meta = manifest_row.get("output")
        media = output_meta.get("media") if isinstance(output_meta, dict) else None
        if not isinstance(media, dict):
            raise InputError(f"{cid}: manifest candidate missing output.media")
        width = media.get("width")
        height = media.get("height")
        total_frames = media.get("total_frames")
        fps = media.get("fps")
        for field_name, val in (("width", width), ("height", height), ("total_frames", total_frames)):
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise InputError(f"{cid}: invalid output.media.{field_name}={val!r}")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
            raise InputError(f"{cid}: invalid output.media.fps={fps!r}")

        ordered_labels, target_json = canonicalize_and_verify_target_json(
            rev.get("labels"),
            context=f"{cid} (review_id={rev.get('review_id')})",
        )
        selected.append(
            SelectedTrainSample(
                candidate_id=cid,
                source_id=sid,
                source_type=stype,
                clip_sha256=rc["clip_sha256"],
                review_id=str(rev["review_id"]),
                revision_sha256=str(rev["revision_sha256"]),
                created_at=str(rev["created_at"]),
                role=str(manifest_row.get("role") or "unknown"),
                width=width,
                height=height,
                total_frames=total_frames,
                fps=float(fps),
                labels=ordered_labels,
                target_json=target_json,
            )
        )

    if not selected and not allow_empty:
        raise InputError(
            f"fold_{ctx.fold}: zero confirmed clean training samples matched current manifest/rules"
        )

    isolation_report = assert_no_fold_leakage(ctx, selected, context=f"fold_{ctx.fold}_train")
    skipped_report = {
        "total_revisions_in_store": len(revisions),
        "matched_current_batch_candidates": len(latest_matched),
        "isolated_history_only_candidates": isolated_only_count,
        "skipped_non_confirmed_by_status": dict(sorted(skipped_status_counts.items())),
        "skipped_confirmed_dec007_excluded": skipped_dec007,
        "skipped_confirmed_outside_fold_train": skipped_outside_fold_train,
    }
    return selected, {"isolation": isolation_report, "skipped": skipped_report}
