# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：无
# 未随迁：无（本文件不读写 finetune/results/diagnostics/ 下的数据）
# 迁移已知影响：正文 `from finetune.results.diagnostics.*` 导入在迁入后不可解析（`run_dataset_evaluation.py` 未迁、`score_diagnostic_evaluation.py` 已落入本目录）。

#!/usr/bin/env python3
"""Create controlled frame variants and evaluate visual sensitivity."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.results.diagnostics.run_dataset_evaluation import (
    assistant_target,
    content,
)
from finetune.results.diagnostics.score_diagnostic_evaluation import extract_json
from finetune.validation.datasets import EvalSample
from finetune.validation.model_runtime import load_model, run_model_on_video
from finetune.validation.run_evaluation import evaluate_sample, write_outputs
from finetune.validation.video_loader import load_video_frames

VARIANTS = ("original", "repeat_first", "reverse", "black")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-file", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def write_video(path: Path, frames: list[Image.Image]) -> None:
    import av

    if not frames:
        raise ValueError(f"cannot write empty video: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    width = frames[0].width - frames[0].width % 2
    height = frames[0].height - frames[0].height % 2
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=2)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        for image in frames:
            normalized = image.convert("RGB").resize((width, height))
            frame = av.VideoFrame.from_image(normalized)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def make_variants(source: Path, output_dir: Path) -> dict[str, Path]:
    frames, _, _ = load_video_frames(str(source), max_frames=8)
    if not frames:
        raise ValueError(f"no frames decoded from {source}")
    black = Image.new("RGB", frames[0].size, "black")
    variant_frames = {
        "original": frames,
        "repeat_first": [frames[0].copy() for _ in frames],
        "reverse": list(reversed(frames)),
        "black": [black.copy() for _ in frames],
    }
    paths = {}
    for variant, selected in variant_frames.items():
        path = output_dir / f"{variant}.mp4"
        if not path.is_file():
            write_video(path, selected)
        paths[variant] = path
    return paths


def summarize(records: list[dict[str, Any]], out_dir: Path) -> None:
    predictions: dict[tuple[int, str], dict[str, Any] | None] = {}
    for record in records:
        parsed, _ = extract_json(record["raw_output"])
        metadata = record["metadata"]
        predictions[(metadata["row_index"], metadata["variant"])] = parsed
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "exact_changed": 0, "has_changed": 0, "interval_changed": 0}
    )
    rows = []
    for row_index in sorted({key[0] for key in predictions}):
        original = predictions[(row_index, "original")]
        row = {"row_index": row_index, "original": original, "variants": {}}
        for variant in VARIANTS[1:]:
            value = predictions[(row_index, variant)]
            item = {
                "prediction": value,
                "exact_changed": value != original,
                "has_changed": (value or {}).get("has_fracture")
                != (original or {}).get("has_fracture"),
                "interval_changed": (value or {}).get("fracture_between")
                != (original or {}).get("fracture_between"),
            }
            row["variants"][variant] = item
            counts[variant]["total"] += 1
            for key in ("exact_changed", "has_changed", "interval_changed"):
                counts[variant][key] += bool(item[key])
        rows.append(row)
    metrics = {}
    for variant, values in counts.items():
        total = values["total"]
        metrics[variant] = {
            key + "_rate": round(values[key] / total, 6) if total else None
            for key in ("exact_changed", "has_changed", "interval_changed")
        }
    (out_dir / "counterfactual_sensitivity.json").write_text(
        json.dumps({"metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    dataset_path = (ROOT / args.dataset_file).resolve()
    model_dir = (ROOT / args.model_dir).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    variant_root = out_dir / "videos"
    records = json.loads(dataset_path.read_text(encoding="utf-8"))
    processor, model = load_model(str(model_dir))
    evaluated: list[dict[str, Any]] = []
    first_prompt = ""
    for row_index, record in enumerate(records):
        source = Path(record["videos"][0])
        if not source.is_absolute():
            source = ROOT / source
        variants = make_variants(source, variant_root / f"sample_{row_index:02d}")
        target = assistant_target(record)
        user_prompt = content(record, "user")
        system_prompt = content(record, "system")
        first_prompt = first_prompt or user_prompt
        source_match = re.match(r"(video_\d+)", source.stem)
        for variant, video_path in variants.items():
            sample = EvalSample(
                sample_id=f"diagnostic_{row_index:02d}_{variant}",
                video_id=f"{source.stem}__{variant}",
                video_path=video_path,
                metadata={
                    "source": str(dataset_path),
                    "row_index": row_index,
                    "variant": variant,
                    "source_video_id": (
                        source_match.group(1) if source_match else source.stem
                    ),
                    "ground_truth": target,
                },
            )
            try:
                raw_output = run_model_on_video(
                    model,
                    processor,
                    video_path,
                    user_prompt,
                    system_prompt=system_prompt,
                )
                error = None
            except Exception as exc:
                raw_output = ""
                error = f"{type(exc).__name__}: {exc}"
            evaluated.append(evaluate_sample(sample, raw_output, error))

    for variant in VARIANTS:
        selected = [
            record for record in evaluated if record["metadata"]["variant"] == variant
        ]
        write_outputs(
            out_dir=out_dir / variant,
            records=selected,
            dataset=f"{dataset_path.name}:{variant}",
            model_dir=str(model_dir),
            prompt="dataset_embedded",
            prompt_text=first_prompt,
        )
    summarize(evaluated, out_dir)


if __name__ == "__main__":
    main()
