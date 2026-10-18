# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-17
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/04_frames`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/visual_audit/val_manifest.json
#   - finetune/results/diagnostics/visual_audit/sampling_strategy.json
# 迁移已知影响：`Path(__file__).resolve().parents[4]` 原解析到仓库根，迁入 `pipeline/scripts/diagnostics/` 后层级少一层，已不指向仓库根。

#!/usr/bin/env python3
"""
在训练机上运行：对 val_manifest 做模型推理，分层抽样 32 条用于人工盲审。

用法：
    uv run python prepare_visual_audit.py \\
        --model-dir /path/to/model \\
        --val-manifest finetune/results/diagnostics/visual_audit/val_manifest.json \\
        [--sampling-strategy finetune/results/diagnostics/visual_audit/sampling_strategy.json] \\
        [--output-dir finetune/results/diagnostics/visual_audit] \\
        [--frames-dir /path/to/04_frames]

阶段一：推理 —— 对每条 val_manifest 记录运行模型，记录预测结果
阶段二：分层抽样 —— 按 TP/FN/TN/FP 分组，按 coverage_matrix 分层抽样 32 条
阶段三：输出 —— sample_manifest.json, manual_review_queue.csv, model_manifest.json

依赖：
    pip install einops torch transformers pillow
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parents[4]  # 从 finetune/results/diagnostics/visual_audit/ 到项目根
sys.path.insert(0, str(ROOT))

from finetune.validation.model_runtime import load_model, run_model_on_video
from finetune.validation.prompts import get_user_prompt, get_experiment_system_prompt

# ---------------------------------------------------------------------------
# 阶段一：推理
# ---------------------------------------------------------------------------
def _parse_prediction(raw_output: str) -> dict:
    """
    解析模型输出，提取四字段预测结果。

    支持格式：
    - "判断依据：...\n结果：{"..."has_fracture":...}"
    - 纯 JSON: {"has_fracture":...}
    - 带 markdown 代码块: ```json {...} ```

    返回 dict，保证包含 has_fracture, fracture_between, type, location 四个键。
    解析失败时 has_fracture=None。
    """
    result = {
        "has_fracture": None,
        "fracture_between": None,
        "type": None,
        "location": None,
    }

    if not raw_output or not raw_output.strip():
        return result

    content = raw_output.strip()

    # 1. 尝试提取 "结果：" 之后的内容
    if "结果：" in content:
        content = content.split("结果：", 1)[1].strip()

    # 2. 去掉 markdown 代码块标记
    content = re.sub(r'^```json\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    content = content.strip()

    # 3. 尝试解析 JSON
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # 尝试找第一个 { 到最后一个 }
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                parsed = json.loads(content[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                return result
        else:
            return result

    # 4. 提取字段
    if not isinstance(parsed, dict):
        return result

    # has_fracture
    hf = parsed.get("has_fracture")
    if isinstance(hf, bool):
        result["has_fracture"] = hf
    elif isinstance(hf, str):
        if hf.lower() in ("true", "是", "有", "yes"):
            result["has_fracture"] = True
        elif hf.lower() in ("false", "否", "没有", "no"):
            result["has_fracture"] = False

    # fracture_between
    fb = parsed.get("fracture_between")
    if isinstance(fb, list) and len(fb) == 2:
        result["fracture_between"] = fb
    elif isinstance(fb, str) and fb.lower() == "null":
        result["fracture_between"] = None

    # type
    tp = parsed.get("type")
    if isinstance(tp, str) and tp.strip():
        result["type"] = tp.strip()

    # location
    loc = parsed.get("location")
    if isinstance(loc, str) and loc.strip():
        result["location"] = loc.strip()
    elif loc is None or (isinstance(loc, str) and loc.lower() == "null"):
        result["location"] = None

    return result


def run_inference(
    model_dir: str,
    val_manifest: list[dict],
    frames_dir: str | None = None,
) -> list[dict]:
    """
    对 val_manifest 中每条样本运行真实模型推理。

    参数:
        model_dir: 合并后模型的目录路径
        val_manifest: 验证集清单（list of dict）
        frames_dir: 可选，预存帧图片目录（当前未使用，帧从视频文件实时加载）

    返回:
        list[dict]: 每条含 {record, prediction, is_correct, runtime_error}
    """
    print(f"  [加载] 模型: {model_dir}")
    processor, model = load_model(model_dir)
    print(f"  [加载] 模型加载完成")

    # 固定 prompt（与 run_evaluation.py 一致）
    system_prompt = get_experiment_system_prompt("medium")
    prompt_text = get_user_prompt(template_index=0)  # 使用第一个模板

    results = []
    total = len(val_manifest)
    for idx, record in enumerate(val_manifest):
        if (idx + 1) % 50 == 0:
            print(f"    ... 已处理 {idx + 1}/{total}")

        video_filename = record["subvideo_filename"]
        video_path = str(ROOT / "data" / "03_subvideos" / video_filename)

        runtime_error = None
        raw_output = ""

        try:
            raw_output = run_model_on_video(
                model, processor, video_path, prompt_text,
                system_prompt=system_prompt,
            )
        except FileNotFoundError as e:
            runtime_error = f"FileNotFoundError: {e}"
        except Exception as e:
            runtime_error = f"{type(e).__name__}: {e}"

        # 解析模型输出
        pred = _parse_prediction(raw_output)

        # 判断是否正确
        gt = record["has_fracture"]
        is_correct = (
            pred["has_fracture"] == gt
            if gt is not None
            else pred["has_fracture"] is None
        )

        results.append({
            "record": record,
            "prediction": pred,
            "is_correct": is_correct,
            "raw_output": raw_output,
            "runtime_error": runtime_error,
        })

    return results


def classify_group(gt_has_fracture, pred_has_fracture, is_correct):
    """将每条结果归入四个盲审分组之一。"""
    if gt_has_fracture is True and pred_has_fracture is True:
        return "true_positive"
    elif gt_has_fracture is True and pred_has_fracture is False:
        return "false_negative"
    elif gt_has_fracture is False and pred_has_fracture is False:
        return "true_negative"
    elif gt_has_fracture is None:
        return "false_positive_or_anomaly"
    else:
        # false_positive (gt=False, pred=True) 或 gt=None 的其他情况
        return "false_positive_or_anomaly"


# ---------------------------------------------------------------------------
# 阶段二：分层抽样
# ---------------------------------------------------------------------------
def stratified_sample(results, strategy):
    """
    从推理结果中按 TP/FN/TN/FP 分组，每组内做分层抽样。

    参数：
        results:  run_inference() 的输出
        strategy: 从 sampling_strategy.json 加载的策略

    返回：
        selected: list[dict] —— 选中的 32 条记录
    """
    # 按分组归类
    groups = defaultdict(list)
    for r in results:
        gt_hf = r["record"]["has_fracture"]
        pred_hf = r["prediction"]["has_fracture"]
        grp = classify_group(gt_hf, pred_hf, r["is_correct"])
        groups[grp].append(r)

    for g, items in groups.items():
        print(f"    {g}: {len(items)} 条可用")

    coverage = strategy["coverage_matrix"]
    selected = []

    for stratum in strategy["strata"]:
        group_name = stratum["group"]
        target = stratum["target"]
        must_cover = stratum["must_cover"]
        pool = groups.get(group_name, [])

        # 随机打乱
        random.shuffle(pool)

        chosen = []
        covered_sources = set()
        covered_types = set()
        covered_intervals = set()
        covered_locations = set()
        covered_crops = set()

        # 第一遍：优先选能补 coverage 的
        for r in pool:
            if len(chosen) >= target:
                break
            rec = r["record"]
            sv = rec["source_video"]
            fb = str(rec["fracture_between"]) if rec["fracture_between"] is not None else "null"
            loc = rec["location"] or "null"
            ct = rec["crop_type"]
            ft = rec["type"] or "null"

            # 检查是否带来新覆盖
            adds_coverage = False
            if "source_videos" in must_cover and sv not in covered_sources:
                adds_coverage = True
            if "fracture_types" in must_cover and ft not in covered_types and ft in coverage.get("fracture_types", []):
                adds_coverage = True
            if "intervals" in must_cover and fb not in covered_intervals and fb in coverage.get("intervals", []):
                adds_coverage = True
            if "locations" in must_cover and loc not in covered_locations and loc in coverage.get("locations", []):
                adds_coverage = True
            if "crop_types" in must_cover and ct not in covered_crops and ct in coverage.get("crop_types", []):
                adds_coverage = True

            if adds_coverage:
                chosen.append(r)
                covered_sources.add(sv)
                covered_types.add(ft)
                covered_intervals.add(fb)
                covered_locations.add(loc)
                covered_crops.add(ct)

        # 第二遍：剩余名额从 pool 中补
        remaining = [r for r in pool if r not in chosen]
        random.shuffle(remaining)
        for r in remaining:
            if len(chosen) >= target:
                break
            chosen.append(r)

        # 记录选中样本
        for r in chosen:
            r["group"] = group_name

        selected.extend(chosen)
        print(f"    {group_name}: 选中 {len(chosen)} 条 (目标 {target})")

    # 如果不足 32 条，从所有结果中补
    if len(selected) < strategy["total_target"]:
        all_ids = {id(r) for r in selected}
        remaining_all = [r for r in results if id(r) not in all_ids]
        random.shuffle(remaining_all)
        needed = strategy["total_target"] - len(selected)
        for r in remaining_all[:needed]:
            r["group"] = "extra"
            selected.append(r)
        print(f"    补充 {needed} 条至目标 {strategy['total_target']}")

    # 最终打乱
    random.shuffle(selected)
    print(f"    === 总计选中 {len(selected)} 条 ===")
    return selected


# ---------------------------------------------------------------------------
# 阶段三：输出
# ---------------------------------------------------------------------------
def write_sample_manifest(selected, output_dir):
    """写入 sample_manifest.json（32 条选中样本的完整信息）。"""
    manifest = []
    for s in selected:
        rec = s["record"].copy()
        rec["group"] = s["group"]
        rec["prediction"] = s["prediction"]
        rec["is_correct"] = s["is_correct"]
        # 给每条一个 sample_id
        rec["sample_id"] = f"audit_{s['record']['video_id']}"
        manifest.append(rec)

    path = output_dir / "sample_manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  → 写入 {path} ({len(manifest)} 条)")
    return manifest


def write_manual_review_queue(manifest, output_dir):
    """写入 manual_review_queue.csv（盲审表单，不含 ground truth）。"""
    fieldnames = [
        "sample_id",
        "subvideo_filename",
        "crop_type",
        "frame_count",
        "duration_bucket",
        "source_video",
        "group",
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

    path = output_dir / "manual_review_queue.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in manifest:
            row = {
                "sample_id": rec["sample_id"],
                "subvideo_filename": rec["subvideo_filename"],
                "crop_type": rec["crop_type"],
                "frame_count": rec["frame_count"],
                "duration_bucket": rec["duration_bucket"],
                "source_video": rec["source_video"],
                "group": rec["group"],
                # round1 & round2 留空供人工填写
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
            writer.writerow(row)
    print(f"  → 写入 {path}")


def write_model_manifest(output_dir):
    """写入 model_manifest.json（模型和运行时信息）。"""
    import platform
    import datetime

    manifest = {
        "generated_at": datetime.datetime.now().isoformat(),
        "model_info": {
            "name": "MiniCPM-V 2.6",
            "variant": "minicpmv4_5",
            "processor": "MiniCPMVProcessor",
            "max_frames": 8,
            "backend": "transformers",
            "precision": "bfloat16",
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "device": "cuda",
            "notes": "请在实际运行后更新 model_info 和设备信息",
        },
        "audit_info": {
            "total_samples_evaluated": None,  # 运行后填充
            "selected_samples": 32,
            "purpose": "阶段2: 实际视觉输入盲审",
        },
    }

    path = output_dir / "model_manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  → 写入 {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="视觉盲审准备：推理 + 分层抽样 + 输出"
    )
    parser.add_argument(
        "--model-dir",
        required=True,
        help="模型权重目录路径",
    )
    parser.add_argument(
        "--val-manifest",
        required=True,
        type=Path,
        help="val_manifest.json 路径",
    )
    parser.add_argument(
        "--sampling-strategy",
        type=Path,
        default=None,
        help="sampling_strategy.json 路径（默认与 val-manifest 同目录）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录（默认与 val-manifest 同目录）",
    )
    parser.add_argument(
        "--frames-dir",
        type=Path,
        default=None,
        help="帧图片目录（如 data/04_frames/），用于 contact sheet",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子（默认 42）",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    random.seed(args.seed)

    # 路径解析
    val_manifest_path = args.val_manifest.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else val_manifest_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.sampling_strategy:
        strategy_path = args.sampling_strategy.resolve()
    else:
        strategy_path = output_dir / "sampling_strategy.json"

    print("=" * 60)
    print("视觉盲审准备脚本")
    print("=" * 60)
    print(f"  模型目录:      {args.model_dir}")
    print(f"  val_manifest:  {val_manifest_path}")
    print(f"  抽样策略:      {strategy_path}")
    print(f"  输出目录:      {output_dir}")
    print(f"  帧目录:        {args.frames_dir or '未指定'}")

    # 加载输入
    print("\n[加载] val_manifest...")
    with open(val_manifest_path, "r", encoding="utf-8") as f:
        val_manifest = json.load(f)
    print(f"  {len(val_manifest)} 条")

    print("[加载] sampling strategy...")
    with open(strategy_path, "r", encoding="utf-8") as f:
        strategy = json.load(f)

    # 阶段一：推理
    print("\n[阶段一] 模型推理...")
    results = run_inference(args.model_dir, val_manifest, args.frames_dir)

    # 统计推理结果
    tp = sum(1 for r in results if classify_group(
        r["record"]["has_fracture"],
        r["prediction"]["has_fracture"],
        r["is_correct"],
    ) == "true_positive")
    fn = sum(1 for r in results if classify_group(
        r["record"]["has_fracture"],
        r["prediction"]["has_fracture"],
        r["is_correct"],
    ) == "false_negative")
    tn = sum(1 for r in results if classify_group(
        r["record"]["has_fracture"],
        r["prediction"]["has_fracture"],
        r["is_correct"],
    ) == "true_negative")
    fp = sum(1 for r in results if classify_group(
        r["record"]["has_fracture"],
        r["prediction"]["has_fracture"],
        r["is_correct"],
    ) == "false_positive_or_anomaly")

    correctly_classified = sum(1 for r in results if r["is_correct"])
    print(f"  TP={tp} FN={fn} TN={tn} FP/Anomaly={fp}")
    print(f"  正确率: {correctly_classified}/{len(results)} ({correctly_classified/len(results)*100:.1f}%)")

    # 阶段二：分层抽样
    print("\n[阶段二] 分层抽样...")
    selected = stratified_sample(results, strategy)

    # 阶段三：输出
    print("\n[阶段三] 输出...")
    manifest = write_sample_manifest(selected, output_dir)
    write_manual_review_queue(manifest, output_dir)
    write_model_manifest(output_dir)

    # 可选：生成 frames 目录（contact sheet）
    if args.frames_dir:
        print("\n[可选] 生成 contact sheet frames...")
        frames_output = output_dir / "frames"
        frames_output.mkdir(exist_ok=True)
        print(f"  contact sheet 将写入 {frames_output}")
        print("  (占位：请实现实际 contact sheet 生成逻辑)")

    print("\n" + "=" * 60)
    print("完成！盲审准备工件已生成。")
    print("=" * 60)


if __name__ == "__main__":
    main()
