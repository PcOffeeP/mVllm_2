"""`script/checks/virtual_dataset.py` 的单元测试。

使用 `tmp_path` 构造合成虚拟数据集，覆盖契约通过与核心失败场景：
- 正常通过（含 `--dataset-dir` 与 `--all` CLI 退出码 0）
- 脏工作树（`upstream.working_tree_dirty: true`）失败
- SHA-256 不匹配失败（视频与 `labels.csv`）
- 软链接视频失败
- `videos/` 目录存在清单外多余 `.mp4` 文件失败
- `labels.csv` 缺失必需列头失败
- 非法 `git_head` / `manifest_sha256` / `schema` / `source_domain` 失败

失效条件：`script/checks/virtual_dataset.py` 的校验口径、28 列头定义或输出 JSON 结构变更时，
本测试文件需同步修订。
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from script.checks.virtual_dataset import (
    EXPECTED_SCHEMA,
    EXPECTED_SOURCE_DOMAIN,
    REQUIRED_LABEL_COLUMNS,
    check_dataset,
    main,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_labels_csv(
    path: Path,
    columns: list[str] | tuple[str, ...],
    rows: list[dict[str, str]],
) -> bytes:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(col, "") for col in columns])
    return path.read_bytes()


def _build_synthetic_dataset(
    base_dir: Path,
    *,
    dataset_id: str = "video-V-test",
    working_tree_dirty: bool = False,
    git_head: str = "a" * 40,
    upstream_manifest_sha256: str = "b" * 64,
    columns: list[str] | tuple[str, ...] = REQUIRED_LABEL_COLUMNS,
    video_payloads: dict[str, bytes] | None = None,
    manifest_overrides: dict[str, Any] | None = None,
) -> Path:
    dataset_dir = base_dir / dataset_id
    videos_dir = dataset_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    payloads = video_payloads or {
        "sample_01": b"\x00\x00\x00\x18ftypmp42sample-video-one",
        "sample_02": b"\x00\x00\x00\x18ftypmp42sample-video-two-longer",
    }

    video_entries: list[dict[str, Any]] = []
    label_rows: list[dict[str, str]] = []
    total_bytes = 0

    for vid, content in payloads.items():
        rel_path = f"videos/{vid}.mp4"
        vfile = dataset_dir / rel_path
        vfile.write_bytes(content)
        total_bytes += len(content)
        video_entries.append(
            {
                "id": vid,
                "video_path": rel_path,
                "sha256": _sha256_bytes(content),
                "bytes": len(content),
                "duration_s": 20,
                "fps": 30,
                "frames": 600,
            }
        )
        label_rows.append(
            {
                "id": vid,
                "video_path": rel_path,
                "断裂模式": "韧性断裂",
                "材料类型": "金属",
                "断裂状态": "发生断裂",
            }
        )

    labels_path = dataset_dir / "labels.csv"
    labels_bytes = _write_labels_csv(labels_path, columns, label_rows)

    manifest: dict[str, Any] = {
        "schema": EXPECTED_SCHEMA,
        "dataset_id": dataset_id,
        "source_domain": EXPECTED_SOURCE_DOMAIN,
        "upstream": {
            "repo": "BlenderTensileVideo",
            "dataset_path": f"datasets/{dataset_id}",
            "git_branch": "main",
            "git_head": git_head,
            "working_tree_dirty": working_tree_dirty,
            "manifest_sha256": upstream_manifest_sha256,
            "omitted_upstream_assets": ["metadata/"],
        },
        "labels": {
            "path": "labels.csv",
            "sha256": _sha256_bytes(labels_bytes),
            "row_count": len(label_rows),
            "format_reference": "annotation-table-full.csv",
        },
        "video_count": len(video_entries),
        "total_video_bytes": total_bytes,
        "videos": video_entries,
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)

    (dataset_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dataset_dir


def test_valid_synthetic_dataset_passes(tmp_path: Path, capsys) -> None:
    dataset_dir = _build_synthetic_dataset(tmp_path)

    result = check_dataset(dataset_dir)
    assert result["ok"] is True
    assert result["dataset_id"] == "video-V-test"
    assert result["checks"] == {
        "manifest": True,
        "upstream": True,
        "labels": True,
        "videos": True,
    }
    assert result["stats"]["label_rows"] == 2
    assert result["stats"]["video_count"] == 2
    assert result["errors"] == []

    rc = main(["--dataset-dir", str(dataset_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checked_count"] == 1
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 0


def test_cli_all_scans_virtual_root(tmp_path: Path, capsys) -> None:
    _build_synthetic_dataset(tmp_path, dataset_id="video-V1")
    _build_synthetic_dataset(tmp_path, dataset_id="video-V2")

    rc = main(["--all", "--virtual-root", str(tmp_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checked_count"] == 2
    assert [d["dataset_id"] for d in payload["datasets"]] == ["video-V1", "video-V2"]


def test_dirty_working_tree_fails(tmp_path: Path, capsys) -> None:
    dataset_dir = _build_synthetic_dataset(tmp_path, working_tree_dirty=True)

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["upstream"] is False
    assert any("working_tree_dirty" in err for err in result["errors"])

    rc = main(["--dataset-dir", str(dataset_dir)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_video_sha256_mismatch_fails(tmp_path: Path) -> None:
    dataset_dir = _build_synthetic_dataset(tmp_path)
    # 保持字节数一致，仅修改内容以触发 SHA-256 不匹配
    target_video = dataset_dir / "videos" / "sample_01.mp4"
    original = target_video.read_bytes()
    tampered = bytes([original[0] ^ 0xFF]) + original[1:]
    assert len(tampered) == len(original)
    target_video.write_bytes(tampered)

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["videos"] is False
    assert any("SHA-256 不匹配" in err and "sample_01.mp4" in err for err in result["errors"])


def test_labels_sha256_mismatch_fails(tmp_path: Path) -> None:
    dataset_dir = _build_synthetic_dataset(tmp_path)
    manifest_path = dataset_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["labels"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["labels"] is False
    assert any("labels.csv SHA-256 不匹配" in err for err in result["errors"])


def test_symlink_video_fails(tmp_path: Path) -> None:
    dataset_dir = _build_synthetic_dataset(tmp_path)
    target_video = dataset_dir / "videos" / "sample_01.mp4"
    external_file = tmp_path / "external_real.mp4"
    external_file.write_bytes(target_video.read_bytes())
    target_video.unlink()
    target_video.symlink_to(external_file)

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["videos"] is False
    assert any("软链接" in err and "sample_01.mp4" in err for err in result["errors"])


def test_extra_mp4_in_videos_dir_fails(tmp_path: Path) -> None:
    dataset_dir = _build_synthetic_dataset(tmp_path)
    extra_video = dataset_dir / "videos" / "untracked_extra.mp4"
    extra_video.write_bytes(b"extra-video-content")

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["videos"] is False
    assert any("多余 .mp4" in err and "untracked_extra.mp4" in err for err in result["errors"])


def test_missing_required_label_column_fails(tmp_path: Path) -> None:
    truncated_columns = [col for col in REQUIRED_LABEL_COLUMNS if col != "现象_断后脱夹"]
    dataset_dir = _build_synthetic_dataset(tmp_path, columns=truncated_columns)

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["labels"] is False
    assert any("缺少必需列头" in err and "现象_断后脱夹" in err for err in result["errors"])


def test_invalid_git_head_and_schema_fail(tmp_path: Path) -> None:
    dataset_dir = _build_synthetic_dataset(
        tmp_path,
        git_head="not-a-40-char-sha",
        upstream_manifest_sha256="short",
        manifest_overrides={"schema": "tensile-virtual-dataset/999", "source_domain": "real"},
    )

    result = check_dataset(dataset_dir)
    assert result["ok"] is False
    assert result["checks"]["manifest"] is False
    assert result["checks"]["upstream"] is False
    assert any("schema" in err for err in result["errors"])
    assert any("source_domain" in err for err in result["errors"])
    assert any("git_head" in err for err in result["errors"])
    assert any("manifest_sha256" in err for err in result["errors"])
