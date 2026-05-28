#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch Random Question Tool

Function: Process a batch of JSONs, injecting random questions from the pool.
Reads from: data/batches/{batch_name}/raw
Writes to: data/batches/{batch_name}/processed
"""

import argparse
import json
import logging
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
import yaml

# ===================== Logging Config =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ===================== Data Models =====================
@dataclass
class QuestionCategory:
    """Question Category Data Class"""
    name: str
    questions: list[str]

@dataclass
class QuestionPool:
    """Question Pool Data Class"""
    categories: list[QuestionCategory] = field(default_factory=list)
    
    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "QuestionPool":
        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load config: {e}")
        
        categories = [
            QuestionCategory(name=name, questions=config.get("questions", []))
            for name, config in data.get("categories", {}).items()
        ]
        return cls(categories=categories)

    def get_balanced_questions(self, total_count: int) -> list[str]:
        if not self.categories:
            raise ValueError("Question pool is empty")

        # 1. Shuffle categories
        shuffled_categories = list(self.categories)
        random.shuffle(shuffled_categories)
        num_cats = len(shuffled_categories)

        # 2. Balanced allocation
        base_count = total_count // num_cats
        extra = total_count % num_cats
        
        counts = [base_count + (1 if i < extra else 0) for i in range(num_cats)]
        
        # 3. Select unique questions
        result_questions = []
        for i, cat in enumerate(shuffled_categories):
            needed = counts[i]
            if needed == 0: continue
            
            if len(cat.questions) >= needed:
                selected = random.sample(cat.questions, needed)
            else:
                selected = [random.choice(cat.questions) for _ in range(needed)]
            
            result_questions.extend([f"<video>{q}" for q in selected])
        
        # 4. Final shuffle
        random.shuffle(result_questions)
        return result_questions

# ===================== Core Functions =====================
def process_single_json(file_path: Path, output_dir: Path, pool: QuestionPool) -> Path:
    """
    Process a single JSON file.

    Args:
        file_path: Path to the JSON file
        output_dir: Directory to save the processed JSON file
        pool: Question pool

    Returns:
        Path to the processed JSON file
    """
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Collect user messages
    user_msgs = []
    for dialog in data:
        for msg in dialog.get("messages", []):
            if msg.get("role") == "user":
                user_msgs.append(msg)

    if not user_msgs:
        return None

    # Generate balanced questions
    new_questions = pool.get_balanced_questions(len(user_msgs))
    
    # Replace content
    for msg, new_q in zip(user_msgs, new_questions):
        msg["content"] = new_q

    output_path = output_dir / file_path.name
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    return output_path

# ----------------------------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Random Question Injection for Batches")
    parser.add_argument("--batch-name", "-b", required=True, help="Name of the batch to process")
    parser.add_argument("--seed", "-s", type=int, default=42, help="Random seed")
    
    # Determine defaults relative to script location
    project_root = Path(__file__).resolve().parent.parent.parent
    qspool_config = project_root / "pipeline" / "config" / "question_pool.yaml"
    
    parser.add_argument("--config", "-c", type=Path, default=qspool_config, help="YAML config path")
    parser.add_argument("--base-dir", type=Path, default=project_root / "pipeline" / "batches", help="Batches base directory")
    
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    # Validate paths
    batch_dir = args.base_dir / args.batch_name
    input_dir = batch_dir / "raw"
    output_dir = batch_dir / "processed"
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        logger.error("Please run init_json.py first.")
        sys.exit(1)

    # Check for files before creating output
    json_files = list(input_dir.glob("*.json"))
    if not json_files:
        logger.warning(f"No JSON files found in {input_dir}")
        return

    # Load Pool
    try:
        pool = QuestionPool.from_yaml(args.config)
        logger.info(f"Loaded question pool with {len(pool.categories)} categories")
    except Exception as e:
        logger.error(f"Failed to load question pool: {e}")
        sys.exit(1)
        
    # Create output dir ONLY if everything else is ready
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process files
    logger.info(f"Processing batch '{args.batch_name}' ({len(json_files)} files)...")
    
    success_count = 0
    for f in json_files:
        try:
            out = process_single_json(f, output_dir, pool)
            if out:
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to process {f.name}: {e}")

    logger.info(f"Batch '{args.batch_name}' completed! Success: {success_count}/{len(json_files)}")
    logger.info(f"Output: {output_dir}")

if __name__ == "__main__":
    main()
