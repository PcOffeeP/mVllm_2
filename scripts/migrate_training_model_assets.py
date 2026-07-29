#!/usr/bin/env python3
"""Migrate known training-machine model assets into the project workspace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.model_registry import (  # noqa: E402
    artifact_identity,
    load_current_model,
    parse_model_name,
)


class MigrationError(RuntimeError):
    """A model migration precondition or filesystem operation failed."""


@dataclass(frozen=True)
class ModelMove:
    model_name: str
    source_adapter: str
    source_merged: str
    target_adapter: str
    target_merged: str
    lifecycle_status: str


CURRENT_MODEL = "v4.1-agent-pipeline-fold0-r1"
CURRENT_SOURCE_PREFIX = (
    "LlamaFactory/saves/minicpmv4_5/lora/"
    "sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_"
    "2a84e8b6cfc3_seed3407"
)
CURRENT_EXPERIMENT = (
    "workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0"
)

MOVES = (
    ModelMove(
        CURRENT_MODEL,
        CURRENT_SOURCE_PREFIX,
        f"{CURRENT_SOURCE_PREFIX}_merged",
        f"{CURRENT_EXPERIMENT}/adapter",
        f"{CURRENT_EXPERIMENT}/merged",
        "current",
    ),
    ModelMove(
        "v4.1-sampling-coverage-first-fold0-r1",
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_"
            "2a84e8b6cfc3_seed3411"
        ),
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_"
            "2a84e8b6cfc3_seed3411_merged"
        ),
        (
            "workspace/runs/v4.1-phase2-coverage-first-v1-seed3411/"
            "fold0/adapter"
        ),
        (
            "workspace/runs/v4.1-phase2-coverage-first-v1-seed3411/"
            "fold0/merged"
        ),
        "evaluated",
    ),
    ModelMove(
        "v4.1-sampling-source-aware-fold0-r1",
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_source_aware_3k_dd89b70e9d63_seed3407"
        ),
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_source_aware_3k_dd89b70e9d63_"
            "seed3407_merged"
        ),
        (
            "workspace/runs/v4.1-phase2-source-aware-v1-seed3407/"
            "fold0/adapter"
        ),
        (
            "workspace/runs/v4.1-phase2-source-aware-v1-seed3407/"
            "fold0/merged"
        ),
        "evaluated",
    ),
    ModelMove(
        "v4.1-sampling-source-aware-fold0-r2",
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_source_aware_3k_dd89b70e9d63_seed3411"
        ),
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_source_aware_3k_dd89b70e9d63_"
            "seed3411_merged"
        ),
        (
            "workspace/runs/v4.1-phase2-source-aware-v1-seed3411/"
            "fold0/adapter"
        ),
        (
            "workspace/runs/v4.1-phase2-source-aware-v1-seed3411/"
            "fold0/merged"
        ),
        "evaluated",
    ),
    ModelMove(
        "v4.1-sampling-fallback-fold0-r1",
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_coverage_first_fallback_"
            "seed3413_seed3413"
        ),
        (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            "sft_tensile_v4_1_phase2_coverage_first_fallback_"
            "seed3413_seed3413_merged"
        ),
        (
            "workspace/runs/v4.1-phase2-coverage-fallback-v1-seed3413/"
            "fold0/adapter"
        ),
        (
            "workspace/runs/v4.1-phase2-coverage-fallback-v1-seed3413/"
            "fold0/merged"
        ),
        "evaluated",
    ),
)


def _visual_moves() -> tuple[ModelMove, ...]:
    values = []
    for fold in range(3):
        source = (
            "LlamaFactory/saves/minicpmv4_5/lora/"
            f"sft_tensile_v4_1_0_760050fad303_20260724_visual_fold{fold}"
        )
        target = f"workspace/runs/v4.1-visual-cv-v1-seed3407/fold{fold}"
        values.append(
            ModelMove(
                f"v4.1-visual-baseline-fold{fold}-r1",
                source,
                f"{source}_merged",
                f"{target}/adapter",
                f"{target}/merged",
                "evaluated",
            )
        )
    return tuple(values)


def _ablation_moves() -> tuple[ModelMove, ...]:
    root = "LlamaFactory/saves/minicpmv4_5/lora/experiments/v4_1"
    target = "workspace/runs/v4.1-data-ablation-v1-seed3407"
    values = (
        (
            "v4.1-data-visual-only-fold0-r1",
            "sft_tensile_v4_1_0_760050fad303_20260723_fold0_visual",
            "visual-only",
        ),
        (
            "v4.1-data-language-augmented-fold0-r1",
            "sft_tensile_v4_1_subvideo_exp_v1_20260723_fold0_language",
            "language-augmented",
        ),
        (
            "v4.1-data-visual-augmented-fold0-r1",
            "sft_tensile_v4_1_subvideo_exp_v1_20260723_fold0_visual",
            "visual-augmented",
        ),
    )
    return tuple(
        ModelMove(
            name,
            f"{root}/{source}",
            f"{root}/{source}_merged",
            f"{target}/{variant}/fold0/adapter",
            f"{target}/{variant}/fold0/merged",
            "evaluated",
        )
        for name, source, variant in values
    )


def _language_moves() -> tuple[ModelMove, ...]:
    values = []
    for fold in range(3):
        source = (
            "LlamaFactory/saves/minicpmv4_5/lora/archive/v4_1_language/"
            f"sft_tensile_v4_1_0_760050fad303_20260723_fold{fold}"
        )
        target = (
            "workspace/runs/archive/v4.1-language-cv-v1-seed3407/"
            f"fold{fold}"
        )
        values.append(
            ModelMove(
                f"v4.1-language-only-fold{fold}-r1",
                source,
                f"{source}_merged",
                f"{target}/adapter",
                f"{target}/merged",
                "archived",
            )
        )
    return tuple(values)


def _v2_moves() -> tuple[ModelMove, ...]:
    values = []
    for scope in ("fold0", "fold1", "fold2", "full"):
        source = (
            "LlamaFactory/saves/minicpmv4_5/lora/archive/v2/"
            f"sft_interval_v2_0_0_1dab1e5e_{scope}_20260719"
        )
        target = (
            "workspace/models/archive/v2/v2.0.0-1dab1e5e-20260719/"
            f"{scope}"
        )
        values.append(
            ModelMove(
                f"v2.0-interval-baseline-{scope}-r1",
                source,
                f"{source}_merged",
                f"{target}/adapter",
                f"{target}/merged",
                "archived",
            )
        )
    return tuple(values)


ALL_MOVES = MOVES + _visual_moves() + _ablation_moves() + _language_moves() + _v2_moves()


def _path(value: str) -> Path:
    # Keep the final path component unresolved so an already-created
    # compatibility symlink can still be recognized on a repeated run.
    result = Path(os.path.abspath(ROOT / value))
    if ROOT != result and ROOT not in result.parents:
        raise MigrationError(f"路径逃逸项目目录: {value}")
    return result


def _relative_link(source: Path, target: Path) -> str:
    return os.path.relpath(target, source.parent)


def _move_and_link(source: Path, target: Path, *, apply: bool) -> str:
    if source.is_symlink():
        if source.resolve() != target.resolve():
            raise MigrationError(f"兼容链接目标错误: {source}")
        if not target.is_dir():
            raise MigrationError(f"兼容链接目标不存在: {target}")
        return "already_migrated"
    if target.exists():
        raise MigrationError(f"目标已存在但源不是兼容链接: {target}")
    if not source.is_dir():
        raise MigrationError(f"源模型目录不存在: {source}")
    if not apply:
        return "ready"
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    source.symlink_to(_relative_link(source, target), target_is_directory=True)
    return "migrated"


def _ensure_current_link(current: Path, release_root: Path) -> str:
    if current.is_symlink():
        if current.resolve() != release_root.resolve():
            raise MigrationError(f"current 兼容链接目标错误: {current}")
        return "already_current"
    if current.exists():
        raise MigrationError(f"current 路径已存在: {current}")
    current.symlink_to(
        _relative_link(current, release_root),
        target_is_directory=True,
    )
    return "created"


def _write_identity(move: ModelMove, *, apply: bool) -> None:
    if not apply:
        return
    target_adapter = _path(move.target_adapter)
    target_merged = _path(move.target_merged)
    parent = target_adapter.parent
    value = {
        "schema_version": "tensile-model-registry/local-identity/v1",
        "model_name": move.model_name,
        "lifecycle_status": move.lifecycle_status,
        "adapter_path": str(target_adapter.relative_to(ROOT)),
        "merged_path": str(target_merged.relative_to(ROOT)),
        "source_adapter_path": move.source_adapter,
        "source_merged_path": move.source_merged,
        "checkpoint_count": len(
            [path for path in target_adapter.glob("checkpoint-*") if path.is_dir()]
        ),
    }
    (parent / "model_identity.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _copy_current_release(*, apply: bool) -> dict[str, Any]:
    _, manifest = load_current_model(ROOT)
    source_adapter = _path(CURRENT_SOURCE_PREFIX)
    source_merged = _path(f"{CURRENT_SOURCE_PREFIX}_merged")
    release_root = ROOT / f"workspace/models/releases/{CURRENT_MODEL}"
    release_adapter = release_root / "adapter"
    release_merged = release_root / "merged"
    if release_root.exists():
        for name, path in (
            ("adapter", release_adapter),
            ("merged", release_merged),
        ):
            if not path.is_dir():
                raise MigrationError(f"current release {name} 不完整: {path}")
            actual = artifact_identity(path)["aggregate_sha256"]
            expected = manifest["artifacts"][name]["aggregate_sha256"]
            if actual != expected:
                raise MigrationError(
                    f"current {name} hash 不一致: expected={expected}, actual={actual}"
                )
        return {
            "model_name": CURRENT_MODEL,
            "release_root": str(release_root),
            "status": "already_copied_and_verified",
        }
    if not apply:
        return {
            "model_name": CURRENT_MODEL,
            "source_adapter": str(source_adapter),
            "source_merged": str(source_merged),
            "release_root": str(release_root),
            "status": "ready",
        }
    release_root.mkdir(parents=True)
    shutil.copytree(source_merged, release_merged)
    release_adapter.mkdir()
    adapter_files = artifact_identity(source_adapter)["files"]
    for name in adapter_files:
        shutil.copy2(source_adapter / name, release_adapter / name)
    for name, path in (
        ("adapter", release_adapter),
        ("merged", release_merged),
    ):
        actual = artifact_identity(path)["aggregate_sha256"]
        expected = manifest["artifacts"][name]["aggregate_sha256"]
        if actual != expected:
            raise MigrationError(
                f"current {name} hash 不一致: expected={expected}, actual={actual}"
            )
    shutil.copy2(
        ROOT / f"pipeline/model_registry/releases/{CURRENT_MODEL}.json",
        release_root / "release-manifest.json",
    )
    return {
        "model_name": CURRENT_MODEL,
        "release_root": str(release_root),
        "status": "copied_and_verified",
    }


def migrate(*, apply: bool) -> dict[str, Any]:
    release = _copy_current_release(apply=apply)
    records = []
    for move in ALL_MOVES:
        parse_model_name(move.model_name)
        adapter_status = _move_and_link(
            _path(move.source_adapter),
            _path(move.target_adapter),
            apply=apply,
        )
        if move.model_name == CURRENT_MODEL:
            source_merged = _path(move.source_merged)
            target_merged = _path(move.target_merged)
            release_merged = ROOT / (
                f"workspace/models/releases/{CURRENT_MODEL}/merged"
            )
            already_linked = (
                source_merged.is_symlink()
                and target_merged.is_symlink()
                and source_merged.resolve() == release_merged.resolve()
                and target_merged.resolve() == release_merged.resolve()
            )
            if already_linked:
                merged_status = "already_linked_to_release"
            elif apply:
                target_merged.parent.mkdir(parents=True, exist_ok=True)
                target_merged.symlink_to(
                    _relative_link(target_merged, release_merged),
                    target_is_directory=True,
                )
                shutil.rmtree(source_merged)
                source_merged.symlink_to(
                    _relative_link(source_merged, release_merged),
                    target_is_directory=True,
                )
                merged_status = "linked_to_release"
            else:
                merged_status = "ready_for_release_link"
        else:
            merged_status = _move_and_link(
                _path(move.source_merged),
                _path(move.target_merged),
                apply=apply,
            )
        _write_identity(move, apply=apply)
        records.append(
            {
                "model_name": move.model_name,
                "adapter": adapter_status,
                "merged": merged_status,
            }
        )
    if apply:
        current = ROOT / "workspace/models/current"
        _ensure_current_link(
            current,
            ROOT / f"workspace/models/releases/{CURRENT_MODEL}",
        )
    return {
        "schema_version": "tensile-model-registry/migration/v1",
        "apply": apply,
        "current_release": release,
        "models": records,
        "checkpoint_policy": "moved_with_adapter_not_deleted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
