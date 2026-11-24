"""Extract a few declared frame positions from clip media and record what was decoded.

ffmpeg/ffprobe are the only media readers; the ``select`` filter emits only the chosen
positions as PNG. Every record carries a four-layer lineage:

``L0`` original source video / ``L1`` ROI video / ``L2`` sub-video clip / ``L3`` the model
input frames decoded from L2. Frame numbers are only derived when the sub-video manifest
holds a verified frame-preserving replay plus evidence that ``roi_frame == source_frame``
(``L1``→``L0`` 同序)：优先级 1 ``manifest_anchors``（候选自带 anchors 自证）、优先级 2
``source_replay_mapping``（``sources[]`` 来源级 replay 声明 + L0/L1 实解码帧数相等）、优先级 3
``unverified``。anchors 非空但自相矛盾是硬失败，绝不降级到来源级声明；什么都证不出来就留两个空
索引而不是猜。批级输出 ``lineage_summary``：三档计数/占比、unverified 的 failed_conditions
直方图与帧号覆盖率告警（``--coverage-scan`` 可只读帧数就产出）。

记录格式从 ``five-label-input-record/2`` 升到 ``/3``：将 ``frames[].frame_index_mapping`` 三个节点
重命名为与实际层级方向一致的 ``clip_to_model_input``（L2→L3）、``clip_to_roi``（L2→L1）与
``roi_to_original``（L1→L0），并显式拒绝旧 ``/2`` schema 或遗留键名（``media_to_clip``／
``source_to_media``／``roi_to_source``）。沿用 ``/2`` 引入的 ``lineage_media``、
``roi_frame_index``/``original_source_frame_index``、``verification`` 与 ``frame_count_convention``。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from . import paths
from .score import InputError, decode_file, require_text

RECORD_SCHEMA = "five-label-input-record/3"
SIZE_BUCKET_SOURCE = "width_rule_le200_lt400"
VERIFIED_REPLAY = "verified_frame_preserving_replay"
# 来源级 replay 声明里固定的 mapping 常量：只有它才算「源帧 i 与 ROI 帧 i 同序」。
SOURCE_MAPPING = "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"
ROI_TO_ORIGINAL_METHODS = ("manifest_anchors", "source_replay_mapping", "unverified")
MAPPING_NODE_KEYS = ("clip_to_model_input", "clip_to_roi", "roi_to_original")
LEGACY_MAPPING_KEYS = ("media_to_clip", "source_to_media", "roi_to_source")
FAILED_CONDITION_TOKENS = ("no_output", "replay_unverified", "bad_clip_index", "no_frame_mapping",
                           "bad_source_start", "anchors_broken", "c1_source_record",
                           "c2_decoded_frame_counts", "c3_candidate_replay")
SUMMARY_SCHEMA = "five-label-lineage-summary/1"
# unverified 占比超过 5% 才告警：恰好 5% 仍算可接受。
COVERAGE_WARNING_RATIO = 0.05
COVERAGE_WARNING_TEXT = "本批帧号覆盖率不足，结果不可用于需要逐帧追溯的分析"
FALLBACK_TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
SHA256 = re.compile(r"[a-f0-9]{64}")
SHOWINFO = re.compile(r"\] n:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:(-?\d+(?:\.\d+)?)")
LAYERS = ("l0", "l1", "l2")
# L3 帧是 L2 的第 ``clip_frame_index`` 个解码帧：抽帧规则本身就是 L2→L3 的映射。
CLIP_TO_MODEL_INPUT = {"kind": "ffmpeg_select_nth_decoded_frame", "offset": None,
                       "reason": "L3 帧由 ffmpeg select=eq(n\\,clip_frame_index) 从 L2 按解码序抽取"}
# 同一路径一次运行内只探测一次：``-count_frames`` 会全解码，重复调用很贵。
_FRAME_COUNT_CACHE: dict[str, int | None] = {}
_MEDIA_INFO_CACHE: dict[str, dict] = {}


def size_bucket(width: int) -> str:
    return "w_le_200" if width <= 200 else "w_200_400" if width < 400 else "w_gt_400"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _anchor_frames(anchor):
    """Return ``(output_frame, roi_frame, source_frame)`` as ints, or three ``None``."""
    if not isinstance(anchor, dict):
        return None, None, None
    values = [anchor.get(key) for key in ("output_frame", "roi_frame", "source_frame")]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        return None, None, None
    return values[0], values[1], values[2]


def _sha256_or_none(value) -> str | None:
    return value if isinstance(value, str) and SHA256.fullmatch(value) else None


def _verdict_id(replay: dict, receipt=None) -> str:
    """Verified verdicts always start with ``replay@``; unverified ones are written "unverified"."""
    for value in (receipt, replay.get("receipt_sha256"), replay.get("source_receipt_sha256")):
        if isinstance(value, str) and SHA256.fullmatch(value):
            return f"replay@{value[:12]}"
    return f"replay@no-receipt:{replay.get('status')}"


def _evidence_sha256(replay: dict, manifest_sha256=None) -> str | None:
    """Prefer the replay receipt, then the source receipt, then the whole manifest bytes."""
    for value in (replay.get("receipt_sha256"), replay.get("source_receipt_sha256"), manifest_sha256):
        if isinstance(value, str) and SHA256.fullmatch(value):
            return value
    return None


def _source_record_usable(evidence) -> bool:
    """c1：来源在 ``sources[]`` 里有一条可用的逐帧保持 replay 声明。"""
    return (isinstance(evidence, dict) and evidence.get("found") is True
            and evidence.get("status") == VERIFIED_REPLAY and evidence.get("mapping") == SOURCE_MAPPING)


def _source_decoded_counts_equal(evidence) -> bool:
    """c2：L0 与 L1 的实解码帧数都是正整数且相等；缺任一边都不算通过。"""
    if not isinstance(evidence, dict):
        return False
    l0, l1 = _positive_int(evidence.get("l0_decoded")), _positive_int(evidence.get("l1_decoded"))
    return l0 is not None and l0 == l1


def _unverified_lineage(reason, checked_at=None, explicit_pairs=(False, False, False),
                        source_replay=(False, False, False), failed=()) -> dict:
    """Unverified admits two empty indices, one non-empty reason and the token it stopped at."""
    return {"clip_frame_index": None, "roi_frame_index": None, "original_source_frame_index": None,
            "clip_to_roi": {"kind": "unverified", "offset": None, "reason": reason},
            "roi_to_original": {"kind": "unverified", "offset": None, "method": "unverified",
                                "reason": reason},
            "verification": {"verdict_id": "unverified", "method": "unverified",
                             "evidence_sha256": None, "checked_at": checked_at,
                             # 条件布尔值独立计算：前置链失败时也如实记录，便于按条件做诊断直方图。
                             "conditions": {"explicit_pairs": list(explicit_pairs),
                                            "source_replay": list(source_replay)},
                             "failed_conditions": list(failed)}}


def _verified_lineage(clip_frame_index, roi_frame_index, source_start, replay, checked_at, method, kind,
                      evidence_sha256, explicit_pairs, source_replay, verdict_receipt=None) -> dict:
    """One passing tier of the three: L1 与 L0 同号，L1→L0 节点写成该级的证据形态。"""
    return {"clip_frame_index": clip_frame_index,
            "roi_frame_index": roi_frame_index,
            # 该级证据已证明 roi_frame == source_frame：L1 与 L0 同序，故原始源帧号等于 ROI 帧号。
            "original_source_frame_index": roi_frame_index,
            # L2→L1 记子视频到 ROI 的加性偏移；L1→L0 记 ROI 到原始源视频的同序证据。
            "clip_to_roi": {"kind": "manifest_replay", "offset": source_start, "reason": None},
            "roi_to_original": {"kind": kind, "offset": 0, "method": method, "reason": None},
            "verification": {"verdict_id": _verdict_id(replay, verdict_receipt), "method": method,
                             "evidence_sha256": evidence_sha256, "checked_at": checked_at,
                             "conditions": {"explicit_pairs": list(explicit_pairs),
                                            "source_replay": list(source_replay)},
                             "failed_conditions": []}}


def derive_lineage(candidate: dict, clip_frame_index: int, manifest_sha256=None, checked_at=None,
                   source_evidence=None) -> dict:
    """Map one L3 clip frame onto the L1 ROI frame and the L0 original frame, or stay unverified.

    命名陷阱（naming trap）：``output.frame_mapping.source_start_frame`` 里的 "source" 指 **ROI
    视频（L1）**——子视频片段的直接来源，不是原始源视频（L0）；replay 的 ``command`` 也确实在
    ROI 视频上 ``select=between(n\\,source_start_frame\\,source_end)`` 切片。此前把这个字段当
    L0 帧号、又没有 ROI 映射可依，才导致 ``roi_frame_index`` 全为 null。正确关系是加性偏移：
    ``roi_frame_index = roi_frame_index_derived = source_start_frame + clip_frame_index``，
    ``output_start_frame`` 是输出序起点，绝不参与 ROI 推导。

    L1→L0（``roi_to_original``）按三级同序证据判定，优先级从高到低：

    1. ``manifest_anchors``：候选自带 anchors 全部良构且 ``roi_frame == source_start_frame +
       output_frame``、``source_frame == roi_frame`` → 显式帧对，``offset`` 为 0。anchors 非空但任一条
       不合法/自相矛盾是**硬失败**，绝不降级到来源级声明。
    2. ``source_replay_mapping``：anchors 为空时，来源级 replay 声明可用（c1：``sources[]`` 记录
       verified 且 mapping 为同序常量）、L0 与 L1 的**实解码**帧数相等（c2）、候选自身 replay 已验
       （c3）→ 来源级 offset 0 映射。
    3. ``unverified``：三级都不成立，两个帧号留 None 并写 ``failed_conditions`` token，不猜。

    ``source_evidence`` 由调用方预解析（``sources[]`` 条目 + 实测 L0/L1 解码帧数）：本函数是纯函数，
    不打开任何媒体，也不读整份清单。
    """
    checked_at = _utc_timestamp() if checked_at is None else checked_at
    # 判定用的布尔条件先独立算出来：前置链中途失败时也要如实记录，便于按条件聚合诊断。
    # c3 与前置链同一校验（前置链失败即 token replay_unverified）；这里重复记录而不是复用结论。
    raw_output = candidate.get("output") if isinstance(candidate, dict) else None
    replay = raw_output.get("frame_preserving_replay") if isinstance(raw_output, dict) else None
    replay = replay if isinstance(replay, dict) else {}
    c1, c2 = _source_record_usable(source_evidence), _source_decoded_counts_equal(source_evidence)
    c3 = replay.get("status") == VERIFIED_REPLAY
    source_replay = [c1, c2, c3]
    explicit_pairs = [False, False, False]
    output = raw_output
    if not isinstance(output, dict):
        return _unverified_lineage("candidate.output 缺失，读不到 frame_preserving_replay 与 frame_mapping",
                                   checked_at, explicit_pairs, source_replay, ["no_output"])
    if not c3:
        status = replay.get("status") if replay else None
        return _unverified_lineage(
            f"frame_preserving_replay 缺失或 status={status!r} != {VERIFIED_REPLAY}；"
            "没有逐帧保持的重放证据就不推导帧号", checked_at, explicit_pairs, source_replay,
            ["replay_unverified"])
    if isinstance(clip_frame_index, bool) or not isinstance(clip_frame_index, int) or clip_frame_index < 0:
        return _unverified_lineage(f"clip_frame_index {clip_frame_index!r} 不是非负整数", checked_at,
                                   explicit_pairs, source_replay, ["bad_clip_index"])
    mapping = output.get("frame_mapping")
    if not isinstance(mapping, dict):
        return _unverified_lineage("output.frame_mapping 缺失：既没有 anchors，也没有 ROI 帧偏移可用",
                                   checked_at, explicit_pairs, source_replay, ["no_frame_mapping"])
    # 命名陷阱（naming trap）：source_start_frame 的 "source" 是 ROI 视频（L1），不是 L0；
    # 这就是早前 roi_frame_index 全为 null 的原因。这里只把它当 ROI 上的加性偏移用。
    source_start = mapping.get("source_start_frame")
    if isinstance(source_start, bool) or not isinstance(source_start, int) or source_start < 0:
        return _unverified_lineage(f"frame_mapping.source_start_frame {source_start!r} 不是非负整数",
                                   checked_at, explicit_pairs, source_replay, ["bad_source_start"])
    roi_frame_index = source_start + clip_frame_index
    anchors = mapping.get("anchors")
    if anchors is not None and not isinstance(anchors, list):
        # 声明了 anchors 却解析不成数组：同样是无法解析的显式证据，按硬失败处理，不静默降级。
        explicit_pairs = [True, False, False]
        return _unverified_lineage(f"output.frame_mapping.anchors {anchors!r} 不是数组：显式帧对不可解析",
                                   checked_at, explicit_pairs, source_replay, ["anchors_broken"])
    anchor_list = anchors if isinstance(anchors, list) else []
    if anchor_list:
        wellformed = consistent = True
        for anchor in anchor_list:
            anchor_output, anchor_roi, anchor_source = _anchor_frames(anchor)
            if anchor_output is None:
                wellformed = False
                continue
            if anchor_roi != source_start + anchor_output or anchor_source != anchor_roi:
                consistent = False
        explicit_pairs = [True, wellformed, consistent]
        if not (wellformed and consistent):
            return _unverified_lineage(
                f"output.frame_mapping.anchors 非空但条目非法或自相矛盾：source_start_frame {source_start} + "
                "output_frame 必须等于 roi_frame，且 roi_frame 必须等于 source_frame；"
                "anchors 是候选自证的硬证据，矛盾时不得降级到来源级声明",
                checked_at, explicit_pairs, source_replay, ["anchors_broken"])
        # 优先级 1：候选自带 anchors 已证明 roi_frame == source_frame。证据身份优先用候选 replay 的
        # receipt_sha256（该候选的决策 receipt），再退化到整份清单摘要并保留可追溯性。
        return _verified_lineage(clip_frame_index, roi_frame_index, source_start, replay, checked_at,
                                 "manifest_anchors", "explicit_pairs",
                                 _evidence_sha256(replay, manifest_sha256), explicit_pairs, source_replay)
    if c1 and c2:
        # 优先级 2：来源级 replay 声明 + L0/L1 实解码帧数相等 + 候选自身 replay 已验。
        # 证据身份优先用 sources[].frame_preserving_replay.receipt_sha256：那是**来源级决策 receipt**
        # （与候选 replay 的 source_receipt_sha256 同值，逐源可区分）；整份清单的字节摘要只能证明
        # 「看过哪份清单」，定位不到是哪条来源的 replay 决策。receipt 不可用时退化到 manifest_sha256，
        # 让「什么证据支撑了这次映射」仍有可追溯的字节身份。
        receipt = _sha256_or_none(source_evidence.get("receipt_sha256"))
        return _verified_lineage(clip_frame_index, roi_frame_index, source_start, replay, checked_at,
                                 "source_replay_mapping", "offset", receipt or _sha256_or_none(manifest_sha256),
                                 explicit_pairs, source_replay, verdict_receipt=receipt)
    failed = [token for token, ok in (("c1_source_record", c1), ("c2_decoded_frame_counts", c2),
                                      ("c3_candidate_replay", c3)) if not ok]
    return _unverified_lineage(
        "anchors 为空，来源级三条件未同时成立（" + "、".join(failed) +
        "）：没有能定位到该来源的 replay 同序证据，不推导 ROI/原始源帧号",
        checked_at, explicit_pairs, source_replay, failed)


def _tool(name: str) -> str:
    for candidate in filter(None, (shutil.which(name),) + tuple(str(Path(d) / name) for d in FALLBACK_TOOL_DIRS)):
        if Path(candidate).is_file():
            return candidate
    raise InputError(f"{name} not found on PATH nor in {list(FALLBACK_TOOL_DIRS)}")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(value):
    """Parse ffprobe ``num/den`` rates; unusable values become None."""
    num, _, den = value.partition("/") if isinstance(value, str) else ("", "", "")
    return _number(num) / _number(den) if _number(den) and _number(num) is not None else _number(value)


def _positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def decoded_frame_count(path) -> int | None:
    """Count the frames ffprobe can actually decode; ``None`` when probing fails, never raises."""
    key = str(path)
    if key in _FRAME_COUNT_CACHE:
        return _FRAME_COUNT_CACHE[key]
    count = None
    try:
        command = [_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_frames",
                   "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)]
        if (result := subprocess.run(command, capture_output=True, text=True)).returncode == 0:
            streams = (json.loads(result.stdout) or {}).get("streams") or []
            count = _positive_int(int(streams[0]["nb_read_frames"])) if streams else None
    except (InputError, OSError, ValueError, KeyError, IndexError, TypeError):
        count = None
    _FRAME_COUNT_CACHE[key] = count
    return count


def media_info(path) -> dict:
    """Ask ffprobe for the first video stream, then count what really decodes.

    ``container_header`` is the file header ``nb_frames`` (``None`` when absent) and
    ``total_frames`` is the decoded count, falling back to the header when counting fails.
    """
    key = str(path)
    if key in _MEDIA_INFO_CACHE:
        return dict(_MEDIA_INFO_CACHE[key])
    command = [_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format",
               "-of", "json", str(path)]
    if (result := subprocess.run(command, capture_output=True, text=True)).returncode != 0:
        raise InputError(f"ffprobe failed for {path}: {result.stderr.strip()[-300:]}")
    try:
        stream = (probe := json.loads(result.stdout))["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise InputError(f"{path}: unexpected ffprobe output: {exc}") from exc
    fps = _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate"))
    header = stream.get("nb_frames")
    container_header = int(header) if isinstance(header, str) and header.isdigit() else None
    decoded = decoded_frame_count(path)
    total = decoded if isinstance(decoded, int) else container_header
    if total is None:
        duration = _number(stream.get("duration")) or _number((probe.get("format") or {}).get("duration"))
        total = round(duration * fps) if duration and fps else None
    info = {"width": width, "height": height, "fps": fps, "total_frames": total,
            "container_header": container_header}
    _MEDIA_INFO_CACHE[key] = info
    return dict(info)


def _sha256_file(path) -> str | None:
    """Digest a media file in chunks; a missing file has no digest, not a zero digest."""
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _layer_media(role: str, path, declared_sha256) -> dict:
    """One lineage layer: measured bytes/frames next to the digest the manifest declared.

    ``total_frames_source`` 明说这个帧数从哪里来：``decoded`` 才能当实解码计数用；计数失败退回
    文件头时记 ``container_header``，并在 ``frame_count_notes.reason`` 里写 ``count_frames_failed``，
    不得把自己伪装成已计数。
    """
    target = Path(path)
    present = target.is_file()
    info = media_info(target) if present else {}
    decoded = decoded_frame_count(target) if present else None
    container_header = info.get("container_header")
    width = info.get("width")
    counted = isinstance(decoded, int)
    if not counted:
        notes = {"decoded": None, "container_header": container_header, "delta": None,
                 "reason": "count_frames_failed"}
    elif isinstance(container_header, int) and decoded != container_header:
        notes = {"decoded": decoded, "container_header": container_header, "delta": decoded - container_header}
    else:
        notes = None
    return {"role": role, "path": str(target), "sha256": _sha256_file(target),
            "declared_sha256": declared_sha256, "fps": info.get("fps"),
            "total_frames": decoded if counted else container_header,
            "total_frames_source": "decoded" if counted else "container_header",
            "width": width, "height": info.get("height"),
            "size_bucket": size_bucket(width) if isinstance(width, int) and not isinstance(width, bool) else None,
            "size_bucket_source": SIZE_BUCKET_SOURCE, "frame_count_notes": notes}


def _layer_total(media: dict, layer: str):
    entry = media.get(layer)
    total = entry.get("total_frames") if isinstance(entry, dict) else None
    return _positive_int(total)


def _clip_to_roi_offset(frame: dict):
    """Return the additive L2→L1 offset (``roi = clip + offset``) when the frame declares an integer one."""
    mapping = frame.get("frame_index_mapping")
    clip_to_roi = mapping.get("clip_to_roi") if isinstance(mapping, dict) else None
    offset = clip_to_roi.get("offset") if isinstance(clip_to_roi, dict) else None
    return offset if isinstance(offset, int) and not isinstance(offset, bool) else None


def _legacy_mapping_keys(frame: dict) -> list[str]:
    mapping = frame.get("frame_index_mapping") if isinstance(frame, dict) else None
    if not isinstance(mapping, dict):
        return []
    return [key for key in LEGACY_MAPPING_KEYS if key in mapping]


def verify_lineage(record: dict) -> list[str]:
    """Return every reason the four-layer lineage does not hold; an empty list means it passes."""
    if not isinstance(record, dict):
        return ["record must be object"]
    media = record.get("lineage_media")
    if not isinstance(media, dict):
        return ["lineage_media missing: l0/l1/l2 layers are required"]
    reasons: list[str] = []
    schema = record.get("record_schema")
    if schema is not None and schema != RECORD_SCHEMA:
        reasons.append(f"record_schema {schema!r} != {RECORD_SCHEMA!r}: legacy input-record schemas "
                       f"are explicitly rejected (use {list(MAPPING_NODE_KEYS)})")
    # 没有 verification 块就没有证据身份：不得当作「反正没给帧号」而静默通过。
    verification = record.get("verification")
    if not isinstance(verification, dict):
        reasons.append("verification block missing or not an object: no evidence identity to check")
        verification = {}
    method = verification.get("method")
    unverified = method == "unverified"
    if method not in ROI_TO_ORIGINAL_METHODS:
        reasons.append(f"verification.method {method!r} is not one of " + "/".join(ROI_TO_ORIGINAL_METHODS))
    conditions = verification.get("conditions")
    # 证据级别必须自证：manifest_anchors 看 explicit_pairs，source_replay_mapping 看 source_replay。
    if method == "manifest_anchors":
        explicit = conditions.get("explicit_pairs") if isinstance(conditions, dict) else None
        if explicit != [True, True, True]:
            reasons.append(f"verification.conditions.explicit_pairs {explicit!r} != [True, True, True]: "
                           "manifest_anchors claims candidate anchors but the condition is not satisfied")
    elif method == "source_replay_mapping":
        replay_conditions = conditions.get("source_replay") if isinstance(conditions, dict) else None
        if replay_conditions != [True, True, True]:
            reasons.append(f"verification.conditions.source_replay {replay_conditions!r} != [True, True, True]: "
                           "source_replay_mapping claims source-level evidence that is not satisfied")
    if unverified:
        failed = verification.get("failed_conditions")
        if not isinstance(failed, list) or not failed:
            reasons.append("verification.failed_conditions missing or empty: unverified must name why "
                           "the frame indices were not derived")
        elif unknown := [token for token in failed if token not in FAILED_CONDITION_TOKENS]:
            reasons.append(f"verification.failed_conditions {unknown} not in the token vocabulary "
                           f"{list(FAILED_CONDITION_TOKENS)}")
    frames = record.get("frames")
    if not isinstance(frames, list):
        reasons.append("frames must be a list of l3 frame entries")
        frames = []
    elif not frames:
        reasons.append("frames is empty: a record without l3 frames carries no lineage evidence")
    l0_total, l1_total, l2_total = (_layer_total(media, layer) for layer in LAYERS)
    # L1↔L0 同序性的媒体层必要条件：两层帧数必须相等（缺任一层就无从比较）。
    if not unverified and (l0_total is None or l1_total is None or l0_total != l1_total):
        reasons.append(f"lineage_media.l0.total_frames {l0_total} != lineage_media.l1.total_frames {l1_total}: "
                       "roi_frame == source_frame ordering needs equal l0/l1 frame counts")
    for order, frame in enumerate(frames):
        if not isinstance(frame, dict):
            reasons.append(f"frames[{order}] must be object")
            continue
        clip_index = frame.get("clip_frame_index")
        roi_index = frame.get("roi_frame_index")
        source_index = frame.get("original_source_frame_index")
        clip_is_int = isinstance(clip_index, int) and not isinstance(clip_index, bool)
        roi_is_int = isinstance(roi_index, int) and not isinstance(roi_index, bool)
        if not clip_is_int:
            reasons.append(f"frames[{order}].clip_frame_index {clip_index!r} must be an integer")
        elif l2_total is None:
            reasons.append("lineage_media.l2.total_frames missing: clip_frame_index cannot be checked "
                           "against the l2 decoded frames")
        elif not 0 <= clip_index < l2_total:
            reasons.append(f"frames[{order}].clip_frame_index {clip_index} outside l2 decoded frames "
                           f"0..{l2_total - 1}")
        if roi_is_int:
            if l1_total is None:
                reasons.append("lineage_media.l1.total_frames missing: roi_frame_index cannot be checked "
                               "against the l1 frames")
            elif not 0 <= roi_index < l1_total:
                reasons.append(f"frames[{order}].roi_frame_index {roi_index} outside l1 frames 0..{l1_total - 1}")
        if legacy := _legacy_mapping_keys(frame):
            reasons.append(f"frames[{order}].frame_index_mapping contains legacy key(s) {legacy}: "
                           f"{RECORD_SCHEMA} explicitly rejects legacy keys; use {list(MAPPING_NODE_KEYS)}")
        offset = _clip_to_roi_offset(frame)
        if not unverified:
            # N1：verified 时偏移必须可校；非整数（含 "973"/973.0/None/缺块）都算缺失，不得静默通过。
            if offset is None:
                reasons.append(f"frames[{order}].frame_index_mapping.clip_to_roi.offset is not an "
                               "integer (string/float/None/missing): roi_frame_index cannot be verified")
            elif roi_is_int and clip_is_int and roi_index != clip_index + offset:
                reasons.append(f"frames[{order}].roi_frame_index {roi_index} != clip_frame_index {clip_index} + "
                               f"clip_to_roi.offset {offset} (added-increment mapping broken)")
        source_is_int = isinstance(source_index, int) and not isinstance(source_index, bool)
        if unverified:
            if source_is_int:
                reasons.append(f"frames[{order}].original_source_frame_index {source_index} is set while "
                               f"verification.method is {method}")
            if roi_is_int:
                reasons.append(f"frames[{order}].roi_frame_index {roi_index} is set while "
                               f"verification.method is {method}")
        elif not source_is_int:
            reasons.append(f"frames[{order}].original_source_frame_index {source_index!r} must be an integer "
                           f"when verification.method is {method}")
        elif l0_total is None:
            reasons.append("lineage_media.l0.total_frames missing: original_source_frame_index cannot be "
                           "checked against the l0 frames")
        elif not 0 <= source_index < l0_total:
            reasons.append(f"frames[{order}].original_source_frame_index {source_index} outside l0 frames "
                           f"0..{l0_total - 1}")
        reasons.extend(_roi_to_original_reasons(order, frame, unverified, method, roi_is_int, roi_index,
                                                source_is_int, source_index))
    for layer in LAYERS:
        entry = media.get(layer)
        if not isinstance(entry, dict):
            reasons.append(f"lineage_media.{layer} missing")
            continue
        # 帧数必须真的数出来：只有文件头值时不得当已计数用。
        if entry.get("total_frames_source") != "decoded":
            reasons.append(f"lineage_media.{layer}.total_frames_source {entry.get('total_frames_source')!r} "
                           "!= 'decoded': frame count was not decoded, only the container header was read")
        actual, declared = entry.get("sha256"), entry.get("declared_sha256")
        # S1：实测摘要缺失就是通道静默（含 unverified），不得当作已校验。
        if actual is None:
            reasons.append(f"lineage_media.{layer}.sha256 is None: actual media digest missing, {layer} "
                           "digest channel is silent")
            continue
        if declared is None or declared == "":
            if layer == "l2" or not unverified:
                reasons.append(f"lineage_media.{layer}.declared_sha256 missing: {layer} sha256 cannot be "
                               "checked against the manifest digest")
            continue
        if actual != declared:
            reasons.append(f"lineage_media.{layer}.sha256 {actual} != declared_sha256 {declared} "
                           "(manifest digest mismatch)")
    reasons.extend(_digest_identity_reasons(record, media))
    return reasons


def _roi_to_original_reasons(order, frame, unverified, method, roi_is_int, roi_index, source_is_int,
                             source_index) -> list[str]:
    """L1→L0 节点自证：verified 时 kind/offset/method/同号必须成立，unverified 时不得挂已验形态。"""
    mapping = frame.get("frame_index_mapping")
    node = mapping.get("roi_to_original") if isinstance(mapping, dict) else None
    label = f"frames[{order}].frame_index_mapping.roi_to_original"
    if unverified:
        # 四项守卫按 kind → method → offset → reason 的顺序全部进 reasons，不早退：
        # 一条记录可能同时挂错形态、写错 method、偷带 offset，只报第一条会遮住其余证据级别矛盾。
        reasons = []
        kind = node.get("kind") if isinstance(node, dict) else None
        if not isinstance(node, dict) or kind != "unverified":
            reasons.append(f"{label}.kind {kind!r} != 'unverified': unverified records must not carry a "
                           f"verified-shape L1→L0 node (kind {kind!r})")
        if isinstance(node, dict):
            node_method = node.get("method")
            if node_method != "unverified":
                reasons.append(f"{label}.method {node_method!r} != 'unverified': an unverified record must "
                               f"not name a verified evidence level")
            node_offset = node.get("offset")
            if isinstance(node_offset, bool) or node_offset not in (0, None):
                reasons.append(f"{label}.offset {node_offset!r} not in (0, None): an unverified node must "
                               f"not carry a non-zero L1→L0 offset")
            reason = node.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                reasons.append(f"{label}.reason is blank: unverified must say why there is no L1→L0 evidence")
        return reasons
    if not isinstance(node, dict):
        return [f"{label} missing: the L1→L0 evidence node is required when verification.method is {method}"]
    reasons = []
    kind = node.get("kind")
    # 证据形态必须与证据级别配对：manifest_anchors 只能给显式帧对，source_replay_mapping 只能给偏移。
    expected_kind = {"manifest_anchors": "explicit_pairs", "source_replay_mapping": "offset"}.get(method)
    if kind not in ("explicit_pairs", "offset"):
        reasons.append(f"{label}.kind {kind!r} is not one of explicit_pairs/offset")
    elif expected_kind is not None and kind != expected_kind:
        reasons.append(f"{label}.kind {kind!r} contradicts verification.method {method!r} "
                       f"(that method needs kind {expected_kind!r})")
    node_method = node.get("method")
    if node_method != method:
        reasons.append(f"{label}.method {node_method!r} != verification.method {method!r}: the L1→L0 "
                       "evidence node must name the same evidence level as the record")
    offset = node.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset != 0:
        reasons.append(f"{label}.offset {offset!r} != 0: L1 and L0 must be in the same order "
                       "(a non-zero offset contradicts equal frame indices)")
    if roi_is_int and source_is_int and roi_index != source_index:
        reasons.append(f"frames[{order}].original_source_frame_index {source_index} != roi_frame_index "
                       f"{roi_index}: L1→L0 same-order evidence does not hold")
    return reasons


def _digest_identity_reasons(record: dict, media: dict) -> list[str]:
    """S2: the record's L2 digest must be the same bytes in all three places that name it."""
    record_media = record.get("media")
    if not isinstance(record_media, dict):
        return ["record.media block missing or not an object: the l2 media digest cannot be cross-checked"]
    l2_entry = media.get("l2")
    l2_actual = l2_entry.get("sha256") if isinstance(l2_entry, dict) else None
    reasons = []
    clip_sha256 = record.get("clip_sha256")
    if l2_actual is not None and clip_sha256 != l2_actual:
        reasons.append(f"record.clip_sha256 {clip_sha256!r} != lineage_media.l2.sha256 {l2_actual} "
                       "(record digest disagrees with the measured l2 digest)")
    media_sha256 = record_media.get("sha256")
    if l2_actual is not None and media_sha256 != l2_actual:
        reasons.append(f"record.media.sha256 {media_sha256!r} != lineage_media.l2.sha256 {l2_actual} "
                       "(record media block disagrees with the measured l2 sha256)")
    return reasons


def read_records(path) -> list[dict]:
    """Parse a records JSONL; blank lines are skipped, objects required, legacy v2/keys explicitly rejected."""
    lines = enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1)
    rows = [(number, decode_file(line, f"{path}:{number}")) for number, line in lines if line.strip()]
    if bad := next(((number, row) for number, row in rows if not isinstance(row, dict)), None):
        raise InputError(f"{path}:{bad[0]}: record row must be object")
    for number, row in rows:
        schema = row.get("record_schema")
        if schema is not None and schema != RECORD_SCHEMA:
            raise InputError(
                f"{path}:{number}: record_schema {schema!r} != expected {RECORD_SCHEMA!r}; "
                f"legacy schemas are explicitly rejected (expected mapping keys: {list(MAPPING_NODE_KEYS)})"
            )
        frames = row.get("frames")
        if isinstance(frames, list):
            for order, frame in enumerate(frames):
                if legacy := _legacy_mapping_keys(frame):
                    raise InputError(
                        f"{path}:{number}: frames[{order}].frame_index_mapping contains legacy key(s) {legacy}; "
                        f"{RECORD_SCHEMA} explicitly rejects legacy keys (use {list(MAPPING_NODE_KEYS)})"
                    )
    return [row for _, row in rows]


def _candidates(manifest_obj) -> dict:
    """Index source-manifest candidates by id; duplicates and malformed rows are errors."""
    rows = manifest_obj.get("candidates") if isinstance(manifest_obj, dict) else None
    if not isinstance(rows, list):
        raise InputError("source manifest must contain candidates array")
    by_id = {}
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise InputError(f"source manifest candidate #{number} must be object")
        require_text(row, "candidate_id", f"source manifest candidate #{number}")
        if row["candidate_id"] in by_id:
            raise InputError(f"duplicate candidate_id in source manifest: {row['candidate_id']} (candidate #{number})")
        by_id[row["candidate_id"]] = row
    return by_id


def _extract_frames(clip: Path, indices: list[int], target: Path) -> tuple[list[float], list[str]]:
    target.mkdir(parents=True, exist_ok=False)
    selector = "+".join(f"eq(n\\,{index})" for index in indices)
    command = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "info", "-i", str(clip), "-vf",
               f"select='{selector}',showinfo", "-vsync", "0", str(target / "frame_%03d.png")]
    if (result := subprocess.run(command, capture_output=True, text=True)).returncode != 0:
        raise InputError(f"ffmpeg failed for {clip}: {result.stderr.strip()[-300:]}")
    times = [float(m.group(3)) for line in result.stderr.splitlines() for m in (SHOWINFO.search(line),) if m]
    names = sorted(path.name for path in target.glob("frame_*.png"))
    if not len(times) == len(names) == len(indices):
        raise InputError(f"{clip}: got {len(names)} images / {len(times)} timestamps for {indices}")
    return times, names


def extract_record(candidate, profiles, out_dir, clips_per_record=3, manifest_sha256=None,
                   source_evidence=None) -> dict:
    """Probe one clip, decode through the last selected frame and keep only those PNGs.

    ``source_evidence`` 是该候选 ``source_video_id`` 对应的来源级 replay 证据（``sources[]`` 声明 +
    实测 L0/L1 解码帧数），由调用方预解析后传入；不传就只有 anchors 一级可用。
    """
    require_text(candidate, "candidate_id", "candidate")
    cid = candidate["candidate_id"]
    output = candidate.get("output")
    if not isinstance(output, dict):
        raise InputError(f"{cid}: candidate.output must be object")
    digest = output.get("sha256") if isinstance(output.get("sha256"), str) else ""
    if not SHA256.fullmatch(digest):
        raise InputError(f"{cid}: output.sha256 must be lowercase SHA256")
    require_text(candidate, "output_path", cid)
    require_text(candidate, "source_video_id", cid)
    source_id = candidate["source_video_id"]
    clip = Path(profiles["sub_video_videos"]) / Path(candidate["output_path"]).name
    actual = _sha256_file(clip)
    if actual != digest:
        raise InputError(f"{cid}: output.sha256 {digest} != media sha256 {actual} (clip {clip})")
    if manifest_sha256 is None:
        manifest_sha256 = hashlib.sha256(Path(profiles["sub_video_manifest"]).read_bytes()).hexdigest()
    replay = output.get("frame_preserving_replay")
    replay = replay if isinstance(replay, dict) else {}
    mapping = output.get("frame_mapping")
    mapping = mapping if isinstance(mapping, dict) else {}
    # L0/L1 的声明摘要按 replay 字段取：source_sha256 是原始源视频，roi_sha256 是 ROI 视频。
    lineage_media = {
        "l0": _layer_media("source_video", Path(profiles["source_videos"]) / f"{source_id}.mp4",
                           replay.get("source_sha256")),
        "l1": _layer_media("roi_video", Path(profiles["roi_videos"]) / f"{source_id}.mp4",
                           replay.get("roi_sha256")),
        "l2": _layer_media("sub_video", clip, digest),
    }
    media = media_info(clip)
    bucket, total = size_bucket(media["width"]), lineage_media["l2"]["total_frames"]
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (clips_per_record, total)):
        raise InputError(f"{cid}: clips_per_record={clips_per_record!r} / total_frames={total!r} must be positive integers")
    count = min(clips_per_record, total)
    indices = [0] if count == 1 else [round(i * (total - 1) / (count - 1)) for i in range(count)]
    times, names = _extract_frames(clip, indices, Path(out_dir) / cid)
    checked_at = _utc_timestamp()
    anchors = mapping.get("anchors") if isinstance(mapping.get("anchors"), list) else []
    anchor_by_output = {}
    for anchor in anchors:
        anchor_output = _anchor_frames(anchor)[0]
        if anchor_output is not None:
            anchor_by_output.setdefault(anchor_output, anchor)
    frames = []
    for order, (clip_frame_index, pts_seconds, image) in enumerate(zip(indices, times, names)):
        lineage = derive_lineage(candidate, clip_frame_index, manifest_sha256=manifest_sha256,
                                 checked_at=checked_at, source_evidence=source_evidence)
        frames.append({"display_order": order, "decode_order": order,
                       "clip_frame_index": clip_frame_index,
                       "roi_frame_index": lineage["roi_frame_index"],
                       "original_source_frame_index": lineage["original_source_frame_index"],
                       "is_anchor": clip_frame_index in anchor_by_output,
                       "anchor_ref": anchor_by_output.get(clip_frame_index), "media_role": "clip",
                       "image": image, "pts_seconds": pts_seconds,
                       "frame_index_mapping": {"clip_to_roi": lineage["clip_to_roi"],
                                               "clip_to_model_input": dict(CLIP_TO_MODEL_INPUT),
                                               "roi_to_original": lineage["roi_to_original"]}})
    # 候选级证据：verdict_id/method/evidence_sha256/checked_at 只取决于候选，不取决于具体帧号。
    candidate_lineage = derive_lineage(candidate, 0, manifest_sha256=manifest_sha256,
                                       checked_at=checked_at, source_evidence=source_evidence)
    verification = candidate_lineage["verification"]
    identity = {"record_schema": RECORD_SCHEMA, "clip_sha256": digest, "media_sha256": digest, "size_bucket": bucket,
                "selection_rule": "evenly_spaced_inclusive", "clips_per_record": clips_per_record,
                "clip_frame_indices": indices,
                "roi_frame_indices": [frame["roi_frame_index"] for frame in frames],
                "original_source_frame_indices": [frame["original_source_frame_index"] for frame in frames],
                "lineage_verification": {key: verification[key] for key in ("method", "verdict_id", "evidence_sha256")},
                # 证据级别本身也是输入身份：L1→L0 由 anchors 换成来源级 replay 必须换 input_id。
                "roi_to_original_kind": candidate_lineage["roi_to_original"]["kind"],
                # L0/L1 实测摘要也是模型输入身份：上游字节变了必须换 input_id（checked_at 等易变值不入哈希）。
                "lineage_sha256": {layer: lineage_media[layer]["sha256"] for layer in LAYERS},
                **{key: media[key] for key in ("width", "total_frames", "fps")}}
    input_id = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    record = {"record_schema": RECORD_SCHEMA, "candidate_id": cid, "clip_sha256": digest,
              "manifest_sha256": manifest_sha256, "input_id": f"input@sha256:{input_id}",
              "frame_count_convention": "decoded", "verification": verification, "lineage_check": "pass",
              "media": {"role": "clip", "path": str(clip), "sha256": digest, "height": media["height"],
                        "size_bucket": bucket, "size_bucket_source": SIZE_BUCKET_SOURCE,
                        **{key: media[key] for key in ("fps", "total_frames", "width")}},
              "lineage_media": lineage_media, "frames": frames}
    if failures := verify_lineage(record):
        raise InputError(f"{cid}: lineage check failed: {' | '.join(failures)}")
    return record


def _export_single_frame(media_path, index: int, target: Path) -> str | None:
    """Export exactly one decoded frame; return a failure reason instead of raising."""
    command = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media_path),
               "-vf", f"select=eq(n\\,{index})", "-vsync", "0", "-frames:v", "1", str(target)]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        return f"ffmpeg unusable: {exc}"
    if result.returncode != 0 or not target.is_file():
        return result.stderr.strip()[-200:] or "ffmpeg wrote no frame"
    return None


def export_lineage_png(records, out_dir) -> tuple[int, int]:
    """Dump L0/L1/L2/L3 evidence per sampled frame; a frame that cannot be exported is a skip row."""
    exported = skipped = 0
    for record in records:
        cid = record["candidate_id"]
        target = Path(out_dir) / "lineage" / cid
        target.mkdir(parents=True, exist_ok=True)
        skips = []
        for frame in record["frames"]:
            for layer, index, tag in (("l0", frame["roi_frame_index"], "L0"),
                                      ("l1", frame["roi_frame_index"], "L1"),
                                      ("l2", frame["clip_frame_index"], "L2")):
                if isinstance(index, bool) or not isinstance(index, int):
                    skips.append({"candidate_id": cid, "layer": layer, "index": index,
                                  "reason": f"{layer} frame index unavailable; nothing to export"})
                    skipped += 1
                    continue
                name = f"{cid}_{tag}_f{index}.png"
                if reason := _export_single_frame(record["lineage_media"][layer]["path"], index, target / name):
                    skips.append({"candidate_id": cid, "layer": layer, "index": index, "reason": reason})
                    skipped += 1
                    continue
                exported += 1
            shutil.copyfile(Path(out_dir) / cid / frame["image"],
                            target / f"{cid}_L3_order{frame['display_order']}.png")
            exported += 1
        if skips:
            with (target / "skips.jsonl").open("w", encoding="utf-8") as stream:
                for row in skips:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return exported, skipped


def lineage_summary(rows) -> dict:
    """Aggregate one batch of candidates into the coverage signal the caller must report.

    入参每行 ``{"candidate_id", "method", "failed_conditions"}``。``warning`` 只在 unverified 占比
    **超过** 5% 时为真（恰好 5% 仍可接受，0 条记录不告警也不除零）。
    """
    counts = {method: 0 for method in ROI_TO_ORIGINAL_METHODS}
    reasons: dict[str, int] = {}
    for row in rows if isinstance(rows, list) else []:
        row = row if isinstance(row, dict) else {}
        method = row.get("method")
        # 未知 method 不得当成已验：归入 unverified，保证三档计数之和等于 total。
        method = method if method in counts else "unverified"
        counts[method] += 1
        failed = row.get("failed_conditions") if method == "unverified" else None
        for token in failed if isinstance(failed, list) else []:
            # 一行多个 token 就各计一次：直方图统计的是「有多少行败在这个条件上」。
            if isinstance(token, str):
                reasons[token] = reasons.get(token, 0) + 1
    total = sum(counts.values())
    unverified = counts["unverified"]
    warning = total > 0 and unverified / total > COVERAGE_WARNING_RATIO
    return {"schema": SUMMARY_SCHEMA, "total": total, "verified_by_method": counts,
            "ratios": {method: (count / total if total else 0.0) for method, count in counts.items()},
            "unverified_reasons": reasons,
            "frame_index_coverage": (total - unverified) / total if total else 0.0,
            "warning": warning,
            "warning_text": (f"{COVERAGE_WARNING_TEXT}：{unverified}/{total} 条候选没有逐帧同序证据"
                             if warning else None)}


def source_evidence_index(manifest_obj) -> dict:
    """Index ``sources[].frame_preserving_replay`` by video id; no media is opened here."""
    index: dict[str, dict] = {}
    sources = manifest_obj.get("sources") if isinstance(manifest_obj, dict) else None
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict) or not isinstance(source.get("video_id"), str):
            continue
        replay = source.get("frame_preserving_replay")
        replay = replay if isinstance(replay, dict) else {}
        index[source["video_id"]] = {"source_video_id": source["video_id"], "found": True,
                                     "status": replay.get("status"), "mapping": replay.get("mapping"),
                                     "proof_type": replay.get("proof_type"),
                                     "receipt_sha256": replay.get("receipt_sha256"),
                                     "l0_decoded": None, "l1_decoded": None}
    return index


def add_source_decoded_counts(evidence, profiles, source_ids=None) -> dict:
    """Fill measured L0/L1 decoded frame counts once per source video, never per candidate.

    用实测 ``decoded_frame_count`` 而不是清单里的 ``metadata_frame_count``/``frame_count``：实测发现
    110 条源里有 1 条的清单帧数与 ROI 实解码帧数不等，清单值会把这个差异抹平。

    ``source_ids=None`` 探测全部来源（``--coverage-scan`` 的批级口径）；传集合时只探测该集合，其余条目
    的 ``l0_decoded``/``l1_decoded`` 保持缺省（``None``），使 c2 判不成立——不得伪造成相等。
    """
    for video_id, entry in evidence.items():
        if source_ids is not None and video_id not in source_ids:
            continue
        entry["l0_decoded"] = decoded_frame_count(Path(profiles["source_videos"]) / f"{video_id}.mp4")
        entry["l1_decoded"] = decoded_frame_count(Path(profiles["roi_videos"]) / f"{video_id}.mp4")
    return evidence


def _coverage_scan(by_id, selected, evidence, manifest_sha256) -> dict:
    """Per-candidate verdicts for the whole batch without extracting a single frame."""
    rows = []
    for cid in selected:
        candidate = by_id[cid]
        lineage = derive_lineage(candidate, 0, manifest_sha256=manifest_sha256,
                                 source_evidence=evidence.get(candidate.get("source_video_id")))
        rows.append({"candidate_id": cid, "source_video_id": candidate.get("source_video_id"),
                     "method": lineage["verification"]["method"],
                     "roi_frame_index": lineage["roi_frame_index"],
                     "original_source_frame_index": lineage["original_source_frame_index"],
                     "failed_conditions": lineage["verification"]["failed_conditions"]})
    return {**lineage_summary(rows), "candidates": rows}


def _report_coverage(summary: dict, target) -> None:
    """Print the batch coverage signal; a warning never changes the exit code."""
    counts = summary["verified_by_method"]
    print(f"Lineage coverage ({summary['schema']}): {summary['total']} candidates -> "
          f"manifest_anchors={counts['manifest_anchors']} "
          f"source_replay_mapping={counts['source_replay_mapping']} unverified={counts['unverified']}; "
          f"frame_index_coverage={summary['frame_index_coverage']:.4f}; summary in {target}")
    if summary["unverified_reasons"]:
        histogram = ", ".join(f"{token}={count}" for token, count in
                               sorted(summary["unverified_reasons"].items(), key=lambda item: (-item[1], item[0])))
        print(f"Unverified failed_conditions: {histogram}")
    if summary["warning"]:
        print(f"!!! {summary['warning_text']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="mac", help="Path profile name from config/eval_paths.json")
    parser.add_argument("--manifest", help="Source sub-video manifest; defaults to the profile value")
    parser.add_argument("--candidate-ids", help="JSON array of candidate IDs in the wanted order")
    parser.add_argument("--output", required=True,
                        help="New records JSONL (extract mode) or lineage summary JSON (--coverage-scan)")
    parser.add_argument("--out-dir", help="New directory for extracted frame images; required unless --coverage-scan")
    parser.add_argument("--clips-per-record", type=int, default=3)
    parser.add_argument("--export-lineage-png", action="store_true",
                        help="Also dump L0/L1/L2/L3 PNG per sampled frame under <out-dir>/lineage/<candidate_id>/")
    parser.add_argument("--coverage-scan", action="store_true",
                        help="Only parse the manifest and count decoded frames: no extraction, no PNG; "
                             "write the batch coverage summary to --output")
    args = parser.parse_args(argv)
    try:
        profiles = paths.load_profile(args.profile)
        manifest_path = Path(args.manifest) if args.manifest else profiles["sub_video_manifest"]
        manifest_obj = decode_file((raw := manifest_path.read_bytes()).decode("utf-8"), str(manifest_path))
        by_id = _candidates(manifest_obj)
        selected = list(by_id)
        if args.candidate_ids:
            selected = decode_file(Path(args.candidate_ids).read_text(encoding="utf-8"), args.candidate_ids)
            if not isinstance(selected, list) or not selected:
                raise InputError("candidate IDs must be a nonempty JSON array")
            if missing := [cid for cid in selected if cid not in by_id]:
                raise InputError(f"candidate_id not found in source manifest: {missing}")
        manifest_sha256 = hashlib.sha256(raw).hexdigest()
        index = source_evidence_index(manifest_obj)
        if args.coverage_scan:
            # 批级口径：探测全部来源，才能给整批的覆盖率结论。
            payload = _coverage_scan(by_id, selected, add_source_decoded_counts(index, profiles),
                                     manifest_sha256)
            with Path(args.output).open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            _report_coverage(payload, args.output)
            return 0
        if not args.out_dir:
            raise InputError("--out-dir is required unless --coverage-scan is used")
        # 抽帧模式只探测本次选中的候选用到的来源：每源一次，不多付无关源的全解码。
        evidence = add_source_decoded_counts(index, profiles,
                                             {by_id[cid].get("source_video_id") for cid in selected})
        Path(args.out_dir).mkdir(parents=True, exist_ok=False)
        records = [extract_record(by_id[cid], profiles, args.out_dir, args.clips_per_record,
                                  manifest_sha256=manifest_sha256,
                                  source_evidence=evidence.get(by_id[cid].get("source_video_id")))
                   for cid in selected]
        with Path(args.output).open("x", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Wrote {len(records)} records to {args.output}; images under {args.out_dir}")
        summary = lineage_summary([{"candidate_id": record["candidate_id"],
                                    "method": record["verification"]["method"],
                                    "failed_conditions": record["verification"]["failed_conditions"]}
                                   for record in records])
        summary_path = Path(args.out_dir) / "lineage_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _report_coverage(summary, summary_path)
        if args.export_lineage_png:
            exported, skipped = export_lineage_png(records, args.out_dir)
            print(f"Lineage PNGs: {exported} exported, {skipped} skipped under "
                  f"{Path(args.out_dir) / 'lineage'}")
        return 0
    except (InputError, OSError, UnicodeError, paths.EvalPathError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
