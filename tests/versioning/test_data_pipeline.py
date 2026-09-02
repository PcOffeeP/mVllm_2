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

    def test_run_stage_dispatches(self, tmp_path: Path) -> None:
        root = _make_root(tmp_path)
        result = run_stage(root, "source", batch=BATCH)
        assert isinstance(result, StageResult)
        assert result.stage == "source"

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
