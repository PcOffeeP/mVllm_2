from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_ground_truth_label, parse_seconds, write_json
from config import GROUND_TRUTH_CSV, GROUND_TRUTH_JSON, TRAINING_JSON_FILES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert the CSV GT sheet into tracked JSON.")
    parser.add_argument("--csv", default=str(GROUND_TRUTH_CSV), help="Path to the CSV GT file.")
    parser.add_argument("--out", default=str(GROUND_TRUTH_JSON), help="Output JSON path.")
    return parser.parse_args()


def load_csv_rows(csv_path: Path) -> list[dict[str, Any]]:
    df = pd.read_csv(csv_path)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for _, row in df.iterrows():
        video_id = str(row["id"]).strip()
        if video_id in seen_ids:
            raise ValueError(f"Duplicated video id in CSV: {video_id}")
        seen_ids.add(video_id)
        gt_time_raw = row["断裂时间点"] if not pd.isna(row["断裂时间点"]) else None
        record = {
            "video_id": video_id,
            "video_name": f"{video_id}.mp4",
            "gt_time_raw": gt_time_raw,
            "gt_time_sec": parse_seconds(gt_time_raw),
            "time_available": gt_time_raw is not None and parse_seconds(gt_time_raw) is not None,
            "gt_type": normalize_ground_truth_label(row["断裂模式"] if not pd.isna(row["断裂模式"]) else None),
            "material": row["材料类型"] if not pd.isna(row["材料类型"]) else None,
            "clarity": row["清晰度"] if not pd.isna(row["清晰度"]) else None,
        }
        records.append(record)
    return sorted(records, key=lambda item: item["video_id"])


def load_training_ground_truth() -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in TRAINING_JSON_FILES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload:
            video_name = Path(item["videos"][0]).name
            answer = next(message["content"] for message in item["messages"] if message["role"] == "assistant")
            parsed = json.loads(answer)
            entry = merged.setdefault(video_name, {"time": set(), "type": set()})
            if "time" in parsed and parse_seconds(parsed["time"]) is not None:
                entry["time"].add(round(parse_seconds(parsed["time"]), 6))
            if "type" in parsed and normalize_ground_truth_label(parsed["type"]) is not None:
                entry["type"].add(normalize_ground_truth_label(parsed["type"]))
    return merged


def verify_against_training_json(records: list[dict[str, Any]]) -> None:
    training_gt = load_training_ground_truth()
    for record in records:
        entry = training_gt.get(record["video_name"])
        if entry is None:
            raise ValueError(f"Training JSON missing GT for {record['video_name']}")
        if record["gt_type"] not in entry["type"]:
            raise ValueError(f"Type mismatch for {record['video_name']}: {record['gt_type']} vs {sorted(entry['type'])}")
        if record["time_available"]:
            gt_time = round(float(record["gt_time_sec"]), 6)
            if gt_time not in entry["time"]:
                raise ValueError(f"Time mismatch for {record['video_name']}: {gt_time} vs {sorted(entry['time'])}")
        elif entry["time"]:
            raise ValueError(f"CSV missing time for {record['video_name']} but training JSON has {sorted(entry['time'])}")


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv)
    out_path = Path(args.out)

    records = load_csv_rows(csv_path)
    verify_against_training_json(records)
    write_json(out_path, records)

    time_available = sum(1 for item in records if item["time_available"])
    print(f"Saved {len(records)} GT records to {out_path}")
    print(f"time_available=true: {time_available}")


if __name__ == "__main__":
    main()
