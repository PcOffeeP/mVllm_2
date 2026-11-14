"""Red-phase tests for the frozen `manifest_convert` contract.

Every fixture here is synthetic: no media file is opened, nothing under `data/`
is read, and the only filesystem use is pytest's `tmp_path`.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from script.five_label_eval import manifest_convert
from script.five_label_eval.score import IDENTITY, InputError, prepare

HEX64 = re.compile(r"^[a-f0-9]{64}$")


def candidate(index, source_video_id="video_0001", clip_sha256=None):
    """Build one synthetic candidate shaped like a `data/sub_video/manifest.json` entry."""
    cid = f"c{index:02d}"
    return {
        "candidate_id": cid,
        "source_video_id": source_video_id,
        "output_path": f"data/sub_video/{cid}.mp4",
        "output": {
            "sha256": clip_sha256 if clip_sha256 is not None else f"{index + 1:064x}",
            "media": {"width": 320, "height": 240, "fps": 30.0, "total_frames": 60},
            "frame_mapping": {"anchors": [], "output_start_frame": 100, "source_start_frame": 900},
            "frame_preserving_replay": {"status": "verified_frame_preserving_replay"},
        },
        "source_frame_range": [900, 959],
    }


def manifest_obj(candidates):
    return {"schema": "synthetic/1", "candidates": candidates, "sources": []}


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")


def convert(candidates, **kwargs):
    """Call `convert` with a synthetic manifest and its exact bytes."""
    obj = manifest_obj(candidates)
    kwargs.setdefault("manifest_version", "test/1")
    return manifest_convert.convert(obj, encode(obj), **kwargs)


def test_convert_should_mark_every_sample_source_type_real():
    draft = convert([candidate(0), candidate(1)])

    assert [sample["source_type"] for sample in draft["samples"]] == ["real", "real"]


def test_source_type_rationale_should_name_field_and_candidate_count():
    obj = manifest_obj([candidate(0), candidate(1), candidate(2)])

    rationale = manifest_convert.source_type_rationale(obj)

    assert "source_type" in rationale
    assert "3" in rationale


def test_source_type_rationale_should_reject_unexpected_source_video_id():
    obj = manifest_obj([candidate(0, source_video_id="clip_00")])

    with pytest.raises(InputError):
        manifest_convert.source_type_rationale(obj)


def test_convert_should_emit_identity_fields_plus_explicit_null_review_id():
    draft = convert([candidate(0)])

    sample = draft["samples"][0]
    assert set(sample) == set(IDENTITY) | {"review_id"}
    assert sample["review_id"] is None


def test_convert_should_format_digests_and_source_binding_from_manifest_bytes():
    clips = [candidate(0), candidate(1)]
    obj = manifest_obj(clips)
    raw = encode(obj)

    draft = manifest_convert.convert(obj, raw, manifest_version="test/1")

    expected_manifest_sha256 = hashlib.sha256(raw).hexdigest()
    for sample, clip in zip(draft["samples"], clips):
        assert sample["manifest_sha256"] == expected_manifest_sha256
        assert HEX64.match(sample["manifest_sha256"])
        assert HEX64.match(sample["clip_sha256"])
        assert sample["clip_sha256"] == clip["output"]["sha256"]
        assert sample["candidate_id"] == clip["candidate_id"]
        assert sample["source_id"] == clip["source_video_id"]
        assert sample["source_type"] == "real"


def test_convert_should_keep_manifest_version_when_supplied():
    draft = convert([candidate(0)], manifest_version="eval/1")

    assert draft["manifest_version"] == "eval/1"


def test_convert_should_truncate_to_limit_in_manifest_order():
    draft = convert([candidate(0), candidate(1), candidate(2)], limit=2)

    assert [sample["candidate_id"] for sample in draft["samples"]] == ["c00", "c01"]


def test_convert_should_follow_given_candidate_order():
    draft = convert([candidate(0), candidate(1), candidate(2)], candidate_ids=["c02", "c00"])

    assert [sample["candidate_id"] for sample in draft["samples"]] == ["c02", "c00"]


def test_convert_should_apply_limit_to_explicit_selection_length():
    draft = convert(
        [candidate(0), candidate(1), candidate(2)],
        candidate_ids=["c02", "c00", "c01"],
        limit=2,
    )

    assert [sample["candidate_id"] for sample in draft["samples"]] == ["c02", "c00"]


def test_convert_output_should_pass_score_prepare_validation():
    draft = convert([candidate(0), candidate(1)], manifest_version="eval/1")

    prepare(draft, [], [])  # must not raise


def test_convert_should_reject_unknown_candidate_id():
    with pytest.raises(InputError):
        convert([candidate(0), candidate(1)], candidate_ids=["c00", "nope"])


def test_convert_should_reject_duplicate_candidate_ids():
    with pytest.raises(InputError):
        convert([candidate(0), candidate(1)], candidate_ids=["c00", "c00"])


@pytest.mark.parametrize("clip_sha256", ["abc", "A" * 64, "g" * 64, ""])
def test_convert_should_reject_malformed_clip_sha256(clip_sha256):
    with pytest.raises(InputError):
        convert([candidate(0, clip_sha256=clip_sha256)])


def test_convert_should_reject_candidate_without_clip_sha256():
    broken = candidate(0)
    del broken["output"]["sha256"]

    with pytest.raises(InputError):
        convert([broken])


@pytest.mark.parametrize("candidate_ids", [[], "c00"])
def test_convert_should_reject_invalid_candidate_ids_argument(candidate_ids):
    with pytest.raises(InputError):
        convert([candidate(0), candidate(1)], candidate_ids=candidate_ids)


@pytest.mark.parametrize("limit", [0, -1])
def test_convert_should_reject_non_positive_limit(limit):
    with pytest.raises(InputError):
        convert([candidate(0), candidate(1)], limit=limit)
