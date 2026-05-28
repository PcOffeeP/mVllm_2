from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # validation/ → AAA-TS-Video/ → finetune/ → mVllm/
DATA_DIR_ROOT = PROJECT_ROOT / "data"
VIDEO_DIR = DATA_DIR_ROOT / "01_videos"


VALIDATION_DIR = Path(__file__).resolve().parent
AAA_TS_VIDEO_DIR = VALIDATION_DIR.parent
DATA_DIR = AAA_TS_VIDEO_DIR / "data"
JSON_DIR = DATA_DIR / "JSON"
SPLIT_DIR = DATA_DIR_ROOT / "03_splits"
RESULTS_DIR = VALIDATION_DIR / "results"

GROUND_TRUTH_CSV = DATA_DIR_ROOT / "02_annotations" / "all_videos_tag.csv"
GROUND_TRUTH_JSON = DATA_DIR / "all_videos_tag.json"
TRAINING_JSON_FILES = [
    JSON_DIR / "3k0.json",
    JSON_DIR / "3k1.json",
    JSON_DIR / "3k2.json",
]

DEFAULT_VIDEO_ROOT = VIDEO_DIR  # 远端原值: Path("/hy-tmp/videos")
DEFAULT_MODEL_DIRS = {
    0: "/hy-tmp/model/train/test01/sft_3k0",
    1: "/hy-tmp/model/train/test01/sft_3k1",
    2: "/hy-tmp/model/train/test01/sft_3k2",
}

SAMPLE_FRAMES = 8
TIME_THRESHOLD_SEC = 2.0
SUPPORTED_FOLDS = (0, 1, 2)
SUPPORTED_TASKS = ("time", "type", "joint")
PROMPT_PRESETS = ("baseline", "strict", "fewshot")

ALLOWED_TYPE_LABELS = (
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "界面脱粘、齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "未断裂",
    "未夹紧",
    "视频异常",
)

PROMPT_INSTRUCTION = '任务：分析视频中材料的断裂。要求：仅以JSON格式输出，严禁任何文字解释。'
BASELINE_PROMPTS = {
    "time": '请仅输出断裂时间，格式为 {"time": "..."}。若未断裂、未夹紧、视频异常或无法判断，请输出 {"time": null}。',
    "type": '请仅输出断裂模式，格式为 {"type": "..."}。',
    "joint": '请仅输出断裂时间和断裂模式，格式为 {"time": "...", "type": "..."}。若无可用时间则 time 设为 null。',
}

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
    "json_invalid",
    "time_unparseable",
    "type_unmapped",
    "time_threshold_exceeded",
    "type_mismatch",
)
