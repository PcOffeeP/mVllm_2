from __future__ import annotations

import json
from pathlib import Path

from pipeline.active_data_path_guard import scan_active_data_paths

ROOT = Path(__file__).resolve().parents[1]


def test_repository_active_data_paths_are_guarded() -> None:
    result = scan_active_data_paths(ROOT)
    assert result["status"] == "passed", result
    assert result["violations"] == []
    assert result["stale_allowlist_entries"] == []


def test_guard_reports_new_violation(tmp_path: Path) -> None:
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/new.py").write_text(
        'ROOT = "data/current"\n',
        encoding="utf-8",
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config/active_data_path_allowlist.json").write_text(
        json.dumps({"schema_version": 1, "entries": []}),
        encoding="utf-8",
    )

    result = scan_active_data_paths(tmp_path)
    assert result["status"] == "failed"
    assert result["violations"] == [
        {"path": "pipeline/new.py", "line": 1, "match": "data/current"}
    ]
