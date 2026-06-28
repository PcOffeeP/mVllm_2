"""Minimal model loading and inference test.
Run on the training machine (GPU required).

Usage:
    cd finetune/
    python -m validation.test_minimal
"""

import sys
from pathlib import Path


def main():
    base_model = Path(__file__).resolve().parents[2] / "models" / "minicpmv4_5"
    merged_model = (
        Path(__file__).resolve().parents[2]
        / "LlamaFactory" / "saves" / "minicpmv4_5" / "lora" / "sft_interval_3k0_merged"
    )
    
    print(f"Base model:  {base_model}  (exists={base_model.exists()})")
    print(f"Merged model: {merged_model}  (exists={merged_model.exists()})")
    
    # Step 1
    print("\n[Step 1] Loading tokenizer...")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        str(base_model), trust_remote_code=True, local_files_only=True
    )
    print(f"  type: {type(tokenizer).__name__}, vocab: {tokenizer.vocab_size}")
    
    # Step 2
    print("\n[Step 2] Loading image processor...")
    from transformers import AutoImageProcessor
    image_processor = AutoImageProcessor.from_pretrained(
        str(base_model), trust_remote_code=True, local_files_only=True
    )
    print(f"  type: {type(image_processor).__name__}")
    
    # Step 3
    print("\n[Step 3] Loading processor...")
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(
        str(base_model), trust_remote_code=True, local_files_only=True
    )
    print(f"  processor type: {type(processor).__name__}")
    print(f"  processor.tokenizer type: {type(processor.tokenizer).__name__ if processor.tokenizer else 'None'}")
    processor.tokenizer = tokenizer
    print(f"  After force-set: processor.tokenizer is tokenizer: {processor.tokenizer is tokenizer}")
    
    # Step 4
    print("\n[Step 4] Debugging chat template...")
    print(f"  tokenizer.chat_template present: {tokenizer.chat_template is not None}")
    if tokenizer.chat_template is not None:
        print(f"  tokenizer.chat_template (first 100 chars): {tokenizer.chat_template[:100]}")
    print(f"  processor.chat_template present: {processor.chat_template is not None}")
    print(f"  processor.tokenizer.chat_template present: {processor.tokenizer.chat_template is not None}")

    # Set chat_template on processor before using it
    processor.chat_template = tokenizer.chat_template
    print(f"  After force-set: processor.chat_template present: {processor.chat_template is not None}")

    messages = [{"role": "user", "content": "Say hello in one word."}]
    try:
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        print(f"  [processor] OK: {text[:80]}...")
    except Exception as e:
        print(f"  [processor] FAILED: {e}")
        sys.exit(1)
    
    # Step 5
    print("\n[Step 5] Loading model...")
    import torch
    from transformers import AutoModel
    model = AutoModel.from_pretrained(
        str(merged_model),
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        low_cpu_mem_usage=True,
    ).eval()
    print(f"  type: {type(model).__name__}, device: {model.device}")

    # Monkey-patch _decode to consume image_sizes
    original_decode = model._decode
    def _patched_decode(*args, **kwargs):
        kwargs.pop("image_sizes", None)
        return original_decode(*args, **kwargs)
    model._decode = _patched_decode
    
    # Step 6
    print("\n[Step 6] Running inference on real video...")
    from PIL import Image
    from .video_loader import load_video_frames

    # Pick a test video
    video_root = Path(__file__).resolve().parents[2] / "data" / "01_videos"
    video_path = video_root / "video_0003.mp4"
    print(f"  Video: {video_path}  (exists={video_path.exists()})")

    # Load frames
    frames, temporal_ids, timestamps = load_video_frames(
        str(video_path), max_frames=8
    )
    print(f"  Loaded {len(frames)} frames, timestamps: {[f'{t:.2f}' for t in timestamps]}")

    # Build a prompt matching the joint strict_interval training template
    prompt = (
        '请仅输出单个 JSON 对象，不得输出解释、Markdown、代码块。\n'
        '字段必须且只能包含以下五个字段：\n'
        '  has_fracture: true / false / null\n'
        '  fracture_between: [i, i+1] (整数对，i 范围 0-6) 或 null\n'
        '  type: 断裂类型字符串\n'
        '  location: "inside_gauge" / "outside_gauge" / null\n'
        '  confidence: 0-1 的数字\n'
        '\n'
        'type 只能从以下闭集中选择一个：\n'
        "韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂 / 未断裂 / 未夹紧 / 视频异常\n"
        '\n'
        '合法组合规则：\n'
        '1. 若 type 是七类断裂之一（韧性断裂 / 脆性断裂 / 界面脱粘 / 齐根断裂 / 界面脱粘、齐根断裂 / 爆炸性断裂 / 半脆半韧断裂）：\n'
        '   has_fracture 必须为 true；fracture_between 必须是相邻整数对 [i, i+1]（i 范围 0-6）；location 必须是 inside_gauge 或 outside_gauge。\n'
        '2. 若 type 是 未断裂 或 未夹紧：\n'
        '   has_fracture 必须为 false；fracture_between 必须为 null；location 必须为 null。\n'
        '3. 若 type 是 视频异常：\n'
        '   has_fracture 必须为 null；fracture_between 必须为 null；location 必须为 null。\n'
        '4. confidence 必须是 0 到 1 的数字。\n'
        '\n'
        '只输出单个 JSON 对象，不要有任何其他文字。'
    )
    image_tags = "".join("(<image>./</image>)" for _ in frames)
    content_str = f"{image_tags}\n{prompt}"
    messages = [{"role": "user", "content": content_str}]

    # Render chat template
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    print(f"  Prompt rendered: {len(text)} chars")

    # Encode text + images
    inputs = processor(
        text=text,
        images=frames,
        temporal_ids=temporal_ids,
        max_slice_nums=1,
        use_image_id=False,
        return_tensors="pt",
    ).to(model.device)
    print(f"  input_ids shape: {inputs.input_ids.shape}")

    # Generate
    inputs.pop("image_sizes", None)
    with torch.no_grad():
        response = model.generate(
            **inputs,
            tokenizer=tokenizer,
            max_new_tokens=50,
            do_sample=False,
            num_beams=1,
            decode_text=True,
        )[0]
    print(f"  Model response: {response}")
    print("\n✅ ALL TESTS PASSED")


if __name__ == "__main__":
    main()
