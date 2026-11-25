"""Red-phase tests for the frozen `frames` four-layer lineage contract.

L0 原始源视频 / L1 ROI 视频 / L2 子视频 / L3 模型输入帧。Only pure helpers,
`verify_lineage`, `lineage_summary` and the record/CLI shape of `extract_record`/`main` are
exercised: ffprobe/ffmpeg and any real media stay out of this file (monkeypatched). Scratch
files live in pytest's `tmp_path`.

三级同序证据（优先级从高到低）：`manifest_anchors`（候选 anchors 自证）→
`source_replay_mapping`（来源级 replay 声明 + L0/L1 实解码帧数相等 + 候选自身 replay 已验）→
`unverified`。anchors 非空但自相矛盾是硬失败，绝不降级到来源级声明。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from script.five_label_eval import frames
from script.five_label_eval.score import InputError

VERIFIED_REPLAY = "verified_frame_preserving_replay"
LINEAGE_LAYERS = ("l0", "l1", "l2")
MEDIA_FIELDS = ("role", "path", "sha256", "declared_sha256", "fps", "total_frames", "total_frames_source",
                "width", "height", "size_bucket", "size_bucket_source", "frame_count_notes")
FRAME_FIELDS = ("display_order", "decode_order", "clip_frame_index", "roi_frame_index",
                "original_source_frame_index", "is_anchor", "anchor_ref", "media_role", "image",
                "pts_seconds", "frame_index_mapping")
MAPPING_FIELDS = ("kind", "offset", "reason")
LINEAGE_RESULT_FIELDS = ("clip_frame_index", "roi_frame_index", "original_source_frame_index",
                         "clip_to_roi", "roi_to_original", "verification")
VERIFICATION_FIELDS = ("verdict_id", "method", "evidence_sha256", "checked_at",
                       "conditions", "failed_conditions")
ROI_TO_ORIGINAL_FIELDS = ("kind", "offset", "method", "reason")
SIZE_BUCKET_SOURCE = "width_rule_le200_lt400"
MISSING = object()  # 参数化用哨兵：区分「键不存在」与「值为 None」

# 清单真实取值（data/sub_video/manifest.json 的 110 个 sources 全部如此）。
SOURCE_MAPPING = "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"
SOURCE_PROOF_TYPE = "exact_static_spatial_pipeline_replay"
SOURCE_RECEIPT = "9" * 64
# 契约定稿的 failed_conditions token 取值域：决策与直方图都按它聚合。
FAILED_CONDITION_TOKENS = {"no_output", "replay_unverified", "bad_clip_index", "no_frame_mapping",
                           "bad_source_start", "anchors_broken", "c1_source_record",
                           "c2_decoded_frame_counts", "c3_candidate_replay"}
SUMMARY_SCHEMA = "five-label-lineage-summary/1"


def anchors_for(output_frames, source_start):
    """Replay anchors consistent with the offset: roi/source frame == source_start + output_frame."""
    return [{"output_frame": frame, "roi_frame": source_start + frame, "source_frame": source_start + frame}
            for frame in output_frames]


def _set(container, path, value):
    keys = path.split("__")
    target = container
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


def _drop(container, path):
    keys = path.split("__")
    target = container
    for key in keys[:-1]:
        target = target[key]
    del target[keys[-1]]


def candidate(drop=(), **overrides):
    """Synthetic candidate shaped like the real manifest row ``video_0001_fracture_01``."""
    base = {
        "candidate_id": "c00",
        "source_video_id": "video_0001",
        "output_path": "data/sub_video/c00.mp4",
        "output": {
            "sha256": "a" * 64,
            "media": {"width": 320, "height": 240, "fps": 30.0, "total_frames": 240},
            "frame_mapping": {"anchors": anchors_for((191, 192), 973),
                              "output_start_frame": 0, "source_start_frame": 973},
            "frame_preserving_replay": {
                "status": VERIFIED_REPLAY,
                "anchors": anchors_for((191, 192), 973),
                "output_sha256": "a" * 64,
                "roi_sha256": "b" * 64,
                "source_sha256": "c" * 64,
                "receipt_sha256": "d" * 64,
                "source_receipt_sha256": "e" * 64,
                "decoded_frame_count": 240,
            },
        },
    }
    for path, value in overrides.items():
        _set(base, path, value)
    for path in drop:
        _drop(base, path)
    return base


def source_evidence(video_id="video_0001", receipt=SOURCE_RECEIPT, l0_decoded=1213, l1_decoded=1213,
                    **overrides):
    """调用方预解析好的来源级证据（sources[] + 实测解码帧数），derive_lineage 只读不探测。"""
    evidence = {"source_video_id": video_id, "found": True, "status": VERIFIED_REPLAY,
                "mapping": SOURCE_MAPPING, "proof_type": SOURCE_PROOF_TYPE,
                "receipt_sha256": receipt, "l0_decoded": l0_decoded, "l1_decoded": l1_decoded}
    evidence.update(overrides)
    return evidence


def empty_anchor_candidate(source_start=973, **overrides):
    """真实语料里 1,042/1,621 条候选的形态：anchors == []，但 source_start_frame 仍在。"""
    return candidate(output__frame_mapping={"anchors": [], "output_start_frame": 0,
                                            "source_start_frame": source_start}, **overrides)


def anchored_candidate(anchors, source_start=973, **overrides):
    """带显式 anchors 的候选（优先级 1 的输入）。"""
    return candidate(output__frame_mapping={"anchors": anchors, "output_start_frame": 0,
                                            "source_start_frame": source_start}, **overrides)


def assert_unverified(lineage):
    """Unverified must admit two empty indices and say why; never guess a frame number."""
    assert lineage["roi_frame_index"] is None
    assert lineage["original_source_frame_index"] is None
    assert lineage["clip_to_roi"]["kind"] == "unverified"
    assert lineage["clip_to_roi"]["offset"] is None
    reason = lineage["clip_to_roi"]["reason"]
    assert isinstance(reason, str) and reason.strip()
    assert lineage["verification"]["method"] == "unverified"
    # L1→L0 节点必须显式 unverified + 非空 reason，且 failed_conditions 非空。
    assert lineage["roi_to_original"]["kind"] == "unverified"
    reason = lineage["roi_to_original"]["reason"]
    assert isinstance(reason, str) and reason.strip()
    failed = lineage["verification"]["failed_conditions"]
    assert isinstance(failed, list) and failed
    assert set(failed) <= FAILED_CONDITION_TOKENS, f"unknown token in {failed}"


@pytest.mark.parametrize(
    "width,bucket",
    [
        (199, "w_le_200"),
        (200, "w_le_200"),
        (201, "w_200_400"),
        (399, "w_200_400"),
        (400, "w_gt_400"),
        (401, "w_gt_400"),
    ],
)
def test_size_bucket_should_follow_inclusive_lower_bounds(width, bucket):
    assert frames.size_bucket(width) == bucket


def test_derive_lineage_should_derive_roi_and_source_index_when_replay_verified():
    """真实语料：source_start_frame=973 + clip 191 == 1164，ROI 与原始源同号（已绑定 verification）。"""
    lineage = frames.derive_lineage(candidate(), 191)

    assert lineage["clip_frame_index"] == 191
    assert lineage["roi_frame_index"] == 1164
    assert lineage["original_source_frame_index"] == 1164
    assert lineage["clip_to_roi"]["kind"] in {"manifest_replay", "manifest_anchors"}
    assert lineage["clip_to_roi"]["offset"] == 973
    # 默认候选带合法 anchors：落优先级 1，词表里再也没有旧的 "manifest_replay"。
    assert lineage["verification"]["method"] == "manifest_anchors"


def test_derive_lineage_should_return_contract_shape_when_replay_verified():
    lineage = frames.derive_lineage(candidate(), 191)

    assert set(LINEAGE_RESULT_FIELDS) <= set(lineage)
    assert set(MAPPING_FIELDS) <= set(lineage["clip_to_roi"])
    assert set(ROI_TO_ORIGINAL_FIELDS) <= set(lineage["roi_to_original"])
    assert set(VERIFICATION_FIELDS) <= set(lineage["verification"])
    assert isinstance(lineage["roi_to_original"]["method"], str)
    assert isinstance(lineage["verification"]["verdict_id"], str)


def test_derive_lineage_should_ignore_output_start_frame_when_deriving_roi_index():
    """output_start_frame 是输出序起点，不是 ROI 帧号：900 + 7 == 907，不是 100 + 7。"""
    clip = candidate(output__frame_mapping={"anchors": anchors_for((7,), 900),
                                            "output_start_frame": 100,
                                            "source_start_frame": 900})

    lineage = frames.derive_lineage(clip, 7)

    assert lineage["roi_frame_index"] == 907
    assert lineage["original_source_frame_index"] == 907
    assert lineage["clip_to_roi"]["offset"] == 900


@pytest.mark.parametrize("build", [
    pytest.param(lambda: candidate(drop=("output__frame_preserving_replay",)), id="replay-field-missing"),
    pytest.param(lambda: candidate(output__frame_preserving_replay=None), id="replay-null"),
    pytest.param(lambda: candidate(output__frame_preserving_replay={"status": "unverified_frame_preserving_replay"}),
                 id="replay-status-unverified"),
    pytest.param(lambda: candidate(output__frame_preserving_replay={"status": "verified"}),
                 id="replay-status-generic-verified"),
    pytest.param(lambda: candidate(output__frame_preserving_replay={}), id="replay-status-missing"),
    pytest.param(lambda: candidate(drop=("output",)), id="output-missing"),
])
def test_derive_lineage_should_return_unverified_when_replay_proof_not_verified(build):
    lineage = frames.derive_lineage(build(), 191)

    assert_unverified(lineage)


@pytest.mark.parametrize("build", [
    pytest.param(lambda: candidate(drop=("output__frame_mapping__anchors",)), id="anchors-field-missing"),
    pytest.param(lambda: candidate(output__frame_mapping={"anchors": [], "output_start_frame": 0,
                                                         "source_start_frame": 973}), id="anchors-empty"),
    pytest.param(lambda: candidate(drop=("output__frame_mapping",)), id="frame-mapping-missing"),
])
def test_derive_lineage_should_return_unverified_when_anchors_absent(build):
    """没有 anchors 就没有同序性证据，offset 再合法也不得推导。"""
    lineage = frames.derive_lineage(build(), 191)

    assert_unverified(lineage)


@pytest.mark.parametrize("clip_frame_index", [-1, -60, 1.5, "191", None, True])
def test_derive_lineage_should_return_unverified_when_clip_frame_index_invalid(clip_frame_index):
    lineage = frames.derive_lineage(candidate(), clip_frame_index)

    assert_unverified(lineage)


@pytest.mark.parametrize("build", [
    pytest.param(lambda: candidate(drop=("output__frame_mapping__source_start_frame",)),
                 id="source-start-missing"),
    pytest.param(lambda: candidate(output__frame_mapping={"anchors": anchors_for((191,), 0),
                                                         "output_start_frame": 0,
                                                         "source_start_frame": None}), id="source-start-null"),
    pytest.param(lambda: candidate(output__frame_mapping={"anchors": anchors_for((191,), 0),
                                                         "output_start_frame": 0,
                                                         "source_start_frame": -5}), id="source-start-negative"),
    pytest.param(lambda: candidate(output__frame_mapping={"anchors": anchors_for((191,), 0),
                                                         "output_start_frame": 0,
                                                         "source_start_frame": 973.5}),
                 id="source-start-float"),
    pytest.param(lambda: candidate(output__frame_mapping={"anchors": anchors_for((191,), 0),
                                                         "output_start_frame": 0,
                                                         "source_start_frame": True}),
                 id="source-start-bool"),
])
def test_derive_lineage_should_return_unverified_when_source_start_frame_invalid(build):
    lineage = frames.derive_lineage(build(), 191)

    assert_unverified(lineage)


def test_derive_lineage_should_return_unverified_when_anchors_contradict_offset():
    """anchors 自相矛盾（191 + 973 != 9999）时不得猜，必须 unverified。"""
    clip = candidate(output__frame_mapping={
        "anchors": [{"output_frame": 191, "roi_frame": 9999, "source_frame": 9999}],
        "output_start_frame": 0,
        "source_start_frame": 973,
    })

    lineage = frames.derive_lineage(clip, 191)

    assert_unverified(lineage)


def assert_verified_tier(lineage, method, kind):
    """三级里某一级通过的公共断言：两帧号同号，且 L1→L0 节点写成该级的证据形态。"""
    assert lineage["verification"]["method"] == method
    assert lineage["roi_to_original"]["kind"] == kind
    assert lineage["roi_to_original"]["method"] == method
    assert lineage["roi_to_original"]["offset"] == 0
    assert lineage["roi_to_original"]["reason"] is None
    assert lineage["roi_frame_index"] == lineage["original_source_frame_index"]
    assert lineage["verification"]["failed_conditions"] == []


def test_derive_lineage_should_use_manifest_anchors_when_anchors_are_consistent():
    """优先级 1：anchors 全部良构且 roi==source 时用 explicit_pairs，offset 为 0。"""
    lineage = frames.derive_lineage(candidate(), 191)

    assert_verified_tier(lineage, "manifest_anchors", "explicit_pairs")
    assert lineage["roi_frame_index"] == 973 + 191
    assert lineage["verification"]["conditions"] == {"explicit_pairs": [True, True, True],
                                                      "source_replay": [False, False, True]}
    # 候选自己声明的 receipt 是优先级 1 的证据身份。
    assert lineage["verification"]["evidence_sha256"] == "d" * 64


def test_derive_lineage_should_prefer_manifest_anchors_over_source_replay_mapping():
    """优先级 1 高于优先级 2：即使来源级三条件全真，有 anchors 就记 manifest_anchors。"""
    lineage = frames.derive_lineage(candidate(), 191, source_evidence=source_evidence())

    assert_verified_tier(lineage, "manifest_anchors", "explicit_pairs")
    assert lineage["verification"]["conditions"]["source_replay"] == [True, True, True]
    assert lineage["verification"]["conditions"]["explicit_pairs"] == [True, True, True]


def test_derive_lineage_should_use_source_replay_mapping_when_anchors_empty_and_source_conditions_hold():
    """优先级 2：anchors 为空但来源级三条件全真 → offset 映射，两帧号 = source_start + clip。"""
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, source_evidence=source_evidence())

    assert_verified_tier(lineage, "source_replay_mapping", "offset")
    assert lineage["roi_frame_index"] == 973 + 191
    assert lineage["verification"]["conditions"] == {"explicit_pairs": [False, False, False],
                                                      "source_replay": [True, True, True]}
    assert lineage["verification"]["evidence_sha256"] == SOURCE_RECEIPT


def test_derive_lineage_should_stay_unverified_when_no_tier_holds():
    """三级都不成立：两帧号 None，failed_conditions 点明哪几条来源级条件没过。"""
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, source_evidence=None)

    assert_unverified(lineage)
    assert lineage["verification"]["conditions"]["source_replay"] == [False, False, True]
    assert set(lineage["verification"]["failed_conditions"]) == {"c1_source_record",
                                                                 "c2_decoded_frame_counts"}


@pytest.mark.parametrize("evidence", [
    pytest.param({"found": False}, id="source-record-not-found"),
    pytest.param({"status": "unverified_frame_preserving_replay"}, id="source-status-unverified"),
    pytest.param({"status": "verified"}, id="source-status-generic-verified"),
    pytest.param({"mapping": "shadow_frame_map"}, id="source-mapping-unexpected"),
])
def test_derive_lineage_should_fail_c1_when_source_record_not_usable(evidence):
    """只让 c1（来源级记录）不成立：帧数仍相等、候选 replay 仍已验，仍必须 unverified。"""
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191,
                                    source_evidence=source_evidence(**evidence))

    assert lineage["verification"]["method"] == "unverified"
    assert lineage["verification"]["conditions"]["source_replay"][0] is False
    assert lineage["verification"]["conditions"]["source_replay"][2] is True
    assert lineage["verification"]["failed_conditions"] == ["c1_source_record"]
    assert_unverified(lineage)


def test_derive_lineage_should_fail_c1_when_source_evidence_is_absent():
    """source_evidence=None 等价于来源级证据不可用：c1 与 c2 都不成立。"""
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, source_evidence=None)

    assert lineage["verification"]["conditions"]["source_replay"][0] is False
    assert "c1_source_record" in lineage["verification"]["failed_conditions"]
    assert_unverified(lineage)


@pytest.mark.parametrize("evidence", [
    pytest.param({"l0_decoded": 1213, "l1_decoded": 1212}, id="counts-differ"),
    pytest.param({"l0_decoded": 1213, "l1_decoded": None}, id="l1-decoded-missing"),
    pytest.param({"l0_decoded": None, "l1_decoded": 1213}, id="l0-decoded-missing"),
    pytest.param({"l0_decoded": None, "l1_decoded": None}, id="both-decoded-missing"),
    pytest.param({"l0_decoded": 0, "l1_decoded": 0}, id="counts-not-positive"),
])
def test_derive_lineage_should_fail_c2_when_decoded_frame_counts_differ_or_missing(evidence):
    """只让 c2（L0/L1 实解码帧数相等）不成立；缺数据不得当通过。"""
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191,
                                    source_evidence=source_evidence(**evidence))

    assert lineage["verification"]["method"] == "unverified"
    assert lineage["verification"]["conditions"]["source_replay"] == [True, False, True]
    assert lineage["verification"]["failed_conditions"] == ["c2_decoded_frame_counts"]
    assert_unverified(lineage)


def test_derive_lineage_should_fail_c3_when_candidate_replay_not_verified():
    """只让 c3（候选自身 replay）不成立：停在前置链 replay 一级，帧号不得推导。

    契约里前置链也包了 ``output.frame_preserving_replay.status``（token ``replay_unverified``），
    所以 c3 为假时实际停在那一步；``conditions.source_replay[2]`` 仍必须如实为 False。
    """
    clip = empty_anchor_candidate(output__frame_preserving_replay={
        "status": "unverified_frame_preserving_replay"})

    lineage = frames.derive_lineage(clip, 191, source_evidence=source_evidence())

    assert lineage["verification"]["method"] == "unverified"
    assert lineage["verification"]["conditions"]["source_replay"][2] is False
    assert lineage["verification"]["failed_conditions"] == ["replay_unverified"]
    assert_unverified(lineage)


@pytest.mark.parametrize("anchors", [
    pytest.param([{"output_frame": 191, "roi_frame": 9999, "source_frame": 9999}], id="roi-offset-broken"),
    pytest.param([{"output_frame": 191, "roi_frame": 1164, "source_frame": 1163}], id="roi-source-differ"),
    pytest.param([{"output_frame": 191, "roi_frame": 1164}], id="source-frame-missing"),
    pytest.param([{"output_frame": "191", "roi_frame": 1164, "source_frame": 1164}], id="output-frame-string"),
    pytest.param([{"output_frame": 191, "roi_frame": 1164, "source_frame": 1164}, "not-an-object"],
                 id="entry-not-object"),
])
def test_derive_lineage_should_hard_fail_with_anchors_broken(anchors):
    """anchors 非空但不合法/自相矛盾 → anchors_broken 硬失败，不降级到来源级声明。"""
    lineage = frames.derive_lineage(anchored_candidate(anchors), 191, source_evidence=source_evidence())

    assert lineage["verification"]["method"] == "unverified"
    assert lineage["verification"]["failed_conditions"] == ["anchors_broken"]
    # 来源级三条件即使全真，也不得把这条候选转成 source_replay_mapping。
    assert lineage["verification"]["conditions"]["source_replay"] == [True, True, True]
    assert lineage["verification"]["conditions"]["explicit_pairs"][0] is True
    assert lineage["roi_frame_index"] is None
    assert_unverified(lineage)


@pytest.mark.parametrize("build,token", [
    pytest.param(lambda: candidate(drop=("output",)), "no_output", id="output-missing"),
    pytest.param(lambda: candidate(output__frame_preserving_replay={"status": "verified"}),
                 "replay_unverified", id="replay-unverified"),
    pytest.param(lambda: candidate(), "bad_clip_index", id="bad-clip-index"),
    pytest.param(lambda: candidate(drop=("output__frame_mapping",)), "no_frame_mapping",
                 id="frame-mapping-missing"),
    pytest.param(lambda: candidate(output__frame_mapping={"anchors": [], "output_start_frame": 0,
                                                        "source_start_frame": None}),
                 "bad_source_start", id="source-start-null"),
])
def test_derive_lineage_should_stop_with_precondition_token(build, token):
    """前置链各级失败各自对应一个固定 token，便于按 token 聚合直方图。"""
    clip_frame_index = 191 if token != "bad_clip_index" else -1

    lineage = frames.derive_lineage(build(), clip_frame_index, source_evidence=source_evidence())

    assert lineage["verification"]["method"] == "unverified"
    assert lineage["verification"]["failed_conditions"] == [token]
    assert_unverified(lineage)


def test_derive_lineage_should_not_probe_media(monkeypatch):
    """derive_lineage 是纯函数：source_evidence 由调用方备好，内部不得调 ffprobe。"""
    def boom(*args, **kwargs):
        raise AssertionError("derive_lineage must not probe media")

    monkeypatch.setattr(frames, "decoded_frame_count", boom)
    monkeypatch.setattr(frames, "media_info", boom)

    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, source_evidence=source_evidence())

    assert lineage["verification"]["method"] == "source_replay_mapping"


def test_derive_lineage_should_use_candidate_receipt_as_evidence_for_manifest_anchors():
    assert frames.derive_lineage(candidate(), 191)["verification"]["evidence_sha256"] == "d" * 64


def test_derive_lineage_should_fall_back_to_manifest_sha256_when_candidate_receipt_missing():
    """候选 receipt 不可用（非 sha256）时退化到 manifest_sha256。"""
    clip = candidate(output__frame_preserving_replay={"status": VERIFIED_REPLAY,
                                                      "receipt_sha256": "not-a-sha256"})

    lineage = frames.derive_lineage(clip, 191, manifest_sha256="f" * 64)

    assert lineage["verification"]["method"] == "manifest_anchors"
    assert lineage["verification"]["evidence_sha256"] == "f" * 64


def test_derive_lineage_should_leave_evidence_null_when_no_digest_is_available():
    """既无 receipt 也无 manifest_sha256 → None，不得伪造摘要。"""
    clip = candidate(output__frame_preserving_replay={"status": VERIFIED_REPLAY})

    lineage = frames.derive_lineage(clip, 191)

    assert lineage["verification"]["method"] == "manifest_anchors"
    assert lineage["verification"]["evidence_sha256"] is None


def test_derive_lineage_should_use_source_receipt_as_evidence_for_source_replay_mapping():
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, source_evidence=source_evidence())

    assert lineage["verification"]["evidence_sha256"] == SOURCE_RECEIPT


def test_derive_lineage_should_fall_back_to_manifest_sha256_when_source_receipt_missing():
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, manifest_sha256="f" * 64,
                                    source_evidence=source_evidence(receipt=None))

    assert lineage["verification"]["method"] == "source_replay_mapping"
    assert lineage["verification"]["evidence_sha256"] == "f" * 64


def test_derive_lineage_should_leave_source_evidence_null_when_no_digest_is_available():
    lineage = frames.derive_lineage(empty_anchor_candidate(), 191, source_evidence=source_evidence(receipt=None))

    assert lineage["verification"]["method"] == "source_replay_mapping"
    assert lineage["verification"]["evidence_sha256"] is None


def media_entry(role, path, sha256, total_frames, frame_count_notes=None, declared_sha256=None,
                total_frames_source="decoded"):
    """One lineage layer: 实测 ``sha256`` 与清单声明 ``declared_sha256``（缺省时与实测一致）。"""
    return {"role": role, "path": path,
            "sha256": sha256, "declared_sha256": sha256 if declared_sha256 is None else declared_sha256,
            "fps": 30.0, "total_frames": total_frames, "total_frames_source": total_frames_source,
            "width": 640 if role != "clip" else 320, "height": 296,
            "size_bucket": "w_gt_400" if role != "clip" else "w_200_400",
            "size_bucket_source": SIZE_BUCKET_SOURCE, "frame_count_notes": frame_count_notes}


L0_SHA, L1_SHA, L2_SHA = "1" * 64, "2" * 64, "3" * 64
L0_TOTAL, L1_TOTAL, L2_TOTAL = 1400, 1400, 240
# 词表已定稿：旧的 "manifest_replay" 不再合法，只剩下面三种。
VERIFIED_METHODS = ("manifest_anchors", "source_replay_mapping")
VERIFIED_VERIFICATION = {"verdict_id": "replay@9f6b9f1af276", "method": "manifest_anchors",
                         "evidence_sha256": "8" * 64, "checked_at": None,
                         "conditions": {"explicit_pairs": [True, True, True],
                                        "source_replay": [True, True, True]},
                         "failed_conditions": []}
SOURCE_REPLAY_VERIFICATION = {"verdict_id": "replay@9f6b9f1af276", "method": "source_replay_mapping",
                              "evidence_sha256": "8" * 64, "checked_at": None,
                              "conditions": {"explicit_pairs": [False, False, False],
                                             "source_replay": [True, True, True]},
                              "failed_conditions": []}
UNVERIFIED_VERIFICATION = {"verdict_id": "unverified", "method": "unverified",
                           "evidence_sha256": None, "checked_at": None,
                           "conditions": {"explicit_pairs": [False, False, False],
                                          "source_replay": [False, False, False]},
                           "failed_conditions": ["c1_source_record"]}


def lineage_media(l0_sha=L0_SHA, l1_sha=L1_SHA, l2_sha=L2_SHA,
                  l0_declared=L0_SHA, l1_declared=L1_SHA, l2_declared=L2_SHA):
    return {"l0": media_entry("source", "/scratch/l0/video_0001.mp4", l0_sha, L0_TOTAL,
                              declared_sha256=l0_declared),
            "l1": media_entry("roi", "/scratch/l1/video_0001.mp4", l1_sha, L1_TOTAL,
                              declared_sha256=l1_declared),
            "l2": media_entry("clip", "/scratch/l2/c00.mp4", l2_sha, L2_TOTAL,
                              declared_sha256=l2_declared)}


def frame_entry(order, clip_frame_index, roi_frame_index, original_source_frame_index, offset=973,
                roi_to_original=None):
    return {"display_order": order, "decode_order": order,
            "clip_frame_index": clip_frame_index, "roi_frame_index": roi_frame_index,
            "original_source_frame_index": original_source_frame_index,
            "is_anchor": clip_frame_index in (191, 192), "anchor_ref": None, "media_role": "clip",
            "image": f"frame_{order + 1:03d}.png", "pts_seconds": clip_frame_index / 30.0,
            "frame_index_mapping": {
                "clip_to_roi": {"kind": "manifest_replay", "offset": offset, "reason": None},
                "clip_to_model_input": {"kind": "manifest_replay", "offset": offset, "reason": None},
                "roi_to_original": {"kind": "explicit_pairs", "offset": 0, "method": "manifest_anchors",
                                  "reason": None} if roi_to_original is None else roi_to_original}}


def unverified_frame_entry(order, clip_frame_index):
    """unverified 帧：两帧号 None，L1→L0 节点记为 unverified 并带非空 reason。"""
    return frame_entry(order, clip_frame_index, None, None,
                       roi_to_original={"kind": "unverified", "offset": None, "method": "unverified",
                                      "reason": "没有可用的同序性证据"})


def offset_frame_entry(order, clip_frame_index, roi_frame_index, original_source_frame_index, offset=973):
    """优先级 2（source_replay_mapping）帧：L1→L0 节点 kind == offset 且 offset 为 0。"""
    return frame_entry(order, clip_frame_index, roi_frame_index, original_source_frame_index, offset=offset,
                       roi_to_original={"kind": "offset", "offset": 0, "method": "source_replay_mapping",
                                      "reason": None})


def lineage_frames():
    return [frame_entry(0, 0, 973, 973), frame_entry(1, 191, 1164, 1164), frame_entry(2, 239, 1212, 1212)]


def lineage_record(verification=None, media=None, frames_override=None, clip_sha256=L2_SHA):
    return {"record_schema": frames.RECORD_SCHEMA, "candidate_id": "video_0001_fracture_01",
            "clip_sha256": clip_sha256, "manifest_sha256": "f" * 64,
            "input_id": "input@sha256:" + "0" * 64,
            "frame_count_convention": "decoded",
            "verification": VERIFIED_VERIFICATION if verification is None else verification,
            "lineage_check": "pass",
            "lineage_media": lineage_media() if media is None else media,
            "media": media_entry("clip", "/scratch/l2/c00.mp4", L2_SHA, L2_TOTAL),
            "frames": lineage_frames() if frames_override is None else frames_override}


def assert_reasons(reasons, *tokens):
    assert isinstance(reasons, list) and reasons
    assert all(isinstance(reason, str) and reason.strip() for reason in reasons)
    text = " | ".join(reasons).lower()
    assert any(token in text for token in tokens), f"reason should mention one of {tokens}: {reasons}"


def assert_reasons_require(reasons, *required):
    """all-token：每个 required token 都必须出现在失败原因里，不容许被别的 token 兜住。"""
    assert isinstance(reasons, list) and reasons
    assert all(isinstance(reason, str) and reason.strip() for reason in reasons)
    text = " | ".join(reasons).lower()
    missing = [token for token in required if token.lower() not in text]
    assert not missing, f"reason should mention {missing}: {reasons}"


def test_verify_lineage_should_pass_for_record_with_consistent_layers():
    assert frames.verify_lineage(lineage_record()) == []


def test_verify_lineage_should_pass_when_unverified_record_keeps_source_index_null():
    record = lineage_record(verification={**UNVERIFIED_VERIFICATION, "verdict_id": "unverified:no_replay"},
                            frames_override=[unverified_frame_entry(0, 0), unverified_frame_entry(1, 239)])

    assert frames.verify_lineage(record) == []


def test_verify_lineage_should_report_clip_index_outside_l2_decoded_count():
    """L3 帧号必须落在 L2 decoded 帧数内：239 是最后一帧，240 已越界。"""
    record = lineage_record(frames_override=[frame_entry(0, 0, 973, 973), frame_entry(1, L2_TOTAL, 1213, 1213)])

    assert_reasons(frames.verify_lineage(record), "clip_frame_index", "l2", "l3", "decoded")


def test_verify_lineage_should_report_roi_index_outside_l1_frame_count():
    """L1 ROI 越界：roi 1400 不满足 0 <= roi < 1400。"""
    record = lineage_record(frames_override=[frame_entry(0, 0, 973, 973), frame_entry(1, 199, L1_TOTAL, 1213)])

    assert_reasons(frames.verify_lineage(record), "roi_frame_index", "roi", "l1")


def test_verify_lineage_should_report_sha256_mismatch_between_manifest_and_media():
    """清单声明摘要（clip_sha256）与 L2 实测摘要不一致时必须报错。"""
    record = lineage_record(media=lineage_media(l2_sha="4" * 64))

    assert_reasons(frames.verify_lineage(record), "sha256", "digest")


def test_verify_lineage_should_report_l0_declared_sha256_mismatch():
    """L0 实测摘要与清单声明摘要（replay.source_sha256）不一致时必须报错。"""
    record = lineage_record(media=lineage_media(l0_declared="5" * 64))

    reasons = frames.verify_lineage(record)

    assert_reasons(reasons, "sha256", "digest")
    assert_reasons(reasons, "l0")


def test_verify_lineage_should_report_l1_declared_sha256_mismatch():
    """L1 实测摘要与清单声明摘要（replay.roi_sha256）不一致时必须报错。"""
    record = lineage_record(media=lineage_media(l1_declared="6" * 64))

    reasons = frames.verify_lineage(record)

    assert_reasons(reasons, "sha256", "digest")
    assert_reasons(reasons, "l1")


def test_verify_lineage_should_tighten_unverified_source_index_reason():
    """method == unverified 时不得给 original_source_frame_index，原因必须点名该字段。"""
    record = lineage_record(verification=UNVERIFIED_VERIFICATION)

    assert_reasons_require(frames.verify_lineage(record), "original_source_frame_index")


def test_verify_lineage_should_report_original_source_index_outside_l0():
    """verified 时 original_source_frame_index 必须落在 L0 帧数内：1400 已越界。"""
    record = lineage_record(frames_override=[frame_entry(0, 0, 973, 973),
                                             frame_entry(1, 191, 1164, L0_TOTAL)])

    assert_reasons_require(frames.verify_lineage(record), "original_source_frame_index")


def test_verify_lineage_should_report_missing_l0_frame_count():
    """L0 帧数缺失时无法校验原始源帧号，不得当作通过。"""
    record = lineage_record()
    record["lineage_media"]["l0"]["total_frames"] = None

    assert_reasons_require(frames.verify_lineage(record), "l0")


def test_verify_lineage_should_report_l0_l1_frame_count_mismatch():
    """L1↔L0 同序性的必要条件：两者帧数必须相等；1400 != 1000 必须报错。"""
    record = lineage_record(frames_override=[frame_entry(0, 0, 973, 973),
                                             frame_entry(1, 1, 974, 974),
                                             frame_entry(2, 2, 975, 975)])
    record["lineage_media"]["l1"]["total_frames"] = 1000

    assert_reasons_require(frames.verify_lineage(record), "l0", "l1")


def test_verify_lineage_should_report_layer_without_decoded_count():
    """某层只能用文件头帧数（total_frames_source == container_header）时必须报错。"""
    record = lineage_record()
    record["lineage_media"]["l2"]["total_frames_source"] = "container_header"

    assert_reasons_require(frames.verify_lineage(record), "total_frames_source", "l2")


def test_verify_lineage_should_report_unknown_verification_method():
    """verification.method 只允许 manifest_anchors / source_replay_mapping / unverified。"""
    record = lineage_record(verification={**VERIFIED_VERIFICATION, "method": "totally_bogus"})

    assert_reasons_require(frames.verify_lineage(record), "method")


def test_verify_lineage_should_pass_for_source_replay_mapping_record():
    """优先级 2 的合法记录：L1→L0 节点 kind == offset、offset == 0、两帧号同号。"""
    record = lineage_record(verification=SOURCE_REPLAY_VERIFICATION,
                            frames_override=[offset_frame_entry(0, 0, 973, 973),
                                             offset_frame_entry(1, 239, 1212, 1212)])

    assert frames.verify_lineage(record) == []


def test_verify_lineage_should_report_legacy_manifest_replay_method():
    """旧词表 "manifest_replay" 已不合法，必须给出 reason。"""
    record = lineage_record(verification={**VERIFIED_VERIFICATION, "method": "manifest_replay"})

    assert_reasons_require(frames.verify_lineage(record), "method")


def test_verify_lineage_should_report_missing_roi_to_original():
    """verified 记录缺 L1→L0 节点时无从校 offset，不得静默通过。"""
    frame = frame_entry(0, 0, 973, 973)
    del frame["frame_index_mapping"]["roi_to_original"]
    record = lineage_record(frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original")


def test_verify_lineage_should_report_roi_to_original_offset_not_zero():
    """verified 要求 roi_to_original.offset == 0；非 0 偏移与两帧号同号相矛盾。"""
    frame = offset_frame_entry(0, 0, 973, 973)
    frame["frame_index_mapping"]["roi_to_original"]["offset"] = 5
    record = lineage_record(verification=SOURCE_REPLAY_VERIFICATION, frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original", "offset")


def test_verify_lineage_should_report_original_source_index_not_equal_roi_index():
    """verified 要求 original_source_frame_index == roi_frame_index（L1 与 L0 同号）。"""
    record = lineage_record(frames_override=[frame_entry(0, 0, 973, 974)])

    assert_reasons_require(frames.verify_lineage(record), "original_source_frame_index")


def test_verify_lineage_should_report_manifest_anchors_conditions_not_satisfied():
    """method == manifest_anchors 时 conditions.explicit_pairs 必须全真，否则给 reason。"""
    record = lineage_record(verification={
        **VERIFIED_VERIFICATION,
        "conditions": {"explicit_pairs": [True, False, False], "source_replay": [True, True, True]}})

    assert_reasons_require(frames.verify_lineage(record), "explicit_pairs")


def test_verify_lineage_should_report_source_replay_conditions_not_satisfied():
    """method == source_replay_mapping 时 conditions.source_replay 必须全真，否则给 reason。"""
    record = lineage_record(verification={
        **SOURCE_REPLAY_VERIFICATION,
        "conditions": {"explicit_pairs": [False, False, False], "source_replay": [True, False, True]}},
        frames_override=[offset_frame_entry(0, 0, 973, 973)])

    assert_reasons_require(frames.verify_lineage(record), "source_replay")


def test_verify_lineage_should_report_unverified_record_with_verified_roi_to_original():
    """unverified 记录的 L1→L0 节点必须是 kind == unverified，不能挂着 verified 形态。

    断言 token 必须能区分「kind 配对守卫」与「reason 未填守卫」：两个子串都要命中此条。
    """
    record = lineage_record(verification=UNVERIFIED_VERIFICATION,
                            frames_override=[frame_entry(0, 0, None, None)])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original", "kind", "explicit_pairs")


def test_verify_lineage_should_report_kind_contradicting_manifest_anchors():
    """method=manifest_anchors 却把 L1→L0 节点写成 kind=offset：证据形态与证据级别不配对。"""
    frame = frame_entry(0, 0, 973, 973,
                        roi_to_original={"kind": "offset", "offset": 0, "method": "manifest_anchors",
                                       "reason": None})
    record = lineage_record(frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "kind", "offset", "explicit_pairs")


def test_verify_lineage_should_report_kind_contradicting_source_replay_mapping():
    """method=source_replay_mapping 却把 L1→L0 节点写成 kind=explicit_pairs：反向的同一缺口。"""
    frame = frame_entry(0, 0, 973, 973,
                        roi_to_original={"kind": "explicit_pairs", "offset": 0,
                                       "method": "source_replay_mapping", "reason": None})
    record = lineage_record(verification=SOURCE_REPLAY_VERIFICATION, frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "kind", "explicit_pairs", "offset")


def test_verify_lineage_should_report_roi_to_original_node_method_disagreeing_with_verification():
    """kind 对但节点自身 method 字段写错：节点里的证据级别也必须与 verification.method 一致。"""
    frame = frame_entry(0, 0, 973, 973,
                        roi_to_original={"kind": "explicit_pairs", "offset": 0,
                                       "method": "source_replay_mapping", "reason": None})
    record = lineage_record(frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original", "method",
                           "manifest_anchors", "source_replay_mapping")


@pytest.mark.parametrize("kind", ["explicit_pairs", "offset"])
def test_verify_lineage_should_report_unverified_record_carrying_verified_shape_with_reason(kind):
    """unverified 帧挂 verified 形态且 reason 非空：不得靠「reason 为空」守卫兜住。

    这条用例在「kind 配对守卫」被去掉（变异）后必须变红：那时 reason 非空使「reason 未填」
    守卫也不生效，verify_lineage 会直接放行。断言的 token 只可能来自 kind 守卫的文案。
    """
    frame = frame_entry(0, 0, None, None,
                        roi_to_original={"kind": kind, "offset": 0, "method": "manifest_anchors",
                                       "reason": "从来源级映射继承（模板残留）"})
    record = lineage_record(verification=UNVERIFIED_VERIFICATION, frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original", "kind", kind)


def test_verify_lineage_should_report_unverified_node_naming_a_verified_method():
    """unverified 记录的节点 kind 已是 unverified，但节点自身 method 还写着已验级别。

    kind == "unverified" 只说明「这一级没建成」，节点 method 若写 manifest_anchors 等于仍声称有锚点证据；
    reason 必须点名该字段与那个错写的取值。
    """
    frame = frame_entry(0, 0, None, None,
                        roi_to_original={"kind": "unverified", "offset": 0,
                                       "method": "manifest_anchors",
                                       "reason": "候选 anchors 为空，来源级证据未采用"})
    record = lineage_record(verification=UNVERIFIED_VERIFICATION, frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original", "method", "manifest_anchors")


def test_verify_lineage_should_report_unverified_node_with_nonzero_offset():
    """unverified 节点的 offset 必须是 0/None：非 0 偏移等于偷带一份未经证明的 L1→L0 偏移。"""
    frame = frame_entry(0, 0, None, None,
                        roi_to_original={"kind": "unverified", "offset": 5, "method": "unverified",
                                       "reason": "候选 anchors 为空，来源级证据未采用"})
    record = lineage_record(verification=UNVERIFIED_VERIFICATION, frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "roi_to_original", "offset")


def test_verify_lineage_should_report_unverified_record_without_failed_conditions():
    """unverified 却拿不出 failed_conditions，等于没说为什么没建成：必须给 reason。"""
    record = lineage_record(verification={**UNVERIFIED_VERIFICATION, "failed_conditions": []},
                            frames_override=[unverified_frame_entry(0, 0)])

    assert_reasons_require(frames.verify_lineage(record), "failed_conditions")


def test_verify_lineage_should_report_unverified_record_without_reason():
    """unverified 记录的 roi_to_original.reason 必须是非空字符串。"""
    frame = unverified_frame_entry(0, 0)
    frame["frame_index_mapping"]["roi_to_original"]["reason"] = "   "
    record = lineage_record(verification=UNVERIFIED_VERIFICATION, frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "reason")


@pytest.mark.parametrize("verification", [
    pytest.param(MISSING, id="verification-key-missing"),
    pytest.param(None, id="verification-null"),
])
def test_verify_lineage_should_report_missing_verification_block(verification):
    """没有 verification 块就没有证据身份，不得静默通过。

    帧本身取 unverified 合法形态（roi/original 均为 None），排掉「unverified 却给帧号」类
    原因把 ``verification`` 这个 token 兜住的可能。
    """
    record = lineage_record(frames_override=[unverified_frame_entry(0, 0), unverified_frame_entry(1, 239)])
    if verification is MISSING:
        del record["verification"]
    else:
        record["verification"] = None

    assert_reasons_require(frames.verify_lineage(record), "verification")


def test_verify_lineage_should_report_empty_frames():
    """零帧记录的 lineage 是空洞证据，必须报错。"""
    record = lineage_record(frames_override=[])

    assert_reasons_require(frames.verify_lineage(record), "frames")


def test_verify_lineage_should_report_roi_index_not_matching_offset():
    """verified 时 roi_frame_index 必须等于 clip_frame_index + clip_to_roi.offset。"""
    record = lineage_record(frames_override=[frame_entry(0, 0, 5, 973)])  # 0 + 973 != 5

    assert_reasons_require(frames.verify_lineage(record), "roi_frame_index")


def test_record_schema_should_be_version_three():
    assert frames.RECORD_SCHEMA == "five-label-input-record/3"


def _drop_frame_index_mapping(frame):
    del frame["frame_index_mapping"]


def _drop_clip_to_roi(frame):
    del frame["frame_index_mapping"]["clip_to_roi"]


def _offset_as_string(frame):
    frame["frame_index_mapping"]["clip_to_roi"]["offset"] = "973"


def _offset_as_float(frame):
    frame["frame_index_mapping"]["clip_to_roi"]["offset"] = 973.0


@pytest.mark.parametrize("break_offset", [_drop_frame_index_mapping, _drop_clip_to_roi,
                                         _offset_as_string, _offset_as_float],
                         ids=["mapping-block-missing", "clip-to-roi-missing",
                              "offset-string", "offset-float"])
def test_verify_lineage_should_report_missing_offset_for_verified_record(break_offset):
    """verified 时偏移必须可校验：缺失或非整数 offset 使 roi 无法校验，不得静默通过。"""
    frame = frame_entry(0, 0, 973, 973)
    break_offset(frame)
    record = lineage_record(frames_override=[frame])

    assert_reasons_require(frames.verify_lineage(record), "offset")


@pytest.mark.parametrize("verification,frames_builder", [
    pytest.param(VERIFIED_VERIFICATION, lineage_frames, id="verified-method"),
    pytest.param(UNVERIFIED_VERIFICATION,
                 lambda: [unverified_frame_entry(0, 0), unverified_frame_entry(1, 239)],
                 id="unverified-method"),
])
def test_verify_lineage_should_report_missing_actual_sha256(verification, frames_builder):
    """任一层实测 sha256 为 None（含 unverified）时不得当作已校验。"""
    record = lineage_record(verification=verification, frames_override=frames_builder())
    record["lineage_media"]["l1"]["sha256"] = None
    record["lineage_media"]["l1"]["declared_sha256"] = None

    assert_reasons_require(frames.verify_lineage(record), "sha256", "l1")


@pytest.mark.parametrize("media", [pytest.param(MISSING, id="media-key-missing"),
                                   pytest.param(None, id="media-null")])
def test_verify_lineage_should_report_missing_media_block(media):
    """record.media 缺失或非 dict 时三方摘要无法对齐，不得静默通过。"""
    record = lineage_record()
    if media is MISSING:
        del record["media"]
    else:
        record["media"] = None

    assert_reasons_require(frames.verify_lineage(record), "media")


def test_verify_lineage_should_report_record_clip_sha_mismatch_with_l2():
    """record.clip_sha256 必须等于 l2 实测/声明摘要（三方一致）。"""
    record = lineage_record(clip_sha256="7" * 64)  # l2 实测与声明仍为 L2_SHA

    assert_reasons_require(frames.verify_lineage(record), "sha256")


def source_manifest(tmp_path, candidates):
    """Write a minimal source manifest to scratch space and read it back like the CLI does."""
    path = tmp_path / "source_manifest.json"
    path.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def test_candidates_should_reject_duplicate_candidate_id(tmp_path):
    manifest = source_manifest(tmp_path, [{"candidate_id": "c00"}, {"candidate_id": "c00"}])

    with pytest.raises(InputError) as excinfo:
        frames._candidates(manifest)

    assert "c00" in str(excinfo.value)


def test_candidates_should_reject_row_that_is_not_an_object(tmp_path):
    manifest = source_manifest(tmp_path, [{"candidate_id": "c00"}, ["x"]])

    with pytest.raises(InputError) as excinfo:
        frames._candidates(manifest)

    assert "#2" in str(excinfo.value)


def test_candidates_should_reject_row_without_candidate_id(tmp_path):
    manifest = source_manifest(tmp_path, [{"candidate_id": "c00"}, {"source_video_id": "video_0001"}])

    with pytest.raises(InputError) as excinfo:
        frames._candidates(manifest)

    assert "candidate_id" in str(excinfo.value)


def test_read_records_should_skip_blank_lines(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"candidate_id": "c00"}\n\n   \n{"candidate_id": "c01"}\n', encoding="utf-8")

    records = frames.read_records(path)

    assert [record["candidate_id"] for record in records] == ["c00", "c01"]


def test_read_records_should_reject_invalid_json_line(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"candidate_id": "c00"}\nnot json\n', encoding="utf-8")

    with pytest.raises(InputError) as excinfo:
        frames.read_records(path)

    # 第二条且不可解析：错误必须点名行号，而不是抛裸 ValueError 让调用方无从定位。
    assert ":2:" in str(excinfo.value)


def test_read_records_should_reject_row_that_is_not_an_object(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"candidate_id": "c00"}\n[1, 2]\n', encoding="utf-8")

    with pytest.raises(InputError) as excinfo:
        frames.read_records(path)

    assert ":2:" in str(excinfo.value)


L2_BYTES = b"fake clip bytes"
FAKE_TOTALS = {"source_videos": 1400, "roi_videos": 1400, "sub_video_videos": 240}


def fake_extract_frames(clip, indices, target):
    """Stand-in for ffmpeg: one timestamp + one image name per requested index."""
    return ([index / 30.0 for index in indices],
            [f"frame_{number:03d}.png" for number in range(1, len(indices) + 1)])


def fake_media_info(path):
    """文件头探针：宽高与 container_header 按 L0/L1/L2 目录区分，不读真实媒体。"""
    directory = Path(path).parent.name
    header = FAKE_TOTALS[directory]
    return {"width": 640 if directory != "sub_video_videos" else 320, "height": 296,
            "fps": 30.0, "container_header": header, "total_frames": header}


def lineage_profiles(tmp_path):
    """Fake L0/L1/L2 media on scratch space plus the sha256 each declared digest must carry."""
    for key in ("source_videos", "roi_videos"):
        (tmp_path / key).mkdir()
        (tmp_path / key / "video_0001.mp4").write_bytes(f"{key} bytes".encode())
    videos = tmp_path / "sub_video_videos"
    videos.mkdir()
    (videos / "c00.mp4").write_bytes(L2_BYTES)
    profiles = {"source_videos": tmp_path / "source_videos", "roi_videos": tmp_path / "roi_videos",
                "sub_video_videos": videos, "sub_video_manifest": tmp_path / "source_manifest.json"}
    digests = {key: hashlib.sha256((tmp_path / key / "video_0001.mp4").read_bytes()).hexdigest()
               for key in ("source_videos", "roi_videos")}
    digests["l2"] = hashlib.sha256(L2_BYTES).hexdigest()
    return profiles, digests


def lineage_candidate(digests):
    """Candidate whose replay proof declares the sha256 of the scratch L0/L1/L2 bytes."""
    clip = candidate(output__sha256=digests["l2"])
    clip["output"]["frame_preserving_replay"].update({"source_sha256": digests["source_videos"],
                                                      "roi_sha256": digests["roi_videos"],
                                                      "output_sha256": digests["l2"]})
    return clip


def patch_media(monkeypatch, decoded=None):
    """Replace every media reader so extract_record only sees the fake layer files.

    ``decode`` 按目录名覆盖 ``frames.decoded_frame_count(path) -> int | None`` 的返回值（其余层用
    FAKE_TOTALS）。该函数是契约要求的公开函数，故意不加 ``raising=False``：它不存在时必须红。
    """
    decoded = decoded or {}

    def fake_decoded_frame_count(path):
        directory = Path(path).parent.name
        return decoded.get(directory, FAKE_TOTALS[directory])

    monkeypatch.setattr(frames, "media_info", fake_media_info)
    monkeypatch.setattr(frames, "_extract_frames", fake_extract_frames)
    monkeypatch.setattr(frames, "decoded_frame_count", fake_decoded_frame_count)


def test_extract_record_should_record_four_layer_lineage(tmp_path, monkeypatch):
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch)

    record = frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                                   manifest_sha256="b" * 64)

    assert record["frame_count_convention"] == "decoded"
    assert record["lineage_check"] == "pass"
    assert set(record["lineage_media"]) == set(LINEAGE_LAYERS)
    for layer in LINEAGE_LAYERS:
        assert set(MEDIA_FIELDS) <= set(record["lineage_media"][layer])
        # 一致时不得输出帧数不一致说明。
        assert record["lineage_media"][layer]["frame_count_notes"] is None
    assert record["lineage_media"]["l0"]["sha256"] == digests["source_videos"]
    assert record["lineage_media"]["l1"]["sha256"] == digests["roi_videos"]
    assert record["lineage_media"]["l2"]["sha256"] == digests["l2"]
    # 清单声明的三层摘要：L0/L1 取 replay.source_sha256/roi_sha256，L2 取 output.sha256。
    assert record["lineage_media"]["l0"]["declared_sha256"] == digests["source_videos"]
    assert record["lineage_media"]["l1"]["declared_sha256"] == digests["roi_videos"]
    assert record["lineage_media"]["l2"]["declared_sha256"] == digests["l2"]
    assert [record["lineage_media"][layer]["total_frames"] for layer in LINEAGE_LAYERS] == \
        [FAKE_TOTALS["source_videos"], FAKE_TOTALS["roi_videos"], FAKE_TOTALS["sub_video_videos"]]
    # 默认候选带合法 anchors：extract 路径得到的 method 是 manifest_anchors（旧词表已不在域内）。
    assert record["verification"]["method"] == "manifest_anchors"
    # verdict_id 契约：verified 时以 "replay@" 开头。
    assert record["verification"]["verdict_id"].startswith("replay@")


def test_extract_record_should_derive_roi_and_source_index_for_every_frame(tmp_path, monkeypatch):
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch)

    record = frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                                   manifest_sha256="b" * 64)

    expected_clip = [0, 34, 68, 102, 137, 171, 205, 239]
    assert [frame["clip_frame_index"] for frame in record["frames"]] == expected_clip
    assert [frame["roi_frame_index"] for frame in record["frames"]] == [973 + i for i in expected_clip]
    assert [frame["original_source_frame_index"] for frame in record["frames"]] == [973 + i for i in expected_clip]
    assert record["sampling"] == {
        "sampling_rule": "evenly_spaced_inclusive",
        "target_frame_count": 8,
        "short_clip_policy": "fail_closed",
        "resize": None,
    }
    for frame in record["frames"]:
        assert set(FRAME_FIELDS) <= set(frame)
        assert frame["width"] == 320
        assert frame["height"] == 296
        # 新增 L1→L0 节点：键集合固定三个。
        assert set(frame["frame_index_mapping"]) == {"clip_to_roi", "clip_to_model_input", "roi_to_original"}
        for mapping in frame["frame_index_mapping"].values():
            assert set(MAPPING_FIELDS) <= set(mapping)
        assert frame["frame_index_mapping"]["clip_to_roi"]["offset"] == 973
        assert frame["frame_index_mapping"]["clip_to_model_input"]["sampling_rule"] == "evenly_spaced_inclusive"
        assert frame["frame_index_mapping"]["clip_to_model_input"]["short_clip_policy"] == "fail_closed"
        assert frame["frame_index_mapping"]["clip_to_model_input"]["target_frame_count"] == 8
        assert frame["frame_index_mapping"]["clip_to_model_input"]["resize"] is None
        assert frame["frame_index_mapping"]["roi_to_original"]["kind"] == "explicit_pairs"
        assert frame["frame_index_mapping"]["roi_to_original"]["offset"] == 0


def test_extract_record_should_keep_l2_identity_fields(tmp_path, monkeypatch):
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch)

    record = frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                                   manifest_sha256="b" * 64)

    assert record["record_schema"] == frames.RECORD_SCHEMA
    assert record["manifest_sha256"] == "b" * 64
    assert record["clip_sha256"] == digests["l2"]
    assert record["input_id"].startswith("input@sha256:")
    # media 仍描述 L2 子视频。
    assert record["media"]["role"] == "clip"
    assert record["media"]["sha256"] == digests["l2"]
    assert record["media"]["total_frames"] == FAKE_TOTALS["sub_video_videos"]


def test_extract_record_should_report_frame_count_delta_when_decoded_differs_from_header(tmp_path, monkeypatch):
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch, decoded={"sub_video_videos": 246})  # L2 文件头声明 240，实解码 246

    record = frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                                   manifest_sha256="b" * 64)

    notes = record["lineage_media"]["l2"]["frame_count_notes"]
    assert notes is not None
    assert notes["delta"] != 0


def test_extract_record_should_raise_input_error_when_lineage_check_fails(tmp_path, monkeypatch):
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch)
    monkeypatch.setattr(frames, "verify_lineage", lambda record: ["synthetic: l2 sha256 mismatch"])

    with pytest.raises(InputError) as excinfo:
        frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                              manifest_sha256="b" * 64)

    assert str(excinfo.value).strip()


def spy_on_lineage_check(monkeypatch):
    """俘获传给 verify_lineage 的 record，并让它按真实校验结果返回。"""
    captured = {}
    real = frames.verify_lineage

    def spy(record):
        captured["record"] = record
        return real(record)

    monkeypatch.setattr(frames, "verify_lineage", spy)
    return captured


def test_extract_record_should_report_count_frames_failure_notes(tmp_path, monkeypatch):
    """L2 实解码计数失败时不得伪装成已计数：标 container_header 并写 reason，且整条记录被拒。"""
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch, decoded={"sub_video_videos": None})
    captured = spy_on_lineage_check(monkeypatch)

    with pytest.raises(InputError) as excinfo:
        frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                              manifest_sha256="b" * 64)

    assert str(excinfo.value).strip()
    layer = captured["record"]["lineage_media"]["l2"]
    assert layer["total_frames_source"] == "container_header"
    assert layer["frame_count_notes"] == {"decoded": None, "container_header": FAKE_TOTALS["sub_video_videos"],
                                         "delta": None, "reason": "count_frames_failed"}


def test_extract_record_should_change_input_id_when_l0_digest_changes(tmp_path, monkeypatch):
    """L0 实测摘要变化必须进入 input_id 身份：同一 candidate 不得得到同一 input_id。"""
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch)
    first = frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames-a",
                                  manifest_sha256="b" * 64)

    (tmp_path / "source_videos" / "video_0001.mp4").write_bytes(b"changed source bytes")
    moved = lineage_candidate(digests)
    moved["output"]["frame_preserving_replay"]["source_sha256"] = \
        hashlib.sha256(b"changed source bytes").hexdigest()
    second = frames.extract_record(moved, profiles, tmp_path / "frames-b", manifest_sha256="b" * 64)

    assert second["lineage_media"]["l0"]["sha256"] != first["lineage_media"]["l0"]["sha256"]
    assert first["input_id"] != second["input_id"]


# --------------------------------------------------------------------------------------
# 批次覆盖率信号（lineage_summary）与 --coverage-scan 模式
# --------------------------------------------------------------------------------------
def summary_row(order, method, failed_conditions=()):
    """批次行：候选级一行，method 与 failed_conditions 是该候选的证据结论。"""
    return {"candidate_id": f"c{order:03d}", "method": method,
            "failed_conditions": list(failed_conditions)}


def summary_rows(methods, reasons=()):
    """按 method 序列造批次行；unverified 行轮流贴 reasons 里的 failed_conditions token。"""
    pool = list(reasons)
    rows = []
    for order, method in enumerate(methods):
        failed = [pool[order % len(pool)]] if method == "unverified" and pool else []
        rows.append(summary_row(order, method, failed))
    return rows


def test_lineage_summary_should_count_methods_ratios_and_unverified_reasons():
    "100 条：60 manifest_anchors + 34 source_replay_mapping + 6 unverified。"
    rows = summary_rows(["manifest_anchors"] * 60 + ["source_replay_mapping"] * 34 + ["unverified"] * 6,
                        reasons=["c2_decoded_frame_counts", "c2_decoded_frame_counts", "anchors_broken"])

    summary = frames.lineage_summary(rows)

    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["total"] == 100
    assert summary["verified_by_method"] == {"manifest_anchors": 60, "source_replay_mapping": 34,
                                             "unverified": 6}
    assert summary["ratios"] == {"manifest_anchors": 0.6, "source_replay_mapping": 0.34, "unverified": 0.06}
    # 直方图只按 unverified 行的 failed_conditions token 聚合。
    assert summary["unverified_reasons"] == {"c2_decoded_frame_counts": 4, "anchors_broken": 2}
    assert summary["frame_index_coverage"] == 0.94
    assert summary["warning"] is True
    assert "本批帧号覆盖率不足" in summary["warning_text"]


@pytest.mark.parametrize("unverified,warning", [(5, False), (6, True)])
def test_lineage_summary_should_warn_only_above_five_percent(unverified, warning):
    """边界：unverified 比例恰为 5% 不警告，> 5%（6/100）警告。"""
    rows = summary_rows(["manifest_anchors"] * (100 - unverified) + ["unverified"] * unverified,
                        reasons=["c2_decoded_frame_counts"])

    summary = frames.lineage_summary(rows)

    assert summary["total"] == 100
    assert summary["ratios"]["unverified"] == unverified / 100
    assert summary["warning"] is warning
    if not warning:
        assert summary["warning_text"] is None


def test_lineage_summary_should_not_warn_when_every_candidate_is_verified():
    rows = summary_rows(["manifest_anchors", "source_replay_mapping"])

    summary = frames.lineage_summary(rows)

    assert summary["warning"] is False
    assert summary["warning_text"] is None
    assert summary["unverified_reasons"] == {}


def test_lineage_summary_should_return_zeroed_summary_when_no_records():
    """total == 0 不得除零：计数与占比全 0，不警告。"""
    summary = frames.lineage_summary([])

    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["total"] == 0
    assert summary["verified_by_method"] == {"manifest_anchors": 0, "source_replay_mapping": 0, "unverified": 0}
    assert summary["ratios"] == {"manifest_anchors": 0.0, "source_replay_mapping": 0.0, "unverified": 0.0}
    assert summary["unverified_reasons"] == {}
    assert summary["frame_index_coverage"] == 0.0
    assert summary["warning"] is False
    assert summary["warning_text"] is None


def run_main(argv):
    """跑 CLI；argparse 的 SystemExit 视为测试失败（--coverage-scan 不应要求 --out-dir）。"""
    try:
        return frames.main(argv)
    except SystemExit as exc:
        pytest.fail(f"frames.main({argv}) 触发了 argparse 退出（rc={exc.code}）")


def snapshot_tree(root):
    return {str(path.relative_to(root)) for path in Path(root).rglob("*")}


def scan_manifest(tmp_path):
    """2 个候选 + 1 条来源记录：c00 有合法 anchors，c01 的 anchors 为空（依赖来源级证据）。"""
    profiles, digests = lineage_profiles(tmp_path)
    (profiles["sub_video_videos"] / "c01.mp4").write_bytes(L2_BYTES)
    first = lineage_candidate(digests)
    second = lineage_candidate(digests)
    second["candidate_id"] = "c01"
    second["output_path"] = "data/sub_video/c01.mp4"
    second["output"]["frame_mapping"] = {"anchors": [], "output_start_frame": 0, "source_start_frame": 973}
    manifest = {
        "schema": "tensile-unified-sub-video/1",
        "candidates": [first, second],
        "sources": [{"video_id": "video_0001", "source_path": "data/videos/video_0001.mp4",
                     "roi_path": "data/roi/videos/video_0001.mp4",
                     "frame_preserving_replay": {"video_id": "video_0001", "status": VERIFIED_REPLAY,
                                                 "mapping": SOURCE_MAPPING, "proof_type": SOURCE_PROOF_TYPE,
                                                 "receipt_sha256": SOURCE_RECEIPT}}],
    }
    path = tmp_path / "scan_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return profiles, path


def test_main_coverage_scan_should_not_extract_frames_or_create_output_dir(tmp_path, monkeypatch):
    """--coverage-scan 只解析清单 + 读帧数：不抽帧、不需要 --out-dir、不建任何目录/PNG。"""
    profiles, manifest_path = scan_manifest(tmp_path)
    patch_media(monkeypatch)

    def refuse_extract(*args, **kwargs):
        raise AssertionError("coverage scan must not extract frames")

    monkeypatch.setattr(frames, "_extract_frames", refuse_extract)
    monkeypatch.setattr(frames.paths, "load_profile", lambda name: profiles)
    output = tmp_path / "lineage_scan.json"
    before = snapshot_tree(tmp_path)

    rc = run_main(["--coverage-scan", "--output", str(output), "--manifest", str(manifest_path)])

    assert rc == 0
    assert snapshot_tree(tmp_path) - before == {"lineage_scan.json"}
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == SUMMARY_SCHEMA
    assert payload["total"] == 2
    assert payload["verified_by_method"] == {"manifest_anchors": 1, "source_replay_mapping": 1, "unverified": 0}
    assert payload["frame_index_coverage"] == 1.0
    assert payload["warning"] is False
    # 每候选一行：两个候选各自的 method 可被追溯。
    rows = next(value for value in payload.values() if isinstance(value, list))
    assert {row["candidate_id"]: row["method"] for row in rows} == {"c00": "manifest_anchors",
                                                                   "c01": "source_replay_mapping"}


def test_main_should_write_lineage_summary_and_warn_in_extract_mode(tmp_path, monkeypatch, capsys):
    """正常抽帧模式写 <out-dir>/lineage_summary.json；unverified 超 5% 时 stdout 打警告行。"""
    profiles, digests = lineage_profiles(tmp_path)
    (profiles["sub_video_videos"] / "c01.mp4").write_bytes(L2_BYTES)
    anchored = lineage_candidate(digests)
    unverifiable = lineage_candidate(digests)
    unverifiable["candidate_id"] = "c01"
    unverifiable["output_path"] = "data/sub_video/c01.mp4"
    # anchors 为空且清单里没有 sources：来源级证据不可用，只能 unverified。
    unverifiable["output"]["frame_mapping"] = {"anchors": [], "output_start_frame": 0,
                                              "source_start_frame": 973}
    manifest_path = tmp_path / "extract_manifest.json"
    manifest_path.write_text(json.dumps({"schema": "tensile-unified-sub-video/1",
                                         "candidates": [anchored, unverifiable]},
                                        ensure_ascii=False), encoding="utf-8")
    patch_media(monkeypatch)
    monkeypatch.setattr(frames.paths, "load_profile", lambda name: profiles)
    out_dir = tmp_path / "frames"

    rc = run_main(["--manifest", str(manifest_path), "--output", str(tmp_path / "records.jsonl"),
                   "--out-dir", str(out_dir)])

    assert rc == 0
    summary = json.loads((out_dir / "lineage_summary.json").read_text(encoding="utf-8"))
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["verified_by_method"] == {"manifest_anchors": 1, "source_replay_mapping": 0, "unverified": 1}
    assert "本批帧号覆盖率不足" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# 来源探测收窄的回归钉子：add_source_decoded_counts 只探测本次批用到的来源
# --------------------------------------------------------------------------------------
def counts_evidence(*video_ids):
    """与 source_evidence_index 同形的证据表：帧数先置 None，等待 add_source_decoded_counts 填。"""
    return {video_id: {"source_video_id": video_id, "found": True, "status": VERIFIED_REPLAY,
                       "mapping": SOURCE_MAPPING, "proof_type": SOURCE_PROOF_TYPE,
                       "receipt_sha256": SOURCE_RECEIPT, "l0_decoded": None, "l1_decoded": None}
            for video_id in video_ids}


def probe_profiles(tmp_path):
    """只给路径，不建文件：探测桩不需要真实媒体（本组用例不得碰 ffprobe）。"""
    return {"source_videos": tmp_path / "source_videos", "roi_videos": tmp_path / "roi_videos",
            "sub_video_videos": tmp_path / "sub_video_videos",
            "sub_video_manifest": tmp_path / "manifest.json"}


def spy_on_decoded_frame_count(monkeypatch, counts=None):
    """记录每一条被探测的路径，并按目录名返回桩帧数（L0=1300 / L1=1213，故意不等）。"""
    probed = []
    counts = counts or {}

    def spy(path):
        probed.append(str(path))
        directory = Path(path).parent.name
        return counts.get(directory, FAKE_TOTALS[directory])

    monkeypatch.setattr(frames, "decoded_frame_count", spy)
    return probed


PROBE_COUNTS = {"source_videos": 1300, "roi_videos": 1213}


def test_add_source_decoded_counts_should_probe_only_requested_sources(tmp_path, monkeypatch):
    """source_ids={"vA"}：只探测 vA 的 L0/L1，vB 一次都不碰且两帧数保持 None（不得伪造成相等）。"""
    evidence = counts_evidence("vA", "vB")
    probed = spy_on_decoded_frame_count(monkeypatch, counts=PROBE_COUNTS)

    frames.add_source_decoded_counts(evidence, probe_profiles(tmp_path), source_ids={"vA"})

    assert set(probed) == {str(tmp_path / "source_videos" / "vA.mp4"),
                           str(tmp_path / "roi_videos" / "vA.mp4")}
    assert evidence["vA"]["l0_decoded"] == 1300
    assert evidence["vA"]["l1_decoded"] == 1213
    assert evidence["vB"]["l0_decoded"] is None
    assert evidence["vB"]["l1_decoded"] is None


def test_add_source_decoded_counts_should_probe_every_source_when_no_subset_given(tmp_path, monkeypatch):
    """source_ids=None（批级口径）：vA/vB 的 L0/L1 都要探测并各自填上。"""
    evidence = counts_evidence("vA", "vB")
    probed = spy_on_decoded_frame_count(monkeypatch, counts=PROBE_COUNTS)

    frames.add_source_decoded_counts(evidence, probe_profiles(tmp_path), source_ids=None)

    assert set(probed) == {str(tmp_path / key / f"{video_id}.mp4")
                           for key in ("source_videos", "roi_videos") for video_id in ("vA", "vB")}
    for video_id in ("vA", "vB"):
        assert evidence[video_id]["l0_decoded"] == 1300
        assert evidence[video_id]["l1_decoded"] == 1213


def two_source_manifest(tmp_path):
    """两个来源 / 两个候选：c00→video_0001（合法 anchors），c01→video_0002（anchors 为空）。"""
    profiles = probe_profiles(tmp_path)
    digests = {}
    for key in ("source_videos", "roi_videos"):
        (tmp_path / key).mkdir()
        for video_id in ("video_0001", "video_0002"):
            payload = f"{key}-{video_id}".encode()
            (tmp_path / key / f"{video_id}.mp4").write_bytes(payload)
            digests[f"{key}:{video_id}"] = hashlib.sha256(payload).hexdigest()
    videos = profiles["sub_video_videos"]
    videos.mkdir()
    for name in ("c00.mp4", "c01.mp4"):
        (videos / name).write_bytes(L2_BYTES)
    digests["l2"] = hashlib.sha256(L2_BYTES).hexdigest()

    def candidate_for(video_id, candidate_id, filename, anchors=None):
        clip = lineage_candidate({"source_videos": digests[f"source_videos:{video_id}"],
                                  "roi_videos": digests[f"roi_videos:{video_id}"],
                                  "l2": digests["l2"]})
        clip["source_video_id"] = video_id
        clip["candidate_id"] = candidate_id
        clip["output_path"] = f"data/sub_video/{filename}"
        if anchors is not None:
            clip["output"]["frame_mapping"] = {"anchors": anchors, "output_start_frame": 0,
                                               "source_start_frame": 973}
        return clip

    first = candidate_for("video_0001", "c00", "c00.mp4")
    second = candidate_for("video_0002", "c01", "c01.mp4", anchors=[])
    manifest = {"schema": "tensile-unified-sub-video/1", "candidates": [first, second],
                "sources": [{"video_id": video_id,
                             "frame_preserving_replay": {"video_id": video_id, "status": VERIFIED_REPLAY,
                                                         "mapping": SOURCE_MAPPING,
                                                         "proof_type": SOURCE_PROOF_TYPE,
                                                         "receipt_sha256": SOURCE_RECEIPT}}
                            for video_id in ("video_0001", "video_0002")]}
    manifest_path = tmp_path / "two_source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return profiles, manifest_path


def test_main_should_probe_only_selected_sources_in_extract_mode(tmp_path, monkeypatch):
    """只选 c00 跑：不得探测 video_0002 的 L0/L1，本批计数也不含未被选来源的候选。"""
    profiles, manifest_path = two_source_manifest(tmp_path)
    patch_media(monkeypatch)
    probed = spy_on_decoded_frame_count(monkeypatch, counts={"source_videos": 1300, "roi_videos": 1300,
                                                             "sub_video_videos": FAKE_TOTALS["sub_video_videos"]})
    monkeypatch.setattr(frames.paths, "load_profile", lambda name: profiles)
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(["c00"]), encoding="utf-8")
    out_dir = tmp_path / "frames"

    rc = run_main(["--manifest", str(manifest_path), "--candidate-ids", str(selection),
                   "--output", str(tmp_path / "records.jsonl"), "--out-dir", str(out_dir)])

    assert rc == 0
    assert [path for path in probed if "video_0002" in path] == []
    assert {path for path in probed if "source_videos" in path or "roi_videos" in path} == {
        str(tmp_path / "source_videos" / "video_0001.mp4"),
        str(tmp_path / "roi_videos" / "video_0001.mp4")}
    summary = json.loads((out_dir / "lineage_summary.json").read_text(encoding="utf-8"))
    assert summary["total"] == 1
    assert summary["verified_by_method"] == {"manifest_anchors": 1, "source_replay_mapping": 0, "unverified": 0}
    records = frames.read_records(tmp_path / "records.jsonl")
    assert [record["candidate_id"] for record in records] == ["c00"]
    assert records[0]["verification"]["method"] == "manifest_anchors"


def test_verify_lineage_should_explicitly_reject_legacy_v2_record_schema():
    """旧 v2 记录 schema 必须被显式拒绝，报错点名当前 v3 schema。"""
    record = lineage_record()
    record["record_schema"] = "five-label-input-record/2"

    reasons = frames.verify_lineage(record)
    assert_reasons_require(reasons, "record_schema", frames.RECORD_SCHEMA)


@pytest.mark.parametrize("legacy_key", ["media_to_clip", "source_to_media", "roi_to_source"])
def test_verify_lineage_should_explicitly_reject_legacy_mapping_keys(legacy_key):
    """即使 record_schema 写成 v3，只要 frame_index_mapping 含旧键名也必须显式拒绝。"""
    frame = frame_entry(0, 0, 973, 973)
    frame["frame_index_mapping"][legacy_key] = {"kind": "manifest_replay", "offset": 973, "reason": None}
    record = lineage_record(frames_override=[frame])

    reasons = frames.verify_lineage(record)
    assert_reasons_require(reasons, "legacy", legacy_key)


def test_read_records_should_explicitly_reject_legacy_v2_schema(tmp_path):
    """read_records 读取旧 five-label-input-record/2 记录必须抛 InputError。"""
    record = lineage_record()
    record["record_schema"] = "five-label-input-record/2"
    path = tmp_path / "legacy_v2.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(InputError) as excinfo:
        frames.read_records(path)

    message = str(excinfo.value)
    assert "five-label-input-record/2" in message
    assert frames.RECORD_SCHEMA in message


@pytest.mark.parametrize("legacy_key", ["media_to_clip", "source_to_media", "roi_to_source"])
def test_read_records_should_explicitly_reject_legacy_mapping_keys(tmp_path, legacy_key):
    """read_records 读到旧映射节点键名必须抛 InputError。"""
    frame = frame_entry(0, 0, 973, 973)
    frame["frame_index_mapping"][legacy_key] = {"kind": "manifest_replay", "offset": 973, "reason": None}
    record = lineage_record(frames_override=[frame])
    path = tmp_path / f"legacy_{legacy_key}.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(InputError) as excinfo:
        frames.read_records(path)

    message = str(excinfo.value)
    assert legacy_key in message
    assert frames.RECORD_SCHEMA in message


# --------------------------------------------------------------------------------------
# 8-frame evenly_spaced_inclusive alignment, fail_closed short clips, and resize=null
# --------------------------------------------------------------------------------------
def test_default_frame_count_and_constants_should_align_to_eight_frame_contract():
    assert frames.DEFAULT_CLIPS_PER_RECORD == 8
    assert frames.SAMPLING_RULE == "evenly_spaced_inclusive"
    assert frames.SHORT_CLIP_POLICY == "fail_closed"
    assert frames.DEFAULT_RESIZE is None
    assert frames.CLIP_TO_MODEL_INPUT["resize"] is None
    assert frames.CLIP_TO_MODEL_INPUT["sampling_rule"] == "evenly_spaced_inclusive"
    assert frames.CLIP_TO_MODEL_INPUT["short_clip_policy"] == "fail_closed"


@pytest.mark.parametrize("total_frames,expected", [
    (8, [0, 1, 2, 3, 4, 5, 6, 7]),
    (9, [0, 1, 2, 3, 5, 6, 7, 8]),
    (45, [0, 6, 13, 19, 25, 31, 38, 44]),
    (150, [0, 21, 43, 64, 85, 106, 128, 149]),
    (240, [0, 34, 68, 102, 137, 171, 205, 239]),
    (600, [0, 86, 171, 257, 342, 428, 513, 599]),
])
def test_sample_frame_indices_should_compute_deterministic_evenly_spaced_inclusive(total_frames, expected):
    indices = frames.sample_frame_indices(total_frames)

    assert indices == expected
    assert len(indices) == 8
    assert indices[0] == 0
    assert indices[-1] == total_frames - 1
    assert indices == sorted(set(indices))
    assert all(isinstance(idx, int) and not isinstance(idx, bool) for idx in indices)


@pytest.mark.parametrize("total_frames,num_frames", [
    (1, 8),
    (3, 8),
    (7, 8),
    (4, 5),
])
def test_sample_frame_indices_should_fail_closed_on_short_clip(total_frames, num_frames):
    with pytest.raises(InputError) as excinfo:
        frames.sample_frame_indices(total_frames, num_frames)

    msg = str(excinfo.value)
    assert "fail_closed" in msg
    assert str(total_frames) in msg
    assert str(num_frames) in msg


@pytest.mark.parametrize("kwargs", [
    {"total_frames": 0},
    {"total_frames": -5},
    {"total_frames": True},
    {"total_frames": 10, "num_frames": 0},
    {"total_frames": 10, "num_frames": False},
    {"total_frames": 10, "sampling_rule": "uniform_bucket_midpoint"},
    {"total_frames": 10, "short_clip_policy": "pad_last"},
])
def test_sample_frame_indices_should_reject_invalid_parameters(kwargs):
    with pytest.raises(InputError):
        frames.sample_frame_indices(**kwargs)


def test_extract_record_should_fail_closed_and_not_invoke_ffmpeg_on_short_clip(tmp_path, monkeypatch):
    profiles, digests = lineage_profiles(tmp_path)
    patch_media(monkeypatch, decoded={"sub_video_videos": 7})

    def boom(*args, **kwargs):
        raise AssertionError("_extract_frames must not run for a short clip refused by fail_closed")

    monkeypatch.setattr(frames, "_extract_frames", boom)

    with pytest.raises(InputError) as excinfo:
        frames.extract_record(lineage_candidate(digests), profiles, tmp_path / "frames",
                              manifest_sha256="b" * 64)

    assert "fail_closed" in str(excinfo.value)
    assert "c00" in str(excinfo.value)


def test_main_should_default_to_eight_frames_with_resize_null(tmp_path, monkeypatch):
    profiles, manifest_path = scan_manifest(tmp_path)
    patch_media(monkeypatch)
    monkeypatch.setattr(frames.paths, "load_profile", lambda name: profiles)
    output = tmp_path / "records.jsonl"
    out_dir = tmp_path / "frames"

    rc = run_main(["--manifest", str(manifest_path), "--output", str(output), "--out-dir", str(out_dir)])

    assert rc == 0
    records = frames.read_records(output)
    assert len(records) == 2
    for rec in records:
        assert len(rec["frames"]) == 8
        assert rec["sampling"]["target_frame_count"] == 8
        assert rec["sampling"]["sampling_rule"] == "evenly_spaced_inclusive"
        assert rec["sampling"]["short_clip_policy"] == "fail_closed"
        assert rec["sampling"]["resize"] is None
        for frame in rec["frames"]:
            assert frame["frame_index_mapping"]["clip_to_model_input"]["resize"] is None
