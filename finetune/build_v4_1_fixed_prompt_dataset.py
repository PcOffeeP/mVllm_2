#!/usr/bin/env python3
"""Derive a seed3411 V4.1 bundle bound to one immutable Prompt revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_source_aware_3k import (  # noqa: E402
    SourceAware3kError,
    _canonical_bytes,
    _pretty_bytes,
    _sha256_bytes,
    _write_immutable_directory,
)
from finetune.v4_1_runtime import validate_training_row  # noqa: E402
from pipeline.current_data import current_data_paths  # noqa: E402
from pipeline.prompt_control import (  # noqa: E402
    PromptControlError,
    build_experiment_contract,
    load_prompt_revision,
)
from pipeline.prompt_control.core import sha256_file  # noqa: E402
from pipeline.data_roots import resolve_workspace_artifact  # noqa: E402
from pipeline.project_workspace import (  # noqa: E402
    CURRENT_EXPERIMENT_ID,
    project_workspace_paths,
    validate_experiment_id,
)

SCHEMA_VERSION = "tensile-vlm-v4.1-fixed-prompt-dataset/v1"
SUMMARY_SCHEMA_VERSION = "tensile-vlm-v4.1-fixed-prompt-dataset-summary/v1"
DEFAULT_SEED = 3411
DEFAULT_SOURCE_SAMPLING_ID = "source-aware-3k-2a84e8b6cfc3"
DEFAULT_RELEASE_ID = "v4.1.0-ecb5aeb9657c"
DEFAULT_PROMPT_REVISION = (
    ROOT
    / "pipeline/prompt_registry/v4.1-fixed-full-fields-initial-v1"
)


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kError(f"无法读取 {label}: {path}: {exc}") from exc


def _validate_source_sampling(source_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source_dir = Path(source_dir).resolve()
    summary = _read_json(source_dir / "summary.json", "source sampling summary")
    manifest = _read_json(
        source_dir / "sampling_manifest.json",
        "source sampling manifest",
    )
    if (
        not isinstance(summary, Mapping)
        or summary.get("immutable") is not True
        or summary.get("status") != "ready"
        or not isinstance(manifest, Mapping)
        or summary.get("sampling_id") != manifest.get("sampling_id")
        or manifest.get("release_id") != summary.get("release_id")
    ):
        raise SourceAware3kError("source sampling 身份或状态非法")
    entries = summary.get("files")
    if not isinstance(entries, list):
        raise SourceAware3kError("source sampling file manifest 缺失")
    root = source_dir.resolve()
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise SourceAware3kError("source sampling file entry 非法")
        relative = entry["path"]
        path = (root / relative).resolve()
        if relative in seen or not path.is_relative_to(root):
            raise SourceAware3kError("source sampling 包含重复或越界路径")
        seen.add(relative)
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or sha256_file(path) != entry.get("sha256")
        ):
            raise SourceAware3kError(f"source sampling 文件漂移: {path}")
    required = {
        "dataset_info.json",
        f"datasets/seed_{DEFAULT_SEED}.json",
        "datasets/fold_0_validation.json",
        "sampling_manifest.json",
    }
    if not required <= seen:
        raise SourceAware3kError("source sampling 缺少 seed3411 或 validation 文件")
    return dict(summary), dict(manifest)


def _rewrite_rows(
    rows: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    data_root: Path,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise SourceAware3kError(f"{label} 必须是非空列表")
    rewritten: list[dict[str, Any]] = []
    for index, source_row in enumerate(rows):
        video_path, _ = validate_training_row(source_row, label, index)
        messages = source_row["messages"]
        resolved_video = resolve_workspace_artifact(video_path, data_root)
        try:
            portable_video = str(resolved_video.relative_to(data_root))
        except ValueError as exc:
            raise SourceAware3kError(
                f"{label}[{index}] 视频路径不属于项目 workspace/data"
            ) from exc
        row = {
            "videos": [portable_video],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"<video>\n{user_prompt}"},
                {
                    "role": "assistant",
                    "content": messages[2]["content"],
                },
            ],
        }
        validate_training_row(row, label, index)
        rewritten.append(row)
    return rewritten


def _validate_release_identity(
    release_dir: Path,
    release_identity: Mapping[str, Any],
) -> None:
    release_dir = Path(release_dir).resolve()
    manifest_path = release_dir / "manifest/release_manifest.json"
    metadata_path = release_dir / "metadata/training_candidates.json"
    if not manifest_path.is_file() or not metadata_path.is_file():
        raise SourceAware3kError(f"training release 文件缺失: {release_dir}")
    manifest = _read_json(manifest_path, "release manifest")
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("release_id") != release_identity.get("release_id")
        or manifest.get("immutable") is not True
        or sha256_file(manifest_path)
        != release_identity.get("release_manifest_sha256")
        or sha256_file(metadata_path)
        != release_identity.get("training_candidates_sha256")
    ):
        raise SourceAware3kError("training release 身份或文件 hash 漂移")
    entry = next(
        (
            item
            for item in manifest.get("files") or []
            if isinstance(item, Mapping)
            and item.get("path") == "metadata/training_candidates.json"
        ),
        None,
    )
    if (
        not isinstance(entry, Mapping)
        or entry.get("sha256") != release_identity["training_candidates_sha256"]
        or entry.get("size_bytes") != metadata_path.stat().st_size
    ):
        raise SourceAware3kError("training_candidates 未被 release manifest 正确绑定")


def _dataset_registry() -> dict[str, Any]:
    common = {
        "formatting": "sharegpt",
        "columns": {"messages": "messages", "videos": "videos"},
        "tags": {
            "role_tag": "role",
            "content_tag": "content",
            "user_tag": "user",
            "assistant_tag": "assistant",
            "observation_tag": "observation",
            "function_tag": "function_call",
            "system_tag": "system",
        },
    }
    return {
        "tensile_v4_1_fixed_full_fields_seed3411": {
            **common,
            "file_name": "datasets/seed_3411.json",
        },
        "tensile_v4_1_fixed_full_fields_fold0_val": {
            **common,
            "file_name": "datasets/fold_0_validation.json",
        },
    }


def build_fixed_prompt_dataset(
    *,
    source_sampling_dir: Path,
    prompt_revision_dir: Path,
    output_root: Path,
    experiment_id: str = CURRENT_EXPERIMENT_ID,
    project_root: Path = ROOT,
    release_dir: Path | None = None,
    validate_only: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Freeze a prompt-only derivative while preserving seed3411 media and labels."""
    experiment_id = validate_experiment_id(experiment_id)
    source_summary, source_manifest = _validate_source_sampling(source_sampling_dir)
    data_root = project_workspace_paths(project_root).data
    try:
        prompt, prompt_manifest = load_prompt_revision(prompt_revision_dir)
    except PromptControlError as exc:
        raise SourceAware3kError(str(exc)) from exc
    plans = source_manifest.get("plans")
    plan = next(
        (
            item
            for item in plans or []
            if isinstance(item, Mapping) and item.get("seed") == DEFAULT_SEED
        ),
        None,
    )
    if not isinstance(plan, Mapping):
        raise SourceAware3kError("source sampling manifest 缺少 seed3411 plan")
    candidate_sequence = plan.get("candidate_sequence")
    if (
        not isinstance(candidate_sequence, list)
        or not candidate_sequence
        or not all(isinstance(item, str) and item for item in candidate_sequence)
    ):
        raise SourceAware3kError("source sampling seed3411 candidate sequence 非法")
    sequence_hash = _sha256_bytes(_canonical_bytes(candidate_sequence))
    summary_plan = next(
        (
            item
            for item in source_summary.get("plans") or []
            if isinstance(item, Mapping) and item.get("seed") == DEFAULT_SEED
        ),
        None,
    )
    if (
        isinstance(summary_plan, Mapping)
        and summary_plan.get("sequence_sha256") != sequence_hash
    ):
        raise SourceAware3kError("source sampling seed3411 sequence hash 漂移")
    source_manifest_path = Path(source_sampling_dir) / "sampling_manifest.json"
    release_inputs = source_manifest.get("inputs")
    if not isinstance(release_inputs, Mapping):
        raise SourceAware3kError("source sampling 缺少 release inputs")
    release_identity = {
        "release_id": source_manifest["release_id"],
        "release_manifest_sha256": release_inputs.get("release_manifest_sha256"),
        "training_candidates_sha256": release_inputs.get(
            "training_candidates_sha256"
        ),
    }
    if release_dir is not None:
        _validate_release_identity(release_dir, release_identity)
    sampling_identity = {
        "sampling_id": source_manifest["sampling_id"],
        "sampling_manifest_sha256": sha256_file(source_manifest_path),
        "candidate_sequence_sha256": sequence_hash,
        "seed": DEFAULT_SEED,
    }
    base_contract = _read_json(
        ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
        "V4.1 contract",
    )
    generation = base_contract["analysis"]["generation"]
    source_train_rows = _read_json(
        Path(source_sampling_dir) / f"datasets/seed_{DEFAULT_SEED}.json",
        "seed3411 dataset",
    )
    if (
        not isinstance(source_train_rows, list)
        or len(source_train_rows) != len(candidate_sequence)
    ):
        raise SourceAware3kError("seed3411 数据行数与 candidate sequence 不一致")
    source_video_sequence = [
        str(row["videos"][0])
        for row in source_train_rows
        if isinstance(row, Mapping)
        and isinstance(row.get("videos"), list)
        and row["videos"]
    ]
    if len(source_video_sequence) != len(source_train_rows):
        raise SourceAware3kError("seed3411 视频序列结构非法")
    video_sequence_hash = _sha256_bytes(_canonical_bytes(source_video_sequence))
    sampling_identity["video_sequence_sha256"] = video_sequence_hash
    experiment_contract = build_experiment_contract(
        prompt_revision_dir=prompt_revision_dir,
        release_identity=release_identity,
        sampling_identity=sampling_identity,
        generation=generation,
    )
    train_rows = _rewrite_rows(
        source_train_rows,
        system_prompt=prompt["system_prompt"],
        user_prompt=prompt["user_prompt"],
        data_root=data_root,
        label="seed3411",
    )
    validation_rows = _rewrite_rows(
        _read_json(
            Path(source_sampling_dir) / "datasets/fold_0_validation.json",
            "fold0 validation",
        ),
        system_prompt=prompt["system_prompt"],
        user_prompt=prompt["user_prompt"],
        data_root=data_root,
        label="fold0_validation",
    )
    identity_seed = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "source_sampling_id": source_manifest["sampling_id"],
        "source_sampling_manifest_sha256": sampling_identity[
            "sampling_manifest_sha256"
        ],
        "candidate_sequence_sha256": sequence_hash,
        "video_sequence_sha256": video_sequence_hash,
        "prompt_revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt_manifest["prompt_content_sha256"],
    }
    input_identity_sha256 = _sha256_bytes(_canonical_bytes(identity_seed))
    files = {
        "dataset_info.json": _pretty_bytes(_dataset_registry()),
        "datasets/seed_3411.json": _pretty_bytes(train_rows),
        "datasets/fold_0_validation.json": _pretty_bytes(validation_rows),
        "experiment_contract.json": _pretty_bytes(experiment_contract),
    }
    file_manifest = [
        {
            "path": relative,
            "size_bytes": len(content),
            "sha256": _sha256_bytes(content),
        }
        for relative, content in sorted(files.items())
    ]
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": "ready",
        "immutable": True,
        "experiment_id": experiment_id,
        "input_identity_sha256": input_identity_sha256,
        "release": release_identity,
        "source_sampling": sampling_identity,
        "prompt_revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt_manifest["prompt_content_sha256"],
        "experiment_contract_sha256": experiment_contract[
            "experiment_contract_sha256"
        ],
        "train_row_count": len(train_rows),
        "validation_row_count": len(validation_rows),
        "files": file_manifest,
    }
    output_dir = Path(output_root) / experiment_id / "input"
    if not validate_only or output_dir.exists():
        _write_immutable_directory(output_dir, files=files, summary=summary)
    return output_dir, summary


def parse_args() -> argparse.Namespace:
    paths = current_data_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-sampling-dir",
        type=Path,
        default=(
            paths.derived
            / "metadata/v4_1/source_aware_3k"
            / DEFAULT_SOURCE_SAMPLING_ID
        ),
    )
    parser.add_argument(
        "--prompt-revision-dir",
        type=Path,
        default=DEFAULT_PROMPT_REVISION,
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=paths.training_releases / DEFAULT_RELEASE_ID,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_workspace_paths(ROOT).runs,
    )
    parser.add_argument("--experiment-id", default=CURRENT_EXPERIMENT_ID)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output, summary = build_fixed_prompt_dataset(
        source_sampling_dir=args.source_sampling_dir,
        prompt_revision_dir=args.prompt_revision_dir,
        output_root=args.output_root,
        experiment_id=args.experiment_id,
        release_dir=args.release_dir,
        validate_only=args.validate_only,
    )
    print(
        json.dumps(
            {
                "output_dir": str(output),
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
