"""Unit tests for LlamaFactory QLoRA YAML and paired vLLM LoRA command renderer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from script.five_label_eval.errors import InputError
from script.five_label_sft.constants import BUILD_SUMMARY_SCHEMA, PURE_SYSTEM_PATH, VLM_EVAL_VLLM_BIN
from script.five_label_sft.render_config import (
    build_qlora_config,
    build_runtime_commands,
    main as render_main,
    render_config_bundle,
    verify_rendered_launch,
)


def _create_verified_bundle(
    bundle_dir: Path,
    *,
    fold: int,
    modality: str,
    num_frames: int,
    dataset_name: str,
    dry_run: bool = False,
    max_est_tokens: int = 7612,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    ds_file = f"{dataset_name}.json"
    media_col = "images" if modality == "images" else "videos"
    ds_bytes = b"[]\n"
    (bundle_dir / ds_file).write_bytes(ds_bytes)
    info_obj = {
        dataset_name: {
            "file_name": ds_file,
            "formatting": "sharegpt",
            "columns": {"messages": "messages", media_col: media_col},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
            },
        }
    }
    info_bytes = (json.dumps(info_obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (bundle_dir / "dataset_info.json").write_bytes(info_bytes)

    pixel_config = (
        {
            "image_max_pixels": 1_200_000 if image_max_pixels is None else image_max_pixels,
            "image_min_pixels": 65_536 if image_min_pixels is None else image_min_pixels,
            "video_max_pixels": None,
            "video_min_pixels": None,
        }
        if modality == "images"
        else {
            "image_max_pixels": None,
            "image_min_pixels": None,
            "video_max_pixels": 1_200_000 if video_max_pixels is None else video_max_pixels,
            "video_min_pixels": 256 if video_min_pixels is None else video_min_pixels,
        }
    )
    preflight_obj = {
        "schema": "five-label-sft-preflight/1",
        "modality": modality,
        "num_frames": num_frames,
        "cutoff_len": 8192,
        "pixel_config": pixel_config,
        "short_clip_count": 0,
        "exceeds_cutoff_count": 0,
        "exceeds_gpu_frame_pixel_guard_count": 0,
        "estimated_total_tokens": {"max": max_est_tokens},
    }
    preflight_bytes = (json.dumps(preflight_obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (bundle_dir / "preflight_report.json").write_bytes(preflight_bytes)

    summary_obj: dict[str, Any] = {
        "schema": BUILD_SUMMARY_SCHEMA,
        "dataset_name": dataset_name,
        "dataset_file": ds_file,
        "fold": fold,
        "modality": modality,
        "num_frames": num_frames,
        "dry_run_missing_frames": dry_run,
        "strict_target_json_verified": True,
        "isolation_checks": {
            "exported_candidate_count": 2,
            "exported_source_count": 1,
            "fold_val_source_overlap": 0,
            "test_source_overlap": 0,
            "eval_test_v1_source_overlap": 0,
            "eval_test_v1_candidate_overlap": 0,
            "eval_dev_v1_fold_val_candidate_overlap": 0,
            "dec007_excluded_overlap": 0,
        },
        "fingerprints": {
            "dataset_sha256": hashlib.sha256(ds_bytes).hexdigest(),
            "dataset_info_sha256": hashlib.sha256(info_bytes).hexdigest(),
            "preflight_report_sha256": hashlib.sha256(preflight_bytes).hexdigest(),
        },
        "preflight_summary": {
            "estimated_total_tokens": {"max": max_est_tokens},
        },
    }
    (bundle_dir / "build_summary.json").write_text(
        json.dumps(summary_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return bundle_dir


def test_render_8f_images_matches_dec008_golden_recipe(tmp_path: Path) -> None:
    ds_name = "tensile_five_label_fold0_images_8f"
    bundle_dir = _create_verified_bundle(
        tmp_path / "bundle_img8",
        fold=0,
        modality="images",
        num_frames=8,
        dataset_name=ds_name,
    )
    out_yaml = tmp_path / "fold0_images_8f.yaml"
    cfg, cmds = render_config_bundle(
        fold=0,
        modality="images",
        num_frames=8,
        dataset_dir=str(bundle_dir),
        dataset_name=ds_name,
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
    assert cmds["dataset_bundle_verification"]["verified"] is True

    vllm_cmd = cmds["vllm_serve_lora_command"]
    assert PURE_SYSTEM_PATH in vllm_cmd
    assert VLM_EVAL_VLLM_BIN in vllm_cmd
    assert "--enable-lora" in vllm_cmd
    assert '"image": 8' in vllm_cmd
    assert "eval-test-v1" in cmds["eval_scope_warning"]


def test_render_16f_video_includes_bit_exact_vllm_flags(tmp_path: Path) -> None:
    ds_name = "tensile_five_label_fold0_video_16f"
    bundle_dir = _create_verified_bundle(
        tmp_path / "bundle_vid16",
        fold=0,
        modality="video",
        num_frames=16,
        dataset_name=ds_name,
    )
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
            str(bundle_dir),
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
    assert cmds["dataset_bundle_verification"]["verified"] is True

    vllm_cmd = cmds["vllm_serve_lora_command"]
    assert PURE_SYSTEM_PATH in vllm_cmd
    assert "--max-model-len \\\n  12288" in vllm_cmd
    assert "--media-io-kwargs" in vllm_cmd
    assert '"num_frames": -1' in vllm_cmd
    assert '"fps": 2.0' in vllm_cmd
    assert "--mm-processor-kwargs" in vllm_cmd
    assert '"do_sample_frames": false' in vllm_cmd
    assert '"cap_pixels_per_frame": false' in vllm_cmd


def test_render_blocks_cross_fold_mismatch_dry_run_and_tampered_bundle(tmp_path: Path) -> None:
    # Fold 0 bundle exported with generic dataset_name="train"
    fold0_bundle = _create_verified_bundle(
        tmp_path / "fold0_train_bundle",
        fold=0,
        modality="video",
        num_frames=16,
        dataset_name="train",
    )

    # Cross-fold mismatch: requesting Fold 1 config on Fold 0 bundle MUST fail closed
    with pytest.raises(InputError, match="fold=0 != requested 1"):
        render_config_bundle(
            fold=1,
            modality="video",
            num_frames=16,
            dataset_dir=str(fold0_bundle),
            dataset_name="train",
            train_output_dir="trains/fold1/adapter",
            output_yaml=tmp_path / "cross_fold.yaml",
        )

    # Modality mismatch MUST fail closed
    with pytest.raises(InputError, match="modality='video' != requested 'images'"):
        render_config_bundle(
            fold=0,
            modality="images",
            num_frames=8,
            dataset_dir=str(fold0_bundle),
            dataset_name="train",
            train_output_dir="trains/fold0/adapter",
            output_yaml=tmp_path / "bad_mod.yaml",
        )

    # Dry-run bundle MUST be rejected for runnable training config
    dry_bundle = _create_verified_bundle(
        tmp_path / "dry_bundle",
        fold=0,
        modality="video",
        num_frames=16,
        dataset_name="train",
        dry_run=True,
    )
    with pytest.raises(InputError, match="dry-run"):
        render_config_bundle(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir=str(dry_bundle),
            dataset_name="train",
            train_output_dir="trains/fold0/adapter",
            output_yaml=tmp_path / "dry.yaml",
        )

    # Pixel parameter drift vs verified preflight_report.json MUST fail closed
    with pytest.raises(InputError, match="pixel config mismatch"):
        render_config_bundle(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir=str(fold0_bundle),
            dataset_name="train",
            train_output_dir="trains/fold0/adapter",
            output_yaml=tmp_path / "drift_pixels.yaml",
            video_min_pixels=1_200_000,
        )

    # Tampered dataset JSON sha256 MUST fail closed
    (fold0_bundle / "train.json").write_bytes(b"[{\"tampered\": true}]\n")
    with pytest.raises(InputError, match="sha256 mismatch"):
        render_config_bundle(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir=str(fold0_bundle),
            dataset_name="train",
            train_output_dir="trains/fold0/adapter",
            output_yaml=tmp_path / "tampered.yaml",
        )


def test_render_refuses_protected_legacy_and_symlink_output_paths(tmp_path: Path) -> None:
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

    bundle = _create_verified_bundle(
        tmp_path / "ok_bundle", fold=0, modality="video", num_frames=16, dataset_name="demo"
    )
    # Protected output_yaml must be refused before creating directories
    bad_yaml = tmp_path / "data" / "sub_video" / "evil.yaml"
    with pytest.raises(InputError, match="protected path"):
        render_config_bundle(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir=str(bundle),
            dataset_name="demo",
            train_output_dir="trains/ok/adapter",
            output_yaml=bad_yaml,
        )
    assert not bad_yaml.parent.exists()

    # Symlink output_yaml pointing to another file must be refused even with overwrite=True
    victim = tmp_path / "victim.txt"
    victim.write_text("DO_NOT_TOUCH", encoding="utf-8")
    link_yaml = tmp_path / "linked.yaml"
    link_yaml.symlink_to(victim)
    with pytest.raises(InputError, match="symlink"):
        render_config_bundle(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir=str(bundle),
            dataset_name="demo",
            train_output_dir="trains/ok/adapter",
            output_yaml=link_yaml,
            overwrite=True,
        )
    assert victim.read_text(encoding="utf-8") == "DO_NOT_TOUCH"


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


def test_render_pins_absolute_dataset_dir_across_cwd_changes_and_blocks_case_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fold0_run = tmp_path / "run_fold0"
    fold1_run = tmp_path / "run_fold1"
    fold0_input = _create_verified_bundle(
        fold0_run / "input", fold=0, modality="video", num_frames=16, dataset_name="train"
    )
    _create_verified_bundle(
        fold1_run / "input", fold=1, modality="video", num_frames=16, dataset_name="train"
    )

    monkeypatch.chdir(fold0_run)
    out_yaml = fold0_run / "qlora_fold0.yaml"
    render_config_bundle(
        fold=0,
        modality="video",
        num_frames=16,
        dataset_dir="input",  # relative path
        dataset_name="train",
        train_output_dir="trains/fold0/adapter",
        output_yaml=out_yaml,
    )
    # Switch cwd to Fold 1 run dir; YAML MUST still point to Fold 0's absolute verified input dir
    monkeypatch.chdir(fold1_run)
    loaded = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
    assert Path(loaded["dataset_dir"]) == fold0_input.resolve()
    assert Path(loaded["dataset_dir"]).is_absolute()

    # Pre-launch verification passes on untouched Fold 0 bundle, and fails closed if bundle is swapped to Fold 1
    cmd_json = out_yaml.with_suffix(".commands.json")
    cmds = json.loads(cmd_json.read_text(encoding="utf-8"))
    assert "--verify-commands-json" in cmds["train_command_manual_only"]
    assert verify_rendered_launch(cmd_json)["verified"] is True
    assert render_main(["--verify-commands-json", str(cmd_json)]) == 0

    # Simulate overwriting Fold 0's dataset dir with Fold 1 bundle -> pre-launch guard MUST block!
    _create_verified_bundle(
        fold0_run / "input", fold=1, modality="video", num_frames=16, dataset_name="train"
    )
    with pytest.raises(InputError, match="fold=1 != requested 0"):
        verify_rendered_launch(cmd_json)
    assert render_main(["--verify-commands-json", str(cmd_json)]) == 2

    # Refusing non-.yaml/.yml output path (prevents overwriting dataset_info.json in bundle dir)
    with pytest.raises(InputError, match=r"\.yaml or \.yml"):
        render_config_bundle(
            fold=1,
            modality="video",
            num_frames=16,
            dataset_dir=str(fold0_input),
            dataset_name="train",
            train_output_dir="trains/fold1/adapter",
            output_yaml=fold0_input / "dataset_info.json",
            overwrite=True,
        )

    # Case-insensitive protected path alias (e.g. data/SPLITS/three-fold/evil.yaml on macOS) MUST be refused
    splits_dir = tmp_path / "data/splits/three-fold"
    splits_dir.mkdir(parents=True)
    with pytest.raises(InputError, match="protected path"):
        render_config_bundle(
            fold=1,
            modality="video",
            num_frames=16,
            dataset_dir=str(fold0_input),
            dataset_name="train",
            train_output_dir="trains/fold1/adapter",
            output_yaml=tmp_path / "data/SPLITS/three-fold/evil.yaml",
            overwrite=True,
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
