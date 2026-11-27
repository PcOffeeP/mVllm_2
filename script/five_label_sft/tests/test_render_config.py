"""Unit tests for LlamaFactory QLoRA YAML and paired vLLM LoRA command renderer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from script.five_label_eval.errors import InputError
from script.five_label_sft.constants import PURE_SYSTEM_PATH, VLM_EVAL_VLLM_BIN
from script.five_label_sft.render_config import (
    build_qlora_config,
    build_runtime_commands,
    main as render_main,
    render_config_bundle,
)


def test_render_8f_images_matches_dec008_golden_recipe(tmp_path: Path) -> None:
    out_yaml = tmp_path / "fold0_images_8f.yaml"
    cfg, cmds = render_config_bundle(
        fold=0,
        modality="images",
        num_frames=8,
        dataset_dir="trains/sft-fold0-images8f/input",
        dataset_name="tensile_five_label_fold0_images_8f",
        train_output_dir="trains/sft-fold0-images8f/adapter",
        output_yaml=out_yaml,
    )
    assert out_yaml.is_file()
    loaded = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
    assert loaded == cfg
    assert cfg["template"] == "qwen3_vl_nothink"
    assert cfg["quantization_bit"] == 4
    assert cfg["quantization_method"] == "bnb"
    assert cfg["optim"] == "paged_adamw_8bit"
    assert cfg["lora_rank"] == 16
    assert cfg["lora_target"] == "all"
    assert cfg["gradient_checkpointing"] is True
    assert cfg["image_max_pixels"] == 1_200_000
    assert cfg["image_min_pixels"] == 65_536
    assert cfg["cutoff_len"] == 8192
    assert "video_max_pixels" not in cfg

    vllm_cmd = cmds["vllm_serve_lora_command"]
    assert PURE_SYSTEM_PATH in vllm_cmd
    assert VLM_EVAL_VLLM_BIN in vllm_cmd
    assert "--enable-lora" in vllm_cmd
    assert '"image": 8' in vllm_cmd
    assert "eval-test-v1" in cmds["eval_scope_warning"]


def test_render_16f_video_includes_bit_exact_vllm_flags(tmp_path: Path) -> None:
    out_yaml = tmp_path / "fold0_video_16f.yaml"
    rc = render_main(
        [
            "--fold",
            "0",
            "--modality",
            "video",
            "--num-frames",
            "16",
            "--dataset-dir",
            "trains/sft-fold0-video16f/input",
            "--train-output-dir",
            "trains/sft-fold0-video16f/adapter",
            "--output-yaml",
            str(out_yaml),
        ]
    )
    assert rc == 0
    loaded = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
    cmds = json.loads(out_yaml.with_suffix(".commands.json").read_text(encoding="utf-8"))
    assert loaded["template"] == "qwen3_vl_nothink"
    assert loaded["cutoff_len"] == 8192
    assert loaded["video_max_pixels"] == 1_200_000
    assert loaded["video_min_pixels"] == 256
    assert loaded["video_fps"] == 2.0
    assert "image_max_pixels" not in loaded

    vllm_cmd = cmds["vllm_serve_lora_command"]
    assert PURE_SYSTEM_PATH in vllm_cmd
    assert "--max-model-len \\\n  12288" in vllm_cmd
    assert "--media-io-kwargs" in vllm_cmd
    assert '"num_frames": -1' in vllm_cmd
    assert '"fps": 2.0' in vllm_cmd
    assert "--mm-processor-kwargs" in vllm_cmd
    assert '"do_sample_frames": false' in vllm_cmd
    assert '"cap_pixels_per_frame": false' in vllm_cmd


def test_render_refuses_protected_and_legacy_output_dirs(tmp_path: Path) -> None:
    for bad_dir in (
        "LlamaFactory/saves/qwen3vl/lora",
        "LlamaFactory//saves/qwen3vl/lora",
        "data/sub_video/adapter",
        "data//sub_video/adapter",
        "data/roi/adapter",
        "data/videos/adapter",
        "data/split-inputs/adapter",
        "../escape/adapter",
    ):
        with pytest.raises(InputError):
            build_qlora_config(
                fold=0,
                modality="video",
                num_frames=16,
                dataset_dir="trains/in",
                dataset_name="demo",
                train_output_dir=bad_dir,
            )

    # Protected output_yaml must also be refused before creating directories
    bad_yaml = tmp_path / "data" / "sub_video" / "evil.yaml"
    with pytest.raises(InputError, match="protected path"):
        render_config_bundle(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir="trains/in",
            dataset_name="demo",
            train_output_dir="trains/ok/adapter",
            output_yaml=bad_yaml,
        )
    assert not bad_yaml.parent.exists()


def test_render_rejects_invalid_hyperparams_and_cross_modality_overrides() -> None:
    with pytest.raises(InputError, match="lora_rank"):
        build_qlora_config(
            fold=0, modality="video", num_frames=16, dataset_dir="trains/in",
            dataset_name="demo", train_output_dir="trains/out", lora_rank=0,
        )
    with pytest.raises(InputError, match="lora_alpha"):
        build_qlora_config(
            fold=0, modality="video", num_frames=16, dataset_dir="trains/in",
            dataset_name="demo", train_output_dir="trains/out", lora_alpha=-1,
        )
    with pytest.raises(InputError, match="video_fps"):
        build_qlora_config(
            fold=0, modality="video", num_frames=16, dataset_dir="trains/in",
            dataset_name="demo", train_output_dir="trains/out", video_fps=0.0,
        )
    with pytest.raises(InputError, match="image_max_pixels"):
        build_qlora_config(
            fold=0, modality="video", num_frames=16, dataset_dir="trains/in",
            dataset_name="demo", train_output_dir="trains/out", image_max_pixels=1_000_000,
        )
    with pytest.raises(InputError, match="port"):
        build_runtime_commands(
            fold=0, modality="video", num_frames=16, yaml_path="trains/a.yaml",
            train_output_dir="trains/out", port=-5,
        )
    with pytest.raises(InputError, match="gpu_memory_utilization"):
        build_runtime_commands(
            fold=0, modality="video", num_frames=16, yaml_path="trains/a.yaml",
            train_output_dir="trains/out", gpu_memory_utilization=1.5,
        )


def test_render_propagates_custom_lora_rank_to_vllm_command() -> None:
    cmds = build_runtime_commands(
        fold=1,
        modality="video",
        num_frames=16,
        yaml_path="trains/fold1/sft.yaml",
        train_output_dir="trains/fold1/adapter",
        lora_rank=32,
    )
    assert "--max-lora-rank \\\n  32" in cmds["vllm_serve_lora_command"]
    assert "fold_1_val" in cmds["eval_scope_warning"]
