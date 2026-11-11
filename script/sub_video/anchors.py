"""Read the explicitly recorded unclamped-phenomenon source frames."""
from __future__ import annotations

from bisect import bisect_left
import hashlib
from pathlib import Path
import re


DOCUMENT = "docs/subvideo-current-logic.md"
START = "<!-- unclamped-anchors:start -->"
END = "<!-- unclamped-anchors:end -->"
HEADERS = ["视频 ID", "源视频帧号", "源视频 SHA-256"]


class AnchorError(ValueError):
    """The reviewed document does not contain an unambiguous anchor table."""


def load_anchors(document_path: Path) -> dict[str, dict]:
    path = Path(document_path).resolve()
    data = path.read_bytes()
    text = data.decode("utf-8-sig")
    if text.count(START) != 1 or text.count(END) != 1 or text.index(END) <= text.index(START):
        raise AnchorError("未夹紧：现象帧记录区缺失或重复")
    lines = [line.strip() for line in text.split(START, 1)[1].split(END, 1)[0].splitlines() if line.strip()]
    def cells(line):
        if not line.startswith("|") or not line.endswith("|"):
            raise AnchorError("未夹紧：现象帧表格格式错误")
        return [cell.strip() for cell in line[1:-1].split("|")]
    if len(lines) < 2 or cells(lines[0]) != HEADERS:
        raise AnchorError("未夹紧：现象帧表头无效")
    if len(cells(lines[1])) != 3 or any(not re.fullmatch(r":?-{3,}:?", c) for c in cells(lines[1])):
        raise AnchorError("未夹紧：现象帧表格分隔行无效")
    result = {}
    for line in lines[2:]:
        values = cells(line)
        if len(values) != 3:
            raise AnchorError("未夹紧：现象帧记录列数错误")
        video_id, raw_frame, source_sha = values
        if (not re.fullmatch(r"video_\d{4}", video_id) or not re.fullmatch(r"0|[1-9]\d*", raw_frame)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha) or video_id in result):
            raise AnchorError("未夹紧：现象帧记录无效或来源重复")
        result[video_id] = {"video_id": video_id, "anchor_type": "unclamped_phenomenon",
                            "source_frame": int(raw_frame), "source_sha256": source_sha,
                            "document_path": str(path), "document_sha256": hashlib.sha256(data).hexdigest()}
    return result


def nearest_boundary(boundaries: list[float], value: float) -> int:
    """Quantize a requested source time to the closest decoded frame boundary."""
    position = bisect_left(boundaries, value)
    options = [i for i in (position-1, position) if 0 <= i < len(boundaries)]
    return min(options, key=lambda i: (abs(boundaries[i] - value), i))
