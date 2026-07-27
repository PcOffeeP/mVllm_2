from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from finetune.build_v4_1_source_aware_3k_prompt_clarified import (
    DEFAULT_PROMPT_OVERLAY,
    _rewrite_dataset,
    sampling_identity,
)
from finetune.run_v4_1_evaluation import _load_contract
from finetune.v4_1_source_aware_3k_prompt_clarified import (
    CONFIG_ROOT,
    RUN_ID,
    SAMPLING_ID,
)
from pipeline.v3_review_workflow import sha256_file


def test_prompt_overlay_is_contract_bound_and_changes_only_instruction() -> None:
    contract, identity = _load_contract(DEFAULT_PROMPT_OVERLAY)
    overlay = json.loads(DEFAULT_PROMPT_OVERLAY.read_text())

    assert identity is not None
    assert identity["prompt_revision_id"] == overlay["prompt_revision_id"]
    assert contract["analysis"] == overlay["analysis"]
    assert contract["contract_hash"] == overlay["base_contract_hash"]
    assert overlay["changed_variable"] == "analysis_instruction_clarification"

    source = [
        {
            "videos": ["sample.mp4"],
            "messages": [
                {"role": "system", "content": "old system"},
                {"role": "user", "content": "<video>\nold user"},
                {"role": "assistant", "content": "{\"clip_state\":\"未断裂\"}"},
            ],
        }
    ]
    rewritten = _rewrite_dataset(
        source,
        analysis=overlay["analysis"],
        label="fixture",
    )
    assert source[0]["messages"][0]["content"] == "old system"
    assert rewritten[0]["videos"] == source[0]["videos"]
    assert rewritten[0]["messages"][2] == source[0]["messages"][2]
    assert rewritten[0]["messages"][0]["content"] == overlay["analysis"][
        "system_prompt"
    ]
    assert rewritten[0]["messages"][1]["content"] == (
        f"<video>\n{overlay['analysis']['user_prompt']}"
    )


def test_prompt_clarified_run_manifest_binds_single_change() -> None:
    manifest = json.loads((CONFIG_ROOT / "run_manifest.json").read_text())
    overlay_sha = hashlib.sha256(DEFAULT_PROMPT_OVERLAY.read_bytes()).hexdigest()

    assert manifest["run_id"] == RUN_ID
    assert manifest["sampling_id"] == SAMPLING_ID
    assert manifest["prompt_overlay_sha256"] == overlay_sha
    assert sampling_identity(prompt_overlay_sha256=overlay_sha) == SAMPLING_ID
    assert manifest["changed_variable"] == "analysis_instruction_clarification"
    assert manifest["source_sampling_id"] == "source-aware-3k-2a84e8b6cfc3"
    assert manifest["expected_optimizer_steps_per_seed"] == 1125

    baseline_root = CONFIG_ROOT.parent / "v4_1_source_aware_3k_coverage_first"
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
        differences = {
            key
            for key in set(revised) | set(baseline)
            if revised.get(key) != baseline.get(key)
        }
        assert differences == {"dataset_dir", "output_dir"}


def test_prompt_clarified_entrypoints_execute_directly() -> None:
    root = Path(__file__).resolve().parents[1] / "finetune"
    for name in (
        "build_v4_1_source_aware_3k_prompt_clarified.py",
        "run_v4_1_source_aware_3k_prompt_clarified.py",
        "monitor_v4_1_source_aware_3k_prompt_clarified.py",
        "analyze_v4_1_source_aware_3k_prompt_clarified.py",
        "analyze_v4_1_source_aware_3k_prompt_clarified_canary.py",
    ):
        result = subprocess.run(
            [sys.executable, str(root / name), "--help"],
            cwd=root.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
