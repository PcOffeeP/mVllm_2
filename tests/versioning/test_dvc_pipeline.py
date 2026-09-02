"""B4 — 根 dvc.yaml 七阶段结构、最小 data CLI 与临时 DVC 仓库集成测试。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.4（七阶段主干、人工审查显式关卡 D015/D016、自动发现手动执行）、
§2.5（DVC 只管数据 pipeline，不管训练）、§5.1/D031（DVC 输出边界=payload
子目录；Git 跟踪同级 release.yaml/README）、D035（stale 只报告不自动执行）；
实施台账 docs/plans/2026-09-01-readable-version-control-implementation.md B4 小节。

第二轮契约修订（reviewer Finding 1/2/3，移交 viber 的实现规格以本文件与
tests/versioning/test_data_pipeline.py 的 docstring 为准）。

本文件覆盖三类行为：

1. 根 ``dvc.yaml`` 结构校验（静态读仓库将创建的 ``dvc.yaml``）：
   七 stage 齐全且顺序固定、cmd 均调用 ``python -m versioning data <stage>``、
   依赖链相邻衔接、review 关卡显式（review_import 有外部人工输入依赖、
   release 依赖 review_import 产物）、release_validate 不触碰训练。
   Finding 3 裁决后的 release 输出边界：outs 恰好为固定路径
   ``data/release_payload/``（可重建、普通 out）与 ``data/release_pointer.json``；
   不再有 ``data/releases`` persist out——封存版本目录不是 pipeline out，
   各版本 payload 子目录由 run_release 内 ``dvc add`` 逐版本纳入 DVC。
   （临时仓库实证，DVC 3.67.1：stage cmd 内 dvc add 正常；push -> 删 cache
   与 payload -> pull 逐字节恢复，release.yaml 不经 DVC。）

   第三轮契约修订（显式版本纪律，§9/§11.6）：release stage 的目标版本
   必须经 DVC params 显式注入——仓库根 ``params.yaml`` 提供顶层键
   ``release_version``（完整 data ID，拒绝 latest/短前缀/缺 revision/
   错类别/占位符）；``dvc.yaml`` release stage 的 cmd 为
   ``python -m versioning data release --root . --batch batch-001
   --version ${release_version}`` 并声明 ``params: [release_version]``。
   实证（DVC 3.67.1）：值变化 -> release stage 过期重跑；键或 params.yaml
   缺失 -> ``dvc repro`` 立即失败（``Could not find 'release_version'``，
   非零退出），不得回退到任何自动分配。同一 ``release_version`` 重复执行
   release 必须冲突失败，不得静默递增产出新 rN（§11.6 同名立即停止）。

2. 最小 CLI（``versioning/cli.py`` + ``versioning/__main__.py``，仅 data 子命令）::

       python -m versioning data <stage> [--root DIR] [--batch NAME]
                   [--version ID] [--protocol P] [--purpose P] [--results FILE]
       # stage 必填且必须属于七阶段；缺参 / 非法 stage -> 非零退出（argparse exit 2）
       # 阶段执行失败（含 ReviewGateError / DataPipelineError）-> 非零退出（exit 1），
       # stderr 有错误信息；成功 -> exit 0。``versioning.cli.main(argv=None) -> int``，
       # ``versioning/__main__.py`` 以 SystemExit(main()) 调用。
       # 【第三轮修订】``data release`` 必须显式传 ``--version``（完整 data ID）：
       #   缺失 -> 非零退出（argparse exit 2 语义），不产生任何 release；
       #   非法值（非完整 data ID / 协议段与 --protocol 裸段不符）
       #   -> 非零退出（exit 1，InvalidIdentifier）。
       #   --version 仅对 release 必填；release_validate 仍可选（指针发现：
       #   校验是只读报告，不分配版本，不受显式纪律约束）。

3. 临时 DVC 仓库集成（``dvc init --no-scm``，tmp_path 内，禁止连正式 remote）：
   七阶段 fixture 闭环；审查缺失/不通过时 pipeline 阻断、回收通过后放行；
   Finding 1 关卡语义：上游内容变化后沿用旧审查结果（content_sha256 失配），
   手动 ``dvc repro`` 必须在 review_import 失败，不产生新版本；重新生成绑定
   新内容的审查结果后 repro 产出新 data 版本且不覆盖旧版本（不再有
   第一轮"内容变化无需重审"的隐含行为）；
   临时 local remote push -> 删本地 cache 与 payload 产物 -> pull 逐字节恢复
   ``release_payload/`` 与各版本 payload 子目录（release.yaml 为 Git 跟踪边界，
   不经 DVC、全程不动）；产出新版本必须由使用者编辑 ``params.yaml`` 的
   ``release_version`` 显式指定新编号（建议-显式传入），同一编号重复执行
   release 冲突拒绝、不静默递增。

第三轮契约修订（显式版本纪律）时根 dvc.yaml/params.yaml 与 production
尚未按新契约更新：结构测试断言 release cmd ``--version ${release_version}``
与根 params.yaml 将失败；CLI 缺 ``--version`` 用例与同版本重复执行用例
因 production 仍自动递增而 RED。集成测试通过 PYTHONPATH 指向本仓库根，
以便临时仓库内调用 versioning 包。
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from versioning.ids import parse_data_id

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
BATCH = "batch-001"
VIDEO_NAMES = ("cam-a.mp4", "cam-b.mp4", "cam-c.mp4")

EXPECTED_STAGES = [
    "source",
    "roi",
    "subvideo",
    "review_export",
    "review_import",
    "release",
    "release_validate",
]


def _entry_paths(entries: list | None) -> set[str]:
    """归一化 dvc.yaml deps/outs 条目：字符串或带参数的单键映射 -> 路径集合。"""
    paths: set[str] = set()
    for entry in entries or []:
        if isinstance(entry, str):
            paths.add(entry)
        elif isinstance(entry, dict):
            paths.update(str(key) for key in entry)
    return paths


def _env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(REPO_ROOT) + os.pathsep + pythonpath if pythonpath else str(REPO_ROOT)
    )
    env["DVC_NO_ANALYTICS"] = "1"
    return env


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "versioning", *args],
        cwd=cwd,
        env=_env(),
        capture_output=True,
        text=True,
    )


def _run_dvc(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "dvc", *args],
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 1. 根 dvc.yaml 结构校验
# ---------------------------------------------------------------------------


class TestDvcYamlStructure:
    @pytest.fixture()
    def dvc_yaml(self) -> dict:
        path = REPO_ROOT / "dvc.yaml"
        assert path.is_file(), "仓库根 dvc.yaml 不存在（B4 应创建七阶段 pipeline）"
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict) and isinstance(loaded.get("stages"), dict), (
            "dvc.yaml 顶层必须含 stages 映射"
        )
        return loaded

    def test_seven_stages_in_fixed_order(self, dvc_yaml: dict) -> None:
        assert list(dvc_yaml["stages"].keys()) == EXPECTED_STAGES

    def test_each_stage_cmd_invokes_data_subcommand(self, dvc_yaml: dict) -> None:
        for name in EXPECTED_STAGES:
            stage = dvc_yaml["stages"][name]
            cmd = stage.get("cmd", "")
            assert isinstance(cmd, str) and cmd, f"{name} 缺 cmd"
            assert "-m versioning" in cmd, f"{name} cmd 未调用 versioning 包: {cmd!r}"
            assert " data " in f" {cmd} ", f"{name} cmd 未走 data 子命令: {cmd!r}"
            assert name in cmd, f"{name} cmd 未显式执行本阶段: {cmd!r}"

    def test_dependency_chain_links_adjacent_stages(self, dvc_yaml: dict) -> None:
        stages = dvc_yaml["stages"]
        for previous, current in zip(EXPECTED_STAGES, EXPECTED_STAGES[1:]):
            prev_outs = _entry_paths(stages[previous].get("outs"))
            cur_deps = _entry_paths(stages[current].get("deps"))
            assert prev_outs & cur_deps, (
                f"{current} 的 deps 未依赖 {previous} 的任何 outs，依赖链断裂"
            )

    def test_review_gate_is_explicit(self, dvc_yaml: dict) -> None:
        stages = dvc_yaml["stages"]
        all_outs: set[str] = set()
        for name in EXPECTED_STAGES:
            all_outs.update(_entry_paths(stages[name].get("outs")))

        # review_import 必须消费一个不由任何阶段产物提供的外部输入（人工审查结果）
        import_deps = _entry_paths(stages["review_import"].get("deps"))
        external = import_deps - all_outs
        assert external, "review_import 缺外部人工审查结果依赖，关卡不显式"

        # release 必须依赖 review_import 的产物（审查关卡先于 release）
        release_deps = _entry_paths(stages["release"].get("deps"))
        import_outs = _entry_paths(stages["review_import"].get("outs"))
        assert import_outs and import_outs & release_deps, (
            "release 未依赖 review_import 产物，审查关卡可被绕过"
        )

    def test_release_outs_payload_boundary(self, dvc_yaml: dict) -> None:
        """Finding 3 裁决后的 release 输出边界（§5.1/D031）。

        release 的 DVC outs 恰好为固定路径 ``data/release_payload/``（可重建、
        普通 out）与 ``data/release_pointer.json``；不再有 ``data/releases``
        persist out——封存版本目录整体不是 pipeline out，payload 与元数据分离：
        版本 payload 子目录由 run_release 内 ``dvc add`` 逐版本纳入 DVC，
        release.yaml/README 落 Git 跟踪边界。
        """
        stages = dvc_yaml["stages"]
        outs = stages["release"].get("outs", [])
        paths = _entry_paths(outs)

        assert "data/release_payload" in paths, (
            "release stage 缺固定 payload out data/release_payload"
        )
        assert "data/release_pointer.json" in paths

        # data/releases 不得作为任何形式的 pipeline out（普通或 persist）
        assert not any(
            path == "data/releases" or path.startswith("data/releases/")
            for path in paths
        ), "release outs 不得包含 data/releases：封存版本目录不是 pipeline out"

        # payload 固定路径可重建、新版本追加不依赖 persist 保护旧版本：
        # release outs 不得声明 persist
        for entry in outs:
            if isinstance(entry, dict):
                for path, params in entry.items():
                    assert not (params or {}).get("persist"), (
                        f"release out {path} 不得声明 persist"
                    )

        # 全局闭合：没有任何 stage 的 out 落在 data/releases 下
        for name in EXPECTED_STAGES:
            for path in _entry_paths(stages[name].get("outs")):
                assert path != "data/releases" and not path.startswith(
                    "data/releases/"
                ), f"{name} 的 out 越界进入 data/releases: {path}"

    def test_release_version_explicit_via_dvc_params(self, dvc_yaml: dict) -> None:
        """显式版本纪律（§9/§11.6）：release stage 版本号必须经 DVC params 显式注入。

        根 ``params.yaml`` 提供顶层键 ``release_version``（完整 data ID）；
        release stage 的 cmd 经 ``${release_version}`` 替换传给 CLI ``--version``，
        并把 ``release_version`` 声明为 params 依赖：值变化 -> stage 过期重跑；
        键或文件缺失 -> ``dvc repro`` 立即失败，不得回退到任何自动分配。
        """
        release = dvc_yaml["stages"]["release"]
        cmd = release.get("cmd", "")
        assert isinstance(cmd, str) and "--version" in cmd, (
            f"release cmd 必须显式传 --version: {cmd!r}"
        )
        assert "${release_version}" in cmd, (
            f"release cmd 的版本号必须来自 params 替换，不得硬编码或自动分配: {cmd!r}"
        )

        params = release.get("params")
        assert isinstance(params, list) and params, (
            "release stage 必须声明 params 依赖（至少含 release_version）"
        )
        tracked = {
            entry.split(":")[-1].strip()
            for entry in params
            if isinstance(entry, str)
        }
        assert "release_version" in tracked, (
            f"release params 未跟踪 release_version: {params!r}"
        )

        params_path = REPO_ROOT / "params.yaml"
        assert params_path.is_file(), "仓库根 params.yaml 不存在（应提供 release_version）"
        loaded = yaml.safe_load(params_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict) and "release_version" in loaded, (
            "params.yaml 必须是含 release_version 顶层键的映射"
        )
        release_version = loaded["release_version"]
        assert isinstance(release_version, str), (
            f"release_version 必须是字符串完整 data ID: {release_version!r}"
        )
        # 完整 data ID 校验：latest / 短前缀 / 缺 revision / 错类别均拒绝
        parse_data_id(release_version)

    def test_release_validate_does_not_start_training(self, dvc_yaml: dict) -> None:
        cmd = dvc_yaml["stages"]["release_validate"]["cmd"]
        assert "train" not in cmd, f"release_validate 不得触碰训练: {cmd!r}"
        # DVC 只管数据 pipeline：所有 cmd 不得含 train/eval/model 子命令
        for name in EXPECTED_STAGES:
            stage_cmd = dvc_yaml["stages"][name]["cmd"]
            for forbidden in (" train", " eval", " model", "backup"):
                assert forbidden not in f" {stage_cmd} ", (
                    f"{name} cmd 越权包含非 data 子命令: {stage_cmd!r}"
                )


# ---------------------------------------------------------------------------
# 2. 最小 CLI（python -m versioning data ...）
# ---------------------------------------------------------------------------


def _make_project(base: Path) -> Path:
    root = base / "proj"
    raw = root / "data" / "raw" / BATCH
    raw.mkdir(parents=True)
    for index, name in enumerate(VIDEO_NAMES):
        (raw / name).write_bytes(b"\x00\x01\x02" + bytes([index]) * 16)
    return root


def _write_review_results(
    root: Path, *, approved: bool, digest: str | None = None
) -> Path:
    """写审查结果 YAML（Finding 1：含绑定当前内容的 content_sha256）。

    digest=None 时从当前审查包 items.jsonl 读取（调用前置条件：
    review_export 已执行）；显式 digest 用于构造失配反向用例。
    """
    working = root / "data" / "working" / BATCH
    clips = json.loads(
        (working / "subvideo" / "subvideo_manifest.json").read_text(encoding="utf-8")
    )["clips"]
    if digest is None:
        digests = {
            json.loads(line)["content_sha256"]
            for line in (working / "review" / "review_package" / "items.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        }
        assert len(digests) == 1, "items.jsonl 各行 content_sha256 必须同值"
        digest = digests.pop()
    results_dir = root / "data" / "review_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{BATCH}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "batch": BATCH,
                "approved": approved,
                "content_sha256": digest,
                "decisions": [
                    {"clip_id": clip["clip_id"], "verdict": "accept"} for clip in clips
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


class TestCliData:
    def test_no_args_fail_closed(self, tmp_path: Path) -> None:
        proc = _run_cli(tmp_path)
        assert proc.returncode != 0

    def test_data_without_stage_fail_closed(self, tmp_path: Path) -> None:
        proc = _run_cli(tmp_path, "data")
        assert proc.returncode != 0

    def test_unknown_stage_fail_closed(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path)
        proc = _run_cli(
            tmp_path, "data", "frobnicate", "--root", str(root), "--batch", BATCH
        )
        assert proc.returncode != 0
        # fail-closed：不产生任何 pipeline 产物
        assert not (root / "data" / "working").exists()
        assert not (root / "data" / "releases").exists()

    def test_train_stage_not_offered(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path)
        proc = _run_cli(tmp_path, "data", "train", "--root", str(root))
        assert proc.returncode != 0

    def test_source_stage_happy_path(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path)
        proc = _run_cli(
            tmp_path, "data", "source", "--root", str(root), "--batch", BATCH
        )
        assert proc.returncode == 0, proc.stderr
        assert (
            root / "data" / "working" / BATCH / "source" / "source_manifest.json"
        ).is_file()

    def test_review_gate_blocks_release_until_approved(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path)

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return _run_cli(
                tmp_path, "data", *args, "--root", str(root), "--batch", BATCH
            )

        for stage in ("source", "roi", "subvideo", "review_export"):
            proc = cli(stage)
            assert proc.returncode == 0, f"{stage}: {proc.stderr}"

        # 审查未回收：release 必须非零退出阻断（显式给出目标版本，
        # 阻断归因于审查关卡而非版本缺失）
        proc = cli("release", "--version", "data-v4.1-r1")
        assert proc.returncode != 0
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

        # 审查不通过：review_import 非零退出，release 仍被阻断
        _write_review_results(root, approved=False)
        proc = cli("review_import")
        assert proc.returncode != 0
        proc = cli("release", "--version", "data-v4.1-r1")
        assert proc.returncode != 0
        assert not releases.exists() or not any(releases.iterdir())

        # 审查通过回收：import -> release（显式版本）-> release_validate 放行
        _write_review_results(root, approved=True)
        proc = cli("review_import")
        assert proc.returncode == 0, proc.stderr
        proc = cli("release", "--version", "data-v4.1-r1")
        assert proc.returncode == 0, proc.stderr
        release_dir = releases / "data-v4.1-r1"
        # Finding 3 封存边界：Git 跟踪元数据 + payload/ 子目录分离
        assert (release_dir / "release.yaml").is_file()
        assert (release_dir / "README.md").is_file()
        assert (release_dir / "payload" / "accepted_clips.json").is_file()
        assert not (release_dir / "accepted_clips.json").exists()
        # 固定路径 payload out（DVC 普通 out）
        assert (root / "data" / "release_payload" / "accepted_clips.json").is_file()
        proc = cli("release_validate")
        assert proc.returncode == 0, proc.stderr
        assert (
            root / "data" / "reports" / "data-v4.1-r1.validation.json"
        ).is_file()

    def test_release_requires_explicit_version_cli(self, tmp_path: Path) -> None:
        """CLI 显式版本纪律（§9/§11.6）：data release 缺 --version 必须非零退出。

        审查已通过时缺 --version 是唯一失败原因；fail-closed：不产生任何
        release，也不重建 release_payload。显式给出后放行。
        """
        root = _make_project(tmp_path)

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return _run_cli(
                tmp_path, "data", *args, "--root", str(root), "--batch", BATCH
            )

        for stage in ("source", "roi", "subvideo", "review_export"):
            assert cli(stage).returncode == 0, f"{stage}: 前置阶段失败"
        _write_review_results(root, approved=True)
        assert cli("review_import").returncode == 0

        proc = cli("release")
        assert proc.returncode != 0, "data release 缺 --version 必须非零退出"
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())
        assert not (root / "data" / "release_payload").exists()

        proc = cli("release", "--version", "data-v4.1-r1")
        assert proc.returncode == 0, proc.stderr
        assert (releases / "data-v4.1-r1" / "release.yaml").is_file()

    def test_release_rejects_invalid_version_cli(self, tmp_path: Path) -> None:
        """CLI 非法目标版本（非完整 data ID / 协议段与 --protocol 不符）非零退出。"""
        root = _make_project(tmp_path)

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return _run_cli(
                tmp_path, "data", *args, "--root", str(root), "--batch", BATCH
            )

        for stage in ("source", "roi", "subvideo", "review_export"):
            assert cli(stage).returncode == 0, f"{stage}: 前置阶段失败"
        _write_review_results(root, approved=True)
        assert cli("review_import").returncode == 0

        for bad in ("data-v4.1", "model-v4.1-r1", "not-a-version"):
            proc = cli("release", "--version", bad)
            assert proc.returncode != 0, f"非法版本 {bad!r} 必须非零退出"
        # 协议段与 --protocol 裸段不符（默认 v4.1）
        proc = cli("release", "--version", "data-v5-r1")
        assert proc.returncode != 0
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

    def test_review_import_rejects_stale_content_digest(self, tmp_path: Path) -> None:
        """Finding 1：内容变化后沿用旧审查结果（digest 失配）必须被关卡阻断。"""
        root = _make_project(tmp_path)

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return _run_cli(
                tmp_path, "data", *args, "--root", str(root), "--batch", BATCH
            )

        for stage in ("source", "roi", "subvideo", "review_export"):
            assert cli(stage).returncode == 0, f"{stage}: 前置阶段失败"
        _write_review_results(root, approved=True)
        assert cli("review_import").returncode == 0

        # 上游内容变化（文件名不变 -> clip_id 集合不变，内容 digest 变化）
        raw_file = root / "data" / "raw" / BATCH / "cam-a.mp4"
        raw_file.write_bytes(raw_file.read_bytes() + b"\xff" * 8)
        for stage in ("source", "roi", "subvideo", "review_export"):
            assert cli(stage).returncode == 0, f"{stage}: 重跑上游失败"

        # 旧审查结果绑定旧内容 digest -> review_import 非零退出阻断
        proc = cli("review_import")
        assert proc.returncode != 0
        # release 复核 decisions 绑定 digest 与当前内容不一致 -> 仍被阻断
        # （显式给出目标版本，阻断归因于 digest 失配而非版本缺失）
        proc = cli("release", "--version", "data-v4.1-r1")
        assert proc.returncode != 0
        releases = root / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

        # 针对新内容重新审查回收后放行（显式指定 r1）
        _write_review_results(root, approved=True)
        proc = cli("review_import")
        assert proc.returncode == 0, proc.stderr
        proc = cli("release", "--version", "data-v4.1-r1")
        assert proc.returncode == 0, proc.stderr

    def test_release_validate_fail_closed_on_unsealed_release(
        self, tmp_path: Path
    ) -> None:
        """Finding 2：封存被破坏的 release，release_validate 必须非零退出并如实报告。"""
        root = _make_project(tmp_path)

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return _run_cli(
                tmp_path, "data", *args, "--root", str(root), "--batch", BATCH
            )

        for stage in ("source", "roi", "subvideo", "review_export"):
            assert cli(stage).returncode == 0
        _write_review_results(root, approved=True)
        assert cli("review_import").returncode == 0
        assert cli("release", "--version", "data-v4.1-r1").returncode == 0

        # 人为破坏封存：恢复 payload 文件写位
        payload_file = (
            root
            / "data"
            / "releases"
            / "data-v4.1-r1"
            / "payload"
            / "accepted_clips.json"
        )
        payload_file.chmod(payload_file.stat().st_mode | 0o200)

        proc = cli("release_validate")
        assert proc.returncode != 0, "封存被破坏的 release 必须 fail-closed"
        report = json.loads(
            (
                root / "data" / "reports" / "data-v4.1-r1.validation.json"
            ).read_text(encoding="utf-8")
        )
        assert report["checks"]["sealed_release"]["passed"] is False
        assert report["passed"] is False


# ---------------------------------------------------------------------------
# 3. 临时 DVC 仓库集成
# ---------------------------------------------------------------------------


def _dvc_yaml(batch: str = BATCH) -> dict:
    """测试用七阶段 dvc.yaml：镜像根 dvc.yaml 契约，cmd 走真实 versioning CLI。

    release stage 与根 dvc.yaml 同构：目标版本经 ``${release_version}``
    （DVC params）显式注入 CLI ``--version``，``params: [release_version]``
    声明依赖（显式版本纪律，§9/§11.6）。
    """

    def cmd(stage: str, *extra: str) -> str:
        base = (
            f"{shlex.quote(PYTHON)} -m versioning data {stage} "
            f"--root . --batch {shlex.quote(batch)}"
        )
        if extra:
            base = f"{base} {' '.join(extra)}"
        return base

    working = f"data/working/{batch}"
    return {
        "stages": {
            "source": {
                "cmd": cmd("source"),
                "deps": [f"data/raw/{batch}"],
                "outs": [f"{working}/source"],
            },
            "roi": {
                "cmd": cmd("roi"),
                "deps": [f"{working}/source"],
                "outs": [f"{working}/roi"],
            },
            "subvideo": {
                "cmd": cmd("subvideo"),
                "deps": [f"{working}/roi"],
                "outs": [f"{working}/subvideo"],
            },
            "review_export": {
                "cmd": cmd("review_export"),
                "deps": [f"{working}/subvideo"],
                "outs": [f"{working}/review/review_package"],
            },
            "review_import": {
                "cmd": cmd("review_import"),
                "deps": [
                    f"{working}/review/review_package",
                    f"data/review_results/{batch}.yaml",
                ],
                "outs": [f"{working}/review/review_decisions.json"],
            },
            "release": {
                # 显式版本纪律：目标版本来自 params.yaml 的 release_version
                # 经 DVC 替换传给 CLI --version，不得自动递增分配
                "cmd": cmd("release", "--version", "${release_version}"),
                "deps": [f"{working}/review/review_decisions.json"],
                "params": ["release_version"],
                # Finding 3 裁决后的输出边界：固定路径 data/release_payload/
                # （可重建、普通 out）+ release_pointer.json。封存版本目录不是
                # pipeline out；run_release 在 cmd 内对每个版本执行
                # dvc add data/releases/<version>/payload，逐版本纳入 DVC
                # （生成同级 payload.dvc）；release.yaml/README 不经 DVC，
                # 落 Git 跟踪边界。
                "outs": [
                    "data/release_payload",
                    "data/release_pointer.json",
                ],
            },
            "release_validate": {
                "cmd": cmd("release_validate"),
                "deps": ["data/release_pointer.json"],
                "outs": ["data/reports"],
            },
        }
    }


@pytest.fixture()
def dvc_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    raw = repo / "data" / "raw" / BATCH
    raw.mkdir(parents=True)
    for index, name in enumerate(VIDEO_NAMES):
        (raw / name).write_bytes(b"\x00\x01\x02" + bytes([index]) * 16)
    proc = _run_dvc(repo, "init", "--no-scm")
    assert proc.returncode == 0, proc.stderr
    # 显式版本纪律：目标版本由 params.yaml 的 release_version 显式提供
    (repo / "params.yaml").write_text(
        yaml.safe_dump({"release_version": "data-v4.1-r1"}, sort_keys=False),
        encoding="utf-8",
    )
    (repo / "dvc.yaml").write_text(
        yaml.safe_dump(_dvc_yaml(), sort_keys=False), encoding="utf-8"
    )
    return repo


def _write_repo_review_results(repo: Path, *, approved: bool) -> None:
    _write_review_results(repo, approved=approved)


def _force_rmtree(path: Path) -> None:
    """删除可能带只读封存位的目录树（仅 tmp_path 内使用）。"""
    for child in path.rglob("*"):
        child.chmod(0o755)
    path.chmod(0o755)
    shutil.rmtree(path)


class TestDvcClosedLoop:
    def test_review_gate_blocks_and_approval_completes_pipeline(
        self, dvc_repo: Path
    ) -> None:
        repo = dvc_repo

        # 审查结果未回收：pipeline 必须阻断，不得产生正式 release
        proc = _run_dvc(repo, "repro")
        assert proc.returncode != 0
        releases = repo / "data" / "releases"
        assert not releases.exists() or not any(releases.iterdir())

        # 审查结论不通过：review_import 失败，release 仍被阻断
        _write_repo_review_results(repo, approved=False)
        proc = _run_dvc(repo, "repro")
        assert proc.returncode != 0
        assert (
            repo / "data" / "working" / BATCH / "review" / "review_package"
        ).is_dir(), "review_export 产物应在阻断前已生成（显式关卡）"
        assert not (
            repo / "data" / "working" / BATCH / "review" / "review_decisions.json"
        ).exists()
        assert not releases.exists() or not any(releases.iterdir())

        # 审查通过回收：pipeline 完整跑通到 release_validate
        _write_repo_review_results(repo, approved=True)
        proc = _run_dvc(repo, "repro")
        assert proc.returncode == 0, proc.stdout + proc.stderr

        # Finding 3 封存边界：版本目录 = Git 跟踪元数据 + DVC 管理 payload 子目录
        release_dir = releases / "data-v4.1-r1"
        assert (release_dir / "release.yaml").is_file()
        assert (release_dir / "README.md").is_file()
        assert (release_dir / "payload" / "accepted_clips.json").is_file()
        assert not (release_dir / "accepted_clips.json").exists()

        # payload 子目录经 dvc add 逐版本纳入 DVC：同级 payload.dvc 指针文件，
        # 指向 payload 子目录而非整个版本目录（release.yaml 不经 DVC）
        payload_dvc = release_dir / "payload.dvc"
        assert payload_dvc.is_file(), "版本 payload 子目录应经 dvc add 生成 payload.dvc"
        payload_dvc_doc = yaml.safe_load(payload_dvc.read_text(encoding="utf-8"))
        tracked_paths = {
            str(entry.get("path", "")) for entry in payload_dvc_doc.get("outs", [])
        }
        assert tracked_paths and all(
            path.endswith("payload") for path in tracked_paths
        ), f"payload.dvc 应仅跟踪 payload 子目录: {tracked_paths!r}"

        # 固定路径 payload out 与 release_validate 报告
        assert (repo / "data" / "release_payload" / "accepted_clips.json").is_file()
        assert (
            repo / "data" / "reports" / "data-v4.1-r1.validation.json"
        ).is_file()

        # release_validate 只报告：不产生训练目录。DVC 3.x 的 run-cache 固定在
        # .dvc/cache/runs（成功 stage 必写、无关闭开关，实测 --no-run-cache 也照建
        # 目录），属 DVC 内部状态而非训练产物；本断言的原始意图是校验 workspace 侧
        # 不出现任何训练 runs 目录（如 workspace/runs），因此排除 .dvc 内部。
        assert not (repo / "workspace").exists()
        runs_dirs = [
            p
            for p in repo.rglob("*")
            if p.is_dir()
            and p.name == "runs"
            and ".dvc" not in p.relative_to(repo).parts
        ]
        assert runs_dirs == [], f"检测到训练产物 runs 目录: {runs_dirs}"

        # 显式版本纪律（§11.6 同名立即停止）：以同一 release_version 重复执行
        # release 必须冲突失败，不得静默递增产出 r2。强制重跑 release stage
        # （上游确定性重生成，审查结果绑定当前内容仍然通过），唯一失败原因
        # 是目标版本 r1 已封存。
        release_yaml_bytes = (release_dir / "release.yaml").read_bytes()
        proc = _run_dvc(repo, "repro", "-f", "release")
        assert proc.returncode != 0, (
            "重复同一显式版本必须冲突失败，不得自动递增: " + proc.stdout + proc.stderr
        )
        assert not (releases / "data-v4.1-r2").exists()
        # r1 原对象不动：release.yaml 逐字节不变
        assert (release_dir / "release.yaml").read_bytes() == release_yaml_bytes


class TestDvcStaleSemantics:
    def test_stale_reported_not_auto_rerun_and_manual_repro_new_version(
        self, dvc_repo: Path
    ) -> None:
        """Finding 1 关卡语义：内容变化后旧审查结果作废，必须重审才产新版本。

        本用例显式取代第一轮"内容变化沿用旧审查结果即可产 r2"的隐含行为：
        raw 变更后沿用旧审查结果的手动 repro 必须在 review_import 失败；
        重新生成绑定新内容 digest 的审查结果后，repro 才产出 r2 且不覆盖 r1。
        """
        repo = dvc_repo
        # 审查结果以 review_export 产物（clips 清单与内容 digest）为输入，
        # 必须先跑到 review_export，再回收人工审查结果（人工审查关卡的合法时序）。
        proc = _run_dvc(repo, "repro", "review_export")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        _write_repo_review_results(repo, approved=True)
        proc = _run_dvc(repo, "repro")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (repo / "data" / "releases" / "data-v4.1-r1").is_dir()

        subvideo_manifest = (
            repo / "data" / "working" / BATCH / "subvideo" / "subvideo_manifest.json"
        )
        before_hash = _sha256(subvideo_manifest)

        # 未变更：status 报告 up-to-date
        proc = _run_dvc(repo, "status")
        assert proc.returncode == 0, proc.stderr
        assert "up to date" in (proc.stdout + proc.stderr).lower()

        # 输入变化：DVC 只报告过期（D035 自动发现），不自动重跑
        raw_file = repo / "data" / "raw" / BATCH / "cam-a.mp4"
        raw_file.write_bytes(raw_file.read_bytes() + b"\xff" * 8)
        proc = _run_dvc(repo, "status")
        combined = (proc.stdout + proc.stderr).lower()
        assert "up to date" not in combined
        assert "source" in combined, f"status 未定位到过期阶段: {combined!r}"
        # 不自动执行：下游产物保持原样
        assert _sha256(subvideo_manifest) == before_hash
        assert not (repo / "data" / "releases" / "data-v4.1-r2").exists()

        # 手动执行，但沿用旧审查结果（content_sha256 绑定旧内容）：
        # Finding 1 关卡必须在 review_import 阻断，不产生新版本
        proc = _run_dvc(repo, "repro")
        combined = proc.stdout + proc.stderr
        assert proc.returncode != 0, (
            "沿用旧审查结果的 repro 必须在 review_import 关卡失败: " + combined
        )
        assert "review_import" in combined, (
            f"失败应定位到 review_import 审查关卡: {combined!r}"
        )
        assert not (repo / "data" / "releases" / "data-v4.1-r2").exists()

        # 针对新内容重新审查回收（review_export 产物已在上次 repro 中更新）；
        # 显式版本纪律（§11.6）：产出新版本必须由使用者编辑 params.yaml 的
        # release_version 显式指定新编号 r2（建议-显式传入），不得自动递增
        (repo / "params.yaml").write_text(
            yaml.safe_dump({"release_version": "data-v4.1-r2"}, sort_keys=False),
            encoding="utf-8",
        )
        _write_repo_review_results(repo, approved=True)
        proc = _run_dvc(repo, "repro")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        # 产生新 data 版本，不原地覆盖 r1
        assert (repo / "data" / "releases" / "data-v4.1-r1").is_dir()
        assert (repo / "data" / "releases" / "data-v4.1-r2").is_dir()
        assert (
            repo / "data" / "releases" / "data-v4.1-r2" / "payload" / "accepted_clips.json"
        ).is_file()
        assert (
            repo / "data" / "releases" / "data-v4.1-r2" / "payload.dvc"
        ).is_file()
        # r1 的 release.yaml 全程未被触碰
        assert (
            repo / "data" / "releases" / "data-v4.1-r1" / "release.yaml"
        ).is_file()


class TestDvcRemoteRecovery:
    def test_push_delete_pull_restores_outputs(self, dvc_repo: Path, tmp_path: Path) -> None:
        """Finding 3 远程恢复底线：payload 两个边界逐字节恢复，release.yaml 不经 DVC。"""
        repo = dvc_repo
        # 审查结果以 review_export 产物（clips 清单与内容 digest）为输入，
        # 必须先跑到 review_export，再回收人工审查结果（人工审查关卡的合法时序）。
        proc = _run_dvc(repo, "repro", "review_export")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        _write_repo_review_results(repo, approved=True)
        proc = _run_dvc(repo, "repro")
        assert proc.returncode == 0, proc.stdout + proc.stderr

        # 临时 local remote（tmp_path 内，不连正式 remote）
        remote_dir = tmp_path / "remote"
        proc = _run_dvc(repo, "remote", "add", "-d", "local", str(remote_dir))
        assert proc.returncode == 0, proc.stderr
        proc = _run_dvc(repo, "push")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert any(p.is_file() for p in remote_dir.rglob("*")), "remote 无对象"

        version = "data-v4.1-r1"
        release_dir = repo / "data" / "releases" / version
        release_yaml = release_dir / "release.yaml"
        subvideo_manifest = (
            repo / "data" / "working" / BATCH / "subvideo" / "subvideo_manifest.json"
        )
        fixed_payload = repo / "data" / "release_payload" / "accepted_clips.json"
        sealed_payload = release_dir / "payload" / "accepted_clips.json"
        release_yaml_bytes = release_yaml.read_bytes()
        manifest_hash = _sha256(subvideo_manifest)
        fixed_payload_hash = _sha256(fixed_payload)
        sealed_payload_hash = _sha256(sealed_payload)

        # 删除本地 cache 全部对象 + DVC 管理的 payload 产物；
        # release.yaml 为 Git 跟踪边界，不经 DVC、全程原地保留。
        shutil.rmtree(repo / ".dvc" / "cache")
        subvideo_manifest.unlink()
        # 封存为只读：先解除写位限制再删除（仅 tmp 仓库内）
        release_dir.chmod(release_dir.stat().st_mode | 0o200)
        _force_rmtree(release_dir / "payload")
        shutil.rmtree(repo / "data" / "release_payload")

        # pull 后从临时 remote 完整恢复
        proc = _run_dvc(repo, "pull")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert _sha256(subvideo_manifest) == manifest_hash
        assert _sha256(fixed_payload) == fixed_payload_hash, (
            "固定路径 release_payload/ 未逐字节恢复"
        )
        assert _sha256(sealed_payload) == sealed_payload_hash, (
            "版本 payload 子目录未逐字节恢复"
        )
        # release.yaml 不经 DVC：删除与恢复全程未被触碰
        assert release_yaml.read_bytes() == release_yaml_bytes
