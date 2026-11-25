"""Offline regression tests for DEC-007 exclusion guard and frozen §5 eval subsets.

No media files are opened and no model is executed.
"""
from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from script.five_label_eval import build_manifest, frames, infer, manifest_convert, score
from script.five_label_eval.exclusions import (
    DEFAULT_EXCLUSIONS_PATH,
    EVAL_SUBSET_SCHEMA,
    REPO_ROOT,
    load_candidate_ids_input,
    load_dev_exclusions,
)
from script.five_label_eval.freeze_subsets import _serialize, build_frozen_subsets
from script.five_label_eval.score import InputError


def _synthetic_candidate(cid: str, source_video_id: str, idx: int = 1) -> dict:
    return {
        "candidate_id": cid,
        "source_video_id": source_video_id,
        "output_path": f"data/sub_video/{cid}.mp4",
        "output": {
            "sha256": f"{idx:064x}",
            "media": {"width": 320, "height": 240, "fps": 30.0, "total_frames": 60},
            "frame_mapping": {"anchors": [], "output_start_frame": 100, "source_start_frame": 900},
            "frame_preserving_replay": {"status": "verified_frame_preserving_replay"},
        },
        "source_frame_range": [900, 959],
    }


def _synthetic_review_row(
    cid: str,
    source_id: str,
    *,
    source_type: str = "real",
    idx: int = 1,
) -> dict:
    return {
        "manifest_sha256": "a" * 64,
        "candidate_id": cid,
        "clip_sha256": f"{idx:064x}",
        "source_id": source_id,
        "source_type": source_type,
        "review_id": f"rev-{idx}",
        "review_status": "confirmed",
        "labels": {"断裂状态": "未断裂"},
    }


# --------------------------------------------------------------------------- #
# 1. DEC-007 exclusions loader & guard unit tests
# --------------------------------------------------------------------------- #


def test_load_dev_exclusions_matches_dec007_contract() -> None:
    ex = load_dev_exclusions(DEFAULT_EXCLUSIONS_PATH)
    assert ex.decision_id == "DEC-007"
    assert ex.excluded_source_ids == frozenset({"video_0006", "video_0079"})
    assert len(ex.excluded_candidate_ids) == 20
    assert {
        "video_0006_pre_06",
        "video_0006_pre_13",
        "video_0079_fracture_01",
    }.issubset(ex.excluded_candidate_ids)
    assert len(ex.isolated_virtual_ids) == 15
    assert "metal_round_ductile_baseline_v1" in ex.isolated_virtual_ids
    assert "polymer_yellow_film_grip_root_baseline_v2" in ex.isolated_virtual_ids


def test_load_dev_exclusions_fails_closed_on_missing_or_bad_schema(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="cannot read"):
        load_dev_exclusions(tmp_path / "missing.json")

    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "wrong/1"}\n', encoding="utf-8")
    with pytest.raises(InputError, match="unexpected schema"):
        load_dev_exclusions(bad)


# --------------------------------------------------------------------------- #
# 2. Entry-point DEC-007 guards (manifest_convert / build_manifest / frames / infer / score)
# --------------------------------------------------------------------------- #


def test_manifest_convert_filters_excluded_sources_on_full_conversion() -> None:
    manifest_obj = {
        "schema": "synthetic/1",
        "candidates": [
            _synthetic_candidate("video_0001_pre_01", "video_0001", 1),
            _synthetic_candidate("video_0006_pre_06", "video_0006", 2),
            _synthetic_candidate("video_0006_pre_13", "video_0006", 3),
            _synthetic_candidate("video_0079_fracture_01", "video_0079", 4),
            _synthetic_candidate("video_0010_pre_01", "video_0010", 5),  # fixed test source, allowed
        ],
        "sources": [],
    }
    raw = json.dumps(manifest_obj, sort_keys=True).encode("utf-8")
    converted = manifest_convert.convert(manifest_obj, raw, manifest_version="guard-test/1")
    got_ids = [s["candidate_id"] for s in converted["samples"]]
    assert got_ids == ["video_0001_pre_01", "video_0010_pre_01"]
    assert converted["dev_exclusions"]["decision_id"] == "DEC-007"
    assert converted["dev_exclusions"]["filtered_count"] == 3


@pytest.mark.parametrize(
    "bad_cid,bad_source",
    [
        ("video_0006_pre_06", "video_0006"),
        ("video_0006_pre_13", "video_0006"),
        ("video_0079_fracture_01", "video_0079"),
    ],
)
def test_manifest_convert_rejects_explicit_excluded_candidate_id(bad_cid: str, bad_source: str) -> None:
    manifest_obj = {
        "schema": "synthetic/1",
        "candidates": [
            _synthetic_candidate("video_0001_pre_01", "video_0001", 1),
            _synthetic_candidate(bad_cid, bad_source, 2),
        ],
        "sources": [],
    }
    raw = json.dumps(manifest_obj, sort_keys=True).encode("utf-8")
    with pytest.raises(InputError, match="DEC-007"):
        manifest_convert.convert(
            manifest_obj,
            raw,
            candidate_ids=["video_0001_pre_01", bad_cid],
            manifest_version="guard-test/1",
        )


def test_build_manifest_rejects_excluded_real_and_isolated_virtual_but_allows_clean() -> None:
    rows = [
        _synthetic_review_row("video_0001_pre_01", "video_0001", idx=1),
        _synthetic_review_row("video_0006_pre_06", "video_0006", idx=2),
        _synthetic_review_row("video_0079_fracture_01", "video_0079", idx=3),
        _synthetic_review_row(
            "metal_round_ductile_baseline_v1_window_01",
            "metal_round_ductile_baseline_v1",
            source_type="virtual",
            idx=4,
        ),
        _synthetic_review_row("video_0010_pre_01", "video_0010", idx=5),
    ]

    # Clean samples pass without error.
    draft = build_manifest.build_draft(rows, ["video_0001_pre_01", "video_0010_pre_01"], "clean/1")
    assert [s["candidate_id"] for s in draft["samples"]] == ["video_0001_pre_01", "video_0010_pre_01"]

    for bad_cid in (
        "video_0006_pre_06",
        "video_0079_fracture_01",
        "metal_round_ductile_baseline_v1_window_01",
    ):
        with pytest.raises(InputError, match="DEC-007"):
            build_manifest.build_draft(rows, ["video_0001_pre_01", bad_cid], "bad/1")


def test_score_and_infer_reject_manifest_with_excluded_samples() -> None:
    bad_manifest = {
        "manifest_version": "bad-score/1",
        "samples": [
            {
                "manifest_sha256": "a" * 64,
                "candidate_id": "video_0006_pre_13",
                "clip_sha256": "b" * 64,
                "source_id": "video_0006",
                "source_type": "real",
                "review_id": None,
            }
        ],
    }
    with pytest.raises(InputError, match="DEC-007"):
        score.prepare(bad_manifest, [], [])
    with pytest.raises(InputError, match="DEC-007"):
        infer.plan_predictions([], bad_manifest, "run-1", "prompt-1")


def test_frames_cli_rejects_excluded_candidate_ids_fail_closed(tmp_path: Path) -> None:
    manifest_obj = {
        "schema": "synthetic/1",
        "candidates": [
            _synthetic_candidate("video_0006_pre_06", "video_0006", 1),
        ],
        "sources": [],
    }
    manifest_file = tmp_path / "manifest.json"
    ids_file = tmp_path / "ids.json"
    manifest_file.write_text(json.dumps(manifest_obj), encoding="utf-8")
    ids_file.write_text('["video_0006_pre_06"]\n', encoding="utf-8")

    err = io.StringIO()
    with redirect_stderr(err):
        rc = frames.main(
            [
                "--manifest",
                str(manifest_file),
                "--candidate-ids",
                str(ids_file),
                "--output",
                str(tmp_path / "out.jsonl"),
                "--out-dir",
                str(tmp_path / "frames"),
            ]
        )
    assert rc == 2
    assert "DEC-007" in err.getvalue()


# --------------------------------------------------------------------------- #
# 3. Frozen §5 evaluation subsets integrity & reproducibility tests
# --------------------------------------------------------------------------- #


def test_frozen_eval_subsets_match_deterministic_rebuild_and_contract() -> None:
    eval_dev_path = REPO_ROOT / "data/eval-subsets/eval-dev-v1.json"
    eval_test_path = REPO_ROOT / "data/eval-subsets/eval-test-v1.json"
    assert eval_dev_path.is_file(), f"missing {eval_dev_path}"
    assert eval_test_path.is_file(), f"missing {eval_test_path}"

    expected_dev, expected_test = build_frozen_subsets()
    assert eval_dev_path.read_bytes() == _serialize(expected_dev).encode("utf-8")
    assert eval_test_path.read_bytes() == _serialize(expected_test).encode("utf-8")

    dev_obj = json.loads(eval_dev_path.read_text(encoding="utf-8"))
    test_obj = json.loads(eval_test_path.read_text(encoding="utf-8"))
    ex = load_dev_exclusions(DEFAULT_EXCLUSIONS_PATH)

    # Schema & zero overlap with DEC-007 exclusions
    for obj in (dev_obj, test_obj):
        assert obj["schema"] == EVAL_SUBSET_SCHEMA
        assert obj["candidate_ids"] == sorted(obj["candidate_ids"])
        assert len(obj["candidate_ids"]) == len(set(obj["candidate_ids"]))
        assert ex.find_violations(obj["candidate_ids"]) == []
        assert set(obj["source_ids"]).isdisjoint(ex.excluded_source_ids)
        assert set(obj["candidate_ids"]).isdisjoint(ex.excluded_candidate_ids)

    # Specifically verify the 3 B2 confirmed clips from excluded sources are absent
    for leaked in ("video_0006_pre_06", "video_0006_pre_13", "video_0079_fracture_01"):
        assert leaked not in dev_obj["candidate_ids"]
        assert leaked not in test_obj["candidate_ids"]

    # Zero overlap between dev and test subsets
    assert set(dev_obj["candidate_ids"]).isdisjoint(test_obj["candidate_ids"])
    assert set(dev_obj["source_ids"]).isdisjoint(test_obj["source_ids"])

    # Exact counts and width-bucket / fold coverage
    assert dev_obj["summary"]["candidate_count"] == 210
    assert dev_obj["summary"]["source_count"] == 87
    assert dev_obj["summary"]["batch_composition"] == {"B0": 32, "B2_clean": 177, "trial_outside_batch": 1}
    assert dev_obj["summary"]["size_buckets"] == {
        "w_le_200": {"candidates": 112, "sources": 48},
        "w_200_400": {"candidates": 42, "sources": 20},
        "w_gt_400": {"candidates": 56, "sources": 19},
    }
    assert dev_obj["summary"]["folds"] == {
        "0": {"candidates": 69, "sources": 29},
        "1": {"candidates": 73, "sources": 29},
        "2": {"candidates": 68, "sources": 29},
    }

    assert test_obj["summary"]["candidate_count"] == 314
    assert test_obj["summary"]["source_count"] == 21
    assert test_obj["summary"]["batch_composition"] == {"B1": 314}
    assert test_obj["summary"]["size_buckets"] == {
        "w_le_200": {"candidates": 90, "sources": 7},
        "w_200_400": {"candidates": 140, "sources": 8},
        "w_gt_400": {"candidates": 84, "sources": 6},
    }

    # Every width bucket has >= 3 sources in both frozen subsets
    for obj in (dev_obj, test_obj):
        for bucket, stats in obj["summary"]["size_buckets"].items():
            assert stats["sources"] >= 3, f"{obj['subset_id']}:{bucket} has <3 sources"

    # Both frozen subset files work directly with load_candidate_ids_input()
    assert load_candidate_ids_input(eval_dev_path) == dev_obj["candidate_ids"]
    assert load_candidate_ids_input(eval_test_path) == test_obj["candidate_ids"]


def test_manifest_convert_cli_accepts_frozen_eval_subset_directly(tmp_path: Path) -> None:
    out = tmp_path / "dev-scoring-manifest.json"
    rc = manifest_convert.main(
        [
            "--input",
            str(REPO_ROOT / "data/sub_video/manifest.json"),
            "--candidate-ids",
            str(REPO_ROOT / "data/eval-subsets/eval-dev-v1.json"),
            "--manifest-version",
            "eval-dev-v1-test",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["samples"]) == 210
    assert payload["dev_exclusions"]["decision_id"] == "DEC-007"
    assert payload["dev_exclusions"]["sha256"] == hashlib.sha256(DEFAULT_EXCLUSIONS_PATH.read_bytes()).hexdigest()
