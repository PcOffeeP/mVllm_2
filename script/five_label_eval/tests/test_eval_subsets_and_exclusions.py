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
    load_candidate_selection,
    load_dev_exclusions,
)
from script.five_label_eval.freeze_subsets import _serialize, build_frozen_subsets, verify_frozen_subsets
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

    verified = verify_frozen_subsets(REPO_ROOT / "data/eval-subsets")
    assert [count for _path, _digest, count in verified] == [210, 314]

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


def test_frozen_subset_rejects_mismatched_manifest_sha256_before_writing(tmp_path: Path) -> None:
    """Finding 1 regression: frozen eval subsets must bind manifest_sha256 fail-closed."""
    real_manifest = json.loads((REPO_ROOT / "data/sub_video/manifest.json").read_text(encoding="utf-8"))
    # Mutate video_0010_pre_01 clip sha256 while preserving candidate IDs -> different manifest_sha256.
    for row in real_manifest["candidates"]:
        if row["candidate_id"] == "video_0010_pre_01":
            row["output"]["sha256"] = "0" * 64
            break
    tampered_manifest = tmp_path / "tampered-manifest.json"
    tampered_manifest.write_text(json.dumps(real_manifest, ensure_ascii=False), encoding="utf-8")

    # manifest_convert must reject before writing output
    out_manifest = tmp_path / "should-not-exist.json"
    err = io.StringIO()
    with redirect_stderr(err):
        rc = manifest_convert.main(
            [
                "--input",
                str(tampered_manifest),
                "--candidate-ids",
                str(REPO_ROOT / "data/eval-subsets/eval-test-v1.json"),
                "--manifest-version",
                "tampered-test",
                "--output",
                str(out_manifest),
            ]
        )
    assert rc == 2
    assert "manifest_sha256" in err.getvalue()
    assert not out_manifest.exists()

    # frames CLI must also reject before touching media
    err2 = io.StringIO()
    with redirect_stderr(err2):
        rc2 = frames.main(
            [
                "--manifest",
                str(tampered_manifest),
                "--candidate-ids",
                str(REPO_ROOT / "data/eval-subsets/eval-test-v1.json"),
                "--output",
                str(tmp_path / "frames.jsonl"),
                "--out-dir",
                str(tmp_path / "frames"),
            ]
        )
    assert rc2 == 2
    assert "manifest_sha256" in err2.getvalue()

    # load_candidate_selection exposes expected_manifest_sha256 and raises on mismatch
    sel = load_candidate_selection(REPO_ROOT / "data/eval-subsets/eval-test-v1.json")
    assert sel.subset_id == "eval-test-v1"
    with pytest.raises(InputError, match="manifest_sha256"):
        sel.assert_manifest_sha256("f" * 64, context="unit")


def test_frozen_v1_verification_survives_appended_b3_reviews(tmp_path: Path) -> None:
    """Finding 2 regression: appending later ReviewApp-matching B3 confirmed reviews must not break v1 --verify."""
    from script.subvideo_review.server import ReviewApp

    app = ReviewApp(REPO_ROOT)
    b3_cand = app.candidates["video_0001_pre_01"]
    reviews_obj = json.loads((REPO_ROOT / "data/subvideo-review/reviews.json").read_text(encoding="utf-8"))
    # Append a ReviewApp.matches-valid B3 confirmed review for video_0001_pre_01 after v1 freeze cutoff.
    b3_row = {
        "candidate_id": b3_cand["candidate_id"],
        "clip_sha256": b3_cand["clip_sha256"],
        "review_subject_sha256": b3_cand["review_subject_sha256"],
        "source_id": b3_cand["source_id"],
        "source_type": b3_cand["source_type"],
        "manifest_sha256": app.manifest_sha256,
        "review_id": "simulated-b3-rev-1",
        "review_status": "confirmed",
        "created_at": "2026-11-26T00:00:00+00:00",
        "labels": {"断裂状态": "未断裂"},
    }
    assert ReviewApp.matches(b3_row, b3_cand)
    reviews_obj["revisions"].append(b3_row)
    extended_reviews = tmp_path / "reviews-with-b3.json"
    extended_reviews.write_text(json.dumps(reviews_obj, ensure_ascii=False), encoding="utf-8")

    # With cutoff enforced, v1 verification still passes with exact 210 / 314 counts.
    results = verify_frozen_subsets(
        REPO_ROOT / "data/eval-subsets",
        reviews_path=extended_reviews,
    )
    assert [count for _path, _digest, count in results] == [210, 314]

    # Without cutoff (cutoff=None), the appended ReviewApp-matching B3 revision IS picked up (211 dev clips).
    dev_unbounded, _test_unbounded = build_frozen_subsets(
        reviews_path=extended_reviews,
        reviews_cutoff_created_at=None,
        enforce_v1_pins=False,
    )
    assert dev_unbounded["summary"]["candidate_count"] == 211
    assert "video_0001_pre_01" in dev_unbounded["candidate_ids"]


def test_empty_custom_exclusions_file_cannot_bypass_official_dec007(tmp_path: Path) -> None:
    """Finding 3 regression: custom --exclusions can only extend official DEC-007, never weaken it."""
    empty_excl = tmp_path / "empty-dec007.json"
    empty_excl.write_text(
        json.dumps(
            {
                "schema": "tensile-dev-exclusions/1",
                "decision_id": "DEC-007",
                "excluded_dev_sources": [],
                "isolated_virtual_videos": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    merged = load_dev_exclusions(empty_excl)
    assert "video_0006" in merged.excluded_source_ids
    assert "video_0079" in merged.excluded_source_ids
    assert "video_0006_pre_06" in merged.excluded_candidate_ids

    # Passing empty_excl via CLI must still reject video_0006_pre_06 without --allow-excluded
    ids_file = tmp_path / "bad-ids.json"
    ids_file.write_text('["video_0006_pre_06"]\n', encoding="utf-8")
    out_file = tmp_path / "out.json"
    err = io.StringIO()
    with redirect_stderr(err):
        rc = manifest_convert.main(
            [
                "--input",
                str(REPO_ROOT / "data/sub_video/manifest.json"),
                "--candidate-ids",
                str(ids_file),
                "--exclusions",
                str(empty_excl),
                "--manifest-version",
                "bypass-attempt/1",
                "--output",
                str(out_file),
            ]
        )
    assert rc == 2
    assert "DEC-007" in err.getvalue()
    assert not out_file.exists()


def test_freeze_rejects_isolated_confirmations_when_label_rules_change(tmp_path: Path) -> None:
    """Round-2 Finding 1 regression: changing docs/label.md must invalidate review_subject_sha256."""
    import shutil

    clone = tmp_path / "repo"
    (clone / "docs").mkdir(parents=True)
    (clone / "data/sub_video").mkdir(parents=True)
    (clone / "data/subvideo-review").mkdir(parents=True)
    (clone / "data/splits/three-fold").mkdir(parents=True)

    # Copy required inputs verbatim, then mutate docs/label.md so ReviewApp isolates all old reviews.
    shutil.copy2(REPO_ROOT / "data/sub_video/manifest.json", clone / "data/sub_video/manifest.json")
    shutil.copy2(REPO_ROOT / "data/subvideo-review/reviews.json", clone / "data/subvideo-review/reviews.json")
    shutil.copy2(REPO_ROOT / "data/subvideo-review/batches.json", clone / "data/subvideo-review/batches.json")
    shutil.copy2(REPO_ROOT / "data/splits/dev-exclusions.json", clone / "data/splits/dev-exclusions.json")
    for p in (REPO_ROOT / "data/splits/three-fold").glob("*.json"):
        shutil.copy2(p, clone / "data/splits/three-fold" / p.name)
    label_text = (REPO_ROOT / "docs/label.md").read_text(encoding="utf-8")
    (clone / "docs/label.md").write_text(label_text + "\n<!-- rule-change -->\n", encoding="utf-8")

    # Even with enforce_v1_pins=False, ReviewApp.matches isolates all old revisions -> empty -> fail-closed!
    with pytest.raises(InputError, match="empty eval subset"):
        build_frozen_subsets(repo_root=clone, enforce_v1_pins=False)


def test_freeze_and_verify_reject_tampered_manifest_and_empty_v1(tmp_path: Path) -> None:
    """Round-2 Finding 2 regression: manifest digest drift or empty v1 files fail closed."""
    tampered_manifest = tmp_path / "manifest.json"
    tampered_manifest.write_bytes((REPO_ROOT / "data/sub_video/manifest.json").read_bytes() + b"\n")

    with pytest.raises(InputError, match="empty eval subset"):
        build_frozen_subsets(manifest_path=tampered_manifest)

    # Forged empty v1 files must fail verify_frozen_subsets independently of disk content.
    forged_dir = tmp_path / "forged"
    forged_dir.mkdir()
    for name, sid in (("eval-dev-v1.json", "eval-dev-v1"), ("eval-test-v1.json", "eval-test-v1")):
        (forged_dir / name).write_text(
            json.dumps(
                {
                    "schema": EVAL_SUBSET_SCHEMA,
                    "subset_id": sid,
                    "inputs": {"manifest_sha256": "0" * 64},
                    "source_ids": [],
                    "candidate_ids": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
    with pytest.raises(InputError, match="pinned v1 input"):
        verify_frozen_subsets(forged_dir)


def test_manifest_convert_forbids_limit_with_frozen_eval_subset(tmp_path: Path) -> None:
    """Round-2 Advisory regression: --limit must not silently truncate a frozen eval subset."""
    out = tmp_path / "truncated.json"
    err = io.StringIO()
    with redirect_stderr(err):
        rc = manifest_convert.main(
            [
                "--input",
                str(REPO_ROOT / "data/sub_video/manifest.json"),
                "--candidate-ids",
                str(REPO_ROOT / "data/eval-subsets/eval-test-v1.json"),
                "--limit",
                "1",
                "--manifest-version",
                "truncated-test/1",
                "--output",
                str(out),
            ]
        )
    assert rc == 2
    assert "--limit" in err.getvalue()
    assert not out.exists()


def test_frozen_subset_loader_rejects_member_substitution_with_same_count(tmp_path: Path) -> None:
    """Round-3 Finding 1 regression: swapping a dev clip for a test clip inside eval-dev-v1 fails closed."""
    dev_obj = json.loads((REPO_ROOT / "data/eval-subsets/eval-dev-v1.json").read_text(encoding="utf-8"))
    # Swap one valid dev clip with a sealed test clip (preserving 210 count and manifest_sha256).
    cids = list(dev_obj["candidate_ids"])
    assert "video_0001_fracture_02" in cids
    cids[cids.index("video_0001_fracture_02")] = "video_0010_pre_01"
    dev_obj["candidate_ids"] = sorted(cids)
    tampered = tmp_path / "tampered-eval-dev-v1.json"
    tampered.write_text(json.dumps(dev_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(InputError, match="member fingerprint mismatch"):
        load_candidate_selection(tampered)

    out = tmp_path / "should-not-write.json"
    err = io.StringIO()
    with redirect_stderr(err):
        rc = manifest_convert.main(
            [
                "--input",
                str(REPO_ROOT / "data/sub_video/manifest.json"),
                "--candidate-ids",
                str(tampered),
                "--manifest-version",
                "tampered-dev/1",
                "--output",
                str(out),
            ]
        )
    assert rc == 2
    assert "member fingerprint mismatch" in err.getvalue()
    assert not out.exists()


def test_score_module_cli_subprocess_exits_cleanly_on_dec007_violation(tmp_path: Path) -> None:
    """Round-3 Advisory 1 regression: python -m script.five_label_eval.score catches InputError cleanly."""
    import subprocess
    import sys

    bad_manifest = tmp_path / "bad-manifest.json"
    bad_manifest.write_text(
        json.dumps(
            {
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
        )
        + "\n",
        encoding="utf-8",
    )
    reviews = tmp_path / "reviews.jsonl"
    preds = tmp_path / "preds.jsonl"
    reviews.write_text("", encoding="utf-8")
    preds.write_text("", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "script.five_label_eval.score",
            "--manifest",
            str(bad_manifest),
            "--reviews",
            str(reviews),
            "--predictions",
            str(preds),
            "--output",
            str(tmp_path / "out"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "ERROR:" in proc.stderr
    assert "DEC-007" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_infer_rejects_superset_manifest_for_frozen_subset_and_accepts_exact_subset(tmp_path: Path) -> None:
    """Round-4 Finding 1 regression: infer with frozen eval-dev-v1 must reject full manifest and accept exact 210-clip manifest."""
    dev_subset_path = REPO_ROOT / "data/eval-subsets/eval-dev-v1.json"
    full_manifest_out = tmp_path / "full-scoring-manifest.json"
    dev_manifest_out = tmp_path / "dev-scoring-manifest.json"

    assert manifest_convert.main(
        [
            "--input",
            str(REPO_ROOT / "data/sub_video/manifest.json"),
            "--manifest-version",
            "full-clean/1",
            "--output",
            str(full_manifest_out),
        ]
    ) == 0
    assert manifest_convert.main(
        [
            "--input",
            str(REPO_ROOT / "data/sub_video/manifest.json"),
            "--candidate-ids",
            str(dev_subset_path),
            "--manifest-version",
            "dev-v1/1",
            "--output",
            str(dev_manifest_out),
        ]
    ) == 0

    dev_manifest = json.loads(dev_manifest_out.read_text(encoding="utf-8"))
    # Build minimal input records matching the 210 dev samples for fake backend.
    records_path = tmp_path / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as stream:
        for idx, sample in enumerate(dev_manifest["samples"]):
            rec = {
                "record_schema": "five-label-input-record/3",
                "candidate_id": sample["candidate_id"],
                "clip_sha256": sample["clip_sha256"],
                "manifest_sha256": sample["manifest_sha256"],
                "input_id": f"input-{idx:04d}",
            }
            stream.write(json.dumps(rec) + "\n")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("synthetic prompt\n", encoding="utf-8")

    # 1. Full 1,613-sample manifest (contains sealed test clips) MUST be rejected with --candidate-ids eval-dev-v1.json
    bad_preds = tmp_path / "bad-preds.jsonl"
    err = io.StringIO()
    with redirect_stderr(err):
        rc_bad = infer.main(
            [
                "--manifest",
                str(full_manifest_out),
                "--candidate-ids",
                str(dev_subset_path),
                "--input-config",
                str(records_path),
                "--prompt-file",
                str(prompt_path),
                "--run-id",
                "run-bad",
                "--backend",
                "fake",
                "--model-id",
                "fake",
                "--output",
                str(bad_preds),
            ]
        )
    assert rc_bad == 2
    assert "do not match frozen subset" in err.getvalue()
    assert not bad_preds.exists()

    # 2. Exact 210-sample dev manifest succeeds through infer AND score with exactly 210 scored samples!
    good_preds = tmp_path / "good-preds.jsonl"
    rc_good = infer.main(
        [
            "--manifest",
            str(dev_manifest_out),
            "--candidate-ids",
            str(dev_subset_path),
            "--input-config",
            str(records_path),
            "--prompt-file",
            str(prompt_path),
            "--run-id",
            "run-good",
            "--backend",
            "fake",
            "--model-id",
            "fake",
            "--output",
            str(good_preds),
        ]
    )
    assert rc_good == 0
    good_pred_rows = score.read_jsonl(good_preds)
    scored = score.score(dev_manifest, [], good_pred_rows)
    assert len(scored["samples"]) == 210
    assert scored["groups"]["real"]["full_clip"]["clips"] == 210

    # 2b. Passing the 210 frozen eval-dev-v1 predictions with the 1,613-sample full manifest to score MUST fail closed!
    full_manifest = json.loads(full_manifest_out.read_text(encoding="utf-8"))
    with pytest.raises(InputError, match="do not match frozen subset"):
        score.score(full_manifest, [], good_pred_rows)

    # 2c. Infer WITHOUT repeating --candidate-ids inherits eval_subset_id from dev_manifest_out and still blocks full_manifest in score!
    inherited_preds = tmp_path / "inherited-preds.jsonl"
    rc_inherited = infer.main(
        [
            "--manifest",
            str(dev_manifest_out),
            "--input-config",
            str(records_path),
            "--prompt-file",
            str(prompt_path),
            "--run-id",
            "run-inherited",
            "--backend",
            "fake",
            "--model-id",
            "fake",
            "--output",
            str(inherited_preds),
        ]
    )
    assert rc_inherited == 0
    inherited_rows = score.read_jsonl(inherited_preds)
    assert all(row.get("eval_subset_id") == "eval-dev-v1" for row in inherited_rows)
    with pytest.raises(InputError, match="do not match frozen subset"):
        score.score(full_manifest, [], inherited_rows)

    # 2d. Score MUST reject a manifest with the same 210 IDs + clip_sha256 but a different manifest_sha256!
    reserialized_manifest = json.loads(dev_manifest_out.read_text(encoding="utf-8"))
    reserialized_manifest.pop("eval_subset_id", None)
    for sample in reserialized_manifest["samples"]:
        sample["manifest_sha256"] = "1" * 64
    with pytest.raises(InputError, match="manifest_sha256"):
        score.score(reserialized_manifest, [], inherited_rows)

    # 3. Mutating one sample's clip_sha256 (while keeping 210 IDs and manifest_sha256 intact) MUST be rejected by infer & build_manifest
    tampered_dev_manifest = json.loads(dev_manifest_out.read_text(encoding="utf-8"))
    tampered_dev_manifest["samples"][0]["clip_sha256"] = "0" * 64
    tampered_manifest_path = tmp_path / "tampered-dev-manifest.json"
    tampered_manifest_path.write_text(json.dumps(tampered_dev_manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    tampered_records_path = tmp_path / "tampered-records.jsonl"
    with tampered_records_path.open("w", encoding="utf-8") as stream:
        for idx, sample in enumerate(tampered_dev_manifest["samples"]):
            stream.write(
                json.dumps(
                    {
                        "record_schema": "five-label-input-record/3",
                        "candidate_id": sample["candidate_id"],
                        "clip_sha256": sample["clip_sha256"],
                        "manifest_sha256": sample["manifest_sha256"],
                        "input_id": f"input-{idx:04d}",
                    }
                )
                + "\n"
            )
    tampered_preds = tmp_path / "tampered-preds.jsonl"
    err_tampered = io.StringIO()
    with redirect_stderr(err_tampered):
        rc_tampered = infer.main(
            [
                "--manifest",
                str(tampered_manifest_path),
                "--candidate-ids",
                str(dev_subset_path),
                "--input-config",
                str(tampered_records_path),
                "--prompt-file",
                str(prompt_path),
                "--run-id",
                "run-tampered",
                "--backend",
                "fake",
                "--model-id",
                "fake",
                "--output",
                str(tampered_preds),
            ]
        )
    assert rc_tampered == 2
    assert "clip_sha256" in err_tampered.getvalue()
    assert not tampered_preds.exists()

    # build_manifest must also reject a review export whose clip_sha256 was altered
    tampered_reviews_jsonl = tmp_path / "tampered-reviews.jsonl"
    with tampered_reviews_jsonl.open("w", encoding="utf-8") as stream:
        for idx, sample in enumerate(tampered_dev_manifest["samples"]):
            stream.write(
                json.dumps(
                    {
                        "manifest_sha256": sample["manifest_sha256"],
                        "candidate_id": sample["candidate_id"],
                        "clip_sha256": sample["clip_sha256"],
                        "source_id": sample["source_id"],
                        "source_type": sample["source_type"],
                        "review_id": f"rev-{idx}",
                        "review_status": "confirmed",
                        "labels": {"断裂状态": "未断裂"},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    tampered_draft_out = tmp_path / "tampered-draft.json"
    err_bm = io.StringIO()
    with redirect_stderr(err_bm):
        rc_bm = build_manifest.main(
            [
                "--reviews",
                str(tampered_reviews_jsonl),
                "--candidate-ids",
                str(dev_subset_path),
                "--manifest-version",
                "tampered-bm/1",
                "--output",
                str(tampered_draft_out),
            ]
        )
    assert rc_bm == 2
    assert "clip_sha256" in err_bm.getvalue()
    assert not tampered_draft_out.exists()


