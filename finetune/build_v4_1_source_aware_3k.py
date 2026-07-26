"""Build deterministic source-aware 3k sampling artifacts for V4.1 fold0."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from finetune.v4_1_runtime import validate_training_row
from pipeline.data_roots import resolve_workspace_artifact
from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_labels import canonicalize_v4_1_labels

SAMPLING_SCHEMA_VERSION = "tensile-vlm-v4.1-source-aware-3k/v1"
SUMMARY_SCHEMA_VERSION = "tensile-vlm-v4.1-source-aware-3k-summary/v1"
POLICY_VERSION = "source-aware-3k/1.0"
ROWS_PER_EPOCH = 3000
HARD_NEGATIVES_PER_EPOCH = 900
OTHER_ROWS_PER_EPOCH = ROWS_PER_EPOCH - HARD_NEGATIVES_PER_EPOCH
EPOCHS = 3
SOURCE_SHARE_CAP = 0.05
SOURCE_COUNT_CAP = int(ROWS_PER_EPOCH * SOURCE_SHARE_CAP)
SIGNATURE_COUNT_CAP = 3
DEFAULT_SEEDS = (3407, 3411)


class SourceAware3kError(ValueError):
    """The fixed 3k policy cannot be satisfied without relaxing a hard gate."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceAware3kError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SourceAware3kError(f"{label}不是合法 JSON: {path}: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceAware3kError(f"{label}必须是对象")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SourceAware3kError(f"{label}必须是列表")
    return value


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verify_release_file(
    release_dir: Path,
    file_index: Mapping[str, Mapping[str, Any]],
    relative: str,
) -> Path:
    entry = file_index.get(relative)
    if entry is None:
        raise SourceAware3kError(f"release manifest 缺少 {relative}")
    root = release_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise SourceAware3kError(f"release 文件越界: {relative}")
    if (
        not path.is_file()
        or path.stat().st_size != entry.get("size_bytes")
        or sha256_file(path) != entry.get("sha256")
    ):
        raise SourceAware3kError(f"release 文件缺失或漂移: {path}")
    return path


def _release_inputs(
    release_dir: Path,
    *,
    media_root: Path,
    verify_media: bool,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    bytes,
    dict[str, str],
]:
    release_dir = Path(release_dir).resolve()
    manifest_path = release_dir / "manifest/release_manifest.json"
    manifest = _mapping(_read_json(manifest_path, "release manifest"), "release manifest")
    if (
        manifest.get("schema_version") != "tensile-training-release/v4.1"
        or manifest.get("status") != "training_ready"
        or manifest.get("immutable") is not True
        or manifest.get("contract_version") != "tensile-vlm/v4.1"
    ):
        raise SourceAware3kError("release 身份或状态不满足 3k 采样要求")
    files = [
        _mapping(item, "release file")
        for item in _list(manifest.get("files"), "release files")
    ]
    file_index = {str(item.get("path") or ""): item for item in files}
    if len(file_index) != len(files) or "" in file_index:
        raise SourceAware3kError("release files 包含空路径或重复路径")
    metadata_path = _verify_release_file(
        release_dir,
        file_index,
        "metadata/training_candidates.json",
    )
    train_path = _verify_release_file(
        release_dir,
        file_index,
        "datasets/train/fold_0.json",
    )
    validation_path = _verify_release_file(
        release_dir,
        file_index,
        "datasets/validation/fold_0.json",
    )
    _verify_release_file(release_dir, file_index, "dataset_info.json")
    metadata = _mapping(
        _read_json(metadata_path, "training candidates"),
        "training candidates",
    )
    candidates = [
        dict(_mapping(item, "training candidate"))
        for item in _list(metadata.get("candidates"), "training candidates")
    ]
    candidate_ids = [str(item.get("candidate_id") or "") for item in candidates]
    if (
        metadata.get("candidate_count") != len(candidates)
        or any(not item for item in candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
    ):
        raise SourceAware3kError("training candidates 数量或 candidate_id 非法")
    by_video: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        source = candidate.get("source_video")
        signature = candidate.get("effective_frame_signature")
        video_path = candidate.get("video_path")
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(signature, str)
            or len(signature) != 64
            or not isinstance(video_path, str)
            or not video_path
            or video_path in by_video
        ):
            raise SourceAware3kError(
                f"{candidate_id}: source、有效帧签名或视频路径非法"
            )
        candidate["labels"] = canonicalize_v4_1_labels(candidate.get("labels"))
        if verify_media:
            media = resolve_workspace_artifact(video_path, media_root)
            if not media.is_file() or sha256_file(media) != candidate.get("video_sha256"):
                raise SourceAware3kError(f"{candidate_id}: 训练媒体缺失或哈希漂移")
        by_video[video_path] = candidate

    training_rows_raw = _list(_read_json(train_path, "fold0 train"), "fold0 train")
    training_rows: list[dict[str, Any]] = []
    fold0_candidates: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(training_rows_raw):
        row = dict(_mapping(raw, f"fold0 train[{index}]"))
        video_path, labels = validate_training_row(row, "fold_0_train", index)
        candidate = by_video.get(video_path)
        if candidate is None:
            raise SourceAware3kError(
                f"fold0 train[{index}] 无法映射到 training candidate"
            )
        if labels != candidate["labels"]:
            raise SourceAware3kError(
                f"{candidate['candidate_id']}: dataset 与 metadata 标签漂移"
            )
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in fold0_candidates:
            raise SourceAware3kError(f"fold0 train candidate 重复: {candidate_id}")
        fold0_candidates[candidate_id] = candidate
        training_rows.append(row)
    expected_train = (manifest.get("counts") or {}).get("splits", {}).get("fold_0_train")
    if expected_train != len(training_rows):
        raise SourceAware3kError("fold0 train 数量与 release manifest 不一致")

    validation_bytes = validation_path.read_bytes()
    validation_rows = _list(
        json.loads(validation_bytes),
        "fold0 validation",
    )
    for index, row in enumerate(validation_rows):
        validate_training_row(row, "fold_0_val", index)
    identities = {
        "release_manifest_sha256": sha256_file(manifest_path),
        "training_candidates_sha256": sha256_file(metadata_path),
        "fold0_train_sha256": sha256_file(train_path),
        "fold0_validation_sha256": sha256_file(validation_path),
    }
    row_index = {
        validate_training_row(row, "fold_0_train", index)[0]: row
        for index, row in enumerate(training_rows)
    }
    return (
        dict(manifest),
        list(fold0_candidates.values()),
        row_index,
        validation_rows,
        validation_bytes,
        identities,
    )


def _state_weights(candidates: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    frequencies = Counter(str(candidate["labels"]["clip_state"]) for candidate in candidates)
    if "未断裂" in frequencies:
        raise SourceAware3kError("other-state pool 意外包含未断裂")
    raw = {state: 1.0 / math.sqrt(count) for state, count in frequencies.items()}
    mean = sum(frequencies[state] * raw[state] for state in raw) / sum(
        frequencies.values()
    )
    return {
        state: min(3.0, max(0.5, raw[state] / mean))
        for state in sorted(raw)
    }


def _pool_capacity(candidates: Sequence[Mapping[str, Any]]) -> int:
    by_source: dict[str, Counter[str]] = {}
    for candidate in candidates:
        source = str(candidate["source_video"])
        signature = str(candidate["effective_frame_signature"])
        by_source.setdefault(source, Counter())[signature] += 1
    return sum(
        min(
            SOURCE_COUNT_CAP,
            sum(SIGNATURE_COUNT_CAP for _ in signatures),
        )
        for signatures in by_source.values()
    )


def _draw_quota(
    *,
    rng: np.random.Generator,
    pool: Sequence[Mapping[str, Any]],
    probabilities: np.ndarray,
    quota: int,
    source_counts: Counter[str],
    signature_counts: Counter[str],
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    selected: list[Mapping[str, Any]] = []
    rejections = Counter()
    attempts = 0
    max_attempts = max(100_000, quota * 1000)
    while len(selected) < quota and attempts < max_attempts:
        attempts += 1
        index = int(rng.choice(len(pool), p=probabilities))
        candidate = pool[index]
        source = str(candidate["source_video"])
        signature = str(candidate["effective_frame_signature"])
        if source_counts[source] >= SOURCE_COUNT_CAP:
            rejections["source_cap"] += 1
            continue
        if signature_counts[signature] >= SIGNATURE_COUNT_CAP:
            rejections["signature_cap"] += 1
            continue
        selected.append(candidate)
        source_counts[source] += 1
        signature_counts[signature] += 1
    if len(selected) != quota:
        raise SourceAware3kError(
            f"固定配额无法生成: requested={quota}, selected={len(selected)}, "
            f"attempts={attempts}, rejections={dict(rejections)}"
        )
    return selected, {"attempts": attempts, **dict(sorted(rejections.items()))}


def _seed_plan(
    candidates: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, Any]:
    ordered = sorted(candidates, key=lambda item: str(item["candidate_id"]))
    negatives = [
        item for item in ordered if item["labels"]["clip_state"] == "未断裂"
    ]
    others = [
        item for item in ordered if item["labels"]["clip_state"] != "未断裂"
    ]
    if not negatives or not others:
        raise SourceAware3kError("fold0 train 必须同时包含未断裂和其他状态")
    negative_capacity = _pool_capacity(negatives)
    other_capacity = _pool_capacity(others)
    total_source_capacity = len({str(item["source_video"]) for item in ordered}) * (
        SOURCE_COUNT_CAP
    )
    if (
        negative_capacity < HARD_NEGATIVES_PER_EPOCH
        or other_capacity < OTHER_ROWS_PER_EPOCH
        or total_source_capacity < ROWS_PER_EPOCH
    ):
        raise SourceAware3kError(
            "固定 source/signature 上限容量不足: "
            f"negative={negative_capacity}, other={other_capacity}, "
            f"total_source={total_source_capacity}"
        )

    weights = _state_weights(others)
    negative_probabilities = np.full(len(negatives), 1.0 / len(negatives))
    other_values = np.array(
        [weights[str(item["labels"]["clip_state"])] for item in others],
        dtype=np.float64,
    )
    other_probabilities = other_values / other_values.sum()
    rng = np.random.Generator(np.random.PCG64(seed))
    source_counts: Counter[str] = Counter()
    signature_counts: Counter[str] = Counter()
    negative_selected, negative_rejections = _draw_quota(
        rng=rng,
        pool=negatives,
        probabilities=negative_probabilities,
        quota=HARD_NEGATIVES_PER_EPOCH,
        source_counts=source_counts,
        signature_counts=signature_counts,
    )
    other_selected, other_rejections = _draw_quota(
        rng=rng,
        pool=others,
        probabilities=other_probabilities,
        quota=OTHER_ROWS_PER_EPOCH,
        source_counts=source_counts,
        signature_counts=signature_counts,
    )
    selected = negative_selected + other_selected
    permutation = rng.permutation(len(selected))
    sequence = [selected[int(index)] for index in permutation]
    candidate_counts = Counter(str(item["candidate_id"]) for item in sequence)
    state_counts = Counter(str(item["labels"]["clip_state"]) for item in sequence)
    if (
        len(sequence) != ROWS_PER_EPOCH
        or state_counts["未断裂"] != HARD_NEGATIVES_PER_EPOCH
        or max(source_counts.values()) > SOURCE_COUNT_CAP
        or max(signature_counts.values()) > SIGNATURE_COUNT_CAP
    ):
        raise SourceAware3kError("生成后的 3k 清单违反固定配额或上限")
    return {
        "seed": seed,
        "rng": "numpy.random.PCG64",
        "candidate_sort": "candidate_id_ascending",
        "sampling": "with_replacement",
        "rows_per_epoch": ROWS_PER_EPOCH,
        "epochs": EPOCHS,
        "total_exposures": ROWS_PER_EPOCH * EPOCHS,
        "hard_negative_count": state_counts["未断裂"],
        "other_state_count": len(sequence) - state_counts["未断裂"],
        "state_frequencies_before_sampling": dict(
            sorted(
                Counter(
                    str(item["labels"]["clip_state"]) for item in ordered
                ).items()
            )
        ),
        "other_state_weights": weights,
        "state_counts": dict(sorted(state_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "candidate_repeat_counts": dict(sorted(candidate_counts.items())),
        "signature_repeat_counts": dict(sorted(signature_counts.items())),
        "max_source_count": max(source_counts.values()),
        "max_source_share": max(source_counts.values()) / ROWS_PER_EPOCH,
        "max_signature_count": max(signature_counts.values()),
        "capacity": {
            "negative": negative_capacity,
            "other": other_capacity,
            "total_source": total_source_capacity,
        },
        "draw_diagnostics": {
            "hard_negative": negative_rejections,
            "other_states": other_rejections,
        },
        "candidate_sequence": [str(item["candidate_id"]) for item in sequence],
    }


def _dataset_registry(seeds: Sequence[int]) -> dict[str, Any]:
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
    registry = {
        f"tensile_v4_1_phase2_3k_seed{seed}": {
            **common,
            "file_name": f"datasets/seed_{seed}.json",
        }
        for seed in seeds
    }
    registry["tensile_v4_1_phase2_fold0_val"] = {
        **common,
        "file_name": "datasets/fold_0_validation.json",
    }
    return registry


def _write_immutable_directory(
    target: Path,
    *,
    files: Mapping[str, bytes],
    summary: Mapping[str, Any],
) -> None:
    if target.exists():
        existing = _read_json(target / "summary.json", "existing sampling summary")
        if existing != summary:
            raise SourceAware3kError(f"拒绝覆盖已有 sampling artifact: {target}")
        for relative, content in files.items():
            path = target / relative
            if not path.is_file() or path.read_bytes() != content:
                raise SourceAware3kError(f"已有 sampling 文件漂移: {path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for relative, content in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (staging / "summary.json").write_bytes(_pretty_bytes(summary))
        os.replace(staging, target)
    finally:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()


def build_source_aware_3k(
    *,
    release_dir: Path,
    media_root: Path,
    output_root: Path,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    verify_media: bool = False,
    validate_only: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Validate and optionally freeze both fixed-seed 3k sampling artifacts."""
    normalized_seeds = tuple(int(seed) for seed in seeds)
    if (
        not normalized_seeds
        or len(normalized_seeds) != len(set(normalized_seeds))
        or any(seed < 0 for seed in normalized_seeds)
    ):
        raise SourceAware3kError("seeds 必须是唯一非负整数")
    (
        release_manifest,
        candidates,
        row_index,
        validation_rows,
        validation_bytes,
        identities,
    ) = _release_inputs(
        release_dir,
        media_root=media_root,
        verify_media=verify_media,
    )
    plans = [_seed_plan(candidates, seed=seed) for seed in normalized_seeds]
    sampling_manifest = {
        "schema_version": SAMPLING_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "release_id": release_manifest["release_id"],
        "contract_hash": release_manifest["contract_hash"],
        "policy": {
            "rows_per_epoch": ROWS_PER_EPOCH,
            "epochs": EPOCHS,
            "hard_negatives_per_epoch": HARD_NEGATIVES_PER_EPOCH,
            "other_rows_per_epoch": OTHER_ROWS_PER_EPOCH,
            "other_state_weight_formula": (
                "clip((1/sqrt(state_frequency))/candidate_weighted_mean,0.5,3.0)"
            ),
            "source_share_cap": SOURCE_SHARE_CAP,
            "source_count_cap": SOURCE_COUNT_CAP,
            "signature_count_cap": SIGNATURE_COUNT_CAP,
        },
        "inputs": identities,
        "seeds": list(normalized_seeds),
        "plans": plans,
    }
    seed = {
        "policy_version": POLICY_VERSION,
        "release_id": release_manifest["release_id"],
        "inputs": identities,
        "seeds": list(normalized_seeds),
        "candidate_sequences": [
            {
                "seed": plan["seed"],
                "sequence": plan["candidate_sequence"],
            }
            for plan in plans
        ],
    }
    sampling_id = f"source-aware-3k-{_sha256_bytes(_canonical_bytes(seed))[:12]}"
    sampling_manifest["sampling_id"] = sampling_id
    candidates_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in candidates
    }
    files: dict[str, bytes] = {
        "sampling_manifest.json": _pretty_bytes(sampling_manifest),
        "dataset_info.json": _pretty_bytes(_dataset_registry(normalized_seeds)),
        "datasets/fold_0_validation.json": validation_bytes,
    }
    for plan in plans:
        dataset = [
            row_index[candidates_by_id[candidate_id]["video_path"]]
            for candidate_id in plan["candidate_sequence"]
        ]
        files[f"datasets/seed_{plan['seed']}.json"] = _pretty_bytes(dataset)
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
        "sampling_id": sampling_id,
        "status": "ready",
        "immutable": True,
        "release_id": release_manifest["release_id"],
        "release_manifest_sha256": identities["release_manifest_sha256"],
        "seeds": list(normalized_seeds),
        "rows_per_epoch": ROWS_PER_EPOCH,
        "epochs": EPOCHS,
        "total_exposures_per_seed": ROWS_PER_EPOCH * EPOCHS,
        "expected_optimizer_steps_per_seed": math.ceil(
            ROWS_PER_EPOCH / 8
        )
        * EPOCHS,
        "fold0_train_candidate_count": len(candidates),
        "fold0_validation_count": len(validation_rows),
        "plans": [
            {
                "seed": plan["seed"],
                "state_counts": plan["state_counts"],
                "max_source_count": plan["max_source_count"],
                "max_source_share": plan["max_source_share"],
                "max_signature_count": plan["max_signature_count"],
                "sequence_sha256": _sha256_bytes(
                    _canonical_bytes(plan["candidate_sequence"])
                ),
            }
            for plan in plans
        ],
        "files": file_manifest,
    }
    output_dir = Path(output_root) / sampling_id
    if not validate_only:
        _write_immutable_directory(output_dir, files=files, summary=summary)
    elif output_dir.exists():
        _write_immutable_directory(output_dir, files=files, summary=summary)
    return output_dir, summary
