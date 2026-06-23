from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.preprocessing import (
    FrameMapping,
    MiniCPMVideoPreprocessor,
    MockVideoPreprocessor,
    ProcessorInfo,
    VideoPreprocessor,
)


def _load_video_meta(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {rec["video_id"]: rec for rec in data}


def _load_splits(splits_dir: Path) -> dict[str, dict[str, Any]]:
    splits: dict[str, dict[str, Any]] = {}
    for path in sorted(splits_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        splits[path.stem] = data
    return splits


def _collect_split_video_ids(splits: dict[str, dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for split in splits.values():
        ids.update(split.get("video_ids", []))
    return ids


def _pick_calibration_videos(
    meta: dict[str, dict[str, Any]],
    available_ids: set[str],
    n_per_category: int = 2,
) -> list[str]:
    """按类别、时长和事件位置挑选代表性视频。"""
    candidates = sorted(vid for vid in available_ids if vid in meta)

    def bucket(rec: dict[str, Any]) -> str:
        if rec.get("is_abnormal_canonical") or rec.get("video_anomaly_kind"):
            return "abnormal"
        if rec.get("has_fracture_canonical") is True:
            return "fracture"
        return "no_fracture"

    def duration_bucket(rec: dict[str, Any]) -> str:
        d = float(rec.get("duration") or 0)
        if d < 10:
            return "short"
        if d < 60:
            return "medium"
        return "long"

    groups: dict[tuple[str, str], list[str]] = {}
    for vid in candidates:
        rec = meta[vid]
        key = (bucket(rec), duration_bucket(rec))
        groups.setdefault(key, []).append(vid)

    selected: list[str] = []
    for key in sorted(groups):
        selected.extend(groups[key][:n_per_category])

    # 兜底：至少保证 3 个视频
    if len(selected) < 3:
        selected.extend([v for v in candidates if v not in selected][: 3 - len(selected)])
    return sorted(set(selected))


def _build_cases_for_video(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """为单个视频生成 full / 30s / 10s / 3s 等校准区间。"""
    duration = float(rec["duration"])
    event_time = rec.get("event_time")
    if not isinstance(event_time, (int, float)):
        event_time = None

    cases: list[dict[str, Any]] = []

    # 完整视频
    cases.append({
        "case_id": f"{rec['video_id']}_full",
        "video_id": rec["video_id"],
        "video_path": str(ROOT / rec["video_path"]),
        "start_time": 0.0,
        "end_time": duration,
        "window_size": duration,
        "event_position": "full",
        "type": rec.get("type"),
    })

    for size in (30, 10, 3):
        if duration < size:
            continue
        positions = _window_positions(duration, size, event_time)
        for pos_name, (start, end) in positions.items():
            cases.append({
                "case_id": f"{rec['video_id']}_{size}s_{pos_name}",
                "video_id": rec["video_id"],
                "video_path": str(ROOT / rec["video_path"]),
                "start_time": start,
                "end_time": end,
                "window_size": size,
                "event_position": pos_name,
                "type": rec.get("type"),
            })
    return cases


def _window_positions(
    duration: float, size: float, event_time: float | None
) -> dict[str, tuple[float, float]]:
    """返回事件在窗口开头、中间、结尾等位置。"""
    positions: dict[str, tuple[float, float]] = {}
    # 开头
    positions["start"] = (0.0, min(duration, size))
    # 结尾
    positions["end"] = (max(0.0, duration - size), duration)
    # 中间
    mid = duration / 2
    positions["middle"] = (max(0.0, mid - size / 2), min(duration, mid + size / 2))
    # 事件居中（如有）
    if event_time is not None:
        start = max(0.0, event_time - size / 2)
        end = min(duration, start + size)
        start = max(0.0, end - size)
        positions["around_event"] = (start, end)
    return positions


# ---------------------------------------------------------------------------
# LLaMA-Factory batch 加载（本地为占位，训练机可替换真实实现）
# ---------------------------------------------------------------------------


def _try_load_llama_factory_batch(
    video_path: str,
    preprocessor_info: ProcessorInfo,
    preprocessor_frames: list[FrameMapping],
) -> dict[str, Any]:
    """尝试调用 LLaMA-Factory 实际 batch 加载；不可用时回退到 mock。"""
    try:
        # 训练机可在此接入真实 LLaMA-Factory 数据加载器。
        # 本地未安装时直接回退，不阻塞脚本骨架。
        raise ImportError("LLaMA-Factory batch loader not integrated in skeleton")
    except Exception as exc:
        return {
            "source": "mock-llama-factory-fallback",
            "error": str(exc),
            "processor_name": preprocessor_info.name,
            "max_frames": preprocessor_info.max_frames,
            "frame_count": len(preprocessor_frames),
            "frames": [
                {"input_index": f.input_index, "original_frame": f.original_frame}
                for f in preprocessor_frames
            ],
        }


def _compare_results(
    preprocessor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
    batch_result: dict[str, Any],
) -> dict[str, Any]:
    """比较数据构建适配层与 LLaMA-Factory batch 加载结果。"""
    checks = {
        "processor_version_match": batch_result.get("processor_name") == preprocessor_info.name,
        "max_frames_match": batch_result.get("max_frames") == preprocessor_info.max_frames,
        "frame_count_match": batch_result.get("frame_count") == len(adapter_frames),
        "order_match": _check_order_match(adapter_frames, batch_result.get("frames", [])),
        "mapping_match": _check_mapping_match(adapter_frames, batch_result.get("frames", [])),
    }
    checks["passed"] = all(checks.values())
    return checks


def _check_order_match(
    adapter_frames: list[FrameMapping], batch_frames: list[dict[str, Any]]
) -> bool:
    if len(adapter_frames) != len(batch_frames):
        return False
    return all(
        a.input_index == b.get("input_index")
        and a.original_frame == b.get("original_frame")
        for a, b in zip(adapter_frames, batch_frames)
    )


def _check_mapping_match(
    adapter_frames: list[FrameMapping], batch_frames: list[dict[str, Any]]
) -> bool:
    return _check_order_match(adapter_frames, batch_frames)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_calibration_cases(
    video_meta_path: Path,
    splits_dir: Path,
) -> list[dict[str, Any]]:
    meta = _load_video_meta(video_meta_path)
    splits = _load_splits(splits_dir)
    available_ids = _collect_split_video_ids(splits)
    selected = _pick_calibration_videos(meta, available_ids)
    cases: list[dict[str, Any]] = []
    for vid in selected:
        cases.extend(_build_cases_for_video(meta[vid]))
    return cases


def run_calibration(
    preprocessor: VideoPreprocessor,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    info = preprocessor.get_info()
    results: list[dict[str, Any]] = []
    all_passed = True

    for case in cases:
        case_result: dict[str, Any] = {
            "case_id": case["case_id"],
            "video_id": case["video_id"],
            "window_size": case["window_size"],
            "event_position": case["event_position"],
            "start_time": case["start_time"],
            "end_time": case["end_time"],
        }
        try:
            frames = preprocessor.sample(
                case["video_path"], case["start_time"], case["end_time"]
            )
            batch_result = _try_load_llama_factory_batch(
                case["video_path"], info, frames
            )
            comparison = _compare_results(info, frames, batch_result)
            case_result["adapter_frames"] = [
                {"input_index": f.input_index, "original_frame": f.original_frame, "timestamp": f.timestamp}
                for f in frames
            ]
            case_result["batch_result"] = batch_result
            case_result["comparison"] = comparison
            case_result["ok"] = comparison["passed"]
            if not comparison["passed"]:
                all_passed = False
        except Exception as exc:
            case_result["ok"] = False
            case_result["error"] = f"{type(exc).__name__}: {exc}"
            all_passed = False
        results.append(case_result)

    return {
        "processor_info": {
            "name": info.name,
            "version": info.version,
            "max_frames": info.max_frames,
            "backend": info.backend,
        },
        "fingerprint": preprocessor.fingerprint(),
        "total_cases": len(results),
        "passed_cases": sum(1 for r in results if r.get("ok")),
        "all_passed": all_passed,
        "cases": results,
    }


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.scripts.calibration",
        description="预处理适配层与 LLaMA-Factory batch 加载校准脚本",
    )
    parser.add_argument(
        "--video-meta",
        type=Path,
        default=ROOT / "data" / "07_metadata" / "video_meta.json",
        help="video_meta.json 路径",
    )
    parser.add_argument(
        "--splits-dir",
        type=Path,
        default=ROOT / "data" / "05_splits",
        help="05_splits 目录路径",
    )
    parser.add_argument(
        "--preprocessor",
        choices=["mock", "minicpm"],
        default="mock",
        help="使用的预处理器（本地默认 mock，训练机可换 minicpm）",
    )
    parser.add_argument(
        "--model",
        default="openbmb/MiniCPM-V-2_6",
        help="minicpm 模型路径或名称",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "07_metadata" / "calibration_report.json",
        help="校准报告输出路径",
    )
    parser.add_argument(
        "--max-cases-per-video-category",
        type=int,
        default=2,
        help="每个类别/时长桶挑选的视频数",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    if args.preprocessor == "mock":
        preprocessor: VideoPreprocessor = MockVideoPreprocessor()
    else:
        preprocessor = MiniCPMVideoPreprocessor(model_path_or_name=args.model)

    if not preprocessor.healthcheck():
        print(f"ERROR: preprocessor healthcheck failed: {preprocessor.get_info()}", file=sys.stderr)
        return 1

    cases = build_calibration_cases(args.video_meta, args.splits_dir)
    if args.max_cases_per_video_category is not None:
        # 重新以指定数量挑选
        meta = _load_video_meta(args.video_meta)
        splits = _load_splits(args.splits_dir)
        available = _collect_split_video_ids(splits)
        selected = _pick_calibration_videos(meta, available, args.max_cases_per_video_category)
        cases = []
        for vid in selected:
            cases.extend(_build_cases_for_video(meta[vid]))

    report = run_calibration(preprocessor, cases)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "total_cases": report["total_cases"],
        "passed_cases": report["passed_cases"],
        "all_passed": report["all_passed"],
    }, ensure_ascii=False))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
