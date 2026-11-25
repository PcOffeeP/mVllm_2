"""Deterministic fake backend for offline pipeline self-checks.

Never contacts a model, never opens media, and rotates through the frozen
``CATEGORY_ORDER`` so each answer shape appears once.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from . import InferenceRequest, InferenceResult

CATEGORY_ORDER = (
    "complete",
    "missing_fields",
    "invalid_literal",
    "conflict",
    "fenced",
    "request_failed",
    "timeout",
)
NON_ANSWERS = ("request_failed", "timeout")
LEGAL = {
    "断裂状态": "发生断裂",
    "断裂模式": "韧性断裂",
    "断裂位置": "标距内",
    "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
    "断裂现象": {"伸长": "否", "颈缩": "否", "开裂": "否", "界面分离": "否", "断后脱夹": "否"},
}


def fake_raw_output(category: str) -> str | None:
    """Return the raw model text for one category; ``None`` means no answer arrived."""
    if category in NON_ANSWERS:
        return None
    labels = copy.deepcopy(LEGAL)
    if category == "missing_fields":
        del labels["断裂位置"], labels["断裂现象"]["开裂"]
    elif category == "invalid_literal":
        # 词表外取值：「无法判断」已是 score.SINGLES 的合法单值，这里要造非法字面量。
        labels["断裂状态"] = "部分断裂"
    elif category == "conflict":
        labels["断裂状态"] = "未断裂"
        labels["断裂位置"] = "无法判断"
        labels["异常情况"]["爆炸性断裂"] = "是"
    elif category not in ("complete", "fenced"):
        raise ValueError(f"unknown fake category: {category}")
    text = json.dumps(labels, ensure_ascii=False)
    return f"```json\n{text}\n```" if category == "fenced" else text


class FakeBackend:
    """Deterministic fake backend implementing ``InferenceBackend``."""

    backend_name = "fake"

    def __init__(self, model_id: str = "fake") -> None:
        self.model_id = model_id
        self._index = 0

    def run_identity(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model_id": self.model_id,
            "output_unwrapping": "none",
        }

    def infer_one(self, request: InferenceRequest) -> InferenceResult:
        category = CATEGORY_ORDER[self._index % len(CATEGORY_ORDER)]
        self._index += 1
        status = category if category in NON_ANSWERS else "success"
        return InferenceResult(
            status=status,
            raw_output=fake_raw_output(category),
            latency_seconds=0.0,
            extra_meta={"fake_category": category},
        )

    def close(self) -> None:
        return None
