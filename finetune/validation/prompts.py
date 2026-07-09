from __future__ import annotations

from .constants import PROMPT_NAMES

TRAINING_PROMPT = (
    "请分析这段拉伸试验视频，判断是否存在断裂。视频将被处理为最多 8 帧，"
    "请判断断裂发生在哪两帧之间。按 JSON 格式输出："
    "has_fracture、fracture_between、type、location、confidence。"
)

SYSTEM_PROMPT = (
    "请分析这段拉伸试验视频，判断是否存在断裂。视频将被处理为最多 8 帧。\n"
    "如果画面中发生断裂，请判断断裂发生在哪两个相邻采样帧之间。\n"
    "只输出一个 JSON 对象，不要输出解释、Markdown 或代码块。\n"
    "JSON 包含以下五个字段：\n"
    "{\n"
    '  "has_fracture": true 或 false,\n'
    '  "fracture_between": [i, i+1] 或 null,\n'
    '  "type": "断裂类型或未断裂",\n'
    '  "location": "inside_gauge或outside_gauge或null",\n'
    '  "confidence": 0到1之间的数字\n'
    "}\n"
    "重要要求：\n"
    "- 如果 has_fracture 为 true，fracture_between 必须是 [0,1] 到 [6,7] 中的一个，不能为 null。\n"
    "- 如果不确定具体区间，也请选择最可能的相邻帧区间。\n"
    "- 只有确认没有断裂时，fracture_between 才输出 null。\n"
    "- 先判断视频中是否发生断裂，再考虑 JSON 格式。"
)


def get_prompt(name: str) -> str:
    if name == "training":
        return TRAINING_PROMPT
    if name == "system":
        return SYSTEM_PROMPT
    raise ValueError(f"Unsupported prompt: {name}. Expected one of {PROMPT_NAMES}.")
