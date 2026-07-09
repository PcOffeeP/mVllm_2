from __future__ import annotations

import json
import sys
import types

from finetune.validation.datasets import EvalSample
from finetune.validation import run_base_prompt_test
from finetune.validation import model_runtime
from finetune.validation.run_evaluation import evaluate_sample, main


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


def test_base_prompt_test_uses_test_dataset_and_writes_comparison(tmp_path, monkeypatch):
    calls = []

    sample = EvalSample(
        sample_id="video_0005",
        video_id="video_0005",
        video_path=tmp_path / "video_0005.mp4",
        metadata={"ground_truth": {"type": "视频异常"}},
    )
    sample.video_path.write_text("not a real video", encoding="utf-8")

    def fake_load_dataset(name, video_root=None):
        calls.append((name, video_root))
        return [sample]

    def fake_load_model(model_dir):
        return object(), object()

    def fake_run_model_on_video(model, processor, video_path, prompt_text):
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

    assert calls == [("test", None)]
    comparison = json.loads((tmp_path / "out" / "prompt_format_comparison.json").read_text(encoding="utf-8"))
    assert comparison["dataset"] == "test"
    assert comparison["sample_count"] == 1
    assert comparison["prompts"]["training"]["raw_output_rate"] == 1.0
    assert comparison["prompts"]["system"]["raw_output_rate"] == 1.0


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
