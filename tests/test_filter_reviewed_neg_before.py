from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from pipeline.scripts.filter_reviewed_neg_before import (
    _find_brittle_missing_source_video,
    filter_subvideos,
    main,
)


def _neg_before(
    subvideo_id: str,
    source_video: str | None = "video_0001",
    source_type: str = "脆性断裂",
    start: float = 0.0,
    end: float = 10.0,
    review_status: str = "approved",
    crop_type: str = "neg_before",
) -> dict:
    return {
        "subvideo_id": subvideo_id,
        "source_video": source_video,
        "source_type": source_type,
        "crop_type": crop_type,
        "review_status": review_status,
        "start_time": start,
        "end_time": end,
    }


def _run_main(argv: list[str]) -> int:
    with patch.object(sys, "argv", ["filter_reviewed_neg_before.py"] + argv):
        return main()


def test_filter_brittle_keeps_only_closest_to_event() -> None:
    subs = [
        _neg_before("a", end=50.0),
        _neg_before("b", end=99.0),
        _neg_before("c", end=80.0),
    ]
    kept, dropped = filter_subvideos(subs)
    assert [s["subvideo_id"] for s in kept] == ["b"]
    assert [s["subvideo_id"] for s in dropped] == ["a", "c"]


def test_filter_ductile_keeps_all() -> None:
    subs = [
        _neg_before("a", source_type="韧性断裂", end=50.0),
        _neg_before("b", source_type="韧性断裂", end=99.0),
    ]
    kept, dropped = filter_subvideos(subs)
    assert [s["subvideo_id"] for s in kept] == ["a", "b"]
    assert dropped == []


def test_filter_semi_brittle_keeps_all() -> None:
    subs = [
        _neg_before("a", source_type="半脆半韧断裂", end=50.0),
        _neg_before("b", source_type="半脆半韧断裂", end=99.0),
    ]
    kept, dropped = filter_subvideos(subs)
    assert [s["subvideo_id"] for s in kept] == ["a", "b"]
    assert dropped == []


def test_filter_brittle_compound_type_dedup() -> None:
    subs = [
        _neg_before("a", source_type="脆性断裂、齐根断裂", end=50.0),
        _neg_before("b", source_type="脆性断裂、齐根断裂", end=99.0),
    ]
    kept, dropped = filter_subvideos(subs)
    assert [s["subvideo_id"] for s in kept] == ["b"]
    assert [s["subvideo_id"] for s in dropped] == ["a"]


def test_filter_non_neg_before_or_non_approved_untouched() -> None:
    subs = [
        _neg_before("dropped_review", review_status="dropped", end=50.0),
        _neg_before("focus_clip", crop_type="focus_3s", end=60.0),
        _neg_before("other_video", source_video="video_0002", end=70.0),
        _neg_before("winner", end=99.0),
        _neg_before("loser", end=10.0),
    ]
    kept, dropped = filter_subvideos(subs)
    assert [s["subvideo_id"] for s in kept] == [
        "dropped_review",
        "focus_clip",
        "other_video",
        "winner",
    ]
    assert [s["subvideo_id"] for s in dropped] == ["loser"]


def test_find_brittle_missing_source_video() -> None:
    missing_key = _neg_before("missing_key")
    del missing_key["source_video"]
    subs = [
        _neg_before("ok"),
        missing_key,
        _neg_before("empty", source_video=""),
        _neg_before("ductile_empty", source_type="韧性断裂", source_video=""),
        _neg_before("dropped_empty", review_status="dropped", source_video=""),
    ]
    missing = _find_brittle_missing_source_video(subs)
    assert [s["subvideo_id"] for s in missing] == ["missing_key", "empty"]


def test_main_fails_when_brittle_source_video_missing(tmp_path: Path) -> None:
    input_meta = tmp_path / "input.json"
    output_meta = tmp_path / "output.json"
    report = tmp_path / "report.json"
    bad = _neg_before("bad_one")
    del bad["source_video"]
    input_meta.write_text(
        json.dumps({"subvideos": [_neg_before("ok", end=99.0), bad]}),
        encoding="utf-8",
    )

    rc = _run_main([
        "--input-meta", str(input_meta),
        "--output-meta", str(output_meta),
        "--output-report", str(report),
    ])

    assert rc == 2
    assert not output_meta.exists()
    assert not report.exists()


def test_main_writes_filtered_output(tmp_path: Path) -> None:
    input_meta = tmp_path / "input.json"
    output_meta = tmp_path / "output.json"
    input_meta.write_text(
        json.dumps({
            "other_field": 1,
            "subvideos": [
                _neg_before("a", end=50.0),
                _neg_before("b", end=99.0),
                _neg_before("ductile", source_type="韧性断裂", end=10.0),
            ],
        }),
        encoding="utf-8",
    )

    rc = _run_main(["--input-meta", str(input_meta), "--output-meta", str(output_meta)])

    assert rc == 0
    assert output_meta.exists()
    out = json.loads(output_meta.read_text(encoding="utf-8"))
    assert [s["subvideo_id"] for s in out["subvideos"]] == ["b", "ductile"]
    assert out["other_field"] == 1
