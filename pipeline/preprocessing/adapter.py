from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessorInfo:
    """预处理器的身份与能力声明。"""

    name: str
    version: str
    max_frames: int
    backend: str


@dataclass(frozen=True)
class FrameMapping:
    """单帧从输入序列到源视频帧号和时间戳的映射。"""

    input_index: int
    original_frame: int
    timestamp: float


class VideoPreprocessor(ABC):
    """训练与服务共用的视频预处理适配层抽象。"""

    @abstractmethod
    def get_info(self) -> ProcessorInfo:
        """返回处理器元信息。"""
        ...

    @abstractmethod
    def healthcheck(self) -> bool:
        """校验当前环境是否可用。"""
        ...

    @abstractmethod
    def sample(
        self, video_path: str, start_time: float, end_time: float
    ) -> list[FrameMapping]:
        """对指定时间区间进行采样，返回帧映射列表。"""
        ...

    @abstractmethod
    def fingerprint(self) -> str:
        """返回可识别的配置指纹字符串。"""
        ...
