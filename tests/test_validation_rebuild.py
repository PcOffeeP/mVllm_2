from __future__ import annotations

import hashlib
import json
import sys
import types

from finetune.validation.datasets import EvalSample
from finetune.validation import run_base_prompt_test
from finetune.validation import model_runtime
from finetune.validation import run_evaluation
from finetune.validation.run_evaluation import evaluate_sample, main
from finetune.validation.prompts import get_system_prompt, get_user_prompt


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
            "--prompt",
            "training",
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
            "--prompt",
            "training",
            "--out-dir",
            str(out_dir),
        ],
    )

    main()

    assert captured["system_prompt"] == get_system_prompt()
    assert captured["prompt"] == get_user_prompt(0)


def test_base_prompt_test_uses_test_dataset_and_writes_comparison(tmp_path, monkeypatch):
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
    assert len(runtime_calls) == 2
    comparison = json.loads((tmp_path / "out" / "prompt_format_comparison.json").read_text(encoding="utf-8"))
    assert comparison["dataset"] == "test"
    assert comparison["sample_count"] == 1
    assert comparison["system_prompt"] == get_system_prompt()
    assert comparison["system_prompt_hash"] == hashlib.sha256(get_system_prompt().encode("utf-8")).hexdigest()
    assert comparison["prompts"]["training"]["raw_output_rate"] == 1.0
    assert comparison["prompts"]["system"]["raw_output_rate"] == 1.0
    # Verify system_prompt was passed to runtime for both prompt variants.
    assert all(call["system_prompt"] == get_system_prompt() for call in runtime_calls)


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
