#!/usr/bin/env python3
"""v2 数据版本冻结脚本。

收集代码 commit、配置哈希、处理器指纹、输入/划分/样本清单哈希、统计报告与
磁盘占用，输出 ``data/metadata_v2/data_version_lock.json``。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DATA_DIR = _PROJECT_ROOT / "data"
VIDEO_DIR = DATA_DIR / "01_videos"
SUBVIDEO_V2_DIR = DATA_DIR / "02_subvideos_v2"
SPLITS_V2_DIR = DATA_DIR / "03_splits_v2"
MERGED_V2_DIR = DATA_DIR / "04_merged_v2"
META_V2_DIR = DATA_DIR / "metadata_v2"

LOCK_PATH = META_V2_DIR / "data_version_lock.json"

CONFIG_FILES = [
    _PROJECT_ROOT / "finetune" / "dataset_info.json",
    _PROJECT_ROOT / "agent" / "config.yaml",
    _PROJECT_ROOT / "pyproject.toml",
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_sorted_file_list(paths: list[Path]) -> str:
    """按路径排序后拼接文件内容计算 SHA-256。"""
    sorted_paths = sorted(paths)
    hasher = hashlib.sha256()
    for p in sorted_paths:
        hasher.update(p.read_bytes())
    return hasher.hexdigest()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_input_video_sha256(video_meta_path: Path) -> dict[str, Any]:
    if not video_meta_path.exists():
        return {"count": 0, "sha256": None, "error": "video_meta.json not found"}
    data = _load_json(video_meta_path)
    if not isinstance(data, list):
        return {"count": 0, "sha256": None, "error": "video_meta.json not a list"}
    video_ids = sorted(
        {r["video_id"] for r in data if isinstance(r, dict) and isinstance(r.get("video_id"), str)}
    )
    payload = "\n".join(video_ids).encode("utf-8")
    return {
        "count": len(video_ids),
        "sha256": _sha256_bytes(payload),
        "source": str(video_meta_path),
    }


def _collect_split_manifest_sha256(splits_dir: Path) -> dict[str, Any]:
    if not splits_dir.exists():
        return {"count": 0, "sha256": None, "error": "splits directory not found"}
    paths = [p for p in splits_dir.glob("*.json")]
    names = sorted(p.name for p in paths)
    return {
        "count": len(paths),
        "files": names,
        "sha256": _sha256_sorted_file_list(paths) if paths else None,
        "source": str(splits_dir),
    }


def _collect_sample_manifest_sha256(merged_dir: Path) -> dict[str, Any]:
    if not merged_dir.exists():
        return {"count": 0, "sha256": None, "error": "merged directory not found"}
    paths = [p for p in merged_dir.glob("*.json") if p.name != "test_ground_truth.json"]
    names = sorted(p.name for p in paths)
    return {
        "count": len(paths),
        "files": names,
        "sha256": _sha256_sorted_file_list(paths) if paths else None,
        "source": str(merged_dir),
    }


def _collect_processor_fingerprints(merged_dir: Path, subvideos_meta_path: Path) -> dict[str, Any]:
    fingerprints: list[str] = []

    if merged_dir.exists():
        for path in sorted(merged_dir.glob("*.json")):
            if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
                continue
            data = _load_json(path)
            if not isinstance(data, list):
                continue
            for sample in data:
                if isinstance(sample, dict) and isinstance(sample.get("processor_fingerprint"), str):
                    fingerprints.append(sample["processor_fingerprint"])

    if subvideos_meta_path.exists():
        raw = _load_json(subvideos_meta_path)
        if isinstance(raw, dict):
            for sub in raw.get("subvideos", []):
                if isinstance(sub, dict) and isinstance(sub.get("processor_fingerprint"), str):
                    fingerprints.append(sub["processor_fingerprint"])

    counter = Counter(fingerprints)
    return {
        "fingerprints": dict(counter),
        "dominant": counter.most_common(1)[0][0] if counter else None,
        "count": len(fingerprints),
    }


def _collect_config_hashes(
    config_files: list[Path], project_root: Path = _PROJECT_ROOT
) -> dict[str, Any]:
    hashes: dict[str, str] = {}
    for path in config_files:
        if path.exists():
            try:
                key = str(path.relative_to(project_root))
            except ValueError:
                key = str(path)
            hashes[key] = _sha256_file(path)
        else:
            try:
                key = str(path.relative_to(project_root))
            except ValueError:
                key = str(path)
            hashes[key] = None
    return {
        "files": hashes,
        "combined_sha256": _sha256_sorted_file_list([p for p in config_files if p.exists()]),
    }


def _collect_git_commit(project_root: Path = _PROJECT_ROOT) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
        return {"commit": commit, "dirty": _is_git_dirty(project_root)}
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {"commit": None, "error": str(exc)}


def _is_git_dirty(project_root: Path = _PROJECT_ROOT) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _collect_statistics(merged_dir: Path) -> dict[str, Any]:
    path = merged_dir / "samples_meta.json"
    if not path.exists():
        return {"error": "samples_meta.json not found"}
    data = _load_json(path)
    if not isinstance(data, dict):
        return {"error": "samples_meta.json not an object"}
    return {
        "source": str(path),
        "summary": {
            "total_samples": data.get("total_samples"),
            "total_video_sources": data.get("total_video_sources"),
            "total_positive": data.get("total_positive"),
            "total_negative": data.get("total_negative"),
        },
        "full_report": data,
    }


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(Path(root) / name)
    return total


def run_freeze(
    merged_dir: Path = MERGED_V2_DIR,
    subvideos_meta_path: Path = META_V2_DIR / "subvideos_meta.json",
    video_meta_path: Path = META_V2_DIR / "video_meta.json",
    splits_dir: Path = SPLITS_V2_DIR,
    subvideo_dir: Path = SUBVIDEO_V2_DIR,
    lock_path: Path = LOCK_PATH,
    config_files: list[Path] | None = None,
    project_root: Path = _PROJECT_ROOT,
) -> dict[str, Any]:
    """执行版本冻结并返回锁文件内容。"""
    if config_files is None:
        config_files = CONFIG_FILES

    lock = {
        "version": "2.0.0",
        "code": _collect_git_commit(project_root),
        "config": _collect_config_hashes(config_files, project_root),
        "processor": _collect_processor_fingerprints(merged_dir, subvideos_meta_path),
        "input_video_manifest": _collect_input_video_sha256(video_meta_path),
        "split_manifest": _collect_split_manifest_sha256(splits_dir),
        "sample_manifest": _collect_sample_manifest_sha256(merged_dir),
        "statistics": _collect_statistics(merged_dir),
        "disk_usage_bytes": {
            "02_subvideos_v2": _dir_size_bytes(subvideo_dir),
            "04_merged_v2": _dir_size_bytes(merged_dir),
        },
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v2 数据版本冻结")
    parser.add_argument(
        "--merged-dir",
        type=Path,
        default=MERGED_V2_DIR,
        help="v2 产物目录（默认：data/04_merged_v2）",
    )
    parser.add_argument(
        "--subvideos-meta",
        type=Path,
        default=META_V2_DIR / "subvideos_meta.json",
        help="v2 子视频元数据路径",
    )
    parser.add_argument(
        "--video-meta",
        type=Path,
        default=META_V2_DIR / "video_meta.json",
        help="v2 视频元数据路径",
    )
    parser.add_argument(
        "--splits-dir",
        type=Path,
        default=SPLITS_V2_DIR,
        help="v2 划分目录",
    )
    parser.add_argument(
        "--subvideo-dir",
        type=Path,
        default=SUBVIDEO_V2_DIR,
        help="v2 子视频媒体目录",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=LOCK_PATH,
        help="版本锁输出路径",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_PROJECT_ROOT,
        help="项目根目录，用于解析配置路径与 git",
    )
    args = parser.parse_args(argv)

    lock = run_freeze(
        merged_dir=args.merged_dir,
        subvideos_meta_path=args.subvideos_meta,
        video_meta_path=args.video_meta,
        splits_dir=args.splits_dir,
        subvideo_dir=args.subvideo_dir,
        lock_path=args.lock,
        project_root=args.project_root,
    )

    print(f"Version lock written to: {args.lock}")
    print(f"  commit: {lock['code']['commit']}")
    print(f"  input videos: {lock['input_video_manifest']['count']}")
    print(f"  split files: {lock['split_manifest']['count']}")
    print(f"  sample files: {lock['sample_manifest']['count']}")
    print(f"  dominant processor fingerprint: {lock['processor']['dominant']}")
    print(f"  disk usage (bytes): {lock['disk_usage_bytes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
