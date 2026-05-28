#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch Merge Tool

Function: Merge processed JSON files from multiple batches into a single large dataset.
Reads from: data/batches/{batch_name}/processed
Writes to: data/merged_datasets
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
    
    # Defaults
    project_root = Path(__file__).resolve().parent.parent.parent
    base_dir = project_root / "pipeline" / "batches"
    output_dir = project_root / "data" / "merged_datasets"
    
    args = parser.parse_args()
    
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
        processed_dir = batch_path / "processed"
        if not processed_dir.exists():
            logger.warning(f"Skipping {batch_path.name}: 'processed' folder not found")
            continue
            
        json_files = list(processed_dir.glob("*.json"))
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
            except Exception as e:
                logger.error(f"Error reading {jf}: {e}")

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
