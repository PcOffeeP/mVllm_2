from pipeline.preprocessing.adapter import (
    FrameMapping,
    ProcessorInfo,
    VideoPreprocessor,
)

__all__ = [
    "FrameMapping",
    "ProcessorInfo",
    "VideoPreprocessor",
    "MockVideoPreprocessor",
    "MiniCPMVideoPreprocessor",
]


def __getattr__(name: str):
    """延迟导入，避免 `python -m module` 产生重复导入警告。"""
    if name == "MockVideoPreprocessor":
        from pipeline.preprocessing.mock_preprocessor import MockVideoPreprocessor

        return MockVideoPreprocessor
    if name == "MiniCPMVideoPreprocessor":
        from pipeline.preprocessing.minicpm_preprocessor import MiniCPMVideoPreprocessor

        return MiniCPMVideoPreprocessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
