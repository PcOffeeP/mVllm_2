from __future__ import annotations

from pipeline.scripts.apply_tail_review_decisions import _filter_subvideos
from pipeline.scripts.audit_tail_contamination import audit_subvideo
from pipeline.scripts.prune_missing_review_media import _filter_subvideos as _filter_missing_media


def test_audit_tail_contamination_flags_tail_positive() -> None:
    sub = {
        "subvideo_id": "video_0001_full",
        "source_video": "video_0001",
        "crop_type": "full_pos",
        "has_fracture_canonical": True,
        "start_frame": 0,
        "end_frame": 99,
        "fracture_between": [6, 7],
        "actual_frame_mapping": [
            {"input_index": i, "original_frame": i * 14}
            for i in range(8)
        ],
    }

    finding = audit_subvideo(
        sub,
        tail_slots=2,
    )

    assert finding is not None
    assert finding["decision"] == "review"
    assert "fracture_between_at_tail" in finding["risk_reasons"]
    assert "full_video_positive" in finding["risk_reasons"]


def test_filter_subvideos_only_drops_explicit_decisions() -> None:
    subvideos = [
        {"subvideo_id": "a", "source_video": "video_0001"},
        {"subvideo_id": "b", "source_video": "video_0001"},
        {"subvideo_id": "c", "source_video": "video_0002"},
    ]

    kept, removed = _filter_subvideos(
        subvideos,
        drop_subvideos={"a"},
        drop_sources={"video_0002"},
    )

    assert [sub["subvideo_id"] for sub in kept] == ["b"]
    assert [item["subvideo_id"] for item in removed] == ["a", "c"]
    assert [item["reason"] for item in removed] == [
        "tail_review_drop_subvideo",
        "tail_review_drop_source",
    ]


def test_prune_missing_review_media_drops_missing_frame(tmp_path, monkeypatch) -> None:
    from pipeline.scripts import prune_missing_review_media

    monkeypatch.setattr(prune_missing_review_media, "PROJECT_ROOT", tmp_path)
    existing_frame = tmp_path / "data" / "04_frames" / "ok" / "frame_0000.jpg"
    existing_frame.parent.mkdir(parents=True)
    existing_frame.write_bytes(b"jpg")

    kept, removed = _filter_missing_media(
        [
            {
                "subvideo_id": "ok",
                "source_video": "video_0001",
                "video_path": "data/01_videos/video_0001.mp4",
                "frame_paths": ["04_frames/ok/frame_0000.jpg"],
            },
            {
                "subvideo_id": "bad",
                "source_video": "video_0002",
                "video_path": "data/01_videos/video_0002.mp4",
                "frame_paths": ["04_frames/bad/frame_0000.jpg"],
            },
        ],
        require_frames=True,
    )

    assert [sub["subvideo_id"] for sub in kept] == ["ok"]
    assert removed == [
        {
            "subvideo_id": "bad",
            "source_video": "video_0002",
            "reason": "missing_review_media",
            "details": ["missing_frame_file"],
        }
    ]
