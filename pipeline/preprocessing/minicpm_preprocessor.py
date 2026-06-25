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
import functools

try:
    import transformers as _transformers_module
except Exception:  # pragma: no cover - 训练机才安装
    _transformers_module = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


logger = logging.getLogger(__name__)


def _hash_model_files(model_path_or_name: str) -> dict[str, str | None]:
    """对模型目录中的关键配置文件计算内容 hash，区分不同权重/版本。

    若 ``model_path_or_name`` 指向本地目录，则读取 ``config.json`` 和
    ``preprocessor_config.json``，分别计算 SHA-256 并取前 16 位。
    不存在的文件对应值为 ``None``；远程模型名或文件路径不存在时全部返回
    ``None``，此时 fingerprint 退化为仅使用路径字符串。
    """
    model_path = Path(model_path_or_name)
    hashes: dict[str, str | None] = {"config": None, "preprocessor": None}
    if not model_path.is_dir():
        return hashes

    for key, filename in (
        ("config", "config.json"),
        ("preprocessor", "preprocessor_config.json"),
    ):
        candidate = model_path / filename
        if candidate.is_file():
            hashes[key] = hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
    return hashes


def _sanitize_model_path(model_path: str) -> str:
    """如果模型路径的目录名包含点号（会导致 trust_remote_code 模块导入失败），
    自动创建无点号的符号链接并返回新路径。如果链接已存在则复用。"""
    path = Path(model_path).resolve()
    dir_name = path.name
    if "." in dir_name or "-" in dir_name:
        safe_name = dir_name.replace(".", "_").replace("-", "_")
        safe_path = path.parent / safe_name
        if not safe_path.exists():
            safe_path.symlink_to(path, target_is_directory=True)
        return str(safe_path)
    return str(model_path)


def configure_processor_max_frames(processor: Any, max_frames: int = 8) -> Any:
    """Set and verify the real MiniCPM-V processor frame limit.

    MiniCPM-V 4.5 does not expose a separate ``video_processor`` sub-component.
    The top-level ``AutoProcessor`` (``MiniCPMVProcessor``) handles video frames
    directly. We therefore configure max-frames on the top-level processor and
    return the processor itself as the callable used for frame processing.
    """
    if max_frames != 8:
        raise ValueError("MiniCPM-V contract requires max_frames=8")

    configured = False
    video_processor = getattr(processor, "video_processor", None)
    video_processor_configured = False

    # 4.5 风格：属性通常挂在 image_processor 或顶层 processor/config 上。
    # 4.6 风格：属性也可能挂在独立的 video_processor 子组件上，保持兼容。
    candidates = [
        (getattr(processor, "image_processor", None), "max_frames"),
        (getattr(processor, "image_processor", None), "video_maxlen"),
        (video_processor, "max_frames"),
        (video_processor, "video_maxlen"),
        (getattr(processor, "config", None), "max_frames"),
        (getattr(processor, "config", None), "video_maxlen"),
        (processor, "max_frames"),
        (processor, "video_maxlen"),
    ]

    for target, attribute in candidates:
        if target is None:
            continue
        if hasattr(target, attribute):
            setattr(target, attribute, max_frames)
            if getattr(target, attribute) != max_frames:
                raise RuntimeError(f"failed to set actual processor {attribute}=8")
            configured = True
            if target is video_processor:
                video_processor_configured = True

    if not configured:
        # MiniCPM-V 4.5 等版本没有 max_frames 属性，跳过设置
        return processor

    # 4.5 返回顶层 processor，由顶层统一处理视频帧；
    # 4.6 返回实际配置过的 video_processor 子组件。
    if video_processor is not None and video_processor_configured:
        return video_processor
    return processor


# ---------------------------------------------------------------------------
# 辅助：环境能力检测
# ---------------------------------------------------------------------------


def _processor_environment_unsupported() -> bool:
    """检测当前环境是否可安全加载 transformer 模型。

    Mac（mps／无 GPU）上加载大型视觉模型容易 OOM，返回 True 表示当前
    环境不支持正式预处理校验。正式 sample() 会 fail closed。
    """
    import platform
    if platform.system() != "Darwin":
        return False  # Linux 训练机，正常加载
    # Mac 上 transformers / torch 可能可用但仍不期望加载大模型
    return True


# ---------------------------------------------------------------------------
# MiniCPM-V 4.5 视频预处理器
# ---------------------------------------------------------------------------


class MiniCPMVideoPreprocessor(VideoPreprocessor):
    """MiniCPM-V 4.5 视频处理器。

    加载 `transformers.AutoProcessor` 后由顶层 ``MiniCPMVProcessor`` 直接处理
    视频帧。4.5 版本没有独立的 ``video_processor`` 子组件，因此
    ``self._video_processor`` 实际保存的是顶层 processor 引用，仅用于标记
    processor 已就绪；实际调用均通过 ``self._processor(images=..., return_tensors="pt")``
    完成。processor 不可用时直接失败；不得用理论 FPS 或均匀采样伪造模型实际帧。

    Architecture
    ------------
    * `__init__` 尝试预加载 processor；若失败（Mac／import 错误）标记延迟加载。
    * `_ensure_processor()` 在首次需要时加载。
    * `sample()` 优先走 processor 路径：解码帧 → 顶层 processor → 输出帧数回映。
    * `healthcheck()` 生成临时视频做集成验证。
    """

    NAME = "minicpm-v-4.5"
    EXPECTED_MAX_FRAMES = 8

    def __init__(
        self,
        model_path_or_name: str,
        max_frames: int = EXPECTED_MAX_FRAMES,
        processor: Any | None = None,
    ) -> None:
        self._model_path_or_name = model_path_or_name
        self._max_frames = max_frames
        self._processor = processor
        self._video_processor = (
            configure_processor_max_frames(processor, max_frames)
            if processor is not None
            else None
        )
        self._processor_loaded = processor is not None
        self.last_tensor_digest: str | None = None
        self.last_tensor_shape: list[int] | None = None

        # 尝试预加载；忽略 Mac 上可预见的失败
        if processor is None:
            self._try_load_processor()

    # ------------------------------------------------------------------
    # Processor 生命周期
    # ------------------------------------------------------------------

    def _try_load_processor(self) -> None:
        """预加载 processor；失败不抛异常，留待延迟加载。"""
        if _transformers_module is None:
            return
        if _processor_environment_unsupported():
            return
        try:
            self._load_processor()
        except Exception as exc:
            logger.info(
                "预加载 processor 失败（将在首次 sample 时重试）: %s", exc,
            )

    def _load_processor(self) -> None:
        """实际加载 ``transformers.AutoProcessor`` 并配置 max_frames。"""
        from transformers import AutoProcessor

        model_path = _sanitize_model_path(self._model_path_or_name)
        processor = AutoProcessor.from_pretrained(
            model_path,
            trust_remote_code=True,
            local_files_only=True,
        )
        # 4.5 返回顶层 processor 本身作为帧处理可调用对象。
        frame_processor = configure_processor_max_frames(processor, self._max_frames)
        self._processor = processor
        self._video_processor = frame_processor
        self._processor_loaded = True

    def _ensure_processor(self) -> None:
        """确保 processor 已加载；不可用时由 sample() 明确失败。"""
        if self._processor_loaded:
            return
        if _transformers_module is None:
            return
        try:
            self._load_processor()
            logger.info("延迟加载 processor 成功: %s", type(self._processor).__name__)
        except Exception as exc:
            logger.warning("processor 加载失败: %s", exc)

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
            backend = "transformers-unavailable"

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
        if _processor_environment_unsupported():
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

        仅使用真实顶层 ``processor`` 做帧选择。
        """
        frame_index_by_timestamp = self._actual_frame_index_map(video_path)
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

            total_frames = len(frame_index_by_timestamp)

            # --- 尝试使用真实 processor ---
            self._ensure_processor()
            if self._processor_loaded and self._video_processor is not None:
                return self._sample_with_processor(
                    container, video_stream,
                    start_time, end_time, total_frames, frame_index_by_timestamp,
                )

            raise RuntimeError(
                "MiniCPM-V processor 不可用；拒绝用理论 FPS/均匀采样 "
                "伪造模型实际输入帧"
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
        total_frames: int,
        frame_index_by_timestamp: dict[float, int],
    ) -> list[FrameMapping]:
        """用顶层 processor 处理解码帧，返回真实帧号映射。

        允许真实 processor 按其已锁定的 max_frames=8 选择帧；
        通过逐帧独立调用 + 像素比对确认保留帧，
        映射回解码帧号。不再静默回退到 pyav 均匀采样。
        """
        # 1. 解码区间内的帧
        decoded_frames, decoded_indices, decoded_timestamps = self._decode_frame_range(
            container, video_stream, start_time, end_time, total_frames,
            frame_index_by_timestamp,
        )
        if not decoded_frames:
            return []

        # 2. 调用真实顶层 processor（失败抛异常，不静默回退）
        try:
            video_inputs = self._processor(
                text="<image>./</image>" * len(decoded_frames),
                images=decoded_frames,
                return_tensors="pt",
            )
        except Exception as exc:
            raise RuntimeError(
                f"processor 调用失败: {exc}"
            ) from exc

        # 4.5 输出 key 为 pixel_values；4.6 风格为 pixel_values_videos。
        pixel_values = video_inputs.get("pixel_values_videos")
        if pixel_values is None:
            pixel_values = video_inputs.get("pixel_values")
        if pixel_values is None:
            raise RuntimeError(
                "processor 输出不含 pixel_values_videos 或 pixel_values"
            )

        shape = tuple(pixel_values.shape)
        if len(shape) == 5:
            # 4.6 风格: (B, T, C, H, W)
            n = int(shape[1])
            selected_pixel_values = pixel_values[0]
        elif len(shape) == 4:
            # 4.5 风格: (T, C, H, W)
            n = int(shape[0])
            selected_pixel_values = pixel_values
        else:
            raise RuntimeError(f"无法识别 pixel_values 形状: {shape}")
        if n > self._max_frames:
            raise RuntimeError(
                f"processor 实际输出 {n} 帧，超过契约上限 {self._max_frames}"
            )
        if n > len(decoded_frames):
            raise RuntimeError(
                f"processor 输出帧数 {n} 大于解码帧数 {len(decoded_frames)}"
            )
        if n <= 0:
            return []

        try:
            import torch
            if isinstance(pixel_values, torch.Tensor):
                raw_tensor = pixel_values.detach().cpu().contiguous()
                self.last_tensor_digest = hashlib.sha256(
                    raw_tensor.view(dtype=torch.uint8).numpy().tobytes()
                ).hexdigest()
                self.last_tensor_shape = list(shape)
        except ImportError:  # pragma: no cover - unit environment without torch
            pass

        # 3. 确定帧映射
        if n == len(decoded_frames):
            # processor 未二次采样，1:1 映射
            return [
                FrameMapping(
                    input_index=i,
                    original_frame=decoded_indices[i],
                    timestamp=decoded_timestamps[i],
                )
                for i in range(n)
            ]

        # processor 做了抽帧，通过逐帧独立调用确认保留帧
        return self._match_processor_frames(
            decoded_frames, decoded_indices, decoded_timestamps, selected_pixel_values, n,
        )


    def _match_processor_frames(
        self,
        decoded_frames: list[Any],
        decoded_indices: list[int],
        decoded_timestamps: list[float],
        batch_pixel_values: Any,
        n: int,
    ) -> list[FrameMapping]:
        """逐帧独立调用顶层 processor，通过像素比对确认保留帧。

        对每个解码帧单独调用 ``processor(images=[frame], return_tensors="pt")``，
        再将批量输出的每一帧与独立输出做 L1 距离匹配，
        映射回 ``decoded_indices``。
        """
        import torch

        # 逐帧调用顶层 processor
        individual_pvs: list[Any] = []
        for frame in decoded_frames:
            try:
                ind_result = self._processor(
                    text="<image>./</image>",
                    images=[frame],
                    return_tensors="pt",
                )
                ind_pv = ind_result.get("pixel_values_videos")
                if ind_pv is None:
                    ind_pv = ind_result.get("pixel_values")
                if ind_pv is not None and ind_pv.shape[0] > 0:
                    if len(ind_pv.shape) == 5:
                        individual_pvs.append(ind_pv[0, 0].float())
                    elif len(ind_pv.shape) == 4:
                        individual_pvs.append(ind_pv[0].float())
                    else:
                        individual_pvs.append(None)
                else:
                    individual_pvs.append(None)
            except Exception:
                individual_pvs.append(None)

        # 批量输出与独立输出做像素比对
        results: list[FrameMapping] = []
        used: set[int] = set()

        for batch_idx in range(n):
            batch_frame = batch_pixel_values[batch_idx].float()
            best_match = -1
            best_diff = float("inf")

            for i, ind_pv in enumerate(individual_pvs):
                if ind_pv is None:
                    continue
                if i in used:
                    continue
                if batch_frame.shape != ind_pv.shape:
                    continue
                diff = torch.abs(batch_frame - ind_pv).mean().item()
                if diff < best_diff:
                    best_diff = diff
                    best_match = i

            if best_match < 0:
                raise RuntimeError(
                    f"无法确定 batch 帧 {batch_idx} 对应哪个解码帧"
                )

            used.add(best_match)
            results.append(
                FrameMapping(
                    input_index=len(results),
                    original_frame=decoded_indices[best_match],
                    timestamp=decoded_timestamps[best_match],
                )
            )

        if not results:
            raise RuntimeError(
                "逐帧比对未找到任何匹配"
            )

        return results

    @staticmethod
    def _frame_to_rgb(frame: av.video.frame.VideoFrame) -> Any:
        """将 pyav 帧转为 RGB ndarray 或 PIL Image（取决于可用性）。"""
        if Image is not None:
            img = frame.to_image()
            if img.mode != "RGB":
                img = img.convert("RGB")
            return img
        # PIL unavailable: use an RGB numpy ndarray.
        return frame.reformat(format="rgb24").to_ndarray()

    def _decode_frame_range(
        self,
        container: av.container.Container,
        video_stream: av.stream.Stream,
        start_time: float,
        end_time: float,
        total_frames: int,
        frame_index_by_timestamp: dict[float, int],
    ) -> tuple[list[Any], list[int], list[float]]:
        """解码区间帧，返回 RGB、原始帧序号和实际 PTS 时间戳。"""
        # seek 到 start_time 附近（前移 0.5s 确保覆盖关键帧）
        seek_pts = int(max(0, start_time - 0.5) / float(video_stream.time_base))
        container.seek(seek_pts, stream=video_stream)

        end_pts = int(end_time / float(video_stream.time_base))

        decoded_frames: list[Any] = []
        decoded_indices: list[int] = []
        decoded_timestamps: list[float] = []
        # 上限防止死循环
        max_decode = total_frames + 30

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

                timestamp = float(pts * video_stream.time_base)
                frame_idx = frame_index_by_timestamp.get(round(timestamp, 9))
                if frame_idx is None:
                    raise RuntimeError("解码帧 PTS 无法映射到实际原始帧序号")
                decoded_indices.append(frame_idx)
                decoded_timestamps.append(timestamp)

            if len(decoded_frames) >= max_decode:
                break
            # check if packet ended our range
            if decoded_frames and hasattr(packet, 'is_keyframe') and packet.is_keyframe and packet.pts is not None and packet.pts > end_pts:
                break

        if not decoded_frames:
            return [], [], []

        # Seek may land before the requested start; trim by actual PTS.
        trimmed_frames: list[Any] = []
        trimmed_indices: list[int] = []
        trimmed_timestamps: list[float] = []
        for img, idx, timestamp in zip(decoded_frames, decoded_indices, decoded_timestamps):
            if start_time <= timestamp < end_time:
                trimmed_frames.append(img)
                trimmed_indices.append(idx)
                trimmed_timestamps.append(timestamp)

        return trimmed_frames, trimmed_indices, trimmed_timestamps

    @staticmethod
    @functools.lru_cache(maxsize=200)
    def _actual_frame_index_map(video_path: str) -> dict[float, int]:
        """Decode actual PTS in display order and map each timestamp to its ordinal."""
        mapping: dict[float, int] = {}
        probe_container = av.open(video_path, "r")
        try:
            stream = next(s for s in probe_container.streams if s.type == "video")
            for index, frame in enumerate(probe_container.decode(stream)):
                if frame.pts is None:
                    raise RuntimeError("视频帧缺少 PTS，无法建立真实帧映射")
                timestamp = float(frame.pts * stream.time_base)
                key = round(timestamp, 9)
                if key in mapping:
                    raise RuntimeError("视频帧 PTS 重复，无法建立唯一帧映射")
                mapping[key] = index
        finally:
            probe_container.close()
        if not mapping:
            raise RuntimeError("视频不包含可解码帧")
        return mapping

    def fingerprint(self) -> str:
        """返回包含模型权重/版本可验证信息的配置指纹。

        指纹包含：处理器名称、模型路径/名称、关键模型配置文件
        （``config.json`` / ``preprocessor_config.json``）的内容 hash、
        max_frames 以及 backend 加载状态。本地模型目录下配置文件存在时，
        取其 SHA-256 前 16 位以 ``cfg=`` / ``pre=`` 形式拼入；远程模型名
        或非目录路径不存在时退化为仅使用路径字符串。

        Raises:
            ValueError: 当 ``model_path_or_name`` 指向本地目录且
                ``config.json`` 与 ``preprocessor_config.json`` 均不存在时，
                抛出明确错误说明缺少的文件，避免在配置文件缺失时生成
                不可区分的退化指纹。
        """
        backend_flag = (
            "transformers-loaded"
            if self._processor_loaded
            else "transformers"
            if _transformers_module is not None
            else "no-transformers"
        )
        parts = [f"{self.NAME}:{self._model_path_or_name}"]
        file_hashes = _hash_model_files(self._model_path_or_name)

        model_path = Path(self._model_path_or_name)
        if (
            model_path.is_dir()
            and file_hashes["config"] is None
            and file_hashes["preprocessor"] is None
        ):
            raise ValueError(
                f"模型目录 {model_path} 缺少关键配置文件: "
                "config.json 和 preprocessor_config.json"
            )

        if file_hashes["config"]:
            parts.append(f"cfg={file_hashes['config']}")
        if file_hashes["preprocessor"]:
            parts.append(f"pre={file_hashes['preprocessor']}")
        parts.append(f"max_frames={self._max_frames}")
        parts.append(f"backend={backend_flag}")
        return ":".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.preprocessing.minicpm_preprocessor",
        description="MiniCPM-V 4.5 视频预处理器 CLI",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="检查配置是否满足 max_frames=8 及 transformers 是否可用",
    )
    parser.add_argument(
        "--model",
        default=str(Path(__file__).resolve().parents[2] / "models" / "minicpm-v-4.5"),
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
