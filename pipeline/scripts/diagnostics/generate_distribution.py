# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-17
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/06_merged/fold_0_train.json`、`data/06_merged/fold_0_val.json`、`data/07_metadata/subvideos_meta.label_reviewed.json`、`data/07_metadata/video_meta.json`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/data_audit

#!/usr/bin/env python3
"""
数据审计脚本：生成 training_distribution.json
涵盖：样本级统计、源视频级统计、裁剪方式与标签相关性、区间标签检查
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

# ── 路径配置 ──────────────────────────────────────────────────────────
BASE = Path("/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2_diagnostics")
TRAIN_PATH  = BASE / "data/06_merged/fold_0_train.json"
VAL_PATH    = BASE / "data/06_merged/fold_0_val.json"
META_PATH   = BASE / "data/07_metadata/subvideos_meta.label_reviewed.json"
VIDEO_META  = BASE / "data/07_metadata/video_meta.json"
OUTPUT_DIR  = BASE / "finetune/results/diagnostics/data_audit"
OUTPUT_PATH = OUTPUT_DIR / "training_distribution.json"


# ── 载入数据 ──────────────────────────────────────────────────────────
train_raw = json.loads(TRAIN_PATH.read_text())
val_raw   = json.loads(VAL_PATH.read_text())
meta_raw  = json.loads(META_PATH.read_text())
vmeta_raw = json.loads(VIDEO_META.read_text())

video_lookup = {v["video_id"]: v for v in vmeta_raw}

# 构建 meta 查找表：key = 文件名（去掉路径前缀）
meta_lookup = {}
for sv in meta_raw["subvideos"]:
    key = Path(sv["video_path"]).name
    meta_lookup[key] = sv


# ── 辅助函数 ──────────────────────────────────────────────────────────
def parse_label(sample):
    """从 fold 样本中解析 ground-truth 标签"""
    content = json.loads(sample["messages"][-1]["content"])
    return content


def get_meta_info(fname):
    """返回 meta 条目，找不到返回 None"""
    return meta_lookup.get(fname)


def safe_bool(v):
    """把 has_fracture 转为 True/False/None"""
    if v is True or (isinstance(v, str) and v.lower() == "true"):
        return True
    if v is False or (isinstance(v, str) and v.lower() == "false"):
        return False
    return None


def fmt_fracture_between(fb):
    """将 fracture_between 转为可哈希的字符串 key"""
    if fb is None or not isinstance(fb, list) or len(fb) < 2:
        return "null"
    return f"[{fb[0]},{fb[1]}]"


def get_duration_bucket(duration):
    """将 duration（秒）转为分桶名"""
    if duration is None:
        return "unknown"
    if duration < 5:
        return "<5s"
    elif duration < 15:
        return "5-15s"
    elif duration < 30:
        return "15-30s"
    elif duration < 60:
        return "30-60s"
    else:
        return ">60s"


def summarize_prompt(user_content):
    """用前 20 个字符作为 prompt 模板标识"""
    return user_content[:20]


# ── 1.1 样本级统计 ──────────────────────────────────────────────────
def build_sample_stats(split_data, split_name):
    total = len(split_data)

    has_fracture_counts = {"true": 0, "false": 0, "null": 0}
    type_dist = Counter()
    fracture_between_dist = Counter()
    location_dist = Counter()
    crop_type_dist = Counter()
    frame_count_dist = Counter()
    prompt_template_dist = Counter()

    for sample in split_data:
        label = parse_label(sample)
        fname = Path(sample["videos"][0]).name
        meta = get_meta_info(fname)

        # has_fracture
        hf = safe_bool(label.get("has_fracture"))
        if hf is True:
            has_fracture_counts["true"] += 1
        elif hf is False:
            has_fracture_counts["false"] += 1
        else:
            has_fracture_counts["null"] += 1

        # type
        t = label.get("type", "null")
        if t is None:
            t = "null"
        type_dist[t] += 1

        # fracture_between
        fb = label.get("fracture_between")
        fb_key = fmt_fracture_between(fb)
        fracture_between_dist[fb_key] += 1

        # location
        loc = label.get("location")
        loc_key = "null" if loc is None else str(loc)
        location_dist[loc_key] += 1

        # crop_type (from meta)
        if meta:
            ct = meta.get("crop_type", "unknown")
            crop_type_dist[ct] += 1
            # frame count
            mapping = meta.get("actual_frame_mapping", [])
            frame_count_dist[len(mapping)] += 1
        else:
            crop_type_dist["not_in_label_reviewed_meta"] += 1
            frame_count_dist["unknown"] = frame_count_dist.get("unknown", 0) + 1

        # prompt template
        user_msg = sample["messages"][1]["content"]
        prompt_template_dist[summarize_prompt(user_msg)] += 1

    # positive/negative ratio
    pos = has_fracture_counts["true"]
    neg = has_fracture_counts["false"]
    ratio = round(pos / neg, 4) if neg > 0 else float("inf")

    return {
        "total": total,
        "has_fracture": has_fracture_counts,
        "type_distribution": dict(type_dist.most_common()),
        "fracture_between_distribution": dict(fracture_between_dist.most_common()),
        "location_distribution": dict(location_dist.most_common()),
        "crop_type_distribution": dict(crop_type_dist.most_common()),
        "frame_count_distribution": {
            str(k): v for k, v in sorted(frame_count_dist.items(), key=lambda x: (isinstance(x[0], int), x[0]))
        },
        "prompt_templates": dict(prompt_template_dist.most_common()),
        "positive_negative_ratio": ratio,
    }


# ── 1.2 源视频级统计 ──────────────────────────────────────────────────
def build_source_video_stats(split_data):
    # type_source_diversity: 每个 type 的 unique sources / total samples / sources list
    type_sources = defaultdict(lambda: {"sources": set(), "total": 0})
    # crop_type 级的 source 多样性
    crop_sources = defaultdict(lambda: {"sources": set(), "total": 0})
    # source_contribution: 每个 source 的样本数/正负/类型/裁剪方式
    source_contrib = defaultdict(lambda: {
        "total_samples": 0, "positive": 0, "negative": 0,
        "types": Counter(), "crop_types": Counter()
    })

    for sample in split_data:
        label = parse_label(sample)
        fname = Path(sample["videos"][0]).name
        meta = get_meta_info(fname)

        if meta is None:
            continue

        source_video = meta.get("source_video", "unknown")
        crop_type = meta.get("crop_type", "unknown")
        t = label.get("type", "null") or "null"
        hf = safe_bool(label.get("has_fracture"))

        # type_source_diversity
        type_sources[t]["sources"].add(source_video)
        type_sources[t]["total"] += 1

        # crop_type source diversity
        crop_sources[crop_type]["sources"].add(source_video)
        crop_sources[crop_type]["total"] += 1

        # source_contribution
        source_contrib[source_video]["total_samples"] += 1
        if hf is True:
            source_contrib[source_video]["positive"] += 1
        elif hf is False:
            source_contrib[source_video]["negative"] += 1
        source_contrib[source_video]["types"][t] += 1
        source_contrib[source_video]["crop_types"][crop_type] += 1

    # 格式化 type_source_diversity
    type_source_diversity = {}
    for t, info in sorted(type_sources.items(), key=lambda x: -x[1]["total"]):
        type_source_diversity[t] = {
            "unique_sources": len(info["sources"]),
            "total_samples": info["total"],
            "sources": sorted(info["sources"]),
        }

    # 格式化 crop_type diversity
    crop_type_div = {}
    for ct, info in sorted(crop_sources.items(), key=lambda x: -x[1]["total"]):
        crop_type_div[ct] = {
            "unique_sources": len(info["sources"]),
            "total_samples": info["total"],
            "sources": sorted(info["sources"]),
        }

    # 格式化 source_contribution
    source_contribution = {}
    for sv, info in sorted(source_contrib.items(), key=lambda x: -x[1]["total_samples"]):
        source_contribution[sv] = {
            "total_samples": info["total_samples"],
            "positive": info["positive"],
            "negative": info["negative"],
            "types": dict(info["types"].most_common()),
            "crop_types": dict(info["crop_types"].most_common()),
        }

    # ── 告警 ──
    alerts = []
    for t, info in type_source_diversity.items():
        if info["unique_sources"] == 1:
            alerts.append(f"type '{t}': 只有 1 个独立源，无法可靠泛化")
        elif info["unique_sources"] <= 4:
            alerts.append(f"type '{t}': 只有 {info['unique_sources']} 个独立源")

    # 检查单个 source 占某个 type 的比例是否 > 30%
    for sv, info in source_contribution.items():
        for t, cnt in info["types"].items():
            total_for_type = type_source_diversity.get(t, {}).get("total_samples", 1)
            pct = round(cnt / total_for_type * 100, 1)
            if pct > 30:
                alerts.append(
                    f"{sv} 占 type '{t}' 的 {pct}%，超过 30% 警戒线"
                )

    # source_macro_imbalance
    sources_sorted = sorted(source_contrib.items(), key=lambda x: -x[1]["total_samples"])
    most_sv = sources_sorted[0][0] if sources_sorted else "N/A"
    most_cnt = sources_sorted[0][1]["total_samples"] if sources_sorted else 0
    least_sv = sources_sorted[-1][0] if sources_sorted else "N/A"
    least_cnt = sources_sorted[-1][1]["total_samples"] if sources_sorted else 0
    ratio_max_min = round(most_cnt / least_cnt, 2) if least_cnt > 0 else float("inf")

    return {
        "type_source_diversity": type_source_diversity,
        "crop_type": crop_type_div,
        "source_contribution": source_contribution,
        "alerts": alerts,
        "source_macro_imbalance": {
            "most_contributing_source": f"{most_sv}: {most_cnt} samples",
            "least_contributing_source": f"{least_sv}: {least_cnt} samples",
            "ratio_max_min": ratio_max_min,
        },
    }


# ── 1.3 裁剪方式与标签相关性 ──────────────────────────────────────────
def build_crop_label_correlation(split_data):
    # crop_type vs has_fracture
    ct_hf = defaultdict(lambda: {"positive": 0, "negative": 0, "total": 0})
    # crop_type vs fracture_between
    ct_fb = defaultdict(lambda: defaultdict(int))
    # video_duration vs has_fracture
    dur_hf = defaultdict(lambda: {"positive": 0, "negative": 0, "total": 0})

    for sample in split_data:
        label = parse_label(sample)
        fname = Path(sample["videos"][0]).name
        meta = get_meta_info(fname)

        if meta is None:
            continue

        crop_type = meta.get("crop_type", "unknown")
        hf = safe_bool(label.get("has_fracture"))
        fb = label.get("fracture_between")

        # ── crop_type vs has_fracture ──
        ct_hf[crop_type]["total"] += 1
        if hf is True:
            ct_hf[crop_type]["positive"] += 1
        elif hf is False:
            ct_hf[crop_type]["negative"] += 1

        # ── crop_type vs fracture_between ──
        ct_fb[crop_type][fmt_fracture_between(fb)] += 1

        # ── video_duration vs has_fracture ──
        source_video = meta.get("source_video", "")
        vmeta = video_lookup.get(source_video)
        if vmeta:
            dur = vmeta.get("duration")
            bucket = get_duration_bucket(dur)
            dur_hf[bucket]["total"] += 1
            if hf is True:
                dur_hf[bucket]["positive"] += 1
            elif hf is False:
                dur_hf[bucket]["negative"] += 1

    # 格式化 crop_type_vs_has_fracture
    crop_type_vs_has_fracture = {}
    for ct in sorted(ct_hf.keys()):
        info = ct_hf[ct]
        total = info["total"]
        pos_ratio = round(info["positive"] / total, 4) if total > 0 else 0.0
        crop_type_vs_has_fracture[ct] = {
            "positive": info["positive"],
            "negative": info["negative"],
            "total": total,
            "positive_ratio": pos_ratio,
        }

    # 格式化 crop_type_vs_fracture_between
    crop_type_vs_fracture_between = {}
    for ct in sorted(ct_fb.keys()):
        crop_type_vs_fracture_between[ct] = dict(
            sorted(ct_fb[ct].items(), key=lambda x: -x[1])
        )

    # 格式化 video_duration_vs_has_fracture
    video_duration_vs_has_fracture = {}
    for bucket in ["<5s", "5-15s", "15-30s", "30-60s", ">60s", "unknown"]:
        if bucket in dur_hf:
            video_duration_vs_has_fracture[bucket] = {
                "positive": dur_hf[bucket]["positive"],
                "negative": dur_hf[bucket]["negative"],
                "total": dur_hf[bucket]["total"],
            }

    # ── 告警 ──
    alerts = []
    for ct, info in crop_type_vs_has_fracture.items():
        if info["positive_ratio"] == 0.0 and info["total"] > 0:
            alerts.append(
                f"{ct} -> 100% 负样本：模型可能学习'裁剪位置={ct}=未断裂'捷径"
            )
        elif info["positive_ratio"] == 1.0 and info["total"] > 0:
            alerts.append(
                f"{ct} -> 100% 正样本：模型可能学习'裁剪位置={ct}=断裂'捷径"
            )
        elif info["positive_ratio"] >= 0.9 and info["total"] > 0:
            alerts.append(
                f"{ct} -> {info['positive_ratio']*100:.0f}% 正样本：模型可能学习'裁剪位置={ct}=断裂'捷径"
            )
        elif info["positive_ratio"] <= 0.1 and info["total"] > 0:
            alerts.append(
                f"{ct} -> {info['positive_ratio']*100:.0f}% 负样本：模型可能学习'裁剪位置={ct}=未断裂'捷径"
            )

    return {
        "crop_type_vs_has_fracture": crop_type_vs_has_fracture,
        "crop_type_vs_fracture_between": crop_type_vs_fracture_between,
        "video_duration_vs_has_fracture": video_duration_vs_has_fracture,
        "alerts": alerts,
    }


# ── 1.4 区间标签检查 ──────────────────────────────────────────────────
def build_interval_label_check(split_data):
    # 只检查正样本（有 fracture_between 的）
    interval_dist = Counter()
    interval_sources = defaultdict(lambda: {"sources": set()})
    interval_vs_crop = defaultdict(lambda: Counter())
    interval_vs_duration = defaultdict(lambda: Counter())
    interval_vs_frame_count = defaultdict(lambda: Counter())

    for sample in split_data:
        label = parse_label(sample)
        fname = Path(sample["videos"][0]).name
        meta = get_meta_info(fname)

        if meta is None:
            continue

        fb = label.get("fracture_between")
        if fb is None or not isinstance(fb, list) or len(fb) < 2:
            continue

        interval_key = fmt_fracture_between(fb)
        source_video = meta.get("source_video", "unknown")
        crop_type = meta.get("crop_type", "unknown")
        frame_count = len(meta.get("actual_frame_mapping", []))
        vmeta = video_lookup.get(source_video)

        interval_dist[interval_key] += 1
        interval_sources[interval_key]["sources"].add(source_video)
        interval_vs_crop[interval_key][crop_type] += 1

        if vmeta:
            dur = vmeta.get("duration")
            bucket = get_duration_bucket(dur)
            interval_vs_duration[interval_key][bucket] += 1

        interval_vs_frame_count[interval_key][str(frame_count)] += 1

    # 格式化
    def sort_keys(d):
        """对 [a,b] 格式的 key 排序"""
        def sort_key(k):
            try:
                parts = k.strip("[]").split(",")
                return (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                return (999, 999)
        return dict(sorted(d.items(), key=lambda x: sort_key(x[0])))

    interval_distribution = sort_keys(dict(interval_dist))
    interval_source_diversity = sort_keys({
        k: {"unique_sources": len(v["sources"]), "sources": sorted(v["sources"])}
        for k, v in interval_sources.items()
    })
    interval_vs_crop_type = sort_keys({
        k: dict(v.most_common()) for k, v in interval_vs_crop.items()
    })
    interval_vs_duration_dict = sort_keys({
        k: dict(v.most_common()) for k, v in interval_vs_duration.items()
    })
    interval_vs_frame_count_dict = sort_keys({
        k: dict(v.most_common()) for k, v in interval_vs_frame_count.items()
    })

    # ── 告警 ──
    alerts = []
    total_pos = sum(interval_dist.values())
    total_intervals = len(interval_dist)

    for interval_key, count in interval_distribution.items():
        crop_info = interval_vs_crop_type.get(interval_key, {})
        dominant_crop = max(crop_info, key=crop_info.get) if crop_info else "N/A"
        dominant_crop_pct = round(crop_info[dominant_crop] / count * 100, 1) if crop_info else 0

        # Check if dominated by single crop type
        if dominant_crop_pct > 80 and len(crop_info) >= 2:
            alerts.append(
                f"{interval_key} 的 {dominant_crop_pct}% 样本来自 {dominant_crop}，"
                f"区间与裁剪方式强相关"
            )

        # Check duration concentration
        dur_info = interval_vs_duration.get(interval_key, {})
        if dur_info:
            dominant_dur = max(dur_info, key=dur_info.get)
            dominant_dur_pct = round(dur_info[dominant_dur] / count * 100, 1)
            if dominant_dur_pct > 70:
                alerts.append(
                    f"{interval_key} 的 {dominant_dur_pct}% 样本集中在 {dominant_dur} 视频"
                )

    return {
        "interval_distribution": interval_distribution,
        "interval_source_diversity": interval_source_diversity,
        "interval_vs_crop_type": interval_vs_crop_type,
        "interval_vs_duration": interval_vs_duration_dict,
        "interval_vs_frame_count": interval_vs_frame_count_dict,
        "alerts": alerts,
    }


# ── 主流程 ────────────────────────────────────────────────────────────
def main():
    output = {}

    # 1.1 样本级统计
    print("[1/4] 构建样本级统计...")
    output["sample_stats"] = {
        "train": build_sample_stats(train_raw, "train"),
        "val": build_sample_stats(val_raw, "val"),
    }

    # 1.2 源视频级统计（基于 train+val 全量）
    print("[2/4] 构建源视频级统计...")
    all_data = train_raw + val_raw
    output["source_video_stats"] = build_source_video_stats(all_data)

    # 1.3 裁剪方式与标签相关性（基于 train+val 全量）
    print("[3/4] 构建裁剪方式与标签相关性...")
    output["crop_label_correlation"] = build_crop_label_correlation(all_data)

    # 1.4 区间标签检查（基于 train+val 全量）
    print("[4/4] 构建区间标签检查...")
    output["interval_label_check"] = build_interval_label_check(all_data)

    # 写入输出
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✓ 已写入: {OUTPUT_PATH}")
    print(f"  文件大小: {OUTPUT_PATH.stat().st_size / 1024:.1f} KB")

    # 终端输出层级预览
    print("\n" + "=" * 60)
    print("JSON 顶层 key 预览")
    print("=" * 60)
    _preview(output, indent=0, max_items=5, depth=0, max_depth=3)


def _preview(obj, indent=0, max_items=5, depth=0, max_depth=3):
    prefix = "  " * indent
    if depth > max_depth:
        print(f"{prefix}  ...")
        return
    if isinstance(obj, dict):
        keys = list(obj.keys())
        for i, k in enumerate(keys):
            if i >= max_items and len(keys) > max_items:
                print(f"{prefix}  ... ({len(keys) - max_items} more keys)")
                break
            v = obj[k]
            if isinstance(v, (dict, list)):
                if isinstance(v, dict) and len(v) <= 3:
                    print(f"{prefix}  {k}: {json.dumps(v, ensure_ascii=False)}")
                else:
                    type_label = type(v).__name__
                    len_label = f"({len(v)} items)"
                    print(f"{prefix}  {k}: {type_label} {len_label}")
                    _preview(v, indent + 1, max_items, depth + 1, max_depth)
            else:
                print(f"{prefix}  {k}: {v}")
    elif isinstance(obj, list):
        if len(obj) <= 5 and all(not isinstance(x, (dict, list)) for x in obj):
            print(f"{prefix}  {obj}")
        else:
            print(f"{prefix}  List({len(obj)} items)")
            if obj and depth < max_depth:
                _preview(obj[0], indent + 1, max_items, depth + 1, max_depth)


if __name__ == "__main__":
    main()
