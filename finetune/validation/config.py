from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # validation/ → finetune/ → TensileAgent/
assert (PROJECT_ROOT / ".gitmodules").exists(), f"PROJECT_ROOT mismatch: {PROJECT_ROOT}"
DATA_DIR_ROOT = PROJECT_ROOT / "data"
VIDEO_DIR = DATA_DIR_ROOT / "01_videos"


VALIDATION_DIR = Path(__file__).resolve().parent
FINETUNE_DIR = VALIDATION_DIR.parent  # finetune/（原视频目录已上提合并至此）
DATA_DIR = DATA_DIR_ROOT  # 仓库根目录的 data/
JSON_DIR = DATA_DIR / "06_merged"  # 合并后的训练/验证 JSON 存放目录
SPLIT_DIR = DATA_DIR_ROOT / "05_splits"
RESULTS_DIR = VALIDATION_DIR / "results"

GROUND_TRUTH_CSV = DATA_DIR_ROOT / "02_annotations" / "all_videos_tag.csv"
# 历史产物：由 prepare_ground_truth.py 从 CSV 生成。如该 JSON 不存在，
# common.load_ground_truth() 会回退到直接读取 GROUND_TRUTH_CSV。
GROUND_TRUTH_JSON = DATA_DIR_ROOT / "02_annotations" / "all_videos_tag.json"
SUBVIDEOS_META_JSON = DATA_DIR_ROOT / "07_metadata" / "subvideos_meta.json"

# 新 interval 方案训练/验证产物。
TRAINING_JSON_FILES = [
    DATA_DIR_ROOT / "06_merged" / "fold_0_train.json",
    DATA_DIR_ROOT / "06_merged" / "fold_0_val.json",
    DATA_DIR_ROOT / "06_merged" / "fold_1_train.json",
    DATA_DIR_ROOT / "06_merged" / "fold_1_val.json",
    DATA_DIR_ROOT / "06_merged" / "fold_2_train.json",
    DATA_DIR_ROOT / "06_merged" / "fold_2_val.json",
]

# Base model path (for processor fallback when merged model tokenizer is None)
BASE_MODEL_DIR = str(PROJECT_ROOT / "models" / "minicpmv4_5")

DEFAULT_VIDEO_ROOT = VIDEO_DIR  # 远端原值: Path("/hy-tmp/videos")
DEFAULT_MODEL_DIRS = {
    0: "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged",
    1: "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1_merged",
    2: "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2_merged",
}

VIDEO_MAX_FRAMES = 8
TIME_THRESHOLD_SEC = 2.0
SUPPORTED_FOLDS = (0, 1, 2)
SUPPORTED_SPLITS = ("fold_0_val", "fold_1_val", "fold_2_val", "test", "test_subvideos")
SUPPORTED_TASKS = ("time", "type", "joint")
PROMPT_PRESETS = ("strict_interval", "training_interval")

FRACTURE_CLASSES = (
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "界面脱粘、齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
)

NON_FRACTURE_CLASSES = (
    "未断裂",
    "未夹紧",
    "视频异常",
)

ALLOWED_TYPE_LABELS = FRACTURE_CLASSES + NON_FRACTURE_CLASSES

PROMPT_INSTRUCTION = '任务：分析视频中材料的断裂。要求：仅以JSON格式输出，严禁任何文字解释。'

TEST_INPUTS_JSON = DATA_DIR_ROOT / "06_merged" / "test_inputs.json"
TEST_GROUND_TRUTH_JSON = DATA_DIR_ROOT / "06_merged" / "test_ground_truth.json"
TEST_SUBVIDEO_INPUTS_JSON = DATA_DIR_ROOT / "06_merged" / "test_subvideo_inputs.json"
TEST_SUBVIDEO_GROUND_TRUTH_JSON = DATA_DIR_ROOT / "06_merged" / "test_subvideo_ground_truth.json"

STRICT_INTERVAL_PROMPT = {
    "joint": (
        '请仅输出单个 JSON 对象，不得输出解释、Markdown、代码块。\n'
        '字段必须且只能包含以下五个字段：\n'
        '  has_fracture: true / false / null\n'
        '  fracture_between: [i, i+1] (整数对，i 范围 0-6) 或 null\n'
        '  type: 断裂类型字符串\n'
        '  location: "inside_gauge" / "outside_gauge" / null\n'
        '  confidence: 0-1 的数字\n'
        '\n'
        'type 只能从以下闭集中选择一个：\n'
        "韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂 / 未断裂 / 未夹紧 / 视频异常\n"
        '\n'
        '合法组合规则：\n'
        '1. 若 type 是七类断裂之一（韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂）：\n'
        '   has_fracture 必须为 true；fracture_between 必须是相邻整数对 [i, i+1]（i 范围 0-6）；location 必须是 inside_gauge 或 outside_gauge。\n'
        '2. 若 type 是 未断裂 或 未夹紧：\n'
        '   has_fracture 必须为 false；fracture_between 必须为 null；location 必须为 null。\n'
        '3. 若 type 是 视频异常：\n'
        '   has_fracture 必须为 null；fracture_between 必须为 null；location 必须为 null。\n'
        '4. confidence 必须是 0 到 1 的数字。\n'
        '\n'
        '只输出单个 JSON 对象，不要有任何其他文字。'
    ),
}

# Instruction text copied from the training samples after the training-side
# <video> placeholder. In inference, run_inference.py inserts concrete image
# placeholders before this text.
TRAINING_INTERVAL_PROMPT = (
    "请分析这段拉伸试验视频，判断是否存在断裂。视频将被处理为最多 8 帧，"
    "请判断断裂发生在哪两帧之间。按 JSON 格式输出："
    "has_fracture、fracture_between、type、location、confidence。"
)

LABEL_ALIASES = {
    "grip-end fracture": "齐根断裂",
    "interface tear-off": "界面脱粘",
    "interface tear-off, grip-end fracture": "界面脱粘、齐根断裂",
    "brittle fracture": "脆性断裂",
    "ductile fracture": "韧性断裂",
    "ductile farcture": "韧性断裂",
    "brittle-ductile fracture": "半脆半韧断裂",
    "explosive fracture": "爆炸性断裂",
    "video anomaly": "视频异常",
    "no fracture": "未断裂",
    "not clamped": "未夹紧",
}

FAILURE_REASONS = (
    "video_load_failed",
    "model_inference_failed",
    "json_invalid",
    "time_unparseable",
    "type_unmapped",
    "time_threshold_exceeded",
    "type_mismatch",
)
