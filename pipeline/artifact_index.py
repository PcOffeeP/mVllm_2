"""Immutable artifact collection index: one index.json per collection directory.

同一集合目录同一时刻只允许一个写入进程（当前调用链为顺序执行）。
append_entry 的读-改-写流程不提供并发写入互斥；并发写入会导致条目静默丢失。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INDEX_FILENAME = "index.json"
REQUIRED_FIELDS = frozenset({"id", "created_at", "step", "inputs", "stats"})


def validate_entry(entry: Any) -> dict[str, Any]:
    """Validate an index entry and return a normalized copy."""
    if not isinstance(entry, dict):
        raise TypeError("索引条目必须是对象")
    missing = sorted(REQUIRED_FIELDS - set(entry))
    if missing:
        raise ValueError(f"索引条目缺少字段: {', '.join(missing)}")
    if not isinstance(entry["id"], str) or not entry["id"]:
        raise ValueError("索引条目 id 必须是非空字符串")
    if not isinstance(entry["created_at"], str) or not entry["created_at"]:
        raise ValueError("索引条目 created_at 必须是非空字符串")
    if not isinstance(entry["step"], str) or not entry["step"]:
        raise ValueError("索引条目 step 必须是非空字符串")
    if not isinstance(entry["inputs"], dict):
        raise TypeError("索引条目 inputs 必须是对象")
    if not isinstance(entry["stats"], dict):
        raise TypeError("索引条目 stats 必须是对象")
    if "note" in entry and not isinstance(entry.get("note"), str):
        raise TypeError("索引条目 note 必须是字符串")
    return dict(entry)


def read_index(collection_dir: Path | str) -> list[dict[str, Any]]:
    """Read and validate the index for a collection directory."""
    path = Path(collection_dir) / INDEX_FILENAME
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"索引 JSON 无法解析: {path}") from exc
    if isinstance(payload, list):
        return [validate_entry(item) for item in payload]
    if isinstance(payload, dict):
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise TypeError(f"索引对象缺少 artifacts 数组: {path}")
        return [validate_entry(item) for item in artifacts]
    raise TypeError(f"索引必须是对象或数组: {path}")


def _write_index(path: Path, entries: list[dict[str, Any]]) -> None:
    payload = {"artifacts": entries}
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{INDEX_FILENAME}.",
        dir=path.parent,
        text=False,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _same_identity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a["id"] == b["id"]
        and a["step"] == b["step"]
        and a["inputs"] == b["inputs"]
        and a["stats"] == b["stats"]
        and a.get("note") == b.get("note")
    )


def append_entry(collection_dir: Path | str, entry: Any) -> bool:
    """Append a validated entry to the collection index.

    Idempotent: if the same id already exists with identical content, skip.
    Raises ValueError if the same id exists with different content.
    Returns True when a new entry was written.
    """
    validated = validate_entry(entry)
    path = Path(collection_dir) / INDEX_FILENAME
    entries = read_index(collection_dir)
    by_id = {item["id"]: item for item in entries}
    artifact_id = validated["id"]
    if artifact_id in by_id:
        existing = by_id[artifact_id]
        if _same_identity(existing, validated):
            return False
        raise ValueError(f"产物 ID 冲突: {artifact_id}")
    entries.append(validated)
    _write_index(path, entries)
    return True


def utc_now() -> str:
    """Return a timezone-aware UTC ISO 8601 timestamp."""
    return datetime.now(UTC).isoformat()
