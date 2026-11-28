"""Unit tests for LlamaFactory QLoRA YAML and paired vLLM LoRA command renderer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any
import zlib

import pytest
import yaml

from script.five_label_eval.errors import InputError
from script.five_label_sft.constants import (
    ADAPTER_PROVENANCE_SCHEMA,
    BUILD_SUMMARY_SCHEMA,
    FRAME_LINEAGE_SCHEMA,
    PURE_SYSTEM_PATH,
    VLM_EVAL_VLLM_BIN,
)
from script.five_label_sft.render_config import (
    ADAPTER_PROVENANCE_FILENAME,
    build_qlora_config,
    build_runtime_commands,
    main as render_main,
    render_config_bundle,
    run_verified_training,
    verify_rendered_launch,
    verify_serve_launch,
)


def _make_png(r: int, g: int, b: int) -> bytes:
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)

    ihdr = struct.pack("!IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes([r & 0xFF, g & 0xFF, b & 0xFF]) * 4
    idat = zlib.compress(row * 4, level=1)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


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
    frames_dir = bundle_dir / "_frames"
    frames_dir.mkdir(exist_ok=True)
    frame_paths: list[str] = []
    verified_frame_shas: dict[str, str] = {}
    for i in range(num_frames):
        fp = (frames_dir / f"f{i:02d}.png").resolve()
        raw = _make_png(fold + 1, i, 42)
        fp.write_bytes(raw)
        frame_paths.append(str(fp))
        verified_frame_shas[str(fp)] = hashlib.sha256(raw).hexdigest()

    ds_file = f"{dataset_name}.json"
    media_col = "images" if modality == "images" else "videos"
    sample_row: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": ("<image>" * num_frames if modality == "images" else "<video>") + "\nprompt"},
            {"role": "assistant", "content": "{}"},
        ],
        media_col: frame_paths if modality == "images" else [frame_paths],
    }
    ds_bytes = (json.dumps([sample_row], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
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
    cid = f"video_000{fold + 2}_fracture_01"
    sid = f"video_000{fold + 2}"
    manifest_sha = hashlib.sha256(f"manifest:{fold}".encode()).hexdigest()
    # Mirror real preflight.py schema: images uses grid_thw=[num_frames, gh, gw], video uses [num_frames//2, gh, gw]
    # and resized_size=[resized_width, resized_height].
    grid = [num_frames // 2, 4, 4] if modality == "video" else [num_frames, 4, 4]
    vis_pad = (grid[0] * grid[1] * grid[2] // 4) if modality == "video" else (num_frames * (grid[1] * grid[2] // 4))
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
        "samples": [
            {
                "candidate_id": cid,
                "source_id": sid,
                "grid_thw": grid,
                "visual_pad_tokens": vis_pad,
                "resized_size": [grid[2] * 16, grid[1] * 16],
                "estimated_total_tokens": max_est_tokens,
            }
        ],
    }
    preflight_bytes = (json.dumps(preflight_obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (bundle_dir / "preflight_report.json").write_bytes(preflight_bytes)

    lineage_row = {
        "schema": FRAME_LINEAGE_SCHEMA,
        "sample_index": 0,
        "candidate_id": cid,
        "source_id": sid,
        "input_id": "input@sha256:" + "1" * 64,
        "modality": modality,
        "num_frames": num_frames,
        "video_fps": 2.0 if modality == "video" else None,
        "clip_sha256": "2" * 64,
        "manifest_sha256": manifest_sha,
        "review_id": "rev-1",
        "review_revision_sha256": "3" * 64,
        "width": 64,
        "height": 64,
        "total_frames": 60,
        "fps": 30.0,
        "source_start_frame": 100,
        "lineage_verification": {"method": "unverified", "verdict_id": "unverified", "failed_conditions": []},
        "frames": [
            {
                "display_order": idx,
                "emitted_path": frame_paths[idx],
                "png_sha256": verified_frame_shas[frame_paths[idx]],
                "clip_frame_index": idx * 3,
                "pts_seconds": round((idx * 3) / 30.0, 6),
                "verified_roi_frame_index": None,
                "verified_original_frame_index": None,
                "derived_roi_frame_index": 100 + idx * 3,
                "derived_original_frame_index": 100 + idx * 3,
                "derived_index_status": "derived_planned",
                "temporal_pair_index": idx // 2 if modality == "video" else None,
                "injected_timestamp_sec": ((idx // 2) + 0.25) if modality == "video" else None,
                "injected_timestamp_label": f"<{(idx // 2) + 0.25:.1f} seconds>" if modality == "video" else None,
                "frame_index_mapping": {
                    "clip_to_model_input": {"status": "verified"},
                    "clip_to_roi": {"status": "unverified"},
                    "roi_to_original": {"status": "unverified"},
                },
            }
            for idx in range(num_frames)
        ],
    }
    lineage_bytes = (json.dumps(lineage_row, ensure_ascii=False) + "\n").encode("utf-8")
    (bundle_dir / "frame_lineage.jsonl").write_bytes(lineage_bytes)

    summary_obj: dict[str, Any] = {
        "schema": BUILD_SUMMARY_SCHEMA,
        "dataset_name": dataset_name,
        "dataset_file": ds_file,
        "frame_lineage_file": "frame_lineage.jsonl",
        "fold": fold,
        "modality": modality,
        "num_frames": num_frames,
        "video_fps": 2.0 if modality == "video" else None,
        "dry_run_missing_frames": dry_run,
        "strict_target_json_verified": True,
        "inputs": {
            "manifest_sha256": manifest_sha,
        },
        "isolation_checks": {
            "exported_candidate_count": 1,
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
            "frame_lineage_sha256": hashlib.sha256(lineage_bytes).hexdigest(),
        },
        "preflight_summary": {
            "estimated_total_tokens": {"max": max_est_tokens},
        },
        "exported_candidate_ids": [cid],
        "verified_frame_sha256s": verified_frame_shas,
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
    cmds = json.loads(Path(f"{out_yaml}.commands.json").read_text(encoding="utf-8"))
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

    # Pre-launch verification passes on untouched Fold 0 bundle
    cmd_json = Path(f"{out_yaml}.commands.json")
    cmds = json.loads(cmd_json.read_text(encoding="utf-8"))
    assert "--run-verified-train" in cmds["train_command_manual_only"]
    assert "--verify-yaml" in cmds["train_command_manual_only"]
    assert Path(loaded["output_dir"]).is_absolute()
    assert verify_rendered_launch(cmd_json, expected_yaml_path=out_yaml)["verified"] is True
    assert render_main(["--verify-commands-json", str(cmd_json), "--verify-yaml", str(out_yaml)]) == 0

    # 0. Companion commands JSON keeps full suffix (.yaml vs .yml) and --verify-yaml blocks YAML mismatch
    alt_yml = fold0_run / "qlora_fold0.yml"
    render_config_bundle(
        fold=1,
        modality="video",
        num_frames=16,
        dataset_dir=str(fold1_run / "input"),
        dataset_name="train",
        train_output_dir=str(tmp_path / "fold1_alt_adapter"),
        output_yaml=alt_yml,
    )
    assert Path(f"{alt_yml}.commands.json").is_file()
    assert cmd_json.is_file()
    with pytest.raises(InputError, match="launch YAML mismatch"):
        verify_rendered_launch(Path(f"{alt_yml}.commands.json"), expected_yaml_path=out_yaml)

    # Comma in dataset_name MUST be rejected by render_config as well
    with pytest.raises(InputError, match="single identifier"):
        build_qlora_config(
            fold=0,
            modality="video",
            num_frames=16,
            dataset_dir="trains/in",
            dataset_name="baseline,fold0",
            train_output_dir="trains/out",
        )

    # 1. Swapping a referenced PNG at its original path AFTER export/render MUST be rejected pre-launch!
    orig_png = fold0_input / "_frames/f00.png"
    orig_png_bytes = orig_png.read_bytes()
    orig_png.write_bytes(_make_png(200, 200, 200))
    with pytest.raises(InputError, match="training frame PNG sha256 mismatch"):
        verify_rendered_launch(cmd_json)
    orig_png.write_bytes(orig_png_bytes)
    assert verify_rendered_launch(cmd_json)["verified"] is True

    # 2. Pre-existing checkpoint-* in output_dir MUST be rejected pre-launch (prevents cross-fold auto-resume)
    ckpt_dir = Path(loaded["output_dir"]) / "checkpoint-10"
    ckpt_dir.mkdir(parents=True)
    with pytest.raises(InputError, match="existing checkpoint/adapter"):
        verify_rendered_launch(cmd_json)
    ckpt_dir.rmdir()
    Path(loaded["output_dir"]).rmdir()

    # 3. Simulate overwriting Fold 0's dataset dir with Fold 1 bundle -> pre-launch guard MUST block!
    _create_verified_bundle(
        fold0_run / "input", fold=1, modality="video", num_frames=16, dataset_name="train"
    )
    with pytest.raises(InputError, match="fold=1 != requested 0"):
        verify_rendered_launch(cmd_json)
    assert render_main(["--verify-commands-json", str(cmd_json)]) == 2

    # 4. Refusing non-.yaml/.yml and uppercase .YAML output paths
    for bad_out in (fold0_input / "dataset_info.json", fold0_run / "UPPER.YAML"):
        with pytest.raises(InputError, match=r"lowercase \.yaml or \.yml"):
            render_config_bundle(
                fold=1,
                modality="video",
                num_frames=16,
                dataset_dir=str(fold0_input),
                dataset_name="train",
                train_output_dir=str(tmp_path / "fresh_out/adapter"),
                output_yaml=bad_out,
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


def test_frame_lineage_tampering_and_adapter_provenance_serve_guard(tmp_path: Path) -> None:
    ds_name = "tensile_five_label_fold0_video_16f"
    bundle_dir = _create_verified_bundle(
        tmp_path / "bundle_prov",
        fold=0,
        modality="video",
        num_frames=16,
        dataset_name=ds_name,
    )
    adapter_dir = tmp_path / "fold0_adapter"
    yaml_path = tmp_path / "fold0_prov.yaml"
    _, cmds = render_config_bundle(
        fold=0,
        modality="video",
        num_frames=16,
        dataset_dir=str(bundle_dir),
        dataset_name=ds_name,
        train_output_dir=str(adapter_dir),
        output_yaml=yaml_path,
    )
    cmd_json = Path(f"{yaml_path}.commands.json")
    assert "--run-verified-train" in cmds["train_command_manual_only"]
    assert "--verify-serve-commands-json" in cmds["vllm_serve_lora_command"]

    # 1. Tampering frame_lineage.jsonl fails closed pre-launch
    lin_path = bundle_dir / "frame_lineage.jsonl"
    orig_lin = lin_path.read_bytes()
    lin_path.write_bytes(b"{}\n")
    with pytest.raises(InputError, match="frame_lineage.jsonl: sha256 mismatch"):
        verify_rendered_launch(cmd_json)
    lin_path.write_bytes(orig_lin)

    # 2. Pre-existing copied weights in adapter_dir MUST block controlled launch AND fail pre-serve
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "adapter_config.json").write_text(json.dumps({"r": 16, "lora_alpha": 32}), encoding="utf-8")
    (adapter_dir / "adapter_model.safetensors").write_bytes(b"preexisting-fold1-weights")
    with pytest.raises(InputError, match="existing checkpoint/adapter"):
        run_verified_training(cmd_json, expected_yaml_path=yaml_path, train_runner=lambda _: 0)
    with pytest.raises(InputError, match=ADAPTER_PROVENANCE_FILENAME):
        verify_serve_launch(cmd_json, expected_fold=0, expected_adapter_dir=adapter_dir)

    # Clean adapter_dir, verify failed training subprocess (rc != 0) does NOT seal provenance
    (adapter_dir / "adapter_config.json").unlink()
    (adapter_dir / "adapter_model.safetensors").unlink()

    def _failing_train(_yaml: Path) -> int:
        (adapter_dir / "adapter_config.json").write_text(json.dumps({"r": 16}), encoding="utf-8")
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"partial-weights")
        return 1

    with pytest.raises(InputError, match="exit code 1"):
        run_verified_training(cmd_json, expected_yaml_path=yaml_path, train_runner=_failing_train)
    assert not (adapter_dir / ADAPTER_PROVENANCE_FILENAME).exists()
    (adapter_dir / "adapter_config.json").unlink()
    (adapter_dir / "adapter_model.safetensors").unlink()

    # 3. Controlled run_verified_training verifies clean dir, runs training, seals provenance on rc==0
    def _ok_train(_yaml: Path) -> int:
        adapter_dir.mkdir(parents=True, exist_ok=True)
        (adapter_dir / "adapter_config.json").write_text(json.dumps({"r": 16, "lora_alpha": 32}), encoding="utf-8")
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"fake-safetensors-weights")
        return 0

    prov = run_verified_training(cmd_json, expected_yaml_path=yaml_path, train_runner=_ok_train)
    assert prov["schema"] == ADAPTER_PROVENANCE_SCHEMA
    assert prov["fold"] == 0
    assert verify_serve_launch(cmd_json, expected_fold=0, expected_adapter_dir=adapter_dir) == prov
    assert render_main([
        "--verify-serve-commands-json",
        str(cmd_json),
        "--expected-fold",
        "0",
        "--expected-adapter-dir",
        str(adapter_dir),
    ]) == 0

    # 4. Cross-fold serve attempt fails closed
    with pytest.raises(InputError, match="pre-serve fold mismatch"):
        verify_serve_launch(cmd_json, expected_fold=1, expected_adapter_dir=adapter_dir)

    # 5. Swapping weights with same-rank Fold 1 weights: BOTH verify_serve_launch AND re-running train fail closed!
    (adapter_dir / "adapter_model.safetensors").write_bytes(b"swapped-cross-fold-weights")
    with pytest.raises(InputError, match="sha256 mismatch"):
        verify_serve_launch(cmd_json, expected_fold=0, expected_adapter_dir=adapter_dir)
    with pytest.raises(InputError, match="existing checkpoint/adapter"):
        run_verified_training(cmd_json, expected_yaml_path=yaml_path, train_runner=_ok_train)

    # 6. Mismatched adapter_config rank r vs YAML lora_rank fails closed inside run_verified_training
    adapter_dir2 = tmp_path / "fold0_adapter_badrank"
    yaml_path2 = tmp_path / "fold0_badrank.yaml"
    render_config_bundle(
        fold=0,
        modality="video",
        num_frames=16,
        dataset_dir=str(bundle_dir),
        dataset_name=ds_name,
        train_output_dir=str(adapter_dir2),
        output_yaml=yaml_path2,
    )
    cmd_json2 = Path(f"{yaml_path2}.commands.json")

    def _bad_rank_train(_yaml: Path) -> int:
        adapter_dir2.mkdir(parents=True, exist_ok=True)
        (adapter_dir2 / "adapter_config.json").write_text(json.dumps({"r": 64}), encoding="utf-8")
        (adapter_dir2 / "adapter_model.safetensors").write_bytes(b"rank64-weights")
        return 0

    with pytest.raises(InputError, match="adapter rank r=64 != YAML lora_rank=16"):
        run_verified_training(cmd_json2, expected_yaml_path=yaml_path2, train_runner=_bad_rank_train)
