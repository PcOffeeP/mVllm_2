from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DEFAULT_VIDEO_ROOT = DATA_ROOT / "01_videos"

ACTIVE_RELEASE_CONFIG = PROJECT_ROOT / "finetune" / "active_data_release.json"
# Pure inference imports must not resolve a legacy active release. Preserve
# the historical constants for callers that explicitly request data paths.
def __getattr__(name: str):
    names = {"ACTIVE_RELEASE_ID", "ACTIVE_RELEASE_DIR", "TRAIN_DATA_DIR",
             "VALIDATION_DATA_DIR", "EVALUATION_DATA_DIR", "TEST_INPUTS_JSON",
             "TEST_GROUND_TRUTH_JSON", "TEST_SUBVIDEO_INPUTS_JSON",
             "TEST_SUBVIDEO_GROUND_TRUTH_JSON"}
    if name not in names:
        raise AttributeError(name)
    active = json.loads(ACTIVE_RELEASE_CONFIG.read_text(encoding="utf-8"))
    release = PROJECT_ROOT / active["release_dir"]
    evaluation = release / "datasets/evaluation"
    return {
        "ACTIVE_RELEASE_ID": active["release_id"], "ACTIVE_RELEASE_DIR": release,
        "TRAIN_DATA_DIR": release / "datasets/train",
        "VALIDATION_DATA_DIR": release / "datasets/validation",
        "EVALUATION_DATA_DIR": evaluation,
        "TEST_INPUTS_JSON": evaluation / "source_videos/inputs.json",
        "TEST_GROUND_TRUTH_JSON": evaluation / "source_videos/ground_truth.json",
        "TEST_SUBVIDEO_INPUTS_JSON": evaluation / "subvideos/inputs.json",
        "TEST_SUBVIDEO_GROUND_TRUTH_JSON": evaluation / "subvideos/ground_truth.json",
    }[name]


SUPPORTED_DATASETS = ("test", "test_subvideos", "fold_0_val", "fold_1_val", "fold_2_val")
VIDEO_MAX_FRAMES = 8
GENERATION_CONFIG = {
    "do_sample": False,
    "num_beams": 1,
    "max_new_tokens": 256,
}

CORE_FIELDS = ("has_fracture", "fracture_between", "type", "location")
