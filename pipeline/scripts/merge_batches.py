#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch Merge Tool

Function: Merge processed/answered JSON files from multiple batches.
Reads from: pipeline/batches/{batch_name}/processed|answered
Writes to: data/04_merged

Modes:
  - Per-batch (default): Each batch outputs to data/04_merged/{batch_name}.json
  - Merged: Use --output to merge all batches into a single file
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# ===================== Logging Config =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _read_batch_data(batch_path, source):
    """Read all JSON files from a single batch's source directory.
    Returns (data_list, file_count) or (None, 0) if skipped."""
    source_dir = batch_path / source
    if not source_dir.exists():
        logger.warning(f"Skipping {batch_path.name}: '{source}' 目录不存在")
        return None, 0

    json_files = list(source_dir.glob("*.json"))
    if not json_files:
        logger.warning(f"Skipping {batch_path.name}: '{source}' 目录为空")
        return None, 0

    logger.info(f"  - {batch_path.name}: {len(json_files)} files")

    data = []
    for jf in json_files:
        try:
            with jf.open('r', encoding='utf-8') as f:
                item = json.load(f)
                if isinstance(item, list):
                    data.extend(item)
                else:
                    data.append(item)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败 {jf}: {e}")
        except Exception as e:
            logger.error(f"读取失败 {jf}: {e}")

    return data, len(json_files)


def _collect_batches(base_dir, batch_names=None):
    """Resolve batch directories to process.
    Returns list of (batch_name, batch_path)."""
    if batch_names:
        seen = set()
        result = []
        for b in batch_names:
            if b not in seen:
                seen.add(b)
                result.append((b, base_dir / b))
        return result

    if not base_dir.exists():
        logger.error(f"Batches directory not found: {base_dir}")
        sys.exit(1)

    return [(d.name, d) for d in sorted(base_dir.iterdir()) if d.is_dir()]


def main():
    parser = argparse.ArgumentParser(
        description="Merge batches. Default: one JSON per batch. Use --output to merge into one file."
    )
    parser.add_argument(
        "--output", "-o",
        help="Output filename for merged mode (e.g. batch_000.json). "
             "When omitted, each batch writes to {batch_name}.json",
    )
    parser.add_argument("--batches", "-b", nargs="+", help="Specific batch names to merge")
    parser.add_argument(
        "--source",
        choices=["processed", "answered"],
        default="processed",
        help="读取来源目录: processed (默认) 或 answered",
    )

    # Defaults
    project_root = Path(__file__).resolve().parent.parent.parent
    base_dir = project_root / "pipeline" / "batches"
    output_dir = project_root / "data" / "04_merged"

    args = parser.parse_args()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve batches
    batches = _collect_batches(base_dir, args.batches)
    if not batches:
        logger.warning("No batches found to merge.")
        return

    # --- Merged mode: --output specified ---
    if args.output:
        if not args.output.lower().endswith(".json"):
            args.output += ".json"
        target_file = output_dir / args.output

        all_data = []
        total_files = 0
        logger.info(f"Merged mode: {len(batches)} batches -> {args.output}")

        for batch_name, batch_path in batches:
            data, n = _read_batch_data(batch_path, args.source)
            if data is not None:
                all_data.extend(data)
                total_files += n

        logger.info(f"Writing {len(all_data)} records to {target_file}...")
        try:
            with target_file.open('w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            logger.info("Merge complete!")
        except Exception as e:
            logger.error(f"Failed to write output: {e}")
        return

    # --- Per-batch mode: --output NOT specified ---
    logger.info(f"Per-batch mode: {len(batches)} batch(es)")
    for batch_name, batch_path in batches:
        data, n = _read_batch_data(batch_path, args.source)
        if data is None:
            continue

        out_name = f"{Path(batch_name).name}.json"
        target_file = output_dir / out_name
        logger.info(f"Writing {len(data)} records ({n} files) to {target_file}...")
        try:
            with target_file.open('w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to write {out_name}: {e}")

    logger.info("Merge complete!")

if __name__ == "__main__":
    main()
