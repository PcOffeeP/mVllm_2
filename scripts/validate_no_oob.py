#!/usr/bin/env python3
"""独立校验脚本：扫描 subvideos_meta.json 与 04_new_merged 样本，确认无越界 fracture_between。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _is_valid_fracture_between(fb: list, n: int | None = None) -> bool:
    """Return True if fracture_between is adjacent frames or a boundary sentinel."""
    if not (isinstance(fb, list) and len(fb) == 2):
        return False
    if fb[0] == 0 and fb[1] == 0:
        return True
    if n is not None and fb[0] == n - 1 and fb[1] == n - 1:
        return True
    return fb[1] == fb[0] + 1


def main() -> int:
    errors: list[tuple[str, ...]] = []

    # 1. 扫描子视频元数据
    meta_path = ROOT / "data" / "metadata" / "subvideos_meta.json"
    if not meta_path.exists():
        print(f"SKIP: generated subvideo metadata does not exist: {meta_path}")
        print("Run pipeline/scripts/subvideo_builder.py before validating generated artifacts.")
        return 0

    subs = json.loads(meta_path.read_text(encoding="utf-8"))
    for sub in subs:
        fb = sub.get("fracture_between")
        if fb is None:
            continue
        n = len(sub.get("frame_paths") or [])
        if not (isinstance(fb, list) and len(fb) == 2):
            errors.append(("subvideos_meta", sub["subvideo_id"], "malformed", str(fb)))
            continue
        if fb[0] < 0 or fb[1] < 0 or fb[0] >= n or fb[1] >= n:
            errors.append(
                ("subvideos_meta", sub["subvideo_id"], "out_of_bounds", str(fb), str(n))
            )
        if not _is_valid_fracture_between(fb, n):
            errors.append(("subvideos_meta", sub["subvideo_id"], "not_adjacent", str(fb)))

    # 2. 扫描训练样本中的 fracture_between 与 start_frame/end_frame
    merged_dir = ROOT / "data" / "04_new_merged"
    sub_by_id = {sub["subvideo_id"]: sub for sub in subs}
    for path in sorted(merged_dir.glob("*.json")):
        if path.name == "samples_meta.json":
            continue
        samples = json.loads(path.read_text(encoding="utf-8"))
        for s in samples:
            if "start_frame" not in s or "end_frame" not in s:
                errors.append(("merged", path.name, s["id"], "missing_start_end_frame"))
            fb = s.get("fracture_between")
            if fb is not None:
                if not (isinstance(fb, list) and len(fb) == 2):
                    errors.append(("merged", path.name, s["id"], "malformed", str(fb)))
                    continue
                # 与元数据交叉校验并取帧数用于哨兵判断
                sub = sub_by_id.get(s["id"])
                n = len(sub.get("frame_paths") or []) if sub else None
                if fb[0] < 0 or fb[1] < 0 or not _is_valid_fracture_between(fb, n):
                    errors.append(("merged", path.name, s["id"], "bad_fracture_between", str(fb)))
                if sub and sub.get("fracture_between") != fb:
                    errors.append(("merged", path.name, s["id"], "mismatch_with_meta", str(fb), str(sub.get("fracture_between"))))

    print(f"Scanned {len(subs)} subvideos.")
    print(f"Errors: {len(errors)}")
    for e in errors[:20]:
        print("  ", e)

    if errors:
        return 1
    print("OK: no out-of-bounds fracture_between, all samples have start_frame/end_frame.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
