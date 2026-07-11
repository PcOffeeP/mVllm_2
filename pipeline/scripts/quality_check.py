#!/usr/bin/env python3
"""数据产物质量校验脚本。

读取 ``data/06_merged/`` 下的训练/验证/测试产物，执行强制检查并输出
``data/07_metadata/quality_check_report.json``。

当前检查项：
- 媒体路径存在性
- assistant target 格式（判断依据 + 结果区 JSON，不含 confidence）
- 结果区字段与 ``pipeline/prompt_library.yaml`` 的 ``target_schema`` 一致
- ``prompt_version`` 一致性
- 训练/验证样本对应子视频 ``review_status`` 为 approved
- 字段组合与 frame 边界
- 正负样本比例
- 划分泄漏
- 测试输入隔离
- processor fingerprint 一致性
- 排除项原因完整性
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

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
PROMPT_LIBRARY_DEFAULT = _PROJECT_ROOT / "pipeline" / "prompt_library.yaml"

FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂",
}
NON_FRACTURE_TYPES = {"未断裂", "未夹紧", "视频异常"}
ALL_TYPES = FRACTURE_TYPES | NON_FRACTURE_TYPES
STATUS_DROPPED = "dropped"

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
    # 7. 断裂类型视频的聚焦正样本（可定位但位置信息缺失）
    {
        "has_fracture": True,
        "fracture_between": "adjacent_pair",
        "type": FRACTURE_TYPES,
        "location": {None},
    },
]

TARGET_SCHEMA_KEYS = {"has_fracture", "fracture_between", "type", "location"}


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


def _load_prompt_library(path: Path) -> dict[str, Any]:
    """读取 prompt 模板库，失败时返回空字典。"""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError, OSError):
        return {}


def _sample_id(sample: dict[str, Any]) -> str | None:
    """统一获取样本 id：优先顶层 ``id``，否则回退到 ``metadata.subvideo_id``。

    训练样本导出后通常不再保留顶层 ``id``，因此实际多从 metadata 读取。
    """
    return sample.get("id") or sample.get("metadata", {}).get("subvideo_id")


def _extract_assistant_text(sample: dict[str, Any]) -> str | None:
    """提取 assistant 消息的原始文本内容。"""
    messages = sample.get("messages", [])
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, str):
                return content
    return None


def _extract_assistant_output(sample: dict[str, Any]) -> dict[str, Any] | None:
    """从 assistant 消息中提取结果区 JSON 字典。

    兼容旧版纯 JSON 格式和新版 ``判断依据 + 结果区`` 文本格式。
    """
    content = _extract_assistant_text(sample)
    if content is None:
        return None

    # 先尝试旧版纯 JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 新版文本格式：解析 ``结果：`` 后的 JSON
    if "结果：" in content:
        result_part = content.split("结果：", 1)[1].strip()
        # 结果区可能包含尾部说明，取第一个 JSON 对象/数组
        try:
            return json.loads(result_part)
        except json.JSONDecodeError:
            # 尝试取第一个完整的 JSON 对象
            match = re.search(r"(\{.*\})", result_part, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    return None
            return None
    return None


def _is_adjacent_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and value[1] == value[0] + 1


def _is_mock_fingerprint(fp: Any) -> bool:
    if not isinstance(fp, str):
        return False
    return "mock" in fp.lower() or "theoretical" in fp.lower()


def _is_valid_subvideo_id(sid: Any) -> bool:
    """subvideo_id must be a non-empty string and not a placeholder."""
    return isinstance(sid, str) and bool(sid) and sid != "<unknown>"


def _validate_excluded_subvideos_metadata(
    data: dict[str, Any],
    subvideos_meta_path: Path,
    errors: list[dict[str, Any]],
) -> None:
    """Validate top-level excluded_subvideos in reviewed metadata."""
    if "excluded_subvideos" not in data:
        return

    excluded = data.get("excluded_subvideos")
    if not isinstance(excluded, list):
        errors.append(
            {
                "check": "excluded_subvideos",
                "detail": "excluded_subvideos_not_a_list",
                "path": str(subvideos_meta_path),
            }
        )
        return

    for idx, rec in enumerate(excluded):
        if not isinstance(rec, dict):
            errors.append(
                {
                    "check": "excluded_subvideos",
                    "detail": "excluded_subvideo_not_an_object",
                    "path": str(subvideos_meta_path),
                    "index": idx,
                    "record": rec,
                }
            )
            continue

        sid = rec.get("subvideo_id")
        if "subvideo_id" not in rec:
            errors.append(
                {
                    "check": "excluded_subvideos",
                    "detail": "missing_subvideo_id",
                    "path": str(subvideos_meta_path),
                    "index": idx,
                    "record": rec,
                }
            )
        elif not _is_valid_subvideo_id(sid):
            errors.append(
                {
                    "check": "excluded_subvideos",
                    "detail": "invalid_subvideo_id",
                    "path": str(subvideos_meta_path),
                    "index": idx,
                    "subvideo_id": sid,
                }
            )

        if "review_status" not in rec:
            errors.append(
                {
                    "check": "excluded_subvideos",
                    "detail": "missing_review_status",
                    "path": str(subvideos_meta_path),
                    "index": idx,
                    "subvideo_id": sid,
                }
            )
        elif rec.get("review_status") != STATUS_DROPPED:
            errors.append(
                {
                    "check": "excluded_subvideos",
                    "detail": "review_status_not_dropped",
                    "path": str(subvideos_meta_path),
                    "index": idx,
                    "subvideo_id": sid,
                    "review_status": rec.get("review_status"),
                    "expected": STATUS_DROPPED,
                }
            )


def _resolve_media_path(rel: str, project_root: Path) -> Path:
    if rel.startswith("data/"):
        return project_root / rel
    return project_root / "data" / rel


def _matches_legal_combination(output: dict[str, Any]) -> bool:
    """检查四字段结果区组合是否合法（不含 confidence）。"""
    hf = output.get("has_fracture")
    fb = output.get("fracture_between")
    ftype = output.get("type")
    loc = output.get("location")

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
                        "id": _sample_id(sample),
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
                        "id": _sample_id(sample),
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


def _validate_assistant_targets(
    merged_dir: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    """检查训练样本 assistant target 格式、无 confidence、结果区可解析。"""
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            text = _extract_assistant_text(sample)
            if text is None:
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "missing_assistant_text",
                    }
                )
                continue

            if "判断依据：" not in text:
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "missing_evidence_section",
                    }
                )
            if "结果：" not in text:
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "missing_result_section",
                    }
                )
                continue

            output = _extract_assistant_output(sample)
            if output is None:
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "result_json_not_parseable",
                        "content_preview": text[:200],
                    }
                )
                continue

            if not isinstance(output, dict):
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "result_not_a_dict",
                        "output": output,
                    }
                )
                continue

            if "confidence" in output:
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "confidence_field_present",
                    }
                )

            if set(output.keys()) != TARGET_SCHEMA_KEYS:
                errors.append(
                    {
                        "check": "assistant_target",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "result_schema_mismatch",
                        "expected": sorted(TARGET_SCHEMA_KEYS),
                        "actual": sorted(output.keys()),
                    }
                )
                continue

            if not _matches_legal_combination(output):
                errors.append(
                    {
                        "check": "field_combination",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "illegal_four_field_combination",
                        "output": output,
                    }
                )

            ftype = output.get("type")
            if ftype not in ALL_TYPES:
                errors.append(
                    {
                        "check": "type_closed_set",
                        "file": path.name,
                        "id": _sample_id(sample),
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
            if not isinstance(output, dict):
                continue
            fb = output.get("fracture_between")
            if fb is None:
                continue
            metadata = sample.get("metadata")
            if isinstance(metadata, dict):
                mapping = metadata.get("actual_frame_mapping") or []
            else:
                mapping = []
            if not mapping:
                mapping = sample.get("actual_frame_mapping") or []
            n = len(mapping)
            if n == 0:
                warnings.append(
                    {
                        "check": "fracture_between",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "missing_actual_frame_mapping",
                        "value": fb,
                    }
                )
                continue
            if not isinstance(fb, list) or len(fb) != 2:
                errors.append(
                    {
                        "check": "fracture_between",
                        "file": path.name,
                        "id": _sample_id(sample),
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
                        "id": _sample_id(sample),
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
                        "id": _sample_id(sample),
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
                        "id": _sample_id(sample),
                        "detail": "not_strictly_adjacent",
                        "value": fb,
                    }
                )


def _validate_prompt_version_consistency(
    merged_dir: Path,
    prompt_version: str | None,
    errors: list[dict[str, Any]],
) -> None:
    """检查所有训练/验证样本的 prompt_version 一致且等于模板库 version。"""
    seen_versions: set[str] = set()
    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            metadata = sample.get("metadata")
            if isinstance(metadata, dict):
                pv = metadata.get("prompt_version")
            else:
                pv = sample.get("prompt_version")
            if pv is None:
                errors.append(
                    {
                        "check": "prompt_version",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "missing_prompt_version",
                    }
                )
                continue
            seen_versions.add(pv)
            if prompt_version is not None and pv != prompt_version:
                errors.append(
                    {
                        "check": "prompt_version",
                        "file": path.name,
                        "id": _sample_id(sample),
                        "detail": "prompt_version_mismatch",
                        "expected": prompt_version,
                        "actual": pv,
                    }
                )

    if len(seen_versions) > 1:
        errors.append(
            {
                "check": "prompt_version",
                "detail": "inconsistent_prompt_versions",
                "versions": sorted(seen_versions),
            }
        )


def _validate_no_test_sharegpt(
    merged_dir: Path,
    errors: list[dict[str, Any]],
) -> None:
    """训练产物中不应存在 test ShareGPT 文件。"""
    test_path = merged_dir / "test.json"
    if test_path.exists():
        errors.append(
            {
                "check": "test_sharegpt",
                "detail": "test_sharegpt_file_exists",
                "path": str(test_path),
            }
        )


def _validate_processor_fingerprints(
    merged_dir: Path,
    subvideos_meta_path: Path,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    fingerprints: set[str] = set()
    mock_fingerprints: set[str] = set()
    missing_fingerprints: list[str] = []

    # 1. 扫描 merged JSON（若其中仍保留 fingerprint 字段）
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
                continue
            if _is_mock_fingerprint(fp):
                mock_fingerprints.add(fp)
            else:
                fingerprints.add(fp)

    # 2. 以 label_reviewed 子视频元数据中的 fingerprint 为准
    label_subs: list[dict[str, Any]] | None = None
    if subvideos_meta_path.exists():
        try:
            raw = _load_json(subvideos_meta_path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = None
        if isinstance(raw, dict):
            label_subs = raw.get("subvideos")
        elif isinstance(raw, list):
            label_subs = raw

    if isinstance(label_subs, list):
        for sub in label_subs:
            if not isinstance(sub, dict):
                continue
            fp = sub.get("processor_fingerprint")
            sub_id = sub.get("subvideo_id", "<unknown>")
            if fp is None or not isinstance(fp, str) or not fp.strip():
                missing_fingerprints.append(sub_id)
                continue
            if _is_mock_fingerprint(fp):
                mock_fingerprints.add(fp)
            else:
                fingerprints.add(fp)
    elif subvideos_meta_path.exists():
        warnings.append(
            {
                "check": "processor_fingerprint",
                "detail": "subvideos_meta_has_no_subvideo_list",
                "path": str(subvideos_meta_path),
            }
        )
    else:
        warnings.append(
            {
                "check": "processor_fingerprint",
                "detail": "subvideos_meta_missing_for_fingerprint_check",
                "path": str(subvideos_meta_path),
            }
        )

    if missing_fingerprints:
        errors.append(
            {
                "check": "processor_fingerprint",
                "detail": "missing_or_empty_processor_fingerprint",
                "subvideo_ids": missing_fingerprints,
            }
        )
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
    elif isinstance(label_subs, list) and label_subs:
        errors.append(
            {
                "check": "processor_fingerprint",
                "detail": "no_valid_processor_fingerprints_found",
                "path": str(subvideos_meta_path),
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


def _load_reviewed_subvideos(
    subvideos_meta_path: Path,
    errors: list[dict[str, Any]],
    allow_unreviewed_meta: bool = False,
) -> list[dict[str, Any]] | None:
    """读取人工审核后的子视频元数据；所有相关检查共享这一份解析结果。"""
    if not subvideos_meta_path.exists():
        errors.append({
            "check": "reviewed_ratio",
            "detail": "reviewed_metadata_missing",
            "path": str(subvideos_meta_path),
        })
        return None
    if not allow_unreviewed_meta and subvideos_meta_path.name != "subvideos_meta.label_reviewed.json":
        errors.append({
            "check": "reviewed_ratio",
            "detail": "unreviewed_metadata_rejected",
            "path": str(subvideos_meta_path),
            "expected": "subvideos_meta.label_reviewed.json",
        })
        return None
    try:
        data = _load_json(subvideos_meta_path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append({
            "check": "reviewed_ratio",
            "detail": "reviewed_metadata_invalid",
            "path": str(subvideos_meta_path),
            "error": f"metadata read error: {exc}",
        })
        return None
    if isinstance(data, dict):
        subvideos = data.get("subvideos")
        _validate_excluded_subvideos_metadata(data, subvideos_meta_path, errors)
    elif isinstance(data, list):
        subvideos = data
    else:
        subvideos = None

    if not isinstance(subvideos, list):
        errors.append({
            "check": "reviewed_ratio",
            "detail": "reviewed_metadata_invalid",
            "path": str(subvideos_meta_path),
        })
        return None

    return [sub for sub in subvideos if isinstance(sub, dict)]


def _report_reviewed_ratio(
    reviewed_subvideos: list[dict[str, Any]] | None,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """基于 label_reviewed 子视频元数据报告人工审核后正负样本比例。"""
    if reviewed_subvideos is None:
        return None

    pos = 0
    neg = 0
    for sub in reviewed_subvideos:
        # 仅统计被选中的训练样本：selected_splits 中至少有一个以 _train 结尾，
        # 且 has_fracture_canonical 不为 None（排除未知样本）。
        selected = sub.get("selected_splits")
        if selected is None:
            continue
        if not any(isinstance(s, str) and s.endswith("_train") for s in selected):
            continue
        if sub.get("has_fracture_canonical") is None:
            continue
        if is_positive_label(sub):
            pos += 1
        else:
            neg += 1

    total = pos + neg
    ratio = pos / neg if neg else None
    if ratio is not None:
        ratio = round(ratio, 4)
    result = {
        "positive": pos,
        "negative": neg,
        "total": total,
        "ratio": ratio,
    }
    if total == 0:
        errors.append({"check": "reviewed_ratio", "detail": "no_reviewed_samples", **result})
    elif pos == 0 or neg == 0:
        errors.append({
            "check": "reviewed_ratio",
            "detail": "missing_positive_or_negative_samples",
            **result,
            "allowed": "0.5:1 ~ 2:1",
        })
    elif not (0.5 <= ratio <= 2.0):
        errors.append({
            "check": "reviewed_ratio",
            "detail": "manual_review_ratio_out_of_range",
            **result,
            "allowed": "0.5:1 ~ 2:1",
        })
    return result


def _selected_splits_from_reviewed_subvideo(sub: dict[str, Any]) -> list[str]:
    selected = sub.get("selected_splits")
    if isinstance(selected, list):
        return [split for split in selected if isinstance(split, str) and split]

    # 兼容旧 sidecar/中间产物：如果尚未落 selected_splits，则尽量从明确的
    # fold assignment 字段恢复 split 名，保证检查能覆盖旧数据。
    assignments = sub.get("fold_assignments")
    if isinstance(assignments, list):
        return [split for split in assignments if isinstance(split, str) and split]

    fold = sub.get("fold")
    if isinstance(fold, str) and fold:
        return [fold]
    return []


def _validate_reviewed_split_leakage(
    reviewed_subvideos: list[dict[str, Any]] | None,
    merged_dir: Path,
    errors: list[dict[str, Any]],
) -> None:
    if reviewed_subvideos is None:
        return

    split_sources: dict[str, set[str]] = defaultdict(set)
    missing_source_ids: list[str] = []
    missing_split_ids: list[str] = []

    for sub in reviewed_subvideos:
        sub_id = sub.get("subvideo_id", "<unknown>")
        source = sub.get("source_video")
        splits = _selected_splits_from_reviewed_subvideo(sub)
        if not isinstance(source, str) or not source:
            missing_source_ids.append(str(sub_id))
            continue
        if not splits:
            missing_split_ids.append(str(sub_id))
            continue
        for split in splits:
            split_sources[split].add(source)

    test_inputs = _load_json(merged_dir / "test_inputs.json")
    if isinstance(test_inputs, list):
        for item in test_inputs:
            if isinstance(item, dict):
                src = item.get("video_id")
                if isinstance(src, str) and src:
                    split_sources["test"].add(src)

    if missing_source_ids:
        errors.append(
            {
                "check": "cross_split_leakage",
                "detail": "reviewed_metadata_missing_source_video",
                "subvideo_ids": missing_source_ids[:20],
                "count": len(missing_source_ids),
            }
        )
    if missing_split_ids:
        errors.append(
            {
                "check": "cross_split_leakage",
                "detail": "reviewed_metadata_missing_selected_splits",
                "subvideo_ids": missing_split_ids[:20],
                "count": len(missing_split_ids),
            }
        )

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
                    "source": "subvideos_meta.label_reviewed.json",
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


def _validate_review_status(
    merged_dir: Path,
    reviewed_subvideos: list[dict[str, Any]] | None,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    """检查训练/验证样本对应的子视频 review_status 必须为 approved。

    以 ``subvideos_meta.label_reviewed.json``（``reviewed_subvideos``）为权威来源，
    建立 ``subvideo_id -> review_status`` 映射。训练样本的 ``metadata.subvideo_id``
    用于在权威映射中定位；样本自身 ``metadata.review_status`` 仅与权威状态交叉校验，
    不能覆盖权威状态。
    """
    review_status_by_id: dict[str, Any] = {}
    if reviewed_subvideos is not None:
        for sub in reviewed_subvideos:
            if not isinstance(sub, dict):
                continue
            sid = sub.get("subvideo_id")
            if isinstance(sid, str) and sid:
                review_status_by_id[sid] = sub.get("review_status")

    for path in sorted(merged_dir.glob("*.json")):
        if path.name in {"samples_meta.json", "test_inputs.json", "test_ground_truth.json"}:
            continue
        if not (path.stem.endswith("_train") or path.stem.endswith("_val")):
            continue
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            display_id = _sample_id(sample)
            metadata = sample.get("metadata")
            lookup_id = (
                metadata.get("subvideo_id")
                if isinstance(metadata, dict)
                else None
            ) or display_id
            if not isinstance(lookup_id, str) or not lookup_id:
                errors.append(
                    {
                        "check": "review_status",
                        "file": path.name,
                        "id": display_id,
                        "detail": "missing_subvideo_id",
                    }
                )
                continue
            authoritative_status = review_status_by_id.get(lookup_id)
            if authoritative_status is None:
                errors.append(
                    {
                        "check": "review_status",
                        "file": path.name,
                        "id": display_id,
                        "detail": "subvideo_not_found_in_reviewed_meta",
                        "review_status": None,
                    }
                )
                continue
            if authoritative_status != "approved":
                errors.append(
                    {
                        "check": "review_status",
                        "file": path.name,
                        "id": display_id,
                        "detail": "subvideo_not_approved",
                        "review_status": authoritative_status,
                    }
                )
            if isinstance(metadata, dict) and "review_status" in metadata:
                metadata_status = metadata["review_status"]
                if metadata_status != authoritative_status:
                    errors.append(
                        {
                            "check": "review_status",
                            "file": path.name,
                            "id": display_id,
                            "detail": "metadata_review_status_mismatch",
                            "authoritative": authoritative_status,
                            "metadata": metadata_status,
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
    try:
        data = _load_json(subvideos_meta_path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
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
    subvideos_meta_path: Path = META_V2_DIR / "subvideos_meta.label_reviewed.json",
    report_path: Path = REPORT_PATH,
    project_root: Path = _PROJECT_ROOT,
    allow_unreviewed_meta: bool = False,
    prompt_library_path: Path = PROMPT_LIBRARY_DEFAULT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """执行全部强制检查，返回 (errors, warnings, summary)。"""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    reviewed_subvideos = _load_reviewed_subvideos(
        subvideos_meta_path, errors, allow_unreviewed_meta=allow_unreviewed_meta
    )

    library = _load_prompt_library(prompt_library_path)
    if not library:
        errors.append(
            {
                "check": "prompt_library",
                "detail": "prompt_library_missing_or_unreadable",
                "path": str(prompt_library_path),
            }
        )
    prompt_version = library.get("version")
    if prompt_version is None:
        errors.append(
            {
                "check": "prompt_library",
                "detail": "prompt_library_missing_version",
                "path": str(prompt_library_path),
            }
        )

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
        _validate_assistant_targets(merged_dir, errors, warnings)
        _validate_fracture_between(merged_dir, errors, warnings)
        _validate_prompt_version_consistency(merged_dir, prompt_version, errors)
        _validate_no_test_sharegpt(merged_dir, errors)
        _validate_processor_fingerprints(merged_dir, subvideos_meta_path, errors, warnings)
        _validate_train_ratios(merged_dir, errors, warnings)
        _validate_no_cross_split_leakage(merged_dir, errors, warnings)
        _validate_reviewed_split_leakage(reviewed_subvideos, merged_dir, errors)
        _validate_review_status(merged_dir, reviewed_subvideos, errors, warnings)
        _validate_test_input_isolation(merged_dir, errors, warnings)

    _validate_exclusions(subvideos_meta_path, errors)
    reviewed_ratio = _report_reviewed_ratio(reviewed_subvideos, errors)

    summary = {
        "merged_dir": str(merged_dir),
        "subvideos_meta": str(subvideos_meta_path),
        "prompt_library": str(prompt_library_path),
        "prompt_version": prompt_version,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "reviewed_ratio": reviewed_ratio,
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
    parser = argparse.ArgumentParser(
        description="数据产物质量校验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s

  # 指定产物目录和 prompt 模板库
  %(prog)s --merged-dir data/06_merged \
      --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json \
      --prompt-library pipeline/prompt_library.yaml
        """.strip(),
    )
    parser.add_argument(
        "--merged-dir",
        type=Path,
        default=MERGED_V2_DIR,
        help="产物目录（默认：data/06_merged）",
    )
    parser.add_argument(
        "--subvideos-meta",
        type=Path,
        default=META_V2_DIR / "subvideos_meta.label_reviewed.json",
        help="子视频元数据路径（默认：data/07_metadata/subvideos_meta.label_reviewed.json）",
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
    parser.add_argument(
        "--allow-unreviewed-meta",
        action="store_true",
        help="允许使用非 label-reviewed 的 subvideos metadata（仅开发调试用）",
    )
    parser.add_argument(
        "--prompt-library",
        type=Path,
        default=PROMPT_LIBRARY_DEFAULT,
        help="prompt 模板库路径（默认：pipeline/prompt_library.yaml）",
    )
    args = parser.parse_args(argv)

    errors, warnings, summary = run_quality_check(
        merged_dir=args.merged_dir,
        subvideos_meta_path=args.subvideos_meta,
        report_path=args.report,
        project_root=args.project_root,
        allow_unreviewed_meta=args.allow_unreviewed_meta,
        prompt_library_path=args.prompt_library,
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
