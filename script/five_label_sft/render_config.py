"""Render LlamaFactory 4-bit QLoRA YAML and paired vLLM LoRA evaluation commands."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shlex
import sys
from typing import Any

import yaml

from script.five_label_eval.errors import InputError

from .constants import (
    CONFIG_MANIFEST_SCHEMA,
    CUDA_ALLOC_CONF,
    DEFAULT_BASE_MODEL_PATH,
    DEFAULT_SERVED_MODEL_NAME,
    DEFAULT_TEMPLATE,
    PURE_SYSTEM_PATH,
    SUPPORTED_FOLDS,
    SUPPORTED_MODALITIES,
    SUPPORTED_NUM_FRAMES,
    VLM_EVAL_VLLM_BIN,
    VLM_SFT_LLAMAFACTORY_CLI,
    get_channel_preset,
)
from .data_guards import validate_fold, validate_safe_output_path


def _require_pos_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputError(f"{name} must be a positive integer, got {value!r}")
    return value


def _require_pos_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise InputError(f"{name} must be a positive finite number, got {value!r}")
    return float(value)


def _validate_train_output_dir(output_dir: str) -> str:
    return validate_safe_output_path(output_dir, label="train_output_dir")


def build_qlora_config(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    dataset_dir: str,
    dataset_name: str,
    train_output_dir: str,
    model_name_or_path: str = DEFAULT_BASE_MODEL_PATH,
    cutoff_len: int | None = None,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    video_fps: float | None = None,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    learning_rate: float = 1.0e-4,
    num_train_epochs: float = 3.0,
    gradient_accumulation_steps: int = 8,
    logging_steps: int = 5,
    save_strategy: str = "epoch",
    seed: int = 42,
) -> dict[str, Any]:
    """Build a LlamaFactory 4-bit QLoRA config dict aligned with DEC-008 and #5."""
    fold = validate_fold(fold)
    preset = get_channel_preset(modality, num_frames)
    clean_output_dir = _validate_train_output_dir(train_output_dir)

    if not isinstance(dataset_dir, str) or not dataset_dir.strip():
        raise InputError("dataset_dir must be non-empty")
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise InputError("dataset_name must be non-empty")
    if not isinstance(model_name_or_path, str) or not model_name_or_path.strip():
        raise InputError("model_name_or_path must be non-empty")

    eff_cutoff = _require_pos_int(cutoff_len if cutoff_len is not None else preset.cutoff_len, "cutoff_len")
    _require_pos_int(lora_rank, "lora_rank")
    _require_pos_int(lora_alpha, "lora_alpha")
    if (
        isinstance(lora_dropout, bool)
        or not isinstance(lora_dropout, (int, float))
        or not math.isfinite(lora_dropout)
        or not (0.0 <= lora_dropout < 1.0)
    ):
        raise InputError(f"lora_dropout must be in [0, 1), got {lora_dropout!r}")
    _require_pos_float(learning_rate, "learning_rate")
    _require_pos_float(num_train_epochs, "num_train_epochs")
    _require_pos_int(gradient_accumulation_steps, "gradient_accumulation_steps")
    _require_pos_int(logging_steps, "logging_steps")

    if modality == "images" and any(v is not None for v in (video_max_pixels, video_min_pixels, video_fps)):
        raise InputError("video_max_pixels/video_min_pixels/video_fps cannot be set when modality='images'")
    if modality == "video" and any(v is not None for v in (image_max_pixels, image_min_pixels)):
        raise InputError("image_max_pixels/image_min_pixels cannot be set when modality='video'")

    cfg: dict[str, Any] = {
        # Model & template (DEC-008 §1, §3)
        "model_name_or_path": model_name_or_path,
        "template": DEFAULT_TEMPLATE,
        "quantization_bit": 4,
        "quantization_method": "bnb",
        "trust_remote_code": False,
        # Method: 4-bit QLoRA
        "stage": "sft",
        "do_train": True,
        "finetuning_type": "lora",
        "lora_rank": lora_rank,
        "lora_alpha": lora_alpha,
        "lora_dropout": lora_dropout,
        "lora_target": "all",
        # Dataset (strictly Fold k clean train only)
        "dataset_dir": dataset_dir,
        "dataset": dataset_name,
        "cutoff_len": eff_cutoff,
        "overwrite_cache": True,
        "preprocessing_num_workers": 4,
    }

    if modality == "images":
        img_max = _require_pos_int(image_max_pixels if image_max_pixels is not None else preset.image_max_pixels, "image_max_pixels")
        img_min = _require_pos_int(image_min_pixels if image_min_pixels is not None else preset.image_min_pixels, "image_min_pixels")
        if img_min > img_max:
            raise InputError(f"image_min_pixels ({img_min}) must be <= image_max_pixels ({img_max})")
        cfg["image_max_pixels"] = img_max
        cfg["image_min_pixels"] = img_min
    else:
        vid_max = _require_pos_int(video_max_pixels if video_max_pixels is not None else preset.video_max_pixels, "video_max_pixels")
        vid_min = _require_pos_int(video_min_pixels if video_min_pixels is not None else preset.video_min_pixels, "video_min_pixels")
        if vid_min > vid_max:
            raise InputError(f"video_min_pixels ({vid_min}) must be <= video_max_pixels ({vid_max})")
        eff_fps = _require_pos_float(video_fps if video_fps is not None else preset.video_fps, "video_fps")
        cfg["video_max_pixels"] = vid_max
        cfg["video_min_pixels"] = vid_min
        cfg["video_fps"] = eff_fps

    cfg.update(
        {
            # Output
            "output_dir": clean_output_dir,
            "logging_steps": logging_steps,
            "save_strategy": save_strategy,
            "plot_loss": True,
            "overwrite_output_dir": False,
            # Train (DEC-008 §3 RTX 4090 24GB golden recipe)
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "learning_rate": learning_rate,
            "num_train_epochs": num_train_epochs,
            "lr_scheduler_type": "cosine",
            "warmup_ratio": 0.1,
            "bf16": True,
            "gradient_checkpointing": True,
            "optim": "paged_adamw_8bit",
            "ddp_timeout": 180000000,
            "seed": seed,
            "report_to": "none",
        }
    )
    return cfg


def build_runtime_commands(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    yaml_path: str,
    train_output_dir: str,
    model_name_or_path: str = DEFAULT_BASE_MODEL_PATH,
    served_model_name: str = DEFAULT_SERVED_MODEL_NAME,
    lora_module_name: str | None = None,
    lora_rank: int = 16,
    port: int = 18080,
    vllm_max_model_len: int | None = None,
    video_fps: float | None = None,
    gpu_memory_utilization: float = 0.88,
) -> dict[str, Any]:
    """Build exact manual training & vLLM LoRA serving commands with DEC-008 PATH isolation."""
    fold = validate_fold(fold)
    preset = get_channel_preset(modality, num_frames)
    _validate_train_output_dir(train_output_dir)
    _require_pos_int(lora_rank, "lora_rank")
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise InputError(f"port must be an integer in [1, 65535], got {port!r}")
    if (
        isinstance(gpu_memory_utilization, bool)
        or not isinstance(gpu_memory_utilization, (int, float))
        or not math.isfinite(gpu_memory_utilization)
        or not (0.0 < gpu_memory_utilization <= 1.0)
    ):
        raise InputError(f"gpu_memory_utilization must be in (0, 1], got {gpu_memory_utilization!r}")
    adapter_name = lora_module_name or f"qwen3vl-fold{fold}-{modality}-{num_frames}f"
    max_model_len = _require_pos_int(
        vllm_max_model_len if vllm_max_model_len is not None else preset.vllm_max_model_len,
        "vllm_max_model_len",
    )
    eff_fps = _require_pos_float(video_fps if video_fps is not None else (preset.video_fps or 2.0), "video_fps")

    train_cmd = (
        f"PYTORCH_CUDA_ALLOC_CONF={CUDA_ALLOC_CONF} "
        f"{VLM_SFT_LLAMAFACTORY_CLI} train {shlex.quote(yaml_path)}"
    )

    vllm_parts = [
        f"PATH={shlex.quote(PURE_SYSTEM_PATH)}",
        VLM_EVAL_VLLM_BIN,
        "serve",
        shlex.quote(model_name_or_path),
        "--served-model-name",
        shlex.quote(served_model_name),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--dtype",
        "bfloat16",
        "--gpu-memory-utilization",
        str(gpu_memory_utilization),
        "--max-model-len",
        str(max_model_len),
        "--max-num-seqs",
        "1",
        "--enable-lora",
        "--max-lora-rank",
        str(lora_rank),
        "--lora-modules",
        shlex.quote(f"{adapter_name}={train_output_dir}"),
    ]

    if modality == "images":
        vllm_parts.extend(
            [
                "--limit-mm-per-prompt",
                shlex.quote(json.dumps({"image": num_frames, "video": 0})),
            ]
        )
    else:
        vllm_parts.extend(
            [
                "--limit-mm-per-prompt",
                shlex.quote(json.dumps({"video": 1, "image": 0})),
                "--media-io-kwargs",
                shlex.quote(json.dumps({"video": {"num_frames": -1, "fps": eff_fps}})),
                "--mm-processor-kwargs",
                shlex.quote(json.dumps({"videos_kwargs": {"do_sample_frames": False, "cap_pixels_per_frame": False}})),
            ]
        )

    vllm_serve_cmd = " \\\n  ".join(vllm_parts)
    return {
        "schema": CONFIG_MANIFEST_SCHEMA,
        "fold": fold,
        "modality": modality,
        "num_frames": num_frames,
        "lora_module_name": adapter_name,
        "path_isolation_warning": (
            "DEC-008 §2: vLLM in vlm-eval MUST run with pure system PATH (excluding vlm-sft/bin/ninja) "
            "to prevent FlashInfer JIT nvcc --compress-mode=size crashes."
        ),
        "eval_scope_warning": (
            f"DEC-008 §5: Evaluate fold_{fold} adapter ONLY on eval-dev-v1 ∩ fold_{fold}_val "
            "(29 clean val sources). NEVER touch eval-test-v1."
        ),
        "train_command_manual_only": train_cmd,
        "vllm_serve_lora_command": vllm_serve_cmd,
    }


def render_config_bundle(
    *,
    fold: int,
    modality: str,
    num_frames: int,
    dataset_dir: str,
    dataset_name: str,
    train_output_dir: str,
    output_yaml: Path | str,
    model_name_or_path: str = DEFAULT_BASE_MODEL_PATH,
    cutoff_len: int | None = None,
    vllm_max_model_len: int | None = None,
    image_max_pixels: int | None = None,
    image_min_pixels: int | None = None,
    video_max_pixels: int | None = None,
    video_min_pixels: int | None = None,
    video_fps: float | None = None,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    learning_rate: float = 1.0e-4,
    num_train_epochs: float = 3.0,
    gradient_accumulation_steps: int = 8,
    port: int = 18080,
    overwrite: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write LlamaFactory YAML and companion runtime command JSON."""
    cfg = build_qlora_config(
        fold=fold,
        modality=modality,
        num_frames=num_frames,
        dataset_dir=dataset_dir,
        dataset_name=dataset_name,
        train_output_dir=train_output_dir,
        model_name_or_path=model_name_or_path,
        cutoff_len=cutoff_len,
        image_max_pixels=image_max_pixels,
        image_min_pixels=image_min_pixels,
        video_max_pixels=video_max_pixels,
        video_min_pixels=video_min_pixels,
        video_fps=video_fps,
        lora_rank=lora_rank,
        lora_alpha=lora_alpha,
        learning_rate=learning_rate,
        num_train_epochs=num_train_epochs,
        gradient_accumulation_steps=gradient_accumulation_steps,
    )
    yaml_path = Path(output_yaml)
    commands_path = yaml_path.with_suffix(".commands.json")
    validate_safe_output_path(yaml_path, label="output_yaml")
    validate_safe_output_path(commands_path, label="commands_json")

    commands = build_runtime_commands(
        fold=fold,
        modality=modality,
        num_frames=num_frames,
        yaml_path=str(yaml_path),
        train_output_dir=train_output_dir,
        model_name_or_path=model_name_or_path,
        lora_rank=lora_rank,
        port=port,
        vllm_max_model_len=vllm_max_model_len,
        video_fps=video_fps,
    )

    if not overwrite:
        existing = [str(p) for p in (yaml_path, commands_path) if p.exists()]
        if existing:
            raise InputError(f"refusing to overwrite existing config files (pass --overwrite): {existing}")

    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        f"# Auto-generated by script/five_label_sft/render_config.py (fold={fold}, modality={modality}, {num_frames}f)\n"
        f"# Launch manually with: PYTORCH_CUDA_ALLOC_CONF={CUDA_ALLOC_CONF} llamafactory-cli train <this_yaml>\n"
        f"# DEC-008 §5: Train strictly on clean fold_{fold}_train; evaluate only on eval-dev-v1 ∩ fold_{fold}_val.\n"
    )
    yaml_text = header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    yaml_path.write_text(yaml_text, encoding="utf-8")
    commands_path.write_text(json.dumps(commands, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg, commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, choices=SUPPORTED_FOLDS, required=True, help="CV fold (0, 1, or 2)")
    parser.add_argument("--modality", choices=SUPPORTED_MODALITIES, required=True, help="Channel modality: images or video")
    parser.add_argument("--num-frames", type=int, choices=SUPPORTED_NUM_FRAMES, required=True, help="Number of L3 frames per clip")
    parser.add_argument("--dataset-dir", required=True, help="Directory containing dataset_info.json and dataset JSON")
    parser.add_argument("--dataset-name", help="Dataset key in dataset_info.json (default: tensile_five_label_fold{k}_{modality}_{K}f)")
    parser.add_argument("--train-output-dir", required=True, help="Adapter output directory (e.g. trains/sft-fold0-video16f/adapter)")
    parser.add_argument("--output-yaml", required=True, help="Target YAML file path (also writes .commands.json)")
    parser.add_argument("--model-name-or-path", default=DEFAULT_BASE_MODEL_PATH, help="Base model path on training machine")
    parser.add_argument("--cutoff-len", type=int, help="Override cutoff_len")
    parser.add_argument("--vllm-max-model-len", type=int, help="Override vLLM --max-model-len")
    parser.add_argument("--image-max-pixels", type=int, help="Override image_max_pixels (images mode)")
    parser.add_argument("--image-min-pixels", type=int, help="Override image_min_pixels (images mode)")
    parser.add_argument("--video-max-pixels", type=int, help="Override video_max_pixels (video mode)")
    parser.add_argument("--video-min-pixels", type=int, help="Override video_min_pixels (video mode)")
    parser.add_argument("--video-fps", type=float, help="Override video_fps (video mode; default 2.0)")
    parser.add_argument("--lora-rank", type=int, default=16, help="LoRA rank (default 16)")
    parser.add_argument("--lora-alpha", type=int, default=32, help="LoRA alpha (default 32)")
    parser.add_argument("--learning-rate", type=float, default=1.0e-4, help="Learning rate (default 1e-4)")
    parser.add_argument("--num-train-epochs", type=float, default=3.0, help="Epochs (default 3.0)")
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8, help="Grad accumulation steps (default 8)")
    parser.add_argument("--port", type=int, default=18080, help="Loopback vLLM serving port (default 18080)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args(argv)

    try:
        ds_name = args.dataset_name or f"tensile_five_label_fold{args.fold}_{args.modality}_{args.num_frames}f"
        cfg, commands = render_config_bundle(
            fold=args.fold,
            modality=args.modality,
            num_frames=args.num_frames,
            dataset_dir=args.dataset_dir,
            dataset_name=ds_name,
            train_output_dir=args.train_output_dir,
            output_yaml=Path(args.output_yaml),
            model_name_or_path=args.model_name_or_path,
            cutoff_len=args.cutoff_len,
            vllm_max_model_len=args.vllm_max_model_len,
            image_max_pixels=args.image_max_pixels,
            image_min_pixels=args.image_min_pixels,
            video_max_pixels=args.video_max_pixels,
            video_min_pixels=args.video_min_pixels,
            video_fps=args.video_fps,
            lora_rank=args.lora_rank,
            lora_alpha=args.lora_alpha,
            learning_rate=args.learning_rate,
            num_train_epochs=args.num_train_epochs,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            port=args.port,
            overwrite=args.overwrite,
        )
        print(
            f"Wrote {args.output_yaml} & {Path(args.output_yaml).with_suffix('.commands.json')} "
            f"(template={cfg['template']}, cutoff_len={cfg['cutoff_len']}, lora={commands['lora_module_name']})"
        )
        return 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
