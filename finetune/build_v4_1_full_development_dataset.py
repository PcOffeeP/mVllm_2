#!/usr/bin/env python3
"""Build one immutable full-development dataset from the published V4.1 release."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.build_v4_1_crossval_coverage_first import (  # noqa: E402
    CLIP_STATE_ORDER,
    SIGNATURE_COUNT_CAP,
    SOURCE_COUNT_CAP,
    _desired_state_quotas,
)
from finetune.build_v4_1_fixed_prompt_dataset import _rewrite_rows  # noqa: E402
from finetune.build_v4_1_prompt_crossval_dataset import (  # noqa: E402
    DEFAULT_PROMPT_REVISION,
    DEFAULT_RELEASE_ID,
    FOLDS,
    _prompt_sanity,
    _read_json,
    _row_index,
)
from finetune.build_v4_1_source_aware_3k import (  # noqa: E402
    SourceAware3kError,
    _canonical_bytes,
    _pretty_bytes,
    _sha256_bytes,
    _write_immutable_directory,
)
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
from pipeline.v4_1_labels import canonicalize_v4_1_labels  # noqa: E402

SCHEMA_VERSION = "tensile-vlm-v4.1-full-development-dataset/v2"
SUMMARY_SCHEMA_VERSION = "tensile-vlm-v4.1-full-development-summary/v2"
DEFAULT_EXPERIMENT_ID = "v4.1-prompt-concise-full-v1-seed3411"
PARENT_CROSSVAL_EXPERIMENT_ID = "v4.1-prompt-concise-cv-v1-seed3411"
TRAINING_SEED = 3411
ROWS_PER_EPOCH = 3000


def _candidate_id(item: Mapping[str, Any]) -> str:
    return str(item["candidate_id"])


def _state(item: Mapping[str, Any]) -> str:
    return str((item.get("labels") or {}).get("clip_state") or "")


def _signature(item: Mapping[str, Any]) -> str:
    return str(item.get("effective_frame_signature") or item["candidate_id"])


def _validate_release_files(
    release_dir: Path,
    release_manifest: Mapping[str, Any],
) -> None:
    required = {
        "metadata/training_candidates.json",
        *(
            f"datasets/{split}/fold_{fold}.json"
            for fold in FOLDS
            for split in ("train", "validation")
        ),
    }
    entries = {
        item.get("path"): item
        for item in release_manifest.get("files") or []
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    if not required <= set(entries):
        raise SourceAware3kError("release manifest 未绑定 full-development 所需文件")
    for relative in sorted(required):
        path = release_dir / relative
        entry = entries[relative]
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or sha256_file(path) != entry.get("sha256")
        ):
            raise SourceAware3kError(f"release 受管文件缺失或漂移: {relative}")


def _full_multiset(
    candidates: list[Mapping[str, Any]],
    *,
    seed: int,
    rows: int,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    by_id = {_candidate_id(item): item for item in candidates}
    if len(by_id) != len(candidates):
        raise SourceAware3kError("published development candidate_id 重复")
    if not by_id or len(by_id) > rows:
        raise SourceAware3kError("published development 数量为空或超过每轮预算")

    unique = [by_id[candidate_id] for candidate_id in sorted(by_id)]
    invalid_states = sorted({_state(item) for item in unique} - set(CLIP_STATE_ORDER))
    if invalid_states:
        raise SourceAware3kError(
            f"published development 含非法 clip_state: {invalid_states}"
        )
    selected = list(unique)
    total_by_state = Counter(_state(item) for item in unique)
    unique_by_source = Counter(str(item["source_video"]) for item in unique)
    unique_by_signature = Counter(_signature(item) for item in unique)
    repeat_by_candidate: Counter[str] = Counter()
    repeat_by_source: Counter[str] = Counter()
    repeat_by_signature: Counter[str] = Counter()
    target = _desired_state_quotas(unique, rows)
    rng = random.Random(seed)
    tie_break = {_candidate_id(item): rng.random() for item in unique}

    while len(selected) < rows:
        eligible: dict[str, list[Mapping[str, Any]]] = {}
        for item in unique:
            source = str(item["source_video"])
            signature = _signature(item)
            if unique_by_source[source] + repeat_by_source[source] >= SOURCE_COUNT_CAP:
                continue
            if (
                unique_by_signature[signature] + repeat_by_signature[signature]
                >= SIGNATURE_COUNT_CAP
            ):
                continue
            eligible.setdefault(_state(item), []).append(item)
        if not eligible:
            raise SourceAware3kError(
                "full-development repeat caps 无法填满 3000 条预算"
            )
        under_target = [
            state
            for state in eligible
            if total_by_state[state] < target.get(state, 0)
        ]
        states = under_target or list(eligible)
        chosen_state = min(
            states,
            key=lambda state: (
                total_by_state[state] - target.get(state, 0),
                total_by_state[state],
                CLIP_STATE_ORDER.index(state),
            ),
        )
        item = min(
            eligible[chosen_state],
            key=lambda candidate: (
                repeat_by_candidate[_candidate_id(candidate)],
                tie_break[_candidate_id(candidate)],
                _candidate_id(candidate),
            ),
        )
        selected.append(item)
        total_by_state[chosen_state] += 1
        repeat_by_candidate[_candidate_id(item)] += 1
        repeat_by_source[str(item["source_video"])] += 1
        repeat_by_signature[_signature(item)] += 1

    rng.shuffle(selected)
    unique_ids = sorted(by_id)
    selected_ids = [_candidate_id(item) for item in selected]
    source_counts = {
        key: {
            "unique": unique_by_source[key],
            "repeat": repeat_by_source[key],
            "total": unique_by_source[key] + repeat_by_source[key],
        }
        for key in sorted(unique_by_source)
    }
    signature_counts = {
        key: {
            "unique": unique_by_signature[key],
            "repeat": repeat_by_signature[key],
            "total": unique_by_signature[key] + repeat_by_signature[key],
        }
        for key in sorted(unique_by_signature)
    }
    return selected, {
        "candidate_count": len(unique),
        "candidate_ids": unique_ids,
        "unique_coverage_count": len(unique),
        "unique_coverage_rate": 1.0,
        "repeat_count": len(selected) - len(unique),
        "candidate_ids_sha256": _sha256_bytes(_canonical_bytes(unique_ids)),
        "candidate_multiset_sha256": _sha256_bytes(
            _canonical_bytes(sorted(selected_ids))
        ),
        "candidate_sequence_sha256": _sha256_bytes(
            _canonical_bytes(selected_ids)
        ),
        "target_state_quota": dict(sorted(target.items())),
        "actual_state_quota": dict(sorted(total_by_state.items())),
        "source_count_cap": SOURCE_COUNT_CAP,
        "signature_count_cap": SIGNATURE_COUNT_CAP,
        "unique_max_source_count": max(unique_by_source.values()),
        "unique_max_signature_count": max(unique_by_signature.values()),
        "final_max_source_count": max(item["total"] for item in source_counts.values()),
        "final_max_signature_count": max(
            item["total"] for item in signature_counts.values()
        ),
        "source_counts": source_counts,
        "signature_counts": signature_counts,
    }


def _release_row_index(
    release_dir: Path,
    *,
    candidates_by_video: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    expected_ids = {
        str(candidate["candidate_id"]) for candidate in candidates_by_video.values()
    }
    canonical_rows: dict[str, Mapping[str, Any]] = {}
    fold_proofs: list[dict[str, Any]] = []
    for fold in FOLDS:
        fold_ids: set[str] = set()
        train_sources: set[str] = set()
        validation_sources: set[str] = set()
        for split, source_bucket in (
            ("train", train_sources),
            ("validation", validation_sources),
        ):
            rows = _read_json(
                release_dir / f"datasets/{split}/fold_{fold}.json",
                f"fold{fold} {split}",
            )
            indexed, sources = _row_index(
                rows,
                candidates_by_video=candidates_by_video,
                label=f"fold{fold}_{split}",
            )
            source_bucket.update(sources)
            for candidate_id, row in indexed.items():
                if candidate_id in fold_ids:
                    raise SourceAware3kError(
                        f"fold{fold} train/validation candidate 重叠: {candidate_id}"
                    )
                fold_ids.add(candidate_id)
                previous = canonical_rows.get(candidate_id)
                if previous is not None:
                    _, previous_labels = _validate_row(previous, candidate_id)
                    _, labels = _validate_row(row, candidate_id)
                    if previous_labels != labels:
                        raise SourceAware3kError(
                            f"release fold 间标签漂移: {candidate_id}"
                        )
                else:
                    canonical_rows[candidate_id] = row
        if fold_ids != expected_ids:
            raise SourceAware3kError(f"fold{fold} 未完整覆盖 published candidates")
        if train_sources & validation_sources:
            raise SourceAware3kError(f"fold{fold} source leakage")
        fold_proofs.append(
            {
                "fold": fold,
                "candidate_count": len(fold_ids),
                "train_source_count": len(train_sources),
                "validation_source_count": len(validation_sources),
                "source_overlap_count": 0,
            }
        )
    if set(canonical_rows) != expected_ids:
        raise SourceAware3kError("三折并集与 published candidate 集不一致")
    candidates_by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in candidates_by_video.values()
    }
    for candidate_id, row in canonical_rows.items():
        _, row_labels = _validate_row(row, candidate_id)
        published_labels = canonicalize_v4_1_labels(
            candidates_by_id[candidate_id].get("labels")
        )
        if row_labels != published_labels:
            raise SourceAware3kError(
                f"published candidate 与 release row 标签不一致: {candidate_id}"
            )
    actual_ids = set(canonical_rows)
    return canonical_rows, {
        "folds": fold_proofs,
        "union_matches_release": actual_ids == expected_ids,
        "missing_candidate_ids": sorted(expected_ids - actual_ids),
        "extra_candidate_ids": sorted(actual_ids - expected_ids),
    }


def _validate_row(
    row: Mapping[str, Any],
    candidate_id: str,
) -> tuple[str, dict[str, Any]]:
    from finetune.v4_1_runtime import validate_training_row

    return validate_training_row(row, f"candidate:{candidate_id}", 0)


def _dataset_registry() -> dict[str, Any]:
    return {
        "tensile_v4_1_prompt_full_development": {
            "file_name": "datasets/full_development.json",
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
    }


def build_full_development_dataset(
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
    release_manifest = _read_json(manifest_path, "release manifest")
    candidate_metadata = _read_json(candidates_path, "training candidates")
    if (
        not isinstance(release_manifest, Mapping)
        or release_manifest.get("immutable") is not True
        or not isinstance(candidate_metadata, Mapping)
        or not isinstance(candidate_metadata.get("candidates"), list)
    ):
        raise SourceAware3kError("release 或 published candidates 非法")
    _validate_release_files(release_dir, release_manifest)
    candidates = candidate_metadata["candidates"]
    candidates_by_video = {str(item["video_path"]): item for item in candidates}
    if len(candidates_by_video) != len(candidates):
        raise SourceAware3kError("published candidate video_path 不唯一")

    try:
        prompt, prompt_manifest = load_prompt_revision(prompt_revision_dir)
    except PromptControlError as exc:
        raise SourceAware3kError(str(exc)) from exc
    _prompt_sanity(prompt)

    rows_by_id, fold_union_proof = _release_row_index(
        release_dir,
        candidates_by_video=candidates_by_video,
    )
    selected, sampling = _full_multiset(
        candidates,
        seed=TRAINING_SEED,
        rows=ROWS_PER_EPOCH,
    )
    selected_rows = [rows_by_id[_candidate_id(item)] for item in selected]
    data_root = project_workspace_paths(project_root).data
    rewritten = _rewrite_rows(
        selected_rows,
        system_prompt=prompt["system_prompt"],
        user_prompt=prompt["user_prompt"],
        data_root=data_root,
        label="full_development",
    )

    release_identity = {
        "release_id": release_manifest["release_id"],
        "release_manifest_sha256": sha256_file(manifest_path),
        "training_candidates_sha256": sha256_file(candidates_path),
    }
    sampling_manifest = {
        "schema_version": SCHEMA_VERSION,
        "immutable": True,
        "sampling_id": f"{experiment_id}-published-development",
        "seed": TRAINING_SEED,
        "rows_per_epoch": ROWS_PER_EPOCH,
        "source_scope": "published_development_release_only",
        "sealed_or_held_out_inputs_read": False,
        "parent_crossval_experiment_id": PARENT_CROSSVAL_EXPERIMENT_ID,
        "release": release_identity,
        "fold_union_proof": fold_union_proof,
        **sampling,
    }
    sampling_bytes = _pretty_bytes(sampling_manifest)
    sampling_identity = {
        "sampling_id": sampling_manifest["sampling_id"],
        "sampling_manifest_sha256": _sha256_bytes(sampling_bytes),
        "candidate_sequence_sha256": sampling["candidate_sequence_sha256"],
        "candidate_multiset_sha256": sampling["candidate_multiset_sha256"],
        "candidate_ids_sha256": sampling["candidate_ids_sha256"],
        "seed": TRAINING_SEED,
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
    files = {
        "dataset_info.json": _pretty_bytes(_dataset_registry()),
        "datasets/full_development.json": _pretty_bytes(rewritten),
        "sampling_manifest.json": sampling_bytes,
        "experiment_contract.json": _pretty_bytes(experiment_contract),
    }
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
        "parent_crossval_experiment_id": PARENT_CROSSVAL_EXPERIMENT_ID,
        "input_identity_sha256": _sha256_bytes(_canonical_bytes(identity)),
        "release": release_identity,
        "sampling": sampling_identity,
        "prompt_revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt_manifest["prompt_content_sha256"],
        "experiment_contract_sha256": experiment_contract[
            "experiment_contract_sha256"
        ],
        "rows_per_epoch": len(rewritten),
        "published_candidate_count": sampling["candidate_count"],
        "unique_coverage_rate": sampling["unique_coverage_rate"],
        "repeat_count": sampling["repeat_count"],
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


def main() -> int:
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
    args = parser.parse_args()
    output, summary = build_full_development_dataset(
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
