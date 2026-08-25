from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

import pipeline.scripts.rebuild_data as rebuild_cli
from pipeline.current_data import current_data_context
from pipeline.source_bootstrap import (
    MAPPING_COLUMNS,
    TAG_COLUMNS,
    SourceBootstrapError,
)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _fake_probe(_: Path) -> dict[str, int | float]:
    return {
        "width": 640,
        "height": 480,
        "codec_name": "h264",
        "fps_num": 30,
        "fps_den": 1,
        "fps": 30.0,
        "duration_us": 10_000_000,
        "total_frames": 300,
    }


def _make_source_project(tmp_path: Path, count: int = 9) -> Path:
    project = tmp_path / "repo"
    current = current_data_context(project)
    current.videos.mkdir(parents=True)
    tags: list[dict[str, str]] = []
    mappings: list[dict[str, str]] = []
    for index in range(1, count + 1):
        video_id = f"video_{index:04d}"
        (current.videos / f"{video_id}.mp4").write_bytes(
            f"fake-{video_id}".encode()
        )
        tag = {column: "" for column in TAG_COLUMNS}
        tag.update(
            {
                "id": video_id,
                "video_path": f"data/01_videos/{video_id}.mp4",
                "断裂模式": "未断裂",
                "材料类型": "金属",
                "清晰度": "480P",
                "断裂位置": "N/A",
                "视频帧率": "30",
                "视频总帧数": "300",
                "视频时长": "10",
                "has_fracture": "FALSE",
                "is_abnormal": "FALSE",
            }
        )
        tags.append(tag)
        mapping = {column: "" for column in MAPPING_COLUMNS}
        mapping.update(
            {
                "标准化文件名": f"{video_id}.mp4",
                "原始文件名": f"raw-{index}.mp4",
                "来源目录": "raw-video/fetch",
                "材料类别": "金属",
                "状态": "existing",
                "duration": "10",
                "resolution": "640x480",
                "codec": "h264",
            }
        )
        mappings.append(mapping)
    _write_csv(current.annotations / "all_videos_tag.csv", TAG_COLUMNS, tags)
    _write_csv(current.annotations / "video_mapping.csv", MAPPING_COLUMNS, mappings)
    return project


def _run_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    project: Path,
    run_root: Path,
    *extra_args: str,
    expected_count: int = 9,
) -> tuple[int, dict[str, object], str]:
    monkeypatch.setattr(rebuild_cli, "PROJECT_ROOT", project)
    monkeypatch.setattr(rebuild_cli, "_probe_video", _fake_probe)
    monkeypatch.setattr(rebuild_cli, "_git_commit", lambda: "abc123")
    monkeypatch.setattr(rebuild_cli, "_tool_version", lambda _: "1.0")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebuild_data.py",
            "run",
            "--run-root",
            str(run_root),
            "--expected-count",
            str(expected_count),
            *extra_args,
        ],
    )
    rc = rebuild_cli.main()
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err
    try:
        parsed = json.loads(out) if out.strip() else {}
    except json.JSONDecodeError as exc:
        raise AssertionError(f"stdout is not valid JSON: {out!r}") from exc
    return rc, parsed, err


def test_source_only_materializes_source_and_split_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    run_root = project / "workspace/data-staging/run-test"

    rc, parsed, _ = _run_rebuild(
        monkeypatch, capsys, project, run_root, "--source-only"
    )

    assert rc == 0
    assert parsed.get("source_only") is True
    source_id = parsed["source_snapshot_id"]
    split_id = parsed["split_snapshot_id"]

    data_root = run_root / "data"
    source_snapshot = data_root / "derived/metadata/source_snapshots" / source_id
    split_snapshot = data_root / "derived/metadata/split_snapshots" / split_id
    assert source_snapshot.is_dir()
    assert split_snapshot.is_dir()
    assert (source_snapshot / "source_manifest.json").is_file()
    assert (split_snapshot / "split_manifest.json").is_file()

    rebuild = json.loads((run_root / "control/rebuild.json").read_text())
    assert rebuild["state"] == "source_snapshotted"
    assert rebuild["artifacts"]["source_snapshot_id"] == source_id
    assert rebuild["artifacts"]["split_snapshot_id"] == split_id


def test_source_only_does_not_require_roi_or_review_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    run_root = project / "workspace/data-staging/run-test"

    rc, parsed, _ = _run_rebuild(
        monkeypatch, capsys, project, run_root, "--source-only"
    )

    assert rc == 0
    assert parsed.get("source_only") is True


def test_source_only_with_check_only_validates_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    run_root = project / "workspace/data-staging/run-test"

    rc, parsed, _ = _run_rebuild(
        monkeypatch, capsys, project, run_root, "--source-only", "--check-only"
    )

    assert rc == 0
    assert parsed.get("check_only") is True
    assert parsed["status"] == "source_validated"
    assert "source_snapshot_id" in parsed
    assert "identity_sha256" in parsed
    assert "validation" in parsed
    assert "split_counts" in parsed
    assert not run_root.exists()


def test_source_only_repeated_run_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    run_root = project / "workspace/data-staging/run-test"

    rc1, parsed1, _ = _run_rebuild(
        monkeypatch, capsys, project, run_root, "--source-only"
    )
    assert rc1 == 0

    rc2, parsed2, _ = _run_rebuild(
        monkeypatch, capsys, project, run_root, "--source-only"
    )
    assert rc2 == 0

    assert parsed1["source_snapshot_id"] == parsed2["source_snapshot_id"]
    assert parsed1["source_snapshot"] == parsed2["source_snapshot"]
    assert parsed1["split_snapshot_id"] == parsed2["split_snapshot_id"]


def test_source_only_fails_when_videos_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    # remove one video to break the expected count invariant
    current = current_data_context(project)
    list(current.videos.glob("*.mp4"))[0].unlink()
    run_root = project / "workspace/data-staging/run-test"

    rc, _, err = _run_rebuild(monkeypatch, capsys, project, run_root, "--source-only")

    assert rc == 1
    assert "错误:" in err


def test_source_only_fails_when_tag_csv_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    current = current_data_context(project)
    (current.annotations / "all_videos_tag.csv").unlink()
    run_root = project / "workspace/data-staging/run-test"

    rc, _, err = _run_rebuild(monkeypatch, capsys, project, run_root, "--source-only")

    assert rc == 1
    assert "错误:" in err


def test_full_pipeline_still_requires_roi_and_review_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _make_source_project(tmp_path)
    run_root = project / "workspace/data-staging/run-test"

    rc, _, err = _run_rebuild(monkeypatch, capsys, project, run_root)

    assert rc == 1
    assert "错误:" in err
