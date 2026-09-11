"""DVC 数据 pipeline 七阶段最小实现。

对应设计 §2.4（七阶段主干 / 人工审查显式关卡）、§2.5（DVC 只管理数据 pipeline）、
D035（自动发现、手动执行；release_validate 只报告不启动训练）。
"""

from __future__ import annotations

import hashlib
import csv
import fcntl
import io
import math
import tempfile
import json
import os
import re
import stat
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from versioning.data_release import (
    DataReleaseError,
    ReleaseConflict,
    _extract_version_protocol,
    assert_payload_sealed,
    load_release_metadata,
    seal_release,
    stage_release,
    validate_training_reference,
)
from versioning.ids import InvalidIdentifier, parse_data_id

STAGES: tuple[str, ...] = (
    "source",
    "roi",
    "subvideo",
    "review_export",
    "review_import",
    "release",
    "release_validate",
)

_STAGES_SET = set(STAGES)

VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".webm")

REVIEW_VALID_VERDICTS = {"accept", "reject"}


class DataPipelineError(ValueError):
    """pipeline 域异常基类。"""


class UnknownStageError(DataPipelineError):
    """非法 stage 名（fail-closed）。"""


class StageInputError(DataPipelineError):
    """缺上游产物或输入为空。"""


class ReviewGateError(DataPipelineError):
    """审查未回收、格式错或结论不通过。"""


@dataclass(frozen=True)
class StageResult:
    """单个阶段的执行结果。"""

    stage: str
    outputs: tuple[Path, ...]
    report: Mapping[str, Any]


def _data_root(root: Path) -> Path:
    return root / "data"


def _working_dir(root: Path, batch: str) -> Path:
    return _data_root(root) / "working" / batch


def _raw_dir(root: Path, batch: str) -> Path:
    return _data_root(root) / "raw" / batch


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _sorted_video_files(directory: Path) -> list[Path]:
    return sorted(
        [p for p in directory.iterdir() if p.is_file()],
        key=lambda p: p.name,
    )


def _derive_roi(name: str) -> dict[str, int]:
    """由视频名确定性推导非负整数 ROI。"""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return {
        "x": int(digest[0:8], 16),
        "y": int(digest[8:16], 16),
        "width": int(digest[16:24], 16),
        "height": int(digest[24:32], 16),
    }


def _clip_id(source: str, index: int) -> str:
    """确定性生成全局唯一 clip_id。"""
    return f"{source}__clip-{index}"


def _accepted_clips(review_decisions: Mapping[str, Any]) -> list[str]:
    return sorted(review_decisions.get("accepted", []))


def run_source(root: Path, *, batch: str = "batch-001") -> StageResult:
    """整理原始文件并写入 source_manifest.json。"""
    raw = _raw_dir(root, batch)
    if not raw.is_dir():
        raise StageInputError(f"raw 目录不存在: {raw}")

    files = _sorted_video_files(raw)
    if not files:
        raise StageInputError(f"raw 目录为空: {raw}")

    working = _working_dir(root, batch)
    source_dir = working / "source"
    media_dir = source_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    for source_file in files:
        target = media_dir / source_file.name
        target.write_bytes(source_file.read_bytes())
        manifest_files.append(
            {
                "name": source_file.name,
                "size": source_file.stat().st_size,
                "sha256": _sha256_file(source_file),
            }
        )

    manifest = {"batch": batch, "files": manifest_files}
    manifest_path = source_dir / "source_manifest.json"
    _write_json(manifest_path, manifest)

    outputs = (source_dir, manifest_path)
    report = {"batch": batch, "file_count": len(manifest_files)}
    return StageResult(stage="source", outputs=outputs, report=report)


def run_roi(root: Path, *, batch: str = "batch-001") -> StageResult:
    """为每个 source 视频生成确定性 ROI manifest。"""
    source_manifest_path = _working_dir(root, batch) / "source" / "source_manifest.json"
    if not source_manifest_path.is_file():
        raise StageInputError(f"source manifest 缺失: {source_manifest_path}")

    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    videos = []
    for entry in sorted(manifest["files"], key=lambda e: e["name"]):
        videos.append(
            {
                "name": entry["name"],
                "roi": _derive_roi(entry["name"]),
                # 上游内容 digest：raw 内容变化时 roi manifest 随之变化，
                # 使 DVC out-hash 沿链传播（Spec A）。
                "sha256": entry["sha256"],
            }
        )

    roi_dir = _working_dir(root, batch) / "roi"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_manifest_path = roi_dir / "roi_manifest.json"
    _write_json(roi_manifest_path, {"videos": videos})

    outputs = (roi_dir, roi_manifest_path)
    report = {"batch": batch, "video_count": len(videos)}
    return StageResult(stage="roi", outputs=outputs, report=report)


def run_subvideo(root: Path, *, batch: str = "batch-001") -> StageResult:
    """每视频生成 2 条确定性子视频记录。"""
    roi_manifest_path = _working_dir(root, batch) / "roi" / "roi_manifest.json"
    if not roi_manifest_path.is_file():
        raise StageInputError(f"roi manifest 缺失: {roi_manifest_path}")

    roi_manifest = json.loads(roi_manifest_path.read_text(encoding="utf-8"))
    clips = []
    for video in sorted(roi_manifest["videos"], key=lambda v: v["name"]):
        for index in (0, 1):
            clips.append(
                {
                    "clip_id": _clip_id(video["name"], index),
                    "source": video["name"],
                    "index": index,
                }
            )

    subvideo_dir = _working_dir(root, batch) / "subvideo"
    subvideo_dir.mkdir(parents=True, exist_ok=True)
    subvideo_manifest_path = subvideo_dir / "subvideo_manifest.json"
    # 顶层记录上游 roi manifest 文件内容 digest：roi 变化时本 manifest 随之变化。
    _write_json(
        subvideo_manifest_path,
        {
            "roi_manifest_sha256": _sha256_file(roi_manifest_path),
            "clips": clips,
        },
    )

    outputs = (subvideo_dir, subvideo_manifest_path)
    report = {"batch": batch, "clip_count": len(clips)}
    return StageResult(stage="subvideo", outputs=outputs, report=report)


def run_review_export(root: Path, *, batch: str = "batch-001") -> StageResult:
    """导出审查包 items.jsonl，覆盖全部 clip。"""
    subvideo_manifest_path = (
        _working_dir(root, batch) / "subvideo" / "subvideo_manifest.json"
    )
    if not subvideo_manifest_path.is_file():
        raise StageInputError(f"subvideo manifest 缺失: {subvideo_manifest_path}")

    subvideo_manifest = json.loads(subvideo_manifest_path.read_text(encoding="utf-8"))
    review_dir = _working_dir(root, batch) / "review" / "review_package"
    review_dir.mkdir(parents=True, exist_ok=True)
    items_path = review_dir / "items.jsonl"

    # 每行携带 subvideo manifest digest：上游变化时包目录 out-hash 随之变化。
    subvideo_sha256 = _sha256_file(subvideo_manifest_path)
    lines = []
    for clip in sorted(subvideo_manifest["clips"], key=lambda c: c["clip_id"]):
        lines.append(
            json.dumps(
                {"clip_id": clip["clip_id"], "content_sha256": subvideo_sha256},
                ensure_ascii=False,
            )
        )
    items_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    outputs = (review_dir, items_path)
    report = {
        "batch": batch,
        "item_count": len(lines),
        "content_sha256": subvideo_sha256,
    }
    return StageResult(stage="review_export", outputs=outputs, report=report)


def _load_review_results(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReviewGateError(f"无法读取审查结果: {exc}") from exc
    return raw if isinstance(raw, dict) else {}


def run_review_import(
    root: Path,
    *,
    batch: str = "batch-001",
    results_path: Path | None = None,
) -> StageResult:
    """回收并校验人工审查结果，通过则写入 review_decisions.json。"""
    if results_path is None:
        results_path = _data_root(root) / "review_results" / f"{batch}.yaml"

    raw = _load_review_results(results_path)

    if not isinstance(raw, dict):
        raise ReviewGateError("审查结果 YAML 顶层必须是映射")

    for key in ("batch", "approved", "decisions", "content_sha256"):
        if key not in raw:
            raise ReviewGateError(f"审查结果缺少必填键: {key}")

    if raw["batch"] != batch:
        raise ReviewGateError(
            f"审查结果 batch 不一致: {raw['batch']!r} != {batch!r}"
        )

    approved = raw["approved"]
    if not isinstance(approved, bool):
        raise ReviewGateError("approved 必须是布尔值")

    content_sha256 = raw["content_sha256"]
    if (
        not isinstance(content_sha256, str)
        or len(content_sha256) != 64
    ):
        raise ReviewGateError("content_sha256 必须是 64 位十六进制摘要")
    try:
        int(content_sha256, 16)
    except ValueError as exc:
        raise ReviewGateError("content_sha256 必须是 64 位十六进制摘要") from exc

    subvideo_manifest_path = (
        _working_dir(root, batch) / "subvideo" / "subvideo_manifest.json"
    )
    current_digest = _sha256_file(subvideo_manifest_path)
    if content_sha256 != current_digest:
        raise ReviewGateError(
            "审查结果 content_sha256 与当前 subvideo manifest 内容哈希不一致"
        )

    decisions = raw["decisions"]
    if not isinstance(decisions, list):
        raise ReviewGateError("decisions 必须是列表")

    expected_clip_ids = set(_clip_ids(root, batch))
    seen_clip_ids: set[str] = set()
    accepted: list[str] = []
    rejected: list[str] = []

    for item in decisions:
        if not isinstance(item, dict):
            raise ReviewGateError("decisions 每项必须是映射")
        clip_id = item.get("clip_id")
        verdict = item.get("verdict")
        if clip_id is None or verdict is None:
            raise ReviewGateError("decisions 每项必须含 clip_id 与 verdict")
        if verdict not in REVIEW_VALID_VERDICTS:
            raise ReviewGateError(f"非法 verdict: {verdict!r}")
        if clip_id in seen_clip_ids:
            raise ReviewGateError(f"decisions 中 clip_id 重复: {clip_id!r}")
        seen_clip_ids.add(clip_id)
        if verdict == "accept":
            accepted.append(clip_id)
        else:
            rejected.append(clip_id)

    if seen_clip_ids != expected_clip_ids:
        raise ReviewGateError(
            "decisions 的 clip_id 集合与导出 clip 集合不一致"
        )

    if not approved:
        raise ReviewGateError("审查结论为不通过")

    review_dir = _working_dir(root, batch) / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = review_dir / "review_decisions.json"
    # 记录本次审查通过绑定的内容 digest（Finding 1）：供 release 复核
    # 审查结论是否仍针对当前内容。
    _write_json(
        decisions_path,
        {
            "batch": batch,
            "accepted": sorted(accepted),
            "rejected": sorted(rejected),
            "content_sha256": current_digest,
        },
    )

    outputs = (decisions_path,)
    report = {
        "batch": batch,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }
    return StageResult(stage="review_import", outputs=outputs, report=report)


def _clip_ids(root: Path, batch: str) -> list[str]:
    manifest = json.loads(
        (
            _working_dir(root, batch) / "subvideo" / "subvideo_manifest.json"
        ).read_text(encoding="utf-8")
    )
    return [clip["clip_id"] for clip in manifest["clips"]]


def _restore_write_bits(path: Path) -> None:
    """递归恢复 owner 写位（仅用于封存目录的临时操作窗口）。"""
    path.chmod(path.stat().st_mode | 0o200)
    if path.is_dir():
        for child in path.iterdir():
            _restore_write_bits(child)


def _strip_write_bits(path: Path) -> None:
    """递归去除全部写位。"""
    path.chmod(path.stat().st_mode & ~0o222)
    if path.is_dir():
        for child in path.iterdir():
            _strip_write_bits(child)


def _dvc_add_payload(root: Path, release_dir: Path, version: str) -> Path:
    """DVC 仓库内对版本 payload 子目录执行 dvc add（Finding 3）。

    封存后的 payload 与版本根目录只读，dvc add 需要临时恢复写位
    （移动文件进 cache、在版本根下创建 payload.dvc），完成后重新封存。
    """
    payload_dir = release_dir / "payload"
    _restore_write_bits(payload_dir)
    release_dir.chmod(release_dir.stat().st_mode | 0o200)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "dvc",
                "add",
                f"data/releases/{version}/payload",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            env={**os.environ, "DVC_NO_ANALYTICS": "1"},
        )
    finally:
        # 无论 add 成败都先恢复封存（read-only）
        for child in release_dir.iterdir():
            if child.name in ("release.yaml", "README.md", "authorization"):
                continue
            _strip_write_bits(child)
        release_dir.chmod(release_dir.stat().st_mode & ~0o222)
    if completed.returncode != 0:
        raise DataPipelineError(
            f"dvc add payload 失败: {completed.stderr.strip()}"
        )
    return release_dir / "payload.dvc"


def run_release(
    root: Path,
    *,
    batch: str = "batch-001",
    version: str | None = None,
    protocol: str = "v4.1",
    purpose: str = "development",
    description: str | None = None,
) -> StageResult:
    """组装 accepted payload 并封存为正式数据版本。"""
    # 显式版本纪律（§9/§11.6）：目标版本必须由调用方显式给出。
    if version is None:
        raise ReviewGateError("未显式指定目标版本，无法 release")

    parsed_version = parse_data_id(version)
    full_id = str(parsed_version)

    version_protocol = _extract_version_protocol(protocol)
    if version_protocol != parsed_version.protocol:
        raise InvalidIdentifier(
            f"protocol 标签裸段 {version_protocol!r} 与版本协议段 {parsed_version.protocol!r} 不符"
        )

    decisions_path = _working_dir(root, batch) / "review" / "review_decisions.json"
    if not decisions_path.is_file():
        raise ReviewGateError("审查结果未回收，无法 release")

    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))

    # Finding 1：release 复核 decisions 绑定的内容 digest 与当前内容一致。
    subvideo_manifest_path = (
        _working_dir(root, batch) / "subvideo" / "subvideo_manifest.json"
    )
    current_digest = _sha256_file(subvideo_manifest_path)
    if decisions.get("content_sha256") != current_digest:
        raise ReviewGateError(
            "审查结论绑定的内容 digest 与当前 subvideo manifest 不一致，"
            "审查针对旧内容，必须重新回收审查结果"
        )

    accepted = _accepted_clips(decisions)

    data_root = _data_root(root)

    # 固定路径 data/release_payload/：可整体重建的普通 DVC out（不封存）。
    fixed_payload_dir = data_root / "release_payload"
    if fixed_payload_dir.exists():
        shutil.rmtree(fixed_payload_dir)
    fixed_payload_dir.mkdir(parents=True)
    fixed_accepted = fixed_payload_dir / "accepted_clips.json"
    _write_json(fixed_accepted, {"clips": accepted})

    # 在独立组装目录中准备 payload 子目录，不移动 DVC 上游的 working/<batch>。
    staging_working_name = f"{batch}.release"
    staging_working = data_root / "working" / staging_working_name
    if staging_working.exists():
        shutil.rmtree(staging_working)
    shutil.copytree(_working_dir(root, batch), staging_working)

    # Finding 3：payload 与 Git 跟踪元数据严格分离 —— accepted_clips.json
    # 位于版本目录的 payload/ 子目录，不得平铺在版本根下。
    payload_subdir = staging_working / "payload"
    payload_subdir.mkdir()
    _write_json(payload_subdir / "accepted_clips.json", {"clips": accepted})

    try:
        stage_release(data_root, staging_working_name, protocol=protocol, version=full_id)
    except DataReleaseError as exc:
        # 组装阶段失败时清理独立 working 目录，避免冲突等路径残留。
        if staging_working.exists():
            shutil.rmtree(staging_working)
        raise DataPipelineError(f"stage_release 失败: {exc}") from exc

    sample_count = len(accepted)
    resolved_description = description or f"{batch} 正式数据发布"

    # 确定性 3-fold 拆分；validation 为 0 不影响 training_reference 校验。
    splits: dict[str, dict[str, int]] = {}
    base = sample_count // 3
    remainder = sample_count % 3
    for idx, fold in enumerate(("fold0", "fold1", "fold2")):
        train_count = base + (1 if idx < remainder else 0)
        splits[fold] = {"train": train_count, "validation": 0}

    try:
        release_dir = seal_release(
            data_root,
            full_id,
            purpose=purpose,
            description=resolved_description,
            sample_count=sample_count,
            source_batches=[batch],
            splits=splits,
        )
    except DataReleaseError as exc:
        # 封存失败时清理 staging，避免留下半成品。
        staging_left = data_root / "release_staging" / full_id
        if staging_left.exists():
            shutil.rmtree(staging_left)
        raise DataPipelineError(f"seal_release 失败: {exc}") from exc

    # Finding 3：DVC 仓库内逐版本执行 dvc add 将 payload 子目录纳入 DVC
    # （生成同级 payload.dvc）；非 DVC 仓库（单元测试 tmp 根）跳过。
    if (root / ".dvc").is_dir():
        _dvc_add_payload(root, release_dir, full_id)

    # 写入 release_pointer.json 供 release_validate 默认发现。
    pointer_path = data_root / "release_pointer.json"
    _write_json(pointer_path, {"version": full_id})

    outputs = (fixed_payload_dir, release_dir, pointer_path)
    report = {"batch": batch, "version": full_id, "sample_count": sample_count}
    return StageResult(stage="release", outputs=outputs, report=report)


def run_release_validate(
    root: Path,
    *,
    version: str | None = None,
) -> StageResult:
    """只报告：真实校验正式数据是否满足训练入口与封存要求（fail-closed）。"""
    data_root = _data_root(root)

    if version is None:
        pointer_path = data_root / "release_pointer.json"
        if not pointer_path.is_file():
            raise DataPipelineError("release_pointer.json 缺失，无法发现版本")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        version = pointer.get("version")
        if not isinstance(version, str):
            raise DataPipelineError("release_pointer.json 中 version 非法")

    # 版本可解析（未封存/元数据非法）时 fail-closed，不写报告。
    try:
        meta = load_release_metadata(data_root, version)
    except Exception as exc:
        raise DataPipelineError(f"版本不可解析: {exc}") from exc

    # Finding 2：两项真实检查，不得硬编码通过。
    checks: dict[str, dict[str, Any]] = {}

    training_check: dict[str, Any] = {"passed": True}
    try:
        validate_training_reference(data_root, version)
    except Exception as exc:
        training_check = {"passed": False, "error": str(exc)}
    checks["training_reference"] = training_check

    sealed_check: dict[str, Any] = {"passed": True}
    try:
        assert_payload_sealed(data_root / "releases" / version)
    except Exception as exc:
        sealed_check = {"passed": False, "error": str(exc)}
    checks["sealed_release"] = sealed_check

    passed = all(check.get("passed") is True for check in checks.values())

    # 总是先落盘报告（含失败情形），再按结果 fail-closed。
    reports_dir = data_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{version}.validation.json"
    report_data = {
        "version": version,
        "status": meta.status.value,
        "training_allowed": meta.training_allowed,
        "passed": passed,
        "checks": checks,
    }
    _write_json(report_path, report_data)

    if not passed:
        raise DataPipelineError(
            f"release_validate 失败（fail-closed）: "
            f"{[name for name, check in checks.items() if not check['passed']]}"
        )

    outputs = (report_path,)
    report = {"version": version, "passed": passed, "checks": checks}
    return StageResult(stage="release_validate", outputs=outputs, report=report)


def run_stage(root: Path, stage: str, **kwargs: Any) -> StageResult:
    """按 stage 名分发到对应执行函数。"""
    if stage not in _STAGES_SET:
        raise UnknownStageError(f"未知 stage: {stage!r}")

    dispatch: dict[str, Any] = {
        "source": run_source,
        "roi": run_roi,
        "subvideo": run_subvideo,
        "review_export": run_review_export,
        "review_import": run_review_import,
        "release": run_release,
        "release_validate": run_release_validate,
    }
    return dispatch[stage](root, **kwargs)


@dataclass(frozen=True)
class PinnedInputFile:
    """Verified bytes at an explicit path; a digest is not a version identity."""

    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class PinnedSourceVideo:
    video_id: str
    file: PinnedInputFile


@dataclass(frozen=True)
class DataInputs:
    """Read-only M3 input envelope, before stage-specific semantic validation.

    Paths in file references are relative to explicit absolute project_root.
    Source tags/mapping correspond to all_videos_tag.csv/video_mapping.csv.
    split, ROI, media and contract are pinned files, not legacy IDs or pointers.
    The consumer must validate their business schemas and cross-file bindings,
    and reverify pins when consuming them; loading is not a concurrent lock.
    """

    config_path: Path
    config_sha256: str
    project_root: Path
    batch: str
    videos: tuple[PinnedSourceVideo, ...]
    tags: PinnedInputFile
    mapping: PinnedInputFile
    split: PinnedInputFile
    roi_decisions: PinnedInputFile
    media_config: PinnedInputFile
    preprocessor_kind: str
    preprocessor_config: PinnedInputFile
    contract: PinnedInputFile

    @property
    def dependencies(self) -> tuple[Path, ...]:
        """Input dependencies only; DVC must also track actual implementation code."""
        return tuple(dict.fromkeys((
            self.config_path, *(v.file.path for v in self.videos),
            self.tags.path, self.mapping.path, self.split.path,
            self.roi_decisions.path, self.media_config.path,
            self.preprocessor_config.path, self.contract.path,
        )))


class _DataInputsLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise StageInputError("inputs 不允许 YAML alias/merge")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag != 'tag:yaml.org,2002:str':
                raise StageInputError("inputs mapping key 必须是字符串；不允许 merge")
            key = self.construct_object(key_node, deep=True)
            if key in result:
                raise StageInputError(f"inputs 重复 YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=True)
        return result


def _input_mapping(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StageInputError(f"{label} 必须是 mapping")
    missing = keys - value.keys()
    extra = value.keys() - keys
    if missing or extra:
        raise StageInputError(
            f"{label} 字段不符: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def _input_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise StageInputError(f"{label} 必须是非空、无首尾空白字符串")
    return value


def _pin_input_file(value: Any, project: Path, label: str) -> PinnedInputFile:
    ref = _input_mapping(value, {'path', 'size_bytes', 'sha256'}, label)
    path_text = _input_text(ref['path'], f"{label}.path")
    relative = Path(path_text)
    if (relative.is_absolute() or '\\' in path_text or '\x00' in path_text
            or any(part in ('', '.', '..') for part in path_text.split('/'))):
        raise StageInputError(f"{label}.path 必须是 project_root 下的规范相对路径")
    size = ref['size_bytes']
    if type(size) is not int or size < 0:
        raise StageInputError(f"{label}.size_bytes 必须是非负整数")
    digest = ref['sha256']
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise StageInputError(f"{label}.sha256 必须是 64 位小写十六进制摘要")
    path = project
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise StageInputError(f"{label}.path 不允许符号链接: {path}")
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise StageInputError(f"{label}.path 必须是普通文件: {path}")
        actual_size = 0
        hasher = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                actual_size += len(chunk)
                hasher.update(chunk)
    except OSError as exc:
        raise StageInputError(f"无法读取 {label}.path: {path}: {exc}") from exc
    if actual_size != size:
        raise StageInputError(f"{label}.size_bytes 不匹配: {actual_size} != {size}")
    if hasher.hexdigest() != digest:
        raise StageInputError(f"{label}.sha256 不匹配: {path}")
    return PinnedInputFile(path, size, digest)


def load_data_inputs(path: Path, *, batch: str) -> DataInputs:
    """Validate the complete explicit inputs envelope without any writes/probes.

    Schema: tensile-data/inputs/v1. Required top-level fields are schema, batch,
    project_root, source, split, roi_decisions, media and contract. source has a
    nonempty videos list (video_id plus file pin) and annotations {tags, mapping}.
    media has config plus preprocessor {kind, config}. Every file pin has exactly
    path, size_bytes and sha256. kind records the explicit requested processor;
    the media adapter must validate support and runtime fingerprint before use.
    """
    try:
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise StageInputError("inputs YAML 必须是普通文件且不得为符号链接")
        content = path.read_bytes()
        raw = yaml.load(content.decode('utf-8'), Loader=_DataInputsLoader)
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise StageInputError(f"无法读取 inputs YAML: {exc}") from exc
    doc = _input_mapping(raw, {
        'schema', 'batch', 'project_root', 'source', 'split', 'roi_decisions',
        'media', 'contract',
    }, 'inputs')
    if doc['schema'] != 'tensile-data/inputs/v1':
        raise StageInputError("inputs.schema 必须是 tensile-data/inputs/v1")
    explicit_batch = _input_text(doc['batch'], 'inputs.batch')
    if (re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', explicit_batch) is None
            or explicit_batch != batch):
        raise StageInputError("inputs.batch 非法或与调用 batch 不一致")
    project = Path(_input_text(doc['project_root'], 'inputs.project_root'))
    if not project.is_absolute() or not project.is_dir():
        raise StageInputError("inputs.project_root 必须是存在的绝对目录")
    project = project.resolve()
    source = _input_mapping(doc['source'], {'videos', 'annotations'}, 'source')
    annotations = _input_mapping(source['annotations'], {'tags', 'mapping'}, 'source.annotations')
    media = _input_mapping(doc['media'], {'config', 'preprocessor'}, 'media')
    processor = _input_mapping(media['preprocessor'], {'kind', 'config'}, 'media.preprocessor')
    kind = _input_text(processor['kind'], 'media.preprocessor.kind')
    entries = source['videos']
    if not isinstance(entries, list) or not entries:
        raise StageInputError("source.videos 必须是非空列表")
    videos = []
    seen = set()
    for entry in entries:
        entry = _input_mapping(entry, {'video_id', 'path', 'size_bytes', 'sha256'}, 'source.videos item')
        video_id = _input_text(entry['video_id'], 'video_id')
        if re.fullmatch(r'video_\d{4}', video_id) is None or video_id in seen:
            raise StageInputError(f"video_id 非法或重复: {video_id}")
        ref = {key: entry[key] for key in ('path', 'size_bytes', 'sha256')}
        file = _pin_input_file(ref, project, f'source.videos.{video_id}')
        if file.path.name != f'{video_id}.mp4':
            raise StageInputError(f"video_id 与视频文件名不匹配: {video_id}")
        videos.append(PinnedSourceVideo(video_id, file))
        seen.add(video_id)
    return DataInputs(
        path.resolve(), hashlib.sha256(content).hexdigest(), project,
        explicit_batch, tuple(videos),
        _pin_input_file(annotations['tags'], project, 'source.annotations.tags'),
        _pin_input_file(annotations['mapping'], project, 'source.annotations.mapping'),
        _pin_input_file(doc['split'], project, 'split'),
        _pin_input_file(doc['roi_decisions'], project, 'roi_decisions'),
        _pin_input_file(media['config'], project, 'media.config'), kind,
        _pin_input_file(processor['config'], project, 'media.preprocessor.config'),
        _pin_input_file(doc['contract'], project, 'contract'),
    )


SPLIT_NAMES = ('test', *(f'fold_{i}_{part}' for i in range(3) for part in ('train', 'val')))


def _verify_input_pin(ref: PinnedInputFile) -> None:
    _pin_input_file({'path': ref.path.name, 'size_bytes': ref.size_bytes,
                     'sha256': ref.sha256}, ref.path.parent, str(ref.path))


def _read_pinned_document(ref: PinnedInputFile) -> Any:
    _verify_input_pin(ref)
    try:
        content = ref.path.read_bytes()
        if len(content) != ref.size_bytes or hashlib.sha256(content).hexdigest() != ref.sha256:
            raise StageInputError(f'输入读取期间内容漂移: {ref.path}')
        return yaml.load(content.decode('utf-8'), Loader=_DataInputsLoader)
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise StageInputError(f'无法读取结构化输入 {ref.path}: {exc}') from exc


def _read_source_rows(ref: PinnedInputFile, columns: tuple[str, ...]) -> list[dict[str, str]]:
    _verify_input_pin(ref)
    content = ref.path.read_bytes()
    if hashlib.sha256(content).hexdigest() != ref.sha256:
        raise StageInputError(f'注释读取期间漂移: {ref.path}')
    try:
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or set(columns) - set(fields):
            raise StageInputError(f'注释表列缺失或重复: {ref.path}')
        rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise StageInputError(f'注释表行列数量不一致: {ref.path}')
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise StageInputError(f'无法读取注释表: {ref.path}: {exc}') from exc


def _load_input_splits(inputs: DataInputs) -> dict[str, list[str]]:
    doc = _input_mapping(_read_pinned_document(inputs.split),
                         {'schema', 'batch', 'source_sha256', 'splits'}, 'split')
    if doc['schema'] != 'tensile-data/split-inputs/v1' or doc['batch'] != inputs.batch:
        raise StageInputError('split schema/batch 不匹配')
    pins = {v.video_id: v.file.sha256 for v in inputs.videos}
    if doc['source_sha256'] != pins:
        raise StageInputError('split 未绑定完整 source SHA-256 清单')
    splits = _input_mapping(doc['splits'], set(SPLIT_NAMES), 'split.splits')
    for name, ids in splits.items():
        if (not isinstance(ids, list) or not all(isinstance(v, str) for v in ids)
                or len(ids) != len(set(ids)) or set(ids) - pins.keys()):
            raise StageInputError(f'split {name} 视频清单非法/重复/未知')
    test = set(splits['test'])
    for fold in range(3):
        train = set(splits[f'fold_{fold}_train'])
        val = set(splits[f'fold_{fold}_val'])
        if train & val or (train | val) & test or train | val | test != pins.keys():
            raise StageInputError(f'fold_{fold}: 划分交叉或未覆盖完整 source')
    return splits


def _input_stage_path(root: Path, batch: str, stage: str) -> Path:
    if stage not in STAGES or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', batch) is None:
        raise StageInputError('非法 stage/batch')
    current = root.absolute()
    for part in ('', 'data', 'working', batch, stage):
        if part:
            current /= part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise StageInputError(f'输出路径不是普通目录: {current}')
    return current


def _stage_inventory(directory: Path) -> dict[str, Any]:
    inventory = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise StageInputError(f'阶段产物不允许符号链接: {path}')
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            raise StageInputError(f'阶段产物必须是普通文件: {path}')
        name = path.relative_to(directory).as_posix()
        if name == 'stage_manifest.json':
            continue
        inventory[name] = {'size_bytes': path.stat().st_size, 'sha256': _sha256_file(path)}
    return inventory


def _load_input_stage(root: Path, inputs: DataInputs, stage: str) -> tuple[Path, dict[str, Any]]:
    directory = _input_stage_path(root, inputs.batch, stage)
    manifest_path = directory / 'stage_manifest.json'
    try:
        if manifest_path.is_symlink():
            raise StageInputError('阶段 manifest 不允许符号链接')
        doc = yaml.load(manifest_path.read_text(encoding='utf-8'), Loader=_DataInputsLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StageInputError(f'阶段 {stage} 缺失或无法读取: {exc}') from exc
    doc = _input_mapping(doc, {'schema', 'stage', 'batch', 'inputs_sha256', 'upstream',
                              'artifacts', 'report'}, f'{stage}.manifest')
    if (doc['schema'] != 'tensile-data/stage/v1' or doc['stage'] != stage
            or doc['batch'] != inputs.batch or doc['inputs_sha256'] != inputs.config_sha256):
        raise StageInputError(f'{stage} 身份或 inputs 内容漂移')
    if doc['artifacts'] != _stage_inventory(directory):
        raise StageInputError(f'{stage} 产物内容漂移')
    return directory, doc


def _publish_input_stage(root: Path, inputs: DataInputs, stage: str, producer,
                         upstream: Mapping[str, str] | None = None) -> StageResult:
    """Publish one complete working stage; never overwrite an existing result."""
    directory = _input_stage_path(root, inputs.batch, stage)
    upstream = dict(upstream or {})
    fresh = load_data_inputs(inputs.config_path, batch=inputs.batch)
    if fresh != inputs:
        raise StageInputError('inputs 在阶段执行前漂移')
    # All semantic preflight must precede this helper's first filesystem write.
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock_path = directory.parent / f'.{stage}.lock'
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    with os.fdopen(os.open(lock_path, flags, 0o600), 'a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load_data_inputs(inputs.config_path, batch=inputs.batch) != inputs:
            raise StageInputError('inputs 在等待阶段锁期间漂移')
        _input_stage_path(root, inputs.batch, stage)
        _verify_upstream_stages(root, inputs, upstream)
        if directory.exists():
            existing, manifest = _load_input_stage(root, inputs, stage)
            if manifest['upstream'] != upstream:
                raise StageInputError(f'{stage} 上游内容漂移')
            return StageResult(stage, (existing,), manifest['report'])
        with tempfile.TemporaryDirectory(prefix=f'.{stage}-', dir=directory.parent) as temp:
            temporary = Path(temp) / stage
            temporary.mkdir()
            report = producer(temporary)
            if load_data_inputs(inputs.config_path, batch=inputs.batch) != inputs:
                raise StageInputError('inputs 在阶段执行期间漂移')
            _verify_upstream_stages(root, inputs, upstream)
            manifest = {'schema': 'tensile-data/stage/v1', 'stage': stage,
                        'batch': inputs.batch, 'inputs_sha256': inputs.config_sha256,
                        'upstream': upstream, 'artifacts': _stage_inventory(temporary),
                        'report': report}
            _write_json(temporary / 'stage_manifest.json', manifest)
            if directory.exists() or directory.is_symlink():
                raise StageInputError(f'{stage} 目标冲突')
            os.rename(temporary, directory)
        return StageResult(stage, (directory,), report)


def _copy_input_pin(ref: PinnedInputFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    size = 0
    with ref.path.open('rb') as source, destination.open('xb') as target:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            target.write(chunk)
            size += len(chunk)
            hasher.update(chunk)
    if size != ref.size_bytes or hasher.hexdigest() != ref.sha256:
        raise StageInputError(f'复制期间输入漂移: {ref.path}')


def run_input_source(root: Path, *, inputs_path: Path, batch: str, probe=None) -> StageResult:
    """Create source snapshot and preserve caller-supplied seven split memberships."""
    from pipeline import source_bootstrap as source_api
    from pipeline.v4_1_training_release import _contract_identity

    inputs = load_data_inputs(inputs_path, batch=batch)
    _input_stage_path(root, batch, 'source')
    splits = _load_input_splits(inputs)
    _read_pinned_document(inputs.contract)  # Reject ambiguous YAML/JSON before business loading.
    try:
        _contract_identity(inputs.contract.path)
    except ValueError as exc:
        raise StageInputError(f'业务 contract 无效: {exc}') from exc
    tags = _read_source_rows(inputs.tags, source_api.TAG_COLUMNS)
    mappings = _read_source_rows(inputs.mapping, source_api.MAPPING_COLUMNS)
    video_ids = {v.video_id for v in inputs.videos}
    tag_ids = [row['id'].strip() for row in tags]
    mapping_ids = [Path(row['标准化文件名'].strip()).stem for row in mappings]
    if (len(set(tag_ids)) != len(tag_ids) or len(set(mapping_ids)) != len(mapping_ids)
            or set(tag_ids) != video_ids or set(mapping_ids) != video_ids):
        raise StageInputError('视频、tags 与 mapping ID 全集不一致或存在重复')
    for row in tags:
        if Path(row['video_path'].strip()).name != f"{row['id'].strip()}.mp4":
            raise StageInputError('tags video_path 与 ID 不一致')
    for row in mappings:
        if (not row['原始文件名'].strip() or not row['来源目录'].strip()
                or row['状态'].strip() not in source_api.MAPPING_STATUSES):
            raise StageInputError('mapping 缺少来源或状态非法')
    tag_index = {row['id'].strip(): row for row in tags}
    records, files, warnings = [], [], []
    for video in inputs.videos:
        try:
            observed = (probe or source_api.probe_video)(video.file.path)
            for key in ('width', 'height', 'fps_num', 'fps_den', 'duration_us', 'total_frames'):
                if type(observed[key]) is not int or observed[key] <= 0:
                    raise ValueError(f'{key} 必须是正整数')
            if (type(observed['fps']) not in (int, float) or not math.isfinite(observed['fps'])
                    or observed['fps'] <= 0
                    or not math.isclose(observed['fps'], observed['fps_num'] / observed['fps_den'])):
                raise ValueError('fps 非法或与有理帧率不一致')
            record, notes = source_api._governed_record(tag_index[video.video_id], observed)
        except Exception as exc:
            raise StageInputError(f'{video.video_id}: probe/标签治理失败: {exc}') from exc
        record['video_path'] = f'media/{video.file.path.name}'
        records.append(record)
        warnings.extend(notes)
        files.append({'name': video.file.path.name, 'video_id': video.video_id,
                      'size': video.file.size_bytes, 'sha256': video.file.sha256,
                      'probe': observed})
    if load_data_inputs(inputs_path, batch=batch) != inputs:
        raise StageInputError('source probe 期间输入漂移')
    manifest = {'batch': batch, 'inputs_sha256': inputs.config_sha256, 'files': files,
                'records': records, 'splits': splits, 'warnings': warnings,
                'annotation_sha256': {'tags': inputs.tags.sha256, 'mapping': inputs.mapping.sha256},
                'contract_sha256': inputs.contract.sha256}

    def produce(destination):
        for video in inputs.videos:
            _copy_input_pin(video.file, destination / 'media' / video.file.path.name)
        for name, ref in (('all_videos_tag.csv', inputs.tags), ('video_mapping.csv', inputs.mapping)):
            _copy_input_pin(ref, destination / 'annotations' / name)
        _copy_input_pin(inputs.split, destination / 'split_inputs.json')
        for name, ids in splits.items():
            _write_json(destination / 'splits' / f'{name}.json',
                        {'split': name, 'video_ids': ids, 'count': len(ids)})
        _write_json(destination / 'source_manifest.json', manifest)
        return {'batch': batch, 'file_count': len(files), 'warnings': warnings}

    return _publish_input_stage(root, inputs, 'source', produce,
                                {'source_manifest_sha256': hashlib.sha256(
                                    json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})




def _verify_upstream_stages(root: Path, inputs: DataInputs, upstream: Mapping[str, str],
                            seen: set[str] | None = None) -> None:
    if not isinstance(upstream, dict):
        raise StageInputError('upstream 必须是 mapping')
    seen = set() if seen is None else seen
    for stage, digest in upstream.items():
        if stage == 'source_manifest_sha256':
            continue
        if stage not in STAGES or stage in seen:
            raise StageInputError('阶段上游非法或出现循环')
        directory, manifest = _load_input_stage(root, inputs, stage)
        if _sha256_file(directory / 'stage_manifest.json') != digest:
            raise StageInputError(f'{stage}: 上游 manifest 漂移')
        _verify_upstream_stages(root, inputs, manifest['upstream'], seen | {stage})


def _execute_input_media(command: list[str], label: str) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise StageInputError(f'{label}: 无法执行媒体命令: {exc}') from exc
    if result.returncode != 0:
        raise StageInputError(f'{label}: {result.stderr.strip()}')


def _stage_json(directory: Path, name: str) -> dict[str, Any]:
    try:
        value = yaml.load((directory / name).read_text(encoding='utf-8'), Loader=_DataInputsLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StageInputError(f'阶段输入无法读取 {name}: {exc}') from exc
    if not isinstance(value, dict):
        raise StageInputError(f'阶段输入必须是 mapping: {name}')
    return value



def _checked_input_probe(probe, path: Path):
    from fractions import Fraction
    observed = probe(path)
    try:
        if (type(observed.duration) not in (int, float)
                or not math.isfinite(observed.duration) or observed.duration <= 0):
            raise ValueError('duration 必须是正有限数')
        for key in ('width', 'height', 'frame_count'):
            value = getattr(observed, key)
            if type(value) is not int or value <= 0:
                raise ValueError(f'{key} 必须是正整数')
        for key in ('frame_rate', 'nominal_frame_rate'):
            if Fraction(getattr(observed, key)) <= 0:
                raise ValueError(f'{key} 必须是正帧率')
    except (AttributeError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise StageInputError(f'媒体属性无效 {path}: {exc}') from exc
    return observed


def run_input_roi(root: Path, *, inputs_path: Path, batch: str, probe=None) -> StageResult:
    """Validate frozen human ROI then crop/pad without changing the timeline."""
    from pipeline import roi_manifest as roi_api, roi_media

    inputs = load_data_inputs(inputs_path, batch=batch)
    source_dir, _ = _load_input_stage(root, inputs, 'source')
    source = _stage_json(source_dir, 'source_manifest.json')
    frozen = _read_pinned_document(inputs.roi_decisions)
    try:
        decisions = roi_api._decision_index(frozen)
    except ValueError as exc:
        raise StageInputError(f'ROI 决定无效: {exc}') from exc
    records = {row['video_id']: row for row in source['records']}
    files = {row['video_id']: row for row in source['files']}
    if set(decisions) != set(records):
        raise StageInputError('ROI 决定必须完整覆盖 source 全集')
    rows = []
    for video in inputs.videos:
        video_id = video.video_id
        decision = decisions[video_id]
        reference = _input_text(decision.get('source_video_path'), 'ROI.source_video_path')
        raw = Path(reference)
        if not raw.is_absolute():
            raw = inputs.project_root / raw
        if '..' in Path(reference).parts or raw.resolve() != video.file.path:
            raise StageInputError(f'{video_id}: ROI 源路径不匹配显式 video pin')
        if decision.get('source_sha256') != video.file.sha256:
            raise StageInputError(f'{video_id}: ROI source SHA-256 不一致')
        observed = files[video_id]['probe']
        if decision.get('source_resolution') != [observed['width'], observed['height']]:
            raise StageInputError(f'{video_id}: ROI source_resolution 与真实 source 不一致')
        timestamps = decision.get('reviewed_timestamps')
        if (not isinstance(timestamps, list) or not timestamps or any(
                type(value) not in (int, float) or not math.isfinite(value)
                or value < 0 or value > records[video_id]['duration'] for value in timestamps)):
            raise StageInputError(f'{video_id}: reviewed_timestamps 无效或越界')
        try:
            # Resolve only the already-bound exact path; no legacy path fallback.
            roi_api._validate_decision(
                {**decision, 'source_video_path': str(video.file.path)}, records[video_id],
                inputs.project_root, verify_source_hash=True)
            video_filter, resolution = roi_media.filter_for_decision(decision)
        except ValueError as exc:
            raise StageInputError(f'{video_id}: ROI 校验失败: {exc}') from exc
        rows.append((video_id, decision, video_filter, resolution))
    upstream = {'source': _sha256_file(source_dir / 'stage_manifest.json')}
    get_probe = probe or roi_media.probe_video

    def produce(destination):
        videos, derived_records = [], []
        for video_id, decision, video_filter, resolution in rows:
            source_path = source_dir / 'media' / files[video_id]['name']
            output = destination / 'media' / f'{video_id}.mp4'
            output.parent.mkdir(parents=True, exist_ok=True)
            try:
                before = _checked_input_probe(get_probe, source_path)
                recorded = files[video_id]['probe']
                if ((before.width, before.height) != tuple(decision['source_resolution'])
                        or before.frame_count != recorded['total_frames']):
                    raise StageInputError(f'{video_id}: 裁剪前源属性漂移')
                command = roi_media.build_ffmpeg_command(source_path, output, decision)
                _execute_input_media(command, f'{video_id}: ROI 裁剪失败')
                after = _checked_input_probe(get_probe, output)
                roi_media.validate_temporal_contract(before, after, resolution)
            except (ValueError, RuntimeError, OSError) as exc:
                raise StageInputError(f'{video_id}: ROI 媒体校验失败: {exc}') from exc
            digest = _sha256_file(output)
            videos.append({'video_id': video_id, 'path': f'media/{video_id}.mp4',
                           'output_resolution': [after.width, after.height],
                           'frame_count': after.frame_count, 'duration': after.duration,
                           'frame_rate': after.frame_rate, 'nominal_frame_rate': after.nominal_frame_rate,
                           'video_filter': video_filter, 'sha256': digest,
                           'size_bytes': output.stat().st_size})
            derived_records.append({**records[video_id], 'video_path': f'media/{video_id}.mp4',
                                    'width': after.width, 'height': after.height,
                                    'roi_provenance': {'source_stage_sha256': upstream['source'],
                                                       'roi_decisions_sha256': inputs.roi_decisions.sha256,
                                                       'mode': decision['mode'], 'pixel_box': decision['pixel_box'],
                                                       'output_sha256': digest}})
        if _sha256_file(source_dir / 'stage_manifest.json') != upstream['source']:
            raise StageInputError('ROI 执行期间 source manifest 漂移')
        _load_input_stage(root, inputs, 'source')
        _write_json(destination / 'roi_manifest.json', {
            'batch': batch, 'inputs_sha256': inputs.config_sha256,
            'videos': videos, 'records': derived_records, 'splits': source['splits']})
        _write_json(destination / 'roi_decisions.frozen.json', {
            'schema_version': frozen['schema_version'],
            'roi_policy_version': frozen['roi_policy_version'],
            'decisions': frozen['decisions']})
        return {'batch': batch, 'video_count': len(videos)}

    return _publish_input_stage(root, inputs, 'roi', produce, upstream)
