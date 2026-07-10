#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
训练样本构建器（判断依据 + 四字段结果）

默认将 ``data/07_metadata/subvideos_meta.label_reviewed.json`` 中的复检后
子视频元数据转换为 LLaMA-Factory ShareGPT 格式的多模态训练样本，并按
``data/05_splits/`` 中的 video_id 集合分组输出到 ``data/06_merged/``。

训练 assistant target 格式为：
    判断依据：<1-3 句视觉证据说明>
    结果：{"has_fracture": ..., "fracture_between": ..., "type": ..., "location": ...}

正式训练链路不应直接消费未经过人工审核和标签复检的
``subvideos_meta.json``；调试时可显式传入 ``--subvideos-meta`` 覆盖。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


SUBVIDEOS_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
VIDEO_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "video_meta.json"
SPLITS_DIR_DEFAULT = _PROJECT_ROOT / "data" / "05_splits"
OUTPUT_DIR_DEFAULT = _PROJECT_ROOT / "data" / "06_merged"
PROMPT_LIBRARY_DEFAULT = _PROJECT_ROOT / "pipeline" / "prompt_library.yaml"


FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
}

STATUS_APPROVED = "approved"
STATUS_DROPPED = "dropped"

SPLIT_NAMES = [
    "fold_0_train",
    "fold_0_val",
    "fold_1_train",
    "fold_1_val",
    "fold_2_train",
    "fold_2_val",
    "test",
]


def is_positive_label(obj: dict[str, Any]) -> bool:
    """统一正样本判断：以 has_fracture/has_fracture_canonical 为准。"""
    return obj.get("has_fracture_canonical", obj.get("has_fracture")) is True


def load_json(path: Path) -> Any:
    """读取 JSON 文件。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """写入 JSON 文件，必要时创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


def load_prompt_library(path: Path) -> dict[str, Any]:
    """读取 prompt 模板库 YAML 文件。"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def select_user_prompt_template(library: dict[str, Any], index: int) -> str:
    """根据索引循环选择一条 user prompt 模板（保留 <video> 占位符）。"""
    templates = library.get("user_prompt_templates", [])
    if not templates:
        raise ValueError("prompt library 中缺少 user_prompt_templates")
    return templates[index % len(templates)]["prompt"]


def load_split_video_ids(splits_dir: Path) -> dict[str, set[str]]:
    """
    加载所有划分文件，返回 ``{split_name: set(video_id), ...}``。

    仅识别 ``fold_*_{train,val}.json`` 与 ``test.json``。
    """
    mapping: dict[str, set[str]] = {}
    for path in sorted(splits_dir.glob("*.json")):
        if path.stem not in SPLIT_NAMES:
            continue
        data = load_json(path)
        mapping[path.stem] = set(data.get("video_ids", []))
    return {name: mapping.get(name, set()) for name in SPLIT_NAMES}


def _normalize_video_path(video_path: str) -> str:
    """规范化视频路径。

    - 以 ``data/`` 开头的相对路径保持原样。
    - 绝对路径（以 ``/`` 开头）保持原样。
    - 其它相对路径视为 ``data/`` 下的子目录，补全 ``data/`` 前缀。
    """
    if not isinstance(video_path, str):
        return video_path
    if video_path.startswith("data/") or video_path.startswith("/"):
        return video_path
    return f"data/{video_path}"


def _normalize_subvideo_labels(sub: dict[str, Any]) -> dict[str, Any]:
    """治理标签冲突：优先使用上游子视频元数据中的 canonical 字段。

    - 若子视频元数据已包含 ``has_fracture_canonical`` / ``location_canonical``，
      直接沿用，保证 CSV 原始标签不被覆盖。
    - 保证 ``has_fracture_canonical=True`` 时 ``type`` 在 7 个断裂类中或视频异常时间不可靠。
    """
    sub = dict(sub)
    ftype = sub.get("type", "")
    source_type = sub.get("source_type", ftype)
    source_location = sub.get("source_location")
    is_abnormal = sub.get("is_abnormal", False)

    has_fracture_canonical = sub.get("has_fracture_canonical")
    canonical_explicitly_null = "has_fracture_canonical" in sub and sub["has_fracture_canonical"] is None
    if has_fracture_canonical is None and not canonical_explicitly_null:
        has_fracture_canonical = sub.get("has_fracture", False)
        if is_abnormal or ftype not in FRACTURE_TYPES:
            has_fracture_canonical = False

    # 视频异常保留原 type；断裂样本仅保留有效位置
    if has_fracture_canonical is True:
        if ftype in FRACTURE_TYPES:
            location = sub.get("location_canonical") or sub.get("location")
            if location not in ("inside_gauge", "outside_gauge"):
                location = None
            fracture_between = sub.get("fracture_between")
        elif ftype == "视频异常":
            location = None
            fracture_between = None
        elif ftype == "未夹紧":
            # 未夹紧但有事件标注，保留正样本
            location = sub.get("location_canonical") or sub.get("location")
            if location not in ("inside_gauge", "outside_gauge"):
                location = None
            fracture_between = sub.get("fracture_between")
        else:
            # 不一致：降级为负样本
            has_fracture_canonical = False
            location = None
            fracture_between = None
    else:
        location = None
        fracture_between = None

    if has_fracture_canonical is True and ftype not in ("视频异常", "未夹紧") and fracture_between is None:
        raise ValueError(
            f"{sub.get('subvideo_id', sub.get('id', '<unknown>'))}: "
            "positive sample missing fracture_between"
        )

    # 归一化 type 字段
    if has_fracture_canonical is True:
        if ftype in FRACTURE_TYPES:
            sub["type"] = ftype
        elif ftype == "未夹紧":
            sub["type"] = "未夹紧"
        elif ftype == "视频异常":
            sub["type"] = "视频异常"
        else:
            # 未知或不一致的正样本 type，按负样本输出。
            sub["type"] = "未断裂"
    elif has_fracture_canonical is None and ftype == "视频异常":
        sub["type"] = "视频异常"
    else:
        # 无事件标注的“未夹紧”在此被降级为“未断裂”。
        sub["type"] = "未断裂"

    sub["has_fracture"] = has_fracture_canonical
    sub["has_fracture_canonical"] = has_fracture_canonical
    sub["fracture_between"] = fracture_between
    sub["location"] = location
    sub["location_canonical"] = location
    sub["source_type"] = source_type
    sub["source_location"] = source_location

    return sub


def compute_effective_frames(sub: dict[str, Any]) -> int:
    """Read actual processor frame count; never derive it from duration/FPS."""
    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
    if not mapping:
        raise ValueError("missing actual processor frame mapping")
    if len(mapping) > 8:
        raise ValueError("actual processor frame count violates max_frames=8")
    return len(mapping)


def _build_evidence_sentence(
    has_fracture: bool,
    ftype: str,
    fracture_between: list[int, int] | None,
    location: str | None,
) -> str:
    """根据标签生成 1-3 句视觉证据说明。"""
    if ftype == "视频异常":
        if has_fracture:
            return "视频画面存在异常，但仍标记有断裂事件，区间信息不可靠。"
        return "视频画面存在异常，无法可靠识别断裂事件。"

    if has_fracture:
        if ftype == "未夹紧":
            return "夹持区域未形成有效标距，记录为夹紧异常事件。"

        interval_text = (
            f"采样帧 {fracture_between[0]} 与帧 {fracture_between[1]} 之间"
            if fracture_between and len(fracture_between) == 2
            else "未知相邻帧区间"
        )
        loc_text = {
            "inside_gauge": "标距内",
            "outside_gauge": "标距外",
        }.get(location, location or "位置不明确")
        return f"在 {interval_text} 观察到断裂形貌突变，呈现 {ftype} 特征，断裂位于 {loc_text}。"

    return "在提供的采样帧序列中未观察到试样断裂，形貌保持连续。"


def build_assistant_content(sub: dict[str, Any]) -> str:
    """构造 assistant 输出：判断依据 + 可解析 JSON 结果区（不含 confidence）。"""
    has_fracture = bool(sub["has_fracture_canonical"])
    ftype = sub["type"]
    location = sub.get("location_canonical")
    fracture_between = sub.get("fracture_between") if has_fracture else None

    evidence = _build_evidence_sentence(has_fracture, ftype, fracture_between, location)

    result: dict[str, Any] = {
        "has_fracture": has_fracture,
        "fracture_between": fracture_between if has_fracture else None,
        "type": ftype,
        "location": location,
    }
    result_json = json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return f"判断依据：{evidence}\n结果：{result_json}"


def _build_actual_frame_mapping(sub: dict[str, Any]) -> list[dict[str, Any]]:
    """构建 actual_frame_mapping；优先使用子视频元数据中的 actual_frame_mapping。"""
    mapping = sub.get("actual_frame_mapping")
    if mapping is not None:
        return [
            {
                "input_index": frame.get("input_index"),
                "original_frame": frame.get("original_frame"),
                "timestamp": frame.get("timestamp"),
            }
            for frame in mapping
        ]
    sampled = sub.get("sampled_frames") or []
    return [
        {
            "input_index": frame.get("input_index"),
            "original_frame": frame.get("original_frame"),
            "timestamp": frame.get("timestamp"),
        }
        for frame in sampled
    ]


def _validate_minicpm_fingerprint(subvideo_id: Any, fingerprint: str) -> None:
    """Validate the structured MiniCPM frame-contract fingerprint."""
    parts = fingerprint.split(":")
    if len(parts) < 2 or parts[0] != "minicpmv4_5":
        raise ValueError(f"{subvideo_id}: invalid MiniCPM processor fingerprint")

    model_id = parts[1]
    if not model_id or "=" in model_id:
        raise ValueError(f"{subvideo_id}: MiniCPM processor fingerprint missing model id")

    fields: dict[str, str] = {}
    for part in parts[2:]:
        if "=" not in part:
            raise ValueError(f"{subvideo_id}: malformed MiniCPM processor fingerprint")
        key, value = part.split("=", 1)
        fields[key] = value

    if fields.get("max_frames") != "8":
        raise ValueError(f"{subvideo_id}: MiniCPM processor fingerprint must declare max_frames=8")

    try:
        video_fps = float(fields["video_fps"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{subvideo_id}: MiniCPM processor fingerprint must declare video_fps=2"
        ) from exc
    if video_fps != 2.0:
        raise ValueError(f"{subvideo_id}: MiniCPM processor fingerprint must declare video_fps=2")

    backend = fields.get("backend")
    if backend not in {"transformers", "transformers-loaded"}:
        raise ValueError(f"{subvideo_id}: invalid MiniCPM processor backend in fingerprint")


def convert_subvideo_to_sample(
    sub: dict[str, Any],
    library: dict[str, Any],
    template_index: int = 0,
) -> dict[str, Any]:
    """将单条子视频元数据转换为 ShareGPT 训练样本。"""
    sid = sub.get("subvideo_id", "<unknown>")
    review_status = sub.get("review_status")
    if review_status != STATUS_APPROVED:
        raise ValueError(
            f"{sid}: review_status={review_status!r} is not approved; "
            "only approved subvideos may be converted to training samples"
        )
    sub = _normalize_subvideo_labels(sub)
    processor_fingerprint = sub.get("processor_fingerprint")
    if not isinstance(processor_fingerprint, str) or not processor_fingerprint.strip():
        raise ValueError(f"{sub.get('subvideo_id')}: missing processor_fingerprint")
    lowered_fingerprint = processor_fingerprint.lower()
    if "mock" in lowered_fingerprint or "theoretical" in lowered_fingerprint:
        raise ValueError(
            f"{sub.get('subvideo_id')}: diagnostic processor fingerprint is forbidden"
        )
    if "minicpm" in lowered_fingerprint:
        _validate_minicpm_fingerprint(sub.get("subvideo_id"), processor_fingerprint)
    start_time = sub.get("start_time", 0.0)
    end_time = sub.get("end_time", 0.0)
    effective_frames = compute_effective_frames(sub)

    system_prompt = library.get("system_prompt", "")
    user_content = select_user_prompt_template(library, template_index)
    assistant_content = build_assistant_content(sub)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]

    sample: dict[str, Any] = {
        "id": sub["subvideo_id"],
        "videos": [_normalize_video_path(sub["video_path"])],
        "messages": messages,
        "has_fracture": sub["has_fracture_canonical"],
        "has_fracture_canonical": sub["has_fracture_canonical"],
        "fracture_between": sub.get("fracture_between"),
        "type": sub["type"],
        "location": sub["location_canonical"],
        "location_canonical": sub["location_canonical"],
        "source_type": sub.get("source_type", sub["type"]),
        "source_location": sub.get("source_location", sub["location"]),
        "source_video": sub["source_video"],
        "start_frame": sub.get("start_frame"),
        "end_frame": sub.get("end_frame"),
        "actual_frame_mapping": _build_actual_frame_mapping(sub),
        "processor_fingerprint": processor_fingerprint,
        "selection_reason": sub.get("selection_reason"),
        "exclusion_reason": sub.get("exclusion_reason"),
        "prompt_version": library.get("version"),
        "metadata": {
            "subvideo_id": sub["subvideo_id"],
            "source_video": sub["source_video"],
            "video_path": _normalize_video_path(sub["video_path"]),
            "prompt_version": library.get("version"),
            "review_status": sub.get("review_status"),
            "reviewed_at": sub.get("reviewed_at"),
            "fracture_between": sub.get("fracture_between"),
            "location_canonical": sub["location_canonical"],
            "type": sub["type"],
            "has_fracture_canonical": sub["has_fracture_canonical"],
            "actual_frame_mapping": _build_actual_frame_mapping(sub),
        },
    }
    return sample



def _validate_subvideo_review_status(subvideos: list[dict[str, Any]]) -> None:
    """训练导出前置状态检查：所有子视频必须是 approved 或 dropped。

    存在 unreviewed、needs_regenerate、状态缺失或非法状态时直接失败，
    并列出问题子视频 ID，避免未审查样本被静默遗漏。
    """
    invalid: dict[str, list[str]] = {}
    for sub in subvideos:
        status = sub.get("review_status")
        sid = sub.get("subvideo_id", "<unknown>")
        if status == STATUS_APPROVED:
            continue
        if status == STATUS_DROPPED:
            continue
        bucket = status if status is not None else "<missing>"
        invalid.setdefault(bucket, []).append(sid)

    if invalid:
        total = sum(len(sids) for sids in invalid.values())
        details = "; ".join(
            f"{status}: {sids}" for status, sids in sorted(invalid.items())
        )
        raise ValueError(
            f"训练导出被阻塞：存在 {total} 条子视频状态不是 approved/dropped：{details}"
        )


def _is_valid_subvideo_id(sid: Any) -> bool:
    """subvideo_id 必须是长度大于 0 的字符串，且不能是占位符。"""
    return isinstance(sid, str) and bool(sid) and sid != "<unknown>"


def _validate_excluded_subvideos(
    excluded_subvideos: list[dict[str, Any]] | None,
) -> None:
    """训练导出前置状态检查：excluded_subvideos 每一项都是对象且 review_status == dropped。

    非对象、缺失 subvideo_id/review_status、subvideo_id 无效、或 review_status 不是 dropped 都直接失败，
    并列出所有问题项及其原因，避免非 dropped 样本被静默遗漏。
    """
    if not excluded_subvideos:
        return

    errors: list[str] = []
    for rec in excluded_subvideos:
        if not isinstance(rec, dict):
            errors.append(f"非对象项: {rec!r}")
            continue
        sid = rec.get("subvideo_id", "<unknown>")
        if "subvideo_id" not in rec:
            errors.append(f"缺少 subvideo_id: {rec!r}")
        elif not _is_valid_subvideo_id(sid):
            errors.append(
                f"{sid!r}: subvideo_id 无效，必须是长度大于 0 的字符串且不能为 <unknown>"
            )
        if "review_status" not in rec:
            errors.append(f"{sid}: 缺少 review_status")
        elif rec["review_status"] != STATUS_DROPPED:
            errors.append(
                f"{sid}: review_status={rec['review_status']!r} 不是 dropped"
            )

    if errors:
        details = "; ".join(errors)
        raise ValueError(
            f"训练导出被阻塞：excluded_subvideos 中存在 {len(errors)} 条非法记录：{details}"
        )


def build_split_samples(
    subvideos: list[dict[str, Any]],
    split_video_ids: dict[str, set[str]],
    library: dict[str, Any],
    seed: int = 42,
    excluded_subvideos: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按当前划分将子视频分组并转换为训练样本（训练集做正负平衡，验证集保持完整）。"""
    _validate_excluded_subvideos(excluded_subvideos)
    _validate_subvideo_review_status(subvideos)

    rng = random.Random(seed)
    template_count = len(library.get("user_prompt_templates", []))
    by_split: dict[str, list[dict[str, Any]]] = {
        name: [] for name in split_video_ids if name != "test"
    }
    for sub in subvideos:
        sid = sub.get("subvideo_id", "<unknown>")
        review_status = sub.get("review_status")
        if review_status == STATUS_DROPPED:
            print(
                f"信息：剔除 dropped 子视频 {sid}",
                file=sys.stderr,
            )
            continue
        src = sub["source_video"]
        selected_splits = set(sub.get("selected_splits", []))
        template_index = rng.randint(0, template_count - 1) if template_count > 0 else 0
        for name, ids in split_video_ids.items():
            if name == "test":
                continue
            if src not in ids:
                continue
            if selected_splits and name not in selected_splits:
                continue
            by_split[name].append(
                convert_subvideo_to_sample(sub, library=library, template_index=template_index)
            )

    # 全局平衡已在 subvideo_builder 中完成，此处不再重复做 fold 级平衡
    return by_split


def _counter_to_dict(counter: Counter[Any], top_k: int | None = None) -> dict[str, int]:
    """将 Counter 转为可 JSON 序列化的字典，可选只保留 Top-K。"""
    items = counter.most_common(top_k) if top_k else counter.most_common()
    return {str(k): int(v) for k, v in items}


def compute_samples_meta(
    split_samples: dict[str, list[dict[str, Any]]],
    split_video_ids: dict[str, set[str]],
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """汇总每个 fold 的样本数、正负样本分布、视频来源分布等统计信息。"""
    split_meta: dict[str, Any] = {}
    total_pos = 0
    total_neg = 0

    for name, samples in split_samples.items():
        pos = sum(1 for s in samples if is_positive_label(s))
        neg = len(samples) - pos
        total_pos += pos
        total_neg += neg

        source_dist = Counter(s["source_video"] for s in samples)
        type_dist = Counter(s["type"] for s in samples)
        source_type_dist = Counter(s["source_type"] for s in samples)

        pos_ratio = round(pos / len(samples), 4) if samples else 0.0
        neg_ratio = round(neg / len(samples), 4) if samples else 0.0
        split_meta[name] = {
            "sample_count": len(samples),
            "video_source_count": len(source_dist),
            "positive_samples": pos,
            "negative_samples": neg,
            "positive_ratio": pos_ratio,
            "negative_ratio": neg_ratio,
            "source_distribution": _counter_to_dict(source_dist, top_k=20),
            "type_distribution": _counter_to_dict(type_dist),
            "source_type_distribution": _counter_to_dict(source_type_dist),
        }

    all_source_ids = set()
    for samples in split_samples.values():
        all_source_ids.update(s["source_video"] for s in samples)

    return {
        "prompt_version": prompt_version,
        "total_samples": total_pos + total_neg,
        "total_video_sources": len(all_source_ids),
        "total_positive": total_pos,
        "total_negative": total_neg,
        "splits": split_meta,
        "split_video_counts": {
            name: len(ids) for name, ids in split_video_ids.items()
        },
    }


def _build_test_artifacts(
    video_meta: list[dict[str, Any]],
    test_video_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """构造测试输入清单与真值 JSON。"""
    by_id = {r["video_id"]: r for r in video_meta}
    inputs: list[dict[str, Any]] = []
    ground_truth: list[dict[str, Any]] = []
    for vid in sorted(test_video_ids):
        rec = by_id.get(vid, {})
        video_path = _normalize_video_path(
            rec.get("video_path") or f"data/01_videos/{vid}.mp4"
        )
        inputs.append(
            {
                "id": vid,
                "video_id": vid,
                "video_path": video_path,
            }
        )
        ground_truth.append(
            {
                "video_id": vid,
                "has_fracture": rec.get("has_fracture"),
                "has_fracture_canonical": rec.get("has_fracture_canonical"),
                "is_abnormal": rec.get("is_abnormal"),
                "is_abnormal_canonical": rec.get("is_abnormal_canonical"),
                "video_anomaly_kind": rec.get("video_anomaly_kind"),
                "event_time_reliable": rec.get("event_time_reliable"),
                "event_frame_original": rec.get("event_frame_original"),
                "event_time": rec.get("event_time"),
                "type": rec.get("type"),
                "location": rec.get("location"),
                "location_canonical": rec.get("location_canonical"),
            }
        )
    return inputs, ground_truth


def build_all(
    subvideos_meta: Path,
    splits_dir: Path,
    output_dir: Path,
    video_meta_path: Path | None = None,
    prompt_library_path: Path | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """核心构建入口：读取元数据、分组、写文件、返回统计信息。"""
    if not subvideos_meta.exists():
        raise FileNotFoundError(
            f"子视频元数据不存在: {subvideos_meta}\n"
            "请先运行 pipeline/scripts/review_subvideo_labels.py 生成 label_reviewed 元数据，"
            "或显式传入 --subvideos-meta 指定其它 metadata 文件。"
        )
    if not splits_dir.exists():
        raise FileNotFoundError(f"划分目录不存在: {splits_dir}")

    prompt_library_path = prompt_library_path or PROMPT_LIBRARY_DEFAULT
    if not prompt_library_path.exists():
        raise FileNotFoundError(f"prompt 模板库不存在: {prompt_library_path}")
    library = load_prompt_library(prompt_library_path)
    prompt_version = library.get("version", "unknown")
    print(f"加载 prompt 模板库: {prompt_library_path} (version: {prompt_version})")

    print(f"读取子视频元数据: {subvideos_meta}")
    raw_subvideos = load_json(subvideos_meta)
    if isinstance(raw_subvideos, dict):
        subvideos = raw_subvideos.get("subvideos", [])
        excluded_subvideos = raw_subvideos.get("excluded_subvideos", [])
    else:
        subvideos = raw_subvideos
        excluded_subvideos = []
    print(f"共 {len(subvideos)} 个子视频")
    _validate_excluded_subvideos(excluded_subvideos)

    print(f"加载划分文件: {splits_dir}")
    split_video_ids = load_split_video_ids(splits_dir)
    for name, ids in split_video_ids.items():
        print(f"  {name}: {len(ids)} 个原始视频")

    print("构建训练样本...")
    split_samples = build_split_samples(
        subvideos,
        split_video_ids,
        library=library,
        seed=seed,
        excluded_subvideos=excluded_subvideos,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, samples in split_samples.items():
        out_path = output_dir / f"{name}.json"
        clean_samples = [
            {k: v for k, v in s.items() if k in ("messages", "videos", "metadata")}
            for s in samples
        ]
        write_json(out_path, clean_samples)
        print(f"写入: {out_path} ({len(samples)} 条样本)")

    test_ids = split_video_ids.get("test", set())
    if test_ids:
        vm_path = video_meta_path or VIDEO_META_DEFAULT
        if vm_path.exists():
            video_meta = load_json(vm_path)
            test_inputs, test_ground_truth = _build_test_artifacts(video_meta, test_ids)
            write_json(output_dir / "test_inputs.json", test_inputs)
            write_json(output_dir / "test_ground_truth.json", test_ground_truth)
            print(
                f"写入测试清单: {output_dir / 'test_inputs.json'} "
                f"({len(test_inputs)} 条), "
                f"真值: {output_dir / 'test_ground_truth.json'}"
            )
        else:
            print(f"警告：未找到 video_meta，跳过测试清单生成: {vm_path}")

    print("汇总样本统计信息...")
    samples_meta = compute_samples_meta(split_samples, split_video_ids, prompt_version=prompt_version)
    meta_path = output_dir / "samples_meta.json"
    write_json(meta_path, samples_meta)
    print(f"写入: {meta_path}")
    print("完成。")
    return samples_meta


def main() -> None:
    parser = argparse.ArgumentParser(description="五字段契约训练样本构建器")
    parser.add_argument(
        "--subvideos-meta", type=Path, default=SUBVIDEOS_META_DEFAULT
    )
    parser.add_argument("--video-meta", type=Path, default=VIDEO_META_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--prompt-library", type=Path, default=PROMPT_LIBRARY_DEFAULT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    build_all(
        subvideos_meta=args.subvideos_meta,
        splits_dir=args.splits_dir,
        output_dir=args.output_dir,
        video_meta_path=args.video_meta,
        prompt_library_path=args.prompt_library,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
