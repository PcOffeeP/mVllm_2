"""虚拟数据集交付包只读校验脚本。

依据 `docs/virtual-dataset-handoff-contract.md` 校验 `data/virtual/<version>/` 下的
`manifest.json`、`labels.csv` 与 `videos/*.mp4`，输出 JSON 摘要。
全部通过返回退出码 0，任一校验失败返回退出码 1。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VIRTUAL_ROOT = ROOT / "data" / "virtual"

EXPECTED_SCHEMA = "tensile-virtual-dataset/1"
EXPECTED_SOURCE_DOMAIN = "virtual"

HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# 与 data/virtual/video-V1/labels.csv 及 data/annotation-table-full.csv 精确对齐的 28 列头。
REQUIRED_LABEL_COLUMNS: tuple[str, ...] = (
    "id",
    "video_path",
    "断裂时间点",
    "断裂模式",
    "材料类型",
    "清晰度",
    "断裂位置",
    "断裂帧数",
    "视频时长",
    "视频帧率",
    "视频总帧数",
    "has_fracture",
    "is_abnormal",
    "标注状态",
    "断裂帧_前",
    "断裂帧_后",
    "标注备注",
    "断裂状态",
    "异常_未夹紧",
    "异常_视频异常",
    "异常_爆炸性断裂",
    "现象_伸长",
    "现象_颈缩",
    "现象_开裂",
    "现象_界面分离",
    "断裂时间范围_下界",
    "断裂时间范围_上界",
    "现象_断后脱夹",
)


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_relpath_under(rel_path: str, prefix: str | None = None) -> tuple[bool, Path | None]:
    if not isinstance(rel_path, str) or not rel_path.strip():
        return False, None
    path = Path(rel_path)
    if path.is_absolute():
        return False, None
    parts = path.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return False, None
    if prefix is not None and (len(parts) < 2 or parts[0] != prefix):
        return False, None
    return True, path


def check_dataset(dataset_dir: Path) -> dict[str, Any]:
    """对单个虚拟数据集目录执行只读契约校验，返回结构化结果。"""
    dataset_dir = Path(dataset_dir)
    errors: list[str] = []
    checks = {
        "manifest": False,
        "upstream": False,
        "labels": False,
        "videos": False,
    }
    stats: dict[str, Any] = {
        "label_rows": None,
        "video_count": None,
        "total_video_bytes": None,
    }
    dataset_id: str | None = None

    if not dataset_dir.exists() or not dataset_dir.is_dir():
        errors.append(f"dataset_dir 不存在或不是目录: {dataset_dir}")
        return {
            "dataset_dir": str(dataset_dir),
            "dataset_id": dataset_id,
            "ok": False,
            "checks": checks,
            "stats": stats,
            "errors": errors,
        }

    # 1) manifest.json 基础检查
    manifest_path = dataset_dir / "manifest.json"
    manifest: dict[str, Any] | None = None
    manifest_errors: list[str] = []

    if manifest_path.is_symlink():
        manifest_errors.append("manifest.json 不允许为软链接")
    elif not manifest_path.exists() or not manifest_path.is_file():
        manifest_errors.append("缺少 manifest.json")
    else:
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            manifest_errors.append(f"manifest.json 不是合法 JSON: {exc}")
        else:
            if not isinstance(loaded, dict):
                manifest_errors.append("manifest.json 顶层必须为 JSON 对象")
            else:
                manifest = loaded
                raw_id = manifest.get("dataset_id")
                if isinstance(raw_id, str) and raw_id.strip():
                    dataset_id = raw_id
                if manifest.get("schema") != EXPECTED_SCHEMA:
                    manifest_errors.append(
                        f"manifest.schema 必须为 {EXPECTED_SCHEMA!r}，实际为 {manifest.get('schema')!r}"
                    )
                if manifest.get("source_domain") != EXPECTED_SOURCE_DOMAIN:
                    manifest_errors.append(
                        f"manifest.source_domain 必须为 {EXPECTED_SOURCE_DOMAIN!r}，"
                        f"实际为 {manifest.get('source_domain')!r}"
                    )

    checks["manifest"] = len(manifest_errors) == 0
    errors.extend(manifest_errors)

    if manifest is None:
        return {
            "dataset_dir": str(dataset_dir),
            "dataset_id": dataset_id,
            "ok": False,
            "checks": checks,
            "stats": stats,
            "errors": errors,
        }

    # 2) upstream 溯源与干净工作树检查
    upstream_errors: list[str] = []
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        upstream_errors.append("manifest.upstream 必须为对象")
    else:
        dirty = upstream.get("working_tree_dirty")
        if not (isinstance(dirty, bool) and dirty is False):
            upstream_errors.append(
                f"upstream.working_tree_dirty 必须严格为 false，实际为 {dirty!r}"
            )
        git_branch = upstream.get("git_branch")
        if not isinstance(git_branch, str) or not git_branch.strip():
            upstream_errors.append("upstream.git_branch 必须为非空字符串")
        git_head = upstream.get("git_head")
        if not isinstance(git_head, str) or not HEX40_RE.match(git_head):
            upstream_errors.append(
                f"upstream.git_head 必须为 40 位十六进制字符串，实际为 {git_head!r}"
            )
        upstream_manifest_sha = upstream.get("manifest_sha256")
        if not isinstance(upstream_manifest_sha, str) or not HEX64_RE.match(upstream_manifest_sha):
            upstream_errors.append(
                "upstream.manifest_sha256 必须为 64 位十六进制字符串，"
                f"实际为 {upstream_manifest_sha!r}"
            )

    checks["upstream"] = len(upstream_errors) == 0
    errors.extend(upstream_errors)

    # 3) labels.csv 检查
    labels_errors: list[str] = []
    labels_meta = manifest.get("labels")
    if not isinstance(labels_meta, dict):
        labels_errors.append("manifest.labels 必须为对象")
    else:
        labels_rel = labels_meta.get("path", "labels.csv")
        ok_rel, rel_path_obj = _is_safe_relpath_under(labels_rel)
        if not ok_rel or rel_path_obj is None:
            labels_errors.append(f"manifest.labels.path 非法: {labels_rel!r}")
        else:
            labels_file = dataset_dir / rel_path_obj
            if labels_file.is_symlink():
                labels_errors.append(f"{labels_rel} 不允许为软链接")
            elif not labels_file.exists() or not labels_file.is_file():
                labels_errors.append(f"缺少标注文件: {labels_rel}")
            else:
                expected_sha = labels_meta.get("sha256")
                actual_sha = _sha256_file(labels_file)
                if not isinstance(expected_sha, str) or not HEX64_RE.match(expected_sha):
                    labels_errors.append(
                        f"manifest.labels.sha256 必须为 64 位十六进制字符串，实际为 {expected_sha!r}"
                    )
                elif actual_sha.lower() != expected_sha.lower():
                    labels_errors.append(
                        f"{labels_rel} SHA-256 不匹配: expected={expected_sha}, actual={actual_sha}"
                    )

                try:
                    with labels_file.open("r", encoding="utf-8-sig", newline="") as fh:
                        reader = csv.reader(fh)
                        header = next(reader, None)
                        if header is None:
                            labels_errors.append(f"{labels_rel} 为空，缺少表头")
                        else:
                            missing_cols = [
                                col for col in REQUIRED_LABEL_COLUMNS if col not in header
                            ]
                            if missing_cols:
                                labels_errors.append(
                                    f"{labels_rel} 缺少必需列头 ({len(missing_cols)} 列): "
                                    + ", ".join(missing_cols)
                                )
                            row_count = sum(1 for _ in reader)
                            stats["label_rows"] = row_count
                            expected_rows = labels_meta.get("row_count")
                            if not _is_strict_int(expected_rows):
                                labels_errors.append(
                                    f"manifest.labels.row_count 必须为整数，实际为 {expected_rows!r}"
                                )
                            elif row_count != expected_rows:
                                labels_errors.append(
                                    f"{labels_rel} 行数不匹配: expected={expected_rows}, actual={row_count}"
                                )
                except (OSError, UnicodeDecodeError, csv.Error) as exc:
                    labels_errors.append(f"读取 {labels_rel} 失败: {exc}")

    checks["labels"] = len(labels_errors) == 0
    errors.extend(labels_errors)

    # 4) videos/ 与逐条视频检查
    videos_errors: list[str] = []
    videos_dir = dataset_dir / "videos"
    if videos_dir.is_symlink():
        videos_errors.append("videos/ 目录不允许为软链接")
    elif not videos_dir.exists() or not videos_dir.is_dir():
        videos_errors.append("缺少 videos/ 目录")

    videos_list = manifest.get("videos")
    expected_video_count = manifest.get("video_count")
    expected_total_bytes = manifest.get("total_video_bytes")

    if not isinstance(videos_list, list):
        videos_errors.append("manifest.videos 必须为数组")
    if not _is_strict_int(expected_video_count):
        videos_errors.append(
            f"manifest.video_count 必须为整数，实际为 {expected_video_count!r}"
        )
    if not _is_strict_int(expected_total_bytes):
        videos_errors.append(
            f"manifest.total_video_bytes 必须为整数，实际为 {expected_total_bytes!r}"
        )

    manifest_video_relpaths: set[str] = set()
    actual_total_bytes = 0

    if isinstance(videos_list, list):
        stats["video_count"] = len(videos_list)
        if _is_strict_int(expected_video_count) and expected_video_count != len(videos_list):
            videos_errors.append(
                f"manifest.video_count ({expected_video_count}) 与 len(videos) ({len(videos_list)}) 不一致"
            )

        for idx, item in enumerate(videos_list):
            if not isinstance(item, dict):
                videos_errors.append(f"manifest.videos[{idx}] 必须为对象")
                continue

            vpath_raw = item.get("video_path")
            ok_vpath, vpath_rel = _is_safe_relpath_under(vpath_raw, prefix="videos")
            if not ok_vpath or vpath_rel is None:
                videos_errors.append(
                    f"manifest.videos[{idx}].video_path 必须位于 videos/ 下且为合法相对路径: {vpath_raw!r}"
                )
                continue

            vpath_posix = vpath_rel.as_posix()
            if vpath_posix in manifest_video_relpaths:
                videos_errors.append(f"manifest.videos 存在重复路径: {vpath_posix}")
            manifest_video_relpaths.add(vpath_posix)

            full_vpath = dataset_dir / vpath_rel
            if full_vpath.is_symlink():
                videos_errors.append(f"视频文件不允许为软链接: {vpath_posix}")
                continue
            if not full_vpath.exists() or not full_vpath.is_file():
                videos_errors.append(f"缺少视频文件: {vpath_posix}")
                continue

            actual_bytes = full_vpath.stat().st_size
            actual_total_bytes += actual_bytes

            expected_bytes = item.get("bytes")
            if not _is_strict_int(expected_bytes):
                videos_errors.append(
                    f"manifest.videos[{idx}].bytes 必须为整数: {expected_bytes!r}"
                )
            elif actual_bytes != expected_bytes:
                videos_errors.append(
                    f"{vpath_posix} 字节数不匹配: expected={expected_bytes}, actual={actual_bytes}"
                )

            expected_vsha = item.get("sha256")
            if not isinstance(expected_vsha, str) or not HEX64_RE.match(expected_vsha):
                videos_errors.append(
                    f"manifest.videos[{idx}].sha256 必须为 64 位十六进制字符串: {expected_vsha!r}"
                )
            else:
                actual_vsha = _sha256_file(full_vpath)
                if actual_vsha.lower() != expected_vsha.lower():
                    videos_errors.append(
                        f"{vpath_posix} SHA-256 不匹配: expected={expected_vsha}, actual={actual_vsha}"
                    )

        stats["total_video_bytes"] = actual_total_bytes
        if _is_strict_int(expected_total_bytes) and actual_total_bytes != expected_total_bytes:
            videos_errors.append(
                f"total_video_bytes 不匹配: expected={expected_total_bytes}, actual={actual_total_bytes}"
            )

    if videos_dir.exists() and videos_dir.is_dir() and not videos_dir.is_symlink():
        extra_mp4s: list[str] = []
        for candidate in sorted(videos_dir.rglob("*")):
            if candidate.suffix.lower() != ".mp4":
                continue
            if not (candidate.is_file() or candidate.is_symlink()):
                continue
            rel_posix = candidate.relative_to(dataset_dir).as_posix()
            if rel_posix not in manifest_video_relpaths:
                extra_mp4s.append(rel_posix)
        if extra_mp4s:
            videos_errors.append(
                f"videos/ 中存在清单外多余 .mp4 文件 ({len(extra_mp4s)} 个): "
                + ", ".join(extra_mp4s)
            )

    checks["videos"] = len(videos_errors) == 0
    errors.extend(videos_errors)

    overall_ok = all(checks.values()) and len(errors) == 0
    return {
        "dataset_dir": str(dataset_dir),
        "dataset_id": dataset_id,
        "ok": overall_ok,
        "checks": checks,
        "stats": stats,
        "errors": errors,
    }


def discover_virtual_datasets(virtual_root: Path) -> list[Path]:
    """扫描 virtual_root 下所有非隐藏子目录，按名称排序返回。"""
    if not virtual_root.exists() or not virtual_root.is_dir():
        return []
    return sorted(
        p for p in virtual_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读校验虚拟数据集交付包（manifest.json / labels.csv / videos/*.mp4）。"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dataset-dir",
        type=Path,
        help="待校验的单个虚拟数据集目录（例如 data/virtual/video-V1）。",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="自动扫描 data/virtual/* 下全部虚拟数据集目录并校验。",
    )
    parser.add_argument(
        "--virtual-root",
        type=Path,
        default=DEFAULT_VIRTUAL_ROOT,
        help="配合 --all 使用的虚拟数据集根目录（默认: <repo>/data/virtual）。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.all:
        targets = discover_virtual_datasets(args.virtual_root)
        if not targets:
            summary = {
                "ok": False,
                "checked_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "datasets": [],
                "error": f"未在 {args.virtual_root} 下发现任何虚拟数据集目录",
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1
    else:
        targets = [args.dataset_dir]

    results = [check_dataset(target) for target in targets]
    passed_count = sum(1 for item in results if item["ok"])
    failed_count = len(results) - passed_count
    summary = {
        "ok": failed_count == 0,
        "checked_count": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "datasets": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
