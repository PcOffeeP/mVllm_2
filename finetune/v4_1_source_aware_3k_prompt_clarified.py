"""Configure the shared Stage B runner for the clarified-prompt revision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finetune.build_v4_1_source_aware_3k_prompt_clarified import (
    DEFAULT_PROMPT_OVERLAY,
    build_prompt_clarified_source_aware_3k,
)
import finetune.run_v4_1_source_aware_3k as runner

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "v4_1_phase2_source_aware_3k_prompt_clarified_b74d7119c0ef"
SAMPLING_ID = "source-aware-3k-prompt-clarified-b74d7119c0ef"
CONFIG_ROOT = (
    ROOT
    / "finetune/MiniCPM/config/active"
    / "v4_1_source_aware_3k_prompt_clarified"
)
TRAINING_CODE_COMMIT = "d1a9a363585c84ad842e594e27b0f552cb3fc5ca"
LAUNCH_RUN_MANIFEST_SHA256 = (
    "87b4bfa7c17e5f86e3f8bdb5396a777bb6cb24be2f1e966305aefe02cb7dab7e"
)


def _build_prompt_clarified(**kwargs: Any) -> tuple[Path, dict[str, Any]]:
    return build_prompt_clarified_source_aware_3k(**kwargs)


def configure_runner() -> Any:
    """Apply the immutable prompt revision identity to the shared runner."""
    runner.CONFIG_ROOT = CONFIG_ROOT
    runner.RUN_MANIFEST_PATH = CONFIG_ROOT / "run_manifest.json"
    runner.RUN_ID = RUN_ID
    runner.TRAINING_CODE_COMMIT = TRAINING_CODE_COMMIT
    runner.LAUNCH_RUN_MANIFEST_SHA256 = LAUNCH_RUN_MANIFEST_SHA256
    runner.SAMPLING_ID = SAMPLING_ID
    runner.LOG_ROOT = ROOT / "finetune/run_logs" / RUN_ID
    runner.STATE_PATH = runner.LOG_ROOT / "state.json"
    runner.RESULT_ROOT = ROOT / "finetune/results" / RUN_ID
    runner.EVALUATION_EXTRA_ARGS = (
        "--analysis-prompt-overlay",
        str(DEFAULT_PROMPT_OVERLAY),
    )
    runner.build_source_aware_3k = _build_prompt_clarified
    return runner
