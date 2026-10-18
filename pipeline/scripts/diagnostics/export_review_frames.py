# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：`data/03_subvideos`
# 未随迁（原 finetune/results/diagnostics/ 下的输入/输出数据与依赖，留 bcdf4f36 + bundle）：
#   - finetune/results/diagnostics/visual_audit/sample_manifest.json
#   - finetune/results/diagnostics/visual_audit/frames
# 迁移已知影响：`Path(__file__).resolve().parents[4]` 原解析到仓库根，迁入 `pipeline/scripts/diagnostics/` 后层级少一层，已不指向仓库根。

#!/usr/bin/env python3
"""Export the exact uniformly sampled frames used by the validation runtime.

This script is intentionally model-free.  It consumes the 32-row
``sample_manifest.json`` produced by ``prepare_visual_audit.py`` and writes the
same frames selected by ``finetune.validation.video_loader.load_video_frames``.
It therefore makes the manual review reproducible without another GPU pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.validation.model_runtime import _write_sampled_frames
from finetune.validation.video_loader import load_video_frames


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export visual-audit review frames.")
    parser.add_argument(
        "--sample-manifest",
        type=Path,
        default=Path("finetune/results/diagnostics/visual_audit/sample_manifest.json"),
    )
    parser.add_argument(
        "--video-root",
        type=Path,
        default=Path("data/03_subvideos"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("finetune/results/diagnostics/visual_audit/frames"),
    )
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing frames directory created by this script.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = args.sample_manifest.resolve()
    video_root = args.video_root.resolve()
    output_dir = args.output_dir.resolve()

    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError(f"{manifest_path} must contain a non-empty list")

    if output_dir.exists():
        if not args.overwrite:
            raise FileExistsError(f"{output_dir} already exists; pass --overwrite to replace it")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    exported: list[dict[str, object]] = []
    for index, record in enumerate(records, start=1):
        sample_id = str(record["sample_id"])
        filename = str(record["subvideo_filename"])
        video_path = video_root / filename
        if not video_path.is_file():
            raise FileNotFoundError(video_path)

        frames, _temporal_ids, timestamps = load_video_frames(
            str(video_path),
            max_frames=args.max_frames,
        )
        sample_dir = output_dir / sample_id
        frame_paths = _write_sampled_frames(frames, timestamps, sample_dir)
        exported.append(
            {
                "review_order": index,
                "sample_id": sample_id,
                "subvideo_filename": filename,
                "video_sha256": sha256_file(video_path),
                "sampled_timestamps": [round(float(value), 6) for value in timestamps],
                "frame_paths": [
                    str(Path(path).relative_to(output_dir.parent)) for path in frame_paths
                ],
                "contact_sheet": str(
                    (sample_dir / "contact_sheet.png").relative_to(output_dir.parent)
                ),
            }
        )
        print(f"[{index:02d}/{len(records)}] {sample_id}: {len(frames)} frames")

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_manifest": str(manifest_path),
        "sample_manifest_sha256": sha256_file(manifest_path),
        "video_root": str(video_root),
        "max_frames": args.max_frames,
        "sampling_implementation": "finetune.validation.video_loader.load_video_frames",
        "sample_count": len(exported),
        "samples": exported,
    }
    audit_path = output_dir.parent / "review_frames_manifest.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {audit_path}")


if __name__ == "__main__":
    main()
