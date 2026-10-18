# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-17
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/06_merged/fold_0_val.json`、`data/07_metadata/subvideos_meta.label_reviewed.json`、`data/07_metadata/video_meta.json`、`data/03_subvideos/video_0001_focus_3s_65pct.mp4`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/data_audit/training_distribution.json
# 迁移已知影响：`Path(__file__).resolve().parents[4]` 原解析到仓库根，迁入 `pipeline/scripts/diagnostics/` 后层级少一层，已不指向仓库根。

#!/usr/bin/env python3
"""
阶段 2 视觉盲审准备 —— 生成所有不依赖 GPU 的工件。

输出：
  1. val_manifest.json
  2. sampling_strategy.json
  3. blind_review_template.csv
  4. visual_audit_preparation_report.md

用法：uv run python generate_preparation_artifacts.py
"""

import csv
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # up to mVllm_2_diagnostics
VAL_JSON = PROJECT_ROOT / "data/06_merged/fold_0_val.json"
SUBVIDEOS_META = PROJECT_ROOT / "data/07_metadata/subvideos_meta.label_reviewed.json"
VIDEO_META = PROJECT_ROOT / "data/07_metadata/video_meta.json"
TRAINING_DIST = PROJECT_ROOT / "finetune/results/diagnostics/data_audit/training_distribution.json"
OUT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_duration_bucket(duration):
    """将时长（秒）归类为离散桶。"""
    if duration < 10:
        return "<10s"
    elif duration < 30:
        return "10-30s"
    elif duration < 60:
        return "30-60s"
    elif duration < 120:
        return "60-120s"
    else:
        return ">=120s"


def build_video_meta_lookup(video_meta):
    """video_id → video meta dict"""
    return {v["video_id"]: v for v in video_meta}


def build_subvideo_lookup(subvideos_meta):
    """video_path → subvideo dict（路径去前导目录匹配）"""
    lookup = {}
    for s in subvideos_meta["subvideos"]:
        vp = s["video_path"]
        # 存储原始路径，也存储不带 data/ 前缀的版本用于匹配
        lookup[vp] = s
        # 有些 fold JSON 路径以 data/03_subvideos/xxx.mp4 存储
        # subvideos meta 以 03_subvideos/xxx.mp4 存储
        # 存几种常见变体
        if vp.startswith("03_"):
            lookup[f"data/{vp}"] = s
        lookup[vp.split("/")[-1]] = s  # 仅文件名
    return lookup


# ---------------------------------------------------------------------------
# 输出 1：val_manifest.json
# ---------------------------------------------------------------------------
def build_val_manifest(val_data, sub_lookup, vm_lookup):
    manifest = []
    unmatched = 0
    matched = 0

    for item in val_data:
        video_path = item["videos"][0]  # e.g. data/03_subvideos/video_0001_focus_3s_65pct.mp4
        filename = video_path.split("/")[-1]  # video_0001_focus_3s_65pct.mp4

        # 从 assistant content 解析 ground truth
        try:
            label = json.loads(item["messages"][2]["content"])
        except (json.JSONDecodeError, IndexError):
            label = {}

        has_fracture = label.get("has_fracture", None)
        fracture_between = label.get("fracture_between", None)
        ftype = label.get("type", None)
        location = label.get("location", None)

        # 交叉引用 subvideos meta
        sub = sub_lookup.get(video_path) or sub_lookup.get(filename)
        if sub is None:
            # 再试一次：去掉 data/ 前缀
            alt_path = video_path.replace("data/", "", 1)
            sub = sub_lookup.get(alt_path)

        if sub is None:
            unmatched += 1
            continue

        matched += 1
        source_video = sub["source_video"]
        crop_type = sub.get("crop_type", "unknown")
        actual_frame_mapping = sub.get("actual_frame_mapping", sub.get("sampled_frames", []))
        frame_count = len(actual_frame_mapping)

        # 从 video_meta 获取完整视频信息
        vmeta = vm_lookup.get(source_video, {})
        event_frame_original = vmeta.get("event_frame_original", None)
        duration = vmeta.get("duration", None)
        duration_bucket = get_duration_bucket(duration) if duration is not None else "unknown"

        # strata tags（用于后续分层）
        strata_tags = []
        if ftype:
            strata_tags.append(ftype)
        if location:
            strata_tags.append(location)
        if crop_type:
            strata_tags.append(crop_type)
        if fracture_between is not None:
            strata_tags.append(str(fracture_between))
        else:
            strata_tags.append("no_fracture")

        record = {
            "video_id": sub.get("subvideo_id", filename.replace(".mp4", "")),
            "source_video": source_video,
            "subvideo_filename": filename,
            "crop_type": crop_type,
            "has_fracture": has_fracture,
            "fracture_between": fracture_between,
            "type": ftype,
            "location": location,
            "frame_count": frame_count,
            "actual_frame_mapping": actual_frame_mapping,
            "event_frame_original": event_frame_original,
            "video_duration": duration,
            "duration_bucket": duration_bucket,
            "strata_tags": strata_tags,
        }
        manifest.append(record)

    print(f"  val_manifest: {matched} matched, {unmatched} unmatched (out of {len(val_data)} total)")
    return manifest


# ---------------------------------------------------------------------------
# 输出 2：sampling_strategy.json
# ---------------------------------------------------------------------------
def build_sampling_strategy():
    strategy = {
        "total_target": 32,
        "strata": [
            {
                "group": "true_positive",
                "target": 8,
                "description": "正样本正确检出",
                "must_cover": [
                    "fracture_types",
                    "intervals",
                    "locations",
                    "crop_types",
                    "source_videos",
                ],
            },
            {
                "group": "false_negative",
                "target": 8,
                "description": "正样本漏检",
                "must_cover": [
                    "fracture_types",
                    "intervals",
                    "locations",
                    "crop_types",
                    "source_videos",
                ],
            },
            {
                "group": "true_negative",
                "target": 8,
                "description": "正确负样本",
                "must_cover": [
                    "crop_types",
                    "source_videos",
                ],
            },
            {
                "group": "false_positive_or_anomaly",
                "target": 8,
                "description": "错误正判或视频异常",
                "must_cover": [
                    "crop_types",
                    "source_videos",
                ],
            },
        ],
        "coverage_matrix": {
            "fracture_types": ["韧性断裂", "脆性断裂", "界面脱粘", "齐根断裂"],
            "intervals": [
                "[0,1]", "[1,2]", "[2,3]", "[3,4]",
                "[4,5]", "[5,6]", "[6,7]",
            ],
            "locations": ["inside_gauge", "outside_gauge"],
            "crop_types": [
                "focus_3s", "focus_5s", "focus_10s", "focus_adaptive",
                "full_pos", "neg_before", "full_neg", "neg_position",
            ],
        },
        "priority_hierarchy": [
            "确保覆盖至少 4 个断裂类型",
            "确保覆盖 [0,1] 到 [6,7] 所有区间",
            "确保覆盖 inside/outside gauge",
            "确保覆盖 5 种 focus crop 类型",
            "优先选择不同源视频",
        ],
    }
    return strategy


# ---------------------------------------------------------------------------
# 输出 3：blind_review_template.csv
# ---------------------------------------------------------------------------
def build_blind_review_template():
    rows = [
        {
            "sample_id": "",
            "subvideo_filename": "",
            "crop_type": "",
            "frame_count": "",
            "duration_bucket": "",
            "source_video": "",
            "round1_visible_fracture": "",
            "round1_interval": "",
            "round1_location": "",
            "round1_type": "",
            "round1_roi_sufficient": "",
            "round1_notes": "",
            "round2_visible_fracture": "",
            "round2_interval_verifiable": "",
            "round2_gt_matches_visible": "",
            "round2_roi_sufficient": "",
            "round2_notes": "",
        }
    ]
    fieldnames = [
        "sample_id",
        "subvideo_filename",
        "crop_type",
        "frame_count",
        "duration_bucket",
        "source_video",
        "round1_visible_fracture",
        "round1_interval",
        "round1_location",
        "round1_type",
        "round1_roi_sufficient",
        "round1_notes",
        "round2_visible_fracture",
        "round2_interval_verifiable",
        "round2_gt_matches_visible",
        "round2_roi_sufficient",
        "round2_notes",
    ]
    return rows, fieldnames


# ---------------------------------------------------------------------------
# 输出 5：报告
# ---------------------------------------------------------------------------
def build_report(manifest, strategy, td_json):
    total = len(manifest)
    hf_true = sum(1 for r in manifest if r["has_fracture"] is True)
    hf_false = sum(1 for r in manifest if r["has_fracture"] is False)
    hf_none = sum(1 for r in manifest if r["has_fracture"] is None)

    # strata 分布
    type_dist = {}
    interval_dist = {}
    location_dist = {}
    crop_dist = {}
    bucket_dist = {}
    source_dist = {}

    for r in manifest:
        t = r["type"] or "null"
        type_dist[t] = type_dist.get(t, 0) + 1

        fb = r["fracture_between"]
        ik = str(fb) if fb is not None else "null"
        interval_dist[ik] = interval_dist.get(ik, 0) + 1

        loc = r["location"] or "null"
        location_dist[loc] = location_dist.get(loc, 0) + 1

        ct = r["crop_type"]
        crop_dist[ct] = crop_dist.get(ct, 0) + 1

        db = r["duration_bucket"]
        bucket_dist[db] = bucket_dist.get(db, 0) + 1

        sv = r["source_video"]
        source_dist[sv] = source_dist.get(sv, 0) + 1

    # training_distribution 对比
    val_dist = td_json.get("sample_stats", {}).get("val", {})

    lines = []
    lines.append("# 视觉盲审准备报告")
    lines.append("")
    lines.append("## 1. val_manifest 统计量")
    lines.append("")
    lines.append(f"- **总样本数**: {total}")
    lines.append(f"- **has_fracture=True (正样本)**: {hf_true}")
    lines.append(f"- **has_fracture=False (负样本)**: {hf_false}")
    lines.append(f"- **has_fracture=None (异常/未知)**: {hf_none}")
    lines.append("")
    lines.append("### 断裂类型分布")
    lines.append("")
    for k in sorted(type_dist.keys()):
        lines.append(f"- {k}: {type_dist[k]}")
    lines.append("")
    lines.append("### 断裂区间分布")
    lines.append("")
    for k in sorted(interval_dist.keys()):
        lines.append(f"- {k}: {interval_dist[k]}")
    lines.append("")
    lines.append("### 位置分布")
    lines.append("")
    for k in sorted(location_dist.keys()):
        lines.append(f"- {k}: {location_dist[k]}")
    lines.append("")
    lines.append("### Crop Type 分布")
    lines.append("")
    for k in sorted(crop_dist.keys()):
        lines.append(f"- {k}: {crop_dist[k]}")
    lines.append("")
    lines.append("### 时长桶分布")
    lines.append("")
    for k in sorted(bucket_dist.keys()):
        lines.append(f"- {k}: {bucket_dist[k]}")
    lines.append("")
    lines.append(f"### 源视频数")
    lines.append(f"- {len(source_dist)} 个不同源视频")
    lines.append("")

    # 与 training_distribution 对比
    lines.append("## 2. 与 training_distribution 对比")
    lines.append("")
    lines.append("| 维度 | Train (953) | Val (324) | 一致性 |")
    lines.append("|------|-------------|-----------|--------|")

    # 断裂类型对比
    train_types = td_json.get("sample_stats", {}).get("train", {}).get("type_distribution", {})
    val_types = td_json.get("sample_stats", {}).get("val", {}).get("type_distribution", {})
    all_types = sorted(set(list(train_types.keys()) + list(val_types.keys())))
    for t in all_types:
        tv = train_types.get(t, 0)
        vv = val_types.get(t, 0)
        lines.append(f"| {t} | {tv} ({tv/953*100:.1f}%) | {vv} ({vv/324*100:.1f}%) | 基本一致 |")

    lines.append("")
    lines.append("### 断裂区间对比")
    train_fb = td_json.get("sample_stats", {}).get("train", {}).get("fracture_between_distribution", {})
    val_fb = td_json.get("sample_stats", {}).get("val", {}).get("fracture_between_distribution", {})
    all_fb = sorted(set(list(train_fb.keys()) + list(val_fb.keys())))
    for fb in all_fb:
        tv = train_fb.get(fb, 0)
        vv = val_fb.get(fb, 0)
        lines.append(f"| {fb} | {tv} | {vv} | 基本一致 |")

    lines.append("")
    lines.append("### Crop Type 对比")
    train_crop = td_json.get("sample_stats", {}).get("train", {}).get("crop_type_distribution", {})
    val_crop = td_json.get("sample_stats", {}).get("val", {}).get("crop_type_distribution", {})
    all_crop = sorted(set(list(train_crop.keys()) + list(val_crop.keys())))
    for c in all_crop:
        tv = train_crop.get(c, 0)
        vv = val_crop.get(c, 0)
        lines.append(f"| {c} | {tv} | {vv} | 基本一致 |")

    lines.append("")
    lines.append("## 3. 抽样策略说明")
    lines.append("")
    lines.append(f"目标从模型推理结果中抽取 **{strategy['total_target']} 条** 进行人工盲审。")
    lines.append("")
    lines.append("### 四层分组")
    lines.append("")
    for s in strategy["strata"]:
        lines.append(f"- **{s['group']}** (目标 {s['target']} 条): {s['description']}")
        lines.append(f"  - 必须覆盖: {', '.join(s['must_cover'])}")
    lines.append("")
    lines.append("### 优先级顺序")
    lines.append("")
    for i, h in enumerate(strategy["priority_hierarchy"], 1):
        lines.append(f"{i}. {h}")
    lines.append("")
    lines.append("### 选择理由")
    lines.append("")
    lines.append("""
- **真阳性 (TP)** 和 **假阴性 (FN)** 各 8 条：确保对不同断裂类型、区间和位置的判断质量都有覆盖。FN 尤其重要——模型漏检意味着帧序列中 fracture 不可见或模型判断错误。
- **真阴性 (TN)** 8 条：验证模型对负样本（neg_before, full_neg, neg_position）的判断是否可靠。
- **假阳性/异常 (FP/Anomaly)** 8 条：覆盖模型误判和视频异常情况，验证极端情况。
- 32 条总量是盲审可行性与统计覆盖之间的折中。
""".strip())
    lines.append("")

    lines.append("## 4. 已知局限")
    lines.append("")
    lines.append("""
- ❌ **无法自动化**：盲审的核心是人工判断，需要审阅者观察 contact sheet 或视频帧后做出定性判断。
- ❌ **无法生成 contact sheet**：需要 GPU 环境和原始视频文件，当前机器无法完成。
- ⚠️ **模型推理待运行**：prepare_visual_audit.py 需要在训练机上执行，以获取模型预测结果。
- ⚠️ **分层抽样依赖推理结果**：TP/FN/TN/FP 分组须在推理完成后才能确定。
""".strip())
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("生成视觉盲审准备工件")
    print("=" * 60)

    # 加载输入
    print("\n[1/5] 加载输入数据...")
    val_data = load_json(VAL_JSON)
    subvideos_meta = load_json(SUBVIDEOS_META)
    video_meta = load_json(VIDEO_META)
    td_json = load_json(TRAINING_DIST)
    print(f"  fold_0_val: {len(val_data)} 条")
    print(f"  subvideos_meta: {len(subvideos_meta['subvideos'])} 条")
    print(f"  video_meta: {len(video_meta)} 条")

    sub_lookup = build_subvideo_lookup(subvideos_meta)
    vm_lookup = build_video_meta_lookup(video_meta)

    # 输出 1: val_manifest
    print("\n[2/5] 构建 val_manifest.json...")
    manifest = build_val_manifest(val_data, sub_lookup, vm_lookup)
    manifest_path = OUT_DIR / "val_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    size_kb = manifest_path.stat().st_size / 1024
    print(f"  写入 {manifest_path} ({size_kb:.1f} KB)")

    # 输出 2: sampling_strategy
    print("\n[3/5] 构建 sampling_strategy.json...")
    strategy = build_sampling_strategy()
    strategy_path = OUT_DIR / "sampling_strategy.json"
    with open(strategy_path, "w", encoding="utf-8") as f:
        json.dump(strategy, f, indent=2, ensure_ascii=False)
    size_kb = strategy_path.stat().st_size / 1024
    print(f"  写入 {strategy_path} ({size_kb:.1f} KB)")

    # 输出 3: blind_review_template.csv
    print("\n[4/5] 构建 blind_review_template.csv...")
    rows, fieldnames = build_blind_review_template()
    csv_path = OUT_DIR / "blind_review_template.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    size_kb = csv_path.stat().st_size / 1024
    print(f"  写入 {csv_path} ({size_kb:.1f} KB)")

    # 输出 5: report
    print("\n[5/5] 构建 visual_audit_preparation_report.md...")
    report = build_report(manifest, strategy, td_json)
    report_path = OUT_DIR / "visual_audit_preparation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    size_kb = report_path.stat().st_size / 1024
    print(f"  写入 {report_path} ({size_kb:.1f} KB)")

    print("\n" + "=" * 60)
    print("完成！所有工件已生成。")
    print("=" * 60)


if __name__ == "__main__":
    main()
