"""Build a deterministic V4.1 source snapshot in an isolated data context."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Mapping

from pipeline.current_data import DataContext

SOURCE_SCHEMA_VERSION = "tensile-source-snapshot/v1"
SPLIT_POLICY_VERSION = "split-policy/v1"
DEFAULT_EXPECTED_COUNT = 110
DEFAULT_SEED = 42
DEFAULT_TEST_RATIO = 0.2
DEFAULT_FOLDS = 3

TAG_COLUMNS = (
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
)
MAPPING_COLUMNS = (
    "标准化文件名",
    "原始文件名",
    "来源目录",
    "材料类别",
    "状态",
    "duration",
    "resolution",
    "codec",
)
MAPPING_STATUSES = frozenset({"existing", "new"})

FRACTURE_TYPES = frozenset(
    {
        "韧性断裂",
        "脆性断裂",
        "界面脱粘",
        "齐根断裂",
        "爆炸性断裂",
        "半脆半韧断裂",
        "界面脱粘、齐根断裂",
        "脆性断裂、齐根断裂",
    }
)
VIDEO_ANOMALY_TYPE = "视频异常"
VIDEO_ANOMALY_KIND_PRESENCE_UNKNOWN = "fracture_presence_unknown"
VIDEO_ANOMALY_KIND_TIME_UNKNOWN = "fracture_time_unknown"


class SourceBootstrapError(RuntimeError):
    """Source inputs cannot produce a complete deterministic snapshot."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        handle = Path(path).open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise SourceBootstrapError(f"无法读取 CSV: {path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = [name for name in required if name not in fields]
        if missing:
            raise SourceBootstrapError(f"{path.name} 缺少列: {', '.join(missing)}")
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in reader
        ]


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "是"}


def _parse_bool_or_none(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "是"}:
        return True
    if text in {"false", "0", "no", "否", ""}:
        return False
    return None


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_event_time(value: Any) -> float | str | None:
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else text


def _clean_location(value: Any) -> str:
    text = str(value).strip()
    return "N/A" if text.lower() in {"", "nan", "nat", "n/a"} else text


def _has_value(value: Any) -> bool:
    return str(value).strip().lower() not in {"", "nan", "nat", "<na>"}


def _canonical_location(location: str, has_fracture: bool) -> str | None:
    if has_fracture and location in {"inside_gauge", "outside_gauge"}:
        return location
    return None


def _governed_record(
    row: Mapping[str, str],
    probe: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    video_id = row["id"].strip()
    warnings: list[str] = []
    csv_has_fracture = _parse_bool_or_none(row.get("has_fracture"))
    csv_is_abnormal = _parse_bool(row.get("is_abnormal"))
    fracture_type = row.get("断裂模式", "").strip() or "未知"
    location = _clean_location(row.get("断裂位置"))
    reasons: list[str] = []
    is_conflict = False

    if fracture_type in FRACTURE_TYPES:
        canonical_fracture: bool | None = True
        canonical_abnormal = False
        anomaly_kind = None
        time_reliable = True
        canonical_location = _canonical_location(location, True)
        if csv_has_fracture is False:
            reasons.append("断裂 type 与 has_fracture=False 冲突，以 type 为准")
            is_conflict = True
    elif fracture_type == "未断裂":
        canonical_fracture = False
        canonical_abnormal = False
        anomaly_kind = None
        time_reliable = False
        canonical_location = None
        if csv_has_fracture is True:
            reasons.append("未断裂 type 与 has_fracture=True 冲突")
            is_conflict = True
        if csv_is_abnormal:
            reasons.append("未断裂 type 与 is_abnormal=True 冲突")
            is_conflict = True
    elif fracture_type == "未夹紧":
        canonical_fracture = False
        canonical_abnormal = True
        anomaly_kind = None
        time_reliable = _has_value(row.get("断裂帧数")) or _has_value(
            row.get("断裂时间点")
        )
        canonical_location = None
        if csv_has_fracture is True:
            reasons.append("未夹紧 type 与 has_fracture=True 冲突")
            is_conflict = True
    elif fracture_type == VIDEO_ANOMALY_TYPE:
        canonical_abnormal = True
        canonical_location = None
        time_reliable = False
        if csv_has_fracture is True:
            canonical_fracture = True
            anomaly_kind = VIDEO_ANOMALY_KIND_TIME_UNKNOWN
        else:
            canonical_fracture = None
            anomaly_kind = VIDEO_ANOMALY_KIND_PRESENCE_UNKNOWN
    else:
        canonical_fracture = False
        canonical_abnormal = False
        anomaly_kind = None
        time_reliable = False
        canonical_location = None
        reasons.append(f"未知 type={fracture_type}，按未断裂处理")
        is_conflict = True

    if canonical_abnormal and location not in {"N/A", ""}:
        reasons.append("异常视频 location_canonical 强制为 null")
        is_conflict = True

    event_time = _parse_event_time(row.get("断裂时间点"))
    event_frame = _to_int(row.get("断裂帧数"))
    fps = float(probe["fps"])
    if event_frame is None and isinstance(event_time, (int, float)):
        event_frame = int(round(float(event_time) * fps))
    warnings.extend(f"{video_id}: {reason}" for reason in reasons)
    return (
        {
            "video_id": video_id,
            "video_path": f"source/videos/{video_id}.mp4",
            "fps": fps,
            "total_frames": int(probe["total_frames"]),
            "duration": int(probe["duration_us"]) / 1_000_000,
            "event_time": event_time,
            "event_frame_original": _to_int(row.get("断裂帧数")),
            "event_frame_effective": event_frame,
            "type": fracture_type,
            "location": location,
            "material_type": row.get("材料类型", "").strip() or "其他",
            "resolution": row.get("清晰度", "").strip() or "未知",
            "has_fracture": csv_has_fracture,
            "is_abnormal": csv_is_abnormal,
            "has_fracture_canonical": canonical_fracture,
            "location_canonical": canonical_location,
            "is_abnormal_canonical": canonical_abnormal,
            "video_anomaly_kind": anomaly_kind,
            "event_time_reliable": time_reliable,
            "is_label_conflict": is_conflict,
            "label_governance_reason": "; ".join(reasons) if reasons else None,
        },
        warnings,
    )


def probe_video(path: Path, *, ffprobe: str = "ffprobe") -> dict[str, Any]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name,r_frame_rate,nb_frames,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceBootstrapError(f"ffprobe 无法执行: {path}") from exc
    if result.returncode != 0:
        raise SourceBootstrapError(
            f"ffprobe 失败: {path}: {result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        rate = Fraction(str(stream["r_frame_rate"]))
        duration = _to_float(stream.get("duration"))
        if duration is None:
            duration = _to_float((payload.get("format") or {}).get("duration"))
        frames = _to_int(stream.get("nb_frames"))
        if frames is None and duration is not None:
            frames = int(round(duration * float(rate)))
    except (KeyError, IndexError, ValueError, ZeroDivisionError) as exc:
        raise SourceBootstrapError(f"ffprobe 输出无效: {path}") from exc
    if (
        width < 1
        or height < 1
        or rate <= 0
        or duration is None
        or duration <= 0
        or frames is None
        or frames < 1
    ):
        raise SourceBootstrapError(f"ffprobe 媒体属性非法: {path}")
    return {
        "width": width,
        "height": height,
        "codec_name": str(stream.get("codec_name") or "unknown").lower(),
        "fps_num": rate.numerator,
        "fps_den": rate.denominator,
        "fps": float(rate),
        "duration_us": int(round(duration * 1_000_000)),
        "total_frames": frames,
    }


def _compute_strata(
    records: list[dict[str, Any]],
) -> tuple[dict[str, str], str]:
    raw_counts: Counter[str] = Counter()
    raw_keys: dict[str, str] = {}
    for record in records:
        location = record.get("location_canonical")
        key = (
            "N/A"
            if location is None
            else f"{record['type']}@@{location}"
        )
        raw_keys[record["video_id"]] = key
        raw_counts[key] += 1

    merged_counts: Counter[str] = Counter()
    merged_keys: dict[str, str] = {}
    for record in records:
        key = raw_keys[record["video_id"]]
        if key != "N/A" and raw_counts[key] <= 2:
            key = f"rare_fracture@@{record.get('location_canonical')}"
        merged_keys[record["video_id"]] = key
        merged_counts[key] += 1

    if any(count <= 2 and key != "N/A" for key, count in merged_counts.items()):
        return (
            {
                record["video_id"]: (
                    "N/A"
                    if record.get("location_canonical") is None
                    else record["type"]
                )
                for record in records
            },
            "type_only",
        )
    return merged_keys, "type_location_rare_merged"


def _rare_pool(records: list[dict[str, Any]]) -> list[str]:
    counts = Counter(record["type"] for record in records)
    return sorted(
        record["video_id"]
        for record in records
        if counts[record["type"]] <= 2
    )


def stratified_split(
    records: list[dict[str, Any]],
    *,
    test_ratio: float = DEFAULT_TEST_RATIO,
    n_folds: int = DEFAULT_FOLDS,
    seed: int = DEFAULT_SEED,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    rng = random.Random(seed)
    rare = _rare_pool(records)
    rare_set = set(rare)
    remaining = [record for record in records if record["video_id"] not in rare_set]
    strata, decision = _compute_strata(remaining)
    groups: dict[str, list[str]] = defaultdict(list)
    for record in remaining:
        groups[strata[record["video_id"]]].append(record["video_id"])

    test_ids: list[str] = []
    pool_ids: list[str] = []
    for ids in groups.values():
        shuffled = ids.copy()
        rng.shuffle(shuffled)
        n_test = (
            max(1, int(round(len(shuffled) * test_ratio)))
            if len(shuffled) >= 2
            else 0
        )
        while len(shuffled) - n_test < n_folds and n_test > 0:
            n_test -= 1
        test_ids.extend(shuffled[:n_test])
        pool_ids.extend(shuffled[n_test:])

    pool_set = set(pool_ids)
    pool_records = [record for record in records if record["video_id"] in pool_set]
    pool_strata, pool_decision = _compute_strata(pool_records)
    pool_groups: dict[str, list[str]] = defaultdict(list)
    for record in pool_records:
        pool_groups[pool_strata[record["video_id"]]].append(record["video_id"])

    folds: list[list[str]] = [[] for _ in range(n_folds)]
    for ids in pool_groups.values():
        shuffled = ids.copy()
        rng.shuffle(shuffled)
        chunk_size = math.ceil(len(shuffled) / n_folds)
        for index in range(n_folds):
            folds[index].extend(
                shuffled[index * chunk_size : (index + 1) * chunk_size]
            )

    result: dict[str, list[str]] = {"test": sorted(test_ids)}
    for index in range(n_folds):
        train = [
            video_id
            for other_index, fold in enumerate(folds)
            if other_index != index
            for video_id in fold
        ]
        result[f"fold_{index}_train"] = sorted(set(train + rare))
        result[f"fold_{index}_val"] = sorted(folds[index])
    return result, {
        "method": "stratified_split_with_rare_pool",
        "policy_version": SPLIT_POLICY_VERSION,
        "test_ratio": test_ratio,
        "n_folds": n_folds,
        "seed": seed,
        "rare_pool": rare,
        "overall_strata_decision": decision,
        "pool_strata_decision": pool_decision,
    }


def _normalized_rows(
    rows: list[dict[str, str]],
    *,
    key: str,
    columns: tuple[str, ...],
) -> list[dict[str, str]]:
    return [
        {column: row.get(column, "").strip() for column in columns}
        for row in sorted(rows, key=lambda item: item[key])
    ]


def _validate_inputs(
    source: DataContext,
    *,
    expected_count: int,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    dict[str, Path],
    list[dict[str, Any]],
]:
    tags = _read_csv(source.annotations / "all_videos_tag.csv", TAG_COLUMNS)
    mappings = _read_csv(source.annotations / "video_mapping.csv", MAPPING_COLUMNS)
    videos = {path.stem: path for path in sorted(source.videos.glob("*.mp4"))}

    tag_ids = [row["id"].strip() for row in tags]
    mapping_ids = [Path(row["标准化文件名"].strip()).stem for row in mappings]
    for video_id in tag_ids:
        if not re.fullmatch(r"video_\d{4}", video_id):
            raise SourceBootstrapError(f"非法 video ID: {video_id}")
    if len(tag_ids) != len(set(tag_ids)):
        raise SourceBootstrapError("all_videos_tag.csv 存在重复 ID")
    if len(mapping_ids) != len(set(mapping_ids)):
        raise SourceBootstrapError("video_mapping.csv 存在重复标准化文件名")
    if len(videos) != expected_count:
        raise SourceBootstrapError(
            f"MP4 数量必须为 {expected_count}，实际为 {len(videos)}"
        )
    expected = set(videos)
    if set(tag_ids) != expected or set(mapping_ids) != expected:
        raise SourceBootstrapError(
            "视频、all_videos_tag.csv 与 video_mapping.csv 的 ID 集合不一致"
        )
    tag_index = {row["id"].strip(): row for row in tags}
    mapping_index = {
        Path(row["标准化文件名"].strip()).stem: row for row in mappings
    }
    material_differences: list[dict[str, Any]] = []
    for video_id in sorted(expected):
        tag = tag_index[video_id]
        mapping = mapping_index[video_id]
        if Path(tag["video_path"].strip()).name != f"{video_id}.mp4":
            raise SourceBootstrapError(f"{video_id}: video_path basename 不匹配")
        if not mapping["原始文件名"].strip() or not mapping["来源目录"].strip():
            raise SourceBootstrapError(f"{video_id}: 来源追踪字段为空")
        if mapping["状态"].strip() not in MAPPING_STATUSES:
            raise SourceBootstrapError(f"{video_id}: 非法 mapping 状态")
        if tag["材料类型"].strip() != mapping["材料类别"].strip():
            material_differences.append(
                {
                    "video_id": video_id,
                    "tag_material": tag["材料类型"].strip(),
                    "mapping_material": mapping["材料类别"].strip(),
                }
            )
    return tags, mappings, videos, material_differences


def current_source_fingerprint(
    source: DataContext,
    *,
    expected_count: int = DEFAULT_EXPECTED_COUNT,
) -> dict[str, Any]:
    """Hash the authoritative source inputs without probing or writing."""
    _, _, videos, _ = _validate_inputs(source, expected_count=expected_count)
    return {
        "annotation_hashes": {
            name: sha256_file(source.annotations / name)
            for name in ("all_videos_tag.csv", "video_mapping.csv")
        },
        "videos": [
            {
                "video_id": video_id,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for video_id, path in sorted(videos.items())
        ],
    }


def build_source_snapshot(
    source: DataContext,
    rebuild: DataContext,
    *,
    expected_count: int = DEFAULT_EXPECTED_COUNT,
    probe: Callable[[Path], dict[str, Any]] = probe_video,
) -> dict[str, Any]:
    tags, mappings, videos, material_differences = _validate_inputs(
        source,
        expected_count=expected_count,
    )
    tag_index = {row["id"].strip(): row for row in tags}
    mapping_index = {
        Path(row["标准化文件名"].strip()).stem: row for row in mappings
    }
    inventory: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    media_differences: list[dict[str, Any]] = []
    for video_id, path in videos.items():
        state = {
            "video_id": video_id,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        media_probe = probe(path)
        normalized_probe = {
            key: media_probe[key]
            for key in (
                "width",
                "height",
                "codec_name",
                "fps_num",
                "fps_den",
                "duration_us",
                "total_frames",
            )
        }
        inventory.append({**state, "probe": normalized_probe})
        record, record_warnings = _governed_record(
            tag_index[video_id],
            media_probe,
        )
        records.append(record)
        warnings.extend(record_warnings)
        tag = tag_index[video_id]
        mapping = mapping_index[video_id]
        comparisons = (
            (
                "mapping.duration",
                _to_float(mapping.get("duration")),
                int(media_probe["duration_us"]) / 1_000_000,
                0.05,
            ),
            (
                "tag.duration",
                _to_float(tag.get("视频时长")),
                int(media_probe["duration_us"]) / 1_000_000,
                0.05,
            ),
            (
                "tag.fps",
                _to_float(tag.get("视频帧率")),
                float(media_probe["fps"]),
                0.01,
            ),
            (
                "tag.total_frames",
                _to_float(tag.get("视频总帧数")),
                float(media_probe["total_frames"]),
                0.0,
            ),
        )
        for field, historical, observed, tolerance in comparisons:
            if historical is not None and abs(historical - observed) > tolerance:
                media_differences.append(
                    {
                        "video_id": video_id,
                        "field": field,
                        "historical": historical,
                        "probed": observed,
                    }
                )
        mapping_resolution = mapping.get("resolution", "").strip().lower()
        probed_resolution = (
            f"{media_probe['width']}x{media_probe['height']}".lower()
        )
        if mapping_resolution and mapping_resolution != probed_resolution:
            media_differences.append(
                {
                    "video_id": video_id,
                    "field": "mapping.resolution",
                    "historical": mapping_resolution,
                    "probed": probed_resolution,
                }
            )
        mapping_codec = mapping.get("codec", "").strip().lower()
        probed_codec = str(media_probe["codec_name"]).strip().lower()
        if mapping_codec and mapping_codec != probed_codec:
            media_differences.append(
                {
                    "video_id": video_id,
                    "field": "mapping.codec",
                    "historical": mapping_codec,
                    "probed": probed_codec,
                }
            )

    records.sort(key=lambda item: item["video_id"])
    splits, decision = stratified_split(records)
    normalized_tags = _normalized_rows(tags, key="id", columns=TAG_COLUMNS)
    normalized_mappings = _normalized_rows(
        mappings,
        key="标准化文件名",
        columns=MAPPING_COLUMNS,
    )
    csv_contracts = {
        "all_videos_tag.csv": {
            "columns": list(TAG_COLUMNS),
            "normalized_rows_sha256": sha256_bytes(
                canonical_bytes(normalized_tags)
            ),
        },
        "video_mapping.csv": {
            "columns": list(MAPPING_COLUMNS),
            "normalized_rows_sha256": sha256_bytes(
                canonical_bytes(normalized_mappings)
            ),
        },
    }
    identity = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "split_policy": SPLIT_POLICY_VERSION,
        "videos": inventory,
        "csv_contracts": csv_contracts,
        "all_videos_tag": normalized_tags,
        "video_mapping": normalized_mappings,
        "splits": splits,
    }
    digest = sha256_bytes(canonical_bytes(identity))
    snapshot_id = f"source-snapshot-{digest[:12]}"
    return {
        "snapshot_id": snapshot_id,
        "identity_sha256": digest,
        "video_meta": records,
        "splits": splits,
        "split_decision": decision,
        "inventory": {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "source_snapshot_id": snapshot_id,
            "identity_sha256": digest,
            "source_root": "source",
            "annotation_hashes": {
                "all_videos_tag.csv": sha256_file(
                    source.annotations / "all_videos_tag.csv"
                ),
                "video_mapping.csv": sha256_file(
                    source.annotations / "video_mapping.csv"
                ),
            },
            "csv_contracts": csv_contracts,
            "videos": inventory,
        },
        "validation": {
            "status": "passed",
            "video_count": len(videos),
            "tag_count": len(tags),
            "mapping_count": len(mappings),
            "material_difference_count": len(material_differences),
            "material_differences": material_differences,
            "media_difference_count": len(media_differences),
            "media_differences": media_differences,
            "warnings": warnings,
        },
        "_source_files": {
            "videos": videos,
            "annotations": {
                name: source.annotations / name
                for name in ("all_videos_tag.csv", "video_mapping.csv")
            },
        },
        "_rebuild_root": rebuild.root,
        "_probe": probe,
    }


def _copy_verified(source: Path, destination: Path, expected_hash: str) -> None:
    if destination.exists():
        stat = destination.lstat()
        if (
            destination.is_symlink()
            or not destination.is_file()
            or stat.st_nlink != 1
            or sha256_file(destination) != expected_hash
        ):
            raise SourceBootstrapError(f"staging 目标已存在且内容不同: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != expected_hash:
            raise SourceBootstrapError(f"复制后 SHA-256 不一致: {source}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _split_payload(
    name: str,
    video_ids: list[str],
    split_decision: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "split": name,
        "video_ids": video_ids,
        "count": len(video_ids),
        "method": "stratified_type_location_with_rare_pool_v2",
        "seed": DEFAULT_SEED,
        "test_ratio": DEFAULT_TEST_RATIO,
        "fold": (
            int(name.split("_")[1]) if name.startswith("fold_") else None
        ),
        "rare_pool_included": name.endswith("_train"),
        "strata_decision": split_decision["overall_strata_decision"],
    }


def _expected_snapshot_files(
    bundle: Mapping[str, Any],
) -> dict[str, bytes]:
    result = {
        "video_meta.json": canonical_bytes(bundle["video_meta"]),
        "source_inventory.json": canonical_bytes(bundle["inventory"]),
        "split_decision.json": canonical_bytes(bundle["split_decision"]),
        "validation_report.json": canonical_bytes(bundle["validation"]),
    }
    for name, video_ids in bundle["splits"].items():
        result[f"splits/{name}.json"] = canonical_bytes(
            _split_payload(name, video_ids, bundle["split_decision"])
        )
    return result


def _validate_physical_file(
    path: Path,
    *,
    expected_hash: str,
    label: str,
) -> None:
    if path.is_symlink() or not path.is_file():
        raise SourceBootstrapError(f"{label} 必须是物理文件: {path}")
    if path.stat().st_nlink != 1:
        raise SourceBootstrapError(f"{label} 不允许 hardlink: {path}")
    if sha256_file(path) != expected_hash:
        raise SourceBootstrapError(f"{label} SHA-256 漂移: {path}")


def validate_materialized_source_snapshot(
    bundle: Mapping[str, Any],
    snapshot: Path,
) -> None:
    """Recompute every staged source and snapshot artifact during resume."""
    rebuild_root = Path(bundle["_rebuild_root"])
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise SourceBootstrapError(f"source snapshot 必须是物理目录: {snapshot}")

    inventory_index = {
        row["video_id"]: row for row in bundle["inventory"]["videos"]
    }
    expected_video_names = {
        f"{video_id}.mp4" for video_id in inventory_index
    }
    staged_video_names = {
        path.name for path in (rebuild_root / "source/videos").iterdir()
    }
    if staged_video_names != expected_video_names:
        raise SourceBootstrapError("staging source/videos 文件集合漂移")
    for video_id, row in inventory_index.items():
        staged_video = (
            rebuild_root / "source/videos" / f"{video_id}.mp4"
        )
        _validate_physical_file(
            staged_video,
            expected_hash=str(row["sha256"]),
            label=f"{video_id} staging video",
        )
        probe = bundle.get("_probe")
        if not callable(probe):
            raise SourceBootstrapError("source bundle 缺少 probe 实现")
        staged_probe = probe(staged_video)
        normalized_probe = {
            key: staged_probe[key]
            for key in (
                "width",
                "height",
                "codec_name",
                "fps_num",
                "fps_den",
                "duration_us",
                "total_frames",
            )
        }
        if normalized_probe != row.get("probe"):
            raise SourceBootstrapError(
                f"{video_id}: staging ffprobe 与 source inventory 不一致"
            )

    annotation_hashes = bundle["inventory"]["annotation_hashes"]
    annotation_root = rebuild_root / "source/annotations"
    if {path.name for path in annotation_root.iterdir()} != set(
        annotation_hashes
    ):
        raise SourceBootstrapError("staging source/annotations 文件集合漂移")
    for name, expected_hash in annotation_hashes.items():
        _validate_physical_file(
            annotation_root / name,
            expected_hash=str(expected_hash),
            label=f"{name} staging annotation",
        )

    expected_files = _expected_snapshot_files(bundle)
    actual_files = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    actual_directories = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    if actual_files != set(expected_files) or actual_directories != {"splits"}:
        raise SourceBootstrapError("source snapshot 文件集合漂移")
    for relative, content in expected_files.items():
        _validate_physical_file(
            snapshot / relative,
            expected_hash=sha256_bytes(content),
            label=f"source snapshot {relative}",
        )

    split_root = rebuild_root / "source/splits"
    expected_splits = {
        Path(relative).name: content
        for relative, content in expected_files.items()
        if relative.startswith("splits/")
    }
    if {path.name for path in split_root.iterdir()} != set(expected_splits):
        raise SourceBootstrapError("staging source/splits 文件集合漂移")
    for name, content in expected_splits.items():
        _validate_physical_file(
            split_root / name,
            expected_hash=sha256_bytes(content),
            label=f"staging split {name}",
        )


def materialize_source_snapshot(bundle: Mapping[str, Any]) -> Path:
    rebuild_root = Path(bundle["_rebuild_root"])
    source_files = bundle["_source_files"]
    managed_directories = (
        rebuild_root,
        rebuild_root / "source",
        rebuild_root / "source/videos",
        rebuild_root / "source/annotations",
        rebuild_root / "source/splits",
        rebuild_root / "derived",
        rebuild_root / "derived/metadata",
        rebuild_root / "derived/metadata/source_snapshots",
    )
    for directory in managed_directories:
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise SourceBootstrapError(
                f"staging 受管目录必须是物理目录: {directory}"
            )
    inventory_index = {
        row["video_id"]: row for row in bundle["inventory"]["videos"]
    }
    for video_id, source_path in source_files["videos"].items():
        _copy_verified(
            Path(source_path),
            rebuild_root / "source/videos" / f"{video_id}.mp4",
            inventory_index[video_id]["sha256"],
        )
    annotation_hashes = bundle["inventory"]["annotation_hashes"]
    for name, source_path in source_files["annotations"].items():
        _copy_verified(
            Path(source_path),
            rebuild_root / "source/annotations" / name,
            annotation_hashes[name],
        )

    snapshot = (
        rebuild_root
        / "derived/metadata/source_snapshots"
        / str(bundle["snapshot_id"])
    )
    if snapshot.exists():
        validate_materialized_source_snapshot(bundle, snapshot)
        return snapshot
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{bundle['snapshot_id']}.", dir=snapshot.parent)
    )
    try:
        (temporary / "splits").mkdir()
        for relative, content in _expected_snapshot_files(bundle).items():
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        os.rename(temporary, snapshot)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    split_root = rebuild_root / "source/splits"
    split_root.mkdir(parents=True, exist_ok=True)
    for path in (snapshot / "splits").glob("*.json"):
        _copy_verified(path, split_root / path.name, sha256_file(path))
    validate_materialized_source_snapshot(bundle, snapshot)
    return snapshot
