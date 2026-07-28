"""Small fail-closed primitives shared by the V4.1 continuation pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


class ManifestRuntimeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any], *, immutable: bool = False) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ManifestRuntimeError(f"refusing to overwrite immutable manifest: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestRuntimeError(f"manifest not found: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value.get("immutable"):
        raise ManifestRuntimeError(f"manifest is not immutable: {path}")
    for rel, expected in (value.get("input_sha256") or {}).items():
        target = Path(rel)
        if not target.is_absolute():
            target = path.parent / target
        if not target.is_file() or sha256_file(target) != expected:
            raise ManifestRuntimeError(f"input identity drift: {target}")
    return value


def pid_running(pid: int | None, command_fragment: str | None = None) -> bool:
    if not pid or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if command_fragment:
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        except OSError:
            return False
        return command_fragment in command
    return True


def launch_singleton(manifest_path: Path, phase: str) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    state_path = Path(manifest["state_path"])
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    if pid_running(state.get("pid"), str(manifest["run_id"])):
        raise ManifestRuntimeError("active PID already owns this run")
    completed = set(state.get("completed_phases") or [])
    if phase in completed:
        return {**state, "idempotent": True}
    commands = manifest.get("commands") or {}
    command = commands.get(phase)
    if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
        raise ManifestRuntimeError(f"phase command missing: {phase}")
    log_path = Path(manifest["log_root"]) / f"{phase}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    proc = subprocess.Popen(command, cwd=manifest["repo_root"], stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    payload = {
        "schema_version": "tensile-vlm-v4.1-pipeline-state/v1",
        "run_id": manifest["run_id"],
        "phase": phase,
        "status": "running",
        "pid": proc.pid,
        "pid_command_fragment": manifest["run_id"],
        "completed_phases": sorted(completed),
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    atomic_json(state_path, payload)
    return payload


def monitor(manifest_path: Path) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    state_path = Path(manifest["state_path"])
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    running = pid_running(state.get("pid"), state.get("pid_command_fragment"))
    step = int(state.get("global_step") or 0)
    expected = int(manifest.get("expected_global_step") or 1125)
    eval_count = int(state.get("evaluation_record_count") or 0)
    eval_expected = int(manifest.get("evaluation_expected_count") or 0)
    eta_reliable = state.get("phase") != "train" or step >= 50
    suggested = 900 if not eta_reliable else int(state.get("suggested_check_after_seconds") or 3600)
    completion = state.get("estimated_completion_at")
    if not completion and eta_reliable and running:
        completion = (datetime.now().astimezone() + timedelta(seconds=suggested)).isoformat(timespec="seconds")
    disk = os.statvfs(Path(manifest["repo_root"]))
    return {
        "status": state.get("status", "not_started"),
        "phase": state.get("phase"),
        "pid_running": running,
        "global_step": step,
        "expected_global_step": expected,
        "evaluation_record_count": eval_count,
        "evaluation_expected_count": eval_expected,
        "gpu_memory_mib": state.get("gpu_memory_mib"),
        "disk_free_bytes": disk.f_bavail * disk.f_frsize,
        "eta_reliable": eta_reliable,
        "estimated_completion_at": completion,
        "suggested_check_after_seconds": suggested,
    }
