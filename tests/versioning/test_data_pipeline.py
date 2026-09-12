"""B4 — DVC 数据 pipeline 七阶段的真实最小实现（versioning.data_pipeline）单元测试。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.4（七阶段主干与人工审查显式关卡、D015/D016）、§2.5（DVC 权威边界）、
§5.1（DVC 输出边界=payload 子目录；Git 跟踪同级 release.yaml/README）、D031、
D035（自动发现、手动执行；release_validate 只报告不启动训练）；
实施台账 docs/plans/2026-09-01-readable-version-control-implementation.md B4 小节。

第二轮契约修订（reviewer Finding 1/2/3，移交 viber 的实现规格以本文件与
tests/versioning/test_dvc_pipeline.py 的 docstring 为准）：

预期 production API（供 viber 对照实现，模块 ``versioning.data_pipeline``）::

    STAGES: tuple[str, ...]
        # 恰好为 ("source", "roi", "subvideo", "review_export",
        #          "review_import", "release", "release_validate")

    class DataPipelineError(ValueError)       # pipeline 域异常基类
    class UnknownStageError(DataPipelineError)  # 非法 stage 名（fail-closed）
    class StageInputError(DataPipelineError)    # 缺上游产物 / 输入为空
    class ReviewGateError(DataPipelineError)    # 审查未回收 / 格式错 / 结论不通过
                                                # / 内容 digest 不匹配（Finding 1）

    @dataclass(frozen=True)
    class StageResult
        # stage: str                    本 stage 名
        # outputs: tuple[Path, ...]     本 stage 产生的真实文件/目录（已存在）
        # report: Mapping[str, Any]     摘要信息（至少含下文各阶段声明的键）

    目录约定（root 为项目根，所有产物在 root/data/ 下，batch 默认 "batch-001"）：
        输入   data/raw/<batch>/<原始媒体文件>          （至少 1 个文件）
        source          -> data/working/<batch>/source/media/<文件名>（结构化整理副本）
                           data/working/<batch>/source/source_manifest.json
        roi             -> data/working/<batch>/roi/roi_manifest.json
        subvideo        -> data/working/<batch>/subvideo/subvideo_manifest.json
        review_export   -> data/working/<batch>/review/review_package/items.jsonl
        review_import   <- data/review_results/<batch>.yaml（人工审查结果，外部输入）
                        -> data/working/<batch>/review/review_decisions.json
        release         -> data/release_payload/（固定路径，可重建，DVC 普通 out）
                           data/releases/<data-v...>/{release.yaml,README.md,payload/}
                           （release.yaml/README.md 为 Git 跟踪边界；payload/ 为
                           DVC 管理的 payload 子目录，封存后只读；DVC 仓库内运行时
                           经 dvc add 生成同级 payload.dvc 指针文件）
                           data/release_pointer.json {"version": ...}
        release_validate-> data/reports/<version>.validation.json（只报告）

    def run_source(root: Path, *, batch: str = "batch-001") -> StageResult
        # 整理 data/raw/<batch>/ 下原始文件到 source/media/，写 source_manifest.json：
        #   {"batch": str, "files": [{"name","size","sha256"}...]} 按 name 排序。
        # 产物确定性：相同输入在不同 root 下 manifest 逐字节一致（不含绝对路径/时间戳）。
        # raw 目录不存在或无文件 -> StageInputError。

    def run_roi(root: Path, *, batch: str = "batch-001") -> StageResult
        # 冻结 ROI manifest：{"videos":[{"name", "roi":{"x","y","width","height"}}...]}
        # 覆盖 source 全部视频，roi 四键为非负整数；产物确定性同 source。
        # source_manifest.json 缺失 -> StageInputError。

    def run_subvideo(root: Path, *, batch: str = "batch-001") -> StageResult
        # 每视频生成 2 条子视频记录：{"clips":[{"clip_id","source","index"}...]}，
        # clip_id 是 (source, index) 的确定性函数、全局唯一；产物确定性同 source。
        # roi_manifest.json 缺失 -> StageInputError。

    def run_review_export(root: Path, *, batch: str = "batch-001") -> StageResult
        # 导出审查包 items.jsonl：逐行 JSON，每个 clip 一行，含 "clip_id" 与
        # "content_sha256" 键；逐行 content_sha256 同值，等于当前 subvideo manifest
        # 的内容哈希（内容变化即变化，clip_id 集合不变也可能变化）；覆盖全部 clip_id。
        # report 至少含 "content_sha256"（与行内同值），供审查方填写结果 YAML。
        # subvideo_manifest.json 缺失 -> StageInputError。

    def run_review_import(root: Path, *, batch: str = "batch-001",
                          results_path: Path | None = None) -> StageResult
        # 人工审查显式关卡（D015）。审查结果 YAML（默认
        # data/review_results/<batch>.yaml，可用 results_path 显式指定）格式：
        #   batch: <batch>            # 必须与本批一致
        #   approved: true|false      # 人工审查通过标记，必须布尔
        #   content_sha256: <64-hex>  # 必填（Finding 1）：审查针对的内容 digest，
        #                             # 取值为审查包导出时行内 content_sha256
        #   decisions: [{clip_id, verdict}]   # verdict ∈ {accept, reject}
        # 校验（任一失败 -> ReviewGateError，且不写/不覆盖 review_decisions.json）：
        #   文件不存在（未回收）/ 非映射 / 缺键（含 content_sha256）/ batch 不一致 /
        #   approved 非布尔 / content_sha256 与当前 subvideo manifest 内容哈希
        #   不一致（审查结论与内容绑定：内容变化后旧审查结果一律作废）/
        #   decisions 的 clip_id 集合不等于审查包导出的 clip_id 集合（漏审或多余）/
        #   verdict 非法 / approved 为 false（审查结论不通过，关卡阻断）。
        # 通过 -> 写 review_decisions.json {"batch","accepted":[...],"rejected":[...],
        #   "content_sha256":<digest>}，accepted/rejected 为排序后的 clip_id 列表，
        #   content_sha256 记录审查通过时绑定的内容 digest 供 release 复核。

    def run_release(root: Path, *, batch: str = "batch-001", version: str | None = None,
                    protocol: str = "v4.1", purpose: str = "development",
                    description: str | None = None) -> StageResult
        # 【第三轮契约修订：显式版本纪律（§9/§11.6）】release 目标版本必须由调用方
        #   显式给出，run_release 不得自动递增分配：
        #   - version=None（缺失）-> ReviewGateError（选定钉死：release 关卡的
        #     前置条件错误，调用方未显式选择目标版本时关卡阻断）；
        #   - version 非法（非字符串 / 非完整 data ID / 协议段与 protocol 裸段
        #     不符）-> versioning.ids.InvalidIdentifier；
        #   - 以上两者均先于任何文件系统副作用：不重建 data/release_payload/、
        #     不复制 data/working/<batch>.release、不产生 data/releases/ 条目。
        #   - 版本建议是调用方职责：用 versioning.ids.suggest_next_id("data",
        #     <裸协议段>, existing=data/releases/ 与 data/release_staging/ 下既有
        #     目录名) 取得建议后核对显式传入；编号无需连续，系统只拒绝同 ID 冲突。
        # 关卡（Finding 1，语义保持）：review_decisions.json 不存在（审查未回收/未通过）
        #   -> ReviewGateError；review_decisions.json 记录的 content_sha256 与当前
        #   subvideo manifest 内容哈希不一致（审查针对的是旧内容）-> ReviewGateError；
        #   且以上两种情形不得在 data/releases/ 下产生任何条目。
        # 通过：组装仅含 accepted clips 的 payload（至少含 accepted_clips.json
        #   {"clips":[...]}），先落固定路径 data/release_payload/（可整体重建的
        #   普通 DVC out，不封存），再以显式 version 调用 versioning.data_release 的
        #   stage_release(version=...) + seal_release 封存为 data-v<protocol>-r<N>；
        #   同名 staging/sealed 已存在 -> ReleaseConflict 经包装为 DataPipelineError
        #   （不得覆盖既有版本；r1/r2 显式共存）。
        # 封存版本目录布局（§5.1/D031，DVC 输出边界=payload 子目录）：
        #   data/releases/<version>/release.yaml   —— Git 跟踪边界，保持 owner 可写
        #   data/releases/<version>/README.md      —— Git 跟踪边界，保持 owner 可写
        #   data/releases/<version>/payload/       —— payload 子目录（含
        #       accepted_clips.json 等），封存后整树只读；payload 与元数据严格分离，
        #       版本根下不得平铺 payload 文件
        #   data/releases/<version>/payload.dvc    —— 当 root 为 DVC 仓库
        #       （root/.dvc 存在）时，run_release 对每个版本执行
        #       ``dvc add data/releases/<version>/payload`` 生成的指针文件；
        #       非 DVC 仓库（单元测试 tmp 根）时跳过，不要求存在
        # 写 data/release_pointer.json {"version": <version>}，返回 report 含
        #   "version" 与 "sample_count"（== accepted 数）。
        # 封存后 load_release_metadata / validate_training_reference /
        #   assert_payload_sealed 必须放行。

    def run_release_validate(root: Path, *, version: str | None = None) -> StageResult
        # 只报告（D035）：version 为 None 时读 data/release_pointer.json，
        # 指针缺失或版本不可解析（未封存/元数据非法）-> DataPipelineError（不写报告）。
        # 版本可加载时执行真实校验（Finding 2，不得硬编码通过）：
        #   - training_reference：真实调用
        #     versioning.data_release.validate_training_reference
        #   - sealed_release：真实调用 versioning.data_release.assert_payload_sealed
        #     校验封存写位（release.yaml/README.md/authorization 豁免）
        # 总是先写 data/reports/<version>.validation.json：
        #   {"version","status","training_allowed","passed": bool,
        #    "checks":{"training_reference":{"passed":bool,...},
        #              "sealed_release":{"passed":bool,...}}}
        # passed 为全部检查的逻辑与；任何检查未过 -> 报告 passed=false 落盘后
        # 再抛 DataPipelineError（CLI 据此非零退出，fail-closed）。
        # 绝不启动训练：不得在 root 下创建 workspace/ 或任何 runs/ 目录。

    def run_stage(root: Path, stage: str, **kwargs) -> StageResult
        # 七阶段分发；stage 不在 STAGES -> UnknownStageError（fail-closed）。

第二轮修订时 production 尚未按上述新契约更新，新增/改写的用例应为 RED
（详见各测试 docstring）。第三轮契约修订（显式版本纪律，§9/§11.6）时
production 仍为旧自动递增契约：run_release 显式版本用例应为 RED
（``TypeError: unexpected keyword argument 'version'`` / DID NOT RAISE
ReviewGateError 等）。所有用例只在 pytest ``tmp_path`` 下构造目录，
不触碰仓库真实数据。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

from versioning.data_pipeline import (
    STAGES,
    DataPipelineError,
    ReviewGateError,
    StageInputError,
    StageResult,
    UnknownStageError,
    run_release,
    run_release_validate,
    run_review_export,
    run_review_import,
    run_roi,
    run_source,
    run_stage,
    run_subvideo,
)
from versioning.data_release import (
    assert_payload_sealed,
    load_release_metadata,
    validate_training_reference,
)
from versioning.ids import InvalidIdentifier, suggest_next_id
from versioning.state import DataStatus

EXPECTED_STAGES = (
    "source",
    "roi",
    "subvideo",
    "review_export",
    "review_import",
    "release",
    "release_validate",
)

BATCH = "batch-001"
VIDEO_NAMES = ("cam-a.mp4", "cam-b.mp4", "cam-c.mp4")


def _make_root(base: Path, batch: str = BATCH, videos: tuple[str, ...] = VIDEO_NAMES) -> Path:
    """构造最小项目根：data/raw/<batch>/ 下放确定性内容的原始媒体文件。"""
    root = base / "proj"
    raw = root / "data" / "raw" / batch
    raw.mkdir(parents=True)
    for index, name in enumerate(videos):
        (raw / name).write_bytes(b"\x00\x01\x02" + bytes([index]) * 16)
    return root


def _working(root: Path, batch: str = BATCH) -> Path:
    return root / "data" / "working" / batch


def _clip_ids(root: Path, batch: str = BATCH) -> list[str]:
    manifest = json.loads(
        (_working(root, batch) / "subvideo" / "subvideo_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return [clip["clip_id"] for clip in manifest["clips"]]


def _export_digest(root: Path, batch: str = BATCH) -> str:
    """读取当前审查包的内容 digest：items.jsonl 逐行 content_sha256 同值。"""
    items_path = (
        _working(root, batch) / "review" / "review_package" / "items.jsonl"
    )
    digests = {
        json.loads(line)["content_sha256"]
        for line in items_path.read_text(encoding="utf-8").splitlines()
    }
    assert len(digests) == 1, "items.jsonl 各行 content_sha256 必须同值"
    return digests.pop()


def _existing_data_versions(root: Path) -> list[str]:
    """data/releases/ 与 data/release_staging/ 下既有版本目录名（建议函数输入）。"""
    data_root = root / "data"
    existing: list[str] = []
    for parent in (data_root / "releases", data_root / "release_staging"):
        if parent.is_dir():
            existing.extend(child.name for child in parent.iterdir() if child.is_dir())
    return existing


def _suggest_next_data_version(root: Path, protocol: str = "v4.1") -> str:
    """建议-显式传入两段式的建议段：取下一个 rN 供调用方核对后显式传入。"""
    return suggest_next_id("data", protocol, _existing_data_versions(root))


def _advance_to_review_export(root: Path, batch: str = BATCH) -> None:
    run_source(root, batch=batch)
    run_roi(root, batch=batch)
    run_subvideo(root, batch=batch)
    run_review_export(root, batch=batch)


def _write_results(
    root: Path,
    batch: str = BATCH,
    *,
    approved: object = True,
    decisions: object = "auto",
    verdict_map: dict[str, str] | None = None,
    content_sha256: object = "auto",
) -> Path:
    """写审查结果文件。

    decisions="auto" 时按当前导出 clip 集合生成全 accept；
    content_sha256="auto" 时取当前审查包的内容 digest（Finding 1：审查结论
    与内容绑定）；content_sha256=None 时省略该键（用于缺键反向用例）。
    """
    if decisions == "auto":
        decisions = [
            {"clip_id": clip_id, "verdict": (verdict_map or {}).get(clip_id, "accept")}
            for clip_id in _clip_ids(root, batch)
        ]
    if content_sha256 == "auto":
        content_sha256 = _export_digest(root, batch)
    payload: dict[str, object] = {
        "batch": batch,
        "approved": approved,
        "decisions": decisions,
    }
    if content_sha256 is not None:
        payload["content_sha256"] = content_sha256
    results_dir = root / "data" / "review_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{batch}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _read_decisions(root: Path, batch: str = BATCH) -> dict:
    return json.loads(
        (_working(root, batch) / "review" / "review_decisions.json").read_text(
            encoding="utf-8"
        )
    )


def _snapshot_tree(tree_root: Path) -> dict[str, bytes]:
    """逐字节快照目录树：posix 相对路径（目录以 ``/`` 结尾）-> 文件字节。

    供冲突路径回归用例断言既有版本目录逐字节不动（含封存只读树）。
    """
    snapshot: dict[str, bytes] = {}
    if not tree_root.is_dir():
        return snapshot
    for path in sorted(tree_root.rglob("*")):
        relative = path.relative_to(tree_root).as_posix()
        if path.is_dir():
            snapshot[f"{relative}/"] = b""
        else:
            snapshot[relative] = path.read_bytes()
    return snapshot


class TestStageRegistry:
    def test_stages_constant_exact(self) -> None:
        assert tuple(STAGES) == EXPECTED_STAGES

    def test_run_stage_requires_explicit_real_inputs(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        with pytest.raises(StageInputError):
            run_stage(root, "source", batch=BATCH)

    def test_run_stage_unknown_fail_closed(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        with pytest.raises(UnknownStageError):
            run_stage(root, "train")  # pipeline 不得触发训练
        with pytest.raises(UnknownStageError):
            run_stage(root, "frobnicate")
        # fail-closed：非法 stage 不产生任何产物
        assert not _working(root).exists()


class TestSourceStage:
    def test_organizes_raw_files_and_writes_manifest(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        result = run_source(root, batch=BATCH)
        assert result.stage == "source"
        for output in result.outputs:
            assert (root / output).exists() if not output.is_absolute() else output.exists()

        source_dir = _working(root) / "source"
        media = source_dir / "media"
        for name in VIDEO_NAMES:
            assert (media / name).read_bytes() == (
                root / "data" / "raw" / BATCH / name
            ).read_bytes()

        manifest = json.loads(
            (source_dir / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["batch"] == BATCH
        names = [entry["name"] for entry in manifest["files"]]
        assert names == sorted(VIDEO_NAMES)
        for entry in manifest["files"]:
            raw = root / "data" / "raw" / BATCH / entry["name"]
            assert entry["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
            assert entry["size"] == raw.stat().st_size
        assert result.report["file_count"] == len(VIDEO_NAMES)

    def test_manifest_deterministic_across_roots(self, tmp_path: Path) -> None:
        root_a = _make_root(tmp_path / "a")
        root_b = _make_root(tmp_path / "b")
        run_source(root_a, batch=BATCH)
        run_source(root_b, batch=BATCH)
        manifest_a = (_working(root_a) / "source" / "source_manifest.json").read_bytes()
        manifest_b = (_working(root_b) / "source" / "source_manifest.json").read_bytes()
        assert manifest_a == manifest_b

    def test_empty_or_missing_raw_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        with pytest.raises(StageInputError):
            run_source(root, batch=BATCH)
        (root / "data" / "raw" / BATCH).mkdir(parents=True)
        with pytest.raises(StageInputError):
            run_source(root, batch=BATCH)


class TestRoiStage:
    def test_freezes_roi_for_every_source_video(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        run_source(root, batch=BATCH)
        result = run_roi(root, batch=BATCH)
        assert result.stage == "roi"
        manifest = json.loads(
            (_working(root) / "roi" / "roi_manifest.json").read_text(encoding="utf-8")
        )
        names = [video["name"] for video in manifest["videos"]]
        assert names == sorted(VIDEO_NAMES)
        for video in manifest["videos"]:
            roi = video["roi"]
            for key in ("x", "y", "width", "height"):
                assert isinstance(roi[key], int)
                assert roi[key] >= 0

    def test_roi_manifest_deterministic_across_roots(self, tmp_path: Path) -> None:
        root_a = _make_root(tmp_path / "a")
        root_b = _make_root(tmp_path / "b")
        for root in (root_a, root_b):
            run_source(root, batch=BATCH)
            run_roi(root, batch=BATCH)
        assert (_working(root_a) / "roi" / "roi_manifest.json").read_bytes() == (
            _working(root_b) / "roi" / "roi_manifest.json"
        ).read_bytes()

    def test_missing_source_rejected(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        with pytest.raises(StageInputError):
            run_roi(root, batch=BATCH)


class TestSubvideoStage:
    def test_generates_deterministic_clip_manifest(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        run_source(root, batch=BATCH)
        run_roi(root, batch=BATCH)
        result = run_subvideo(root, batch=BATCH)
        assert result.stage == "subvideo"
        manifest = json.loads(
            (_working(root) / "subvideo" / "subvideo_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        clips = manifest["clips"]
        # 每视频恰好 2 条子视频记录
        assert len(clips) == 2 * len(VIDEO_NAMES)
        clip_ids = [clip["clip_id"] for clip in clips]
        assert len(set(clip_ids)) == len(clip_ids)
        sources = {clip["source"] for clip in clips}
        assert sources == set(VIDEO_NAMES)
        for clip in clips:
            assert isinstance(clip["index"], int)
            assert clip["index"] in (0, 1)

    def test_clip_manifest_deterministic_across_roots(self, tmp_path: Path) -> None:
        root_a = _make_root(tmp_path / "a")
        root_b = _make_root(tmp_path / "b")
        for root in (root_a, root_b):
            run_source(root, batch=BATCH)
            run_roi(root, batch=BATCH)
            run_subvideo(root, batch=BATCH)
        assert (_working(root_a) / "subvideo" / "subvideo_manifest.json").read_bytes() == (
            _working(root_b) / "subvideo" / "subvideo_manifest.json"
        ).read_bytes()

    def test_missing_roi_rejected(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        run_source(root, batch=BATCH)
        with pytest.raises(StageInputError):
            run_subvideo(root, batch=BATCH)


class TestReviewExport:
    def test_exports_package_covering_all_clips(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        run_source(root, batch=BATCH)
        run_roi(root, batch=BATCH)
        run_subvideo(root, batch=BATCH)
        result = run_review_export(root, batch=BATCH)
        assert result.stage == "review_export"
        package = _working(root) / "review" / "review_package"
        items_path = package / "items.jsonl"
        assert items_path.is_file()
        exported: list[str] = []
        for line in items_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            exported.append(item["clip_id"])
        assert sorted(exported) == sorted(_clip_ids(root))

        # Finding 1：每行携带内容 digest 且同值；report 暴露同一 digest，
        # 供审查方填写结果 YAML 的 content_sha256。
        digest = _export_digest(root)
        assert result.report["content_sha256"] == digest
        assert len(digest) == 64
        int(digest, 16)

    def test_missing_subvideo_rejected(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        run_source(root, batch=BATCH)
        run_roi(root, batch=BATCH)
        with pytest.raises(StageInputError):
            run_review_export(root, batch=BATCH)


class TestReviewImportGate:
    def test_missing_results_file_blocked(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)
        assert not (_working(root) / "review" / "review_decisions.json").exists()

    def test_malformed_results_blocked(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        results_dir = root / "data" / "review_results"
        results_dir.mkdir(parents=True)
        path = results_dir / f"{BATCH}.yaml"

        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)

        path.write_text(
            yaml.safe_dump({"batch": BATCH, "decisions": []}), encoding="utf-8"
        )
        with pytest.raises(ReviewGateError):  # 缺 approved
            run_review_import(root, batch=BATCH)

        path.write_text(
            yaml.safe_dump({"batch": "batch-999", "approved": True, "decisions": []}),
            encoding="utf-8",
        )
        with pytest.raises(ReviewGateError):  # batch 不一致
            run_review_import(root, batch=BATCH)

        _write_results(root, approved="yes")  # approved 非布尔
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)

        # Finding 1：缺 content_sha256（其余字段合法）同样阻断
        _write_results(root, content_sha256=None)
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)

        assert not (_working(root) / "review" / "review_decisions.json").exists()

    def test_content_digest_mismatch_blocked(self, tmp_path: Path) -> None:
        """Finding 1 反向用例：digest 与当前内容不匹配的旧审查结果必须阻断。"""
        root = _make_root(tmp_path)
        _advance_to_review_export(root)

        # 合法格式但 digest 指向其他内容（如旧批次的 digest）
        _write_results(root, content_sha256="0" * 64)
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)
        assert not (_working(root) / "review" / "review_decisions.json").exists()

        # 重新生成绑定当前内容的审查结果后放行
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)
        assert (_working(root) / "review" / "review_decisions.json").is_file()

    def test_stale_review_results_blocked_after_content_change(
        self, tmp_path: Path
    ) -> None:
        """Finding 1 核心关卡语义：内容变化后沿用旧审查结果必须失败。

        clip_id 集合随视频名不变，但 raw 内容变更 -> subvideo manifest 内容
        哈希变化 -> 旧审查结果的 content_sha256 失配。审查必须针对新内容
        重新回收后才能 release。
        """
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)

        # 上游内容变化（文件名不变，字节内容变化 -> 内容 digest 变化）
        raw_file = root / "data" / "raw" / BATCH / "cam-a.mp4"
        raw_file.write_bytes(raw_file.read_bytes() + b"\xff" * 8)
        _advance_to_review_export(root)

        # 旧审查结果（digest 绑定旧内容）必须被关卡拒绝
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)
        # 阻断不得覆盖既有 decisions 文件内容（仍记录旧 digest）
        assert _read_decisions(root)["content_sha256"] != _export_digest(root)

        # release 复核 decisions 绑定 digest 与当前内容：不一致 -> ReviewGateError
        # （显式给出目标版本，阻断归因于 digest 失配而非版本缺失）
        with pytest.raises(ReviewGateError):
            run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

        # 针对新内容重新审查回收后放行（建议-显式传入：仍为空仓库，建议 r1）
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)
        assert _suggest_next_data_version(root, "v4.1") == "data-v4.1-r1"
        result = run_release(
            root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1"
        )
        assert result.report["version"] == "data-v4.1-r1"

    def test_rejected_review_blocked(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=False)
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)
        assert not (_working(root) / "review" / "review_decisions.json").exists()

    def test_incomplete_or_extra_decisions_blocked(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        clips = _clip_ids(root)

        # 漏审一个 clip
        _write_results(
            root,
            decisions=[{"clip_id": c, "verdict": "accept"} for c in clips[1:]],
        )
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)

        # 多出未知 clip
        _write_results(
            root,
            decisions=[{"clip_id": c, "verdict": "accept"} for c in clips]
            + [{"clip_id": "ghost-clip", "verdict": "accept"}],
        )
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)

        # 非法 verdict
        _write_results(
            root,
            decisions=[
                {"clip_id": c, "verdict": "accept" if i else "maybe"}
                for i, c in enumerate(clips)
            ],
        )
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)

        assert not (_working(root) / "review" / "review_decisions.json").exists()

    def test_approved_review_recycles_decisions(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        clips = _clip_ids(root)
        accepted = sorted(clips[:2])
        rejected = sorted(clips[2:])
        verdict_map = {c: "accept" for c in accepted}
        verdict_map.update({c: "reject" for c in rejected})
        _write_results(root, approved=True, verdict_map=verdict_map)

        result = run_review_import(root, batch=BATCH)
        assert result.stage == "review_import"
        decisions = _read_decisions(root)
        assert decisions["batch"] == BATCH
        assert sorted(decisions["accepted"]) == accepted
        assert sorted(decisions["rejected"]) == rejected
        # Finding 1：decisions 记录审查绑定的内容 digest，供 release 复核
        assert decisions["content_sha256"] == _export_digest(root)

    def test_explicit_results_path(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        path = _write_results(root, approved=True)
        explicit = tmp_path / "elsewhere.yaml"
        explicit.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        run_review_import(root, batch=BATCH, results_path=explicit)
        assert (_working(root) / "review" / "review_decisions.json").is_file()


class TestReleaseStage:
    def test_release_blocked_without_review(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        # 显式给出目标版本：阻断归因于审查关卡而非版本缺失
        with pytest.raises(ReviewGateError):
            run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

    def test_release_blocked_when_review_rejected(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=False)
        with pytest.raises(ReviewGateError):
            run_review_import(root, batch=BATCH)
        with pytest.raises(ReviewGateError):
            run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

    def test_release_requires_explicit_version(self, tmp_path: Path) -> None:
        """显式版本纪律（§9/§11.6）：run_release 不得静默自动分配版本号。

        审查已通过时，缺失 version 是唯一失败原因：必须 ReviewGateError
        （选定钉死），且先于任何文件系统副作用。
        """
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)

        with pytest.raises(ReviewGateError):
            run_release(root, batch=BATCH, protocol="v4.1")
        # fail-closed：不重建 release_payload、不复制 staging working、不产生 release
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())
        assert not (root / "data" / "release_payload").exists()
        assert not (root / "data" / "working" / f"{BATCH}.release").exists()

    def test_release_rejects_invalid_version(self, tmp_path: Path) -> None:
        """非法目标版本（非完整 data ID / 协议段不符）-> InvalidIdentifier，无副作用。"""
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)

        for bad in ("data-v4.1", "data-v4.1-r0", "model-v4.1-r1", "not-a-version", ""):
            with pytest.raises(InvalidIdentifier):
                run_release(root, batch=BATCH, protocol="v4.1", version=bad)
        with pytest.raises(InvalidIdentifier):
            run_release(root, batch=BATCH, protocol="v4.1", version=123)
        # 协议段与 protocol 不符
        with pytest.raises(InvalidIdentifier):
            run_release(root, batch=BATCH, protocol="v4.1", version="data-v5-r1")
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())
        assert not (root / "data" / "release_payload").exists()

    def test_release_seals_accepted_clips_as_data_version(self, tmp_path: Path) -> None:
        """Finding 3 新封存边界：payload/ 子目录与 Git 跟踪元数据严格分离。"""
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        clips = _clip_ids(root)
        accepted = sorted(clips[:2])
        verdict_map = {c: "accept" for c in accepted}
        verdict_map.update({c: "reject" for c in clips if c not in accepted})
        _write_results(root, approved=True, verdict_map=verdict_map)
        run_review_import(root, batch=BATCH)

        # 建议-显式传入两段式：空仓库建议 r1，调用方核对后显式指定
        suggested = _suggest_next_data_version(root, "v4.1")
        assert suggested == "data-v4.1-r1"
        result = run_release(root, batch=BATCH, protocol="v4.1", version=suggested)
        version = result.report["version"]
        assert version == "data-v4.1-r1"
        assert result.report["sample_count"] == len(accepted)

        # 封存产物真实存在且通过 data_release 校验
        release_dir = root / "data" / "releases" / version
        assert release_dir.is_dir()
        meta = load_release_metadata(root / "data", version)
        assert meta.status is DataStatus.ACTIVE
        assert meta.sample_count == len(accepted)
        validate_training_reference(root / "data", version)

        # §5.1/D031：release.yaml / README.md 为 Git 跟踪边界，保持 owner 可写
        release_yaml = release_dir / "release.yaml"
        readme = release_dir / "README.md"
        assert release_yaml.is_file() and os.access(release_yaml, os.W_OK)
        assert readme.is_file() and os.access(readme, os.W_OK)

        # DVC 输出边界=payload 子目录：payload 与元数据分离，
        # 版本根下不得平铺 payload 文件
        payload_dir = release_dir / "payload"
        assert payload_dir.is_dir()
        assert not (release_dir / "accepted_clips.json").exists()

        # 封存真实生效：payload 子目录整树只读
        assert_payload_sealed(release_dir)

        # payload 仅包含 accepted clips
        payload = json.loads(
            (payload_dir / "accepted_clips.json").read_text(encoding="utf-8")
        )
        assert sorted(payload["clips"]) == accepted

        # 固定路径 release_payload/（可重建 DVC 普通 out）与封存 payload 同内容
        workspace_payload = json.loads(
            (root / "data" / "release_payload" / "accepted_clips.json").read_text(
                encoding="utf-8"
            )
        )
        assert workspace_payload == payload

        # release_pointer 供 release_validate 发现版本
        pointer = json.loads(
            (root / "data" / "release_pointer.json").read_text(encoding="utf-8")
        )
        assert pointer["version"] == version

    def test_release_explicit_versions_coexist(self, tmp_path: Path) -> None:
        """原自动递增用例改写为建议-显式传入：r1、r2 由调用方显式指定后共存。

        系统不再自动递增；建议值（r2）正确性仍可断言，但封存落位的
        必须是调用方显式传入的那个版本。
        """
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)
        first = run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        suggested = _suggest_next_data_version(root, "v4.1")
        assert suggested == "data-v4.1-r2"
        second = run_release(root, batch=BATCH, protocol="v4.1", version=suggested)
        assert first.report["version"] == "data-v4.1-r1"
        assert second.report["version"] == "data-v4.1-r2"
        assert (root / "data" / "releases" / "data-v4.1-r1").is_dir()
        assert (root / "data" / "releases" / "data-v4.1-r2").is_dir()
        # 新版本追加封存，payload 子目录各自独立
        assert (
            root / "data" / "releases" / "data-v4.1-r2" / "payload"
        ).is_dir()

    def test_release_existing_version_conflict_rejected(self, tmp_path: Path) -> None:
        """同 ID 冲突拒绝（§11.6）：对已封存版本重复 release 必须失败，不得覆盖。

        同名 staging/sealed 已存在 -> ReleaseConflict 经包装为 DataPipelineError；
        绝不静默递增到下一个 rN。原对象逐字节不动。
        """
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)
        run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        release_dir = root / "data" / "releases" / "data-v4.1-r1"
        payload_bytes = (release_dir / "payload" / "accepted_clips.json").read_bytes()

        with pytest.raises(DataPipelineError) as excinfo:
            run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        # 冲突是封存域错误而非审查关卡错误：包装目标钉死为 DataPipelineError
        assert not isinstance(excinfo.value, ReviewGateError)
        # 原对象不动：r1 唯一、payload 逐字节不变、无 staging 残留
        assert sorted(p.name for p in (root / "data" / "releases").iterdir()) == [
            "data-v4.1-r1"
        ]
        assert (
            release_dir / "payload" / "accepted_clips.json"
        ).read_bytes() == payload_bytes
        assert not (root / "data" / "release_staging" / "data-v4.1-r1").exists()

    def test_release_conflict_leaves_no_assembly_residue(self, tmp_path: Path) -> None:
        """P3-1 回归：同版本冲突失败不得遗留组装目录残留。

        reviewer 发现 run_release 冲突路径（对已封存版本重复 release）失败时
        遗留 data/working/<batch>.release 组装目录。冲突失败路径必须完整清理：
        - 冲突经包装为 DataPipelineError 而非 ReviewGateError（封存域错误）；
        - data/working/<batch>.release 组装目录不得残留（修复目标本体）；
        - 既有 releases/<version> 逐字节不动；
        - release_staging/ 无半成品残留。
        修复落地前本用例应为 RED（组装目录残留存在），修复后转 GREEN。
        """
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)
        run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")

        release_dir = root / "data" / "releases" / "data-v4.1-r1"
        before = _snapshot_tree(release_dir)

        # 成功 release r1 后以同版本再次 run_release：ReleaseConflict 路径
        with pytest.raises(DataPipelineError) as excinfo:
            run_release(root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1")
        # 冲突是封存域错误而非审查关卡错误：包装目标钉死为 DataPipelineError
        assert not isinstance(excinfo.value, ReviewGateError)

        # P3-1 修复目标：组装目录 data/working/<batch>.release 不得残留
        assert not (root / "data" / "working" / f"{BATCH}.release").exists()
        # 既有版本逐字节不动（含 payload/ 封存只读树全部文件）
        assert _snapshot_tree(release_dir) == before
        # staging 无半成品残留
        staging = root / "data" / "release_staging"
        assert not staging.exists() or not any(staging.iterdir())
        # releases/ 下仍只有 r1，无新增条目
        assert sorted(p.name for p in (root / "data" / "releases").iterdir()) == [
            "data-v4.1-r1"
        ]


class TestReleaseValidate:
    def _released_root(self, tmp_path: Path) -> tuple[Path, str]:
        root = _make_root(tmp_path)
        _advance_to_review_export(root)
        _write_results(root, approved=True)
        run_review_import(root, batch=BATCH)
        result = run_release(
            root, batch=BATCH, protocol="v4.1", version="data-v4.1-r1"
        )
        return root, result.report["version"]

    def test_validate_writes_report_only(self, tmp_path: Path) -> None:
        root, version = self._released_root(tmp_path)
        result = run_release_validate(root)
        assert result.stage == "release_validate"
        assert result.report["version"] == version

        report_path = root / "data" / "reports" / f"{version}.validation.json"
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["version"] == version
        assert report["status"] == "active"
        assert report["training_allowed"] is True
        # Finding 2：报告含真实检查结果的 passed 标志与整体判定
        assert report["checks"]["training_reference"]["passed"] is True
        assert report["checks"]["sealed_release"]["passed"] is True
        assert report["passed"] is True

        # D035：只报告，不启动训练 —— 不产生 workspace/ 或任何 runs/ 目录
        assert not (root / "workspace").exists()
        assert [p for p in root.rglob("*") if p.is_dir() and p.name == "runs"] == []

    def test_validate_reports_unsealed_release_fail_closed(self, tmp_path: Path) -> None:
        """Finding 2：sealed_release 检查必须真实反映 assert_payload_sealed 结果。

        对被人为 chmod +w 的 release，validation 报告必须记录
        sealed_release.passed=false 且整体 passed=false，并 fail-closed
        （run_release_validate 抛 DataPipelineError，CLI 非零退出）。
        """
        root, version = self._released_root(tmp_path)

        # 人为破坏封存：恢复 payload 文件的写位
        payload_file = (
            root / "data" / "releases" / version / "payload" / "accepted_clips.json"
        )
        payload_file.chmod(payload_file.stat().st_mode | 0o200)

        with pytest.raises(DataPipelineError):
            run_release_validate(root, version=version)

        # 失败情形同样落盘报告：sealed 检查如实记录未通过，整体 fail-closed
        report_path = root / "data" / "reports" / f"{version}.validation.json"
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["checks"]["sealed_release"]["passed"] is False
        assert report["passed"] is False

    def test_validate_with_explicit_version(self, tmp_path: Path) -> None:
        root, version = self._released_root(tmp_path)
        result = run_release_validate(root, version=version)
        assert result.report["version"] == version

    def test_validate_without_release_blocked(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        with pytest.raises(DataPipelineError):
            run_release_validate(root)

    def test_validate_unknown_version_blocked(self, tmp_path: Path) -> None:
        root, _ = self._released_root(tmp_path)
        with pytest.raises(DataPipelineError):
            run_release_validate(root, version="data-v4.1-r99")


# M3a Test List: strict envelope/recursive duplicate keys; explicit batch/project
# binding; complete pinned file inventory; missing, escaped or changed inputs;
# no writes, probes or subprocesses; successful read preserves file bytes.
@pytest.fixture()
def pinned_inputs(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()

    def pin(name, content=b'fixture'):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {'path': name, 'size_bytes': len(content),
                'sha256': hashlib.sha256(content).hexdigest()}

    doc = {
        'schema': 'tensile-data/inputs/v1', 'batch': 'batch-001',
        'project_root': str(project),
        'source': {
            'videos': [{'video_id': 'video_0001', **pin('videos/video_0001.mp4')}],
            'annotations': {'tags': pin('annotations/all_videos_tag.csv'),
                            'mapping': pin('annotations/video_mapping.csv')},
        },
        'split': pin('split.json'), 'roi_decisions': pin('roi.json'),
        'media': {'config': pin('media.yaml'),
                  'preprocessor': {'kind': 'minicpm', 'config': pin('preprocessor.json')}},
        'contract': pin('contract.json'),
    }
    path = tmp_path / 'inputs.yaml'
    path.write_text(yaml.safe_dump(doc), encoding='utf-8')
    return path, doc, project


def _load_pinned(path, batch='batch-001'):
    from versioning.data_pipeline import load_data_inputs
    return load_data_inputs(path, batch=batch)


def _save_pinned(path, doc):
    path.write_text(yaml.safe_dump(doc), encoding='utf-8')


class TestPinnedDataInputs:
    def test_load_is_read_only_and_preserves_explicit_inventory(self, pinned_inputs, monkeypatch):
        path, doc, project = pinned_inputs
        before = {p: p.read_bytes() for p in project.rglob('*') if p.is_file()}
        def forbid(*args, **kwargs):
            pytest.fail('input loading must not write or launch media processing')
        monkeypatch.setattr(Path, 'mkdir', forbid)
        monkeypatch.setattr(Path, 'write_bytes', forbid)
        monkeypatch.setattr(Path, 'write_text', forbid)
        monkeypatch.setattr('subprocess.run', forbid)
        loaded = _load_pinned(path)
        assert loaded.project_root == project
        assert loaded.batch == doc['batch']
        assert loaded.config_path == path
        assert loaded.config_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert loaded.videos[0].video_id == 'video_0001'
        assert loaded.videos[0].file.path == project / 'videos/video_0001.mp4'
        assert loaded.preprocessor_kind == 'minicpm'
        assert {p: p.read_bytes() for p in before} == before
        assert set(loaded.dependencies) == {path, *before}

    @pytest.mark.parametrize('field', ['schema', 'batch', 'project_root', 'source', 'split', 'roi_decisions', 'media', 'contract'])
    def test_required_fields(self, pinned_inputs, field):
        path, doc, _ = pinned_inputs
        del doc[field]
        _save_pinned(path, doc)
        with pytest.raises(StageInputError, match=field):
            _load_pinned(path)

    @pytest.mark.parametrize('location', [(), ('source',), ('source', 'annotations'), ('media',), ('media', 'preprocessor'), ('split',)])
    def test_unknown_fields(self, pinned_inputs, location):
        path, doc, _ = pinned_inputs
        target = doc
        for key in location:
            target = target[key]
        target['LATEST'] = 'ignored?'
        _save_pinned(path, doc)
        with pytest.raises(StageInputError, match='LATEST'):
            _load_pinned(path)

    @pytest.mark.parametrize('text', ['[]', 'null', 'true', 'schema: a\nschema: b',
                                     'source:\n  videos: []\n  videos: []',
                                     '? [complex, key]\n: value', 'x: &x {x: *x}',
                                     'x: &x {}\ny: {<<: *x}'])
    def test_malformed_or_ambiguous_yaml(self, pinned_inputs, text):
        path, _, _ = pinned_inputs
        path.write_text(text)
        with pytest.raises(StageInputError):
            _load_pinned(path)

    @pytest.mark.parametrize('field,value', [('schema', 'unknown'), ('batch', 'other'),
                                           ('batch', '../escape'), ('batch', True),
                                           ('project_root', ''), ('project_root', '.'),
                                           ('project_root', '/no/such/project')])
    def test_envelope_binding(self, pinned_inputs, field, value):
        path, doc, _ = pinned_inputs
        doc[field] = value
        _save_pinned(path, doc)
        with pytest.raises(StageInputError, match=field):
            _load_pinned(path)

    @pytest.mark.parametrize('ref_name', ['tags', 'mapping', 'split', 'roi_decisions', 'media', 'preprocessor', 'contract', 'video'])
    def test_every_role_is_content_pinned(self, pinned_inputs, ref_name):
        path, doc, project = pinned_inputs
        refs = {**doc['source']['annotations'], 'split': doc['split'],
                'roi_decisions': doc['roi_decisions'], 'media': doc['media']['config'],
                'preprocessor': doc['media']['preprocessor']['config'],
                'contract': doc['contract'], 'video': doc['source']['videos'][0]}
        (project / refs[ref_name]['path']).write_bytes(b'changed')
        with pytest.raises(StageInputError, match='size_bytes|sha256'):
            _load_pinned(path)

    @pytest.mark.parametrize('field,value', [('path', ''), ('path', '../outside'), ('path', '/outside'),
        ('size_bytes', True), ('size_bytes', -1), ('size_bytes', 1.5),
        ('sha256', 'abc'), ('sha256', 'A' * 64), ('sha256', 123)])
    def test_bad_file_reference(self, pinned_inputs, field, value):
        path, doc, _ = pinned_inputs
        doc['split'][field] = value
        _save_pinned(path, doc)
        with pytest.raises(StageInputError, match=field):
            _load_pinned(path)

    def test_same_size_drift(self, pinned_inputs):
        path, doc, project = pinned_inputs
        (project / doc['split']['path']).write_bytes(b'changed')  # seven bytes, like fixture
        with pytest.raises(StageInputError, match='sha256'):
            _load_pinned(path)

    @pytest.mark.parametrize('mode', ['missing', 'directory', 'symlink'])
    def test_non_regular_input(self, pinned_inputs, mode):
        path, doc, project = pinned_inputs
        source = project / doc['split']['path']
        source.unlink()
        if mode == 'directory':
            source.mkdir()
        elif mode == 'symlink':
            source.symlink_to(project / 'roi.json')
        with pytest.raises(StageInputError):
            _load_pinned(path)

    @pytest.mark.parametrize('mode', ['empty', 'duplicate', 'id_mismatch', 'bad_id', 'not_list'])
    def test_video_inventory_binding(self, pinned_inputs, mode):
        path, doc, _ = pinned_inputs
        videos = doc['source']['videos']
        if mode == 'empty':
            videos.clear()
        elif mode == 'duplicate':
            videos.append(dict(videos[0]))
        elif mode == 'id_mismatch':
            videos[0]['video_id'] = 'video_0002'
        elif mode == 'bad_id':
            videos[0]['video_id'] = '../video'
        else:
            doc['source']['videos'] = {}
        _save_pinned(path, doc)
        with pytest.raises(StageInputError):
            _load_pinned(path)

    @pytest.mark.parametrize('value', ['', {}, None, True])
    def test_preprocessor_not_silently_defaulted(self, pinned_inputs, value):
        path, doc, _ = pinned_inputs
        doc['media']['preprocessor']['kind'] = value
        _save_pinned(path, doc)
        with pytest.raises(StageInputError, match='preprocessor'):
            _load_pinned(path)

    def test_missing_config(self, tmp_path):
        with pytest.raises(StageInputError):
            _load_pinned(tmp_path / 'missing.yaml')


# M3b Test List: real CSV governance and supplied splits; exact inventories;
# byte-identical inputs copied; pin drift during probe refuses publication;
# safe repeat and conflict; no legacy source builder/publisher or derived IDs.
@pytest.fixture()
def source_inputs(pinned_inputs):
    import csv
    from pipeline.source_bootstrap import TAG_COLUMNS, MAPPING_COLUMNS
    path, doc, project = pinned_inputs

    def rewrite(ref, content):
        (project / ref['path']).write_bytes(content)
        ref.update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())

    def csv_bytes(columns, rows):
        import io
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode()

    tag = dict.fromkeys(TAG_COLUMNS, '')
    tag.update(id='video_0001', video_path='videos/video_0001.mp4',
               断裂模式='脆性断裂', 材料类型='金属', 清晰度='480P', 断裂位置='中间',
               断裂时间点='4', 断裂帧数='120', 视频时长='10', 视频帧率='30',
               视频总帧数='300', has_fracture='FALSE', is_abnormal='FALSE')
    mapping = dict.fromkeys(MAPPING_COLUMNS, '')
    mapping.update(标准化文件名='video_0001.mp4', 原始文件名='original.mp4',
                   来源目录='original', 材料类别='金属', 状态='existing',
                   duration='10', resolution='640x480', codec='h264')
    rewrite(doc['source']['annotations']['tags'], csv_bytes(TAG_COLUMNS, [tag]))
    rewrite(doc['source']['annotations']['mapping'], csv_bytes(MAPPING_COLUMNS, [mapping]))
    splits = {'test': []}
    for fold in range(3):
        splits[f'fold_{fold}_train'] = ['video_0001']
        splits[f'fold_{fold}_val'] = []
    split = {'schema': 'tensile-data/split-inputs/v1', 'batch': doc['batch'],
             'source_sha256': {'video_0001': doc['source']['videos'][0]['sha256']},
             'splits': splits}
    rewrite(doc['split'], json.dumps(split).encode())
    contract = Path(__file__).resolve().parents[2] / 'pipeline/contracts/tensile_vlm_v4_1.json'
    rewrite(doc['contract'], contract.read_bytes())
    _save_pinned(path, doc)
    return path, doc, project, rewrite


def _source_probe(path):
    return dict(width=640, height=480, codec_name='h264', fps_num=30, fps_den=1,
                fps=30.0, duration_us=10000000, total_frames=300)


def _run_real_source(root, inputs, probe=_source_probe):
    from versioning.data_pipeline import run_input_source
    return run_input_source(root, inputs_path=inputs, batch='batch-001', probe=probe)


class TestInputSource:
    def test_source_preserves_governance_and_explicit_splits(self, source_inputs, tmp_path, monkeypatch):
        from pipeline import source_bootstrap
        path, doc, project, _ = source_inputs
        def forbidden(*args, **kwargs):
            pytest.fail('legacy builder/publisher must not be used')
        for name in ('build_source_snapshot', 'materialize_source_snapshot', 'materialize_split_snapshot', 'stratified_split'):
            monkeypatch.setattr(source_bootstrap, name, forbidden)
        root = tmp_path / 'store'
        result = _run_real_source(root, path)
        assert result.stage == 'source'
        output = root / 'data/working/batch-001/source'
        manifest = json.loads((output / 'source_manifest.json').read_text())
        record = manifest['records'][0]
        assert record['has_fracture_canonical'] is True
        assert record['is_label_conflict'] is True
        assert record['event_frame_effective'] == 120
        assert manifest['splits'] == json.loads((project / 'split.json').read_text())['splits']
        assert (output / 'media/video_0001.mp4').read_bytes() == (project / 'videos/video_0001.mp4').read_bytes()
        assert manifest['inputs_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert not any(p.name in {'LATEST', 'index.json'} for p in root.rglob('*'))
        assert 'source-snapshot-' not in (output / 'source_manifest.json').read_text()
        assert len(manifest['files']) == 1

    @pytest.mark.parametrize('problem', ['overlap', 'unknown', 'missing', 'duplicate', 'binding', 'batch', 'extra'])
    def test_invalid_split_writes_nothing(self, source_inputs, tmp_path, problem):
        path, doc, project, rewrite = source_inputs
        split = json.loads((project / 'split.json').read_text())
        if problem == 'overlap':
            split['splits']['test'] = ['video_0001']
        elif problem == 'unknown':
            split['splits']['fold_0_train'] = ['video_0999']
        elif problem == 'missing':
            del split['splits']['fold_0_val']
        elif problem == 'duplicate':
            split['splits']['fold_0_train'] *= 2
        elif problem == 'binding':
            split['source_sha256']['video_0001'] = '0' * 64
        elif problem == 'batch':
            split['batch'] = 'wrong'
        else:
            split['LATEST'] = 'anything'
        rewrite(doc['split'], json.dumps(split).encode())
        _save_pinned(path, doc)
        root = tmp_path / 'store'
        with pytest.raises(StageInputError):
            _run_real_source(root, path)
        assert not root.exists()

    @pytest.mark.parametrize('problem', ['missing', 'duplicate', 'extra', 'path', 'mapping_state'])
    def test_invalid_annotations_writes_nothing(self, source_inputs, tmp_path, problem):
        path, doc, project, rewrite = source_inputs
        role = 'mapping' if problem == 'mapping_state' else 'tags'
        ref = doc['source']['annotations'][role]
        text = (project / ref['path']).read_text()
        lines = text.splitlines()
        if problem == 'missing':
            text = lines[0] + '\n'
        elif problem == 'duplicate':
            text += lines[1] + '\n'
        elif problem == 'extra':
            text += lines[1].replace('video_0001', 'video_0002') + '\n'
        elif problem == 'path':
            text = text.replace('videos/video_0001.mp4', 'videos/video_9999.mp4')
        else:
            text = text.replace('existing', 'not_valid')
        rewrite(ref, text.encode())
        _save_pinned(path, doc)
        root = tmp_path / 'store'
        with pytest.raises(StageInputError):
            _run_real_source(root, path)
        assert not root.exists()

    def test_probe_failure_has_no_published_snapshot(self, source_inputs, tmp_path):
        path, _, _, _ = source_inputs
        def fail(_):
            raise RuntimeError('probe unavailable')
        root = tmp_path / 'store'
        with pytest.raises(StageInputError, match='probe'):
            _run_real_source(root, path, fail)
        assert not root.exists()

    def test_drift_during_probe_has_no_published_snapshot(self, source_inputs, tmp_path):
        path, _, project, _ = source_inputs
        def mutate(video):
            (project / 'videos/video_0001.mp4').write_bytes(b'changed')
            return _source_probe(video)
        root = tmp_path / 'store'
        with pytest.raises(StageInputError):
            _run_real_source(root, path, mutate)
        assert not root.exists()

    def test_repeat_verifies_outputs_and_refuses_conflict(self, source_inputs, tmp_path):
        path, _, _, _ = source_inputs
        root = tmp_path / 'store'
        first = _run_real_source(root, path)
        again = _run_real_source(root, path)
        assert first.outputs == again.outputs
        media = root / 'data/working/batch-001/source/media/video_0001.mp4'
        media.write_bytes(b'tampered')
        with pytest.raises(StageInputError):
            _run_real_source(root, path)
        assert media.read_bytes() == b'tampered'

    def test_input_drift_while_waiting_for_stage_lock_is_rejected(self, source_inputs, tmp_path, monkeypatch):
        import fcntl
        import threading
        from concurrent.futures import ThreadPoolExecutor
        path, _, project, _ = source_inputs
        root = tmp_path / 'store'
        _run_real_source(root, path)
        lock_path = root / 'data/working/batch-001/.source.lock'
        flock = fcntl.flock
        waiting = threading.Event()
        def observed_lock(fd, operation):
            waiting.set()
            return flock(fd, operation)
        with lock_path.open('a+') as held, ThreadPoolExecutor(max_workers=1) as pool:
            flock(held.fileno(), fcntl.LOCK_EX)
            monkeypatch.setattr(fcntl, 'flock', observed_lock)
            future = pool.submit(_run_real_source, root, path)
            try:
                assert waiting.wait(5), 'source did not reach stage lock'
                (project / 'videos/video_0001.mp4').write_bytes(b'changed while waiting')
            finally:
                flock(held.fileno(), fcntl.LOCK_UN)
            with pytest.raises(StageInputError):
                future.result(timeout=5)


# M3c Test List: frozen human ROI has full coverage and source/geometry binding;
# crop commands use existing policy; actual resolution/frame count/duration gate;
# publication remains atomic and source inputs/previous outputs are preserved.
@pytest.fixture()
def roi_inputs(source_inputs):
    from pipeline.scripts import roi_annotation_app as app
    path, doc, project, rewrite = source_inputs
    video = project / 'videos/video_0001.mp4'
    decision = app.build_decision(
        video_id='video_0001', video_path=video, mode=app.MODE_NO_CROP,
        review_status=app.STATUS_APPROVED,
        margins=dict(top=0.0, right=0.0, bottom=0.0, left=0.0),
        source_width=640, source_height=480, reviewed_timestamps=[0.0, 4.0, 9.0],
        source_sha256=doc['source']['videos'][0]['sha256'],
        source_video_reference='videos/video_0001.mp4',
        visibility_checks={key: True for key in app.VISIBILITY_CHECK_KEYS})
    payload = dict(schema_version=app.SCHEMA_VERSION, roi_policy_version=app.ROI_POLICY_VERSION,
                   decisions=[decision])
    rewrite(doc['roi_decisions'], json.dumps(payload).encode())
    _save_pinned(path, doc)
    return path, doc, project, rewrite


def _roi_probe(path):
    from pipeline.roi_media import VideoProbe
    width, height = (640, 480) if path.parent.parent.name == 'source' else (642, 856)
    return VideoProbe(width=width, height=height, frame_rate='30/1',
                      nominal_frame_rate='30/1', frame_count=300, duration=10.0)


def _fake_input_media(command, label):
    Path(command[-1]).write_bytes(b'real-media-command-fixture')


def _run_real_roi(root, path, probe=_roi_probe):
    from versioning.data_pipeline import run_input_roi
    return run_input_roi(root, inputs_path=path, batch='batch-001', probe=probe)


class TestInputRoi:
    def test_real_geometry_and_timeline_are_recorded(self, roi_inputs, tmp_path, monkeypatch):
        from pipeline import roi_media, roi_manifest
        from versioning import data_pipeline as dp
        path, _, project, _ = roi_inputs
        root = tmp_path / 'store'
        _run_real_source(root, path)
        calls = []
        def execute(command, label):
            calls.append(command)
            _fake_input_media(command, label)
        monkeypatch.setattr(dp, '_execute_input_media', execute)
        def forbid(*args, **kwargs):
            pytest.fail('legacy ROI publisher must not run')
        monkeypatch.setattr(roi_media, 'materialize_plan', forbid)
        monkeypatch.setattr(roi_manifest, 'build_roi_manifest_bundle', forbid)
        result = _run_real_roi(root, path)
        output = root / 'data/working/batch-001/roi'
        manifest = json.loads((output / 'roi_manifest.json').read_text())
        assert result.stage == 'roi'
        assert manifest['records'][0]['event_frame_effective'] == 120
        assert manifest['videos'][0]['output_resolution'] == [642, 856]
        assert manifest['videos'][0]['frame_count'] == 300
        assert calls[0][calls[0].index('-vf') + 1] == 'pad=642:856:1:188:color=black,setsar=1'
        frozen = json.loads((output / 'roi_decisions.frozen.json').read_text())
        assert frozen == json.loads((project / 'roi.json').read_text())
        assert not any(p.name in {'LATEST', 'index.json'} for p in root.rglob('*'))

    @pytest.mark.parametrize('problem', ['missing', 'extra', 'pending', 'hash', 'path', 'geometry', 'resolution', 'timestamps'])
    def test_invalid_roi_blocks_before_media_execution(self, roi_inputs, tmp_path, monkeypatch, problem):
        from versioning import data_pipeline as dp
        path, doc, project, rewrite = roi_inputs
        payload = json.loads((project / 'roi.json').read_text())
        decision = payload['decisions'][0]
        if problem == 'missing':
            payload['decisions'] = []
        elif problem == 'extra':
            payload['decisions'].append({**decision, 'source_video_id': 'video_0999'})
        elif problem == 'pending':
            decision['review_status'] = 'needs_review'
        elif problem == 'hash':
            decision['source_sha256'] = '0' * 64
        elif problem == 'path':
            decision['source_video_path'] = 'other/video_0001.mp4'
        elif problem == 'geometry':
            decision['pixel_box']['width'] -= 2
        elif problem == 'resolution':
            decision['source_resolution'] = [480, 640]
        else:
            decision['reviewed_timestamps'] = [float('nan')]
        rewrite(doc['roi_decisions'], json.dumps(payload).encode())
        _save_pinned(path, doc)
        root = tmp_path / 'store'
        _run_real_source(root, path)
        def forbidden(*args, **kwargs):
            pytest.fail('invalid ROI must fail before any media write')
        monkeypatch.setattr(dp, '_execute_input_media', forbidden)
        with pytest.raises(StageInputError):
            _run_real_roi(root, path)
        assert not (root / 'data/working/batch-001/roi').exists()

    @pytest.mark.parametrize('problem', ['frame_count', 'duration', 'nan_duration', 'infinite_duration', 'zero_duration', 'resolution', 'rate', 'execution'])
    def test_failed_real_media_gate_never_publishes(self, roi_inputs, tmp_path, monkeypatch, problem):
        from dataclasses import replace
        from versioning import data_pipeline as dp
        path, _, _, _ = roi_inputs
        root = tmp_path / 'store'
        _run_real_source(root, path)
        def execute(command, label):
            if problem == 'execution':
                raise StageInputError('ffmpeg failed')
            _fake_input_media(command, label)
        def probe(target):
            result = _roi_probe(target)
            if target.parent.parent.name == 'source':
                return result
            changes = {'frame_count': {'frame_count': 299}, 'duration': {'duration': 9.0},
                       'resolution': {'width': 640}, 'rate': {'nominal_frame_rate': '24/1'},
                       'nan_duration': {'duration': float('nan')},
                       'infinite_duration': {'duration': float('inf')},
                       'zero_duration': {'duration': 0.0}}
            return replace(result, **changes.get(problem, {}))
        monkeypatch.setattr(dp, '_execute_input_media', execute)
        with pytest.raises(StageInputError):
            _run_real_roi(root, path, probe)
        assert not (root / 'data/working/batch-001/roi').exists()
        assert not list((root / 'data/working/batch-001').glob('.roi-*'))

    def test_upstream_drift_while_waiting_for_roi_lock_is_rejected(self, roi_inputs, tmp_path, monkeypatch):
        import fcntl
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from versioning import data_pipeline as dp
        path, _, _, _ = roi_inputs
        root = tmp_path / 'store'
        _run_real_source(root, path)
        monkeypatch.setattr(dp, '_execute_input_media', _fake_input_media)
        _run_real_roi(root, path)
        flock = fcntl.flock
        waiting = threading.Event()
        def observed_lock(fd, operation):
            waiting.set()
            return flock(fd, operation)
        lock_path = root / 'data/working/batch-001/.roi.lock'
        with lock_path.open('a+') as held, ThreadPoolExecutor(max_workers=1) as pool:
            flock(held.fileno(), fcntl.LOCK_EX)
            monkeypatch.setattr(fcntl, 'flock', observed_lock)
            future = pool.submit(_run_real_roi, root, path)
            try:
                assert waiting.wait(5)
                (root / 'data/working/batch-001/source/media/video_0001.mp4').write_bytes(b'upstream changed')
            finally:
                flock(held.fileno(), fcntl.LOCK_UN)
            with pytest.raises(StageInputError):
                future.result(timeout=5)


# M3d — candidate planning and actual media/sampling adaptation.
@pytest.fixture()
def media_inputs(roi_inputs):
    path, doc, project, rewrite = roi_inputs
    def pin(name, value):
        content = json.dumps(value, ensure_ascii=False).encode()
        ref = {'path': name}
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        rewrite(ref, content)
        return ref
    v3_path = Path(__file__).resolve().parents[2] / 'pipeline/contracts/tensile_vlm_v3.json'
    v3 = pin('candidate_contract.json', json.loads(v3_path.read_text()))
    development = pin('development_reference.json', {'reference_id': 'fixture-reference',
        'source_inventory': ['video_0001'], 'records': []})
    test = pin('test_reference.json', {'reference_id': 'fixture-reference', 'source_inventory': [], 'records': []})
    media = {'schema': 'tensile-data/media-inputs/v1', 'candidate_contract': v3,
             'development_reference': development, 'test_reference': test}
    rewrite(doc['media']['config'], json.dumps(media).encode())
    config = pin('model/config.json', {})
    processor = pin('model/preprocessor_config.json', {})
    prep = {'schema': 'tensile-data/preprocessor-inputs/v1', 'model_root': 'model',
            'files': [config, processor], 'max_frames': 8, 'video_fps': 2.0,
            'expected_fingerprint': 'fixture:minicpm'}
    rewrite(doc['media']['preprocessor']['config'], json.dumps(prep).encode())
    _save_pinned(path, doc)
    return path, doc, project, rewrite


@pytest.fixture()
def media_runtime(monkeypatch):
    import re
    from versioning import data_pipeline as dp
    from pipeline import roi_media, v3_candidate_media
    from pipeline.preprocessing.adapter import FrameMapping
    calls = []
    def execute(command, label):
        calls.append(command)
        output = Path(command[-1])
        frame_count = 300
        if '-vf' in command:
            match = re.search(r'trim=start_frame=(\d+):end_frame=(\d+)', command[command.index('-vf')+1])
            if match:
                frame_count = int(match[2]) - int(match[1])
        output.write_text(json.dumps({'frames': frame_count}))
    def probe(path):
        from pipeline.roi_media import VideoProbe
        if path.parent.parent.name == 'source':
            return _roi_probe(path)
        try:
            n = json.loads(path.read_text())['frames']
        except (ValueError, KeyError):
            n = 300
        return VideoProbe(width=642, height=856, frame_rate='30/1', nominal_frame_rate='30/1',
                          frame_count=n, duration=n / 30)
    class Processor:
        def fingerprint(self):
            return 'fixture:minicpm'
        def sample(self, path, start, end):
            count = probe(Path(path)).frame_count
            frames = sorted({round(i * (count-1) / 7) for i in range(8)})
            return [FrameMapping(i, f, f/30) for i, f in enumerate(frames)]
    monkeypatch.setattr(dp, '_execute_input_media', execute)
    monkeypatch.setattr(dp, '_make_input_preprocessor', lambda *args: Processor())
    monkeypatch.setattr(roi_media, 'probe_video', probe)
    monkeypatch.setattr(v3_candidate_media, 'probe_video', probe)
    monkeypatch.setattr(v3_candidate_media, '_source_frame_timestamps',
                        lambda path: tuple(i/30 for i in range(probe(Path(path)).frame_count)))
    return calls, Processor, probe


def _run_real_subvideo(root, path):
    from versioning.data_pipeline import run_input_subvideo
    return run_input_subvideo(root, inputs_path=path, batch='batch-001')


class TestInputSubvideo:
    def test_real_candidate_policy_and_actual_frames_are_preserved(self, media_inputs, media_runtime, tmp_path, monkeypatch):
        from pipeline import v3_candidate_plan as planner, v3_candidate_media as media_api
        path, _, _, _ = media_inputs
        root = tmp_path / 'store'
        _run_real_source(root, path)
        _run_real_roi(root, path)
        def forbid(*args, **kwargs):
            pytest.fail('legacy candidate builder/publisher forbidden')
        monkeypatch.setattr(planner, 'build_candidate_plan', forbid)
        monkeypatch.setattr(planner, 'materialize_candidate_plan', forbid)
        monkeypatch.setattr(media_api, 'materialize_media_plan', forbid)
        result = _run_real_subvideo(root, path)
        output = root / 'data/working/batch-001/subvideo'
        manifest = json.loads((output / 'subvideo_manifest.json').read_text())
        assert result.stage == 'subvideo'
        assert len(manifest['candidates']) > 2
        roi = json.loads((root / 'data/working/batch-001/roi/roi_manifest.json').read_text())
        expected = planner._raw_candidates_for_source(roi['records'][0], [])
        actual = manifest['planned_candidates']
        assert [(r['start_frame'], r['end_frame'], r['candidate_v3_labels']) for r in actual] == [
            (r['start_frame'], r['end_frame'], r['candidate_v3_labels']) for r in expected]
        for candidate in manifest['candidates']:
            assert candidate['processor_fingerprint'] == 'fixture:minicpm'
            assert len(candidate['actual_frame_mapping']) == len(candidate['frame_artifacts']) == 8
            assert (output / candidate['video_path']).is_file()
            assert all((output / f['path']).is_file() for f in candidate['frame_artifacts'])
        assert not any(p.name in {'LATEST', 'index.json'} for p in root.rglob('*'))
        assert 'candidate-plan-' not in json.dumps(manifest)

    @pytest.mark.parametrize('problem', ['missing_reference', 'reference_drift', 'inventory', 'contract', 'processor_pin', 'fingerprint'])
    def test_configuration_failures_never_publish(self, media_inputs, media_runtime, tmp_path, monkeypatch, problem):
        from versioning import data_pipeline as dp
        path, doc, project, rewrite = media_inputs
        media = json.loads((project / 'media.yaml').read_text())
        if problem == 'missing_reference':
            del media['development_reference']
            rewrite(doc['media']['config'], json.dumps(media).encode())
        elif problem == 'reference_drift':
            (project / 'development_reference.json').write_text('{}')
        elif problem == 'inventory':
            ref = json.loads((project / 'development_reference.json').read_text())
            ref['source_inventory'] = []
            rewrite(media['development_reference'], json.dumps(ref).encode())
            rewrite(doc['media']['config'], json.dumps(media).encode())
        elif problem == 'contract':
            rewrite(media['candidate_contract'], b'{}')
            rewrite(doc['media']['config'], json.dumps(media).encode())
        elif problem == 'processor_pin':
            (project / 'model/config.json').write_text('{"changed":true}')
        else:
            class WrongProcessor:
                def fingerprint(self):
                    return 'wrong'
            monkeypatch.setattr(dp, '_make_input_preprocessor', lambda *args: WrongProcessor())
        _save_pinned(path, doc)
        root = tmp_path / 'store'
        _run_real_source(root, path)
        _run_real_roi(root, path)
        with pytest.raises(StageInputError):
            _run_real_subvideo(root, path)
        assert not (root / 'data/working/batch-001/subvideo').exists()

    def test_actual_sampling_gate_excludes_failed_candidates(self, media_inputs, media_runtime, tmp_path, monkeypatch):
        from versioning import data_pipeline as dp
        from pipeline.preprocessing.adapter import FrameMapping
        path, _, _, _ = media_inputs
        root = tmp_path / 'store'
        _run_real_source(root, path)
        _run_real_roi(root, path)
        class NoTransition:
            def fingerprint(self):
                return 'fixture:minicpm'
            def sample(self, path, start, end):
                return [FrameMapping(0, 0, 0.0)]
        monkeypatch.setattr(dp, '_make_input_preprocessor', lambda *args: NoTransition())
        _run_real_subvideo(root, path)
        manifest = json.loads((root / 'data/working/batch-001/subvideo/subvideo_manifest.json').read_text())
        assert any(row['reason'] == 'transition_missing_post_event_sample' for row in manifest['excluded'])
        assert all(row['candidate_v3_labels']['clip_state'] != '发生断裂' for row in manifest['candidates'])

class TestInputSubvideoBoundaries:
    def test_test_scope_is_actually_materialized(self, media_inputs, media_runtime, tmp_path):
        path, doc, project, rewrite = media_inputs
        split = json.loads((project / doc['split']['path']).read_text())
        split['splits'] = {name: (['video_0001'] if name == 'test' else []) for name in split['splits']}
        rewrite(doc['split'], json.dumps(split).encode())
        media = json.loads((project / doc['media']['config']['path']).read_text())
        for key, ids in [('development_reference', []), ('test_reference', ['video_0001'])]:
            reference = json.loads((project / media[key]['path']).read_text())
            reference['source_inventory'] = ids
            rewrite(media[key], json.dumps(reference).encode())
        rewrite(doc['media']['config'], json.dumps(media).encode()); _save_pinned(path, doc)
        root = tmp_path / 'store'
        _run_real_source(root, path); _run_real_roi(root, path); _run_real_subvideo(root, path)
        output = root / 'data/working/batch-001/subvideo'
        manifest = json.loads((output / 'subvideo_manifest.json').read_text())
        assert manifest['candidates'], 'test candidates require real media, not only a plan'
        assert all(c['scope'] == 'test_audit' for c in manifest['candidates'])
        assert all((output / c['video_path']).is_file() and c['actual_frame_mapping'] for c in manifest['candidates'])

    def test_processor_snapshot_modules_are_isolated_per_execution(self, media_inputs, media_runtime, tmp_path, monkeypatch):
        from versioning import data_pipeline as dp
        path, _, _, _ = media_inputs
        calls = []
        def create(*args):
            calls.append(args[-1].name)
            return media_runtime[1]()
        monkeypatch.setattr(dp, '_make_input_preprocessor', create)
        for name in ('first', 'second'):
            root = tmp_path / name
            _run_real_source(root, path); _run_real_roi(root, path); _run_real_subvideo(root, path)
        assert len(calls) == len(set(calls)) == 2
        assert all(name.isidentifier() for name in calls)

    @pytest.mark.parametrize('code_ref', ['other/repo--processing_minicpmv.MiniCPMVProcessor', 'missing_module.Processor'])
    def test_processor_cannot_load_unpinned_dynamic_code(self, media_inputs, code_ref):
        from versioning import data_pipeline as dp
        path, doc, project, rewrite = media_inputs
        prep = json.loads((project / doc['media']['preprocessor']['config']['path']).read_text())
        rewrite(prep['files'][1], json.dumps({'auto_map': {'AutoProcessor': code_ref}}).encode())
        rewrite(doc['media']['preprocessor']['config'], json.dumps(prep).encode()); _save_pinned(path, doc)
        with pytest.raises(StageInputError):
            dp._load_media_inputs(dp.load_data_inputs(path, batch='batch-001'))


# M3e — portable, complete human-review round trip.
@pytest.fixture()
def review_stage(media_inputs, media_runtime, tmp_path):
    path, _, _, _ = media_inputs
    root = tmp_path / 'store'
    _run_real_source(root, path)
    _run_real_roi(root, path)
    _run_real_subvideo(root, path)
    return root, path


def _review_return(package, destination):
    from pipeline.v4_1_review_workflow import new_decision
    from pipeline.v4_1_review_decisions import build_review_payload
    queue = json.loads((package / 'review_queue.json').read_text())
    records = [new_decision(row, status='approved', corrected_labels=None,
        historical_suggested_labels=None, historical_reference_ids=[], reviewer_notes='fixture review',
        reviewer_id='fixture-reviewer', reviewed_at='2026-09-12T12:00:00+08:00') for row in queue['candidates']]
    payload = {'schema': 'tensile-data/review-return/v1', 'batch': queue['batch'],
        'inputs_sha256': queue['inputs_sha256'],
        'export_sha256': hashlib.sha256((package / 'stage_manifest.json').read_bytes()).hexdigest(),
        'review': build_review_payload(records, batch_id=queue['batch'], created_at='2026-09-12T12:00:00+08:00')}
    destination.write_text(json.dumps(payload, ensure_ascii=False))
    return payload


class TestInputReview:
    def test_portable_complete_round_trip_preserves_proposals(self, review_stage, tmp_path):
        from versioning import data_pipeline as dp
        from pipeline.v4_1_review_workflow import _proposal
        root, path = review_stage
        result = dp.run_input_review_export(root, inputs_path=path, batch='batch-001')
        assert len(result.outputs) == 1
        package = result.outputs[0]
        queue = json.loads((package / 'review_queue.json').read_text())
        sub = json.loads((root / 'data/working/batch-001/subvideo/subvideo_manifest.json').read_text())
        expected = [c for c in sub['candidates'] if _proposal(c) is not None]
        assert expected and len(queue['candidates']) == len(expected)
        assert {c['candidate_id'] for c in queue['candidates']} == {c['candidate_id'] for c in expected}
        for c in queue['candidates']:
            assert c['candidate_v4_labels'] == _proposal(c)
            assert not Path(c['video_path']).is_absolute()
            assert (package / c['video_path']).is_file()
            assert all((package / f['path']).is_file() for f in c['frame_artifacts'])
        import shutil
        portable = tmp_path / 'mac-copy'
        shutil.copytree(package, portable)
        returned = tmp_path / 'returned.json'
        expected_return = _review_return(portable, returned)
        result = dp.run_input_review_import(root, inputs_path=path, batch='batch-001', results_path=returned)
        frozen = json.loads((result.outputs[0] / 'review_return.json').read_text())
        assert frozen == expected_return
        assert result.report['reviewed_count'] == len(expected)

    @pytest.mark.parametrize('problem', ['missing', 'extra', 'batch', 'export', 'media', 'timestamps',
                                        'proposal', 'pending', 'reviewer', 'drop_notes', 'same_correction'])
    def test_invalid_returns_do_not_publish(self, review_stage, tmp_path, problem):
        from versioning import data_pipeline as dp
        from pipeline.v4_1_review_decisions import build_review_payload
        root, path = review_stage
        package = dp.run_input_review_export(root, inputs_path=path, batch='batch-001').outputs[0]
        returned = tmp_path / 'returned.json'
        payload = _review_return(package, returned)
        records = payload['review']['decisions']
        if problem == 'missing': records.pop()
        elif problem == 'extra':
            row = dict(records[0]); row['clip_id'] = 'extra'; records.append(row)
        elif problem == 'batch': payload['batch'] = 'other'
        elif problem == 'export': payload['export_sha256'] = '0' * 64
        elif problem == 'media': records[0]['evidence']['media_sha256'] = '0' * 64
        elif problem == 'timestamps': records[0]['evidence']['actual_sampled_timestamps'] = []
        elif problem == 'proposal': records[0]['system_proposed_labels']['clip_state'] = '未断裂'
        elif problem == 'pending':
            records[0]['review_status'] = 'needs_review'; records[0]['effective_labels'] = None
        elif problem == 'reviewer': records[0]['reviewer_id'] = ' '
        elif problem == 'drop_notes':
            records[0]['review_status'] = 'dropped'; records[0]['effective_labels'] = None; records[0]['reviewer_notes'] = ''
        else:
            records[0]['review_status'] = 'corrected'
            records[0]['corrected_labels'] = records[0]['system_proposed_labels']
        returned.write_text(json.dumps(payload, ensure_ascii=False))
        with pytest.raises((dp.StageInputError, dp.ReviewGateError)):
            dp.run_input_review_import(root, inputs_path=path, batch='batch-001', results_path=returned)
        assert not (root / 'data/working/batch-001/review_import').exists()

# M3f — reviewed development release with real datasets.
@pytest.fixture()
def reviewed_inputs(review_stage, tmp_path):
    from versioning import data_pipeline as dp
    root, path = review_stage
    package = dp.run_input_review_export(root, inputs_path=path, batch='batch-001').outputs[0]
    returned = tmp_path / 'returned.json'
    _review_return(package, returned)
    dp.run_input_review_import(root, inputs_path=path, batch='batch-001', results_path=returned)
    return root, path


class TestInputRelease:
    def test_datasets_preserve_labels_media_and_source_splits(self, reviewed_inputs):
        from versioning import data_pipeline as dp
        from pipeline.v4_1_training_release import _dataset_row
        root, path = reviewed_inputs
        result = dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        assert len(result.outputs) >= 1
        release = root / 'data/releases/data-v4.1-r1'
        payload = release / 'payload'
        meta = json.loads((payload / 'metadata/training_candidates.json').read_text())
        contract = json.loads((payload / 'contract.json').read_text())
        assert meta['candidates']
        assert {'automatic_validation', 'human_review'} == {r['label_source'] for r in meta['candidates']}
        splits = json.loads((payload / 'splits.json').read_text())
        for fold in range(3):
            for name, directory in [('train', 'train'), ('val', 'validation')]:
                rows = [r for r in meta['candidates'] if r['source_video'] in splits[f'fold_{fold}_{name}']]
                actual = json.loads((payload / f'datasets/{directory}/fold_{fold}.json').read_text())
                assert actual == [_dataset_row({'_release_video_path': r['video_path']}, r['labels'], contract) for r in rows]
        assert all((payload / r['video_path']).is_file() for r in meta['candidates'])
        assert not any(r['source_video'] in splits['test'] for r in meta['candidates'])
        assert not any(p.stat().st_mode & 0o222 for p in payload.rglob('*'))
        report = dp.run_input_release_validate(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        assert report.report['passed'] is True
        assert not (root / 'data/release_pointer.json').exists()

    def test_tampered_release_fails_validation(self, reviewed_inputs):
        from versioning import data_pipeline as dp
        root, path = reviewed_inputs
        dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        target = root / 'data/releases/data-v4.1-r1/payload/dataset_info.json'
        assert target.exists()
        target.chmod(0o600); target.write_text('{}'); target.chmod(0o400)
        with pytest.raises(dp.DataPipelineError):
            dp.run_input_release_validate(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')

    def test_no_review_cannot_create_release(self, review_stage):
        from versioning import data_pipeline as dp
        root, path = review_stage
        with pytest.raises(dp.DataPipelineError):
            dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        assert not (root / 'data/releases').exists()

class TestInputReleaseBoundaries:
    @pytest.mark.parametrize('problem', ['protocol', 'release_link', 'extra_manifest'])
    def test_sealed_release_validation_rejects_unbound_changes(self, reviewed_inputs, problem):
        from versioning import data_pipeline as dp
        root, path = reviewed_inputs
        dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        release = root / 'data/releases/data-v4.1-r1'
        if problem == 'protocol':
            meta = yaml.safe_load((release / 'release.yaml').read_text()); meta['protocol'] = 'v9.9'
            (release / 'release.yaml').write_text(yaml.safe_dump(meta))
        elif problem == 'release_link':
            backup = release.with_name('moved'); release.chmod(0o700); release.rename(backup)
            backup.chmod(0o500); release.symlink_to(backup, target_is_directory=True)
        else:
            payload = release / 'payload'; payload.chmod(0o700)
            extra = payload / 'stage_manifest.json'; extra.write_text('{}'); extra.chmod(0o400); payload.chmod(0o500)
        with pytest.raises(dp.DataPipelineError):
            dp.run_input_release_validate(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')

    def test_collection_path_change_while_waiting_does_not_publish(self, reviewed_inputs, tmp_path, monkeypatch):
        from versioning import data_pipeline as dp
        root, path = reviewed_inputs
        (root / 'data/releases').mkdir()
        outside = tmp_path / 'outside'; outside.mkdir()
        calls = []
        original = dp.fcntl.flock
        def wait(lock, operation):
            calls.append(lock)
            if len(calls) == 2:
                (root / 'data/releases').rmdir()
                (root / 'data/releases').symlink_to(outside, target_is_directory=True)
            return original(lock, operation)
        monkeypatch.setattr(dp.fcntl, 'flock', wait)
        with pytest.raises(dp.DataPipelineError):
            dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        assert list(outside.iterdir()) == []

    def test_existing_version_is_a_conflict_even_when_identical(self, reviewed_inputs):
        from versioning import data_pipeline as dp
        root, path = reviewed_inputs
        dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')
        with pytest.raises(dp.ReleaseConflict):
            dp.run_input_release(root, inputs_path=path, batch='batch-001', version='data-v4.1-r1')


# M3g — portable review UI adapter and persisted decisions.
class TestInputReviewWorkspace:
    def test_portable_package_load_and_draft_round_trip(self, review_stage, tmp_path):
        from versioning import data_pipeline as dp
        import shutil
        root, path = review_stage
        exported = dp.run_input_review_export(root, inputs_path=path, batch='batch-001').outputs[0]
        package = tmp_path / 'portable'
        shutil.copytree(exported, package)
        identity, candidates, references = dp.load_input_review_package(package)
        assert candidates
        assert all(Path(c['_resolved_video_path']).is_file() for c in candidates)
        result_path = tmp_path / 'review.json'
        payload = _review_return(package, result_path)
        decisions = {r['clip_id']: r for r in payload['review']['decisions']}
        draft = tmp_path / 'draft.json'
        dp.save_input_review_draft(draft, identity, {candidates[0]['candidate_id']: decisions[candidates[0]['candidate_id']]})
        assert len(dp.load_input_review_draft(draft, identity)) == 1
        dp.save_input_review_draft(draft, identity, decisions)
        result = dp.freeze_input_review_workspace(tmp_path / 'result', identity, decisions)
        assert result.is_file()
        dp.run_input_review_import(root, inputs_path=path, batch='batch-001', results_path=result)

    def test_changed_portable_media_cannot_open(self, review_stage):
        from versioning import data_pipeline as dp
        root, path = review_stage
        package = dp.run_input_review_export(root, inputs_path=path, batch='batch-001').outputs[0]
        next(package.rglob('*.mp4')).write_bytes(b'changed')
        with pytest.raises(dp.DataPipelineError):
            dp.load_input_review_package(package)

    def test_ui_rejects_partial_selection_even_zero_limit(self, tmp_path):
        from pipeline.scripts.review_candidates_app import _parse_args
        with pytest.raises(SystemExit):
            _parse_args(['--versioning-package', str(tmp_path / 'package'), '--reviewer-id', 'reviewer',
                         '--draft', str(tmp_path / 'draft.json'), '--output-root', str(tmp_path / 'out'), '--limit', '0'])

class TestInputReviewApp:
    def test_ui_completes_fixture_review_into_bound_return(self, media_inputs, media_runtime, tmp_path, monkeypatch):
        from streamlit.testing.v1 import AppTest
        from PIL import Image
        from versioning import data_pipeline as dp
        import sys
        original = dp._execute_input_media
        def execute(command, label):
            original(command, label)
            if command[-1].endswith('.jpg'):
                Image.new('RGB', (2, 2), 'gray').save(command[-1])
        monkeypatch.setattr(dp, '_execute_input_media', execute)
        path = media_inputs[0]; root = tmp_path / 'store'
        _run_real_source(root, path); _run_real_roi(root, path); _run_real_subvideo(root, path)
        package = dp.run_input_review_export(root, inputs_path=path, batch='batch-001').outputs[0]
        output = tmp_path / 'review-output'
        script = Path(__file__).resolve().parents[2] / 'pipeline/scripts/review_candidates_app.py'
        monkeypatch.setattr(sys, 'argv', [str(script), '--versioning-package', str(package),
            '--reviewer-id', 'fixture-reviewer', '--draft', str(tmp_path / 'draft.json'), '--output-root', str(output)])
        app = AppTest.from_file(str(script)).run(timeout=20)
        assert not app.exception
        count = len(json.loads((package / 'review_queue.json').read_text())['candidates'])
        for _ in range(count):
            [button for button in app.button if button.label == '批准'][0].click()
            app.run(timeout=20)
            assert not app.exception
        returned = output / 'review_return.json'
        assert returned.is_file()
        dp.run_input_review_import(root, inputs_path=path, batch='batch-001', results_path=returned)


class TestInputReviewWorkspaceBoundaries:
    @pytest.mark.parametrize('problem', ['overwrite_frozen', 'traversal_into_package'])
    def test_workspace_preserves_package_and_frozen_result(self, review_stage, tmp_path, problem):
        from versioning import data_pipeline as dp
        root, path = review_stage
        package = dp.run_input_review_export(root, inputs_path=path, batch='batch-001').outputs[0]
        identity, _, _ = dp.load_input_review_package(package)
        returned = tmp_path / 'return.json'
        payload = _review_return(package, returned)
        decisions = {r['clip_id']: r for r in payload['review']['decisions']}
        if problem == 'overwrite_frozen':
            output = dp.freeze_input_review_workspace(tmp_path / 'final', identity, decisions)
            next(iter(decisions.values()))['reviewer_notes'] = 'changed'
            with pytest.raises(dp.ReviewGateError):
                dp.save_input_review_draft(output, identity, decisions)
        else:
            sibling = package.parent / 'sibling'; sibling.mkdir()
            output = sibling / '..' / package.name / 'draft.json'
            with pytest.raises(dp.ReviewGateError):
                dp.save_input_review_draft(output, identity, decisions)
            assert not (package / 'draft.json').exists()


# M3h — explicit CLI routing without the synthetic data path.
class TestInputCli:
    def test_source_requires_explicit_inputs(self, tmp_path):
        from versioning.cli import main
        root = tmp_path / 'store'
        (root / 'data/raw/batch-001').mkdir(parents=True)
        (root / 'data/raw/batch-001/fake.mp4').write_bytes(b'fake')
        assert main(['data', 'source', '--root', str(root), '--batch', 'batch-001']) == 2
        assert not (root / 'data/working').exists()

    def test_all_seven_commands_use_real_adapters(self, media_inputs, media_runtime, tmp_path, monkeypatch):
        from versioning.cli import main
        from pipeline import source_bootstrap
        monkeypatch.setattr(source_bootstrap, 'probe_video', _source_probe)
        path, _, _, _ = media_inputs
        root = tmp_path / 'store'
        common = ['--root', str(root), '--batch', 'batch-001', '--inputs', str(path)]
        for stage in ('source', 'roi', 'subvideo', 'review_export'):
            assert main(['data', stage, *common]) == 0
        returned = tmp_path / 'returned.json'
        _review_return(root / 'data/working/batch-001/review_export', returned)
        assert main(['data', 'review_import', *common, '--results', str(returned)]) == 0
        assert main(['data', 'release', *common, '--version', 'data-v4.1-r1']) == 0
        assert main(['data', 'release_validate', *common, '--version', 'data-v4.1-r1']) == 0
        assert not (root / 'data/release_pointer.json').exists()

class TestInputDvcConfiguration:
    def test_all_stages_track_explicit_and_nested_inputs(self, media_inputs, tmp_path):
        from versioning import data_pipeline as dp
        path, doc, project, _ = media_inputs
        root = tmp_path / 'explicit-store'
        results = tmp_path / 'external-review.json'
        config = dp.build_input_dvc_configuration(root, inputs_path=path, batch='batch-001', results_path=results, version='data-v4.1-r1')
        assert 'pipeline' in config
        assert list(config['pipeline']) == list(dp.STAGES)
        for index, (stage, spec) in enumerate(config['pipeline'].items()):
            assert '--inputs' in spec['cmd'] and str(path) in spec['cmd']
            assert str(root) in spec['cmd'] and '--root .' not in spec['cmd']
            deps = spec['deps']
            assert str(path) in deps and str(project / 'model/config.json') in deps
            assert str(project / 'development_reference.json') in deps
            assert str(Path(dp.__file__).resolve()) in deps
            if index:
                assert str(root / 'data/working/batch-001' / dp.STAGES[index-1]) in deps
        assert str(results) in config['pipeline']['review_import']['deps']
        assert '--version data-v4.1-r1' in config['pipeline']['release']['cmd']
        assert all('release_pointer' not in str(s) for s in config['pipeline'].values())


class TestHumanReviewerIdentity:
    @pytest.mark.parametrize('portable', [False, True])
    def test_single_maintainer_needs_no_manual_identity(self, tmp_path, monkeypatch, portable):
        from types import SimpleNamespace
        from pipeline.scripts import review_candidates_app as app
        monkeypatch.setattr(app, 'data_context_from_arg', lambda *a: SimpleNamespace(root=tmp_path))
        argv = (['--versioning-package', str(tmp_path / 'package'), '--draft', str(tmp_path / 'draft.json'),
                 '--output-root', str(tmp_path / 'output')] if portable else ['--queue', str(tmp_path / 'queue.json')])
        assert app._parse_args(argv).reviewer_id == '项目维护者'

    def test_reviewer_id_is_normalized_at_entry(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from pipeline.scripts import review_candidates_app as app
        monkeypatch.setattr(app, 'data_context_from_arg', lambda *a: SimpleNamespace(root=tmp_path))
        args = app._parse_args(['--queue', str(tmp_path / 'queue.json'), '--reviewer-id', '  reviewer-a  '])
        assert args.reviewer_id == 'reviewer-a'

    def test_legacy_history_keeps_missing_identity_without_reapproval(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from pipeline.scripts import review_candidates_app as app
        writes = []
        monkeypatch.setattr(app, 'freeze_completed_batch', lambda *a, **kw: writes.append(a[2]))
        args = SimpleNamespace(versioning_package=None,
                               _data_context=SimpleNamespace(metadata_collection=lambda _: tmp_path))
        decisions = {'clip-1': {'clip_id': 'clip-1', 'reviewer_id': None}}
        app._freeze_review_result(args, tmp_path, {}, decisions)
        assert writes == [decisions]
        assert decisions['clip-1']['reviewer_id'] is None
