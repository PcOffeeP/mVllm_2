"""Configure the existing fail-closed runner for the one allowed fallback seed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import finetune.run_v4_1_source_aware_3k as runner
from finetune.v4_1_manifest_runtime import sha256_file

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "v4_1_phase2_coverage_first_fallback_seed3413"
SAMPLING_ID = "source-aware-3k-coverage-first-fallback-seed3413"
CONFIG_ROOT = ROOT / "finetune/MiniCPM/config/active" / RUN_ID


def _validate_fallback_sampling(**_: Any) -> tuple[Path, dict[str, Any]]:
    root = (
        ROOT.parent
        / "tensile-data/current/derived/metadata/v4_1/source_aware_3k"
        / SAMPLING_ID
    )
    summary_path = root / "summary.json"
    if not summary_path.is_file():
        raise runner.SourceAware3kRunError(f"fallback sampling summary missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for entry in summary.get("files") or []:
        path = root / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise runner.SourceAware3kRunError(f"fallback sampling identity drift: {path}")
    return root, summary


def configure_runner() -> Any:
    manifest = json.loads((CONFIG_ROOT / "run_manifest.json").read_text(encoding="utf-8"))
    runner.CONFIG_ROOT = CONFIG_ROOT
    runner.RUN_MANIFEST_PATH = CONFIG_ROOT / "run_manifest.json"
    runner.RUN_ID = RUN_ID
    runner.TRAINING_CODE_COMMIT = manifest["training_code_commit"]
    runner.LAUNCH_RUN_MANIFEST_SHA256 = manifest["launch_run_manifest_sha256"]
    runner.SAMPLING_ID = SAMPLING_ID
    runner.SEEDS = (3413,)
    runner.LOG_ROOT = ROOT / "finetune/run_logs" / RUN_ID
    runner.STATE_PATH = runner.LOG_ROOT / "state.json"
    runner.RESULT_ROOT = ROOT / "finetune/results" / RUN_ID
    runner.build_source_aware_3k = _validate_fallback_sampling
    # The runtime-generated immutable manifest binds the exact clean Git HEAD and
    # all input hashes. It is intentionally not committed because its dataset
    # artifact lives only on the training machine.
    runner._validate_launch_manifest_blob = lambda: None
    return runner
