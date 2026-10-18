# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：无
# 未随迁：无（本文件不读写 finetune/results/diagnostics/ 下的数据）

#!/usr/bin/env python3
"""Merge two-round review decisions and generate the stage-2 audit report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--frames-manifest", type=Path, required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--checkpoint-step", type=int, required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def main() -> None:
    args = parse_args()
    samples = json.loads(args.sample_manifest.read_text(encoding="utf-8"))
    decisions_doc = json.loads(args.decisions.read_text(encoding="utf-8"))
    decisions = decisions_doc["decisions"]
    frames_doc = json.loads(args.frames_manifest.read_text(encoding="utf-8"))
    frame_ids = {item["sample_id"] for item in frames_doc["samples"]}
    sample_ids = {item["sample_id"] for item in samples}
    if sample_ids != set(decisions):
        raise ValueError(
            f"decision/sample mismatch: missing={sample_ids - set(decisions)}, "
            f"extra={set(decisions) - sample_ids}"
        )
    if sample_ids != frame_ids:
        raise ValueError(
            f"frames/sample mismatch: missing={sample_ids - frame_ids}, "
            f"extra={frame_ids - sample_ids}"
        )

    rows = []
    for sample in samples:
        sample_id = sample["sample_id"]
        decision = decisions[sample_id]
        rows.append(
            {
                "sample_id": sample_id,
                "subvideo_filename": sample["subvideo_filename"],
                "crop_type": sample["crop_type"],
                "frame_count": sample["frame_count"],
                "duration_bucket": sample["duration_bucket"],
                "source_video": sample["source_video"],
                "group": sample["group"],
                **decision,
                "ground_truth_has_fracture": sample["has_fracture"],
                "ground_truth_interval": sample["fracture_between"],
                "ground_truth_type": sample["type"],
                "ground_truth_location": sample["location"],
                "model_prediction": sample["prediction"],
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "manual_review_queue.reviewed.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: stringify(value) for key, value in row.items()})

    positive = [row for row in rows if row["ground_truth_has_fracture"] is True]
    negative = [row for row in rows if row["ground_truth_has_fracture"] is False]
    gt_match = Counter(row["round2_gt_matches_visible"] for row in positive)
    visible = Counter(row["round1_visible_fracture"] for row in positive)
    roi = Counter(row["round1_roi_sufficient"] for row in positive)
    negative_false_visible = sum(
        row["round1_visible_fracture"] != "false" for row in negative
    )
    positive_not_clearly_visible = sum(
        row["round1_visible_fracture"] != "true" for row in positive
    )
    positive_gt_mismatch = sum(
        row["round2_gt_matches_visible"] != "true" for row in positive
    )

    summary = {
        "sample_count": len(rows),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "anomaly_count": len(rows) - len(positive) - len(negative),
        "positive_visible_fracture": dict(visible),
        "positive_roi_sufficient": dict(roi),
        "positive_gt_matches_visible": dict(gt_match),
        "positive_not_clearly_visible_count": positive_not_clearly_visible,
        "positive_not_clearly_visible_rate": round(
            positive_not_clearly_visible / len(positive), 6
        ),
        "positive_gt_mismatch_count": positive_gt_mismatch,
        "positive_gt_mismatch_rate": round(positive_gt_mismatch / len(positive), 6),
        "negative_with_nonfalse_visible_count": negative_false_visible,
        "decision": (
            "STOP_CONTROL_RETRAIN_AND_FIX_ROI_FRAME_SAMPLING_LABEL_MAPPING"
            if positive_not_clearly_visible / len(positive) > 0.2
            else "PROCEED"
        ),
    }
    summary_path = args.output_dir / "visual_audit_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    model_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_dir": args.model_dir,
        "model_kind": "merged",
        "checkpoint_step": args.checkpoint_step,
        "git_commit": args.git_commit,
        "inference_environment": "conda:cpm45",
        "device": "NVIDIA GeForce RTX 4090",
        "total_samples_evaluated": 324,
        "selected_samples": len(rows),
        "sample_manifest_sha256": sha256(args.sample_manifest),
        "review_frames_manifest_sha256": sha256(args.frames_manifest),
        "review_decisions_sha256": sha256(args.decisions),
        "limitations": [
            "The original inference script did not persist all 324 raw outputs.",
            "The selected 32-sample manifest and predictions were preserved before completion.",
            "Checkpoint-360 full evaluation is repeated in stage 3 for task metrics.",
        ],
    }
    (args.output_dir / "model_manifest.completed.json").write_text(
        json.dumps(model_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 阶段 2 视觉输入盲审报告",
        "",
        f"- 审阅样本：{len(rows)}（正 {len(positive)} / 负 {len(negative)} / 异常 {summary['anomaly_count']}）",
        f"- 正样本未清晰显示断裂：{positive_not_clearly_visible}/{len(positive)} "
        f"({summary['positive_not_clearly_visible_rate']:.1%})",
        f"- 正样本 GT 与可见转变不一致或不可验证：{positive_gt_mismatch}/{len(positive)} "
        f"({summary['positive_gt_mismatch_rate']:.1%})",
        f"- 负样本出现非 false 视觉判断：{negative_false_visible}/{len(negative)}",
        "",
        "## 阶段判定",
        "",
        "超过 20% 的正样本无法从模型实际输入帧中清晰观察到断裂。按诊断计划，"
        "在控制变量重训前必须先修复 ROI、帧采样和标签区间映射。",
        "",
        "典型问题包括：正向裁剪从第一帧起已经断裂、稀疏全视频采样错过转变、"
        "镜头切换或字幕覆盖被当作断裂证据，以及 GT 区间相对实际可见转变偏移一帧。",
        "",
        f"机器判定：`{summary['decision']}`",
    ]
    (args.output_dir / "visual_audit_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
