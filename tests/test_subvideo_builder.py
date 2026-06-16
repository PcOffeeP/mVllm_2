from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.scripts import subvideo_builder as builder


def _frames(*originals: int) -> list[dict]:
    return [
        {"input_index": i, "original_frame": f, "timestamp": float(i)}
        for i, f in enumerate(originals)
    ]


def test_compute_fracture_between_exact_hit_middle_returns_left_interval():
    sampled = _frames(10, 20, 30, 40, 50)
    assert builder.compute_fracture_between(sampled, 30) == [1, 2]


def test_compute_fracture_between_exact_hit_first_returns_sentinel():
    sampled = _frames(30, 40, 50)
    assert builder.compute_fracture_between(sampled, 30) == [0, 0]


def test_compute_fracture_between_exact_hit_last_prefers_right_sentinel():
    """命中最后一帧时，按越界末段规则取 [N-1, N-1]。"""
    sampled = _frames(10, 20, 30)
    assert builder.compute_fracture_between(sampled, 30) == [2, 2]


def test_compute_fracture_between_normal_interval():
    sampled = _frames(10, 20, 30, 40)
    assert builder.compute_fracture_between(sampled, 25) == [1, 2]


def test_compute_fracture_between_left_out_of_bounds():
    sampled = _frames(20, 30, 40)
    assert builder.compute_fracture_between(sampled, 5) == [0, 0]


def test_compute_fracture_between_right_out_of_bounds():
    sampled = _frames(10, 20, 30)
    assert builder.compute_fracture_between(sampled, 100) == [2, 2]


def test_compute_fracture_between_none_event_frame():
    assert builder.compute_fracture_between(_frames(10, 20), None) is None


def test_compute_fracture_between_empty_frames():
    assert builder.compute_fracture_between([], 10) is None


def test_parse_fps_rejects_nan_and_inf():
    assert builder._parse_fps("nan") is None
    assert builder._parse_fps("NaN") is None
    assert builder._parse_fps("inf") is None
    assert builder._parse_fps("Infinity") is None
    assert builder._parse_fps("-inf") is None
    assert builder._parse_fps("-Infinity") is None
    assert builder._parse_fps("30/1") == 30.0
    assert builder._parse_fps("30000/1001") == 30000.0 / 1001.0
    assert builder._parse_fps("29.97") == 29.97


def test_subvideo_builder_write_json_rejects_nan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    video_meta = tmp_path / "video_meta.json"
    splits_dir = tmp_path / "splits"
    subvideo_dir = tmp_path / "subvideos"
    frame_dir = tmp_path / "frames"
    output_meta = tmp_path / "subvideos_meta.json"
    splits_dir.mkdir(parents=True, exist_ok=True)

    records = [
        {
            "video_id": "v001",
            "video_path": "data/01_videos/v001.mp4",
            "fps": 30.0,
            "total_frames": 300,
            "duration": 10.0,
            "has_fracture": False,
            "is_abnormal": False,
            "type": "未断裂",
            "location": "N/A",
            "event_frame_original": None,
        }
    ]
    video_meta.write_text(json.dumps(records), encoding="utf-8")
    (splits_dir / "test.json").write_text(
        json.dumps({"split": "test", "video_ids": ["v001"]}), encoding="utf-8"
    )

    monkeypatch.setattr(
        builder,
        "build_subvideos_for_record",
        lambda rec, split_info: [{"subvideo_id": "v001_full", "bad_value": float("nan")}],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "subvideo_builder",
            "--video-meta",
            str(video_meta),
            "--splits-dir",
            str(splits_dir),
            "--subvideo-dir",
            str(subvideo_dir),
            "--frame-dir",
            str(frame_dir),
            "--output-meta",
            str(output_meta),
        ],
    )

    with pytest.raises(ValueError):
        builder.main()


def test_load_splits_only_reads_new_interval_files(tmp_path: Path):
    # 旧基线文件应被忽略
    (tmp_path / "stratified_3_fold_0.json").write_text(
        '{"video_ids": ["old_001"]}', encoding="utf-8"
    )
    (tmp_path / "fold_0_train.json").write_text(
        '{"split": "train", "video_ids": ["v001", "v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_0_val.json").write_text(
        '{"split": "val", "video_ids": ["v003"]}', encoding="utf-8"
    )
    (tmp_path / "test.json").write_text(
        '{"split": "test", "video_ids": ["v004"]}', encoding="utf-8"
    )

    mapping = builder.load_splits(tmp_path)
    assert "old_001" not in mapping
    assert mapping["v001"]["split"] == "train"
    assert mapping["v003"]["split"] == "val"
    assert mapping["v004"]["split"] == "test"
    assert "fold_assignments" in mapping["v001"]


def test_load_splits_fold_assignments_are_complete(tmp_path: Path):
    # v001 同时出现在 fold_0_train、fold_1_train、fold_1_val
    (tmp_path / "fold_0_train.json").write_text(
        '{"split": "train", "video_ids": ["v001"]}', encoding="utf-8"
    )
    (tmp_path / "fold_0_val.json").write_text(
        '{"split": "val", "video_ids": ["v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_1_train.json").write_text(
        '{"split": "train", "video_ids": ["v001", "v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_1_val.json").write_text(
        '{"split": "val", "video_ids": ["v001"]}', encoding="utf-8"
    )
    (tmp_path / "fold_2_train.json").write_text(
        '{"split": "train", "video_ids": ["v001", "v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_2_val.json").write_text(
        '{"split": "val", "video_ids": ["v002"]}', encoding="utf-8"
    )

    mapping = builder.load_splits(tmp_path)
    assert set(mapping["v001"]["fold_assignments"]) == {
        "fold_0_train",
        "fold_1_train",
        "fold_1_val",
        "fold_2_train",
    }
    # 存在 val 时，primary 选择 val
    assert mapping["v001"]["split"] == "val"


def test_build_subvideos_for_record_generates_all_classes_for_fracture(
    monkeypatch: pytest.MonkeyPatch,
):
    rec = {
        "video_id": "video_0001",
        "has_fracture": True,
        "is_abnormal": False,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "event_frame_original": 100,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": []}

    monkeypatch.setattr(
        builder,
        "build_full_subvideo",
        lambda r, s: {
            "subvideo_id": f"{r['video_id']}_full",
            "source_video": r["video_id"],
            "video_path": f"02_subvideos/{r['video_id']}_full.mp4",
            "frame_paths": [],
            "start_time": 0.0,
            "end_time": r["duration"],
            "duration": r["duration"],
            "crop_type": "full_pos",
            "event_position_ratio": None,
            "has_fracture": True,
            "is_abnormal": False,
            "fracture_between": [0, 1],
            "type": r["type"],
            "location": r["location"],
            "source_type": r["type"],
            "source_location": r["location"],
            "fold": s.get("fold"),
            "split": s.get("split"),
            "fold_assignments": s.get("fold_assignments", []),
        },
    )
    monkeypatch.setattr(
        builder, "build_focus_subvideos", lambda r, s: [{"crop_type": "focus"}] * 3
    )
    monkeypatch.setattr(
        builder, "build_neg_before_after", lambda r, s: [{"crop_type": "neg"}] * 2
    )

    result = builder.build_subvideos_for_record(rec, split_info)
    crop_types = [r["crop_type"] for r in result]
    assert crop_types.count("full_pos") == 1
    assert crop_types.count("focus") == 3
    assert crop_types.count("neg") == 2


def test_build_subvideos_for_record_abnormal_only_full(
    monkeypatch: pytest.MonkeyPatch,
):
    rec = {
        "video_id": "video_0045",
        "has_fracture": True,
        "is_abnormal": True,
        "type": "视频异常",
        "location": "N/A",
        "event_frame_original": 100,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
    }
    split_info = {"split": "test", "fold": "test", "fold_assignments": []}

    monkeypatch.setattr(
        builder,
        "build_full_subvideo",
        lambda r, s: {
            "subvideo_id": f"{r['video_id']}_full",
            "source_video": r["video_id"],
            "video_path": f"02_subvideos/{r['video_id']}_full.mp4",
            "frame_paths": [],
            "start_time": 0.0,
            "end_time": r["duration"],
            "duration": r["duration"],
            "crop_type": "full",
            "event_position_ratio": None,
            "has_fracture": False,
            "is_abnormal": True,
            "fracture_between": None,
            "type": r["type"],
            "location": r["location"],
            "source_type": r["type"],
            "source_location": r["location"],
            "fold": s.get("fold"),
            "split": s.get("split"),
            "fold_assignments": s.get("fold_assignments", []),
        },
    )
    monkeypatch.setattr(builder, "build_focus_subvideos", lambda r, s: [])
    monkeypatch.setattr(builder, "build_neg_before_after", lambda r, s: [])

    result = builder.build_subvideos_for_record(rec, split_info)
    assert len(result) == 1
    assert result[0]["crop_type"] == "full"


def test_build_subvideos_for_record_non_fracture_only_full(
    monkeypatch: pytest.MonkeyPatch,
):
    rec = {
        "video_id": "video_0099",
        "has_fracture": False,
        "is_abnormal": False,
        "type": "未断裂",
        "location": "N/A",
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": []}

    monkeypatch.setattr(
        builder,
        "build_full_subvideo",
        lambda r, s: {
            "subvideo_id": f"{r['video_id']}_full",
            "source_video": r["video_id"],
            "video_path": f"02_subvideos/{r['video_id']}_full.mp4",
            "frame_paths": [],
            "start_time": 0.0,
            "end_time": r["duration"],
            "duration": r["duration"],
            "crop_type": "full_neg",
            "event_position_ratio": None,
            "has_fracture": False,
            "is_abnormal": False,
            "fracture_between": None,
            "type": r["type"],
            "location": r["location"],
            "source_type": r["type"],
            "source_location": r["location"],
            "fold": s.get("fold"),
            "split": s.get("split"),
            "fold_assignments": s.get("fold_assignments", []),
        },
    )
    monkeypatch.setattr(builder, "build_focus_subvideos", lambda r, s: [])
    monkeypatch.setattr(builder, "build_neg_before_after", lambda r, s: [])

    result = builder.build_subvideos_for_record(rec, split_info)
    assert len(result) == 1
    assert result[0]["crop_type"] == "full_neg"


def test_build_full_subvideo_preserves_original_and_outputs_canonical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """冲突视频的 full 子视频应保留原始标签，同时输出 canonical 字段。"""
    rec = {
        "video_id": "video_conflict",
        "has_fracture": True,
        "has_fracture_canonical": False,
        "is_abnormal": True,
        "type": "视频异常",
        "location": "inside_gauge",
        "location_canonical": "N/A",
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
        "video_path": str(tmp_path / "video_conflict.mp4"),
    }
    (tmp_path / "video_conflict.mp4").write_text("fake")
    split_info = {"split": "test", "fold": "test", "fold_assignments": []}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)
    monkeypatch.setattr(
        builder, "extract_sampled_frames", lambda path, out_dir, n, duration: []
    )

    sub = builder.build_full_subvideo(rec, split_info)
    assert sub is not None
    assert sub["has_fracture"] is False
    assert sub["has_fracture_canonical"] is False
    assert sub["type"] == "视频异常"
    assert sub["location"] == "N/A"
    assert sub["location_canonical"] == "N/A"
    assert sub["source_type"] == "视频异常"
    assert sub["source_location"] == "inside_gauge"
    assert sub["crop_type"] == "full_neg"


# ---------------------------------------------------------------------------
# start_frame / end_frame 一致性校验
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (ROOT / "data" / "metadata" / "subvideos_meta.json").exists(),
    reason="需要先生成 data/metadata/subvideos_meta.json 产物",
)
def test_subvideos_meta_has_start_end_frames():
    meta_path = ROOT / "data" / "metadata" / "subvideos_meta.json"
    subs = json.loads(meta_path.read_text(encoding="utf-8"))
    assert subs
    for sub in subs:
        assert "start_frame" in sub, sub["subvideo_id"]
        assert "end_frame" in sub, sub["subvideo_id"]
        sf = sub["start_frame"]
        ef = sub["end_frame"]
        assert isinstance(sf, int), sub["subvideo_id"]
        assert isinstance(ef, int), sub["subvideo_id"]
        assert 0 <= sf < ef, sub["subvideo_id"]


@pytest.mark.skipif(
    not (ROOT / "data" / "metadata" / "subvideos_meta.json").exists(),
    reason="需要先生成 data/metadata/subvideos_meta.json 产物",
)
def test_subvideos_meta_positive_fracture_between_in_bounds_and_adjacent():
    """正样本的 fracture_between 必须是正常相邻区间 [i, i+1] 或边界哨兵 [0,0] / [N-1,N-1]。"""
    meta_path = ROOT / "data" / "metadata" / "subvideos_meta.json"
    subs = json.loads(meta_path.read_text(encoding="utf-8"))
    for sub in subs:
        if not sub.get("has_fracture"):
            continue
        fb = sub.get("fracture_between")
        assert fb is not None, sub["subvideo_id"]
        assert len(fb) == 2, sub["subvideo_id"]
        n = len(sub.get("frame_paths") or [])
        assert 0 <= fb[0] < n, sub["subvideo_id"]
        assert 0 <= fb[1] < n, sub["subvideo_id"]
        if fb[0] == fb[1]:
            assert fb == [0, 0] or fb == [n - 1, n - 1], sub["subvideo_id"]
        else:
            assert fb[1] == fb[0] + 1, sub["subvideo_id"]


@pytest.mark.skipif(
    not (ROOT / "data" / "metadata" / "subvideos_meta.json").exists()
    or not (ROOT / "data" / "metadata" / "video_meta.json").exists(),
    reason="需要先生成 data/metadata/subvideos_meta.json 与 video_meta.json 产物",
)
def test_subvideos_meta_frame_bounds_consistent_with_time():
    meta_path = ROOT / "data" / "metadata" / "subvideos_meta.json"
    video_meta_path = ROOT / "data" / "metadata" / "video_meta.json"
    subs = json.loads(meta_path.read_text(encoding="utf-8"))
    video_meta = {
        v["video_id"]: v
        for v in json.loads(video_meta_path.read_text(encoding="utf-8"))
    }
    for sub in subs:
        rec = video_meta[sub["source_video"]]
        fps = rec["fps"]
        total_frames = rec["total_frames"]
        sf = sub["start_frame"]
        ef = sub["end_frame"]
        assert 0 <= sf <= ef < total_frames, sub["subvideo_id"]
        assert abs(sub["start_time"] - sf / fps) < 0.5 / fps, sub["subvideo_id"]
        assert abs(sub["end_time"] - ef / fps) < 0.5 / fps, sub["subvideo_id"]


@pytest.mark.skipif(
    not (ROOT / "data" / "metadata" / "subvideos_meta.json").exists()
    or not (ROOT / "data" / "metadata" / "video_meta.json").exists(),
    reason="需要先生成 data/metadata/subvideos_meta.json 与 video_meta.json 产物",
)
def test_subvideos_meta_fracture_between_recalculation_consistent():
    """用 start_frame/end_frame 对应的时间区间反算 fracture_between，验证无 ±1 帧偏差。"""
    meta_path = ROOT / "data" / "metadata" / "subvideos_meta.json"
    video_meta_path = ROOT / "data" / "metadata" / "video_meta.json"
    subs = json.loads(meta_path.read_text(encoding="utf-8"))
    video_meta = {
        v["video_id"]: v
        for v in json.loads(video_meta_path.read_text(encoding="utf-8"))
    }
    mismatches = []
    for sub in subs:
        if not sub.get("has_fracture"):
            continue
        rec = video_meta[sub["source_video"]]
        fps = rec["fps"]
        total_frames = rec["total_frames"]
        event_frame = rec["event_frame_original"]
        if event_frame is None:
            continue
        # 以实际 frame_paths 数量作为采样帧数反算，确保与元数据一致
        n_actual = len(sub.get("frame_paths") or [])
        sampled = builder.compute_sampled_frames_with_n(
            sub["start_time"],
            sub["end_time"],
            fps,
            total_frames,
            n_actual,
        )
        recomputed = builder.compute_fracture_between(sampled, event_frame)
        if recomputed != sub["fracture_between"]:
            mismatches.append(
                (
                    sub["subvideo_id"],
                    sub["fracture_between"],
                    recomputed,
                    event_frame,
                    [f["original_frame"] for f in sampled],
                )
            )
    assert not mismatches, f"fracture_between 反算不一致: {mismatches[:5]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
