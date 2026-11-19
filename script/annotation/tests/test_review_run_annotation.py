from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest

from script.annotation.review_run_annotation import LocalServer, PROJECT_ROOT


DEFAULT_CSV = Path("data/annotation-table-full.csv")
DEFAULT_VIDEOS = Path("data/videos")
ORIGINAL_CSV = "id,video_path,断裂模式,断裂位置,断裂时间点\n1,video.mp4,无,无,无\n"


def test_project_root_matches_migrated_script_location():
    assert PROJECT_ROOT == Path(__file__).resolve().parents[3]


@pytest.fixture
def annotation_server(tmp_path):
    project = tmp_path / "project"
    csv_path = project / DEFAULT_CSV
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(ORIGINAL_CSV, encoding="utf-8")
    video_directory = project / DEFAULT_VIDEOS
    video_directory.mkdir(parents=True)
    (video_directory / "video.mp4").write_bytes(b"default video")

    with LocalServer(project_root=project) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server, project
        finally:
            server.shutdown()
            thread.join()


def request(server, method, route, payload=None, *, header_overrides=None):
    headers = {
        "Origin": server.origin,
        "Sec-Fetch-Site": "same-origin",
        "X-Annotation-Session": server.token,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    for name, value in (header_overrides or {}).items():
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
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


def test_default_sources_open_without_upload_and_can_be_reloaded(annotation_server):
    server, project = annotation_server
    status, defaults = request(server, "GET", "/api/default-sources")
    assert status == HTTPStatus.OK
    assert defaults["csv_path"] == str(DEFAULT_CSV)
    assert defaults["video_directory"] == str(DEFAULT_VIDEOS)

    # Each request uses a new connection and sends only the path, with no file upload.
    for _ in range(2):
        status, csv = request(server, "POST", "/api/csv/read", {"path": defaults["csv_path"]})
        assert status == HTTPStatus.OK
        assert Path(csv["path"]) == (project / DEFAULT_CSV).resolve()
        assert csv["csv"] == ORIGINAL_CSV

        status, library = request(server, "POST", "/api/video/library", {"path": defaults["video_directory"]})
        assert status == HTTPStatus.OK
        assert [item["relative_path"] for item in library["files"]] == ["video.mp4"]
        status, video = request(server, "GET", f"/api/video/file/{library['files'][0]['id']}")
        assert status == HTTPStatus.OK
        assert video == b"default video"


def test_external_paths_load_and_save_without_modifying_default_sources(annotation_server, tmp_path):
    server, project = annotation_server
    external = tmp_path / "自选 数据"
    video_directory = external / "视频"
    nested = video_directory / "批次一"
    nested.mkdir(parents=True)
    video_path = nested / "video.mp4"
    video_path.write_bytes(b"external video")
    csv_path = external / "自选表.csv"
    csv_path.write_text(ORIGINAL_CSV, encoding="utf-8")

    status, csv = request(server, "POST", "/api/csv/read", {"path": str(csv_path)})
    assert status == HTTPStatus.OK
    assert Path(csv["path"]) == csv_path.resolve()
    assert csv["csv"] == ORIGINAL_CSV
    assert csv["sha256"] == hashlib.sha256(ORIGINAL_CSV.encode()).hexdigest()

    updated_csv = ORIGINAL_CSV.replace("无,无,无", "韧性断裂,标距内,2.5")
    status, result = request(server, "POST", "/api/csv/write", {
        "path": csv["path"],
        "expected_sha256": csv["sha256"],
        "csv": updated_csv,
    })
    assert status == HTTPStatus.OK
    assert csv_path.read_bytes() == updated_csv.encode("utf-8")
    assert (project / DEFAULT_CSV).read_text(encoding="utf-8") == ORIGINAL_CSV
    status, reloaded = request(server, "POST", "/api/csv/read", {"path": csv["path"]})
    assert status == HTTPStatus.OK
    assert reloaded["csv"] == updated_csv
    assert reloaded["sha256"] == result["sha256"]

    status, library = request(server, "POST", "/api/video/library", {"path": str(video_directory)})
    assert status == HTTPStatus.OK
    assert Path(library["path"]) == video_directory.resolve()
    assert [item["relative_path"] for item in library["files"]] == ["批次一/video.mp4"]
    status, video = request(server, "GET", f"/api/video/file/{library['files'][0]['id']}")
    assert status == HTTPStatus.OK
    assert video == b"external video"


def test_csv_write_preserves_changes_from_an_external_program(annotation_server):
    server, project = annotation_server
    status, csv = request(server, "POST", "/api/csv/read", {"path": str(DEFAULT_CSV)})
    assert status == HTTPStatus.OK

    original_file = project / DEFAULT_CSV
    external_change = ORIGINAL_CSV.replace("无,无,无", "脆性断裂,夹持根部,1.0")
    original_file.write_text(external_change, encoding="utf-8")
    status, _ = request(server, "POST", "/api/csv/write", {
        "path": csv["path"],
        "expected_sha256": csv["sha256"],
        "csv": ORIGINAL_CSV.replace("无,无,无", "韧性断裂,标距内,2.5"),
    })
    assert status == HTTPStatus.CONFLICT
    assert original_file.read_bytes() == external_change.encode("utf-8")


def test_invalid_source_paths_leave_existing_files_and_video_access_intact(annotation_server, tmp_path):
    server, project = annotation_server
    status, csv = request(server, "POST", "/api/csv/read", {"path": str(DEFAULT_CSV)})
    assert status == HTTPStatus.OK
    status, library = request(server, "POST", "/api/video/library", {"path": str(DEFAULT_VIDEOS)})
    assert status == HTTPStatus.OK
    video_id = library["files"][0]["id"]

    missing_csv = tmp_path / "missing.csv"
    status, _ = request(server, "POST", "/api/csv/read", {"path": str(missing_csv)})
    assert 400 <= status < 500
    status, _ = request(server, "POST", "/api/csv/write", {
        "path": str(missing_csv),
        "expected_sha256": csv["sha256"],
        "csv": ORIGINAL_CSV,
    })
    assert 400 <= status < 500
    assert not missing_csv.exists()
    assert (project / DEFAULT_CSV).read_text(encoding="utf-8") == ORIGINAL_CSV

    unopened_csv = tmp_path / "unopened.csv"
    unopened_csv.write_text(ORIGINAL_CSV, encoding="utf-8")
    status, _ = request(server, "POST", "/api/csv/write", {
        "path": str(unopened_csv.resolve()),
        "expected_sha256": csv["sha256"],
        "csv": ORIGINAL_CSV.replace("无,无,无", "韧性断裂,标距内,2.5"),
    })
    assert status == HTTPStatus.FORBIDDEN
    assert unopened_csv.read_text(encoding="utf-8") == ORIGINAL_CSV

    status, _ = request(server, "POST", "/api/video/library", {"path": str(tmp_path / "missing-videos")})
    assert 400 <= status < 500
    status, video = request(server, "GET", f"/api/video/file/{video_id}")
    assert status == HTTPStatus.OK
    assert video == b"default video"


@pytest.mark.parametrize("headers", [
    {"X-Annotation-Session": None},
    {"Origin": "http://example.invalid"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Host": "example.invalid"},
])
def test_sensitive_file_requests_reject_other_clients(annotation_server, headers):
    server, project = annotation_server
    status, library = request(server, "POST", "/api/video/library", {"path": str(DEFAULT_VIDEOS)})
    assert status == HTTPStatus.OK
    video_id = library["files"][0]["id"]

    status, _ = request(server, "POST", "/api/csv/read", {"path": str(DEFAULT_CSV)}, header_overrides=headers)
    assert status == HTTPStatus.FORBIDDEN
    status, _ = request(server, "POST", "/api/csv/write", {
        "path": str((project / DEFAULT_CSV).resolve()),
        "expected_sha256": hashlib.sha256(ORIGINAL_CSV.encode()).hexdigest(),
        "csv": ORIGINAL_CSV.replace("无,无,无", "韧性断裂,标距内,2.5"),
    }, header_overrides=headers)
    assert status == HTTPStatus.FORBIDDEN
    assert (project / DEFAULT_CSV).read_text(encoding="utf-8") == ORIGINAL_CSV
    status, _ = request(server, "GET", f"/api/video/file/{video_id}", header_overrides=headers)
    assert status == HTTPStatus.FORBIDDEN


def test_video_library_cannot_read_links_to_files_outside_selected_directory(annotation_server, tmp_path):
    server, project = annotation_server
    video_directory = project / DEFAULT_VIDEOS
    outside_video = tmp_path / "outside.mp4"
    outside_video.write_bytes(b"outside the selected video library")
    (video_directory / "linked.mp4").symlink_to(outside_video)

    status, library = request(server, "POST", "/api/video/library", {"path": str(DEFAULT_VIDEOS)})
    assert status == HTTPStatus.OK
    assert [item["relative_path"] for item in library["files"]] == ["video.mp4"]

    original_video = video_directory / "video.mp4"
    original_video.unlink()
    original_video.symlink_to(outside_video)
    status, _ = request(server, "GET", f"/api/video/file/{library['files'][0]['id']}")
    assert 400 <= status < 500
