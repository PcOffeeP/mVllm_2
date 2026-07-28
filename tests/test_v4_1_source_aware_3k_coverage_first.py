from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from finetune.archive.v4_1_source_aware_3k_coverage_first import (
    CONFIG_ROOT,
    RUN_ID,
    SAMPLING_ID,
)
from pipeline.v3_review_workflow import sha256_file


def test_coverage_first_run_manifest_binds_configs_and_single_change() -> None:
    manifest = json.loads((CONFIG_ROOT / "run_manifest.json").read_text())

    assert manifest["run_id"] == RUN_ID
    assert manifest["sampling_id"] == SAMPLING_ID
    assert manifest["revision_reason"] == "failed_development_gate"
    assert (
        manifest["changed_variable"]
        == "coverage_first_shared_candidate_multiset"
    )
    assert manifest["expected_optimizer_steps_per_seed"] == 1125

    baseline_root = CONFIG_ROOT.parent / "v4_1_source_aware_3k"
    allowed_differences = {
        "dataset_dir",
        "output_dir",
    }
    for seed in (3407, 3411):
        entry = manifest["seeds"][str(seed)]
        train_path = CONFIG_ROOT / entry["train_config"]
        merge_path = CONFIG_ROOT / entry["merge_config"]
        assert sha256_file(train_path) == entry["train_config_sha256"]
        assert sha256_file(merge_path) == entry["merge_config_sha256"]

        revised = yaml.safe_load(train_path.read_text())
        baseline = yaml.safe_load(
            (baseline_root / f"train_seed{seed}.yaml").read_text()
        )
        differing = {
            key
            for key in set(revised) | set(baseline)
            if revised.get(key) != baseline.get(key)
        }
        assert differing == allowed_differences
        assert SAMPLING_ID in revised["dataset_dir"]
        assert RUN_ID in revised["output_dir"]

        merge = yaml.safe_load(merge_path.read_text())
        assert RUN_ID in merge["adapter_name_or_path"]
        assert RUN_ID in merge["export_dir"]


def test_coverage_first_runner_entrypoints_execute_directly() -> None:
    root = Path(__file__).resolve().parents[1] / "finetune" / "archive"
    for name in (
        "run_v4_1_source_aware_3k_coverage_first.py",
        "monitor_v4_1_source_aware_3k_coverage_first.py",
        "analyze_v4_1_source_aware_3k_coverage_first.py",
        "analyze_v4_1_source_aware_3k_coverage_first_canary.py",
    ):
        path = root / name
        assert path.is_file()
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            cwd=root.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_coverage_first_configures_derived_state_path() -> None:
    code = (
        "from finetune.archive.v4_1_source_aware_3k_coverage_first "
        "import configure_runner; "
        "r=configure_runner(); "
        "print(r.STATE_PATH); print(r.LOG_ROOT / 'state.json')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 2
    assert lines[0] == lines[1]
    assert RUN_ID in lines[0]
