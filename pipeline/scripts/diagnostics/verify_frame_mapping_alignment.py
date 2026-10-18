# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：无
# 未随迁：无（本文件不读写 finetune/results/diagnostics/ 下的数据）

#!/usr/bin/env python3
"""Verify that persisted training mappings match inference-time sampled frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--review-frames-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance-seconds", type=float, default=0.001)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = {
        item["sample_id"]: item
        for item in json.loads(args.sample_manifest.read_text(encoding="utf-8"))
    }
    review_document = json.loads(
        args.review_frames_manifest.read_text(encoding="utf-8")
    )
    reviews = {item["sample_id"]: item for item in review_document["samples"]}
    if samples.keys() != reviews.keys():
        raise ValueError(
            f"sample ID mismatch: missing_review={sorted(samples.keys() - reviews.keys())}, "
            f"extra_review={sorted(reviews.keys() - samples.keys())}"
        )
    rows = []
    for sample_id, sample in samples.items():
        expected = [
            float(frame["clip_timestamp"])
            for frame in sample["actual_frame_mapping"]
        ]
        actual = [float(value) for value in reviews[sample_id]["sampled_timestamps"]]
        count_matches = len(expected) == len(actual)
        differences = (
            [abs(left - right) for left, right in zip(expected, actual, strict=True)]
            if count_matches
            else []
        )
        max_difference = max(differences, default=None)
        aligned = (
            count_matches
            and max_difference is not None
            and max_difference <= args.tolerance_seconds
        )
        rows.append(
            {
                "sample_id": sample_id,
                "expected_frame_count": len(expected),
                "actual_frame_count": len(actual),
                "count_matches": count_matches,
                "max_timestamp_difference_seconds": max_difference,
                "aligned": aligned,
            }
        )
    summary = {
        "sample_count": len(rows),
        "tolerance_seconds": args.tolerance_seconds,
        "frame_count_match_count": sum(row["count_matches"] for row in rows),
        "aligned_count": sum(row["aligned"] for row in rows),
        "all_aligned": all(row["aligned"] for row in rows),
        "conclusion": (
            "Training metadata and inference sampling are aligned; visual audit "
            "mismatches cannot be attributed to frame-loader index drift."
            if all(row["aligned"] for row in rows)
            else "Frame mapping drift exists and must be fixed before model comparison."
        ),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in ("sample_count", "frame_count_match_count", "aligned_count", "all_aligned", "conclusion")}, ensure_ascii=False, indent=2))
    if not summary["all_aligned"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
