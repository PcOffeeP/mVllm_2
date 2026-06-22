from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.scripts import training_sample_builder as builder


def _subvideo(video_id: str = "video_0001", has_fracture: bool = True) -> dict:
    """构造一条最小子视频元数据。"""
    return {
        "subvideo_id": f"{video_id}_focus_3s_50pct",
        "source_video": video_id,
        "video_path": f"02_subvideos/{video_id}_focus_3s_50pct.mp4",
        "frame_paths": [f"03_frames/{video_id}_focus_3s_50pct/frame_{i:04d}.jpg" for i in range(24)],
        "start_time": 143.9,
        "end_time": 146.9,
        "start_frame": 4317,
        "end_frame": 4324,
        "duration": 3.0,
        "crop_type": "focus_3s",
        "event_position_ratio": 0.5,
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "fracture_between": [17, 18] if has_fracture else None,
        "type": "韧性断裂" if has_fracture else "未断裂",
        "location": "inside_gauge" if has_fracture else "N/A",
        "location_canonical": "inside_gauge" if has_fracture else "N/A",
        "source_type": "韧性断裂",
        "source_location": "inside_gauge",
        "fold": "fold_0_train",
        "split": "fold_0_train",
    }


def _write_subvideos_meta(path: Path, subvideos: list[dict]) -> None:
    """将子视频元数据写入临时 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(subvideos, ensure_ascii=False), encoding="utf-8")


def _write_splits(splits_dir: Path, mapping: dict[str, list[str]]) -> None:
    """按 split 名称写入临时划分文件。"""
    splits_dir.mkdir(parents=True, exist_ok=True)
    for name, video_ids in mapping.items():
        (splits_dir / f"{name}.json").write_text(
            json.dumps({"video_ids": video_ids}, ensure_ascii=False),
            encoding="utf-8",
        )


def test_convert_subvideo_to_sample_sharegpt_format():
    sub = _subvideo(has_fracture=True)
    sample = builder.convert_subvideo_to_sample(sub, video_fps=8.0, video_maxlen=36)

    assert sample["id"] == sub["subvideo_id"]
    assert sample["videos"] == [sub["video_path"]]
    assert len(sample["messages"]) == 3

    roles = [m["role"] for m in sample["messages"]]
    assert roles == ["system", "user", "assistant"]

    system_msg = sample["messages"][0]
    assert "材料拉伸试验视频分析助手" in system_msg["content"]

    user_msg = sample["messages"][1]
    assert "<video>" in user_msg["content"]
    assert "[143.9, 146.9]" in user_msg["content"]

    assistant_text = sample["messages"][2]["content"]
    assistant = json.loads(assistant_text)
    assert assistant["has_fracture"] is True
    assert assistant["fracture_between"] == [17, 18]
    assert assistant["type"] == "韧性断裂"
    assert assistant["location"] == "inside_gauge"
    assert assistant["confidence"] == pytest.approx(1.0)

    assert sample["has_fracture"] is True
    assert sample["fracture_between"] == [17, 18]
    assert sample["source_type"] == "韧性断裂"
    assert sample["source_location"] == "inside_gauge"
    assert sample["start_frame"] == sub["start_frame"]
    assert sample["end_frame"] == sub["end_frame"]


def test_convert_negative_sample_has_null_fracture_between():
    sub = _subvideo(has_fracture=False)
    sample = builder.convert_subvideo_to_sample(sub, video_fps=8.0, video_maxlen=36)

    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is False
    assert assistant["fracture_between"] is None
    assert assistant["type"] == "未断裂"
    assert assistant["location"] is None
    assert sample["fracture_between"] is None


def test_compute_effective_frames_prefers_frame_paths():
    sub = _subvideo()
    assert builder.compute_effective_frames(sub, 8.0, 36) == len(sub["frame_paths"])


def test_build_split_samples_groups_by_source_video():
    sub1 = _subvideo("video_0001", has_fracture=True)
    sub2 = _subvideo("video_0002", has_fracture=False)
    split_ids = {
        "fold_0_train": {"video_0001"},
        "fold_0_val": {"video_0002"},
    }
    split_samples = builder.build_split_samples(
        [sub1, sub2], split_ids, video_fps=8.0, video_maxlen=36
    )
    assert len(split_samples["fold_0_train"]) == 1
    assert len(split_samples["fold_0_val"]) == 1
    assert split_samples["fold_0_train"][0]["source_video"] == "video_0001"


def test_build_all_outputs_valid_json_and_samples_meta(tmp_path):
    """build_all 在临时目录生成合法 JSON 与样本统计信息。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    sub1 = _subvideo("video_0001", has_fracture=True)
    sub2 = _subvideo("video_0002", has_fracture=False)
    _write_subvideos_meta(sub_meta, [sub1, sub2])
    _write_splits(
        splits_dir,
        {
            "fold_0_train": ["video_0001"],
            "fold_0_val": ["video_0002"],
        },
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_fps=8.0,
        video_maxlen=36,
    )

    for name in builder.SPLIT_NAMES:
        if name == "test":
            continue
        path = out_dir / f"{name}.json"
        assert path.exists(), f"{path} 不存在"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        if data:
            first = data[0]
            assert "id" in first
            assert "videos" in first
            assert "messages" in first
            assert any(m["role"] == "system" for m in first["messages"])
            assert any(m["role"] == "user" for m in first["messages"])
            assert any(m["role"] == "assistant" for m in first["messages"])

    meta_path = out_dir / "samples_meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["total_samples"] > 0
    assert "splits" in meta
    assert all(name in meta["splits"] for name in builder.SPLIT_NAMES if name != "test")


def test_dataset_info_interval_keys_point_to_existing_files():
    dataset_info = json.loads(
        Path("finetune/dataset_info.json").read_text(encoding="utf-8")
    )
    finetune_dir = Path("finetune").resolve()

    interval_keys = [k for k in dataset_info if k.startswith("tensile_video_interval")]
    assert interval_keys, "未找到 tensile_video_interval 键"
    # 新方案只保留 6 个训练/验证数据集键，不再包含 test ShareGPT 键
    assert "tensile_video_interval_test" not in dataset_info

    missing: list[str] = []
    for key in interval_keys:
        entry = dataset_info[key]
        assert entry.get("formatting") == "sharegpt"
        assert entry["columns"].get("messages") == "messages"
        assert entry["columns"].get("videos") == "videos"
        assert "04_merged" in entry["file_name"]
        file_path = (finetune_dir / entry["file_name"]).resolve()
        if not file_path.exists():
            missing.append(str(file_path.relative_to(Path.cwd())))

    if missing:
        pytest.skip(
            f"需要先生成 data/04_merged 训练样本: {', '.join(missing)}"
        )


def test_build_all_outputs_contain_start_end_frames(tmp_path):
    """生成的训练样本顶层必须包含 start_frame / end_frame。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    sub = _subvideo("video_0001", has_fracture=True)
    _write_subvideos_meta(sub_meta, [sub])
    _write_splits(splits_dir, {"fold_0_train": ["video_0001"]})

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_fps=8.0,
        video_maxlen=36,
    )

    for name in builder.SPLIT_NAMES:
        if name == "test":
            continue
        path = out_dir / f"{name}.json"
        assert path.exists(), f"{path} 不存在"
        samples = json.loads(path.read_text(encoding="utf-8"))
        for sample in samples:
            assert "start_frame" in sample, sample["id"]
            assert "end_frame" in sample, sample["id"]
            assert isinstance(sample["start_frame"], int)
            assert isinstance(sample["end_frame"], int)


def test_main_with_custom_paths():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sub_meta = tmp_path / "subvideos_meta.json"
        splits_dir = tmp_path / "splits"
        out_dir = tmp_path / "out"
        splits_dir.mkdir()

        sub = _subvideo("video_0001", has_fracture=True)
        sub_meta.write_text(json.dumps([sub], ensure_ascii=False), encoding="utf-8")
        (splits_dir / "fold_0_train.json").write_text(
            json.dumps({"video_ids": ["video_0001"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        builder.build_all(
            subvideos_meta=sub_meta,
            splits_dir=splits_dir,
            output_dir=out_dir,
            video_fps=8.0,
            video_maxlen=36,
        )

        out_file = out_dir / "fold_0_train.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 1


# ---------------------------------------------------------------------------
# 异常/冲突样本处理断言
# ---------------------------------------------------------------------------

FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
}

CONFLICT_VIDEOS = {
    "video_0045",
    "video_0049",
    "video_0078",
    "video_0083",
    "video_0094",
    "video_0096",
    "video_0107",
}


def test_conflict_videos_samples_are_negative(tmp_path):
    """7 条冲突视频在生成的训练样本中必须被降级为负样本。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    conflict_subs = []
    for vid in CONFLICT_VIDEOS:
        sub = _subvideo(vid, has_fracture=True)
        sub["has_fracture_canonical"] = False
        sub["is_abnormal"] = True
        sub["type"] = "视频异常"
        sub["location"] = "N/A"
        sub["location_canonical"] = "N/A"
        sub["fracture_between"] = [10, 11]
        conflict_subs.append(sub)

    _write_subvideos_meta(sub_meta, conflict_subs)
    _write_splits(splits_dir, {"fold_0_train": sorted(CONFLICT_VIDEOS)})

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_fps=8.0,
        video_maxlen=36,
    )

    for name in builder.SPLIT_NAMES:
        path = out_dir / f"{name}.json"
        if not path.exists():
            continue
        samples = json.loads(path.read_text(encoding="utf-8"))
        for sample in samples:
            if sample.get("source_video") in CONFLICT_VIDEOS:
                assert sample["has_fracture"] is False, (
                    f"{sample['id']} 来源为冲突视频，has_fracture 必须为 False"
                )
                assert sample.get("has_fracture_canonical") is False
                assert sample.get("fracture_between") is None
                assert sample["type"] == "视频异常"
                assert sample["location"] is None
                assert sample.get("location_canonical") is None
                assistant = json.loads(sample["messages"][2]["content"])
                assert assistant["has_fracture"] is False
                assert assistant["fracture_between"] is None
                assert assistant["location"] is None


def test_no_positive_sample_with_non_fracture_type(tmp_path):
    """has_fracture=True 的样本 type 必须在 7 个断裂类中。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    positive = _subvideo("video_pos", has_fracture=True)
    positive["type"] = "韧性断裂"
    negative = _subvideo("video_neg", has_fracture=False)
    negative["type"] = "视频异常"
    negative["is_abnormal"] = True

    _write_subvideos_meta(sub_meta, [positive, negative])
    _write_splits(
        splits_dir,
        {
            "fold_0_train": ["video_pos"],
            "fold_0_val": ["video_neg"],
        },
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_fps=8.0,
        video_maxlen=36,
    )

    for name in builder.SPLIT_NAMES:
        path = out_dir / f"{name}.json"
        if not path.exists():
            continue
        samples = json.loads(path.read_text(encoding="utf-8"))
        for sample in samples:
            if sample["has_fracture"] is True:
                assert sample["type"] in FRACTURE_TYPES, (
                    f"{sample['id']} has_fracture=True 但 type={sample['type']}"
                )


def test_convert_subvideo_downgrades_inconsistent_positive():
    """子视频元数据中 has_fracture_canonical=False 时训练样本应被降级。"""
    sub = _subvideo("video_0045", has_fracture=True)
    sub["type"] = "视频异常"
    sub["location"] = "N/A"
    sub["location_canonical"] = "N/A"
    sub["fracture_between"] = [10, 11]
    sub["is_abnormal"] = True
    sub["has_fracture_canonical"] = False

    sample = builder.convert_subvideo_to_sample(sub, video_fps=8.0, video_maxlen=36)
    assert sample["has_fracture"] is False
    assert sample["has_fracture_canonical"] is False
    assert sample["fracture_between"] is None
    assert sample["location"] is None
    assert sample["location_canonical"] is None
    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is False
    assert assistant["location"] is None


def test_convert_subvideo_prefers_canonical_over_original():
    """当 has_fracture 与 has_fracture_canonical 不一致时，训练样本使用 canonical。"""
    sub = _subvideo("video_conflict", has_fracture=True)
    sub["has_fracture"] = True  # CSV 原始值
    sub["has_fracture_canonical"] = False  # 治理后值
    sub["location"] = "inside_gauge"  # CSV 原始值
    sub["location_canonical"] = "N/A"  # 治理后值
    sub["type"] = "视频异常"
    sub["is_abnormal"] = True
    sub["fracture_between"] = [10, 11]

    sample = builder.convert_subvideo_to_sample(sub, video_fps=8.0, video_maxlen=36)
    assert sample["has_fracture"] is False
    assert sample["has_fracture_canonical"] is False
    assert sample["location"] is None
    assert sample["location_canonical"] is None
    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is False
    assert assistant["location"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
