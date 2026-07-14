from __future__ import annotations

import json
import sys

from finetune.validation.datasets import EvalSample
from finetune.validation import run_prompt_sweep


def test_build_prompt_conditions_reuses_training_questions_without_examples() -> None:
    library = run_prompt_sweep.get_prompt_library()

    conditions = run_prompt_sweep.build_prompt_conditions(
        library, [0], [run_prompt_sweep.VARIANT_TRAINING_QUESTION, run_prompt_sweep.VARIANT_FOUR_FIELD]
    )

    assert [condition["prompt_id"] for condition in conditions] == [
        "zh_binary_and_interval__training_question",
        "zh_binary_and_interval__four_field",
    ]
    assert "confidence" not in conditions[0]["prompt_text"]
    assert "示例" not in conditions[0]["prompt_text"]
    assert "confidence" not in conditions[1]["prompt_text"]
    assert "只能包含以下四个字段" in conditions[1]["prompt_text"]


def test_system_prompt_variants_are_read_from_the_shared_prompt_library() -> None:
    library = run_prompt_sweep.get_prompt_library()

    prompt = run_prompt_sweep.get_system_prompt_by_id("label_contract_v1", library)

    assert "has_fracture、fracture_between、type、location" in prompt
    assert "示例" not in prompt


def test_inspect_four_field_output_uses_project_legal_combinations() -> None:
    valid = run_prompt_sweep.inspect_four_field_output(
        '{"has_fracture":true,"fracture_between":[2,3],"type":"韧性断裂","location":"inside_gauge"}'
    )
    invalid = run_prompt_sweep.inspect_four_field_output(
        '{"has_fracture":false,"fracture_between":[2,3],"type":"未断裂","location":null}'
    )

    assert valid["json_valid"] is True
    assert valid["schema_valid"] is True
    assert valid["legal_combination_valid"] is True
    assert invalid["json_valid"] is True
    assert invalid["schema_valid"] is True
    assert invalid["legal_combination_valid"] is False


def test_summarize_condition_counts_malformed_as_incorrect_for_has_fracture() -> None:
    condition = {
        "prompt_id": "p",
        "template_index": 0,
        "template_id": "t",
        "variant": "four_field",
        "prompt_text": "prompt",
        "prompt_hash": "hash",
    }
    positive = EvalSample(
        sample_id="positive",
        video_id="positive",
        video_path="/tmp/positive.mp4",
        metadata={"ground_truth": {"has_fracture": True}},
    )
    negative = EvalSample(
        sample_id="negative",
        video_id="negative",
        video_path="/tmp/negative.mp4",
        metadata={"ground_truth": {"has_fracture": False}},
    )
    records = [
        run_prompt_sweep.evaluate_record(
            positive,
            condition,
            '{"has_fracture":true,"fracture_between":[1,2],"type":"韧性断裂","location":"inside_gauge"}',
            None,
        ),
        run_prompt_sweep.evaluate_record(negative, condition, "not json", None),
    ]

    metrics = run_prompt_sweep.summarize_condition(records)

    assert metrics["has_fracture_evaluable_count"] == 2
    assert metrics["has_fracture_accuracy"] == 0.5
    assert metrics["has_fracture_precision"] == 1.0
    assert metrics["has_fracture_recall"] == 1.0
    assert metrics["has_fracture_f1"] == 1.0
    assert metrics["type_evaluable_count"] == 0
    assert metrics["joint_evaluable_count"] == 0


def test_main_runs_each_sample_for_each_selected_condition(tmp_path, monkeypatch) -> None:
    samples = [
        EvalSample(
            sample_id="one",
            video_id="one",
            video_path=tmp_path / "one.mp4",
            metadata={"ground_truth": {"has_fracture": False}},
        ),
        EvalSample(
            sample_id="two",
            video_id="two",
            video_path=tmp_path / "two.mp4",
            metadata={"ground_truth": {"has_fracture": True}},
        ),
    ]
    for sample in samples:
        sample.video_path.write_text("placeholder", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(run_prompt_sweep, "load_dataset", lambda name, video_root=None: samples)
    monkeypatch.setattr(run_prompt_sweep, "load_model", lambda model_dir: (object(), object()))

    def fake_run(model, processor, video_path, prompt, system_prompt=None):
        calls.append(f"{video_path.stem}:{prompt}")
        return '{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'

    monkeypatch.setattr(run_prompt_sweep, "run_model_on_video", fake_run)
    out_dir = tmp_path / "sweep"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_prompt_sweep",
            "--dataset",
            "test",
            "--model-dir",
            "/tmp/base",
            "--out-dir",
            str(out_dir),
            "--template-indices",
            "0,1",
            "--variants",
            "four_field",
        ],
    )

    run_prompt_sweep.main()

    records = [json.loads(line) for line in (out_dir / "evaluation_records.jsonl").read_text().splitlines()]
    summary = json.loads((out_dir / "prompt_sweep_summary.json").read_text())
    assert len(calls) == 4
    assert len(records) == 4
    assert {record["prompt_id"] for record in records} == {
        "zh_binary_and_interval__four_field",
        "zh_mode_focus__four_field",
    }
    assert summary["paired_design"] is True
    assert summary["sample_count"] == 2
