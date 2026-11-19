from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest

from script.annotation import review_run_annotation
from script.annotation.review_run_annotation import (
    DEFAULT_CSV,
    DEFAULT_VIDEOS,
    PROJECT_ROOT,
    LocalServer,
)


# 契约里的字面值：默认来源是项目根下的相对路径字符串。
EXPECTED_DEFAULT_CSV = "data/annotation-table-full.csv"
EXPECTED_DEFAULT_VIDEOS = "data/videos"
GENERIC_MISSING_MESSAGE = "找不到此路径，或本机没有访问权限。"


def collect_default_warnings(project_root: Path) -> list[str]:
    # 生产函数由 coder 新增；缺失时这里抛 AttributeError，即为红阶段预期失败。
    return review_run_annotation.default_source_warnings(Path(project_root))


def request(server, method, route, payload=None):
    headers = {
        "Origin": server.origin,
        "Sec-Fetch-Site": "same-origin",
        "X-Annotation-Session": server.token,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(method, route, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        if response.headers.get_content_type() == "application/json":
            data = json.loads(data)
        return response.status, data
    finally:
        connection.close()


def running_server(project_root: Path):
    server = LocalServer(project_root=project_root)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    return server, thread


@pytest.fixture
def empty_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def empty_project_server(empty_project):
    server, thread = running_server(empty_project)
    try:
        yield server, empty_project
    finally:
        server.shutdown()
        thread.join()


def assert_中文提示(text: str, path: str) -> None:
    """提示里必须同时出现路径本身和可执行的中文指引。"""
    assert path in text, f"提示未包含默认路径 {path}：{text!r}"
    assert "不存在" in text, f"提示未说明路径不存在：{text!r}"
    assert "填" in text or "路径" in text, f"提示未指引用户填写路径：{text!r}"


def test_default_paths_point_to_real_project_files():
    assert DEFAULT_CSV == EXPECTED_DEFAULT_CSV
    assert DEFAULT_VIDEOS == EXPECTED_DEFAULT_VIDEOS

    # 默认值按项目根解析，必须真的指向本机存在的 CSV 与视频目录。
    assert (PROJECT_ROOT / DEFAULT_CSV).is_file()
    assert (PROJECT_ROOT / DEFAULT_VIDEOS).is_dir()


def test_default_sources_resolve_independently_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    csv_path = (Path(PROJECT_ROOT) / DEFAULT_CSV).resolve(strict=True)
    video_path = (Path(PROJECT_ROOT) / DEFAULT_VIDEOS).resolve(strict=True)
    assert csv_path.is_file()
    assert video_path.is_dir()

    server, thread = running_server(Path(PROJECT_ROOT))
    try:
        status, defaults = request(server, "GET", "/api/default-sources")
    finally:
        server.shutdown()
        thread.join()

    assert status == HTTPStatus.OK
    assert defaults["csv_path"] == EXPECTED_DEFAULT_CSV
    assert defaults["video_directory"] == EXPECTED_DEFAULT_VIDEOS
    # 页面拿到的值必须能按项目根解析成功（与 LocalServer.source_path 同一语义）。
    assert (Path(PROJECT_ROOT) / defaults["csv_path"]).resolve(strict=True) == csv_path
    assert (Path(PROJECT_ROOT) / defaults["video_directory"]).resolve(strict=True) == video_path
    # 整个过程中工作目录都没有被当作解析基准。
    assert Path.cwd() == tmp_path


def make_defaults(project: Path, *, with_csv: bool, with_videos: bool) -> None:
    if with_csv:
        csv_path = project / EXPECTED_DEFAULT_CSV
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("id,video_path\n", encoding="utf-8")
    if with_videos:
        (project / EXPECTED_DEFAULT_VIDEOS).mkdir(parents=True, exist_ok=True)


def test_default_source_warnings_are_empty_when_both_defaults_exist(tmp_path):
    make_defaults(tmp_path, with_csv=True, with_videos=True)

    assert collect_default_warnings(tmp_path) == []


def test_default_source_warnings_report_missing_csv_only(tmp_path):
    make_defaults(tmp_path, with_csv=False, with_videos=True)

    warnings = collect_default_warnings(tmp_path)

    assert len(warnings) == 1
    assert_中文提示(warnings[0], EXPECTED_DEFAULT_CSV)


def test_default_source_warnings_report_missing_video_directory_only(tmp_path):
    make_defaults(tmp_path, with_csv=True, with_videos=False)

    warnings = collect_default_warnings(tmp_path)

    assert len(warnings) == 1
    assert_中文提示(warnings[0], EXPECTED_DEFAULT_VIDEOS)


def test_default_source_warnings_report_both_missing(tmp_path):
    warnings = collect_default_warnings(tmp_path)

    assert len(warnings) == 2
    csv_warnings = [item for item in warnings if EXPECTED_DEFAULT_CSV in item]
    video_warnings = [item for item in warnings if EXPECTED_DEFAULT_VIDEOS in item]
    assert len(csv_warnings) == 1
    assert len(video_warnings) == 1
    assert_中文提示(csv_warnings[0], EXPECTED_DEFAULT_CSV)
    assert_中文提示(video_warnings[0], EXPECTED_DEFAULT_VIDEOS)


def test_csv_read_reports_missing_default_csv(empty_project_server):
    server, _ = empty_project_server

    status, data = request(server, "POST", "/api/csv/read", {"path": EXPECTED_DEFAULT_CSV})

    assert status == HTTPStatus.NOT_FOUND
    assert_中文提示(data["error"], EXPECTED_DEFAULT_CSV)


def test_video_library_reports_missing_default_directory(empty_project_server):
    server, _ = empty_project_server

    status, data = request(server, "POST", "/api/video/library", {"path": EXPECTED_DEFAULT_VIDEOS})

    assert status == HTTPStatus.NOT_FOUND
    assert_中文提示(data["error"], EXPECTED_DEFAULT_VIDEOS)


@pytest.mark.parametrize("route,path", [
    ("/api/csv/read", "data/自选表.csv"),
    ("/api/video/library", "data/自选视频"),
])
def test_non_default_missing_path_keeps_generic_message(empty_project_server, route, path):
    server, _ = empty_project_server

    status, data = request(server, "POST", route, {"path": path})

    assert status == HTTPStatus.NOT_FOUND
    assert data["error"] == GENERIC_MISSING_MESSAGE


def test_main_reports_missing_default_sources_before_serving(empty_project, monkeypatch, capsys):
    import shutil
    import subprocess
    import webbrowser

    served = []

    def fake_serve_forever(self, poll_interval=0.5):
        served.append(self.host)

    # main() 决定「默认来源缺不缺」时用的项目根必须是空的临时目录：
    # 同时替换模块常量与 LocalServer 的默认参数，覆盖两种实现写法。
    monkeypatch.setattr(review_run_annotation, "PROJECT_ROOT", empty_project)
    monkeypatch.setattr(LocalServer.__init__, "__defaults__", (empty_project,))
    monkeypatch.setattr(LocalServer, "serve_forever", fake_serve_forever)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: b"fd\npipe\n")
    monkeypatch.setattr(webbrowser, "open", lambda url: True)
    monkeypatch.setattr(sys, "argv", ["review_run_annotation.py", "--no-browser"])

    review_run_annotation.main()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert_中文提示(output, EXPECTED_DEFAULT_CSV)
    assert_中文提示(output, EXPECTED_DEFAULT_VIDEOS)
    # 提示之后仍然启动服务，缺默认值不阻止标注页面运行。
    assert len(served) == 1
