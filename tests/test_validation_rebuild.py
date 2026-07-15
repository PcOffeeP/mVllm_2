from __future__ import annotations

import hashlib
import json
import sys
import types
from typing import Any

import pytest

from finetune.validation.datasets import EvalSample, load_dataset
import finetune.validation.datasets as datasets_module
from finetune.validation import run_base_prompt_test
from finetune.validation import model_runtime
from finetune.validation import run_evaluation
from finetune.validation.run_evaluation import evaluate_sample, main
from finetune.validation.prompts import (
    get_inference_target_schema,
    get_inference_user_prompt,
    get_system_prompt,
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
        return "output"

    monkeypatch.setattr(run_evaluation, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(run_evaluation, "load_model", fake_load_model)
    monkeypatch.setattr(run_evaluation, "run_model_on_video", fake_run_model_on_video)
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
    assert "confidence" in captured["prompt"]
    assert captured["prompt"] in {get_inference_user_prompt(i) for i in range(6)}


def test_run_evaluation_records_inference_target_schema_with_confidence(tmp_path, monkeypatch):
    """评估输出应记录五字段推理 target_schema（含 confidence）。"""
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
    assert set(schema.keys()) == {"has_fracture", "fracture_between", "type", "location", "confidence"}
    assert "confidence" in schema

    records = [
        json.loads(line)
        for line in (out_dir / "evaluation_records.jsonl").read_text(encoding="utf-8").strip().split("\n")
    ]
    assert len(records) == 1
    assert records[0].get("target_schema") == schema
    dataset_calls = []
    runtime_calls = []

    sample = EvalSample(
        sample_id="video_0005",
        video_id="video_0005",
        video_path=tmp_path / "video_0005.mp4",
        metadata={"ground_truth": {"type": "视频异常"}},
    )
    sample.video_path.write_text("not a real video", encoding="utf-8")

    def fake_load_dataset(name, video_root=None):
        dataset_calls.append((name, video_root))
        return [sample]

    def fake_load_model(model_dir):
        return object(), object()

    def fake_run_model_on_video(model, processor, video_path, prompt_text, system_prompt=None):
        runtime_calls.append({"prompt_text": prompt_text, "system_prompt": system_prompt})
        return json.dumps(
            {
                "has_fracture": None,
                "fracture_between": None,
                "type": "视频异常",
                "location": None,
                "confidence": 0.6,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(run_base_prompt_test, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(run_base_prompt_test, "load_model", fake_load_model)
    monkeypatch.setattr(run_base_prompt_test, "run_model_on_video", fake_run_model_on_video)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_base_prompt_test",
            "--model-dir",
            "/tmp/base-model",
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    run_base_prompt_test.main()

    assert dataset_calls == [("test", None)]
    assert len(runtime_calls) == 1
    comparison = json.loads((tmp_path / "out" / "prompt_format_comparison.json").read_text(encoding="utf-8"))
    assert comparison["dataset"] == "test"
    assert comparison["sample_count"] == 1
    assert comparison["system_prompt"] == get_system_prompt()
    assert comparison["system_prompt_hash"] == hashlib.sha256(get_system_prompt().encode("utf-8")).hexdigest()
    assert comparison["prompts"]["training"]["raw_output_rate"] == 1.0
    # Verify system_prompt was passed to runtime for the inference prompt variant.
    assert all(call["system_prompt"] == get_system_prompt() for call in runtime_calls)
    assert "confidence" in runtime_calls[0]["prompt_text"]
    assert runtime_calls[0]["prompt_text"] in {get_inference_user_prompt(i) for i in range(6)}


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

    monkeypatch.setattr(video_loader, "load_video_frames", lambda video_path, max_frames: (["frame1", "frame2"], [[0, 0]], [0.0, 1.0]))

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
        lambda video_path, max_frames: (["frame1"], [[0, 0]], [0.0]),
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
        lambda video_path, max_frames: (["frame1"], [[0, 0]], [0.0]),
    )

    result = model_runtime.run_model_on_video(
        FakeModel(), FakeProcessor(), tmp_path / "sample.mp4", "user prompt"
    )
    assert result == "output"
    assert captured_messages == [
        {"role": "user", "content": "(<image>./</image>)\nuser prompt"},
    ]


def test_run_evaluation_default_prompt_requires_confidence(tmp_path, monkeypatch):
    """默认评估 prompt 必须是含 confidence 的 inference user prompt。"""
    out_dir = tmp_path / "eval"
    sample = EvalSample(
        sample_id="video_0001",
        video_id="video_0001",
        video_path=tmp_path / "video_0001.mp4",
        metadata={},
    )

    def fake_run_model_on_video(model, processor, video_path, prompt_text, system_prompt=None):
        return "output"

    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: [sample])
    monkeypatch.setattr(run_evaluation, "load_model", lambda model_dir: (object(), object()))
    monkeypatch.setattr(run_evaluation, "run_model_on_video", fake_run_model_on_video)
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
    assert "confidence" in summary["prompt_text"]
    assert "confidence" in summary["target_schema"]


def test_run_evaluation_same_seed_reproduces_template_sequence(tmp_path, monkeypatch):
    """相同 seed 两次运行应产生相同的 per-sample 模板序列。"""
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

    library = run_evaluation.get_prompt_library()
    text_to_index = {get_inference_user_prompt(i, library): i for i in range(run_evaluation.get_user_prompt_template_count(library))}
    captured_runs: list[list[int]] = []

    def fake_run_model_on_video(model, processor, video_path, prompt_text, system_prompt=None):
        captured_runs[-1].append(text_to_index[prompt_text])
        return "output"

    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: samples)
    monkeypatch.setattr(run_evaluation, "load_model", lambda model_dir: (object(), object()))
    monkeypatch.setattr(run_evaluation, "run_model_on_video", fake_run_model_on_video)

    for _ in range(2):
        captured_runs.append([])
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
                "--user-prompt-seed",
                "42",
            ],
        )
        main()

    assert captured_runs[0] == captured_runs[1]


def test_run_evaluation_uses_multiple_templates_from_pool(tmp_path, monkeypatch):
    """多个样本运行时实际模板应来自 6 个模板之一，且不同样本可以使用不同模板。"""
    samples = [
        EvalSample(
            sample_id=f"video_{i:03d}",
            video_id=f"video_{i:03d}",
            video_path=tmp_path / f"video_{i:03d}.mp4",
            metadata={},
        )
        for i in range(20)
    ]
    for sample in samples:
        sample.video_path.write_text("not a video", encoding="utf-8")

    library = run_evaluation.get_prompt_library()
    text_to_index = {get_inference_user_prompt(i, library): i for i in range(run_evaluation.get_user_prompt_template_count(library))}
    used_indices: list[int] = []

    def fake_run_model_on_video(model, processor, video_path, prompt_text, system_prompt=None):
        used_indices.append(text_to_index[prompt_text])
        return "output"

    monkeypatch.setattr(run_evaluation, "load_dataset", lambda name, video_root=None: samples)
    monkeypatch.setattr(run_evaluation, "load_model", lambda model_dir: (object(), object()))
    monkeypatch.setattr(run_evaluation, "run_model_on_video", fake_run_model_on_video)
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

    template_count = run_evaluation.get_user_prompt_template_count(library)
    assert all(0 <= i < template_count for i in used_indices)
    assert len(set(used_indices)) > 1


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
    monkeypatch.setattr(datasets_module, "MERGED_DATA_DIR", tmp_path)
    record = _make_fold_record(
        "判断依据：在采样帧 3 与帧 4 之间观察到断裂形貌突变。\n"
        '结果：{"has_fracture": true, "fracture_between": [3, 4], "type": "脆性断裂", "location": "inside_gauge"}'
    )
    (tmp_path / "fold_0_val.json").write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")

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
    monkeypatch.setattr(datasets_module, "MERGED_DATA_DIR", tmp_path)
    record = _make_fold_record(
        '{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null}'
    )
    (tmp_path / "fold_1_val.json").write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")

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
