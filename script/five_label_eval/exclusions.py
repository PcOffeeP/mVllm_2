"""DEC-007 exclusion guard and frozen eval-subset candidate-ID loader.

Loads ``data/splits/dev-exclusions.json`` (schema ``tensile-dev-exclusions/1``) and
prevents excluded dev sources (``video_0006``, ``video_0079``), their 20 derived
sub-videos, and the 15 isolated virtual videos from entering evaluation manifests,
frame extraction, inference, or scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable

from .score import InputError, decode_file

EXCLUSIONS_SCHEMA = "tensile-dev-exclusions/1"
EVAL_SUBSET_SCHEMA = "tensile-eval-subset/1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXCLUSIONS_PATH = REPO_ROOT / "data" / "splits" / "dev-exclusions.json"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class CandidateSelection:
    """Candidate IDs plus optional frozen-subset manifest digest binding."""

    candidate_ids: list[str]
    expected_manifest_sha256: str | None = None
    subset_id: str | None = None

    def assert_manifest_sha256(self, actual_manifest_sha256: str, *, context: str = "selection") -> None:
        """Fail closed when a frozen eval subset is applied to a different manifest."""
        if self.expected_manifest_sha256 is None:
            return
        if actual_manifest_sha256 != self.expected_manifest_sha256:
            label = self.subset_id or EVAL_SUBSET_SCHEMA
            raise InputError(
                f"{context}: frozen subset {label!r} requires manifest_sha256="
                f"{self.expected_manifest_sha256}, got {actual_manifest_sha256!r}"
            )


@dataclass(frozen=True)
class DevExclusions:
    """Validated DEC-007 exclusion sets loaded from ``dev-exclusions.json``."""

    path: str | None
    sha256: str | None
    decision_id: str
    excluded_source_ids: frozenset[str]
    excluded_candidate_ids: frozenset[str]
    isolated_virtual_ids: frozenset[str]

    def violation_reasons(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        source_type: str | None = None,
    ) -> list[str]:
        """Return all DEC-007 exclusion reasons matching the given item."""
        reasons: list[str] = []
        if isinstance(source_id, str) and source_id in self.excluded_source_ids:
            reasons.append(f"excluded_dev_source:{source_id}")
        if isinstance(candidate_id, str) and candidate_id in self.excluded_candidate_ids:
            reasons.append(f"excluded_subvideo_id:{candidate_id}")
        if source_type == "virtual" or source_type is None:
            if isinstance(candidate_id, str) and candidate_id in self.isolated_virtual_ids:
                reasons.append(f"isolated_virtual_video:{candidate_id}")
            if isinstance(source_id, str) and source_id in self.isolated_virtual_ids:
                reasons.append(f"isolated_virtual_video:{source_id}")
        return reasons

    def is_excluded(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        source_type: str | None = None,
    ) -> bool:
        return bool(
            self.violation_reasons(
                candidate_id=candidate_id,
                source_id=source_id,
                source_type=source_type,
            )
        )

    def find_violations(self, items: Iterable[Any]) -> list[dict[str, Any]]:
        """Inspect candidate IDs or candidate/sample dicts and return DEC-007 violations."""
        violations: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                cid, sid, stype = item, None, None
            elif isinstance(item, dict):
                cid = item.get("candidate_id")
                sid = item.get("source_id") or item.get("source_video_id")
                stype = item.get("source_type")
            else:
                continue
            reasons = self.violation_reasons(
                candidate_id=cid if isinstance(cid, str) else None,
                source_id=sid if isinstance(sid, str) else None,
                source_type=stype if isinstance(stype, str) else None,
            )
            if reasons:
                violations.append(
                    {
                        "candidate_id": cid,
                        "source_id": sid,
                        "reasons": reasons,
                    }
                )
        return violations

    def assert_no_excluded(self, items: Iterable[Any], *, context: str = "selection") -> None:
        """Raise ``InputError`` if any item violates DEC-007 exclusions."""
        violations = self.find_violations(items)
        if not violations:
            return
        preview = ", ".join(
            f"{v['candidate_id'] or v['source_id']}({';'.join(v['reasons'])})"
            for v in violations[:10]
        )
        suffix = f" ... (+{len(violations) - 10} more)" if len(violations) > 10 else ""
        source_hint = self.path or "data/splits/dev-exclusions.json"
        raise InputError(
            f"{context}: contains {len(violations)} DEC-007 excluded item(s) "
            f"[{preview}{suffix}] per {self.decision_id} ({source_hint})"
        )

    def filter_candidates(self, candidates: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Partition candidate dicts into ``(clean, excluded)`` preserving order."""
        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for row in candidates:
            if self.is_excluded(
                candidate_id=row.get("candidate_id"),
                source_id=row.get("source_id") or row.get("source_video_id"),
                source_type=row.get("source_type"),
            ):
                removed.append(row)
            else:
                kept.append(row)
        return kept, removed

    def metadata(self, *, filtered_count: int = 0) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "path": self.path,
            "sha256": self.sha256,
            "excluded_source_ids": sorted(self.excluded_source_ids),
            "filtered_count": filtered_count,
        }


def _parse_dev_exclusions_file(target: Path, *, require_nonempty: bool = False) -> DevExclusions:
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read DEC-007 dev-exclusions file {target}: {exc}") from exc
    obj = decode_file(raw.decode("utf-8"), str(target))
    if not isinstance(obj, dict):
        raise InputError(f"{target}: expected JSON object")
    if obj.get("schema") != EXCLUSIONS_SCHEMA:
        raise InputError(
            f"{target}: unexpected schema {obj.get('schema')!r}; expected {EXCLUSIONS_SCHEMA!r}"
        )
    decision_id = obj.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise InputError(f"{target}: missing decision_id")

    raw_sources = obj.get("excluded_dev_sources")
    if not isinstance(raw_sources, list):
        raise InputError(f"{target}: excluded_dev_sources must be a list")
    excluded_sources: set[str] = set()
    excluded_candidates: set[str] = set()
    for entry in raw_sources:
        if not isinstance(entry, dict):
            raise InputError(f"{target}: excluded_dev_sources entry must be object")
        sid = entry.get("source_id")
        if not isinstance(sid, str) or not sid.strip():
            raise InputError(f"{target}: excluded_dev_sources entry missing source_id")
        excluded_sources.add(sid)
        cids = entry.get("excluded_subvideo_ids")
        if not isinstance(cids, list):
            raise InputError(f"{target}: {sid}: excluded_subvideo_ids must be a list")
        for cid in cids:
            if not isinstance(cid, str) or not cid.strip():
                raise InputError(f"{target}: {sid}: invalid candidate_id in excluded_subvideo_ids")
            excluded_candidates.add(cid)

    raw_virtuals = obj.get("isolated_virtual_videos")
    if not isinstance(raw_virtuals, list):
        raise InputError(f"{target}: isolated_virtual_videos must be a list")
    isolated_virtuals: set[str] = set()
    for entry in raw_virtuals:
        if not isinstance(entry, dict):
            raise InputError(f"{target}: isolated_virtual_videos entry must be object")
        vid = entry.get("virtual_video_id")
        if not isinstance(vid, str) or not vid.strip():
            raise InputError(f"{target}: isolated_virtual_videos entry missing virtual_video_id")
        isolated_virtuals.add(vid)

    if require_nonempty and (not excluded_sources or not excluded_candidates):
        raise InputError(f"{target}: official DEC-007 exclusions file cannot be empty")

    try:
        display_path = str(target.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        display_path = str(target)

    return DevExclusions(
        path=display_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        decision_id=decision_id,
        excluded_source_ids=frozenset(excluded_sources),
        excluded_candidate_ids=frozenset(excluded_candidates),
        isolated_virtual_ids=frozenset(isolated_virtuals),
    )


def load_dev_exclusions(path: Path | str | None = None) -> DevExclusions:
    """Load and validate ``data/splits/dev-exclusions.json`` fail-closed.

    A custom ``path`` can only *extend* the official DEC-007 exclusions (union),
    never drop or weaken them; bypassing DEC-007 requires explicit ``--allow-excluded``.
    """
    official = _parse_dev_exclusions_file(DEFAULT_EXCLUSIONS_PATH, require_nonempty=True)
    if path is None:
        return official
    target = Path(path)
    if target.resolve() == DEFAULT_EXCLUSIONS_PATH.resolve():
        return official
    extra = _parse_dev_exclusions_file(target, require_nonempty=False)
    return DevExclusions(
        path=f"{official.path}+{extra.path}",
        sha256=official.sha256,
        decision_id=official.decision_id,
        excluded_source_ids=official.excluded_source_ids | extra.excluded_source_ids,
        excluded_candidate_ids=official.excluded_candidate_ids | extra.excluded_candidate_ids,
        isolated_virtual_ids=official.isolated_virtual_ids | extra.isolated_virtual_ids,
    )


def load_candidate_selection(path: Path | str) -> CandidateSelection:
    """Load candidate IDs and frozen-subset manifest digest binding."""
    target = Path(path)
    obj = decode_file(target.read_text(encoding="utf-8"), str(target))
    expected_manifest_sha256: str | None = None
    subset_id: str | None = None
    if isinstance(obj, list):
        ids = obj
    elif isinstance(obj, dict) and obj.get("schema") == EVAL_SUBSET_SCHEMA:
        ids = obj.get("candidate_ids")
        if not isinstance(ids, list):
            raise InputError(f"{target}: frozen eval subset missing candidate_ids array")
        inputs = obj.get("inputs")
        manifest_sha = inputs.get("manifest_sha256") if isinstance(inputs, dict) else None
        if not isinstance(manifest_sha, str) or not SHA256_RE.fullmatch(manifest_sha):
            raise InputError(
                f"{target}: frozen eval subset missing valid inputs.manifest_sha256"
            )
        expected_manifest_sha256 = manifest_sha
        raw_sid = obj.get("subset_id")
        subset_id = raw_sid if isinstance(raw_sid, str) and raw_sid.strip() else None
    else:
        raise InputError(
            f"{target}: candidate IDs must be a JSON array or {EVAL_SUBSET_SCHEMA!r} object"
        )
    if not ids or any(not isinstance(cid, str) or not cid.strip() for cid in ids):
        raise InputError(f"{target}: candidate IDs must be a nonempty array of strings")
    return CandidateSelection(
        candidate_ids=ids,
        expected_manifest_sha256=expected_manifest_sha256,
        subset_id=subset_id,
    )


def load_candidate_ids_input(path: Path | str) -> list[str]:
    """Load candidate IDs from either a JSON array or a frozen eval-subset JSON file."""
    return load_candidate_selection(path).candidate_ids
