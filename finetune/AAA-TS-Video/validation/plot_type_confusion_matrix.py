from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_INPUT = Path(__file__).resolve().parent / "results" / "type_eval" / "type_confusion_matrix.csv"
DEFAULT_OUTPUT = DEFAULT_INPUT.with_suffix(".png")
FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the type confusion matrix CSV as a PNG image.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Confusion matrix CSV path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="PNG output path.")
    parser.add_argument("--title", default="模式判断混淆矩阵", help="Image title.")
    return parser.parse_args()


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def load_matrix(path: Path) -> tuple[list[str], list[str], list[list[int]]]:
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        column_labels = reader.fieldnames[1:] if reader.fieldnames else []
        row_labels: list[str] = []
        matrix: list[list[int]] = []
        row_key = reader.fieldnames[0]
        for row in reader:
            row_labels.append(row[row_key])
            matrix.append([int(row[column]) for column in column_labels])
    return row_labels, column_labels, matrix


def color_for_value(value: int, max_value: int) -> tuple[int, int, int]:
    if max_value <= 0 or value <= 0:
        return (250, 250, 250)
    ratio = value / max_value
    r = 255
    g = int(245 - 145 * ratio)
    b = int(245 - 190 * ratio)
    return (r, g, b)


def text_color_for_value(value: int, max_value: int) -> tuple[int, int, int]:
    if max_value <= 0 or value / max_value < 0.45:
        return (20, 20, 20)
    return (255, 255, 255)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    left, top, right, bottom = box
    bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=4)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = left + (right - left - width) / 2
    y = top + (bottom - top - height) / 2
    draw.multiline_text((x, y), text, font=font, fill=fill, align="center", spacing=4)


def wrap_label(label: str) -> str:
    if label == "__INVALID__":
        return "INVALID"
    if "、" in label:
        return label.replace("、", "、\n")
    if len(label) > 6:
        midpoint = len(label) // 2
        return label[:midpoint] + "\n" + label[midpoint:]
    return label


def render_matrix(row_labels: list[str], column_labels: list[str], matrix: list[list[int]], output_path: Path, title: str) -> None:
    cell_w = 150
    cell_h = 84
    left_margin = 280
    top_margin = 210
    right_margin = 40
    bottom_margin = 60
    width = left_margin + len(column_labels) * cell_w + right_margin
    height = top_margin + len(row_labels) * cell_h + bottom_margin

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    title_font = load_font(34)
    label_font = load_font(22)
    cell_font = load_font(24)
    axis_font = load_font(26)

    title_box = (0, 18, width, 64)
    draw_centered_text(draw, title_box, title, title_font, (25, 25, 25))
    draw.text((left_margin, 92), "预测类别", font=axis_font, fill=(40, 40, 40))
    draw.text((18, top_margin - 44), "真实类别", font=axis_font, fill=(40, 40, 40))

    max_value = max(max(row) for row in matrix) if matrix else 0
    diagonal = sum(matrix[idx][idx] for idx in range(min(len(row_labels), len(column_labels))))
    total = sum(sum(row) for row in matrix)
    accuracy = diagonal / total if total else 0.0
    summary = f"样本数: {total}    对角线命中: {diagonal}    Accuracy: {accuracy:.2%}"
    draw.text((left_margin, 132), summary, font=label_font, fill=(70, 70, 70))

    for col_idx, label in enumerate(column_labels):
        box = (
            left_margin + col_idx * cell_w,
            top_margin - cell_h,
            left_margin + (col_idx + 1) * cell_w,
            top_margin,
        )
        draw.rounded_rectangle(box, radius=10, fill=(240, 243, 246), outline=(205, 210, 215), width=1)
        draw_centered_text(draw, box, wrap_label(label), label_font, (30, 30, 30))

    for row_idx, label in enumerate(row_labels):
        label_box = (24, top_margin + row_idx * cell_h, left_margin - 18, top_margin + (row_idx + 1) * cell_h)
        draw.rounded_rectangle(label_box, radius=10, fill=(247, 247, 247), outline=(220, 220, 220), width=1)
        draw_centered_text(draw, label_box, wrap_label(label), label_font, (30, 30, 30))

        for col_idx, value in enumerate(matrix[row_idx]):
            box = (
                left_margin + col_idx * cell_w,
                top_margin + row_idx * cell_h,
                left_margin + (col_idx + 1) * cell_w,
                top_margin + (row_idx + 1) * cell_h,
            )
            fill = color_for_value(value, max_value)
            text_fill = text_color_for_value(value, max_value)
            draw.rounded_rectangle(box, radius=10, fill=fill, outline=(215, 215, 215), width=1)
            draw_centered_text(draw, box, str(value), cell_font, text_fill)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    row_labels, column_labels, matrix = load_matrix(input_path)
    render_matrix(row_labels, column_labels, matrix, output_path, args.title)
    print(f"Saved confusion matrix image to {output_path}")


if __name__ == "__main__":
    main()
