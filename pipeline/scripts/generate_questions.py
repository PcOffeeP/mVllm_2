#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate Questions Tool（合并 init_json + randomize_qs）

功能：读取 split 文件 + template.json + question_pool.yaml，
     为每个 train 视频直接生成带随机问题的 JSON，跳过 raw/ 中间步骤。

用法:
    python pipeline/scripts/generate_questions.py -s data/03_splits/stratified_3_fold_0.json -b stratified_3_fold_0
"""

import argparse
import json
import logging
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml 库，请运行: pip install pyyaml")

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
    name: str
    questions: list[str]


@dataclass
class QuestionPool:
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

        shuffled_categories = list(self.categories)
        random.shuffle(shuffled_categories)
        num_cats = len(shuffled_categories)

        base_count = total_count // num_cats
        extra = total_count % num_cats

        counts = [base_count + (1 if i < extra else 0) for i in range(num_cats)]

        result_questions = []
        for i, cat in enumerate(shuffled_categories):
            needed = counts[i]
            if needed == 0:
                continue
            if len(cat.questions) >= needed:
                selected = random.sample(cat.questions, needed)
            else:
                selected = [random.choice(cat.questions) for _ in range(needed)]
            result_questions.extend([f"<video>{q}" for q in selected])

        random.shuffle(result_questions)
        return result_questions


# ===================== Core Functions =====================
def generate_for_video(
    video_path: str,
    template_data: list,
    pool: QuestionPool,
) -> list:
    """
    为单个视频生成带随机问题的对话数据。

    Args:
        video_path: 视频路径，如 "video_0001.mp4"
        template_data: 模板对话列表（已解析为 Python 对象）
        pool: 问题池

    Returns:
        处理后的对话数据列表
    """
    data = json.loads(json.dumps(template_data))  # deep copy

    # 收集所有 user message
    user_msgs = []
    for dialog in data:
        for msg in dialog.get("messages", []):
            if msg.get("role") == "user":
                user_msgs.append(msg)

    if not user_msgs:
        return data

    # 生成平衡问题
    new_questions = pool.get_balanced_questions(len(user_msgs))

    # 替换 content
    for msg, new_q in zip(user_msgs, new_questions):
        msg["content"] = new_q

    # 更新视频路径为统一格式: videos/video_XXXX.mp4
    video_filename = Path(video_path).name  # 提取纯文件名
    for dialog in data:
        if "videos" in dialog and len(dialog["videos"]) > 0:
            dialog["videos"][0] = f"videos/{video_filename}"

    return data


def _check_legacy_video_paths(output_dir: Path):
    """扫描 processed/ 目录，检测旧格式视频路径并打印警告。"""
    if not output_dir.exists():
        return
    legacy_files = []
    for json_file in output_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data if isinstance(data, list) else [data]:
                videos = item.get("videos", [])
                if videos and not videos[0].startswith("videos/"):
                    legacy_files.append(f"  - {json_file.name}: videos[0]={videos[0]!r}")
                    break
        except Exception:
            pass
    if legacy_files:
        logger.warning(
            f"发现 {len(legacy_files)} 个文件使用旧格式视频路径，"
            "请使用 --force 重新生成："
        )
        for msg in legacy_files:
            logger.warning(msg)


def main():
    project_root = Path(__file__).resolve().parent.parent.parent

    parser = argparse.ArgumentParser(
        description="Generate questions: 从 split 文件 + template + question pool 直接生成带随机问题的 JSON"
    )
    parser.add_argument(
        "--split-file", "-s",
        type=Path,
        required=True,
        help="划分文件路径 (例如: data/03_splits/stratified_3_fold_0.json)",
    )
    parser.add_argument(
        "--batch-name", "-b",
        type=str,
        default=None,
        help="批次名称（默认使用 split 文件名）",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=project_root / "pipeline" / "templates" / "template.json",
        help="模板 JSON 文件路径",
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=project_root / "pipeline" / "config" / "question_pool.yaml",
        help="问题池 YAML 配置文件路径",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "pipeline" / "batches",
        help="批次输出基目录",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子（默认: 42）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已存在的文件（默认跳过）",
    )

    args = parser.parse_args()

    # 设置随机种子
    random.seed(args.seed)

    # 验证 split 文件
    if not args.split_file.exists():
        logger.error(f"划分文件不存在: {args.split_file}")
        sys.exit(1)

    try:
        with open(args.split_file, "r", encoding="utf-8") as f:
            split_data = json.load(f)
    except Exception as e:
        logger.error(f"无法读取划分文件: {e}")
        sys.exit(1)

    if "train" not in split_data:
        logger.error("划分文件中缺少 'train' 键")
        sys.exit(1)

    train_videos = split_data["train"]
    logger.info(f"从划分文件读取到 {len(train_videos)} 个训练集视频")

    # 确定 batch name
    batch_name = args.batch_name or args.split_file.stem

    # 读取模板
    if not args.template.exists():
        logger.error(f"模板文件不存在: {args.template}")
        sys.exit(1)

    try:
        with open(args.template, "r", encoding="utf-8") as f:
            template_data = json.load(f)
    except Exception as e:
        logger.error(f"无法读取或解析模板: {e}")
        sys.exit(1)

    # 加载问题池
    if not args.config.exists():
        logger.error(f"问题池配置文件不存在: {args.config}")
        sys.exit(1)

    try:
        pool = QuestionPool.from_yaml(args.config)
        logger.info(f"加载问题池: {len(pool.categories)} 个类别")
    except Exception as e:
        logger.error(f"无法加载问题池: {e}")
        sys.exit(1)

    # 创建输出目录
    output_dir = args.output_dir / batch_name / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"开始生成批次 '{batch_name}' → {output_dir}")

    success_count = 0
    skip_count = 0

    for video_path in train_videos:
        video_name = Path(video_path).stem  # e.g. "video_0001"
        json_filename = f"{video_name}.json"
        json_filepath = output_dir / json_filename

        if json_filepath.exists():
            if not args.force:
                logger.debug(f"跳过: {json_filename} (文件已存在)")
                skip_count += 1
                continue
            logger.debug(f"覆盖: {json_filename} (--force)")

        try:
            data = generate_for_video(video_path, template_data, pool)
            with open(json_filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            success_count += 1
        except Exception as e:
            logger.error(f"处理 {video_name} 失败: {e}")

    logger.info(
        f"批次 '{batch_name}' 完成! "
        f"成功: {success_count}/{len(train_videos)}, "
        f"跳过: {skip_count}"
    )
    logger.info(f"输出: {output_dir}")

    # 检测旧格式视频路径
    _check_legacy_video_paths(output_dir)


if __name__ == "__main__":
    main()
