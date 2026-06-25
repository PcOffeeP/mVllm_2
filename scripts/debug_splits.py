"""诊断：检查 split 文件加载和视频 ID 覆盖情况。"""
import json
import re
from pathlib import Path


def main():
    splits_dir = Path("data/05_splits")
    if not splits_dir.exists():
        print(f"❌ {splits_dir} 不存在")
        return

    pattern = re.compile(r"^(fold_\d+_(?:train|val)|test)$")

    print("=== 读取的文件 ===")
    matched_files = []
    for f in sorted(splits_dir.glob("*.json")):
        match = bool(pattern.match(f.stem))
        print(f"  {f.name}  stem={f.stem}  匹配={'✅' if match else '❌'}")
        if match:
            matched_files.append(f)

    if not matched_files:
        print("\n❌ 没有匹配的文件！")
        return

    print(f"\n匹配的文件: {len(matched_files)} 个")

    # 统计 split 分布
    mapping = {}
    for f in matched_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        split_name = data.get("split")
        if split_name is None:
            split_name = "test" if f.stem == "test" else "train"
        for vid in data.get("video_ids", []):
            if vid not in mapping:
                mapping[vid] = {}
            mapping[vid][f.stem] = split_name

    test_ids = [vid for vid, info in mapping.items() if "test" in info]
    only_fold = [vid for vid, info in mapping.items() if "test" not in info]

    print(f"\n=== split 分布 ===")
    print(f"  总视频数: {len(mapping)}")
    print(f"  测试集中视频数: {len(test_ids)}")
    print(f"  仅 fold 中视频数: {len(only_fold)}")
    if only_fold:
        print(f"  仅 fold 视频示例: {only_fold[:5]}...")

    for split_type in ["test", "train", "val"]:
        count = sum(1 for v in mapping.values() if v.get("split") == split_type)
        print(f"  {split_type}: {count}")

    # video_meta.json 中的 ID 与 split ID 对比
    meta_path = Path("data/07_metadata/video_meta.json")
    if not meta_path.exists():
        print(f"\n❌ {meta_path} 不存在")
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta_ids = {r["video_id"] for r in meta}
    mapped_ids = set(mapping.keys())

    print(f"\n=== video_meta vs split 覆盖 ===")
    print(f"  video_meta.json 视频数: {len(meta_ids)}")
    print(f"  split 文件覆盖数: {len(mapped_ids)}")

    missing = meta_ids - mapped_ids
    extra = mapped_ids - meta_ids
    if missing:
        print(f"  ⚠️  在 meta 但不在 split 中: {missing}")
    if extra:
        print(f"  ⚠️  在 split 但不在 meta 中: {extra}")
    if not missing and not extra:
        print(f"  ✅ 完全一致")

    # 检查 subvideo_builder 中 split_info.get("split") == "test" 的行为
    test_in_splits = sum(
        1 for v in mapping.values() if v.get("split") == "test"
    )
    print(f"\n=== subvideo_builder 视角 ===")
    print(f"  会被跳过的视频数 (split=test): {test_in_splits}")
    print(f"  会处理的视频数: {len(mapping) - test_in_splits}")


if __name__ == "__main__":
    main()
