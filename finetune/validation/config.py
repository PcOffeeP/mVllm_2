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
BASE_MODEL_DIR = str(PROJECT_ROOT / "models" / "minicpm-v-4.5")

DEFAULT_VIDEO_ROOT = VIDEO_DIR  # 远端原值: Path("/hy-tmp/videos")
DEFAULT_MODEL_DIRS = {
    0: "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged",
    1: "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1_merged",
    2: "LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2_merged",
}

VIDEO_MAX_FRAMES = 8
TIME_THRESHOLD_SEC = 2.0
SUPPORTED_FOLDS = (0, 1, 2)
SUPPORTED_SPLITS = ("fold_0_val", "fold_1_val", "fold_2_val", "test")
SUPPORTED_TASKS = ("time", "type", "joint")
PROMPT_PRESETS = ("baseline", "strict", "fewshot", "strict_interval", "fewshot_interval")

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
BASELINE_PROMPTS = {
    "time": '请仅输出断裂时间，格式为 {"time": "..."}。若未断裂、未夹紧、视频异常或无法判断，请输出 {"time": null}。',
    "type": '请仅输出断裂模式，格式为 {"type": "..."}。',
    "joint": '请仅输出断裂时间和断裂模式，格式为 {"time": "...", "type": "..."}。若无可用时间则 time 设为 null。',
}

TEST_INPUTS_JSON = DATA_DIR_ROOT / "06_merged" / "test_inputs.json"
TEST_GROUND_TRUTH_JSON = DATA_DIR_ROOT / "06_merged" / "test_ground_truth.json"

STRICT_PROMPTS = {
    "time": (
        '请仅输出单个 JSON 对象，格式严格为 {"time": "<float>s"} 或 {"time": null}。'
        '只有在样本属于 未断裂、未夹紧、视频异常 或 无法判断 时，才允许输出 null。'
        '禁止输出日期、年月日、时分秒、帧序号、clip/frame/image 等描述。'
    ),
    "type": (
        '请仅输出单个 JSON 对象，格式严格为 {"type": "..."}。'
        'type 只能从以下闭集标签中选择一个：'
        "韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂 / 未断裂 / 未夹紧 / 视频异常。"
        '禁止输出闭集之外的标签或解释性文字。'
    ),
    "joint": (
        '请仅输出单个 JSON 对象，格式严格为 {"time": "<float>s", "type": "..."} 或 {"time": null, "type": "..."}。'
        'time 只能是带 s 后缀的秒数或 null；禁止输出日期、帧序号、clip/frame/image 等描述。'
        '只有在样本属于 未断裂、未夹紧、视频异常 或 无法判断 时，time 才允许为 null。'
        'type 只能从以下闭集标签中选择一个：'
        "韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂 / 未断裂 / 未夹紧 / 视频异常。"
        '禁止输出数组、多行 JSON 或闭集之外的标签。'
    ),
}

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

FEWSHOT_EXAMPLES = {
    "type": (
        '示例1输出：{"type": "韧性断裂"}\n'
        '示例2输出：{"type": "视频异常"}'
    ),
    "joint": (
        '示例1输出：{"time": "38.65s", "type": "韧性断裂"}\n'
        '示例2输出：{"time": null, "type": "视频异常"}'
    ),
}

FEWSHOT_INTERVAL_EXAMPLES = (
    '示例1（正常断裂）：\n'
    '{"has_fracture": true, "fracture_between": [3, 4], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.95}\n'
    '示例2（未断裂）：\n'
    '{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null, "confidence": 0.98}\n'
    '示例3（视频异常）：\n'
    '{"has_fracture": null, "fracture_between": null, "type": "视频异常", "location": null, "confidence": 0.70}\n'
    '示例4（脆性断裂，outside_gauge）：\n'
    '{"has_fracture": true, "fracture_between": [5, 6], "type": "脆性断裂", "location": "outside_gauge", "confidence": 0.88}'
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
