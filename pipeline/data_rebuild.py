"""State and atomic promotion primitives for isolated V4.1 rebuilds."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from pipeline.current_data import (
    DataContext,
    current_data_context,
    data_context_for_root,
)
from pipeline.source_bootstrap import canonical_bytes, sha256_file

REBUILD_SCHEMA_VERSION = "tensile-v4.1-data-rebuild/v1"
PROMOTION_SCHEMA_VERSION = "tensile-v4.1-promotion/v1"
STATES = (
    "initialized",
    "source_validated",
    "source_snapshotted",
    "roi_validated",
    "waiting_for_roi_review",
    "roi_media_ready",
    "candidate_media_ready",
    "review_validated",
    "waiting_for_candidate_review",
    "release_validated",
    "ready_to_promote",
    "promoted",
)


class DataRebuildError(RuntimeError):
    """A rebuild or promotion invariant failed."""


def atomic_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_bytes(payload)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably append one single-line JSON completion record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def has_completed_stage_record(run_root: Path, stage: str) -> bool:
    path = Path(run_root) / "control/commands.jsonl"
    if not path.is_file():
        return False
    try:
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise DataRebuildError(f"commands.jsonl 无法校验: {path}") from exc
    return any(
        isinstance(record, dict)
        and record.get("stage") == stage
        and record.get("record_status") == "completed"
        for record in records
    )


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataRebuildError(f"无法读取 {label}: {path}") from exc
    if not isinstance(value, dict):
        raise DataRebuildError(f"{label} 必须是 JSON object")
    return value


def rebuild_paths(
    project_root: Path,
    run_root: Path,
) -> tuple[DataContext, Path]:
    project_root = Path(project_root).resolve()
    run_root = Path(run_root)
    if not run_root.is_absolute():
        run_root = project_root / run_root
    run_root = run_root.resolve()
    context = data_context_for_root(project_root, run_root / "data")
    return context, run_root


def initialize_state(
    project_root: Path,
    run_root: Path,
    *,
    roi_mode: str,
    review_mode: str,
    source_identity: Mapping[str, Any],
    git_commit: str,
    runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if roi_mode not in {"reuse", "review"} or review_mode not in {
        "reuse",
        "review",
    }:
        raise DataRebuildError("roi/review mode 必须是 reuse 或 review")
    context, normalized_run_root = rebuild_paths(project_root, run_root)
    state_path = normalized_run_root / "control/rebuild.json"
    requested = {
        "schema_version": REBUILD_SCHEMA_VERSION,
        "state": "initialized",
        "run_root": str(normalized_run_root),
        "data_root": str(context.root),
        "roi_mode": roi_mode,
        "review_mode": review_mode,
        "git_commit": git_commit,
        "source_identity": dict(source_identity),
        "runtime_identity": dict(runtime_identity or {}),
        "artifacts": {},
    }
    if state_path.exists():
        existing = load_json_object(state_path, "rebuild state")
        immutable = (
            "schema_version",
            "run_root",
            "data_root",
            "roi_mode",
            "review_mode",
            "git_commit",
            "source_identity",
            "runtime_identity",
        )
        if any(existing.get(key) != requested[key] for key in immutable):
            raise DataRebuildError("既有 rebuild state 与本次输入身份不一致")
        return existing
    atomic_json(state_path, requested)
    return requested


def update_state(
    run_root: Path,
    state: Mapping[str, Any],
    next_state: str,
    *,
    artifacts: Mapping[str, Any] | None = None,
    allow_completed: bool = False,
) -> dict[str, Any]:
    if next_state not in STATES:
        raise DataRebuildError(f"非法 rebuild state: {next_state}")
    current_name = str(state.get("state"))
    if current_name not in STATES:
        raise DataRebuildError(f"既有 rebuild state 非法: {current_name}")
    if STATES.index(next_state) < STATES.index(current_name):
        if not allow_completed:
            raise DataRebuildError(f"状态不能回退: {current_name} -> {next_state}")
        next_state = current_name
    updated = dict(state)
    updated["state"] = next_state
    merged = dict(updated.get("artifacts") or {})
    if artifacts:
        merged.update(artifacts)
    updated["artifacts"] = merged
    atomic_json(Path(run_root) / "control/rebuild.json", updated)
    return updated


def tree_inventory(root: Path) -> dict[str, Any]:
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise DataRebuildError(f"晋级源必须是物理目录: {root}")
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise DataRebuildError(f"晋级目录包含 symlink: {path}")
        if path.is_dir():
            items.append({"path": relative, "type": "directory"})
            continue
        if not path.is_file():
            raise DataRebuildError(f"晋级目录包含特殊文件: {path}")
        stat = path.stat()
        if stat.st_nlink != 1:
            raise DataRebuildError(f"晋级目录包含 hardlink 文件: {path}")
        items.append(
            {
                "path": relative,
                "type": "file",
                "size_bytes": stat.st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "file_count": sum(item["type"] == "file" for item in items),
        "total_bytes": sum(
            int(item.get("size_bytes", 0)) for item in items
        ),
        "items": items,
        "tree_sha256": hashlib.sha256(canonical_bytes(items)).hexdigest(),
    }


def build_promotion_manifest(
    project_root: Path,
    run_root: Path,
    entries: Iterable[tuple[str, Path, Path]],
    *,
    release_name: str,
    source_fingerprint: Mapping[str, Any],
    git_commit: str,
) -> dict[str, Any]:
    context, normalized_run_root = rebuild_paths(project_root, run_root)
    current = current_data_context(project_root)
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for name, source, target in entries:
        if name in names:
            raise DataRebuildError(f"重复 promotion entry: {name}")
        names.add(name)
        source = Path(source).resolve()
        target = Path(target).resolve()
        try:
            source_relative = source.relative_to(context.root).as_posix()
            target_relative = target.relative_to(current.root).as_posix()
        except ValueError as exc:
            raise DataRebuildError(f"promotion 路径超出受管根: {name}") from exc
        inventory = tree_inventory(source)
        result.append(
            {
                "name": name,
                "source": source_relative,
                "target": target_relative,
                "tree_sha256": inventory["tree_sha256"],
                "file_count": inventory["file_count"],
                "total_bytes": inventory["total_bytes"],
                "is_release": name == release_name,
            }
        )
    if sum(bool(entry["is_release"]) for entry in result) != 1:
        raise DataRebuildError("promotion inventory 必须且只能包含一个 release")
    result.sort(key=lambda entry: bool(entry["is_release"]))
    manifest = {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "status": "ready",
        "run_root": str(normalized_run_root),
        "git_commit": git_commit,
        "source_fingerprint": dict(source_fingerprint),
        "entries": result,
        "journal": [],
    }
    atomic_json(normalized_run_root / "control/promotion.json", manifest)
    return manifest


def _entry_hash(path: Path) -> str:
    return str(tree_inventory(path)["tree_sha256"])


def _managed_child(root: Path, value: Any, label: str) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise DataRebuildError(f"{label} 不是安全相对路径: {value}")
    resolved = (Path(root) / relative).resolve()
    try:
        resolved.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise DataRebuildError(f"{label} 逃逸受管根: {value}") from exc
    return resolved


def _resolve_identity(value: Any) -> Any:
    return value() if callable(value) else value


def promote(
    project_root: Path,
    run_root: Path,
    *,
    expected_git_commit: str | Callable[[], str],
    current_source_fingerprint: (
        Mapping[str, Any] | Callable[[], Mapping[str, Any]]
    ),
) -> dict[str, Any]:
    rebuild, normalized_run_root = rebuild_paths(project_root, run_root)
    current = current_data_context(project_root)
    state = load_json_object(
        normalized_run_root / "control/rebuild.json",
        "rebuild state",
    )
    if state.get("state") not in {"ready_to_promote", "promoted"}:
        raise DataRebuildError("只有 ready_to_promote 才能执行 promote")
    if state.get("state") == "ready_to_promote" and not has_completed_stage_record(
        normalized_run_root,
        "ready_to_promote",
    ):
        raise DataRebuildError("ready_to_promote 缺少完成 provenance")
    manifest_path = normalized_run_root / "control/promotion.json"
    manifest = load_json_object(manifest_path, "promotion manifest")
    if manifest.get("schema_version") != PROMOTION_SCHEMA_VERSION:
        raise DataRebuildError("promotion schema_version 不匹配")
    if manifest.get("status") not in {"ready", "promoted"}:
        raise DataRebuildError("promotion status 无效")
    if manifest.get("run_root") != str(normalized_run_root):
        raise DataRebuildError("promotion run_root 身份不匹配")
    if state.get("git_commit") != manifest.get("git_commit"):
        raise DataRebuildError("rebuild state 与 promotion Git identity 不一致")
    state_source_identity = state.get("source_identity")
    if not isinstance(state_source_identity, Mapping):
        raise DataRebuildError("rebuild state source identity 无效")
    state_source_fingerprint = state_source_identity.get(
        "fingerprint",
        state_source_identity,
    )
    if state_source_fingerprint != manifest.get("source_fingerprint"):
        raise DataRebuildError(
            "rebuild state 与 promotion source fingerprint 不一致"
        )

    lock_path = current.root / ".locks/v4-1-promote.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DataRebuildError("另一个 promote 正持有互斥锁") from exc

        actual_git_commit = str(_resolve_identity(expected_git_commit))
        actual_source_fingerprint = _resolve_identity(
            current_source_fingerprint
        )
        if manifest.get("git_commit") != actual_git_commit:
            raise DataRebuildError("Git identity 已变化")
        if not isinstance(actual_source_fingerprint, Mapping):
            raise DataRebuildError("当前 source fingerprint 无效")
        if manifest.get("source_fingerprint") != dict(
            actual_source_fingerprint
        ):
            raise DataRebuildError("当前 source fingerprint 已变化")
        if rebuild.root.stat().st_dev != current.root.stat().st_dev:
            raise DataRebuildError("staging 与 workspace/data 不在同一文件系统")

        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            raise DataRebuildError("promotion entries 无效")
        if (
            sum(
                bool(entry.get("is_release"))
                for entry in entries
                if isinstance(entry, dict)
            )
            != 1
            or not isinstance(entries[-1], dict)
            or not bool(entries[-1].get("is_release"))
        ):
            raise DataRebuildError("release 必须是最后一个 promotion entry")
        entry_names = [
            str(entry.get("name"))
            for entry in entries
            if isinstance(entry, dict)
        ]
        if len(entry_names) != len(entries) or len(entry_names) != len(
            set(entry_names)
        ):
            raise DataRebuildError("promotion entry 名称无效或重复")
        raw_journal = manifest.get("journal")
        if not isinstance(raw_journal, list):
            raise DataRebuildError("promotion journal 无效")
        journal = {
            str(item.get("name")): dict(item)
            for item in raw_journal
            if isinstance(item, dict)
        }
        if len(journal) != len(raw_journal) or not set(journal).issubset(
            entry_names
        ):
            raise DataRebuildError("promotion journal 包含非法条目")

        append_jsonl(
            normalized_run_root / "control/commands.jsonl",
            {
                "schema_version": "tensile-v4.1-stage-completion/v1",
                "record_status": "intent",
                "stage": "promoted",
                "resulting_state": "promoted",
                "git_commit": actual_git_commit,
                "runtime_identity": state.get("runtime_identity"),
                "inputs": {
                    "source_fingerprint": dict(
                        actual_source_fingerprint
                    ),
                    "promotion_manifest_tree_entries": entries,
                },
                "outputs": {},
            },
        )
        for entry in entries:
            if not isinstance(entry, dict):
                raise DataRebuildError("promotion entry 必须是对象")
            name = str(entry["name"])
            source = _managed_child(
                rebuild.root,
                entry.get("source"),
                f"{name} source",
            )
            target = _managed_child(
                current.root,
                entry.get("target"),
                f"{name} target",
            )
            expected_hash = str(entry["tree_sha256"])
            if target.exists():
                if _entry_hash(target) != expected_hash:
                    raise DataRebuildError(f"晋级目标同名但内容不同: {target}")
                status = "already_present"
            else:
                if not source.exists() or _entry_hash(source) != expected_hash:
                    raise DataRebuildError(f"晋级源缺失或漂移: {source}")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(source, target)
                status = "promoted"
            journal[name] = {
                "name": name,
                "status": status,
                "target": str(entry["target"]),
                "tree_sha256": expected_hash,
            }
            manifest["journal"] = [
                journal[key] for key in sorted(journal)
            ]
            atomic_json(manifest_path, manifest)
        manifest["status"] = "promoted"
        atomic_json(manifest_path, manifest)
        promoted_state = update_state(
            normalized_run_root,
            state,
            "promoted",
        )
        append_jsonl(
            normalized_run_root / "control/commands.jsonl",
            {
                "schema_version": "tensile-v4.1-stage-completion/v1",
                "record_status": "completed",
                "stage": "promoted",
                "resulting_state": "promoted",
                "git_commit": actual_git_commit,
                "runtime_identity": promoted_state.get("runtime_identity"),
                "inputs": {
                    "source_fingerprint": dict(
                        actual_source_fingerprint
                    ),
                    "promotion_manifest_tree_entries": entries,
                },
                "outputs": {"journal": manifest["journal"]},
            },
        )
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return manifest
