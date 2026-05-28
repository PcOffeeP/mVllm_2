#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch Merge Tool

Function: Merge processed/answered JSON files from multiple batches into a single large dataset.
Reads from: pipeline/batches/{batch_name}/processed|answered
Writes to: data/04_merged
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

def main():
    parser = argparse.ArgumentParser(description="Merge batches into a single training dataset.")
    parser.add_argument("--output", "-o", required=True, help="Output filename (e.g. batch_000.json)")
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
    
    # 自动追加 .json 后缀（如果用户未提供）
    if not args.output.endswith(".json"):
        args.output += ".json"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    target_file = output_dir / args.output
    
    # Identify batches to process
    if args.batches:
        batches_to_process = [base_dir / b for b in args.batches]
    else:
        # Find all directories in base_dir
        if not base_dir.exists():
            logger.error(f"Batches directory not found: {base_dir}")
            sys.exit(1)
        batches_to_process = [d for d in base_dir.iterdir() if d.is_dir()]
    
    if not batches_to_process:
        logger.warning("No batches found to merge.")
        return

    all_data = []
    total_files = 0
    
    logger.info(f"Merging {len(batches_to_process)} batches...")
    
    for batch_path in batches_to_process:
        source_dir = batch_path / args.source
        if not source_dir.exists():
            logger.warning(f"Skipping {batch_path.name}: '{args.source}' 目录不存在")
            continue
            
        json_files = list(source_dir.glob("*.json"))
        if not json_files:
            logger.warning(f"Skipping {batch_path.name}: '{args.source}' 目录为空")
            continue
        logger.info(f"  - {batch_path.name}: {len(json_files)} files")
        
        for jf in json_files:
            try:
                with jf.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_data.extend(data)
                    else:
                        # Handle case where file might be a single object
                        all_data.append(data)
                total_files += 1
            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析失败 {jf}: {e}")
            except Exception as e:
                logger.error(f"读取失败 {jf}: {e}")

    # Write output
    logger.info(f"Writing {len(all_data)} records to {target_file}...")
    try:
        with target_file.open('w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        logger.info("Merge complete!")
    except Exception as e:
        logger.error(f"Failed to write output: {e}")

if __name__ == "__main__":
    main()
