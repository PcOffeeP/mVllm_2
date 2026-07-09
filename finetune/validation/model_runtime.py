from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import GENERATION_CONFIG, VIDEO_MAX_FRAMES
from pipeline.preprocessing.minicpm_preprocessor import configure_processor_max_frames


def load_model(model_dir: str) -> tuple[Any, Any]:
    import torch
    from transformers import AutoImageProcessor, AutoModel, AutoProcessor, AutoTokenizer

    model_path = _sanitize_model_path(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    AutoImageProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    processor.tokenizer = tokenizer
    configure_processor_max_frames(processor)
    if getattr(processor, "chat_template", None) is None and getattr(tokenizer, "chat_template", None) is not None:
        processor.chat_template = tokenizer.chat_template

    torch_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else "auto"
    model = AutoModel.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        device_map="auto",
        low_cpu_mem_usage=True,
    ).eval()
    return processor, model


def run_model_on_video(model: Any, processor: Any, video_path: Path, prompt: str) -> str:
    import torch

    from .video_loader import load_video_frames

    frames, temporal_ids, _timestamps = load_video_frames(str(video_path), max_frames=VIDEO_MAX_FRAMES)
    image_tags = "".join("(<image>./</image>)" for _ in frames)
    messages = [{"role": "user", "content": f"{image_tags}\n{prompt}"}]
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
        return model.generate(
            **inputs,
            tokenizer=processor.tokenizer,
            do_sample=GENERATION_CONFIG["do_sample"],
            num_beams=GENERATION_CONFIG["num_beams"],
            max_new_tokens=GENERATION_CONFIG["max_new_tokens"],
            decode_text=True,
        )[0]


def _sanitize_model_path(model_dir: str) -> str:
    path = Path(model_dir).resolve()
    if "." not in path.name and "-" not in path.name:
        return str(path)
    safe_path = path.parent / path.name.replace(".", "_").replace("-", "_")
    if not safe_path.exists():
        safe_path.symlink_to(path, target_is_directory=True)
    return str(safe_path)
