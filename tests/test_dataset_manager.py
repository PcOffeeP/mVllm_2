from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.scripts.dataset_manager import (
    _parse_frame_rate,
    _to_float,
    stratified_split,
    write_json,
)


def _make_records(n: int) -> list[dict]:
    """构造可用于 stratified_split 的伪 video_meta 记录。"""
    types = [
        "韧性断裂",
        "脆性断裂",
        "界面脱粘",
        "齐根断裂",
        "爆炸性断裂",
        "半脆半韧断裂",
        "界面脱粘、齐根断裂",
        "未断裂",
        "未夹紧",
        "视频异常",
    ]
    records = []
    for i in range(n):
        ftype = types[i % len(types)]
        loc = "inside_gauge" if i % 10 < 7 else "outside_gauge"
        if ftype in {"未断裂", "未夹紧", "视频异常"}:
            loc = "N/A"
        records.append(
            {
                "video_id": f"video_{i:04d}",
                "type": ftype,
                "location": loc,
            }
        )
    return records


def _unwrap(splits):
    """stratified_split 返回 (splits, decision_log)，测试只关心 splits。"""
    return splits[0] if isinstance(splits, tuple) else splits


def test_stratified_split_test_ratio_is_around_20_percent():
    records = _make_records(100)
    splits = _unwrap(stratified_split(records, test_ratio=0.2, n_folds=3, seed=42))
    total = len(records)
    test_ratio = len(splits["test"]) / total
    assert 0.15 <= test_ratio <= 0.25, f"test ratio {test_ratio} 不在 20% 附近"


def test_stratified_split_folds_are_disjoint_and_cover_all():
    records = _make_records(100)
    splits = _unwrap(stratified_split(records, test_ratio=0.2, n_folds=3, seed=42))

    all_ids = {r["video_id"] for r in records}
    test_ids = set(splits["test"])
    train_val_ids: set[str] = set()

    for i in range(3):
        train_ids = set(splits[f"fold_{i}_train"])
        val_ids = set(splits[f"fold_{i}_val"])
        assert train_ids & val_ids == set(), f"fold {i} train/val 有重叠"
        train_val_ids.update(train_ids, val_ids)

    assert test_ids & train_val_ids == set(), "test 与 train/val 有重叠"
    assert test_ids | train_val_ids == all_ids, "划分未覆盖全部视频"


def test_stratified_split_train_larger_than_val():
    records = _make_records(100)
    splits = _unwrap(stratified_split(records, test_ratio=0.2, n_folds=3, seed=42))
    for i in range(3):
        assert len(splits[f"fold_{i}_train"]) > len(splits[f"fold_{i}_val"])


# ---------------------------------------------------------------------------
# 真实产物检查
# ---------------------------------------------------------------------------

VIDEO_META_PATH = ROOT / "data" / "metadata" / "video_meta.json"
SPLITS_DIR = ROOT / "data" / "03_splits"

CONFLICT_VIDEOS = {
    "video_0045",
    "video_0049",
    "video_0078",
    "video_0083",
    "video_0094",
    "video_0096",
    "video_0107",
}


@pytest.mark.skipif(not VIDEO_META_PATH.exists(), reason="video_meta.json 不存在")
def test_conflict_abnormal_videos_are_downgraded():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    by_id = {r["video_id"]: r for r in meta}
    for vid in CONFLICT_VIDEOS:
        rec = by_id[vid]
        assert rec["is_abnormal"] is True, f"{vid} 应为异常样本"
        # CSV 原始标签必须保留
        assert rec["has_fracture"] is True, f"{vid} CSV 原始 has_fracture 不应被覆盖"
        assert rec["type"] == "视频异常", f"{vid} CSV 原始 type 不应被覆盖"
        # canonical 字段应被正确降级
        assert rec["has_fracture_canonical"] is False, (
            f"{vid} 冲突样本 canonical 未降级"
        )
        assert rec["location_canonical"] == "N/A", (
            f"{vid} 异常样本 location_canonical 应为 N/A"
        )
        assert rec["is_label_conflict"] is True, f"{vid} 应被标记为标签冲突"
        assert rec["label_governance_reason"], f"{vid} 应有治理原因"


@pytest.mark.skipif(
    not (SPLITS_DIR / "test.json").exists(), reason="划分文件不存在"
)
def test_real_splits_no_leakage_and_full_coverage():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    all_ids = {r["video_id"] for r in meta}

    splits: dict[str, set[str]] = {}
    for name in ["fold_0_train", "fold_0_val", "fold_1_train", "fold_1_val",
                 "fold_2_train", "fold_2_val", "test"]:
        path = SPLITS_DIR / f"{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        splits[name] = set(data.get("video_ids", []))

    test_ids = splits["test"]
    train_val_ids: set[str] = set()
    for name, ids in splits.items():
        if name == "test":
            continue
        assert not (ids & test_ids), f"{name} 与 test 存在视频泄漏"
        train_val_ids.update(ids)

    assert test_ids | train_val_ids == all_ids, "划分未覆盖全部视频"


@pytest.mark.skipif(
    not (SPLITS_DIR / "test.json").exists(), reason="划分文件不存在"
)
def test_real_split_test_ratio_around_20_percent():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    total = len(meta)
    test_data = json.loads((SPLITS_DIR / "test.json").read_text(encoding="utf-8"))
    test_count = len(test_data.get("video_ids", []))
    ratio = test_count / total
    assert 0.15 <= ratio <= 0.25, f"真实 test ratio={ratio:.2%} 不在 20% 附近"


@pytest.mark.skipif(
    not (SPLITS_DIR / "fold_0_train.json").exists(), reason="划分文件不存在"
)
def test_real_split_type_distribution_not_empty():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    by_id = {r["video_id"]: r for r in meta}

    for name in ["test", "fold_0_train", "fold_0_val"]:
        path = SPLITS_DIR / f"{name}.json"
        if not path.exists():
            continue
        ids = json.loads(path.read_text(encoding="utf-8")).get("video_ids", [])
        types = {by_id[vid]["type"] for vid in ids if vid in by_id}
        assert types, f"{name} 中没有任何 type"


# ---------------------------------------------------------------------------
# 标签治理 / canonical 字段单元测试
# ---------------------------------------------------------------------------

from pipeline.scripts.dataset_manager import build_video_meta


def _make_annotation_row(
    video_id: str,
    has_fracture: bool,
    is_abnormal: bool,
    ftype: str,
    location: str | None,
) -> dict:
    return {
        "id": video_id,
        "video_path": f"data/01_videos/{video_id}.mp4",
        "断裂时间点": "",
        "断裂模式": ftype,
        "材料类型": "金属",
        "清晰度": "480P",
        "断裂位置": location if location is not None else "",
        "断裂帧数": "",
        "视频时长": "",
        "视频帧率": "",
        "视频总帧数": "",
        "has_fracture": has_fracture,
        "is_abnormal": is_abnormal,
    }


def test_canonical_preserved_for_abnormal_fracture_conflict(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_conflict",
                has_fracture=True,
                is_abnormal=True,
                ftype="视频异常",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr(
        "pipeline.scripts.dataset_manager._ffprobe", lambda path: {}
    )
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is True, "CSV 原始 has_fracture 必须保留"
    assert rec["location"] == "inside_gauge", "CSV 原始 location 必须保留"
    assert rec["has_fracture_canonical"] is False
    assert rec["location_canonical"] == "N/A"
    assert rec["is_label_conflict"] is True
    assert any("is_abnormal=True" in r for r in rec["label_governance_reason"])
    assert any("数据一致性错误" in w for w in warnings)


def test_canonical_preserved_for_non_fracture_type(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_bad_type",
                has_fracture=True,
                is_abnormal=False,
                ftype="未断裂",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr(
        "pipeline.scripts.dataset_manager._ffprobe", lambda path: {}
    )
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is True, "CSV 原始 has_fracture 必须保留"
    assert rec["type"] == "未断裂", "CSV 原始 type 必须保留"
    assert rec["has_fracture_canonical"] is False
    assert rec["is_label_conflict"] is True
    assert any("不在 7 个断裂类中" in r for r in rec["label_governance_reason"])


def test_canonical_equals_original_for_normal_fracture(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_normal",
                has_fracture=True,
                is_abnormal=False,
                ftype="韧性断裂",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr(
        "pipeline.scripts.dataset_manager._ffprobe", lambda path: {}
    )
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is True
    assert rec["has_fracture_canonical"] is True
    assert rec["location"] == "inside_gauge"
    assert rec["location_canonical"] == "inside_gauge"
    assert rec["is_label_conflict"] is False
    assert rec["label_governance_reason"] == []
    assert all("ffprobe" in w for w in warnings) or not warnings


def test_canonical_equals_original_for_normal_negative(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_neg",
                has_fracture=False,
                is_abnormal=False,
                ftype="未断裂",
                location="N/A",
            )
        ]
    )
    monkeypatch.setattr(
        "pipeline.scripts.dataset_manager._ffprobe", lambda path: {}
    )
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is False
    assert rec["has_fracture_canonical"] is False
    assert rec["is_label_conflict"] is False
    assert rec["label_governance_reason"] == []


def test_abnormal_forces_location_canonical_to_na_without_overwriting_original(
    monkeypatch: pytest.MonkeyPatch,
):
    """异常样本的 location 应通过 location_canonical 改为 N/A，原始 location 保留。"""
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_abnormal_loc",
                has_fracture=False,
                is_abnormal=True,
                ftype="未夹紧",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr(
        "pipeline.scripts.dataset_manager._ffprobe", lambda path: {}
    )
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["location"] == "inside_gauge", "CSV 原始 location 必须保留"
    assert rec["location_canonical"] == "N/A", "异常样本 location_canonical 应为 N/A"
    assert rec["has_fracture"] is False
    assert rec["has_fracture_canonical"] is False
    assert rec["is_label_conflict"] is True
    assert any("location 强制设为 location_canonical=N/A" in r for r in rec["label_governance_reason"])
    assert any("location 强制设为 location_canonical=N/A" in w for w in warnings)


# ---------------------------------------------------------------------------
# NaN / inf 健壮性
# ---------------------------------------------------------------------------


def test_to_float_rejects_nan_and_inf():
    assert _to_float(float("nan")) is None
    assert _to_float(float("inf")) is None
    assert _to_float(float("-inf")) is None
    assert _to_float("nan") is None
    assert _to_float("inf") is None
    assert _to_float("-inf") is None
    assert _to_float("3.14") == 3.14


def test_parse_frame_rate_rejects_nan_and_inf():
    assert _parse_frame_rate("nan") is None
    assert _parse_frame_rate("inf") is None
    assert _parse_frame_rate("-inf") is None
    assert _parse_frame_rate("NaN") is None
    assert _parse_frame_rate("1/0") is None
    assert _parse_frame_rate("0/0") is None
    assert _parse_frame_rate("30/1") == 30.0
    assert _parse_frame_rate("29.97") == 29.97


def test_build_video_meta_handles_nan_duration_and_fps(monkeypatch: pytest.MonkeyPatch):
    row = _make_annotation_row(
        "video_nan_meta",
        has_fracture=False,
        is_abnormal=False,
        ftype="未断裂",
        location="N/A",
    )
    row["视频时长"] = float("nan")
    row["视频帧率"] = float("nan")
    df = pd.DataFrame([row])
    monkeypatch.setattr(
        "pipeline.scripts.dataset_manager._ffprobe", lambda path: {}
    )
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["fps"] == 30.0
    assert rec["duration"] == 0.0
    assert rec["total_frames"] is None


def test_write_json_rejects_nan(tmp_path: Path):
    with pytest.raises(ValueError):
        write_json(tmp_path / "bad.json", {"value": float("nan")})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
