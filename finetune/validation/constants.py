from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DEFAULT_VIDEO_ROOT = DATA_ROOT / "01_videos"

ACTIVE_RELEASE_CONFIG = PROJECT_ROOT / "finetune" / "active_data_release.json"
_active_release = json.loads(ACTIVE_RELEASE_CONFIG.read_text(encoding="utf-8"))
ACTIVE_RELEASE_ID = _active_release["release_id"]
ACTIVE_RELEASE_DIR = PROJECT_ROOT / _active_release["release_dir"]

TRAIN_DATA_DIR = ACTIVE_RELEASE_DIR / "datasets" / "train"
VALIDATION_DATA_DIR = ACTIVE_RELEASE_DIR / "datasets" / "validation"
EVALUATION_DATA_DIR = ACTIVE_RELEASE_DIR / "datasets" / "evaluation"

TEST_INPUTS_JSON = EVALUATION_DATA_DIR / "source_videos" / "inputs.json"
TEST_GROUND_TRUTH_JSON = EVALUATION_DATA_DIR / "source_videos" / "ground_truth.json"
TEST_SUBVIDEO_INPUTS_JSON = EVALUATION_DATA_DIR / "subvideos" / "inputs.json"
TEST_SUBVIDEO_GROUND_TRUTH_JSON = EVALUATION_DATA_DIR / "subvideos" / "ground_truth.json"

SUPPORTED_DATASETS = ("test", "test_subvideos", "fold_0_val", "fold_1_val", "fold_2_val")
VIDEO_MAX_FRAMES = 8
GENERATION_CONFIG = {
    "do_sample": False,
    "num_beams": 1,
    "max_new_tokens": 256,
}

CORE_FIELDS = ("has_fracture", "fracture_between", "type", "location")
