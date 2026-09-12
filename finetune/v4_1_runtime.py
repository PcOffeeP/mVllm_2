"""V4.1 finetuning release, config, and output validation helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from pipeline.current_data import current_data_paths
from pipeline.data_roots import resolve_workspace_artifact
from pipeline.v4_1_labels import V4_1_LABEL_FIELDS, canonicalize_v4_1_labels
from pipeline.v4_1_training_release import (
    canonical_release_identity_bytes,
)

CONTRACT_VERSION = "tensile-vlm/v4.1"


class V4_1FinetuneError(ValueError):
    """Raised when V4.1 training inputs or configs drift."""


def _load_active_release_id() -> str:
    pointer_path = Path(__file__).with_name("active_data_release.json")
    try:
        data = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V4_1FinetuneError(
            f"无法读取 release pointer {pointer_path}: {exc}"
        ) from exc
    release_id = data.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise V4_1FinetuneError(
            f"release pointer {pointer_path} 缺少有效 release_id"
        )
    return release_id


def __getattr__(name: str):
    # Only legacy callers requesting the active identity read its pointer.
    if name == "RELEASE_ID":
        return _load_active_release_id()
    raise AttributeError(name)
RELEASE_SCHEMA_VERSION = "tensile-training-release/v4.1"
RELEASE_SCHEMA_VERSION_V2 = "tensile-training-release/v4.1-v2"


def _load_active_release_pointer(project_root: Path | None = None) -> dict[str, Any]:
    """Load the git-tracked release pointer and verify the pinned trust anchor.

    The pointer carries the expected_contract_hash that was frozen when the
    release was promoted. It must be present and complete; a missing field is
    treated as a configuration error and fails closed.
    """
    project_root = (
        project_root
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    ).resolve()
    pointer_path = project_root / "finetune/active_data_release.json"
    try:
        pointer = _read_json(pointer_path)
    except V4_1FinetuneError as exc:
        raise V4_1FinetuneError(
            f"无法读取 release pointer {pointer_path}: {exc}"
        ) from exc
    if not isinstance(pointer, dict):
        raise V4_1FinetuneError(f"release pointer {pointer_path} 必须是对象")
    expected_contract_hash = pointer.get("expected_contract_hash")
    if (
        not isinstance(expected_contract_hash, str)
        or len(expected_contract_hash) != 64
    ):
        raise V4_1FinetuneError(
            f"release pointer {pointer_path} 缺少有效 expected_contract_hash 字段；"
            "请在 release_build 后补全该钉扎值，否则无法防御 manifest 自证化篡改"
        )
    expected_manifest_sha256 = pointer.get("expected_manifest_sha256")
    if (
        not isinstance(expected_manifest_sha256, str)
        or len(expected_manifest_sha256) != 64
    ):
        raise V4_1FinetuneError(
            f"release pointer {pointer_path} 缺少有效 expected_manifest_sha256 字段；"
            "请在 release_build 后从对应 release_summary.json 的 "
            "release_manifest_sha256 字段回填，否则无法防御 manifest 自证化篡改"
        )
    return pointer


def load_release_expectations(
    project_root: Path | str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Load the frozen contract_hash and counts from a release manifest.

    Reads from workspace/data/releases/<release_id>/manifest/release_manifest.json
    and verifies the manifest's contract_hash against the pinned value stored in
    finetune/active_data_release.json. Raises V4_1FinetuneError when the pointer
    is incomplete or when the manifest has drifted (e.g. through tampering).
    """
    resolved_release_id = release_id or _load_active_release_id()
    project_root = Path(
        project_root
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    ).resolve()
    pointer = _load_active_release_pointer(project_root)
    expected_contract_hash = pointer["expected_contract_hash"]
    expected_manifest_sha256 = pointer["expected_manifest_sha256"]
    manifest_path = (
        release_dir(project_root, resolved_release_id)
        / "manifest/release_manifest.json"
    )
    if not manifest_path.is_file():
        raise V4_1FinetuneError(
            f"release manifest 缺失: {manifest_path}；"
            "评测/验证必须在挂载 workspace 的训练机上执行"
        )
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise V4_1FinetuneError(
            f"无法读取 release manifest {manifest_path}；"
            "评测/验证必须在挂载 workspace 的训练机上执行"
        ) from exc
    actual_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise V4_1FinetuneError(
            f"release manifest sha256 漂移: "
            f"pointer={expected_manifest_sha256!r}, actual={actual_manifest_sha256!r}"
        )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V4_1FinetuneError(f"无法读取 JSON {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise V4_1FinetuneError("release manifest 必须是对象")
    contract_hash = manifest.get("contract_hash")
    if not isinstance(contract_hash, str) or len(contract_hash) != 64:
        raise V4_1FinetuneError("release manifest contract_hash 无效")
    if contract_hash != expected_contract_hash:
        raise V4_1FinetuneError(
            f"release manifest contract_hash 漂移: "
            f"pointer={expected_contract_hash!r}, actual={contract_hash!r}"
        )
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise V4_1FinetuneError("release manifest counts 缺失")
    return {
        "contract_hash": expected_contract_hash,
        "counts": counts,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V4_1FinetuneError(f"无法读取 JSON {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_dir(project_root: Path, release_id: str | None = None) -> Path:
    return current_data_paths(project_root).training_releases / (release_id or _load_active_release_id())


def _validate_v2_snapshot_binding(manifest: Mapping[str, Any]) -> None:
    source_snapshot_id = manifest.get("source_snapshot_id")
    split_snapshot_id = manifest.get("split_snapshot_id")
    provenance = manifest.get("provenance")
    if (
        not isinstance(source_snapshot_id, str)
        or not source_snapshot_id.startswith("source-snapshot-")
        or not isinstance(split_snapshot_id, str)
        or not split_snapshot_id.startswith("split-snapshot-")
        or not isinstance(provenance, Mapping)
        or provenance.get("release_schema_version")
        != RELEASE_SCHEMA_VERSION_V2
        or provenance.get("source_snapshot_id") != source_snapshot_id
        or provenance.get("split_snapshot_id") != split_snapshot_id
    ):
        raise V4_1FinetuneError(
            "release v2 缺少有效 source/split snapshot binding"
        )
    for field in (
        "source_snapshot_tree_sha256",
        "split_snapshot_tree_sha256",
        "source_snapshot_manifest_sha256",
        "split_snapshot_manifest_sha256",
    ):
        value = provenance.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise V4_1FinetuneError(
                f"release v2 provenance {field} 无效"
            )
    data_version = provenance.get("data_version")
    if not isinstance(data_version, str) or not data_version:
        raise V4_1FinetuneError("release v2 provenance data_version 无效")
    canonical_seed = canonical_release_identity_bytes(dict(provenance))
    expected_release_id = (
        f"v{data_version}-{hashlib.sha256(canonical_seed).hexdigest()[:12]}"
    )
    if manifest.get("release_id") != expected_release_id:
        raise V4_1FinetuneError("release v2 canonical identity 漂移")


def validate_release(
    project_root: Path,
    *,
    verify_media: bool = False,
    release_id: str | None = None,
    expected_counts: Mapping[str, int] | None = None,
    expected_contract_hash: str | None = None,
    expected_schema_version: str | None = None,
) -> dict[str, Any]:
    """Validate immutable release files, rows, labels, splits, and optional media.

    If both ``expected_counts`` and ``expected_contract_hash`` are supplied by
    the caller, the pointer pinning check is skipped entirely. This
    short-circuit is intended for tests and should not be used in production.
    """
    project_root = Path(project_root).resolve()
    resolved_release_id = release_id or _load_active_release_id()
    resolved_schema_version = expected_schema_version or RELEASE_SCHEMA_VERSION
    if expected_contract_hash is None or expected_counts is None:
        expectations = load_release_expectations(
            project_root, resolved_release_id
        )
        if expected_contract_hash is None:
            expected_contract_hash = expectations["contract_hash"]
        if expected_counts is None:
            expected_counts = expectations["counts"]
    media_root = current_data_paths(project_root).root
    root = release_dir(project_root, resolved_release_id)
    manifest_path = root / "manifest/release_manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise V4_1FinetuneError("release manifest 必须是对象")
    expected_identity = {
        "schema_version": resolved_schema_version,
        "release_id": resolved_release_id,
        "status": "training_ready",
        "immutable": True,
        "contract_version": CONTRACT_VERSION,
        "contract_hash": expected_contract_hash,
        "label_semantics": "frame_window_authoritative",
    }
    for field, expected in expected_identity.items():
        if manifest.get(field) != expected:
            raise V4_1FinetuneError(
                f"release manifest {field} 漂移: "
                f"expected={expected!r}, actual={manifest.get(field)!r}"
            )
    if resolved_schema_version == RELEASE_SCHEMA_VERSION_V2:
        _validate_v2_snapshot_binding(manifest)
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        raise V4_1FinetuneError("release manifest counts 缺失")
    required_counts = dict(expected_counts or {})
    for field, expected in required_counts.items():
        if counts.get(field) != expected:
            raise V4_1FinetuneError(
                f"release count {field} 漂移: expected={expected}, actual={counts.get(field)}"
            )

    files = manifest.get("files")
    if not isinstance(files, list):
        raise V4_1FinetuneError("release manifest files 必须是列表")
    required_paths = {
        "dataset_info.json",
        "metadata/training_candidates.json",
        "reports/quality_report.json",
        *(
            f"datasets/{directory}/fold_{fold}.json"
            for fold in range(3)
            for directory in ("train", "validation")
        ),
    }
    manifested_paths = {
        item.get("path") for item in files if isinstance(item, Mapping)
    }
    if (
        len(manifested_paths) != len(files)
        or not required_paths <= manifested_paths
    ):
        raise V4_1FinetuneError("release manifest files 缺少受管文件或包含重复路径")
    for item in files:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise V4_1FinetuneError("release file manifest 非法")
        path = root / item["path"]
        if (
            not path.is_file()
            or path.stat().st_size != item.get("size_bytes")
            or _sha256(path) != item.get("sha256")
        ):
            raise V4_1FinetuneError(f"release 文件缺失或漂移: {path}")

    registry = _read_json(root / "dataset_info.json")
    expected_names = {
        f"tensile_v4_1_fold{fold}_{split}"
        for fold in range(3)
        for split in ("train", "val")
    }
    if not isinstance(registry, dict) or set(registry) != expected_names:
        raise V4_1FinetuneError("V4.1 dataset registry 名称不完整")

    all_fold_counts: dict[str, int] = {}
    for fold in range(3):
        seen_videos: set[str] = set()
        for split, directory in (("train", "train"), ("val", "validation")):
            name = f"fold_{fold}_{split}"
            rows = _read_json(root / f"datasets/{directory}/fold_{fold}.json")
            if not isinstance(rows, list) or not rows:
                raise V4_1FinetuneError(f"{name}: 数据集为空或不是列表")
            all_fold_counts[name] = len(rows)
            for index, row in enumerate(rows):
                video_path, labels = validate_training_row(row, name, index)
                if video_path in seen_videos:
                    raise V4_1FinetuneError(
                        f"fold_{fold}: train/val 重复候选媒体: {video_path}"
                    )
                seen_videos.add(video_path)
                media_path = resolve_workspace_artifact(video_path, media_root)
                if verify_media and not media_path.is_file():
                    raise V4_1FinetuneError(f"训练媒体不存在: {media_path}")
                canonicalize_v4_1_labels(labels)
        published_count = counts.get("published_candidates")
        if not isinstance(published_count, int) or published_count <= 0:
            raise V4_1FinetuneError("release published_candidates 非法")
        if len(seen_videos) != published_count:
            raise V4_1FinetuneError(
                f"fold_{fold}: train+val 应覆盖 {published_count} 条，"
                f"实际 {len(seen_videos)}"
            )
    if all_fold_counts != dict(counts.get("splits") or {}):
        raise V4_1FinetuneError("数据文件行数与 release manifest splits 不一致")
    return {
        "release_id": resolved_release_id,
        "contract_version": CONTRACT_VERSION,
        "contract_hash": expected_contract_hash,
        "release_dir": str(root),
        "media_verified": verify_media,
        "split_counts": all_fold_counts,
    }


def validate_training_row(
    row: Any,
    split_name: str = "dataset",
    index: int = 0,
) -> tuple[str, dict[str, Any]]:
    if not isinstance(row, Mapping) or set(row) != {"videos", "messages"}:
        raise V4_1FinetuneError(f"{split_name}[{index}]: 训练行字段非法")
    videos = row.get("videos")
    messages = row.get("messages")
    if (
        not isinstance(videos, list)
        or len(videos) != 1
        or not isinstance(videos[0], str)
        or not videos[0]
    ):
        raise V4_1FinetuneError(f"{split_name}[{index}]: videos 必须只有一个路径")
    if not isinstance(messages, list) or [item.get("role") for item in messages] != [
        "system",
        "user",
        "assistant",
    ]:
        raise V4_1FinetuneError(f"{split_name}[{index}]: messages 角色顺序非法")
    if not str(messages[1].get("content") or "").startswith("<video>\n"):
        raise V4_1FinetuneError(f"{split_name}[{index}]: user prompt 缺少 <video>")
    raw_target = messages[2].get("content")
    try:
        target = json.loads(raw_target)
    except (TypeError, json.JSONDecodeError) as exc:
        raise V4_1FinetuneError(
            f"{split_name}[{index}]: assistant target 不是合法 JSON"
        ) from exc
    labels = canonicalize_v4_1_labels(target)
    if list(target) != list(V4_1_LABEL_FIELDS):
        raise V4_1FinetuneError(f"{split_name}[{index}]: target 字段顺序漂移")
    return videos[0], labels


def validate_training_config(
    config_path: Path,
    *,
    fold: int,
    project_root: Path,
) -> dict[str, Any]:
    try:
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise V4_1FinetuneError(f"无法读取训练配置 {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise V4_1FinetuneError(f"训练配置不是对象: {config_path}")
    expected = {
        "dataset": f"tensile_v4_1_fold{fold}_train",
        "eval_dataset": f"tensile_v4_1_fold{fold}_val",
        "video_maxlen": 8,
        "stage": "sft",
        "finetuning_type": "lora",
        "do_train": True,
        "do_eval": True,
        "overwrite_output_dir": False,
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise V4_1FinetuneError(
                f"{config_path.name}: {field} 应为 {value!r}，实际 {config.get(field)!r}"
            )
    configured_dataset_dir = (
        Path(project_root) / "finetune" / str(config.get("dataset_dir"))
    ).resolve()
    expected_dataset_dir = release_dir(project_root).resolve()
    if configured_dataset_dir != expected_dataset_dir:
        raise V4_1FinetuneError(
            f"{config_path.name}: dataset_dir 未绑定 {_load_active_release_id()}"
        )
    configured_media_dir = (
        Path(project_root) / "finetune" / str(config.get("media_dir"))
    ).resolve()
    expected_media_dir = current_data_paths(project_root).root.resolve()
    if configured_media_dir != expected_media_dir:
        raise V4_1FinetuneError(
            f"{config_path.name}: media_dir 未绑定当前语义化数据 workspace"
        )
    output_dir = str(config.get("output_dir") or "")
    if _load_active_release_id().replace(".", "_").replace("-", "_") not in output_dir:
        raise V4_1FinetuneError(
            f"{config_path.name}: output_dir 未包含 V4.1 发布身份"
        )
    return config


def parse_v4_1_output(raw_output: str) -> dict[str, Any]:
    """Parse a strict four-field model response without legacy V2 repairs."""
    try:
        value = json.loads(str(raw_output).strip())
    except json.JSONDecodeError as exc:
        raise V4_1FinetuneError(f"模型输出不是合法 JSON: {exc.msg}") from exc
    try:
        return canonicalize_v4_1_labels(value)
    except (TypeError, ValueError) as exc:
        raise V4_1FinetuneError(f"模型输出不符合 V4.1: {exc}") from exc


def score_v4_1_prediction(
    target: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    target_labels = canonicalize_v4_1_labels(target)
    prediction_labels = (
        canonicalize_v4_1_labels(prediction) if prediction is not None else None
    )
    result: dict[str, Any] = {
        "contract_valid": prediction_labels is not None,
        "joint_correct": prediction_labels == target_labels,
    }
    for field in V4_1_LABEL_FIELDS:
        result[f"{field}_correct"] = (
            prediction_labels is not None
            and prediction_labels[field] == target_labels[field]
        )
    return result


def summarize_v4_1_scores(scores: list[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(scores)
    fields = [
        "contract_valid",
        "joint_correct",
        *(f"{field}_correct" for field in V4_1_LABEL_FIELDS),
    ]
    counts = Counter(
        field for score in scores for field in fields if score.get(field) is True
    )
    return {
        "total": total,
        **{
            f"{field}_rate": round(counts[field] / total, 6) if total else None
            for field in fields
        },
    }
