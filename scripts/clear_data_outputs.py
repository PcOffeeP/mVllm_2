#!/usr/bin/env python3
"""安全清空指定的数据产物目录，保留目录本身。

受保护的目录（不会被触碰）：
- data/01_videos/
- data/02_annotations/
- data/08_training_ready/（已发布、不可覆盖的训练版本）
"""

import shutil
import sys
from pathlib import Path


TARGET_DIRS = [
    "data/05_splits/",
    "data/06_merged/",
    "data/03_subvideos/",
    "data/04_frames/",
    "data/07_metadata/",
    "data/08_runtime/",
]

PROTECTED_DIRS = [
    "data/01_videos/",
    "data/02_annotations/",
    "data/08_training_ready/",
]


def _repo_root() -> Path:
    """脚本位于 scripts/，因此仓库根目录是其父目录。"""
    return Path(__file__).resolve().parent.parent


def _count_items(directory: Path) -> int:
    """返回目录下直接子项的数量；目录不存在时返回 0。"""
    if not directory.exists():
        return 0
    return len(list(directory.iterdir()))


def _is_safe_target(root: Path, target: Path, protected: set[Path]) -> bool:
    """确保目标位于仓库内且在 data/ 下，并且不是受保护目录。"""
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        return False
    if not resolved.is_relative_to(root / "data"):
        return False
    if resolved in protected:
        return False
    return True


def clear_data_outputs() -> None:
    root = _repo_root()
    protected = {root / p for p in PROTECTED_DIRS}

    targets = [root / p for p in TARGET_DIRS]

    print("将要清空的数据产物目录：")
    for t in targets:
        status = "存在" if t.is_dir() else "不存在（将跳过）"
        print(f"  - {t.relative_to(root)}  [{status}]")
    print()

    for target in targets:
        if not target.exists():
            print(f"跳过（不存在）: {target.relative_to(root)}")
            continue

        if not _is_safe_target(root, target, protected):
            print(
                f"拒绝处理非安全目标: {target.relative_to(root)}",
                file=sys.stderr,
            )
            continue

        if not target.is_dir():
            print(
                f"目标不是目录，跳过: {target.relative_to(root)}",
                file=sys.stderr,
            )
            continue

        print(f"正在清空: {target.relative_to(root)}")
        for child in sorted(target.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    print()
    print("清空后各目录剩余项目数：")
    for target in targets:
        count = _count_items(target)
        print(f"  - {target.relative_to(root)}: {count}")


if __name__ == "__main__":
    clear_data_outputs()
