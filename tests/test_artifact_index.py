from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from pipeline import artifact_index
from pipeline.current_data import current_data_context, data_context_for_root
from pipeline.roi_manifest import build_roi_manifest_bundle, write_roi_manifest_bundle
from pipeline.roi_media import materialize_plan
from pipeline.scripts import roi_annotation_app as app
from pipeline.scripts.build_artifact_index import main
from pipeline.source_bootstrap import (
    MAPPING_COLUMNS,
    TAG_COLUMNS,
    build_source_snapshot,
    materialize_source_snapshot,
    materialize_split_snapshot,
)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _source_fixture(project: Path, count: int = 9) -> None:
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
                "材料类别": "高分子" if index == 1 else "金属",
                "状态": "existing",
                "duration": "10",
                "resolution": "640x480",
                "codec": "h264",
            }
        )
        mappings.append(mapping)
    _write_csv(
        current.annotations / "all_videos_tag.csv",
        TAG_COLUMNS,
        tags,
    )
    _write_csv(
        current.annotations / "video_mapping.csv",
        MAPPING_COLUMNS,
        mappings,
    )


def _probe(_: Path) -> dict[str, int | float]:
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


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _roi_fixture(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path
    videos_dir = root / "data/01_videos"
    videos_dir.mkdir(parents=True)
    video1 = videos_dir / "video_0001.mp4"
    video2 = videos_dir / "video_0002.mp4"
    video1.write_bytes(b"video-one")
    video2.write_bytes(b"video-two")
    metadata = _write_json(
        root / "data/07_metadata/video_meta.json",
        [
            {"video_id": "video_0001", "video_path": "data/01_videos/video_0001.mp4"},
            {"video_id": "video_0002", "video_path": "data/01_videos/video_0002.mp4"},
        ],
    )
    test_manifest = _write_json(
        root / "data/05_splits/test.json",
        {"video_ids": ["video_0002"], "count": 1},
    )
    dragged_box = {"x": 148, "y": 162, "width": 222, "height": 296}
    decisions = {
        "video_0001": app.build_decision(
            video_id="video_0001",
            video_path=video1,
            mode=app.MODE_FIXED,
            review_status=app.STATUS_APPROVED,
            margins={"top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
            source_width=456,
            source_height=670,
            reviewed_timestamps=[0.0, 1.0, 2.0],
            source_sha256=__import__("hashlib").sha256(video1.read_bytes()).hexdigest(),
            source_video_reference="data/01_videos/video_0001.mp4",
            visibility_checks={key: True for key in app.VISIBILITY_CHECK_KEYS},
            pixel_box_override=dragged_box,
        ),
        "video_0002": app.build_decision(
            video_id="video_0002",
            video_path=video2,
            mode=app.MODE_NO_CROP,
            review_status=app.STATUS_APPROVED,
            margins={"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0},
            source_width=924,
            source_height=946,
            reviewed_timestamps=[0.0, 1.0, 2.0],
            source_sha256=__import__("hashlib").sha256(video2.read_bytes()).hexdigest(),
            source_video_reference="data/01_videos/video_0002.mp4",
            visibility_checks={key: True for key in app.VISIBILITY_CHECK_KEYS},
        ),
    }
    decisions_path = root / "data/07_metadata/roi_decisions.json"
    app.save_roi_payload(
        decisions_path,
        decisions,
        metadata_path=metadata,
    )
    return {
        "decisions_path": decisions_path,
        "video_metadata_path": metadata,
        "test_manifest_path": test_manifest,
        "project_root": root,
    }


def test_validate_entry_requires_fields() -> None:
    with pytest.raises(ValueError, match="id"):
        artifact_index.validate_entry({"created_at": "x", "step": "source"})
    with pytest.raises(ValueError, match="created_at"):
        artifact_index.validate_entry({"id": "x", "step": "source"})
    with pytest.raises(ValueError, match="step"):
        artifact_index.validate_entry({"id": "x", "created_at": "x"})


def test_append_and_read_creates_index(tmp_path: Path) -> None:
    collection_dir = tmp_path / "collection"
    entry = {
        "id": "artifact-abc123",
        "created_at": "2026-07-20T00:00:00+00:00",
        "step": "source",
        "inputs": {},
        "stats": {"count": 3},
    }
    artifact_index.append_entry(collection_dir, entry)
    index = artifact_index.read_index(collection_dir)
    assert index == [entry]


def test_append_is_idempotent(tmp_path: Path) -> None:
    collection_dir = tmp_path / "collection"
    entry = {
        "id": "artifact-abc123",
        "created_at": "2026-07-20T00:00:00+00:00",
        "step": "source",
        "inputs": {},
        "stats": {"count": 3},
    }
    artifact_index.append_entry(collection_dir, entry)
    artifact_index.append_entry(collection_dir, entry)
    assert len(artifact_index.read_index(collection_dir)) == 1


def test_append_rejects_conflicting_id(tmp_path: Path) -> None:
    collection_dir = tmp_path / "collection"
    entry = {
        "id": "artifact-abc123",
        "created_at": "2026-07-20T00:00:00+00:00",
        "step": "source",
        "inputs": {},
        "stats": {"count": 3},
    }
    artifact_index.append_entry(collection_dir, entry)
    conflicting = {**entry, "stats": {"count": 4}}
    with pytest.raises(ValueError, match="冲突"):
        artifact_index.append_entry(collection_dir, conflicting)


def test_atomic_write_keeps_index_intact_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_dir = tmp_path / "collection"
    entry = {
        "id": "artifact-abc123",
        "created_at": "2026-07-20T00:00:00+00:00",
        "step": "source",
        "inputs": {},
        "stats": {"count": 3},
    }
    artifact_index.append_entry(collection_dir, entry)

    def failing_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError("simulated")

    monkeypatch.setattr("os.replace", failing_replace)
    with pytest.raises(OSError, match="simulated"):
        artifact_index.append_entry(
            collection_dir,
            {
                "id": "artifact-def456",
                "created_at": "2026-07-20T00:00:00+00:00",
                "step": "source",
                "inputs": {},
                "stats": {"count": 5},
            },
        )
    monkeypatch.undo()

    assert artifact_index.read_index(collection_dir) == [entry]


def test_source_snapshot_appends_index_entries(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _source_fixture(project)
    current = current_data_context(project)
    rebuild = data_context_for_root(
        project,
        project / "workspace/data-staging/rebuild-test/data",
    )
    bundle = build_source_snapshot(
        current,
        rebuild,
        expected_count=9,
        probe=_probe,
    )
    materialize_source_snapshot(bundle)
    materialize_split_snapshot(bundle)

    source_index = artifact_index.read_index(
        rebuild.metadata_collection("source_snapshots")
    )
    assert len(source_index) == 1
    assert source_index[0]["id"] == bundle["snapshot_id"]
    assert source_index[0]["step"] == "source"
    assert source_index[0]["stats"]["video_count"] == 9

    split_index = artifact_index.read_index(
        rebuild.metadata_collection("split_snapshots")
    )
    assert len(split_index) == 1
    assert split_index[0]["id"] == bundle["split_snapshot_id"]
    assert split_index[0]["step"] == "source"
    assert split_index[0]["inputs"]["source_snapshot"] == bundle["snapshot_id"]


def test_roi_manifest_appends_index_entry(tmp_path: Path) -> None:
    paths = _roi_fixture(tmp_path / "inputs")
    bundle = build_roi_manifest_bundle(**paths)
    collection_dir = tmp_path / "out"
    write_roi_manifest_bundle(collection_dir, bundle)

    index = artifact_index.read_index(collection_dir)
    assert len(index) == 1
    entry = index[0]
    assert entry["id"] == bundle["manifest.json"]["roi_manifest_id"]
    assert entry["step"] == "roi"
    assert entry["stats"]["total_source_count"] == 2
    assert set(entry["stats"]["mode_counts"]) == {"fixed_roi", "no_crop"}


def test_roi_media_appends_index_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    roi_videos_dir = project / "derived/roi_videos"
    roi_videos_dir.mkdir(parents=True)
    manifest_id = "roi-manifest-test"
    plan: dict[str, Any] = {
        "media_id": "roi-media-testid",
        "identity": {
            "schema_version": "tensile-roi-media/v1",
            "roi_manifest_id": manifest_id,
            "roi_manifest_sha256": "a" * 64,
            "encoding_profile": {},
            "selected_video_ids": ["video_0001"],
        },
        "rows": [
            {
                "video_id": "video_0001",
                "video": {"video_id": "video_0001"},
                "decision": {
                    "source_video_id": "video_0001",
                    "mode": "fixed_roi",
                    "source_resolution": [222, 296],
                    "pixel_box": {"x": 0, "y": 0, "width": 222, "height": 296},
                    "source_sha256": "b" * 64,
                    "source_video_path": "source/videos/video_0001.mp4",
                },
                "source_path": project / "source/videos/video_0001.mp4",
                "video_filter": "crop=222:296:0:0,setsar=1",
                "output_resolution": (222, 296),
            }
        ],
        "source_count": 1,
        "full_scope": True,
        "project_root": str(project),
    }

    def fake_materialize_one(row: Any, destination: Path) -> dict[str, Any]:
        output_path = destination / "videos" / f"{row['video_id']}.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"roi-video")
        return {
            "source_video_id": row["video_id"],
            "source_video_path": row["decision"].get("source_video_path"),
            "source_sha256": row["decision"]["source_sha256"],
            "mode": row["decision"]["mode"],
            "pixel_box": row["decision"]["pixel_box"],
            "input_resolution": list(row["decision"]["source_resolution"]),
            "output_resolution": list(row["output_resolution"]),
            "source_frame_rate": "25/1",
            "source_nominal_frame_rate": "25/1",
            "source_frame_count": 100,
            "source_duration": 4.0,
            "frame_rate": "25/1",
            "nominal_frame_rate": "25/1",
            "frame_count": 100,
            "duration": 4.0,
            "video_filter": row["video_filter"],
            "output_path": str(output_path),
            "output_sha256": __import__("hashlib").sha256(output_path.read_bytes()).hexdigest(),
            "output_size_bytes": output_path.stat().st_size,
            "reused_existing": False,
        }

    monkeypatch.setattr("pipeline.roi_media._materialize_one", fake_materialize_one)

    materialize_plan(plan, roi_videos_dir, workers=1)

    index = artifact_index.read_index(roi_videos_dir)
    assert len(index) == 1
    entry = index[0]
    assert entry["id"] == "roi-media-testid"
    assert entry["step"] == "roi"
    assert entry["inputs"]["roi_manifest"] == manifest_id
    assert entry["stats"]["source_count"] == 1


def test_build_index_cli_includes_new_collections(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    collections = {
        "derived/subvideos": ("subvideo-plan-abc123", "subvideo"),
        "derived/frames": ("frame-plan-abc123", "frame"),
        "derived/metadata/review_queues": ("v4-1-review-abc123", "review"),
        "derived/metadata/review_decisions": ("review-batch-abc123", "review"),
        "releases": ("v4.1.0-abc123", "release"),
    }
    for relative, (artifact_id, step) in collections.items():
        collection_dir = data_root / relative
        collection_dir.mkdir(parents=True)
        artifact_index.append_entry(
            collection_dir,
            {
                "id": artifact_id,
                "created_at": "2026-07-20T02:00:00+00:00",
                "step": step,
                "inputs": {"upstream": "upstream-id"},
                "stats": {"count": 1},
            },
        )

    assert main(["--data-root", str(data_root)]) == 0

    content = (data_root / "INDEX.md").read_text(encoding="utf-8")
    for artifact_id, _ in collections.values():
        assert artifact_id in content


def test_build_index_cli_generates_index_markdown(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source_dir = data_root / "derived/metadata/source_snapshots"
    roi_dir = data_root / "derived/roi_videos"
    source_dir.mkdir(parents=True)
    roi_dir.mkdir(parents=True)

    artifact_index.append_entry(
        source_dir,
        {
            "id": "source-snapshot-abc123",
            "created_at": "2026-07-20T00:00:00+00:00",
            "step": "source",
            "inputs": {},
            "stats": {"video_count": 9},
            "note": "test",
        },
    )
    artifact_index.append_entry(
        roi_dir,
        {
            "id": "roi-media-def456",
            "created_at": "2026-07-20T01:00:00+00:00",
            "step": "roi",
            "inputs": {"roi_manifest": "roi-manifest-xyz"},
            "stats": {"source_count": 2},
        },
    )

    assert main(["--data-root", str(data_root)]) == 0

    index_md = data_root / "INDEX.md"
    assert index_md.is_file()
    content = index_md.read_text(encoding="utf-8")
    assert "| source | source-snapshot-abc123 |" in content
    assert "| roi | roi-media-def456 |" in content
    assert "video_count" in content
    assert "roi-manifest-xyz" in content


def test_build_index_cli_skips_missing_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_root = tmp_path / "data"
    (data_root / "derived/metadata/source_snapshots").mkdir(parents=True)
    (data_root / "derived/metadata/roi_manifests").mkdir(parents=True)

    assert main(["--data-root", str(data_root)]) == 0

    index_md = data_root / "INDEX.md"
    assert index_md.is_file()
    content = index_md.read_text(encoding="utf-8")
    assert "source_snapshots" in content or "产物索引" in content
    captured = capsys.readouterr()
    assert "跳过" in captured.err or "roi_manifests" in captured.err


@pytest.mark.parametrize(
    "bad_payload",
    [
        pytest.param("not-json-object", id="string"),
        pytest.param([{"id": "bad"}], id="array"),
        pytest.param({"artifacts": "not-a-list"}, id="wrong-structure"),
        pytest.param({"missing": "artifacts"}, id="missing-artifacts"),
    ],
)
def test_build_index_cli_warns_on_malformed_index_and_continues(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bad_payload: Any,
) -> None:
    data_root = tmp_path / "data"
    source_dir = data_root / "derived/metadata/source_snapshots"
    split_dir = data_root / "derived/metadata/split_snapshots"
    source_dir.mkdir(parents=True)
    split_dir.mkdir(parents=True)

    _write_json(source_dir / "index.json", bad_payload)
    artifact_index.append_entry(
        split_dir,
        {
            "id": "split-healthy",
            "created_at": "2026-07-20T02:00:00+00:00",
            "step": "source",
            "inputs": {"source_snapshot": "source-abc"},
            "stats": {"count": 1},
        },
    )

    assert main(["--data-root", str(data_root)]) == 0

    captured = capsys.readouterr()
    assert "source_snapshots" in captured.err
    assert "索引" in captured.err or "warning" in captured.err.lower()

    index_md = data_root / "INDEX.md"
    assert index_md.is_file()
    content = index_md.read_text(encoding="utf-8")
    assert "split-healthy" in content
    assert "source-abc" in content


def test_build_index_cli_warns_on_permission_denied_index_and_continues(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    source_dir = data_root / "derived/metadata/source_snapshots"
    split_dir = data_root / "derived/metadata/split_snapshots"
    source_dir.mkdir(parents=True)
    split_dir.mkdir(parents=True)

    _write_json(source_dir / "index.json", {"artifacts": []})
    artifact_index.append_entry(
        split_dir,
        {
            "id": "split-healthy",
            "created_at": "2026-07-20T02:00:00+00:00",
            "step": "source",
            "inputs": {"source_snapshot": "source-abc"},
            "stats": {"count": 1},
        },
    )

    real_read_text = Path.read_text

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == source_dir / "index.json":
            raise PermissionError(13, "Permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert main(["--data-root", str(data_root)]) == 0

    captured = capsys.readouterr()
    assert "source_snapshots" in captured.err
    assert "索引" in captured.err

    index_md = data_root / "INDEX.md"
    assert index_md.is_file()
    content = index_md.read_text(encoding="utf-8")
    assert "split-healthy" in content
    assert "source-abc" in content
    assert "not-json-object" not in content


@pytest.mark.parametrize("arguments", [[], ["--data-root", "/nonexistent/mvllm2-index-root"]])
def test_index_cli_requires_explicit_existing_root(arguments, tmp_path, monkeypatch):
    from pipeline.scripts import build_artifact_index as cli
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(arguments)
    assert exc.value.code == 2
    assert not (tmp_path / "INDEX.md").exists()
