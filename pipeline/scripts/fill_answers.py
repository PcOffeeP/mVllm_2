#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fill Answers Tool

功能: 读取 processed/ 目录下的 JSON 文件，根据 CSV 标注填入 assistant 的答案。
输出到 answered/ 目录，不覆盖原文件。

用法:
    python pipeline/scripts/fill_answers.py --batch-name stratified_3_fold_0
"""

import json
import re
import sys
from pathlib import Path

# ===================== Import checks =====================
try:
    import pandas as pd
except ImportError:
    sys.exit("需要 pandas 库，请运行: pip install pandas")

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml 库，请运行: pip install pyyaml")


# ===================== Load CSV data =====================
def load_csv_data(csv_path: Path) -> dict:
    """Load video fracture data from CSV. Returns {video_id: {time, mode}}"""
    df = pd.read_csv(csv_path)

    data = {}
    for _, row in df.iterrows():
        video_id = row["id"]
        fracture_time = row["断裂时间点"] if not pd.isna(row["断裂时间点"]) else None
        fracture_mode = row["断裂模式"] if not pd.isna(row["断裂模式"]) else None
        if pd.isna(video_id):
            continue
        if video_id:
            time_str = None
            if fracture_time:
                time_str = (
                    str(fracture_time).strip().replace(" s", "s").replace(" S", "s")
                )
                if not time_str:  # empty string guard
                    time_str = None
                elif not time_str.endswith("s"):
                    time_str = time_str + "s"
            data[video_id] = {
                "time": time_str,
                "mode": str(fracture_mode).strip() if fracture_mode else None,
            }
    return data


# ===================== Load question pool for classification =====================
def load_question_pool(yaml_path: Path) -> dict:
    """Load question pool and build question -> category mapping"""
    with yaml_path.open("r", encoding="utf-8") as f:
        pool_data = yaml.safe_load(f)

    q_to_cat = {}
    for cat_name, cat_config in pool_data.get("categories", {}).items():
        for q in cat_config.get("questions", []):
            q_to_cat[q.strip()] = cat_name
    return q_to_cat


def classify_question(question_text: str, q_to_cat: dict) -> str:
    """
    Classify a question into one of: zh_time, zh_mode, zh_both, en_time, en_mode, en_both
    First tries exact match from pool, then falls back to keyword detection.
    """
    clean_q = question_text.replace("<video>", "").strip()

    if clean_q in q_to_cat:
        return q_to_cat[clean_q]

    is_chinese = bool(re.search(r"[\u4e00-\u9fff]", clean_q))

    if is_chinese:
        has_time_kw = any(
            kw in clean_q
            for kw in [
                "时间", "时刻", "第几秒", "哪一秒", "啥时候", "何时",
                "时间点", "时间戳", "时间轴", "几秒", "拉断的具体",
                "只输出断裂时间",
            ]
        )
        has_mode_kw = any(
            kw in clean_q
            for kw in [
                "模式", "方式", "类型", "形式", "形态", "特征",
                "韧性", "脆性", "破坏模式", "断裂类型", "怎么断",
                "如何分类", "哪类", "哪一种", "破坏方式", "术语",
            ]
        )

        if has_time_kw and has_mode_kw:
            return "zh_both"
        elif has_time_kw:
            return "zh_time"
        elif has_mode_kw:
            return "zh_mode"
        else:
            if "断裂" in clean_q and ("何时" in clean_q or "时" in clean_q):
                return "zh_time"
            return "zh_both"
    else:
        has_time_kw = any(
            kw in clean_q.lower()
            for kw in [
                "when", "time", "second", "timestamp", "moment",
                "onset", "initiate",
            ]
        )
        has_mode_kw = any(
            kw in clean_q.lower()
            for kw in [
                "mode", "type", "pattern", "style", "how",
                "ductile", "brittle", "classify", "categorize",
                "describe", "failure mode", "look like", "what failure",
            ]
        )

        if has_time_kw and has_mode_kw:
            return "en_both"
        elif has_time_kw:
            return "en_time"
        elif has_mode_kw:
            return "en_mode"
        else:
            return "en_both"


# ===================== Fracture mode translation =====================
FRACTURE_MODE_EN = {
    "韧性断裂": "ductile fracture",
    "脆性断裂": "brittle fracture",
    "半脆半韧断裂": "brittle-ductile fracture",
    "界面脱粘": "interface tear-off",
    "齐根断裂": "grip-end fracture",
    "爆炸性断裂": "explosive fracture",
    "界面脱粘、齐根断裂": "interface tear-off, grip-end fracture",
    "未断裂": "no fracture",
    "未夹紧": "not clamped",
    "视频异常": "video anomaly",
}


def _generate_special_answer(
    category: str, special_value: str, mode_val: str, is_chinese: bool
) -> str:
    """
    Generate answer for special fracture_time values:
    未断裂, 未夹紧, 视频异常, 不可分辨

    Rules:
    ┌──────────────┬───────────────────────┬───────────────────────┬──────────────────────────────────────┐
    │ fracture_time│ time 类               │ mode 类               │ both 类                              │
    ├──────────────┼───────────────────────┼───────────────────────┼──────────────────────────────────────┤
    │ 未断裂       │ {"time": "未发生断裂"} │ 正常答模式            │ {"type": mode, "time": "未发生断裂"}  │
    │ 未夹紧       │ {"time": "未发生断裂"} │ 正常答模式            │ {"type": mode, "time": "未发生断裂"}  │
    │ 视频异常     │ {"time": 异常文本}     │ {"type": 异常文本}    │ {"type": 异常文本, "time": 异常文本}  │
    │ 不可分辨     │ {"time": 不可分辨文本} │ 正常答模式            │ {"type": mode, "time": 不可分辨文本}  │
    └──────────────┴───────────────────────┴───────────────────────┴──────────────────────────────────────┘
    """
    if is_chinese:
        time_map = {
            "未断裂": "未发生断裂",
            "未夹紧": "未发生断裂",
            "视频异常": "视频异常，无法判断",
            "不可分辨": "断裂时间不可分辨",
        }
        anomaly_text = "视频异常，无法判断"
    else:
        time_map = {
            "未断裂": "no fracture occurred",
            "未夹紧": "no fracture occurred",
            "视频异常": "video anomaly, unable to determine",
            "不可分辨": "fracture time indistinguishable",
        }
        anomaly_text = "video anomaly, unable to determine"

    time_answer = time_map.get(special_value, special_value)

    if category in ("zh_time", "en_time"):
        return json.dumps({"time": time_answer}, ensure_ascii=False, allow_nan=False)

    elif category in ("zh_mode", "en_mode"):
        if special_value == "视频异常":
            return json.dumps({"type": anomaly_text}, ensure_ascii=False, allow_nan=False)
        else:
            answer = {}
            if mode_val:
                answer["type"] = mode_val
            return json.dumps(answer, ensure_ascii=False, allow_nan=False)

    elif category in ("zh_both", "en_both"):
        answer = {"time": time_answer}
        if special_value == "视频异常":
            answer["type"] = anomaly_text
        elif mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False, allow_nan=False)

    # Fallback
    answer = {"time": time_answer}
    if special_value == "视频异常":
        answer["type"] = anomaly_text
    elif mode_val:
        answer["type"] = mode_val
    return json.dumps(answer, ensure_ascii=False, allow_nan=False)


def generate_answer(
    category: str, fracture_time: str, fracture_mode: str, question_text: str
) -> str:
    """
    Generate the assistant answer JSON string based on category.

    Rules:
    - Only include fields that have values; omit empty fields entirely
    - For videos with no fracture time: always return only {"type": "..."}
    - Time format: "38.65s" (no space)
    - English mode: all lowercase
    - Special text values (未断裂/未夹紧/视频异常/不可分辨) handled via _generate_special_answer
    """
    is_chinese = category.startswith("zh_")

    if is_chinese:
        mode_val = fracture_mode if fracture_mode else None
    else:
        mode_val = (
            FRACTURE_MODE_EN.get(fracture_mode, fracture_mode)
            if fracture_mode
            else None
        )

    # If no fracture time exists, always return only type
    if not fracture_time:
        answer = {}
        if mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False, allow_nan=False)

    # Detect non-numeric fracture_time (e.g. "未断裂s" from load_csv_data)
    # Normal times: "38.65s", "168.5s"; Special: "未断裂s", "视频异常s"
    is_normal_time = bool(re.match(r'^\d+\.?\d*s$', fracture_time))

    if not is_normal_time:
        # load_csv_data appends 's' to text values, strip it back
        special_value = fracture_time[:-1].strip()  # "未断裂s" -> "未断裂"
        if not special_value:  # empty after stripping (empty cell guard)
            answer = {}
            if mode_val:
                answer["type"] = mode_val
            return json.dumps(answer, ensure_ascii=False, allow_nan=False)
        return _generate_special_answer(category, special_value, mode_val, is_chinese)

    if category in ("zh_time", "en_time"):
        return json.dumps({"time": fracture_time}, ensure_ascii=False, allow_nan=False)

    elif category in ("zh_mode", "en_mode"):
        answer = {}
        if mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False, allow_nan=False)

    elif category in ("zh_both", "en_both"):
        answer = {"time": fracture_time}
        if mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False, allow_nan=False)

    # Fallback
    answer = {}
    if fracture_time:
        answer["time"] = fracture_time
    if mode_val:
        answer["type"] = mode_val
    return json.dumps(answer, ensure_ascii=False, allow_nan=False)


# ===================== Main Processing =====================
def process_batch(batch_name: str, base_dir: Path, csv_path: Path, yaml_path: Path):
    """Process a single batch: read from processed/, write to answered/"""

    processed_dir = base_dir / batch_name / "processed"
    answered_dir = base_dir / batch_name / "answered"

    if not processed_dir.exists():
        print(f"错误: processed 目录不存在: {processed_dir}")
        print("请先运行 generate_questions.py 生成 processed 数据")
        sys.exit(1)

    # Load data sources
    video_data = load_csv_data(csv_path)
    q_to_cat = load_question_pool(yaml_path)

    print(f"加载 {len(video_data)} 个视频标注")
    print(f"加载 {len(q_to_cat)} 个问题分类规则")

    json_files = sorted(processed_dir.glob("*.json"))
    if not json_files:
        print(f"警告: {processed_dir} 中没有 JSON 文件")
        return

    print(f"找到 {len(json_files)} 个 JSON 文件")

    # Create output directory
    answered_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    skipped = 0

    for jf in json_files:
        video_id = jf.stem  # e.g. "video_0018"

        if video_id not in video_data:
            print(f"  警告: {video_id} 不在 CSV 中，跳过")
            skipped += 1
            continue

        vd = video_data[video_id]
        fracture_time = vd["time"]
        fracture_mode = vd["mode"]

        # Read JSON from processed/
        with jf.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Process each QA pair
        for dialog in data:
            messages = dialog.get("messages", [])
            user_msg = None
            assistant_msg = None

            for msg in messages:
                if msg["role"] == "user":
                    user_msg = msg
                elif msg["role"] == "assistant":
                    assistant_msg = msg

            if user_msg and assistant_msg:
                question = user_msg["content"]
                category = classify_question(question, q_to_cat)
                answer = generate_answer(
                    category, fracture_time, fracture_mode, question
                )
                assistant_msg["content"] = answer

        # Write to answered/
        output_path = answered_dir / jf.name
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4, allow_nan=False)

        success += 1

    print(f"\n完成! 处理: {success}/{len(json_files)}, 跳过: {skipped}")
    print(f"输出: {answered_dir}")


if __name__ == "__main__":
    import argparse

    project_root = Path(__file__).resolve().parent.parent.parent

    parser = argparse.ArgumentParser(
        description="Fill Answers: 从 CSV 标注填入 assistant 答案"
    )
    parser.add_argument(
        "--batch-name", "-b",
        type=str,
        required=True,
        help="批次名称（必填）",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=project_root / "data" / "02_annotations" / "all_videos_tag.csv",
        help="标注 CSV 文件路径",
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=project_root / "pipeline" / "config" / "question_pool.yaml",
        help="问题池 YAML 配置文件路径",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=project_root / "pipeline" / "batches",
        help="批次基目录",
    )

    args = parser.parse_args()

    process_batch(
        batch_name=args.batch_name,
        base_dir=args.base_dir,
        csv_path=args.csv,
        yaml_path=args.config,
    )
