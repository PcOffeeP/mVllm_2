#!/usr/bin/env python3
"""Build immutable prompt-controlled datasets for all frozen V4.1 folds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.build_v4_1_crossval_coverage_first import (  # noqa: E402
    _capacity_aware_multiset,
)
from finetune.build_v4_1_fixed_prompt_dataset import _rewrite_rows  # noqa: E402
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
from pipeline.project_workspace import (  # noqa: E402
    project_workspace_paths,
    validate_experiment_id,
)

SCHEMA_VERSION = "tensile-vlm-v4.1-prompt-crossval-dataset/v1"
SUMMARY_SCHEMA_VERSION = "tensile-vlm-v4.1-prompt-crossval-summary/v1"
DEFAULT_RELEASE_ID = "v4.1.0-ecb5aeb9657c"
DEFAULT_PROMPT_REVISION = (
    ROOT / "pipeline/prompt_registry/v4.1-concise-evidence-json-v2"
)
DEFAULT_EXPERIMENT_ID = "v4.1-prompt-concise-cv-v1-seed3411"
TRAINING_SEED = 3411
ROWS_PER_FOLD = 3000
FOLDS = (0, 1, 2)


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kError(f"无法读取 {label}: {path}: {exc}") from exc


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
    registry: dict[str, Any] = {}
    for fold in FOLDS:
        registry[f"tensile_v4_1_prompt_cv_fold{fold}_train"] = {
            **common,
            "file_name": f"datasets/train/fold_{fold}.json",
        }
        registry[f"tensile_v4_1_prompt_cv_fold{fold}_val"] = {
            **common,
            "file_name": f"datasets/validation/fold_{fold}.json",
        }
    return registry


def _prompt_sanity(prompt: Mapping[str, Any]) -> None:
    system = str(prompt.get("system_prompt") or "")
    user = str(prompt.get("user_prompt") or "")
    required = {
        "clip_state",
        "fracture_mechanism",
        "fracture_site",
        "special_case",
        "无法判断",
        '禁止字符串 "null"',
    }
    missing = sorted(item for item in required if item not in system)
    if missing:
        raise SourceAware3kError(f"Prompt 缺少关键约束: {missing}")
    if len(system) > 500:
        raise SourceAware3kError(f"Prompt 超过精简上限: {len(system)} > 500")
    if "仅依据当前视频" not in system or not user.strip():
        raise SourceAware3kError("Prompt 未固定当前视频证据边界或 user prompt 为空")


def _row_index(
    rows: Any,
    *,
    candidates_by_video: Mapping[str, Mapping[str, Any]],
    label: str,
) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    if not isinstance(rows, list) or not rows:
        raise SourceAware3kError(f"{label} 必须是非空列表")
    indexed: dict[str, Mapping[str, Any]] = {}
    sources: set[str] = set()
    for index, row in enumerate(rows):
        video, _ = validate_training_row(row, label, index)
        candidate = candidates_by_video.get(video)
        if candidate is None:
            raise SourceAware3kError(f"{label}[{index}] 无 candidate 映射: {video}")
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in indexed:
            raise SourceAware3kError(f"{label} candidate 重复: {candidate_id}")
        indexed[candidate_id] = row
        sources.add(str(candidate["source_video"]))
    return indexed, sources


def build_prompt_crossval_dataset(
    *,
    release_dir: Path,
    prompt_revision_dir: Path,
    output_root: Path,
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    project_root: Path = ROOT,
    validate_only: bool = False,
) -> tuple[Path, dict[str, Any]]:
    experiment_id = validate_experiment_id(experiment_id)
    release_dir = Path(release_dir).resolve()
    manifest_path = release_dir / "manifest/release_manifest.json"
    candidates_path = release_dir / "metadata/training_candidates.json"
    manifest = _read_json(manifest_path, "release manifest")
    metadata = _read_json(candidates_path, "training candidates")
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("immutable") is not True
        or not isinstance(metadata, Mapping)
        or not isinstance(metadata.get("candidates"), list)
    ):
        raise SourceAware3kError("release manifest 或 training candidates 非法")
    candidates = metadata["candidates"]
    candidates_by_video = {str(item["video_path"]): item for item in candidates}
    if len(candidates_by_video) != len(candidates):
        raise SourceAware3kError("training candidates video_path 不唯一")

    try:
        prompt, prompt_manifest = load_prompt_revision(prompt_revision_dir)
    except PromptControlError as exc:
        raise SourceAware3kError(str(exc)) from exc
    _prompt_sanity(prompt)

    data_root = project_workspace_paths(project_root).data
    files: dict[str, bytes] = {}
    fold_manifests: list[dict[str, Any]] = []
    all_sequence_ids: list[str] = []
    all_video_paths: list[str] = []
    for fold in FOLDS:
        train_source = _read_json(
            release_dir / f"datasets/train/fold_{fold}.json",
            f"fold{fold} train",
        )
        validation_source = _read_json(
            release_dir / f"datasets/validation/fold_{fold}.json",
            f"fold{fold} validation",
        )
        train_index, train_sources = _row_index(
            train_source,
            candidates_by_video=candidates_by_video,
            label=f"fold{fold}_train",
        )
        _, validation_sources = _row_index(
            validation_source,
            candidates_by_video=candidates_by_video,
            label=f"fold{fold}_validation",
        )
        overlap = train_sources & validation_sources
        if overlap:
            raise SourceAware3kError(
                f"fold{fold} source leakage: {sorted(overlap)}"
            )
        train_candidates = [
            item
            for item in candidates
            if str(item["candidate_id"]) in train_index
        ]
        sampling_seed = TRAINING_SEED + fold
        selected, diagnostics = _capacity_aware_multiset(
            train_candidates,
            seed=sampling_seed,
            rows=ROWS_PER_FOLD,
        )
        selected_ids = [str(item["candidate_id"]) for item in selected]
        selected_rows = [train_index[candidate_id] for candidate_id in selected_ids]
        train_rows = _rewrite_rows(
            selected_rows,
            system_prompt=prompt["system_prompt"],
            user_prompt=prompt["user_prompt"],
            data_root=data_root,
            label=f"fold{fold}_train",
        )
        validation_rows = _rewrite_rows(
            validation_source,
            system_prompt=prompt["system_prompt"],
            user_prompt=prompt["user_prompt"],
            data_root=data_root,
            label=f"fold{fold}_validation",
        )
        all_sequence_ids.extend(f"{fold}:{value}" for value in selected_ids)
        all_video_paths.extend(
            f"{fold}:{row['videos'][0]}" for row in train_rows
        )
        fold_manifests.append(
            {
                "fold": fold,
                "training_seed": TRAINING_SEED,
                "sampling_seed": sampling_seed,
                "train_rows": len(train_rows),
                "validation_rows": len(validation_rows),
                "unique_train_candidates": len(train_index),
                "train_source_count": len(train_sources),
                "validation_source_count": len(validation_sources),
                "source_overlap_count": 0,
                "candidate_sequence_sha256": _sha256_bytes(
                    _canonical_bytes(selected_ids)
                ),
                **diagnostics,
            }
        )
        files[f"datasets/train/fold_{fold}.json"] = _pretty_bytes(train_rows)
        files[f"datasets/validation/fold_{fold}.json"] = _pretty_bytes(
            validation_rows
        )

    combined_sequence_sha256 = _sha256_bytes(_canonical_bytes(all_sequence_ids))
    combined_video_sha256 = _sha256_bytes(_canonical_bytes(all_video_paths))
    sampling_manifest = {
        "schema_version": SCHEMA_VERSION,
        "immutable": True,
        "sampling_id": f"{experiment_id}-frozen-release-folds",
        "release_id": manifest["release_id"],
        "rows_per_fold": ROWS_PER_FOLD,
        "folds": fold_manifests,
        "candidate_sequence_sha256": combined_sequence_sha256,
        "video_sequence_sha256": combined_video_sha256,
    }
    sampling_bytes = _pretty_bytes(sampling_manifest)
    files["sampling_manifest.json"] = sampling_bytes
    files["dataset_info.json"] = _pretty_bytes(_dataset_registry())

    release_identity = {
        "release_id": manifest["release_id"],
        "release_manifest_sha256": sha256_file(manifest_path),
        "training_candidates_sha256": sha256_file(candidates_path),
    }
    sampling_identity = {
        "sampling_id": sampling_manifest["sampling_id"],
        "sampling_manifest_sha256": _sha256_bytes(sampling_bytes),
        "candidate_sequence_sha256": combined_sequence_sha256,
        "video_sequence_sha256": combined_video_sha256,
        "seed": TRAINING_SEED,
        "folds": list(FOLDS),
    }
    base_contract = _read_json(
        ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
        "V4.1 contract",
    )
    experiment_contract = build_experiment_contract(
        prompt_revision_dir=prompt_revision_dir,
        release_identity=release_identity,
        sampling_identity=sampling_identity,
        generation=base_contract["analysis"]["generation"],
    )
    files["experiment_contract.json"] = _pretty_bytes(experiment_contract)

    identity = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "release": release_identity,
        "sampling": sampling_identity,
        "prompt_content_sha256": prompt_manifest["prompt_content_sha256"],
    }
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": "ready",
        "immutable": True,
        "experiment_id": experiment_id,
        "input_identity_sha256": _sha256_bytes(_canonical_bytes(identity)),
        "release": release_identity,
        "sampling": sampling_identity,
        "prompt_revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt_manifest["prompt_content_sha256"],
        "system_prompt_chars": len(prompt["system_prompt"]),
        "experiment_contract_sha256": experiment_contract[
            "experiment_contract_sha256"
        ],
        "folds": fold_manifests,
        "files": [
            {
                "path": relative,
                "size_bytes": len(content),
                "sha256": _sha256_bytes(content),
            }
            for relative, content in sorted(files.items())
        ],
    }
    output_dir = Path(output_root) / experiment_id / "input"
    if not validate_only or output_dir.exists():
        _write_immutable_directory(output_dir, files=files, summary=summary)
    return output_dir, summary


def parse_args() -> argparse.Namespace:
    current = current_data_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=current.training_releases / DEFAULT_RELEASE_ID,
    )
    parser.add_argument(
        "--prompt-revision-dir",
        type=Path,
        default=DEFAULT_PROMPT_REVISION,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_workspace_paths(ROOT).runs,
    )
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output, summary = build_prompt_crossval_dataset(
        release_dir=args.release_dir,
        prompt_revision_dir=args.prompt_revision_dir,
        output_root=args.output_root,
        experiment_id=args.experiment_id,
        validate_only=args.validate_only,
    )
    print(json.dumps({"output_dir": str(output), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
