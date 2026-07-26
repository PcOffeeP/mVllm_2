"""Configure the shared Stage B runner for the coverage-first revision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finetune.build_v4_1_source_aware_3k import (
    COVERAGE_FIRST_POLICY_VERSION,
    build_source_aware_3k,
)
import finetune.run_v4_1_source_aware_3k as runner

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3"
SAMPLING_ID = "source-aware-3k-2a84e8b6cfc3"
CONFIG_ROOT = (
    ROOT
    / "finetune/MiniCPM/config/active"
    / "v4_1_source_aware_3k_coverage_first"
)
TRAINING_CODE_COMMIT = "f54d9ca617e455454f28e31ae058eda2dfdb5ec7"
LAUNCH_RUN_MANIFEST_SHA256 = (
    "8880686e9856dde0c176978c4662996f291634fd6bd34cca36f63949bb2cdcd9"
)


def _build_coverage_first(**kwargs: Any) -> tuple[Path, dict[str, Any]]:
    return build_source_aware_3k(
        **kwargs,
        policy_version=COVERAGE_FIRST_POLICY_VERSION,
        coverage_first=True,
    )


def configure_runner() -> Any:
    """Apply the immutable revision identity to the already-tested runner."""
    runner.CONFIG_ROOT = CONFIG_ROOT
    runner.RUN_MANIFEST_PATH = CONFIG_ROOT / "run_manifest.json"
    runner.RUN_ID = RUN_ID
    runner.TRAINING_CODE_COMMIT = TRAINING_CODE_COMMIT
    runner.LAUNCH_RUN_MANIFEST_SHA256 = LAUNCH_RUN_MANIFEST_SHA256
    runner.SAMPLING_ID = SAMPLING_ID
    runner.LOG_ROOT = ROOT / "finetune/run_logs" / RUN_ID
    runner.STATE_PATH = runner.LOG_ROOT / "state.json"
    runner.RESULT_ROOT = ROOT / "finetune/results" / RUN_ID
    runner.build_source_aware_3k = _build_coverage_first
    return runner
