# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：无
# 未随迁：无（本文件不读写 finetune/results/diagnostics/ 下的数据）

#!/usr/bin/env python3
"""Build compact, labeled montages from exact-frame contact sheets."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--frames-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rows-per-montage", type=int, default=6)
    parser.add_argument("--row-width", type=int, default=1800)
    parser.add_argument("--label-height", type=int, default=42)
    parser.add_argument("--show-ground-truth", action="store_true")
    parser.add_argument("--webp-quality", type=int, default=68)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = json.loads(args.sample_manifest.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for montage_number in range(math.ceil(len(samples) / args.rows_per_montage)):
        chunk = samples[
            montage_number
            * args.rows_per_montage : (montage_number + 1)
            * args.rows_per_montage
        ]
        prepared = []
        for sample in chunk:
            sheet_path = args.frames_dir / sample["sample_id"] / "contact_sheet.png"
            with Image.open(sheet_path) as source:
                sheet = source.convert("RGB")
                scale = min(1.0, args.row_width / sheet.width)
                resized = sheet.resize(
                    (round(sheet.width * scale), round(sheet.height * scale))
                )
            prepared.append((sample, resized))
        row_height = max(image.height for _, image in prepared) + args.label_height
        canvas = Image.new(
            "RGB",
            (args.row_width, row_height * len(prepared)),
            "white",
        )
        draw = ImageDraw.Draw(canvas)
        montage_rows = []
        for row, (sample, image) in enumerate(prepared):
            top = row * row_height
            label = sample["sample_id"]
            if args.show_ground_truth:
                label += (
                    f" | gt={sample['fracture_between']} | "
                    f"{sample['type']} | {sample['location']}"
                )
            draw.text((6, top + 6), label, fill="black")
            canvas.paste(image, (0, top + args.label_height))
            montage_rows.append(
                {
                    "row": row,
                    "sample_id": sample["sample_id"],
                    "ground_truth_interval": sample["fracture_between"],
                }
            )
        output_path = args.output_dir / f"montage_{montage_number + 1:02d}.webp"
        canvas.save(
            output_path,
            format="WEBP",
            quality=args.webp_quality,
            method=6,
        )
        index.append({"montage": output_path.name, "rows": montage_rows})
        print(output_path)
    (args.output_dir / "montage_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
