from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import GENERATION_CONFIG, VIDEO_MAX_FRAMES
from pipeline.preprocessing.minicpm_preprocessor import configure_processor_max_frames

FOUR_BIT_INFERENCE_PRECISION = "bnb_4bit_nf4_resampler_bf16"
FOUR_BIT_SKIP_MODULES = ("resampler",)


@dataclass(frozen=True)
class ModelRunResult:
    raw_output: str
    sampled_timestamps: list[float]
    generated_token_count: int | None
    hit_token_limit: bool | None
    frame_paths: list[str]


def load_model(
    model_dir: str,
    *,
    quantization_bit: int | None = None,
) -> tuple[Any, Any]:
    import torch
    from transformers import (
        AutoImageProcessor,
        AutoModel,
        AutoProcessor,
        AutoTokenizer,
        BitsAndBytesConfig,
    )

    if quantization_bit not in (None, 4):
        raise ValueError("quantization_bit must be None or 4")

    model_path = _sanitize_model_path(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    AutoImageProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    processor.tokenizer = tokenizer
    configure_processor_max_frames(processor)
    if getattr(processor, "chat_template", None) is None and getattr(tokenizer, "chat_template", None) is not None:
        processor.chat_template = tokenizer.chat_template

    torch_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else "auto"
    model_kwargs: dict[str, Any] = {}
    if quantization_bit == 4:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch_dtype,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_quant_storage=torch_dtype,
            llm_int8_skip_modules=list(FOUR_BIT_SKIP_MODULES),
        )
    model = AutoModel.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        device_map="auto",
        low_cpu_mem_usage=True,
        **model_kwargs,
    ).eval()
    return processor, model


def run_model_on_video(model: Any, processor: Any, video_path: Path, prompt: str, system_prompt: str | None = None) -> str:
    return run_model_on_video_detailed(
        model,
        processor,
        video_path,
        prompt,
        system_prompt=system_prompt,
        max_new_tokens=GENERATION_CONFIG["max_new_tokens"],
    ).raw_output


def run_model_on_video_detailed(
    model: Any,
    processor: Any,
    video_path: Path,
    prompt: str,
    system_prompt: str | None = None,
    max_new_tokens: int = GENERATION_CONFIG["max_new_tokens"],
    frame_dir: Path | None = None,
) -> ModelRunResult:
    import torch

    from .video_loader import load_video_frames

    frames, temporal_ids, timestamps = load_video_frames(str(video_path), max_frames=VIDEO_MAX_FRAMES)
    frame_paths = _write_sampled_frames(frames, timestamps, frame_dir) if frame_dir else []
    image_tags = "".join("(<image>./</image>)" for _ in frames)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": f"{image_tags}\n{prompt}"})
    prompt_text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(
        text=prompt_text,
        images=frames,
        temporal_ids=temporal_ids,
        max_slice_nums=1,
        use_image_id=False,
        return_tensors="pt",
    ).to(model.device)
    # `image_sizes` is a processor-only helper that MiniCPM's _decode would pass
    # through to the text LLM. Keep temporal_ids/image_bound/tgt_sizes: MiniCPM
    # needs them to build video embeddings.
    inputs.pop("image_sizes", None)

    with torch.no_grad():
        generated = model.generate(
            **inputs,
            tokenizer=processor.tokenizer,
            do_sample=GENERATION_CONFIG["do_sample"],
            num_beams=GENERATION_CONFIG["num_beams"],
            max_new_tokens=max_new_tokens,
            decode_text=True,
        )[0]
    raw_output = str(generated)
    token_count: int | None = None
    try:
        token_count = len(processor.tokenizer.encode(raw_output, add_special_tokens=False))
    except Exception:
        pass
    return ModelRunResult(
        raw_output=raw_output,
        sampled_timestamps=[round(float(value), 6) for value in timestamps],
        generated_token_count=token_count,
        hit_token_limit=token_count >= max_new_tokens if token_count is not None else None,
        frame_paths=frame_paths,
    )


def _write_sampled_frames(frames: list[Any], timestamps: list[float], frame_dir: Path) -> list[str]:
    """Persist the exact RGB frames supplied to the processor for later review."""
    frame_dir.mkdir(parents=True, exist_ok=False)
    paths: list[str] = []
    for index, (frame, timestamp) in enumerate(zip(frames, timestamps, strict=True)):
        path = frame_dir / f"frame_{index:02d}_{timestamp:.3f}s.png"
        frame.save(path)
        paths.append(str(path))
    if frames:
        width = max(frame.width for frame in frames)
        height = max(frame.height for frame in frames)
        from PIL import Image, ImageDraw

        sheet = Image.new("RGB", (width * len(frames), height + 28), "white")
        draw = ImageDraw.Draw(sheet)
        for index, (frame, timestamp) in enumerate(zip(frames, timestamps, strict=True)):
            sheet.paste(frame, (index * width, 0))
            draw.text((index * width + 4, height + 4), f"{index}: {timestamp:.3f}s", fill="black")
        sheet.save(frame_dir / "contact_sheet.png")
    return paths


def _sanitize_model_path(model_dir: str) -> str:
    path = Path(model_dir).resolve()
    if "." not in path.name and "-" not in path.name:
        return str(path)
    safe_path = path.parent / path.name.replace(".", "_").replace("-", "_")
    if not safe_path.exists():
        safe_path.symlink_to(path, target_is_directory=True)
    return str(safe_path)
