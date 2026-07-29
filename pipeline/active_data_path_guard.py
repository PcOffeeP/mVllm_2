"""Scan supported active surfaces for forbidden legacy data roots."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FORBIDDEN = re.compile(
    r"data/current|data/01_videos|tensile-data/current|"
    r"\.compat/workspace|TENSILE_DATA_HOME|/Users/|/home/"
)
TEXT_SUFFIXES = frozenset({".py", ".sh", ".yaml", ".yml", ".json", ".md"})


class ActiveDataPathError(RuntimeError):
    """An unsupported active path or stale allowlist entry was found."""


def _candidate_files(project_root: Path) -> list[Path]:
    project_root = Path(project_root).resolve()
    candidates: set[Path] = {
        project_root / "README.md",
        project_root / "docs/DATA_PROCESSING_RUNBOOK.md",
    }
    roots = (
        project_root / "pipeline",
        project_root / "scripts",
        project_root / "finetune",
    )
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(project_root)
            if "__pycache__" in relative.parts:
                continue
            if relative.parts[:3] == ("pipeline", "scripts", "archive"):
                continue
            if relative.parts[:2] == ("scripts", "archive"):
                continue
            if relative.parts[:2] in {
                ("finetune", "archive"),
                ("finetune", "results"),
                ("finetune", "run_logs"),
                ("finetune", "experiments"),
            }:
                continue
            if relative.parts[:4] in {
                ("finetune", "MiniCPM", "config", "archive"),
                ("finetune", "MiniCPM", "config", "experiments"),
            }:
                continue
            if relative.parts[:3] == ("pipeline", "model_registry", "releases"):
                continue
            candidates.add(path)
    return sorted(path for path in candidates if path.is_file())


def _load_allowlist(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveDataPathError(f"无法读取 allowlist: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ActiveDataPathError("allowlist schema_version 必须为 1")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) for entry in entries
    ):
        raise ActiveDataPathError("allowlist entries 必须是对象列表")
    return entries


def scan_active_data_paths(
    project_root: Path,
    *,
    allowlist_path: Path | None = None,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    allowlist_path = allowlist_path or (
        project_root / "config/active_data_path_allowlist.json"
    )
    entries = _load_allowlist(allowlist_path)
    keyed: dict[tuple[str, int, str], dict[str, Any]] = {}
    for entry in entries:
        path = entry.get("path")
        line = entry.get("line")
        match = entry.get("match")
        reason = entry.get("reason")
        if (
            not isinstance(path, str)
            or type(line) is not int
            or line < 1
            or not isinstance(match, str)
            or not match
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ActiveDataPathError("allowlist entry 字段无效")
        key = (path, line, match)
        if key in keyed:
            raise ActiveDataPathError(f"allowlist entry 重复: {key}")
        keyed[key] = entry

    used: set[tuple[str, int, str]] = set()
    violations: list[dict[str, Any]] = []
    match_count = 0
    for path in _candidate_files(project_root):
        relative = path.relative_to(project_root).as_posix()
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for match in FORBIDDEN.finditer(line):
                match_count += 1
                key = (relative, line_number, match.group(0))
                if key in keyed:
                    used.add(key)
                else:
                    violations.append(
                        {
                            "path": relative,
                            "line": line_number,
                            "match": match.group(0),
                        }
                    )
    stale = [
        {"path": path, "line": line, "match": match}
        for path, line, match in sorted(set(keyed) - used)
    ]
    return {
        "status": "passed" if not violations and not stale else "failed",
        "scanned_file_count": len(_candidate_files(project_root)),
        "match_count": match_count,
        "allowlisted_count": len(used),
        "violations": violations,
        "stale_allowlist_entries": stale,
    }
