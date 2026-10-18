from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from finetune.validation.datasets import EvalSample, load_dataset
import finetune.validation.datasets as datasets_module
from finetune.validation import model_runtime
from finetune.validation import run_evaluation
from finetune.validation.run_evaluation import evaluate_sample, main
from finetune.validation.task_metrics import summarize_task_metrics
from finetune.validation.prompts import (
    get_system_prompt,
    get_system_prompt_hash,
    get_user_prompt,
)



def test_evaluate_sample_keeps_raw_output_without_schema_extraction():
    sample = EvalSample(
        sample_id="sample_1",
        video_id="sample_1",
        video_path="/tmp/sample_1.mp4",
        metadata={"ground_truth": {"type": "脆性断裂"}},
    )
    raw = '{"has_fracture": "yes", "fracture_between": "frame 1 and frame 2"}'

    record = evaluate_sample(sample, raw)

    assert record["raw_output"] == raw
    assert record["raw_output_non_empty"] is True
    assert "schema_valid" not in record
    assert "field_results" not in record
    assert record["metadata"]["ground_truth"]["type"] == "脆性断裂"


def test_evaluate_sample_records_normalized_output_and_repairs():
    sample = EvalSample(
        sample_id="sample_1",
        video_id="sample_1",
        video_path="/tmp/sample_1.mp4",
        metadata={"ground_truth": {"has_fracture": False}},
    )
    raw = '{"has_fracture":"false","fracture_between":null,"type":"未断裂","location":null}'

    record = evaluate_sample(sample, raw)

    assert record["json_valid"] is True
    assert record["parsed_output"]["has_fracture"] == "false"
    assert record["normalized_output"] == {
        "has_fracture": False,
        "fracture_between": None,
        "type": "未断裂",
        "location": None,
    }
    assert record["normalized_valid"] is True
    assert any("string coerced" in repair for repair in record["normalization_repairs"])


def test_task_metrics_score_fields_interval_time_and_joint():
    sample = EvalSample(
        sample_id="sample_1",
        video_id="sample_1",
        video_path="/tmp/sample_1.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": True,
                "fracture_between": [2, 3],
                "type": "脆性断裂",
                "location": "outside_gauge",
            },
            "event_time": 14.0,
            "start_time": 10.0,
        },
    )
    record = evaluate_sample(
        sample,
        json.dumps(
            {
                "has_fracture": True,
                "fracture_between": [2, 3],
                "type": "脆性断裂",
                "location": "outside_gauge",
            },
            ensure_ascii=False,
        ),
        sampled_timestamps=[0.0, 2.0, 3.0, 5.0],
    )

    metrics = summarize_task_metrics([record])

    assert record["task_scores"]["target_event_time_sec"] == 4.0
    assert record["task_scores"]["predicted_time_range_sec"] == [3.0, 5.0]
    assert record["task_scores"]["time_hit"] is True
    assert metrics["has_fracture_accuracy"] == 1.0
    assert metrics["type_accuracy_positive"] == 1.0
    assert metrics["location_accuracy_positive"] == 1.0
    assert metrics["interval_exact_accuracy"] == 1.0
    assert metrics["time_hit_rate"] == 1.0
    assert metrics["joint_success_rate"] == 1.0


def test_task_metrics_keep_invalid_outputs_in_denominator():
    valid_sample = EvalSample(
        sample_id="valid",
        video_id="valid",
        video_path="/tmp/valid.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
            }
        },
    )
    invalid_sample = EvalSample(
        sample_id="invalid",
        video_id="invalid",
        video_path="/tmp/invalid.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": True,
                "fracture_between": [1, 2],
                "type": "韧性断裂",
                "location": "inside_gauge",
            }
        },
    )
    records = [
        evaluate_sample(
            valid_sample,
            '{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
        ),
        evaluate_sample(invalid_sample, "not json", runtime_error="model failed"),
    ]

    metrics = summarize_task_metrics(records)

    assert metrics["scored_samples"] == 2
    assert metrics["has_fracture_accuracy"] == 0.5
    assert metrics["interval_exact_accuracy"] == 0.0
    # 目标与预测的 fracture_between 同为 None 不构成区间证据，不得白送 joint_success。
    assert metrics["joint_success_rate"] == 0.0
    assert metrics["has_fracture_confusion"] == {
        "target=false|pred=false": 1,
        "target=true|pred=invalid": 1,
    }


def test_task_metrics_credit_valid_fields_when_contract_is_incomplete():
    sample = EvalSample(
        sample_id="partial",
        video_id="partial",
        video_path="/tmp/partial.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
            }
        },
    )

    record = evaluate_sample(
        sample,
        '{"has_fracture":false,"fracture_between":null,"type":null,"location":null}',
    )
    metrics = summarize_task_metrics([record])

    assert record["normalized_valid"] is False
    assert record["task_scores"]["contract_valid"] is False
    assert metrics["has_fracture_accuracy"] == 1.0
    assert metrics["type_accuracy"] == 0.0
    assert metrics["location_accuracy"] == 1.0
    assert metrics["joint_success_rate"] == 0.0


def test_task_metrics_missing_interval_never_credits_joint_success():
    """目标与预测的 fracture_between 均为 None 时，不得凭 None == None 白送 joint_success。"""
    samples = [
        EvalSample(
            sample_id=f"no_fracture_{index:02d}",
            video_id=f"no_fracture_{index:02d}",
            video_path=f"/tmp/no_fracture_{index:02d}.mp4",
            metadata={
                "ground_truth": {
                    "has_fracture": False,
                    "fracture_between": None,
                    "type": "未断裂",
                    "location": None,
                }
            },
        )
        for index in range(10)
    ]
    records = [
        evaluate_sample(
            sample,
            '{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
        )
        for sample in samples
    ]

    metrics = summarize_task_metrics(records)

    assert metrics["scored_samples"] == 10
    assert metrics["interval_scored_samples"] == 0
    assert metrics["interval_exact_accuracy"] is None
    assert metrics["joint_success_rate"] == 0.0


def test_task_metrics_one_sided_missing_interval_is_never_correct():
    """目标有合法区间而预测 fracture_between 为 null 时，样本计入区间评分且判错。"""
    sample = EvalSample(
        sample_id="partial_interval",
        video_id="partial_interval",
        video_path="/tmp/partial_interval.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": True,
                "fracture_between": [1, 2],
                "type": "脆性断裂",
                "location": "inside_gauge",
            }
        },
    )

    record = evaluate_sample(
        sample,
        '{"has_fracture":true,"fracture_between":null,"type":"脆性断裂","location":"inside_gauge"}',
    )
    metrics = summarize_task_metrics([record])

    assert record["task_scores"]["interval_available"] is True
    assert record["task_scores"]["interval_correct"] is False
    assert record["task_scores"]["joint_success"] is False
    assert metrics["interval_scored_samples"] == 1
    assert metrics["interval_exact_accuracy"] == 0.0


def test_task_metrics_bool_interval_is_not_credited():
    """区间 [true, 2] 不得被当成 [1, 2] 记分。"""
    sample = EvalSample(
        sample_id="bool_interval",
        video_id="bool_interval",
        video_path="/tmp/bool_interval.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": True,
                "fracture_between": [1, 2],
                "type": "韧性断裂",
                "location": "inside_gauge",
            }
        },
    )

    # JSON 的 true 解析成 Python bool，而 bool 是 int 的子类，因此 [True, 2] == [1, 2]
    # 会成立；区间合法性与相等比较都必须显式排除 bool，否则布尔值会被当成帧号白送分数。
    record = evaluate_sample(
        sample,
        '{"has_fracture": true, "fracture_between": [true, 2], "type": "韧性断裂", "location": "inside_gauge"}',
    )
    metrics = summarize_task_metrics([record])

    assert record["task_scores"]["interval_available"] is True
    assert record["task_scores"]["interval_correct"] is False
    assert record["task_scores"]["joint_success"] is False
    assert metrics["interval_scored_samples"] == 1
    assert metrics["interval_exact_accuracy"] == 0.0


def test_evaluate_sample_raw_without_legacy_interval_key():
    """v2 字段集去掉 fracture_between 的混合形状 raw 端到端不产生该字段、不产生修复标记且判定合法。

    注意：该 raw 形如 {"has_fracture", "type", "location"}，是 v2 字段集去掉 fracture_between
    后的混合形状，**不是** v4.1 契约形状（v4.1 四字段为
    clip_state / fracture_mechanism / fracture_site / special_case）。
    """
    sample = EvalSample(
        sample_id="raw_without_interval_key",
        video_id="raw_without_interval_key",
        video_path="/tmp/raw_without_interval_key.mp4",
        metadata={
            "ground_truth": {
                "has_fracture": True,
                "type": "韧性断裂",
                "location": "inside_gauge",
            }
        },
    )

    # 该混合形状 raw 的端到端路径（v2 字段集去掉 fracture_between，非 v4.1 契约形状）：
    # 旧字段 fracture_between 在 raw 中缺失时，
    # 归一化输出既不补键也不产生 repair 标记，且整体仍判为合法。
    record = evaluate_sample(
        sample,
        '{"has_fracture": true, "type": "韧性断裂", "location": "inside_gauge"}',
    )

    assert "fracture_between" not in record["normalized_output"]
    assert record["normalization_repairs"] == []
    assert record["normalized_valid"] is True


def test_run_evaluation_prediction_file_mode(tmp_path, monkeypatch):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "video_id": "video_0005_full",
                        "raw_output": json.dumps(
                            {
                                "has_fracture": None,
                                "fracture_between": None,
                                "type": "视频异常",
                                "location": None,
                                "confidence": 0.7,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "video_id": "video_0008_full",
                        "raw_output": json.dumps(
                            {
                                "has_fracture": True,
                                "fracture_between": [6, 7],
                                "type": "脆性断裂",
                                "location": "outside_gauge",
                                "confidence": 0.9,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "eval"

    samples = [
        EvalSample(
            sample_id="video_0005_full",
            video_id="video_0005_full",
            video_path=tmp_path / "video_0005_full.mp4",
            metadata={},
        ),
        EvalSample(
            sample_id="video_0008_full",
            video_id="video_0008_full",
            video_path=tmp_path / "video_0008_full.mp4",
            metadata={},
        ),
    ]
    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: samples)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test_subvideos",
            "--predictions",
            str(predictions),
            "--out-dir",
            str(out_dir),
            "--max-samples",
            "2",
        ],
    )

    main()

    summary = json.loads((out_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["total_samples"] == 2
    assert summary["metrics"]["raw_output_rate"] == 1.0
    assert summary["metrics"]["runtime_error_count"] == 0
    assert (out_dir / "evaluation_records.jsonl").exists()
    assert (out_dir / "runtime_failures.csv").exists()


def test_run_evaluation_passes_system_prompt_to_model_runtime(tmp_path, monkeypatch):
    """Patch: run_evaluation 推理时应把 prompt_library 的 system prompt 传给 model_runtime。"""
    out_dir = tmp_path / "eval"
    sample = EvalSample(
        sample_id="video_0001",
        video_id="video_0001",
        video_path=tmp_path / "video_0001.mp4",
        metadata={},
    )
    sample.video_path.write_text("not a video", encoding="utf-8")

    captured = {}

    def fake_load_dataset(name, video_root=None):
        return [sample]

    def fake_load_model(model_dir):
        return object(), object()

    def fake_run_model_on_video(model, processor, video_path, prompt, system_prompt=None):
        captured["system_prompt"] = system_prompt
        captured["prompt"] = prompt
        return model_runtime.ModelRunResult("output", [0.0], 1, False, [])

    monkeypatch.setattr(run_evaluation, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(run_evaluation, "load_model", fake_load_model)
    monkeypatch.setattr(run_evaluation, "run_model_on_video_detailed", fake_run_model_on_video)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test",
            "--model-dir",
            "/tmp/model",
            "--out-dir",
            str(out_dir),
        ],
    )

    main()

    assert captured["system_prompt"] == get_system_prompt()
    assert "confidence" not in captured["prompt"]
    assert captured["prompt"] == get_user_prompt()


def test_run_evaluation_records_target_schema_and_canonical_prompts(tmp_path, monkeypatch):
    """评估输出记录四字段 schema，并使用唯一 System/User Prompt。"""
    out_dir = tmp_path / "eval"
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "video_id": "video_0001",
                "raw_output": json.dumps(
                    {
                        "has_fracture": True,
                        "fracture_between": [2, 3],
                        "type": "韧性断裂",
                        "location": "inside_gauge",
                        "confidence": 0.85,
                    },
                    ensure_ascii=False,
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sample = EvalSample(
        sample_id="video_0001",
        video_id="video_0001",
        video_path=tmp_path / "video_0001.mp4",
        metadata={},
    )
    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: [sample])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test_subvideos",
            "--predictions",
            str(predictions),
            "--out-dir",
            str(out_dir),
        ],
    )

    main()

    summary = json.loads((out_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert "target_schema" in summary
    schema = summary["target_schema"]
    assert set(schema.keys()) == {"has_fracture", "fracture_between", "type", "location"}
    assert "confidence" not in schema

    records = [
        json.loads(line)
        for line in (out_dir / "evaluation_records.jsonl").read_text(encoding="utf-8").strip().split("\n")
    ]
    assert len(records) == 1
    assert records[0].get("target_schema") == schema
    assert summary["system_prompt"] == get_system_prompt()
    assert summary["system_prompt_hash"] == get_system_prompt_hash()
    assert summary["prompt_text"] == get_user_prompt()


def test_model_runtime_keeps_minicpm_video_embedding_inputs(monkeypatch, tmp_path):
    captured = {}

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        tokenizer = object()

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            return "rendered prompt"

        def __call__(self, **kwargs):
            return FakeInputs(
                {
                    "input_ids": "ids",
                    "attention_mask": "mask",
                    "pixel_values": "pixels",
                    "image_sizes": "processor-only",
                    "temporal_ids": [[0, 0]],
                    "image_bound": "bounds",
                    "tgt_sizes": "sizes",
                }
            )

    class FakeModel:
        device = "cpu"

        def generate(self, **kwargs):
            captured.update(kwargs)
            return ["{}"]

    class FakeNoGrad:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=lambda: FakeNoGrad()))

    monkeypatch.setattr(
        model_runtime,
        "load_video_frames",
        lambda video_path, max_frames: (["frame1", "frame2"], [[0, 0]], [0.0, 1.0]),
        raising=False,
    )

    # run_model_on_video imports load_video_frames inside the function, so patch
    # the imported module path instead of model_runtime globals.
    import finetune.validation.video_loader as video_loader

    # fake 需接受 run_model_on_video_detailed 新增的关键字参数；返回值仍是 1 组
    # 时间融合，用于断言透传保真（不做新的语义承诺）。
    monkeypatch.setattr(
        video_loader,
        "load_video_frames",
        lambda video_path, max_frames, **kwargs: (["frame1", "frame2"], [[0, 0]], [0.0, 1.0]),
    )

    assert model_runtime.run_model_on_video(FakeModel(), FakeProcessor(), tmp_path / "sample.mp4", "prompt") == "{}"
    assert "image_sizes" not in captured
    assert captured["temporal_ids"] == [[0, 0]]
    assert captured["image_bound"] == "bounds"
    assert captured["tgt_sizes"] == "sizes"


def test_model_runtime_includes_system_prompt_when_provided(monkeypatch, tmp_path):
    captured_messages = []

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        tokenizer = object()

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            captured_messages.extend(messages)
            return "rendered prompt"

        def __call__(self, **kwargs):
            return FakeInputs({"input_ids": "ids"})

    class FakeModel:
        device = "cpu"

        def generate(self, **kwargs):
            return ["output"]

    class FakeNoGrad:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=lambda: FakeNoGrad()))
    import finetune.validation.video_loader as video_loader

    monkeypatch.setattr(
        video_loader,
        "load_video_frames",
        lambda video_path, max_frames, **kwargs: (["frame1"], [[0, 0]], [0.0]),
    )

    result = model_runtime.run_model_on_video(
        FakeModel(),
        FakeProcessor(),
        tmp_path / "sample.mp4",
        "user prompt",
        system_prompt="system prompt",
    )
    assert result == "output"
    assert captured_messages == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "(<image>./</image>)\nuser prompt"},
    ]


def test_model_runtime_omits_system_prompt_when_none(monkeypatch, tmp_path):
    captured_messages = []

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeProcessor:
        tokenizer = object()

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            captured_messages.extend(messages)
            return "rendered prompt"

        def __call__(self, **kwargs):
            return FakeInputs({"input_ids": "ids"})

    class FakeModel:
        device = "cpu"

        def generate(self, **kwargs):
            return ["output"]

    class FakeNoGrad:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(no_grad=lambda: FakeNoGrad()))
    import finetune.validation.video_loader as video_loader

    monkeypatch.setattr(
        video_loader,
        "load_video_frames",
        lambda video_path, max_frames, **kwargs: (["frame1"], [[0, 0]], [0.0]),
    )

    result = model_runtime.run_model_on_video(
        FakeModel(), FakeProcessor(), tmp_path / "sample.mp4", "user prompt"
    )
    assert result == "output"
    assert captured_messages == [
        {"role": "user", "content": "(<image>./</image>)\nuser prompt"},
    ]


def test_run_evaluation_default_prompt_uses_four_field_user_prompt(tmp_path, monkeypatch):
    """默认评估 prompt 应使用不含 confidence 的 4-field user prompt。"""
    out_dir = tmp_path / "eval"
    sample = EvalSample(
        sample_id="video_0001",
        video_id="video_0001",
        video_path=tmp_path / "video_0001.mp4",
        metadata={},
    )

    def fake_run_model_on_video(model, processor, video_path, prompt_text, system_prompt=None):
        return model_runtime.ModelRunResult("output", [0.0], 1, False, [])

    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: [sample])
    monkeypatch.setattr(run_evaluation, "load_model", lambda model_dir: (object(), object()))
    monkeypatch.setattr(run_evaluation, "run_model_on_video_detailed", fake_run_model_on_video)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test",
            "--model-dir",
            "/tmp/model",
            "--out-dir",
            str(out_dir),
        ],
    )

    main()

    summary = json.loads((out_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["prompt"] == "training"
    assert "confidence" not in summary["prompt_text"]
    assert set(summary["target_schema"].keys()) == {"has_fracture", "fracture_between", "type", "location"}
    assert "confidence" not in summary["target_schema"]


def test_run_evaluation_uses_one_fixed_user_prompt(tmp_path, monkeypatch):
    """所有样本都必须使用唯一 User Prompt。"""
    samples = [
        EvalSample(
            sample_id=f"video_{i:03d}",
            video_id=f"video_{i:03d}",
            video_path=tmp_path / f"video_{i:03d}.mp4",
            metadata={},
        )
        for i in range(10)
    ]
    for sample in samples:
        sample.video_path.write_text("not a video", encoding="utf-8")

    captured_prompts: list[str] = []

    def fake_run_model_on_video(model, processor, video_path, prompt_text, system_prompt=None):
        captured_prompts.append(prompt_text)
        return model_runtime.ModelRunResult("output", [0.0], 1, False, [])

    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: samples)
    monkeypatch.setattr(run_evaluation, "load_model", lambda model_dir: (object(), object()))
    monkeypatch.setattr(run_evaluation, "run_model_on_video_detailed", fake_run_model_on_video)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test",
            "--model-dir",
            "/tmp/model",
            "--out-dir",
            str(tmp_path / "eval"),
        ],
    )

    main()

    assert captured_prompts == [get_user_prompt()] * len(samples)


def test_parse_assistant_json_raises_on_invalid_content():
    from finetune.validation.datasets import _parse_assistant_json

    with pytest.raises(ValueError, match="结果："):
        _parse_assistant_json("invalid content without json")


def _make_fold_record(assistant_content: str, video_path: str = "data/01_videos/video_0001.mp4") -> dict[str, Any]:
    return {
        "id": "video_0001",
        "videos": [video_path],
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user prompt"},
            {"role": "assistant", "content": assistant_content},
        ],
        "metadata": {},
    }


def test_load_fold_dataset_parses_new_format_assistant(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets_module, "VALIDATION_DATA_DIR", tmp_path)
    record = _make_fold_record(
        "判断依据：在采样帧 3 与帧 4 之间观察到断裂形貌突变。\n"
        '结果：{"has_fracture": true, "fracture_between": [3, 4], "type": "脆性断裂", "location": "inside_gauge"}'
    )
    (tmp_path / "fold_0.json").write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")

    samples = load_dataset("fold_0_val")

    assert len(samples) == 1
    assert samples[0].video_id == "video_0001"
    assert samples[0].metadata["ground_truth"] == {
        "has_fracture": True,
        "fracture_between": [3, 4],
        "type": "脆性断裂",
        "location": "inside_gauge",
    }
    assert "结果：" in samples[0].metadata["assistant_raw"]
    assert samples[0].metadata["assistant_json"] == samples[0].metadata["ground_truth"]


def test_load_fold_dataset_parses_legacy_json_assistant(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets_module, "VALIDATION_DATA_DIR", tmp_path)
    record = _make_fold_record(
        '{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null}'
    )
    (tmp_path / "fold_1.json").write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")

    samples = load_dataset("fold_1_val")

    assert len(samples) == 1
    assert samples[0].metadata["ground_truth"] == {
        "has_fracture": False,
        "fracture_between": None,
        "type": "未断裂",
        "location": None,
    }
    assert samples[0].metadata["assistant_raw"] == record["messages"][2]["content"]
    assert samples[0].metadata["assistant_json"] == samples[0].metadata["ground_truth"]


def test_run_evaluation_rejects_prompt_system(tmp_path, monkeypatch):
    """--prompt system 已移除，传入应触发 argparse 错误。"""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test",
            "--model-dir",
            "/tmp/model",
            "--prompt",
            "system",
            "--out-dir",
            str(tmp_path / "eval"),
        ],
    )
    with pytest.raises(SystemExit):
        main()
