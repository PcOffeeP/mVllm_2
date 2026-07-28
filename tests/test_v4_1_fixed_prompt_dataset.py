from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.build_v4_1_fixed_prompt_dataset import build_fixed_prompt_dataset
from finetune.build_v4_1_source_aware_3k import SourceAware3kError
from finetune.prepare_v4_1_fixed_prompt_run import prepare_fixed_prompt_run
from finetune.run_v4_1_evaluation import _load_contract
from pipeline.prompt_control import load_experiment_contract
from pipeline.prompt_control.core import sha256_file

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "pipeline/prompt_registry/v4.1-fixed-full-fields-initial-v1"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _row(video: str, state: str) -> dict[str, object]:
    labels = {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂" if state != "未断裂" else None,
        "fracture_site": "inside_gauge" if state != "未断裂" else None,
        "special_case": None,
    }
    return {
        "videos": [video],
        "messages": [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "<video>\nold user"},
            {
                "role": "assistant",
                "content": json.dumps(labels, ensure_ascii=False),
            },
        ],
    }


def _source_sampling(tmp_path: Path, *, train_count: int = 2) -> Path:
    root = tmp_path / "source-aware-3k-test"
    templates = [_row("media/a.mp4", "未断裂"), _row("media/b.mp4", "发生断裂")]
    train = [templates[index % len(templates)] for index in range(train_count)]
    validation = [_row("media/c.mp4", "临界未断裂")]
    sequence = ["a" if index % 2 == 0 else "b" for index in range(train_count)]
    _write_json(root / "datasets/seed_3411.json", train)
    _write_json(root / "datasets/fold_0_validation.json", validation)
    _write_json(root / "dataset_info.json", {"source": {}})
    _write_json(
        root / "sampling_manifest.json",
        {
            "schema_version": "tensile-vlm-v4.1-source-aware-3k/v1",
            "sampling_id": "source-aware-3k-test",
            "release_id": "release-test",
            "inputs": {
                "release_manifest_sha256": "a" * 64,
                "training_candidates_sha256": "b" * 64,
            },
            "plans": [{"seed": 3411, "candidate_sequence": sequence}],
        },
    )
    managed = [
        "dataset_info.json",
        "datasets/seed_3411.json",
        "datasets/fold_0_validation.json",
        "sampling_manifest.json",
    ]
    _write_json(
        root / "summary.json",
        {
            "schema_version": "source-summary-test",
            "status": "ready",
            "immutable": True,
            "sampling_id": "source-aware-3k-test",
            "release_id": "release-test",
            "files": [
                {
                    "path": relative,
                    "size_bytes": (root / relative).stat().st_size,
                    "sha256": sha256_file(root / relative),
                }
                for relative in managed
            ],
        },
    )
    return root


def test_builds_prompt_only_derivative_and_evaluation_loads_same_snapshot(
    tmp_path: Path,
) -> None:
    source = _source_sampling(tmp_path)
    output, summary = build_fixed_prompt_dataset(
        source_sampling_dir=source,
        prompt_revision_dir=REVISION,
        output_root=tmp_path / "output",
    )
    experiment_path = output / "experiment_contract.json"
    experiment = load_experiment_contract(experiment_path)
    train = json.loads((output / "datasets/seed_3411.json").read_text())
    source_train = json.loads((source / "datasets/seed_3411.json").read_text())

    assert summary["train_row_count"] == 2
    assert summary["validation_row_count"] == 1
    assert [row["videos"] for row in train] == [
        row["videos"] for row in source_train
    ]
    assert [row["messages"][2] for row in train] == [
        row["messages"][2] for row in source_train
    ]
    assert all(
        row["messages"][0]["content"] == experiment["prompt"]["system_prompt"]
        and row["messages"][1]["content"]
        == f"<video>\n{experiment['prompt']['user_prompt']}"
        for row in train
    )

    contract, identity = _load_contract(
        experiment_contract_path=experiment_path
    )
    assert contract["analysis"]["system_prompt"] == experiment["prompt"][
        "system_prompt"
    ]
    assert identity["prompt_content_sha256"] == experiment["prompt"][
        "prompt_content_sha256"
    ]

    repeated, repeated_summary = build_fixed_prompt_dataset(
        source_sampling_dir=source,
        prompt_revision_dir=REVISION,
        output_root=tmp_path / "output",
        validate_only=True,
    )
    assert repeated == output
    assert repeated_summary == summary


def test_rejects_source_sampling_file_drift(tmp_path: Path) -> None:
    source = _source_sampling(tmp_path)
    (source / "datasets/seed_3411.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(SourceAware3kError, match="文件漂移"):
        build_fixed_prompt_dataset(
            source_sampling_dir=source,
            prompt_revision_dir=REVISION,
            output_root=tmp_path / "output",
        )


def test_prepares_seed3411_run_without_hyperparameter_drift(
    tmp_path: Path,
) -> None:
    source = _source_sampling(tmp_path, train_count=3000)
    bundle, _ = build_fixed_prompt_dataset(
        source_sampling_dir=source,
        prompt_revision_dir=REVISION,
        output_root=tmp_path / "output",
    )
    config_dir, manifest = prepare_fixed_prompt_run(
        bundle_dir=bundle,
        config_parent=tmp_path / "configs",
        adapter_dir=tmp_path / "adapter",
        merged_dir=tmp_path / "merged",
        training_code_commit="test-commit",
    )

    assert manifest["seed"] == 3411
    assert manifest["expected_optimizer_steps"] == 1125
    assert manifest["prompt"]["revision_id"] == (
        "v4.1-fixed-full-fields-initial-v1"
    )
    assert manifest["resolved_train_config"]["lora_rank"] == 8
    assert manifest["resolved_train_config"]["lora_dropout"] == 0.25
    assert manifest["resolved_train_config"]["dataset"] == (
        "tensile_v4_1_fixed_full_fields_seed3411"
    )
    assert manifest["commands"]["evaluate"][-2:] == [
        "--experiment-contract",
        str(bundle / "experiment_contract.json"),
    ]
    assert sha256_file(config_dir / "train_seed3411.yaml") == manifest[
        "train_config"
    ]["sha256"]
