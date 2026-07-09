from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline.scripts import prune_reviewed_subvideos as prune


def _write_meta(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _frame_dir(tmp_path: Path) -> Path:
    return tmp_path / "data" / "04_frames"


def _make_sub(sid: str, status: str) -> dict:
    return {
        "subvideo_id": sid,
        "source_video": f"video_{sid}",
        "video_path": f"data/03_subvideos/{sid}.mp4",
        "review_status": status,
    }


def test_prune_keeps_approved_and_drops_others_non_strict(tmp_path: Path):
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    subs = [
        _make_sub("sub1", "approved"),
        _make_sub("sub2", "dropped"),
        _make_sub("sub3", "needs_regenerate"),
        _make_sub("sub4", "unreviewed"),
    ]
    _write_meta(meta, {"subvideos": subs})

    kept, dropped, blocked = prune.prune_reviewed_subvideos(
        meta, output, report, frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path, strict=False
    )

    assert len(kept) == 1 and kept[0]["subvideo_id"] == "sub1"
    assert len(dropped) == 1
    assert len(blocked) == 2
    assert output.exists()
    pruned = json.loads(output.read_text(encoding="utf-8"))
    assert [s["subvideo_id"] for s in pruned["subvideos"]] == ["sub1"]


def test_prune_strict_blocks_without_output(tmp_path: Path):
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    _write_meta(meta, {"subvideos": [_make_sub("sub1", "approved"), _make_sub("sub2", "unreviewed")]})

    kept, dropped, blocked = prune.prune_reviewed_subvideos(
        meta, output, report, frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path, strict=True
    )

    assert len(kept) == 1
    assert len(blocked) == 1
    assert not output.exists()
    assert report.exists()


def test_prune_legacy_media_fallback(tmp_path: Path):
    meta = tmp_path / "subvideos_meta.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sub1",
                    "source_video": "video_sub1",
                    "video_path": "data/03_subvideos/sub1.mp4",
                }
            ]
        },
    )
    (tmp_path / "data" / "03_subvideos").mkdir(parents=True)
    (tmp_path / "data" / "03_subvideos" / "sub1.mp4").write_text("x", encoding="utf-8")
    (tmp_path / "data" / "04_frames" / "sub1").mkdir(parents=True)
    (tmp_path / "data" / "04_frames" / "sub1" / "f.jpg").write_text("x", encoding="utf-8")

    kept, dropped, blocked = prune.prune_reviewed_subvideos(
        meta, output, report, frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path
    )

    assert len(kept) == 1
    assert len(blocked) == 0


def test_prune_cli_returns_nonzero_on_blocked(tmp_path: Path, monkeypatch):
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    _write_meta(meta, {"subvideos": [_make_sub("sub1", "approved"), _make_sub("sub2", "needs_regenerate")]})

    monkeypatch.setattr(
        sys, "argv",
        [
            "prune_reviewed_subvideos.py",
            "--subvideos-meta", str(meta),
            "--output-meta", str(output),
            "--report", str(report),
            "--frame-dir", str(_frame_dir(tmp_path)),
            "--project-root", str(tmp_path),
        ],
    )
    rc = prune.main()
    assert rc != 0


def test_prune_delete_media_removes_dropped_files(tmp_path: Path):
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sub1",
                    "source_video": "video_sub1",
                    "video_path": "data/03_subvideos/sub1.mp4",
                    "review_status": "dropped",
                }
            ]
        },
    )
    video = tmp_path / "data" / "03_subvideos" / "sub1.mp4"
    frame_dir = tmp_path / "data" / "04_frames" / "sub1"
    video.parent.mkdir(parents=True)
    video.write_text("x", encoding="utf-8")
    frame_dir.mkdir(parents=True)
    (frame_dir / "f.jpg").write_text("x", encoding="utf-8")

    kept, dropped, blocked = prune.prune_reviewed_subvideos(
        meta,
        output,
        report,
        frame_dir_root=frame_dir.parent,
        project_root=tmp_path,
        delete_media=True,
        strict=False,
    )

    assert len(dropped) == 1
    assert not video.exists()
    assert not frame_dir.exists()


def test_prune_strict_blocked_does_not_delete_media(tmp_path: Path):
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sub1",
                    "source_video": "video_sub1",
                    "video_path": "data/03_subvideos/sub1.mp4",
                    "review_status": "dropped",
                },
                {
                    "subvideo_id": "sub2",
                    "source_video": "video_sub2",
                    "video_path": "data/03_subvideos/sub2.mp4",
                    "review_status": "unreviewed",
                },
            ]
        },
    )
    video = tmp_path / "data" / "03_subvideos" / "sub1.mp4"
    video.parent.mkdir(parents=True)
    video.write_text("x", encoding="utf-8")

    kept, dropped, blocked = prune.prune_reviewed_subvideos(
        meta,
        output,
        report,
        frame_dir_root=_frame_dir(tmp_path),
        project_root=tmp_path,
        delete_media=True,
        strict=True,
    )

    assert len(blocked) == 1
    assert video.exists(), "strict 阻塞时不应删除媒体"


def test_prune_cli_returns_zero_on_clean(tmp_path: Path, monkeypatch):
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    output = tmp_path / "subvideos_meta.pruned.json"
    report = tmp_path / "report.json"
    _write_meta(meta, {"subvideos": [_make_sub("sub1", "approved")]})

    monkeypatch.setattr(
        sys, "argv",
        [
            "prune_reviewed_subvideos.py",
            "--subvideos-meta", str(meta),
            "--output-meta", str(output),
            "--report", str(report),
            "--frame-dir", str(_frame_dir(tmp_path)),
            "--project-root", str(tmp_path),
        ],
    )
    rc = prune.main()
    assert rc == 0
    assert output.exists()
