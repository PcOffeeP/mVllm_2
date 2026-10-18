"""开发评测侧预处理对齐训练/服务侧（8 帧逐帧成组、影片级视觉 token 8x64）。

红阶段测试：断言的目标行为由 `finetune/validation/constants.py`、
`finetune/validation/video_loader.py` 与 `finetune/validation/model_runtime.py`
实现，本文件不实现被测行为，也不 import torch / transformers 或加载权重。

全部输入为合成数据：`av` 容器/流/帧用 fake 对象代替，帧是纯合成 PIL 图像。
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import finetune.eval_run as evaluation_cli
from finetune.validation import constants, model_runtime, video_loader
from finetune.validation.video_loader import load_video_frames

# ---------------------------------------------------------------------------
# 合成视频：40 帧、2 fps、20.0 s、PTS 为整数 tick（time_base = 0.5 s）。
# 生产采样规则 min(int(duration * 2), max_frames, total) 在该输入下必然取
# 8 帧（max_frames 默认 8），因此 fake 流的期望帧数是确定的。
# ---------------------------------------------------------------------------
TIME_BASE = 0.5
FAKE_FRAME_COUNT = 40
FAKE_DURATION_SECONDS = FAKE_FRAME_COUNT * TIME_BASE  # 20.0 s
EXPECTED_SAMPLED_FRAMES = 8


class _FakeStreams(list):
    """列表语义 + PyAV 的 ``container.streams.video`` 便捷属性。"""

    @property
    def video(self) -> list["_FakeStream"]:
        return [stream for stream in self if stream.type == "video"]


class _FakeStream:
    type = "video"

    def __init__(self, frame_count: int, time_base: float) -> None:
        self.time_base = time_base
        self.duration = frame_count  # 单位是 PTS tick
        self.frames = frame_count


class _FakeFrame:
    def __init__(self, index: int, size: tuple[int, int], mode: str = "RGB") -> None:
        self.pts = index
        self._size = size
        self._mode = mode

    def to_image(self) -> Image.Image:
        return Image.new(self._mode, self._size)


class _FakePacket:
    def __init__(self, frames: list[_FakeFrame]) -> None:
        self._frames = frames

    def decode(self) -> Any:
        return iter(self._frames)


class _FakeContainer:
    def __init__(self, stream: _FakeStream, frames: list[_FakeFrame]) -> None:
        self.streams = _FakeStreams([stream])
        self.duration = int(stream.duration * stream.time_base * 1_000_000)
        self.seek_calls: list[tuple[int, Any]] = []
        self.closed = False
        self._frames = frames

    def seek(self, offset: int, stream: Any = None, **kwargs: Any) -> None:
        self.seek_calls.append((offset, stream))

    def demux(self, stream: Any = None, **kwargs: Any) -> Any:
        yield _FakePacket(self._frames)

    def decode(self, *args: Any, **kwargs: Any) -> Any:
        yield from self._frames

    def close(self) -> None:
        self.closed = True


def _install_fake_video(
    monkeypatch: pytest.MonkeyPatch,
    *,
    frame_size: tuple[int, int] = (498, 622),
    frame_count: int = FAKE_FRAME_COUNT,
    mode: str = "RGB",
) -> _FakeContainer:
    """把 video_loader 的 ``av`` 模块换成 fake，返回可断言的容器。"""
    frames = [_FakeFrame(index, frame_size, mode) for index in range(frame_count)]
    container = _FakeContainer(_FakeStream(frame_count, TIME_BASE), frames)
    monkeypatch.setattr(
        video_loader,
        "av",
        types.SimpleNamespace(open=lambda *args, **kwargs: container),
    )
    return container


class _BackfillingProcessor:
    """模拟 MiniCPM 处理器：``temporal_ids is None`` 时回填逐帧 ``-1`` 组。

    生产语义（训练机实测）：默认 ``None`` 让处理器自行回填，每帧独立成一组，
    因此视觉段组数 == 帧数；这不是 1 组的时间融合。
    """

    def __init__(self) -> None:
        self.received: list[tuple[int, Any]] = []

    def __call__(self, *, images: list[Any], temporal_ids: Any = None, **kwargs: Any) -> list[list[int]]:
        self.received.append((len(images), temporal_ids))
        if temporal_ids is None:
            return [[-1] for _ in images]
        return [list(group) for group in temporal_ids]


# ---------------------------------------------------------------------------
# A / B：temporal_ids 默认 None，视觉段组数 == 帧数（不再是 1 组融合）
# ---------------------------------------------------------------------------


def test_load_video_frames_defaults_to_no_temporal_fusion(monkeypatch: pytest.MonkeyPatch) -> None:
    """A：默认 temporal_ids 必须是 None，交给处理器逐帧成组。"""
    _install_fake_video(monkeypatch, frame_count=FAKE_FRAME_COUNT)

    frames, temporal_ids, timestamps = load_video_frames("synthetic.mp4")

    assert len(frames) == EXPECTED_SAMPLED_FRAMES
    assert len(timestamps) == EXPECTED_SAMPLED_FRAMES
    assert temporal_ids is None


def test_visual_groups_equal_frame_count_not_a_single_fused_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B：处理器按生产语义回填后，视觉段组数 == 帧数，且明确不是 1 组融合。"""
    _install_fake_video(monkeypatch, frame_count=FAKE_FRAME_COUNT)
    frames, temporal_ids, _ = load_video_frames("synthetic.mp4")
    processor = _BackfillingProcessor()

    groups = processor(
        images=frames,
        temporal_ids=temporal_ids,
        max_slice_nums=2,
        use_image_id=False,
        text="rendered prompt",
    )

    assert len(groups) == len(frames) == EXPECTED_SAMPLED_FRAMES
    assert len(groups) != 1, "8 帧必须各自成组，不能退化为 1 组时间融合"
    assert all(group == [-1] for group in groups)
    assert (EXPECTED_SAMPLED_FRAMES * 64) == 512


# ---------------------------------------------------------------------------
# C：像素规整与 LlamaFactory MiniCPMVPlugin._preprocess_image 完全一致
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_size", "expected_size"),
    [
        # 训练机 A8 实测 image_sizes（见 preprocess-probe-20261017.md §9.1 / §9.2）
        ((498, 622), (229, 286)),
        ((926, 896), (260, 251)),
    ],
)
def test_pixel_regularization_downsizes_like_production(
    monkeypatch: pytest.MonkeyPatch,
    source_size: tuple[int, int],
    expected_size: tuple[int, int],
) -> None:
    """C：超过 max_pixels 的帧按 sqrt 比例 int() 截断缩放，与生产一致。"""
    _install_fake_video(monkeypatch, frame_size=source_size, frame_count=FAKE_FRAME_COUNT)

    frames, _, _ = load_video_frames("synthetic.mp4")

    assert [frame.size for frame in frames] == [expected_size] * EXPECTED_SAMPLED_FRAMES
    # video_max_pixels = 65536（与常量断言解耦，故此处写字面值）
    assert all(frame.width * frame.height <= 65536 for frame in frames)


def test_pixel_regularization_upsizes_frames_below_min_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C：小于 min_pixels 的帧按同一公式放大（8x8 -> 16x16，min_pixels=256）。"""
    _install_fake_video(monkeypatch, frame_size=(8, 8), frame_count=FAKE_FRAME_COUNT)

    frames, _, _ = load_video_frames("synthetic.mp4")

    assert [frame.size for frame in frames] == [(16, 16)] * EXPECTED_SAMPLED_FRAMES
    assert all(frame.width * frame.height >= 256 for frame in frames)


@pytest.mark.parametrize("size", [(229, 286), (260, 251), (16, 16)])
def test_regularized_frames_stay_below_slice_threshold(size: tuple[int, int]) -> None:
    """C：规整后的尺寸满足 get_sliced_grid 不切片的判据 w*h/(448*448) < 1。"""
    width, height = size

    assert width * height / (448 * 448) < 1


# ---------------------------------------------------------------------------
# E：回退开关打开时恢复旧行为（1 组时间融合），默认必须关闭
# ---------------------------------------------------------------------------


def test_temporal_fusion_fallback_restores_single_fused_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E：temporal_fusion=True 回到旧行为 temporal_ids == [[0] * n]。"""
    _install_fake_video(monkeypatch, frame_count=FAKE_FRAME_COUNT)

    frames, temporal_ids, _ = load_video_frames("synthetic.mp4", temporal_fusion=True)

    assert len(frames) == EXPECTED_SAMPLED_FRAMES
    assert temporal_ids == [[0] * EXPECTED_SAMPLED_FRAMES]


def test_temporal_fusion_legacy_switch_defaults_off() -> None:
    """E：回退开关默认关闭，开发评测侧默认走逐帧成组语义。"""
    assert constants.TEMPORAL_FUSION_LEGACY is False


# ---------------------------------------------------------------------------
# 常量（规格 1 / G）
# ---------------------------------------------------------------------------


def test_video_pixel_and_slice_constants_match_training_contract() -> None:
    """规格 1：像素与切片常量取训练/服务侧的 film 级取值。"""
    assert constants.VIDEO_MAX_PIXELS == 65536
    assert constants.VIDEO_MIN_PIXELS == 256
    assert constants.VIDEO_SLICE_MAX_NUMS == 2


def test_inference_timeout_constant_matches_service_backend() -> None:
    """G：单次推理超时默认 600 s，与服务后端 600 s 对齐。"""
    assert constants.INFERENCE_TIMEOUT_SECONDS == 600.0


# ---------------------------------------------------------------------------
# 运行时 fake：processor / model / torch
# ---------------------------------------------------------------------------


class _FakeInputs(dict):
    def to(self, device: str) -> "_FakeInputs":
        return self


class _FakeNoGrad:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


@pytest.fixture
def fake_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    """本机没有 torch，注入最小 no_grad 替身。"""
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=lambda: _FakeNoGrad()))


class _RuntimeState:
    def __init__(self, *, sleep_seconds: float = 0.0) -> None:
        self.generate_calls = 0
        self.sleep_seconds = sleep_seconds
        self.processor_kwargs: dict[str, Any] = {}


class _FakeProcessor:
    def __init__(self, state: _RuntimeState) -> None:
        self._state = state
        self.tokenizer = types.SimpleNamespace(encode=lambda text, **kwargs: [])

    def apply_chat_template(
        self, messages: list[dict[str, Any]], tokenize: bool = False, add_generation_prompt: bool = True
    ) -> str:
        return "rendered prompt"

    def __call__(self, **kwargs: Any) -> _FakeInputs:
        self._state.processor_kwargs.update(kwargs)
        return _FakeInputs({"input_ids": "ids", "image_sizes": "processor-only"})


class _FakeModel:
    device = "cpu"

    def __init__(self, state: _RuntimeState) -> None:
        self._state = state

    def generate(self, **kwargs: Any) -> list[str]:
        self._state.generate_calls += 1
        if self._state.sleep_seconds:
            time.sleep(self._state.sleep_seconds)
        return ["{}"]


@pytest.fixture
def synthetic_frame_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 run_model_on_video_detailed 拿到合成帧，避开真实解码。"""
    monkeypatch.setattr(
        video_loader,
        "load_video_frames",
        lambda *args, **kwargs: ([Image.new("RGB", (32, 32))], None, [0.0]),
    )


# ---------------------------------------------------------------------------
# F：max_slice_nums 默认取 VIDEO_SLICE_MAX_NUMS（2），且显式传参可覆盖
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fake_torch", "synthetic_frame_loader")
def test_processor_receives_video_slice_max_nums_by_default(tmp_path: Path) -> None:
    """F：默认 max_slice_nums 由 1 改为 VIDEO_SLICE_MAX_NUMS（=2）。"""
    state = _RuntimeState()

    model_runtime.run_model_on_video_detailed(
        _FakeModel(state), _FakeProcessor(state), tmp_path / "sample.mp4", "user prompt"
    )

    assert state.processor_kwargs["max_slice_nums"] == 2


@pytest.mark.usefixtures("fake_torch", "synthetic_frame_loader")
def test_processor_max_slice_nums_can_be_overridden(tmp_path: Path) -> None:
    """F：显式传参会覆盖默认值。"""
    state = _RuntimeState()

    model_runtime.run_model_on_video_detailed(
        _FakeModel(state),
        _FakeProcessor(state),
        tmp_path / "sample.mp4",
        "user prompt",
        max_slice_nums=1,
    )

    assert state.processor_kwargs["max_slice_nums"] == 1


# ---------------------------------------------------------------------------
# D：单次推理超时 -> InferenceTimeoutError、不重试、记为 runtime failure
# ---------------------------------------------------------------------------


def test_inference_timeout_error_is_a_runtime_error() -> None:
    """D：InferenceTimeoutError 继承 RuntimeError，才能被既有记录路径归类为 runtime failure。"""
    assert issubclass(model_runtime.InferenceTimeoutError, RuntimeError)


@pytest.mark.usefixtures("fake_torch", "synthetic_frame_loader")
def test_inference_timeout_raises_dedicated_error_without_retry(tmp_path: Path) -> None:
    """D：generate 睡过超时后抛 InferenceTimeoutError，且 generate 只调用一次。"""
    state = _RuntimeState(sleep_seconds=0.5)

    with pytest.raises(model_runtime.InferenceTimeoutError, match="inference timeout"):
        model_runtime.run_model_on_video_detailed(
            _FakeModel(state),
            _FakeProcessor(state),
            tmp_path / "sample.mp4",
            "user prompt",
            timeout_seconds=0.05,
        )

    assert state.generate_calls == 1


def test_inference_timeout_is_recorded_as_runtime_failure_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D：经 evaluate_one 记录路径观察超时（不改 eval_run.py，只包一层固定超时）。"""
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=lambda: _FakeNoGrad()))
    monkeypatch.setattr(
        video_loader,
        "load_video_frames",
        lambda *args, **kwargs: ([Image.new("RGB", (32, 32))], None, [0.0]),
    )
    state = _RuntimeState(sleep_seconds=0.5)
    real_runtime = model_runtime.run_model_on_video_detailed

    def fixed_timeout_runtime(*args: Any, **kwargs: Any) -> Any:
        kwargs["timeout_seconds"] = 0.05
        return real_runtime(*args, **kwargs)

    monkeypatch.setattr(evaluation_cli, "run_model_on_video_detailed", fixed_timeout_runtime)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")
    sample = {
        "candidate_id": "video_0001",
        "source_video": "video_0001",
        "video_path": str(video),
        "target": {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
    }

    record = evaluation_cli.evaluate_one(
        sample=sample,
        model=_FakeModel(state),
        processor=_FakeProcessor(state),
        system_prompt="system prompt",
        user_prompt="user prompt",
        media_root=tmp_path,
    )

    assert record["runtime_error"] is not None
    assert "InferenceTimeoutError" in record["runtime_error"]
    assert "inference timeout" in record["runtime_error"].lower()
    assert record["strict_valid"] is False
    assert state.generate_calls == 1


# ---------------------------------------------------------------------------
# 回退开关经 run_model_on_video_detailed 真的透传到 load_video_frames
#
# 覆盖缺口 (e)：若 runtime 调用 load_video_frames 时丢掉
# ``temporal_fusion=resolved_temporal_fusion``，loader 会退回自身默认值 False，
# 这里捕获关键字实参即可变红（下面的 fake 不返回固定值，严格按收到的开关决定
# temporal_ids，因此丢参时 processor 侧的断言也会同时变红）。
# ---------------------------------------------------------------------------
class _RecordingFrameLoader:
    """fake load_video_frames：记录关键字实参，并按开关决定分组形态。"""

    def __init__(self, frame_count: int = 3) -> None:
        self.frame_count = frame_count
        self.calls: list[dict[str, Any]] = []

    def __call__(self, video_path: Any, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        frames = [Image.new("RGB", (32, 32)) for _ in range(self.frame_count)]
        timestamps = [float(index) for index in range(self.frame_count)]
        temporal_ids = [[0] * self.frame_count] if kwargs.get("temporal_fusion") else None
        return frames, temporal_ids, timestamps


@pytest.mark.usefixtures("fake_torch")
def test_runtime_forwards_temporal_fusion_true_to_frame_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E：temporal_fusion=True 必须作为关键字实参传给 load_video_frames，并得到 1 组。"""
    loader = _RecordingFrameLoader(frame_count=3)
    monkeypatch.setattr(video_loader, "load_video_frames", loader)
    state = _RuntimeState()

    model_runtime.run_model_on_video_detailed(
        _FakeModel(state),
        _FakeProcessor(state),
        tmp_path / "sample.mp4",
        "user prompt",
        temporal_fusion=True,
    )

    assert loader.calls[0].get("temporal_fusion") is True
    assert state.processor_kwargs["temporal_ids"] == [[0, 0, 0]]


@pytest.mark.usefixtures("fake_torch")
def test_runtime_forwards_default_temporal_fusion_false_to_frame_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E：默认不传时 runtime 必须显式把 False 传给 load_video_frames，processor 收到 None。"""
    loader = _RecordingFrameLoader(frame_count=3)
    monkeypatch.setattr(video_loader, "load_video_frames", loader)
    state = _RuntimeState()

    model_runtime.run_model_on_video_detailed(
        _FakeModel(state), _FakeProcessor(state), tmp_path / "sample.mp4", "user prompt"
    )

    assert loader.calls[0].get("temporal_fusion") is False
    assert state.processor_kwargs["temporal_ids"] is None


# ---------------------------------------------------------------------------
# 生产「全 -1 逐帧成组」语义的静态锚点（覆盖缺口 (5)）
#
# 本机没有 torch/transformers，也没有模型权重，无法跑 MiniCPM-V 前向；这里只对
# 模型源码做文本级断言，钉住三处关键语句：缺省分支逐帧回填 -1、temporal_ids 写回
# batch feature、resampler 的组数由 len(temporal_ids) 决定。真实前向数值必须在
# 训练机验证。不复制任何切片/重采样算法。
# ---------------------------------------------------------------------------
MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "minicpm-v-4.5"


def _model_source(filename: str) -> str:
    path = MODEL_DIR / filename
    if not path.is_file():
        pytest.skip(f"MiniCPM-V model source is not present: {path}")
    return path.read_text(encoding="utf-8")


def _indented_block(source: str, header_prefix: str) -> str:
    """取以 ``header_prefix`` 开头的语句及其更深缩进的全部后继行。"""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(header_prefix):
            indent = len(line) - len(line.lstrip())
            block = [line]
            for following in lines[index + 1 :]:
                if following.strip() and len(following) - len(following.lstrip()) <= indent:
                    break
                block.append(following)
            return "\n".join(block)
    raise AssertionError(f"没有在源码中找到语句：{header_prefix}")


def test_processor_source_backfills_minus_one_temporal_id_per_frame() -> None:
    """生产语义静态锚点：temporal_ids 缺省时逐帧回填，每帧一组、组 id 全 -1。"""
    source = _model_source("image_processing_minicpmv.py")

    branch = _indented_block(source, "if temporal_ids is None:")

    assert "tp_ids.extend([[-1]] * len(image_patches))" in branch
    # 语义绑定：必须是「全 -1 的组」×「每帧的 patch 数」，而不是单组融合
    assert "[[-1]]" in branch
    assert "len(image_patches)" in branch
    # 逐帧循环 append，组数因此等于帧数
    assert "for image in _images:" in branch


def test_processor_source_writes_temporal_ids_back_into_batch_feature() -> None:
    """生产语义静态锚点：逐帧 tp_ids 被写回输出，处理器才真正影响视觉段组数。"""
    source = _model_source("image_processing_minicpmv.py")

    assert "temporal_ids_list.append(tp_ids)" in source
    assert '"temporal_ids": temporal_ids_list' in source


def test_resampler_group_count_is_driven_by_temporal_ids_length() -> None:
    """生产语义静态锚点：resampler 的批大小（组数）由 len(temporal_ids) 决定。"""
    source = _model_source("resampler.py")

    block = _indented_block(source, "def batch_attn_forward(")

    assert "bs = len(temporal_ids)" in block
    assert "for tp in temporal_ids:" in block
