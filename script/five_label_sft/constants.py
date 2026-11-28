"""Constants, schema identifiers, and verified presets for Qwen3-VL five-label SFT."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BUILD_SUMMARY_SCHEMA = "five-label-sft-build-summary/1"
PREFLIGHT_REPORT_SCHEMA = "five-label-sft-preflight/1"
CONFIG_MANIFEST_SCHEMA = "five-label-sft-config-manifest/1"
FRAME_LINEAGE_SCHEMA = "five-label-sft-frame-lineage/1"
RUNTIME_VERIFY_SCHEMA = "five-label-sft-runtime-verify/1"
CORRESPONDENCE_AUDIT_SCHEMA = "five-label-sft-correspondence-audit/1"
ADAPTER_PROVENANCE_SCHEMA = "five-label-sft-adapter-provenance/1"

SUPPORTED_FOLDS = (0, 1, 2)
SUPPORTED_MODALITIES = ("images", "video")
SUPPORTED_NUM_FRAMES = (8, 16)
WIDTH_BUCKETS = ("w_le_200", "w_200_400", "w_gt_400")

# Default relative project paths (read-only inputs).
DEFAULT_MANIFEST_REL = "data/sub_video/manifest.json"
DEFAULT_REVIEWS_REL = "data/subvideo-review/reviews.json"
DEFAULT_SPLITS_DIR_REL = "data/splits/three-fold"
DEFAULT_EXCLUSIONS_REL = "data/splits/dev-exclusions.json"
DEFAULT_EVAL_DEV_REL = "data/eval-subsets/eval-dev-v1.json"
DEFAULT_EVAL_TEST_REL = "data/eval-subsets/eval-test-v1.json"
DEFAULT_PROMPT_REL = "script/five_label_eval/prompts/five_label_v2.txt"
DEFAULT_ROI_MANIFEST_REL = "data/roi/manifest.json"
DEFAULT_NCC_THRESHOLD = 0.80

# Qwen3-VL-8B-Instruct model & vision geometry constants (transformers 4.57.6 / 5.22.2).
DEFAULT_BASE_MODEL_PATH = "/data/models/Qwen3-VL-8B-Instruct"
DEFAULT_SERVED_MODEL_NAME = "Qwen3-VL-8B-Instruct"
DEFAULT_TEMPLATE = "qwen3_vl_nothink"

QWEN3_VL_PATCH_SIZE = 16
QWEN3_VL_MERGE_SIZE = 2
QWEN3_VL_SPATIAL_FACTOR = QWEN3_VL_PATCH_SIZE * QWEN3_VL_MERGE_SIZE  # 32
QWEN3_VL_TEMPORAL_PATCH_SIZE = 2

# Model native processor defaults from Qwen3-VL-8B-Instruct preprocessor_config.json & video_preprocessor_config.json.
QWEN3_VL_IMAGE_PROCESSOR_MIN_PIXELS = 65_536
QWEN3_VL_IMAGE_PROCESSOR_MAX_PIXELS = 16_777_216
QWEN3_VL_VIDEO_PROCESSOR_MIN_PIXELS = 4_096
QWEN3_VL_VIDEO_PROCESSOR_MAX_PIXELS = 25_165_824

# Empirical text/wrapper token budgets anchored to DEC-008 Run A (five_label_v2.txt + Qwen3-VL chat template):
# - 8f images 804x1072 measured prompt_tokens = 7,430 = 6,800 image_pad + 16 vision_bos/eos + 614 prompt/template.
# - Video wrapper per temporal pair (2 frames): "<t.t seconds><|vision_start|><|vision_end|>" = 8 tokens (#5).
# - Target five-label JSON measured completion_tokens ~ 93; reserve 128 tokens for safe upper bound.
BASE_PROMPT_CHAR_LEN = 890
BASE_PROMPT_TEMPLATE_TOKENS = 620
IMAGE_WRAPPER_TOKENS_PER_FRAME = 2
VIDEO_WRAPPER_TOKENS_PER_PAIR = 8
TARGET_JSON_TOKEN_BUDGET = 128

# Training machine runtime safety constants (DEC-008 §2).
PURE_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
VLM_EVAL_VLLM_BIN = "/home/liuyang/miniconda3/envs/vlm-eval/bin/vllm"
VLM_SFT_PYTHON_BIN = "/home/liuyang/miniconda3/envs/vlm-sft/bin/python"
VLM_SFT_LLAMAFACTORY_CLI = "/home/liuyang/miniconda3/envs/vlm-sft/bin/llamafactory-cli"
CUDA_ALLOC_CONF = "expandable_segments:True"


@dataclass(frozen=True)
class ChannelPreset:
    """Verified QLoRA + vLLM alignment preset for one (modality, num_frames) channel."""

    modality: str
    num_frames: int
    cutoff_len: int
    vllm_max_model_len: int
    image_max_pixels: int | None
    image_min_pixels: int | None
    video_max_pixels: int | None
    video_min_pixels: int | None
    video_fps: float | None
    max_safe_train_frame_pixels: int
    note: str


# Presets: (modality, num_frames) -> ChannelPreset.
# Locked against DEC-008 §3 (8f images) and 2026-11-27 RTX 4090 hardware probe (16f <video>, board #19).
CHANNEL_PRESETS: dict[tuple[str, int], ChannelPreset] = {
    ("images", 8): ChannelPreset(
        modality="images",
        num_frames=8,
        cutoff_len=8192,
        vllm_max_model_len=8192,
        image_max_pixels=1_200_000,
        image_min_pixels=65_536,
        video_max_pixels=None,
        video_min_pixels=None,
        video_fps=None,
        max_safe_train_frame_pixels=1_200_000,
        note="DEC-008 §3 locked 8f full-resolution golden QLoRA recipe (22,525 MiB peak on RTX 4090).",
    ),
    ("video", 8): ChannelPreset(
        modality="video",
        num_frames=8,
        cutoff_len=8192,
        vllm_max_model_len=8192,
        image_max_pixels=None,
        image_min_pixels=None,
        video_max_pixels=1_200_000,
        video_min_pixels=256,
        video_fps=2.0,
        max_safe_train_frame_pixels=1_200_000,
        note="Native Qwen3-VL <video> 8f lossless pre-extracted PNG list (bit-exact with vLLM 0.34.0).",
    ),
    ("video", 16): ChannelPreset(
        modality="video",
        num_frames=16,
        cutoff_len=8192,
        vllm_max_model_len=12288,
        image_max_pixels=None,
        image_min_pixels=None,
        video_max_pixels=1_200_000,
        video_min_pixels=256,
        video_fps=2.0,
        max_safe_train_frame_pixels=865_000,
        note=(
            "Native Qwen3-VL <video> 16f lossless pre-extracted PNG list: train cutoff_len=8192 + "
            "video_max_pixels=1,200,000 (all 1,299 dev_clean <= 804x1072 = 861,888 px, 0 pre-resize, "
            "22,643 MiB peak on RTX 4090; guard >865,000 px against 924x1232 4090 OOM); "
            "vLLM --max-model-len 12288 verified PASS (20,613 MiB) covering native 924x1232."
        ),
    ),
}


def get_channel_preset(modality: str, num_frames: int) -> ChannelPreset:
    """Return the verified preset for ``(modality, num_frames)`` or raise ``ValueError``."""
    key = (modality, num_frames)
    if key not in CHANNEL_PRESETS:
        supported = ", ".join(f"{m}/{k}f" for m, k in sorted(CHANNEL_PRESETS))
        raise ValueError(
            f"unsupported SFT channel ({modality!r}, {num_frames!r}); supported presets: {supported}"
        )
    return CHANNEL_PRESETS[key]
