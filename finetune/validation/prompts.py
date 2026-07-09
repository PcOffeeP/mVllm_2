from __future__ import annotations

from .constants import PROMPT_NAMES

TRAINING_PROMPT = (
    "请分析这段拉伸试验视频，判断是否存在断裂。视频将被处理为最多 8 帧，"
    "请判断断裂发生在哪两帧之间。按 JSON 格式输出："
    "has_fracture、fracture_between、type、location、confidence。"
)

SYSTEM_PROMPT = (
    "任务：分析视频中材料的断裂。只允许输出单个 JSON 对象，不得输出解释、Markdown 或代码块。\n"
    "JSON 必须且只能包含五个字段：has_fracture、fracture_between、type、location、confidence。\n"
    "字段约束：\n"
    "- has_fracture: true、false 或 null。\n"
    "- fracture_between: 断裂发生的相邻采样帧索引 [i, i+1]，i 范围 0-6；无断裂或异常时为 null。\n"
    "- type: 只能是 韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂 / 未断裂 / 未夹紧 / 视频异常。\n"
    "- location: 断裂时只能是 inside_gauge 或 outside_gauge；无断裂或异常时为 null。\n"
    "- confidence: 0 到 1 的数字。\n"
    "组合规则：七类断裂必须 has_fracture=true 且给出 fracture_between 和 location；"
    "未断裂/未夹紧必须 has_fracture=false 且 fracture_between/location 为 null；"
    "视频异常必须 has_fracture=null 且 fracture_between/location 为 null。"
)


def get_prompt(name: str) -> str:
    if name == "training":
        return TRAINING_PROMPT
    if name == "system":
        return SYSTEM_PROMPT
    raise ValueError(f"Unsupported prompt: {name}. Expected one of {PROMPT_NAMES}.")
