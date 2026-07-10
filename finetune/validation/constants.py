from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
MERGED_DATA_DIR = DATA_ROOT / "06_merged"
DEFAULT_VIDEO_ROOT = DATA_ROOT / "01_videos"

TEST_INPUTS_JSON = MERGED_DATA_DIR / "test_inputs.json"
TEST_GROUND_TRUTH_JSON = MERGED_DATA_DIR / "test_ground_truth.json"
TEST_SUBVIDEO_INPUTS_JSON = MERGED_DATA_DIR / "test_subvideo_inputs.json"
TEST_SUBVIDEO_GROUND_TRUTH_JSON = MERGED_DATA_DIR / "test_subvideo_ground_truth.json"

SUPPORTED_DATASETS = ("test", "test_subvideos", "fold_0_val", "fold_1_val", "fold_2_val")
PROMPT_NAMES = ("training",)

VIDEO_MAX_FRAMES = 8
GENERATION_CONFIG = {
    "do_sample": False,
    "num_beams": 1,
    "max_new_tokens": 256,
}

CORE_FIELDS = ("has_fracture", "fracture_between", "type", "location", "confidence")
