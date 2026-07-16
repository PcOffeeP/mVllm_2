from __future__ import annotations

import json
import re
import sys

import pytest
from PIL import Image

from finetune.validation.datasets import EvalSample
from finetune.validation import run_prompt_sweep
from finetune.validation import model_runtime
from finetune.validation.model_runtime import ModelRunResult


def test_build_prompt_conditions_reuses_training_questions_without_examples() -> None:
    library = run_prompt_sweep.get_prompt_library()

    conditions = run_prompt_sweep.build_prompt_conditions(library, [0], "test")

    assert [condition["prompt_id"] for condition in conditions] == ["zh_binary_and_interval__test"]
    assert "confidence" not in conditions[0]["prompt_text"]
    assert "示例" not in conditions[0]["prompt_text"]
    assert "只能包含以下四个字段" not in conditions[0]["prompt_text"]
    assert conditions[0]["output_protocol"] == "four_field_json"


def test_test_system_prompt_is_read_from_the_shared_prompt_library() -> None:
    library = run_prompt_sweep.get_prompt_library()

    prompt = run_prompt_sweep.get_test_system_prompt(library)

    assert "has_fracture、fracture_between、type、location" in prompt
    assert "示例" not in prompt


def test_user_mode_uses_the_same_normal_question_without_structured_protocol() -> None:
    library = run_prompt_sweep.get_prompt_library()
    condition = run_prompt_sweep.build_prompt_conditions(library, [0], "user")[0]

    assert condition["output_protocol"] == "free_text"
    assert "请分析这段拉伸试验视频" in condition["prompt_text"]


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


def test_inspect_four_field_output_does_not_crash_on_model_value_type_errors() -> None:
    malformed = run_prompt_sweep.inspect_four_field_output(
        '{"has_fracture":true,"fracture_between":["3","4"],'
        '"type":"韧性断裂","location":"inside_gauge"}'
    )

    assert malformed["json_valid"] is True
    assert malformed["schema_valid"] is True
    assert malformed["legal_combination_valid"] is False
    assert malformed["parse_error"] == "illegal four-field value combination"


def test_summarize_condition_counts_malformed_as_incorrect_for_has_fracture() -> None:
    condition = {
        "prompt_id": "p",
        "template_id": "t",
        "variant": "four_field",
        "output_protocol": "four_field_json",
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
            "--prompt",
            "test",
        ],
    )

    run_prompt_sweep.main()

    records = [json.loads(line) for line in (out_dir / "evaluation_records.jsonl").read_text().splitlines()]
    summary = json.loads((out_dir / "prompt_sweep_summary.json").read_text())
    assert len(calls) == 12
    assert len(records) == 12
    assert {record["prompt_id"] for record in records} == {
        "zh_binary_and_interval__test",
        "zh_mode_focus__test",
        "zh_location_focus__test",
        "zh_anomaly_aware__test",
        "zh_full_reasoning__test",
        "zh_concise__test",
    }
    for record in records:
        assert "template_index" not in record
    for condition in summary["conditions"]:
        assert "template_index" not in condition


def test_new_cli_defaults_require_only_model_dir() -> None:
    prompt = run_prompt_sweep.parse_args(["prompt", "--model-dir", "/models/current"])
    evidence = run_prompt_sweep.parse_args(["evidence", "--model-dir", "/models/current"])

    assert prompt.dataset == "fold_0_val"
    assert prompt.variants == ("light", "medium", "strict")
    assert prompt.user_prompt_seed == 42
    assert prompt.max_new_tokens == 256
    assert evidence.variants == ("medium", "medium_evidence")
    assert evidence.max_new_tokens == 512
    with pytest.raises(SystemExit):
        run_prompt_sweep.parse_args(["prompt"])


def test_round_two_experiment_prompt_version_is_separate_from_training_version() -> None:
    library = run_prompt_sweep.get_prompt_library()

    assert run_prompt_sweep.get_prompt_version(library) == "v1.0.0"
    assert run_prompt_sweep.get_experiment_prompt_version(library) == "round_2_medium_contract"


def test_stable_template_assignment_is_order_independent() -> None:
    first = run_prompt_sweep.stable_template_index("sample-a", 42, 6)
    assert first == run_prompt_sweep.stable_template_index("sample-a", 42, 6)
    assert 0 <= first < 6


def test_experiment_variants_do_not_change_training_system_prompt() -> None:
    library = run_prompt_sweep.get_prompt_library()
    training_prompt = run_prompt_sweep.get_system_prompt(library)
    natural = run_prompt_sweep.build_variant_condition(library, "sample", "natural")
    strict = run_prompt_sweep.build_variant_condition(library, "sample", "strict")

    assert natural["system_prompt"] is None
    assert strict["output_protocol"] == "four_field_json"
    assert "confidence" not in strict["system_prompt"]
    assert run_prompt_sweep.get_system_prompt(library) == training_prompt


def test_medium_constrains_only_output_contract_without_visual_criteria() -> None:
    library = run_prompt_sweep.get_prompt_library()
    medium = run_prompt_sweep.build_variant_condition(library, "sample", "medium")
    prompt = medium["system_prompt"]

    assert medium["output_protocol"] == "four_field_json"
    assert "必须是 JSON 的 true、false 或 null" in prompt
    assert "两个相邻整数 [i, i+1] 或 null" in prompt
    assert '"界面脱粘、齐根断裂"' in prompt
    assert '"inside_gauge"、"outside_gauge" 或 null' in prompt
    assert "所有解释文字只能写在 visual_evidence" not in prompt
    for visual_criterion in ("颈缩", "突然发生", "界面间隙", "碎片飞溅", "打滑"):
        assert visual_criterion not in prompt


def test_strict_adds_visual_criteria_to_the_medium_output_contract() -> None:
    library = run_prompt_sweep.get_prompt_library()
    medium = run_prompt_sweep.build_variant_condition(library, "sample", "medium")["system_prompt"]
    strict = run_prompt_sweep.build_variant_condition(library, "sample", "strict")["system_prompt"]

    for contract_clause in medium.splitlines():
        assert contract_clause in strict
    assert "颈缩" in strict
    assert "界面间隙" in strict


def test_medium_evidence_keeps_explanations_out_of_final_fields() -> None:
    library = run_prompt_sweep.get_prompt_library()
    condition = run_prompt_sweep.build_variant_condition(library, "sample", "medium_evidence")
    prompt = condition["system_prompt"]

    assert condition["output_protocol"] == "evidence_first_json"
    assert "所有解释文字只能写在 visual_evidence 中" in prompt
    assert "fracture_between 必须是两个相邻整数" in prompt
    assert "不能使用说明文字" in prompt


def test_strict_prompt_lists_each_legal_type_as_an_unambiguous_quoted_value() -> None:
    library = run_prompt_sweep.get_prompt_library()
    strict = library["experiments"]["prompt_engineering"]["variants"]["strict"]["system_prompt"]
    type_clause = re.search(r"type 必须是以下完整字符串之一：\[(.*?)\]", strict)
    assert type_clause is not None
    listed = set(re.findall(r'"([^"]+)"', type_clause.group(1)))

    from pipeline.scripts.quality_check import ALL_TYPES

    assert listed == ALL_TYPES
    assert '"界面脱粘、齐根断裂"' in strict


def test_inspect_evidence_output_keeps_core_labels_and_checks_order() -> None:
    valid = run_prompt_sweep.inspect_evidence_output(
        '{"visual_evidence":"整体伸长后在帧2和3间分离；四字段均据此判断。",'
        '"has_fracture":true,"fracture_between":[2,3],"type":"韧性断裂","location":"inside_gauge"}'
    )
    reordered = run_prompt_sweep.inspect_evidence_output(
        '{"has_fracture":false,"visual_evidence":"画面未见连续性中断。",'
        '"fracture_between":null,"type":"未断裂","location":null}'
    )
    empty = run_prompt_sweep.inspect_evidence_output(
        '{"visual_evidence":"","has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'
    )

    assert valid["schema_valid"] is True
    assert valid["key_order_valid"] is True
    assert valid["parsed_output"]["has_fracture"] is True
    assert "visual_evidence" not in valid["parsed_output"]
    assert reordered["schema_valid"] is True
    assert reordered["key_order_valid"] is False
    assert empty["schema_valid"] is False
    assert empty["parse_error"] == "visual_evidence must be a non-empty string"


def test_build_evidence_pilot_selects_one_sample_per_fixed_source() -> None:
    samples = []
    for source, (has_fracture, fracture_type) in run_prompt_sweep.PILOT_TARGETS.items():
        for suffix in ("b", "a"):
            samples.append(
                EvalSample(
                    sample_id=f"{source}_focus_{suffix}",
                    video_id=f"{source}_focus_{suffix}",
                    video_path=f"/tmp/{source}_focus_{suffix}.mp4",
                    metadata={
                        "source_video_id": source,
                        "ground_truth": {"has_fracture": has_fracture, "type": fracture_type},
                    },
                )
            )

    selected = run_prompt_sweep.build_evidence_pilot(samples)

    assert len(selected) == 17
    assert {run_prompt_sweep.source_video_id(sample) for sample in selected} == set(run_prompt_sweep.PILOT_TARGETS)
    assert selected == run_prompt_sweep.build_evidence_pilot(list(reversed(samples)))


def test_coverage_blocks_only_sources_selected_for_the_target_split(tmp_path, monkeypatch) -> None:
    metadata_dir = tmp_path / "data" / "07_metadata"
    splits_dir = tmp_path / "data" / "05_splits"
    metadata_dir.mkdir(parents=True)
    splits_dir.mkdir(parents=True)
    (metadata_dir / "subvideos_meta.label_reviewed.json").write_text(
        json.dumps(
            {
                "subvideos": [
                    {"source_video": "video_elsewhere", "selected_splits": ["fold_0_train"]},
                    {"source_video": "video_missing", "selected_splits": ["fold_0_val"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    (splits_dir / "fold_0_val.json").write_text(
        json.dumps({"video_ids": ["video_present", "video_elsewhere", "video_missing"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_prompt_sweep, "PROJECT_ROOT", tmp_path)
    samples = [
        EvalSample(
            sample_id="video_present_focus",
            video_id="video_present_focus",
            video_path="/tmp/video_present_focus.mp4",
            metadata={"source_video_id": "video_present"},
        )
    ]

    coverage = run_prompt_sweep.build_dataset_coverage(samples, "fold_0_val")

    assert coverage["blocking_coverage_issues"] == ["video_missing"]
    assert coverage["missing_source_audit"]["video_elsewhere"]["reason"] == "reviewed_but_not_selected_for_split"
    assert coverage["missing_source_audit"]["video_missing"]["reason"] == "selected_for_split_but_missing_from_merged"


def test_model_manifest_requires_directly_loadable_config(tmp_path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    with pytest.raises(ValueError, match="config.json"):
        run_prompt_sweep.build_model_manifest(str(model_dir))
    (model_dir / "config.json").write_text('{"model_type":"minicpmv","_name_or_path":"base"}', encoding="utf-8")
    metadata_path = model_dir / "model_metadata.json"
    metadata_path.write_text('{"model_kind":"base","base_model":"base"}', encoding="utf-8")

    with pytest.raises(ValueError, match="no model"):
        run_prompt_sweep.build_model_manifest(str(model_dir))
    (model_dir / "model.safetensors").write_bytes(b"model-weights")
    metadata_path.unlink()

    with pytest.raises(ValueError, match="provenance metadata"):
        run_prompt_sweep.build_model_manifest(str(model_dir))
    metadata_path.write_text('{"model_kind":"base","base_model":"base"}', encoding="utf-8")

    manifest = run_prompt_sweep.build_model_manifest(str(model_dir))

    assert manifest["model_type"] == "minicpmv"
    assert manifest["base_model"] == "base"
    assert manifest["weight_file_count"] == 1
    assert manifest["model_kind"] == "base"
    assert manifest["weights"]["model.safetensors"]["size"] == 13
    assert manifest["weights_hash"]


def test_model_manifest_rejects_adapter_only_directory(tmp_path) -> None:
    model_dir = tmp_path / "adapter"
    model_dir.mkdir()
    (model_dir / "config.json").write_text('{}', encoding="utf-8")
    (model_dir / "adapter_config.json").write_text('{}', encoding="utf-8")
    (model_dir / "adapter_model.safetensors").write_bytes(b"adapter")

    with pytest.raises(ValueError, match="adapter-only"):
        run_prompt_sweep.build_model_manifest(str(model_dir))


def test_model_manifest_validates_merged_provenance(tmp_path) -> None:
    model_dir = tmp_path / "merged"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        '{"model_type":"minicpmv","_name_or_path":"/models/base"}', encoding="utf-8"
    )
    (model_dir / "model-00001-of-00002.safetensors").write_bytes(b"part-1")
    (model_dir / "model-00002-of-00002.safetensors").write_bytes(b"part-2")
    (model_dir / "merge_metadata.json").write_text(
        json.dumps(
            {
                "model_kind": "merged",
                "base_model": "/models/base",
                "adapter_path": "/checkpoints/fold0/checkpoint-1200",
                "checkpoint_step": 1200,
            }
        ),
        encoding="utf-8",
    )

    manifest = run_prompt_sweep.build_model_manifest(str(model_dir))

    assert manifest["model_kind"] == "merged"
    assert manifest["provenance"]["checkpoint_step"] == 1200
    assert manifest["weight_file_count"] == 2


def test_free_text_format_metrics_are_not_applicable() -> None:
    sample = EvalSample(
        sample_id="natural",
        video_id="natural",
        video_path="/tmp/natural.mp4",
        metadata={"ground_truth": {"has_fracture": False}},
    )
    condition = {
        "prompt_id": "natural",
        "template_id": "t",
        "variant": "natural",
        "output_protocol": "free_text",
        "prompt_text": "prompt",
        "prompt_hash": "hash",
    }
    record = run_prompt_sweep.evaluate_record(sample, condition, "画面中未见断裂。", None)

    metrics = run_prompt_sweep.summarize_condition([record])

    assert metrics["format_evaluable_count"] == 0
    assert metrics["json_valid_rate"] is None
    assert metrics["schema_valid_rate"] is None
    assert metrics["legal_combination_valid_rate"] is None


def test_new_prompt_experiment_writes_manifests_and_source_summary(tmp_path, monkeypatch) -> None:
    samples = [
        EvalSample(
            sample_id="video_0001_positive",
            video_id="video_0001_positive",
            video_path=tmp_path / "positive.mp4",
            metadata={"source_video_id": "video_0001", "ground_truth": {"has_fracture": True, "type": "韧性断裂"}},
        ),
        EvalSample(
            sample_id="video_0002_negative",
            video_id="video_0002_negative",
            video_path=tmp_path / "negative.mp4",
            metadata={"source_video_id": "video_0002", "ground_truth": {"has_fracture": False, "type": "未断裂"}},
        ),
    ]
    for sample in samples:
        sample.video_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(run_prompt_sweep, "load_dataset", lambda name, video_root=None: samples)
    monkeypatch.setattr(
        run_prompt_sweep,
        "build_dataset_coverage",
        lambda samples, dataset: {
            "dataset": dataset,
            "sample_count": 2,
            "merged_source_count": 2,
            "merged_sources": ["video_0001", "video_0002"],
            "split_path": None,
            "split_source_count": None,
            "split_sources": [],
            "missing_from_merged": [],
            "missing_source_audit": {},
            "blocking_coverage_issues": [],
            "unexpected_in_merged": [],
        },
    )
    monkeypatch.setattr(run_prompt_sweep, "build_model_manifest", lambda model_dir: {"model_dir": model_dir})
    monkeypatch.setattr(run_prompt_sweep, "load_model", lambda model_dir: (object(), object()))

    def fake_run(*args, **kwargs):
        frame_paths = []
        frame_dir = kwargs.get("frame_dir")
        if frame_dir is not None:
            frame_dir.mkdir(parents=True)
            frame_path = frame_dir / "frame_00_0.000s.png"
            frame_path.write_bytes(b"png")
            (frame_dir / "contact_sheet.png").write_bytes(b"png")
            frame_paths = [str(frame_path)]
        return ModelRunResult(
            raw_output='{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
            sampled_timestamps=[0.0, 1.0],
            generated_token_count=20,
            hit_token_limit=False,
            frame_paths=frame_paths,
        )

    monkeypatch.setattr(run_prompt_sweep, "run_model_on_video_detailed", fake_run)
    out_dir = tmp_path / "new-sweep"
    args = run_prompt_sweep.parse_args(
        ["prompt", "--model-dir", "/models/current", "--out-dir", str(out_dir), "--max-samples", "2"]
    )

    result = run_prompt_sweep.run_experiment(args)

    assert result == out_dir
    assert (out_dir / "experiment_manifest.json").exists()
    assert (out_dir / "source_level_summary.json").exists()
    assert (out_dir / "manual_review_queue.csv").exists()
    experiment_manifest = json.loads((out_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert experiment_manifest["experiment_prompt_version"] == "round_2_medium_contract"
    records = [json.loads(line) for line in (out_dir / "evaluation_records.jsonl").read_text().splitlines()]
    assert len(records) == 6
    assert {record["variant"] for record in records} == {"light", "medium", "strict"}
    assert records[0]["frame_paths"] == ["frames/video_0001_positive/frame_00_0.000s.png"]
    queue = (out_dir / "manual_review_queue.csv").read_text(encoding="utf-8")
    assert str(out_dir) not in queue
    assert "frames/video_0001_positive/contact_sheet.png" in queue


def test_sampled_frame_export_writes_exact_frames_and_contact_sheet(tmp_path) -> None:
    frames = [Image.new("RGB", (8, 6), "red"), Image.new("RGB", (8, 6), "blue")]

    paths = model_runtime._write_sampled_frames(frames, [0.0, 1.25], tmp_path / "frames")

    assert len(paths) == 2
    assert (tmp_path / "frames" / "frame_00_0.000s.png").exists()
    assert (tmp_path / "frames" / "contact_sheet.png").exists()
