from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from pipeline.current_data import current_data_context, data_context_for_root
from pipeline.source_bootstrap import (
    MAPPING_COLUMNS,
    TAG_COLUMNS,
    SourceBootstrapError,
    build_source_snapshot,
    materialize_source_snapshot,
    stratified_split,
)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(project: Path, count: int = 9) -> None:
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


def test_source_snapshot_is_deterministic_and_materializes_isolated_copy(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    _fixture(project)
    current = current_data_context(project)
    rebuild = data_context_for_root(
        project,
        project / "workspace/data-rebuild/rebuild-test/data",
    )

    first = build_source_snapshot(
        current,
        rebuild,
        expected_count=9,
        probe=_probe,
    )
    second = build_source_snapshot(
        current,
        rebuild,
        expected_count=9,
        probe=_probe,
    )

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["validation"]["material_difference_count"] == 1
    assert set(first["splits"]) == {
        "test",
        "fold_0_train",
        "fold_0_val",
        "fold_1_train",
        "fold_1_val",
        "fold_2_train",
        "fold_2_val",
    }
    destination = materialize_source_snapshot(first)
    assert destination.name == first["snapshot_id"]
    assert len(list(rebuild.videos.glob("*.mp4"))) == 9
    assert not any(path.is_symlink() for path in rebuild.root.rglob("*"))
    metadata = json.loads((destination / "video_meta.json").read_text())
    assert metadata[0]["video_path"] == "source/videos/video_0001.mp4"
    assert materialize_source_snapshot(second) == destination


def test_source_snapshot_resume_rejects_metadata_drift(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _fixture(project)
    bundle = build_source_snapshot(
        current_data_context(project),
        data_context_for_root(
            project,
            project / "workspace/data-rebuild/rebuild-test/data",
        ),
        expected_count=9,
        probe=_probe,
    )
    destination = materialize_source_snapshot(bundle)
    (destination / "video_meta.json").write_text("[]\n")

    with pytest.raises(SourceBootstrapError, match="SHA-256 漂移"):
        materialize_source_snapshot(bundle)


def test_source_snapshot_resume_rejects_staged_symlink(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _fixture(project)
    rebuild = data_context_for_root(
        project,
        project / "workspace/data-rebuild/rebuild-test/data",
    )
    bundle = build_source_snapshot(
        current_data_context(project),
        rebuild,
        expected_count=9,
        probe=_probe,
    )
    materialize_source_snapshot(bundle)
    staged = rebuild.videos / "video_0001.mp4"
    staged.unlink()
    staged.symlink_to(current_data_context(project).videos / staged.name)

    with pytest.raises(SourceBootstrapError, match="内容不同|物理文件"):
        materialize_source_snapshot(bundle)


def test_source_snapshot_rejects_duplicate_tag_id(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _fixture(project, count=3)
    path = current_data_context(project).annotations / "all_videos_tag.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    rows[1]["id"] = rows[0]["id"]
    _write_csv(path, TAG_COLUMNS, rows)

    with pytest.raises(SourceBootstrapError, match="重复 ID"):
        build_source_snapshot(
            current_data_context(project),
            data_context_for_root(
                project,
                project / "workspace/data-rebuild/rebuild-test/data",
            ),
            expected_count=3,
            probe=_probe,
        )


def test_historical_split_membership_golden() -> None:
    compact_records = """\
韧性断裂|i
未夹紧|-
脆性断裂|i
界面脱粘|i
视频异常|-
韧性断裂|i
韧性断裂|i
脆性断裂|o
界面脱粘|i
韧性断裂|i
韧性断裂|i
韧性断裂|i
韧性断裂|i
半脆半韧断裂|i
韧性断裂|i
韧性断裂|i
界面脱粘、齐根断裂|o
韧性断裂|i
韧性断裂|i
界面脱粘|i
韧性断裂|i
韧性断裂|i
韧性断裂|i
韧性断裂|i
齐根断裂|o
爆炸性断裂|i
界面脱粘、齐根断裂|o
韧性断裂|i
脆性断裂|o
韧性断裂|i
齐根断裂|o
脆性断裂|i
韧性断裂|o
未断裂|-
韧性断裂|i
未断裂|-
界面脱粘|i
韧性断裂|i
韧性断裂|i
爆炸性断裂|i
脆性断裂|i
视频异常|-
界面脱粘|i
界面脱粘|i
韧性断裂|o
韧性断裂|i
脆性断裂|o
齐根断裂|o
未断裂|-
韧性断裂|i
韧性断裂|i
未断裂|-
界面脱粘|i
未断裂|-
韧性断裂|o
未断裂|-
韧性断裂|i
视频异常|-
齐根断裂|o
齐根断裂|o
韧性断裂|i
韧性断裂|i
界面脱粘|i
未断裂|-
脆性断裂|i
未断裂|-
韧性断裂|i
韧性断裂|i
视频异常|-
韧性断裂|i
脆性断裂|i
韧性断裂|i
韧性断裂|i
韧性断裂|o
脆性断裂|i
齐根断裂|o
韧性断裂|i
脆性断裂|i
脆性断裂|i
韧性断裂|i
韧性断裂|i
韧性断裂|o
未断裂|-
韧性断裂|i
韧性断裂|i
韧性断裂|i
未断裂|-
韧性断裂|o
韧性断裂|i
韧性断裂|i
韧性断裂|o
韧性断裂|o
韧性断裂|i
未断裂|-
未断裂|-
未断裂|-
韧性断裂|i
韧性断裂|i
韧性断裂|o
脆性断裂|o
脆性断裂|i
脆性断裂|o
脆性断裂|i
脆性断裂|i
脆性断裂|i
未断裂|-
未断裂|-
脆性断裂|i
脆性断裂|o
脆性断裂|o"""
    locations = {"i": "inside_gauge", "o": "outside_gauge", "-": None}
    records = [
        {
            "video_id": f"video_{index:04d}",
            "type": line.split("|", 1)[0],
            "location_canonical": locations[line.rsplit("|", 1)[1]],
        }
        for index, line in enumerate(compact_records.splitlines(), start=1)
    ]
    assert len(records) == 110
    actual, _ = stratified_split(records)
    expected_hashes = {
        "test": "553db89d302449c4d8640362db5da77678335bba109005ed480f44ded3f09e2d",
        "fold_0_train": "4cc0a634f62cd15c18e0f25760c994b387304faa4e91cfdf228db4f89f5d3264",
        "fold_0_val": "890a05ede9c01fa57fb0abc2342726cdb6c988ab0e3d6f510f6d66d808874b7a",
        "fold_1_train": "da29fb9b64f8b4fd053601d842213d8e7df64c9aafa8852cd721abcd42a12723",
        "fold_1_val": "f8846307234843a3ffd8afdeffbe1eb11a35ba2de324b9d2cd86bcbf5bed4cce",
        "fold_2_train": "e278f81166ddbe9db26ee55f68ebb24e8de4f6e1796d4f92d9665327c491d14b",
        "fold_2_val": "68aca105e1b35945bdafde8343acc36312c45910618c5692a16ae20ae890f336",
    }
    for name, expected_hash in expected_hashes.items():
        membership = (
            json.dumps(
                sorted(actual[name]),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        assert hashlib.sha256(membership).hexdigest() == expected_hash
