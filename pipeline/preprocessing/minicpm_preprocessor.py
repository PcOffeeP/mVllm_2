from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from pipeline.preprocessing.adapter import FrameMapping, ProcessorInfo, VideoPreprocessor

try:
    import transformers
except Exception:  # pragma: no cover - 训练机才安装
    transformers = None


class MiniCPMVideoPreprocessor(VideoPreprocessor):
    """MiniCPM-V 4.6 视频处理器模板。

    训练机将接入真实 processor；本地无 transformers 时仅作接口占位，
    保证结构一致性，不报错。
    """

    NAME = "minicpm-v-4.6"
    EXPECTED_MAX_FRAMES = 8

    def __init__(self, model_path_or_name: str, max_frames: int = EXPECTED_MAX_FRAMES) -> None:
        self._model_path_or_name = model_path_or_name
        self._max_frames = max_frames
        self._processor: Any | None = None

    # ------------------------------------------------------------------
    # VideoPreprocessor 接口
    # ------------------------------------------------------------------

    def get_info(self) -> ProcessorInfo:
        return ProcessorInfo(
            name=self.NAME,
            version=self._model_path_or_name,
            max_frames=self._max_frames,
            backend=(
                "transformers"
                if transformers is not None
                else "transformers-not-installed"
            ),
        )

    def healthcheck(self) -> bool:
        """校验 max_frames 为 8，并在可用时检查 transformers。"""
        if self._max_frames != self.EXPECTED_MAX_FRAMES:
            return False
        if transformers is None:
            return False
        return True

    def sample(
        self, video_path: str, start_time: float, end_time: float
    ) -> list[FrameMapping]:
        """TODO: 在训练机上使用真实 MiniCPM-V 4.6 video_processor 实现。"""
        raise NotImplementedError(
            "MiniCPMVideoPreprocessor.sample() 需在训练机接入真实 "
            "MiniCPM-V 4.6 视频处理器后补全。"
        )

    def fingerprint(self) -> str:
        backend_flag = "transformers" if transformers is not None else "no-transformers"
        base = (
            f"{self.NAME}:{self._model_path_or_name}:"
            f"max_frames={self._max_frames}:{backend_flag}"
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.preprocessing.minicpm_preprocessor",
        description="MiniCPM-V 4.6 视频预处理器模板 CLI",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="检查配置是否满足 max_frames=8 及 transformers 是否可用",
    )
    parser.add_argument(
        "--model",
        default="openbmb/MiniCPM-V-2_6",
        help="模型路径或 HuggingFace 名称",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    preprocessor = MiniCPMVideoPreprocessor(model_path_or_name=args.model)

    if args.healthcheck:
        ok = preprocessor.healthcheck()
        info = preprocessor.get_info()
        print(json.dumps({
            "ok": ok,
            "info": {
                "name": info.name,
                "version": info.version,
                "max_frames": info.max_frames,
                "backend": info.backend,
            },
            "fingerprint": preprocessor.fingerprint(),
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    _build_argparser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
