"""Safe inventory and deletion planning for completed training checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


POLICY_SCHEMA = "tensile-checkpoint-policy/v1"
PLAN_SCHEMA = "tensile-checkpoint-plan/v1"
CHECKPOINT_RE = re.compile(r"checkpoint-(\d+)")


class CheckpointManagementError(RuntimeError):
    """Raised when checkpoint evidence is incomplete or has drifted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_identity(path: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total = 0
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink():
            raise CheckpointManagementError(f"checkpoint 内不允许软链接: {candidate}")
        if not candidate.is_file():
            continue
        stat = candidate.stat()
        size = stat.st_size
        total += size
        files.append(
            {
                "path": str(candidate.relative_to(path)),
                "size_bytes": size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "file_count": len(files),
        "size_bytes": total,
        "metadata_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _best_checkpoint(adapter: Path) -> str | None:
    state_path = adapter / "trainer_state.json"
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    raw = state.get("best_model_checkpoint")
    return Path(raw).name if raw else None


def _merged_path(adapter: Path) -> Path:
    merged = adapter.parent / "merged"
    if merged.is_dir():
        return merged
    raise CheckpointManagementError(f"adapter 缺少对应 merged 模型: {adapter}")


def _checkpoint_dirs(adapter: Path) -> list[Path]:
    checkpoints = [
        path
        for path in adapter.iterdir()
        if path.is_dir() and CHECKPOINT_RE.fullmatch(path.name)
    ]
    return sorted(checkpoints, key=lambda path: int(path.name.split("-")[-1]))


def _adapter_roots(root: Path) -> list[Path]:
    workspace = root / "workspace"
    roots = {
        path.parent
        for path in workspace.rglob("adapter_model.safetensors")
        if not CHECKPOINT_RE.fullmatch(path.parent.name)
    }
    return sorted(roots)


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise CheckpointManagementError("checkpoint policy schema 无效")
    return policy


def build_plan(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    current_adapter = root / policy["current_training_adapter"]
    actions: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    for adapter in _adapter_roots(root):
        checkpoints = _checkpoint_dirs(adapter)
        if not checkpoints:
            continue
        root_weight = adapter / "adapter_model.safetensors"
        if not root_weight.is_file():
            raise CheckpointManagementError(f"缺少 root adapter: {adapter}")
        merged = _merged_path(adapter)
        best_name = _best_checkpoint(adapter)
        last_name = checkpoints[-1].name
        selected_name = best_name or last_name
        selected = adapter / selected_name
        selected_weight = selected / "adapter_model.safetensors"
        if not selected_weight.is_file():
            raise CheckpointManagementError(f"selected checkpoint 权重不存在: {selected}")
        if sha256_file(root_weight) != sha256_file(selected_weight):
            raise CheckpointManagementError(
                f"root adapter 与 selected checkpoint 不一致: {adapter}"
            )
        keep_names: set[str] = set()
        if adapter.resolve() == current_adapter.resolve():
            for selector in policy["current_retention"]:
                if selector == "best" and best_name:
                    keep_names.add(best_name)
                elif selector == "last":
                    keep_names.add(last_name)
        experiment_actions = []
        for checkpoint in checkpoints:
            identity = directory_identity(checkpoint)
            decision = "keep" if checkpoint.name in keep_names else "delete"
            action = {
                "path": str(checkpoint.relative_to(root)),
                "decision": decision,
                "reason": (
                    "current_release_best_or_last"
                    if decision == "keep"
                    else "completed_experiment_root_adapter_and_merged_verified"
                ),
                **identity,
            }
            actions.append(action)
            experiment_actions.append(action)
        experiments.append(
            {
                "adapter": str(adapter.relative_to(root)),
                "merged": str(merged.relative_to(root)),
                "best_checkpoint": best_name,
                "last_checkpoint": last_name,
                "root_matches": selected_name,
                "checkpoint_count": len(checkpoints),
                "keep_count": sum(a["decision"] == "keep" for a in experiment_actions),
                "delete_count": sum(
                    a["decision"] == "delete" for a in experiment_actions
                ),
            }
        )
    delete_actions = [action for action in actions if action["decision"] == "delete"]
    keep_actions = [action for action in actions if action["decision"] == "keep"]
    return {
        "schema_version": PLAN_SCHEMA,
        "policy": policy,
        "experiments": experiments,
        "actions": actions,
        "summary": {
            "experiment_count": len(experiments),
            "checkpoint_count": len(actions),
            "keep_count": len(keep_actions),
            "delete_count": len(delete_actions),
            "keep_bytes": sum(action["size_bytes"] for action in keep_actions),
            "delete_bytes": sum(action["size_bytes"] for action in delete_actions),
        },
    }


def _assert_no_training_process() -> None:
    result = subprocess.run(
        ["ps", "-eo", "args="],
        check=True,
        capture_output=True,
        text=True,
    )
    markers = ("llamafactory-cli train", "torchrun", "run_v4_1_prompt_crossval.py")
    active = [line for line in result.stdout.splitlines() if any(x in line for x in markers)]
    if active:
        raise CheckpointManagementError("检测到训练进程，拒绝删除 checkpoint")


def apply_plan(root: Path, plan: dict[str, Any], confirmation: str) -> dict[str, Any]:
    root = root.resolve()
    summary = plan.get("summary", {})
    delete_count = int(summary.get("delete_count", -1))
    expected = f"DELETE-{delete_count}-CHECKPOINTS"
    if confirmation != expected:
        raise CheckpointManagementError(f"确认字符串无效；需要精确输入 {expected}")
    _assert_no_training_process()
    deleted = []
    for action in plan.get("actions", []):
        if action.get("decision") != "delete":
            continue
        target = Path(os.path.abspath(root / action["path"]))
        workspace = root / "workspace"
        if workspace not in target.parents:
            raise CheckpointManagementError(f"删除路径不在 workspace: {target}")
        if not CHECKPOINT_RE.fullmatch(target.name):
            raise CheckpointManagementError(f"删除目标不是 checkpoint: {target}")
        if target.is_symlink() or not target.is_dir():
            raise CheckpointManagementError(f"删除目标状态异常: {target}")
        if directory_identity(target) != {
            key: action[key]
            for key in ("file_count", "size_bytes", "metadata_sha256")
        }:
            raise CheckpointManagementError(f"checkpoint 已发生变化: {target}")
        shutil.rmtree(target)
        deleted.append(action["path"])
    return {
        "schema_version": "tensile-checkpoint-cleanup/v1",
        "deleted_count": len(deleted),
        "deleted_paths": deleted,
        "expected_reclaimed_bytes": summary["delete_bytes"],
    }
