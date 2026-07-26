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
TRAINING_CODE_COMMIT = "4936381ef15fcf0d6dac3fee5af711a4678daa27"
LAUNCH_RUN_MANIFEST_SHA256 = (
    "dd2dfa855237720b685a78d188d3619d77cb6e9a4ee5d0603855ed2cab398021"
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
    runner.RESULT_ROOT = ROOT / "finetune/results" / RUN_ID
    runner.build_source_aware_3k = _build_coverage_first
    return runner
