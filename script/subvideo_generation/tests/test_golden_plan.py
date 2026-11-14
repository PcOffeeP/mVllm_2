"""R8: golden plan snapshot for one source of each strategy.

The snapshot is committed by the implementer (``golden_plan.json`` next to this
file). It pins the *behaviour* of the approved planners, so a refactor that moves
constants around cannot silently change which windows a batch would contain.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from script.subvideo_generation.tests.rules_support import REPO_ROOT, generate_module


GOLDEN = Path(__file__).with_name("golden_plan.json")
REPRESENTATIVE = ("video_0093", "video_0005", "video_0001")
SNAPSHOT_FIELDS = ("candidate_id", "role", "start_frame", "end_frame", "output_path")
SECONDS_FIELDS = ("start_seconds", "end_seconds")


def _required_paths(root):
    g = generate_module()
    paths = [root / "data/annotation-table-full.csv",
             root / "data/roi/manifest.json",
             root / g.anchors.DOCUMENT,
             root / "data/splits/three-fold"]
    for key in REPRESENTATIVE:
        paths.append(root / "data/videos" / f"{key}.mp4")
        paths.append(root / "data/roi/videos" / f"{key}.mp4")
    return paths


def _dataset_root():
    if not shutil.which("ffprobe"):
        pytest.skip("golden plan needs ffprobe on PATH to probe the real media")
    root = REPO_ROOT
    missing = [str(path.relative_to(root)) for path in _required_paths(root) if not path.exists()]
    if missing:
        pytest.skip("golden plan needs the real 110-source dataset; missing: " + ", ".join(missing))
    return root


def _snapshot(candidate):
    return {
        "candidate_id": candidate["candidate_id"],
        "role": candidate["role"],
        "start_frame": candidate["start_frame"],
        "end_frame": candidate["end_frame"],
        "start_seconds": float(candidate.get("start_seconds", candidate.get("start_time"))),
        "end_seconds": float(candidate.get("end_seconds", candidate.get("end_time"))),
        "output_path": candidate["output_path"],
    }


def _current_plan(root):
    g = generate_module()
    try:
        rows, rois, folds, hashes, _ = g.load_inputs(root)
    except Exception as exc:  # missing/broken inventory is a dataset problem, not a plan drift
        pytest.skip(f"golden plan needs a loadable 110-source inventory: {exc}")
    anchor_records = g.anchors.load_anchors(root / g.anchors.DOCUMENT)
    plan = {}
    for key in REPRESENTATIVE:
        raw, cropped = g._paths(root, key)
        media = g.aligned.probe_video(raw)
        candidates, excluded = g._expected_candidates(
            key, rows[key], folds[key], media,
            g.base.sha256_file(raw), g.base.sha256_file(cropped), anchor_records)
        ordered = sorted(candidates, key=lambda item: (item["role"], item["sequence"]))
        plan[key] = [_snapshot(candidate) for candidate in ordered]
    return plan


def _golden_plan():
    assert GOLDEN.is_file(), (
        f"{GOLDEN.name} must be committed by the implementer: it is the approved "
        "plan for video_0093 (special), video_0005 (coverage) and video_0001 (regular)")
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    plan = data["sources"] if isinstance(data, dict) and "sources" in data else data
    for key in REPRESENTATIVE:
        assert key in plan, f"golden_plan.json has no snapshot for {key}"
        assert plan[key], f"golden_plan.json has an empty snapshot for {key}"
    return plan


def test_golden_plan_matches_the_current_planners():
    root = _dataset_root()
    expected = _golden_plan()
    actual = _current_plan(root)

    for key in REPRESENTATIVE:
        want, have = expected[key], actual[key]
        assert len(have) == len(want), (
            f"{key}: the plan now yields {len(have)} candidates, golden says {len(want)}")
        for index, (wanted, produced) in enumerate(zip(want, have)):
            where = f"{key}[{index}]"
            for field in SNAPSHOT_FIELDS:
                assert produced[field] == wanted[field], (
                    f"{where}.{field} drifted: {produced[field]!r} != golden {wanted[field]!r}")
            for field in SECONDS_FIELDS:
                assert produced[field] == pytest.approx(wanted[field], abs=1e-6), (
                    f"{where}.{field} drifted: {produced[field]!r} != golden {wanted[field]!r}")
