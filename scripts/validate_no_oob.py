#!/usr/bin/env python3
"""发布前校验：扫描 06_merged 工作区与 07_metadata，验证 interval 产物合规性。

校验成功不会生成或激活 08_training_ready；仍需继续执行质量检查、版本冻结和发布。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
VIDEO_DIR = DATA_DIR / "01_videos"
SUBVIDEO_DIR = DATA_DIR / "03_subvideos"
META_DIR = DATA_DIR / "07_metadata"
SPLITS_DIR = DATA_DIR / "05_splits"
MERGED_DIR = DATA_DIR / "06_merged"
SAMPLES_META_PATH = MERGED_DIR / "samples_meta.json"
SUBVIDEOS_META_DEFAULT = META_DIR / "subvideos_meta.label_reviewed.json"

FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
}


def _is_valid_fracture_between(fb: list, n: int | None = None) -> bool:
    """仅接受严格相邻区间 [i, i+1]；拒绝 [0,0] / [N-1,N-1] 等边界哨兵。"""
    if not (isinstance(fb, list) and len(fb) == 2):
        return False
    if fb[0] == fb[1]:
        return False
    return fb[1] == fb[0] + 1


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_splits() -> dict[str, set[str]]:
    splits: dict[str, set[str]] = {}
    for path in sorted(SPLITS_DIR.glob("*.json")):
        data = _load_json(path)
        if isinstance(data, dict):
            splits[path.stem] = set(data.get("video_ids", []))
    return splits


def _collect_video_meta() -> tuple[list[dict], dict[str, dict]]:
    meta = _load_json(META_DIR / "video_meta.json")
    if not isinstance(meta, list):
        raise FileNotFoundError(f"video_meta.json 不存在或格式错误: {META_DIR / 'video_meta.json'}")
    return meta, {r["video_id"]: r for r in meta}


def _validate_fracture_between(subvideos: list[dict], errors: list) -> None:
    for sub in subvideos:
        fb = sub.get("fracture_between")
        if fb is None:
            continue
        n = len(sub.get("sampled_frames") or [])
        if not (isinstance(fb, list) and len(fb) == 2):
            errors.append(("subvideos_meta", sub["subvideo_id"], "malformed", str(fb)))
            continue
        if fb[0] < 0 or fb[1] < 0 or fb[0] >= n or fb[1] >= n:
            errors.append(("subvideos_meta", sub["subvideo_id"], "out_of_bounds", str(fb), str(n)))
        if not _is_valid_fracture_between(fb, n):
            errors.append(("subvideos_meta", sub["subvideo_id"], "not_strictly_adjacent", str(fb)))


def _validate_merged_samples(subvideos: list[dict], errors: list) -> None:
    sub_by_id = {sub["subvideo_id"]: sub for sub in subvideos}
    for path in sorted(MERGED_DIR.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for s in data:
            if "start_frame" not in s or "end_frame" not in s:
                continue  # ShareGPT 格式样本不含这些字段，跳过
            fb = s.get("fracture_between")
            if fb is not None:
                if not (isinstance(fb, list) and len(fb) == 2):
                    errors.append(("merged", path.name, s.get("id"), "malformed", str(fb)))
                    continue
                sub = sub_by_id.get(s.get("id"))
                n = len(sub.get("sampled_frames") or []) if sub else None
                if fb[0] < 0 or fb[1] < 0 or not _is_valid_fracture_between(fb, n):
                    errors.append(("merged", path.name, s.get("id"), "bad_fracture_between", str(fb)))
                if sub and sub.get("fracture_between") != fb:
                    errors.append(("merged", path.name, s.get("id"), "mismatch_with_meta", str(fb), str(sub.get("fracture_between"))))


def _validate_coverage(video_meta: list[dict], errors: list) -> None:
    """验证 110 视频覆盖、ID 唯一、CSV 与视频文件存在。"""
    video_ids = [r["video_id"] for r in video_meta]
    if len(video_ids) != 110:
        errors.append(("coverage", f"video_meta 视频数 {len(video_ids)} != 110"))
    if len(set(video_ids)) != len(video_ids):
        errors.append(("coverage", "video_meta 存在重复 video_id"))
    csv_path = DATA_DIR / "02_annotations" / "all_videos_tag.csv"
    if csv_path.exists():
        import csv
        with csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_ids = {row["id"].strip() for row in reader}
        meta_set = set(video_ids)
        if meta_set != csv_ids:
            errors.append(("coverage", f"video_meta 与 CSV ID 不一致: 仅 meta {meta_set - csv_ids}, 仅 CSV {csv_ids - meta_set}"))
    for rec in video_meta:
        vid = rec["video_id"]
        video_path = VIDEO_DIR / f"{vid}.mp4"
        if not video_path.exists():
            errors.append(("coverage", vid, "missing_video_file", str(video_path)))


def _validate_splits(splits: dict[str, set[str]], video_meta: list[dict], errors: list) -> None:
    all_ids = {r["video_id"] for r in video_meta}
    required = {"test", "fold_0_train", "fold_0_val", "fold_1_train", "fold_1_val", "fold_2_train", "fold_2_val"}
    missing = required - set(splits)
    if missing:
        errors.append(("splits", f"缺少划分文件: {sorted(missing)}"))
        return

    # 互斥性：test 与所有其他 split 必须不相交；同一 fold 内 train/val 必须不相交
    for name in required:
        if name == "test":
            continue
        inter = splits[name] & splits["test"]
        if inter:
            errors.append(("splits", f"{name} 与 test 相交: {sorted(inter)[:5]}"))
    for i in range(3):
        train = splits[f"fold_{i}_train"]
        val = splits[f"fold_{i}_val"]
        inter = train & val
        if inter:
            errors.append(("splits", f"fold_{i}_train 与 fold_{i}_val 相交: {sorted(inter)[:5]}"))

    union = set().union(*(splits[name] for name in required))
    if union != all_ids:
        errors.append(("splits", f"划分未覆盖全部视频: 缺失 {sorted(all_ids - union)[:5]}, 多余 {sorted(union - all_ids)[:5]}"))

    # 稀有池只在 train
    inventory = _load_json(META_DIR / "inventory_report.json")
    rare_pool = []
    if isinstance(inventory, dict):
        rare_pool = inventory.get("rare_pool", [])
    if not rare_pool:
        # 若 inventory 未生成，根据 video_meta 重新计算
        type_counts = Counter(r["type"] for r in video_meta if r.get("has_fracture_canonical") and r["type"] in FRACTURE_TYPES)
        rare_types = {t for t, c in type_counts.items() if c <= 2}
        rare_pool = [r["video_id"] for r in video_meta if r.get("type") in rare_types and r.get("has_fracture_canonical")]
    train_union = splits["fold_0_train"] | splits["fold_1_train"] | splits["fold_2_train"]
    for vid in rare_pool:
        if vid not in train_union:
            errors.append(("rare_pool", vid, "not_in_any_train"))
        for val_name in ("fold_0_val", "fold_1_val", "fold_2_val", "test"):
            if vid in splits.get(val_name, set()):
                errors.append(("rare_pool", vid, f"leaked_to_{val_name}"))


def _validate_train_ratio(errors: list) -> None:
    meta = _load_json(SAMPLES_META_PATH)
    if not isinstance(meta, dict):
        errors.append(("ratio", "samples_meta.json", "missing_or_invalid; run training_sample_builder.py first"))
        return
    splits = meta.get("splits", {})
    pos = 0
    neg = 0
    missing = []
    for i in range(3):
        split_name = f"fold_{i}_train"
        split = splits.get(split_name)
        if split is None:
            missing.append(f"{split_name}.json")
            continue
        pos += split.get("positive_samples", 0)
        neg += split.get("negative_samples", 0)
    if missing:
        errors.append(("ratio", ",".join(missing), "missing_in_samples_meta"))
        return
    if pos == 0:
        errors.append(("ratio", "all_train_splits", "no_positive_samples"))
    if neg == 0:
        errors.append(("ratio", "all_train_splits", "no_negative_samples"))
    total = pos + neg
    if total == 0:
        errors.append(("ratio", "all_train_splits", "no_samples"))
        return
    ratio = pos / neg if neg > 0 else float("inf")
    if not (0.5 <= ratio <= 2.0):
        errors.append(("ratio", "all_train_splits", f"global pos/neg ratio={ratio:.2f}"))


def _validate_test_isolation(errors: list) -> None:
    test_inputs_path = MERGED_DIR / "test_inputs.json"
    if not test_inputs_path.exists():
        errors.append(("test", "test_inputs.json 不存在"))
        return
    inputs = _load_json(test_inputs_path)
    if not isinstance(inputs, list):
        errors.append(("test", "test_inputs.json 格式错误"))
        return
    forbidden = {"fracture_between", "has_fracture", "type", "location", "event_frame_original", "event_time"}
    for item in inputs:
        if not isinstance(item, dict):
            continue
        leaked = forbidden & set(item)
        if leaked:
            errors.append(("test", item.get("video_id"), "contains_truth_fields", sorted(leaked)))
    # 不应存在 test ShareGPT 产物
    if (MERGED_DIR / "test.json").exists():
        errors.append(("test", "test.json ShareGPT 产物不应存在"))


def _validate_media_paths(subvideos: list[dict], errors: list) -> None:
    for sub in subvideos:
        # 仅校验被选中的子视频（若存在 selected_splits）
        if sub.get("selected_splits") == []:
            continue
        rel = sub.get("video_path")
        if not rel:
            errors.append(("media", sub["subvideo_id"], "missing_video_path"))
            continue
        # video_path 可能是 data/...（相对项目根）或 03_subvideos/...（相对 data 目录）
        if rel.startswith("data/"):
            full = ROOT / rel
        else:
            full = DATA_DIR / rel
        if not full.exists():
            errors.append(("media", sub["subvideo_id"], "missing_file", str(rel)))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="独立校验脚本：扫描数据产物合规性")
    parser.add_argument(
        "--subvideos-meta",
        type=Path,
        default=SUBVIDEOS_META_DEFAULT,
        help="子视频元数据路径（默认：data/07_metadata/subvideos_meta.label_reviewed.json）",
    )
    args = parser.parse_args()

    errors: list[tuple[str, ...]] = []

    meta_path = args.subvideos_meta
    if not meta_path.exists():
        print(f"SKIP: generated subvideo metadata does not exist: {meta_path}")
        print("Run pipeline/scripts/subvideo_builder.py before validating generated artifacts.")
        return 0

    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    subvideos = raw.get("subvideos", []) if isinstance(raw, dict) else raw
    video_meta, _ = _collect_video_meta()
    splits = _load_splits()

    _validate_fracture_between(subvideos, errors)
    _validate_merged_samples(subvideos, errors)
    _validate_coverage(video_meta, errors)
    _validate_splits(splits, video_meta, errors)
    _validate_train_ratio(errors)
    _validate_test_isolation(errors)
    _validate_media_paths(subvideos, errors)

    print(f"Scanned {len(subvideos)} subvideos.")
    print(f"Errors: {len(errors)}")
    for e in errors[:40]:
        print("  ", e)

    if errors:
        return 1
    print("OK: all validation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
