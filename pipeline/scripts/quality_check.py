#!/usr/bin/env python3
"""数据产物质量校验脚本。

读取 ``data/06_merged/`` 下的训练/验证/测试产物，执行强制检查并输出
``data/07_metadata/quality_check_report.json``。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DATA_DIR = _PROJECT_ROOT / "data"
VIDEO_DIR = DATA_DIR / "01_videos"
SUBVIDEO_DIR = DATA_DIR / "03_subvideos"
META_V2_DIR = DATA_DIR / "07_metadata"
SPLITS_V2_DIR = DATA_DIR / "05_splits"
MERGED_V2_DIR = DATA_DIR / "06_merged"

REPORT_PATH = META_V2_DIR / "quality_check_report.json"

FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
}
NON_FRACTURE_TYPES = {"未断裂", "未夹紧", "视频异常"}
ALL_TYPES = FRACTURE_TYPES | NON_FRACTURE_TYPES

LEGAL_COMBINATIONS = [
    # 1. 正常断裂且可定位
    {
        "has_fracture": True,
        "fracture_between": "adjacent_pair",
        "type": FRACTURE_TYPES,
        "location": {"inside_gauge", "outside_gauge"},
    },
    # 2. 确认未断裂
    {
        "has_fracture": False,
        "fracture_between": {None},
        "type": {"未断裂"},
        "location": {None},
    },
    # 3. 未夹紧
    {
        "has_fracture": False,
        "fracture_between": {None},
        "type": {"未夹紧"},
        "location": {None},
    },
    # 3b. 未夹紧但有事件标注（正样本）
    {
        "has_fracture": True,
        "fracture_between": "adjacent_pair",
        "type": {"未夹紧"},
        "location": {None},
    },
    # 4. 视频异常，无法确定是否断裂
    {
        "has_fracture": None,
        "fracture_between": {None},
        "type": {"视频异常"},
        "location": {None},
    },
    # 5. 视频异常，确认断裂但时间不可靠
    {
        "has_fracture": True,
        "fracture_between": {None},
        "type": {"视频异常"},
        "location": {None},
    },
]


def is_positive_label(obj: dict[str, Any]) -> bool:
    """统一正样本判断：以 has_fracture/has_fracture_canonical 为准。"""
    return obj.get("has_fracture_canonical", obj.get("has_fracture")) is True


TRUTH_FIELDS = {
    "event_frame",
    "event_time",
    "type",
    "location",
    "has_fracture_canonical",
    "fracture_between",
}


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_assistant_output(sample: dict[str, Any]) -> dict[str, Any] | None:
    messages = sample.get("messages", [])
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content")
            if not isinstance(content, str):
                return None
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None
    return None


def _is_adjacent_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and value[1] == value[0] + 1


def _is_mock_fingerprint(fp: Any) -> bool:
    if not isinstance(fp, str):
        return False
    return "mock" in fp.lower() or "theoretical" in fp.lower()


def _resolve_media_path(rel: str, project_root: Path) -> Path:
    if rel.startswith("data/"):
        return project_root / rel
    return project_root / "data" / rel


def _matches_legal_combination(output: dict[str, Any]) -> bool:
    hf = output.get("has_fracture")
    fb = output.get("fracture_between")
    ftype = output.get("type")
    loc = output.get("location")
    conf = output.get("confidence")

    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        return False

    for combo in LEGAL_COMBINATIONS:
        if hf != combo["has_fracture"]:
            continue
        expected_fb = combo["fracture_between"]
        if expected_fb == "adjacent_pair":
            if not _is_adjacent_pair(fb):
                continue
        elif expected_fb == {None}:
            if fb is not None:
                continue
        else:
            if fb != expected_fb:
                continue
        if ftype not in combo["type"]:
            continue
        if loc not in combo["location"]:
            continue
        return True
    return False


def _validate_media_paths(
    merged_dir: Path,
    test_inputs: list[dict[str, Any]] | None,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    project_root: Path,
) -> None:
    checked: set[str] = set()
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            rel = sample.get("videos", [None])[0]
            if not isinstance(rel, str):
                errors.append(
                    {
                        "check": "media_path",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "missing_video_path",
                    }
                )
                continue
            if rel in checked:
                continue
            checked.add(rel)
            full = _resolve_media_path(rel, project_root)
            if not full.exists():
                errors.append(
                    {
                        "check": "media_path",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "missing_file",
                        "path": rel,
                        "resolved": str(full),
                    }
                )

    for item in test_inputs or []:
        if not isinstance(item, dict):
            continue
        rel = item.get("video_path")
        if not isinstance(rel, str):
            errors.append(
                {
                    "check": "media_path",
                    "file": "test_inputs.json",
                    "id": item.get("id"),
                    "detail": "missing_video_path",
                }
            )
            continue
        if rel in checked:
            continue
        checked.add(rel)
        full = _resolve_media_path(rel, project_root)
        if not full.exists():
            errors.append(
                {
                    "check": "media_path",
                    "file": "test_inputs.json",
                    "id": item.get("id"),
                    "detail": "missing_file",
                    "path": rel,
                    "resolved": str(full),
                }
            )


def _validate_field_combinations(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            output = _extract_assistant_output(sample)
            if output is None:
                errors.append(
                    {
                        "check": "field_combination",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "assistant_content_not_valid_json",
                    }
                )
                continue
            if not _matches_legal_combination(output):
                errors.append(
                    {
                        "check": "field_combination",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "illegal_five_field_combination",
                        "output": output,
                    }
                )

            ftype = output.get("type")
            if ftype not in ALL_TYPES:
                errors.append(
                    {
                        "check": "type_closed_set",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "invalid_type",
                        "type": ftype,
                    }
                )


def _validate_fracture_between(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            output = _extract_assistant_output(sample)
            if output is None:
                continue
            fb = output.get("fracture_between")
            if fb is None:
                continue
            mapping = sample.get("actual_frame_mapping") or []
            n = len(mapping)
            if n == 0:
                continue  # ShareGPT 格式不含 actual_frame_mapping，边界校验跳过
            if not isinstance(fb, list) or len(fb) != 2:
                errors.append(
                    {
                        "check": "fracture_between",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "malformed",
                        "value": fb,
                    }
                )
                continue
            i, j = fb
            if not (isinstance(i, int) and isinstance(j, int)):
                errors.append(
                    {
                        "check": "fracture_between",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "non_integer",
                        "value": fb,
                    }
                )
                continue
            if not (0 <= i < j < n):
                errors.append(
                    {
                        "check": "fracture_between",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "out_of_bounds_or_not_adjacent",
                        "value": fb,
                        "frame_count": n,
                    }
                )
                continue
            if j != i + 1:
                errors.append(
                    {
                        "check": "fracture_between",
                        "file": path.name,
                        "id": sample.get("id"),
                        "detail": "not_strictly_adjacent",
                        "value": fb,
                    }
                )


def _validate_processor_fingerprints(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    fingerprints: set[str] = set()
    mock_fingerprints: set[str] = set()
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            fp = sample.get("processor_fingerprint")
            if fp is None:
                continue  # ShareGPT 格式不含 processor_fingerprint，跳过
            if _is_mock_fingerprint(fp):
                mock_fingerprints.add(fp)
            else:
                fingerprints.add(fp)

    if mock_fingerprints:
        errors.append(
            {
                "check": "processor_fingerprint",
                "detail": "mock_or_theoretical_fingerprints_forbidden",
                "fingerprints": sorted(mock_fingerprints),
            }
        )
    if fingerprints:
        if len(fingerprints) > 1:
            errors.append(
                {
                    "check": "processor_fingerprint",
                    "detail": "inconsistent_non_mock_fingerprints",
                    "fingerprints": sorted(fingerprints),
                }
            )


def _is_positive_sample(sample: dict[str, Any]) -> bool:
    output = _extract_assistant_output(sample)
    if output is None:
        return False
    return is_positive_label(output)


def _validate_train_ratios(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    train_samples: list[dict[str, Any]] = []
    missing_or_bad: list[str] = []
    for i in range(3):
        path = merged_dir / f"fold_{i}_train.json"
        data = _load_json(path)
        if not isinstance(data, list):
            missing_or_bad.append(path.name)
            continue
        train_samples.extend(data)

    if missing_or_bad:
        errors.append(
            {
                "check": "train_ratio",
                "file": ",".join(missing_or_bad),
                "detail": "missing_or_not_a_list",
            }
        )
        return

    pos = sum(1 for s in train_samples if _is_positive_sample(s))
    neg = len(train_samples) - pos
    if pos == 0 or neg == 0:
        errors.append(
            {
                "check": "train_ratio",
                "file": "all_train_splits",
                "detail": "missing_positive_or_negative_samples",
                "positive": pos,
                "negative": neg,
            }
        )
        return

    ratio = pos / neg
    if not (0.5 <= ratio <= 2.0):
        errors.append(
            {
                "check": "train_ratio",
                "file": "all_train_splits",
                "detail": "global_ratio_out_of_range",
                "positive": pos,
                "negative": neg,
                "ratio": round(ratio, 4),
                "allowed": "0.5:1 ~ 2:1",
            }
        )


def _validate_no_cross_split_leakage(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    split_sources: dict[str, set[str]] = defaultdict(set)
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        split = path.stem
        for sample in data:
            if not isinstance(sample, dict):
                continue
            src = sample.get("source_video")
            if not isinstance(src, str):
                continue  # ShareGPT 格式不含 source_video，跳过
            if isinstance(src, str):
                split_sources[split].add(src)

    test_inputs = _load_json(merged_dir / "test_inputs.json")
    if isinstance(test_inputs, list):
        for item in test_inputs:
            if isinstance(item, dict):
                src = item.get("video_id")
                if isinstance(src, str):
                    split_sources["test"].add(src)

    sets_to_check = [
        ("fold_0_train", "fold_0_val"),
        ("fold_1_train", "fold_1_val"),
        ("fold_2_train", "fold_2_val"),
        ("fold_0_train", "test"),
        ("fold_0_val", "test"),
        ("fold_1_train", "test"),
        ("fold_1_val", "test"),
        ("fold_2_train", "test"),
        ("fold_2_val", "test"),
    ]
    for a, b in sets_to_check:
        inter = split_sources[a] & split_sources[b]
        if inter:
            errors.append(
                {
                    "check": "cross_split_leakage",
                    "detail": f"video_source_overlap_between_{a}_and_{b}",
                    "overlap": sorted(inter)[:20],
                    "count": len(inter),
                }
            )


def _validate_test_input_isolation(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    path = merged_dir / "test_inputs.json"
    data = _load_json(path)
    if data is None:
        errors.append(
            {
                "check": "test_input_isolation",
                "file": path.name,
                "detail": "missing",
            }
        )
        return
    if not isinstance(data, list):
        errors.append(
            {
                "check": "test_input_isolation",
                "file": path.name,
                "detail": "not_a_list",
            }
        )
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        leaked = TRUTH_FIELDS & set(item.keys())
        if leaked:
            errors.append(
                {
                    "check": "test_input_isolation",
                    "file": path.name,
                    "id": item.get("id"),
                    "detail": "contains_truth_fields",
                    "fields": sorted(leaked),
                }
            )


def _validate_exclusions(subvideos_meta_path: Path, errors: list[dict[str, Any]]) -> None:
    if not subvideos_meta_path.exists():
        return
    data = _load_json(subvideos_meta_path)
    if not isinstance(data, dict):
        return
    exclusions = data.get("exclusions", [])
    for idx, exc in enumerate(exclusions):
        if not isinstance(exc, dict):
            errors.append(
                {
                    "check": "exclusion_reason",
                    "detail": "exclusion_not_an_object",
                    "index": idx,
                }
            )
            continue
        if "reason" not in exc or not isinstance(exc.get("reason"), str) or not exc["reason"]:
            errors.append(
                {
                    "check": "exclusion_reason",
                    "detail": "missing_or_empty_reason",
                    "index": idx,
                    "exclusion": exc,
                }
            )


def run_quality_check(
    merged_dir: Path = MERGED_V2_DIR,
    subvideos_meta_path: Path = META_V2_DIR / "subvideos_meta.json",
    report_path: Path = REPORT_PATH,
    project_root: Path = _PROJECT_ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """执行全部强制检查，返回 (errors, warnings, summary)。"""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not merged_dir.exists():
        errors.append(
            {
                "check": "existence",
                "detail": "merged_directory_missing",
                "path": str(merged_dir),
            }
        )
    else:
        test_inputs = _load_json(merged_dir / "test_inputs.json")
        _validate_media_paths(merged_dir, test_inputs, errors, warnings, project_root)
        _validate_field_combinations(merged_dir, errors, warnings)
        _validate_fracture_between(merged_dir, errors, warnings)
        _validate_processor_fingerprints(merged_dir, errors, warnings)
        _validate_train_ratios(merged_dir, errors, warnings)
        _validate_no_cross_split_leakage(merged_dir, errors, warnings)
        _validate_test_input_isolation(merged_dir, errors, warnings)

    _validate_exclusions(subvideos_meta_path, errors)

    summary = {
        "merged_dir": str(merged_dir),
        "subvideos_meta": str(subvideos_meta_path),
        "error_count": len(errors),
        "warning_count": len(warnings),
    }
    report = {
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return errors, warnings, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据产物质量校验")
    parser.add_argument(
        "--merged-dir",
        type=Path,
        default=MERGED_V2_DIR,
        help="产物目录（默认：data/06_merged）",
    )
    parser.add_argument(
        "--subvideos-meta",
        type=Path,
        default=META_V2_DIR / "subvideos_meta.json",
        help="子视频元数据路径（默认：data/07_metadata/subvideos_meta.json）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_PATH,
        help="校验报告输出路径",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_PROJECT_ROOT,
        help="项目根目录，用于解析媒体路径",
    )
    args = parser.parse_args(argv)

    errors, warnings, summary = run_quality_check(
        merged_dir=args.merged_dir,
        subvideos_meta_path=args.subvideos_meta,
        report_path=args.report,
        project_root=args.project_root,
    )

    print(f"Scanned: {summary['merged_dir']}")
    print(f"Errors: {summary['error_count']}, Warnings: {summary['warning_count']}")
    for e in errors[:40]:
        print("  ERROR:", e)
    for w in warnings[:20]:
        print("  WARN :", w)

    if errors:
        print("FAILED: quality check found errors.")
        return 1
    print("OK: all quality checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
