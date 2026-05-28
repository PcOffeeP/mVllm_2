#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fill Answers Tool

Function: Read fracture time/mode from xlsx, classify each question in processed JSONs,
and fill in the assistant's answer accordingly.

Rules (aligned with stratified_3_fold_0 reference):
- 问时刻回答时刻，问时间回答时间 (match the question's phrasing)
- 二者都问需要都回答 (if both asked, answer both)
- 中文提问中文回答，英文提问英文回答
- 空字段直接删除 (omit empty fields from JSON)
- 时间格式无空格 "38.65s"
- 英文模式全小写 "ductile fracture"
- 无时间的视频(未断裂/视频异常等) 只返回 {"type": "..."}, 省略 time 字段
"""

import json
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("Installing openpyxl...")
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl

try:
    import yaml
except ImportError:
    print("Installing pyyaml...")
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
    import yaml


# ===================== Load xlsx data =====================
def load_xlsx_data(xlsx_path: Path) -> dict:
    """Load video fracture data from xlsx. Returns {video_id: {time, mode}}"""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb["Sheet1"]

    data = {}
    for row in ws.iter_rows(min_row=2, values_only=True):  # skip header
        video_id = row[0]  # e.g. "video_0001"
        fracture_time = row[1] if row[1] else None  # e.g. "38.65 s" or None
        fracture_mode = row[2] if row[2] else None  # e.g. "韧性断裂" or None
        if video_id:
            # Normalize time: "38.65 s" -> "38.65s" (remove space before 's')
            time_str = None
            if fracture_time:
                time_str = (
                    str(fracture_time).strip().replace(" s", "s").replace(" S", "s")
                )
                # Ensure it ends with 's'
                if not time_str.endswith("s"):
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
    # Strip the <video> prefix
    clean_q = question_text.replace("<video>", "").strip()

    # Try exact match from pool
    if clean_q in q_to_cat:
        return q_to_cat[clean_q]

    # Fallback: detect language and type by keywords
    is_chinese = bool(re.search(r"[\u4e00-\u9fff]", clean_q))

    if is_chinese:
        has_time_kw = any(
            kw in clean_q
            for kw in [
                "时间",
                "时刻",
                "第几秒",
                "哪一秒",
                "啥时候",
                "何时",
                "时间点",
                "时间戳",
                "时间轴",
                "几秒",
                "拉断的具体",
                "只输出断裂时间",
            ]
        )
        has_mode_kw = any(
            kw in clean_q
            for kw in [
                "模式",
                "方式",
                "类型",
                "形式",
                "形态",
                "特征",
                "韧性",
                "脆性",
                "破坏模式",
                "断裂类型",
                "怎么断",
                "如何分类",
                "哪类",
                "哪一种",
                "破坏方式",
                "术语",
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
            return "zh_both"  # safe fallback
    else:
        has_time_kw = any(
            kw in clean_q.lower()
            for kw in [
                "when",
                "time",
                "second",
                "timestamp",
                "moment",
                "onset",
                "initiate",
            ]
        )
        has_mode_kw = any(
            kw in clean_q.lower()
            for kw in [
                "mode",
                "type",
                "pattern",
                "style",
                "how",
                "ductile",
                "brittle",
                "classify",
                "categorize",
                "describe",
                "failure mode",
                "look like",
                "what failure",
            ]
        )

        if has_time_kw and has_mode_kw:
            return "en_both"
        elif has_time_kw:
            return "en_time"
        elif has_mode_kw:
            return "en_mode"
        else:
            return "en_both"  # safe fallback


# ===================== Fracture mode translation =====================
# Aligned with stratified_3_fold_0 reference (all lowercase English)
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


def generate_answer(
    category: str, fracture_time: str, fracture_mode: str, question_text: str
) -> str:
    """
    Generate the assistant answer JSON string based on category.

    Rules (from fold_0 reference):
    - Only include fields that have values; omit empty fields entirely
    - For videos with no fracture time (未断裂, 视频异常, etc.):
      always return only {"type": "..."} regardless of question type
    - Time format: "38.65s" (no space)
    - English mode: all lowercase
    """
    is_chinese = category.startswith("zh_")

    # Determine mode value in the correct language
    if is_chinese:
        mode_val = fracture_mode if fracture_mode else None
    else:
        mode_val = (
            FRACTURE_MODE_EN.get(fracture_mode, fracture_mode)
            if fracture_mode
            else None
        )

    # If no fracture time exists, always return only type (per fold_0 reference)
    # This covers 未断裂, 未夹紧, 视频异常, and any video with empty time
    if not fracture_time:
        answer = {}
        if mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False)

    # Video HAS fracture time — build answer based on question category
    if category in ("zh_time", "en_time"):
        # Time-only question: only include time
        return json.dumps({"time": fracture_time}, ensure_ascii=False)

    elif category in ("zh_mode", "en_mode"):
        # Mode-only question: only include type
        answer = {}
        if mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False)

    elif category in ("zh_both", "en_both"):
        # Both: include time and type
        answer = {"time": fracture_time}
        if mode_val:
            answer["type"] = mode_val
        return json.dumps(answer, ensure_ascii=False)

    # Fallback
    answer = {}
    if fracture_time:
        answer["time"] = fracture_time
    if mode_val:
        answer["type"] = mode_val
    return json.dumps(answer, ensure_ascii=False)


# ===================== Main Processing =====================
def process_all(processed_dir: Path, xlsx_path: Path, yaml_path: Path):
    """Process all JSON files in processed directory"""

    # Load data sources
    video_data = load_xlsx_data(xlsx_path)
    q_to_cat = load_question_pool(yaml_path)

    print(f"Loaded {len(video_data)} videos from xlsx")
    print(f"Loaded {len(q_to_cat)} questions from pool")

    json_files = sorted(processed_dir.glob("*.json"))
    print(f"Found {len(json_files)} JSON files to process")

    success = 0
    for jf in json_files:
        video_id = jf.stem  # e.g. "video_0018"

        if video_id not in video_data:
            print(f"  WARNING: {video_id} not found in xlsx, skipping")
            continue

        vd = video_data[video_id]
        fracture_time = vd["time"]
        fracture_mode = vd["mode"]

        # Read JSON
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

        # Write back
        with jf.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        success += 1

    print(f"\nDone! Processed {success}/{len(json_files)} files successfully")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent.parent

    xlsx_path = project_root / "data" / "annotations" / "all_videos_tag.xlsx"
    yaml_path = project_root / "pipeline" / "config" / "question_pool.yaml"

    # Process both fold_1 and fold_2
    for fold in ["stratified_3_fold_1", "stratified_3_fold_2"]:
        processed_dir = project_root / "pipeline" / "batches" / fold / "processed"
        print(f"\n{'=' * 60}")
        print(f"Processing {fold}...")
        print(f"{'=' * 60}")
        process_all(processed_dir, xlsx_path, yaml_path)
