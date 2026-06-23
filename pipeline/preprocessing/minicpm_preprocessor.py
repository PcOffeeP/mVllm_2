from __future__ import annotations

import argparse
import hashlib
import logging
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pipeline.preprocessing.adapter import FrameMapping, ProcessorInfo, VideoPreprocessor

import av

try:
    import transformers as _transformers_module
except Exception:  # pragma: no cover - 训练机才安装
    _transformers_module = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助：CPU 退路
# ---------------------------------------------------------------------------


def _cpu_fallback() -> bool:
    """检测当前环境是否可安全加载 transformer 模型。

    Mac（mps／无 GPU）上加载大型视觉模型容易 OOM，返回 True 表示应走 fallback。
    """
    import platform
    if platform.system() != "Darwin":
        return False  # Linux 训练机，正常加载
    # Mac 上 transformers / torch 可能可用但仍不期望加载大模型
    return True


# ---------------------------------------------------------------------------
# MiniCPM-V 4.6 视频预处理器
# ---------------------------------------------------------------------------


class MiniCPMVideoPreprocessor(VideoPreprocessor):
    """MiniCPM-V 4.6 视频处理器。

    加载 `transformers.AutoProcessor` 并提取 `video_processor` 用于帧选择。
    在 Mac（无 GPU／transformers 不可用）上优雅 fallback 到 pyav 帧索引计算。

    Architecture
    ------------
    * `__init__` 尝试预加载 processor；若失败（Mac／import 错误）标记延迟加载。
    * `_ensure_processor()` 在首次需要时加载。
    * `sample()` 优先走 processor 路径：解码帧 → video_processor → 输出帧数回映。
    * `healthcheck()` 生成临时视频做集成验证。
    """

    NAME = "minicpm-v-4.6"
    EXPECTED_MAX_FRAMES = 8

    def __init__(self, model_path_or_name: str, max_frames: int = EXPECTED_MAX_FRAMES) -> None:
        self._model_path_or_name = model_path_or_name
        self._max_frames = max_frames
        self._processor: Any | None = None
        self._video_processor: Any | None = None
        self._processor_loaded = False

        # 尝试预加载；忽略 Mac 上可预见的失败
        self._try_load_processor()

    # ------------------------------------------------------------------
    # Processor 生命周期
    # ------------------------------------------------------------------

    def _try_load_processor(self) -> None:
        """预加载 processor；失败不抛异常，留待延迟加载。"""
        if _transformers_module is None:
            return
        if _cpu_fallback():
            return
        try:
            self._load_processor()
        except Exception as exc:
            logger.info(
                "预加载 processor 失败（将在首次 sample 时重试）: %s", exc,
            )

    def _load_processor(self) -> None:
        """实际加载 ``transformers.AutoProcessor`` 并提取 ``video_processor``。"""
        from transformers import AutoProcessor

        processor = AutoProcessor.from_pretrained(
            self._model_path_or_name,
            trust_remote_code=True,
        )
        video_processor = getattr(processor, "video_processor", None)
        if video_processor is None:
            raise RuntimeError(
                f"Processor {type(processor).__name__} 没有 video_processor 属性"
            )
        self._processor = processor
        self._video_processor = video_processor
        self._processor_loaded = True

    def _ensure_processor(self) -> None:
        """确保 processor 已加载；若失败则静默 fallback。"""
        if self._processor_loaded:
            return
        if _transformers_module is None:
            return
        try:
            self._load_processor()
            logger.info("延迟加载 processor 成功: %s", type(self._processor).__name__)
        except Exception as exc:
            logger.warning(
                "processor 加载失败，回退到 pyav 帧索引计算: %s", exc,
            )

    # ------------------------------------------------------------------
    # VideoPreprocessor 接口
    # ------------------------------------------------------------------

    def get_info(self) -> ProcessorInfo:
        version: str = self._model_path_or_name
        if self._processor_loaded and self._processor is not None:
            version = self._processor.__class__.__name__

        if self._processor_loaded:
            backend = "transformers"
        elif _transformers_module is None:
            backend = "transformers-not-installed"
        else:
            backend = "transformers-fallback"

        return ProcessorInfo(
            name=self.NAME,
            version=version,
            max_frames=self._max_frames,
            backend=backend,
        )

    def healthcheck(self) -> bool:
        """校验 max_frames 为 8，加载 processor，用临时视频验证 sample() 输出。"""
        if self._max_frames != self.EXPECTED_MAX_FRAMES:
            return False
        if _transformers_module is None:
            return False
        if _cpu_fallback():
            return False

        self._ensure_processor()
        if not self._processor_loaded:
            return False

        # 用 ffmpeg 生成临时测试视频
        try:
            with tempfile.TemporaryDirectory(prefix="minicpm_healthcheck_") as tmpdir:
                video_path = Path(tmpdir) / "test_healthcheck.mp4"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f", "lavfi",
                    "-i", "color=c=black:s=64x64:d=2:r=10",
                    "-pix_fmt", "yuv420p",
                    "-an",
                    str(video_path),
                ]
                subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                    timeout=30,
                )

                frames = self.sample(str(video_path), start_time=0.0, end_time=2.0)

                # 帧数 ≤ max_frames
                if len(frames) > self._max_frames:
                    return False
                # 顺序单调
                orig_frames = [f.original_frame for f in frames]
                timestamps = [f.timestamp for f in frames]
                if orig_frames != sorted(orig_frames):
                    return False
                if timestamps != sorted(timestamps):
                    return False
                # 无重复帧号
                if len(set(orig_frames)) != len(orig_frames):
                    return False
                # input_index 连续
                if [f.input_index for f in frames] != list(range(len(frames))):
                    return False

                return True
        except Exception:
            return False

    def sample(
        self, video_path: str, start_time: float, end_time: float
    ) -> list[FrameMapping]:
        """对视频时间区间采样，返回帧映射列表。

        优先使用真实 ``video_processor`` 做帧选择；
        processor 不可用时回退到 pyav 均匀帧索引计算。
        """
        container = av.open(video_path, "r")
        try:
            video_stream = next(s for s in container.streams if s.type == "video")

            # --- 获取视频时长（秒）---
            if video_stream.duration is not None:
                duration = float(video_stream.duration * video_stream.time_base)
            elif container.duration:
                duration = float(container.duration) / 1_000_000.0
            else:
                duration = 0.0

            # --- 边界截断 ---
            start_time = max(0.0, start_time)
            end_time = min(end_time, duration)
            if end_time <= start_time:
                return []

            # --- 获取 FPS 和总帧数 ---
            fps = float(video_stream.average_rate)
            total_frames: int = (
                video_stream.frames
                if video_stream.frames is not None and video_stream.frames > 0
                else int(round(duration * fps))
            )

            # --- 尝试使用真实 processor ---
            self._ensure_processor()
            if self._processor_loaded and self._video_processor is not None:
                return self._sample_with_processor(
                    container, video_stream,
                    start_time, end_time, fps, total_frames,
                )

            # --- fallback：pyav 纯帧索引计算 ---
            return self._sample_fallback(
                start_time, end_time, fps, total_frames,
            )
        finally:
            container.close()

    # ------------------------------------------------------------------
    # 采样策略
    # ------------------------------------------------------------------

    def _sample_with_processor(
        self,
        container: av.container.Container,
        video_stream: av.stream.Stream,
        start_time: float,
        end_time: float,
        fps: float,
        total_frames: int,
    ) -> list[FrameMapping]:
        """用 video_processor 处理解码帧，根据实际输出帧数回映。"""
        # 1. 解码区间内的帧
        decoded_frames, decoded_indices = self._decode_frame_range(
            container, video_stream, start_time, end_time, fps, total_frames,
        )
        if not decoded_frames:
            return []

        # 2. 调用 video_processor
        try:
            video_inputs = self._video_processor([decoded_frames], return_tensors="pt")  # type: ignore[union-attr]
            pixel_values = video_inputs.get("pixel_values_videos")
            if pixel_values is None:
                logger.warning(
                    "video_processor 输出不含 pixel_values_videos，回退到 pyav",
                )
                return self._sample_fallback(start_time, end_time, fps, total_frames)
            n = pixel_values.shape[0]
        except Exception as exc:
            logger.warning("video_processor 调用失败 (%s)，回退到 pyav", exc)
            return self._sample_fallback(start_time, end_time, fps, total_frames)

        # 3. processor 输出帧数与解码帧数的关系决定回映策略
        n = min(n, len(decoded_frames))
        if n <= 0:
            return []

        # 若 processor 做了采样（n != 解码帧数），无法假设均匀分布，
        # 因为我们没有帧级索引信息来反推 processor 到底选了哪些帧。
        # 降级到 pyav 均匀采样。
        if n != len(decoded_frames):
            logger.warning(
                "processor 输出帧数 (%d) 与解码帧数 (%d) 不匹配，"
                "processor 采样行为偏离均匀假设，降级到 pyav 均匀采样",
                n, len(decoded_frames),
            )
            return self._sample_fallback(start_time, end_time, fps, total_frames)

        # n == len(decoded_frames): processor 未二次采样，可 1:1 映射
        return [
            FrameMapping(
                input_index=i,
                original_frame=decoded_indices[i],
                timestamp=decoded_indices[i] / fps,
            )
            for i in range(n)
        ]

    @staticmethod
    def _frame_to_rgb(frame: av.video.frame.VideoFrame) -> Any:
        """将 pyav 帧转为 RGB ndarray 或 PIL Image（取决于可用性）。"""
        if Image is not None:
            img = frame.to_image()
            if img.mode != "RGB":
                img = img.convert("RGB")
            return img
        # fallback: numpy ndarray (不需要 PIL)
        return frame.reformat(format="rgb24").to_ndarray()

    def _decode_frame_range(
        self,
        container: av.container.Container,
        video_stream: av.stream.Stream,
        start_time: float,
        end_time: float,
        fps: float,
        total_frames: int,
    ) -> tuple[list[Any], list[int]]:
        """解码 [start_time, end_time] 区间的帧，返回 (RGB图像列表, 帧号列表)。"""
        start_frame = max(0, min(int(round(start_time * fps)), total_frames - 1))
        end_frame = min(total_frames, int(round(end_time * fps)))

        # seek 到 start_time 附近（前移 0.5s 确保覆盖关键帧）
        seek_pts = int(max(0, start_time - 0.5) / float(video_stream.time_base))
        container.seek(seek_pts, stream=video_stream)

        end_pts = int(end_time / float(video_stream.time_base))

        decoded_frames: list[Any] = []
        decoded_indices: list[int] = []
        # 上限防止死循环
        max_decode = (end_frame - start_frame) * 2 + 30

        for packet in container.demux(video_stream):
            for frame in packet.decode():
                if len(decoded_frames) >= max_decode:
                    break
                pts = frame.pts
                if pts is None:
                    continue
                if pts < seek_pts:
                    continue
                if pts > end_pts:
                    break

                img = self._frame_to_rgb(frame)
                decoded_frames.append(img)

                # 从 PTS 反推帧号
                frame_idx = int(round(pts * float(video_stream.time_base) * fps))
                decoded_indices.append(frame_idx)

            if len(decoded_frames) >= max_decode:
                break
            # check if packet ended our range
            if decoded_frames and hasattr(packet, 'is_keyframe') and packet.is_keyframe and packet.pts is not None and packet.pts > end_pts:
                break

        if not decoded_frames:
            return [], []

        # 如果 seek 到了 start 之前，截断到 start_frame
        trimmed_frames: list[Any] = []
        trimmed_indices: list[int] = []
        for img, idx in zip(decoded_frames, decoded_indices):
            if idx >= start_frame and idx < end_frame:
                trimmed_frames.append(img)
                trimmed_indices.append(idx)

        return trimmed_frames, trimmed_indices

    def _uniform_select(self, n: int, total: int) -> list[int]:
        """从 [0, total) 中均匀选择 n 个索引，去重保序。"""
        if n <= 0 or total <= 0:
            return []
        if n == 1:
            return [0]
        if n >= total:
            return list(range(total))

        step = (total - 1) / (n - 1)
        indices = [int(round(i * step)) for i in range(n)]

        seen: set[int] = set()
        unique: list[int] = []
        for idx in indices:
            if idx not in seen and idx < total:
                seen.add(idx)
                unique.append(idx)
        while len(unique) < n and unique[-1] + 1 < total:
            unique.append(unique[-1] + 1)
        return unique[:n]

    def _sample_fallback(
        self,
        start_time: float,
        end_time: float,
        fps: float,
        total_frames: int,
    ) -> list[FrameMapping]:
        """pyav 均匀帧索引计算（processor 不可用时的 fallback）。"""
        start_frame = max(0, min(int(round(start_time * fps)), total_frames - 1))
        end_frame = max(
            start_frame + 1,
            min(int(round(end_time * fps)), total_frames),
        )
        frame_count = end_frame - start_frame
        n = min(self._max_frames, max(1, frame_count))

        if n == 1:
            indices: list[int] = [start_frame]
        else:
            step = (frame_count - 1) / (n - 1)
            indices = [start_frame + int(round(i * step)) for i in range(n)]

        seen: set[int] = set()
        unique: list[int] = []
        for idx in indices:
            if idx not in seen and idx < total_frames:
                seen.add(idx)
                unique.append(idx)

        return [
            FrameMapping(
                input_index=i,
                original_frame=frame_idx,
                timestamp=frame_idx / fps,
            )
            for i, frame_idx in enumerate(unique)
        ]

    def fingerprint(self) -> str:
        backend_flag = (
            "transformers-loaded"
            if self._processor_loaded
            else "transformers"
            if _transformers_module is not None
            else "no-transformers"
        )
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
        description="MiniCPM-V 4.6 视频预处理器 CLI",
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
