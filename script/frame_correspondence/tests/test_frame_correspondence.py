"""Comprehensive unit and CLI tests for DEC-005 frame-correspondence evidence extraction."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from script.five_label_eval import frames as eval_frames
from script.frame_correspondence import (
    EVIDENCE_SCHEMA,
    MAPPING_DIRECTIONS,
    PROOF_STRENGTH,
    AutoFrameExtractor,
    EvidenceError,
    FfmpegFrameExtractor,
    FrameExtractionResult,
    MetadataOnlyExtractor,
    build_evidence_manifest,
    ensure_output_outside_git_repo,
    extract_evidence_bundle,
    filter_records,
    load_input_records,
    load_roi_manifest,
    load_subvideo_manifest,
    main,
    render_index_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
L0_BYTES = b"synthetic-l0-source-video-bytes"
L1_BYTES = b"synthetic-l1-roi-video-bytes"
L2_BYTES = b"synthetic-l2-subvideo-bytes"
L0_SHA = hashlib.sha256(L0_BYTES).hexdigest()
L1_SHA = hashlib.sha256(L1_BYTES).hexdigest()
L2_SHA = hashlib.sha256(L2_BYTES).hexdigest()
MANIFEST_SHA = "d" * 64
RECEIPT_SHA = "e" * 64

FORBIDDEN_SIMILARITY_WORDS = (
    "similarity",
    "ssim",
    "psnr",
    "lpips",
    "mse",
    "pixel_diff",
    "looks_similar",
    "match_score",
)


def make_v3_record(
    *,
    candidate_id: str = "video_0001_fracture_01",
    source_video_id: str = "video_0001",
    run_id: str | None = "run-20261124-01",
    method: str = "manifest_anchors",
    clip_indices: tuple[int, ...] = (0, 120, 191),
    source_start: int = 973,
    media_root: Path | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a valid five-label-input-record/3 dictionary (no real media needed)."""
    root = media_root or Path("/nonexistent/media")
    l0_path = str(root / "videos" / f"{source_video_id}.mp4")
    l1_path = str(root / "roi" / "videos" / f"{source_video_id}.mp4")
    l2_path = str(root / "sub_video" / "videos" / f"{candidate_id}.mp4")

    unverified = method == "unverified"
    roi_kind = (
        "explicit_pairs"
        if method == "manifest_anchors"
        else "offset"
        if method == "source_replay_mapping"
        else "unverified"
    )

    frame_rows = []
    for order, clip_idx in enumerate(clip_indices):
        roi_idx = None if unverified else source_start + clip_idx
        orig_idx = None if unverified else roi_idx
        frame_rows.append(
            {
                "display_order": order,
                "decode_order": order,
                "clip_frame_index": clip_idx,
                "roi_frame_index": roi_idx,
                "original_source_frame_index": orig_idx,
                "is_anchor": (not unverified and clip_idx == 191),
                "anchor_ref": (
                    {"output_frame": 191, "roi_frame": source_start + 191, "source_frame": source_start + 191}
                    if (not unverified and clip_idx == 191)
                    else None
                ),
                "media_role": "clip",
                "image": f"frame_{order + 1:03d}.png",
                "pts_seconds": round(clip_idx / 30.0, 6),
                "frame_index_mapping": {
                    "clip_to_model_input": dict(eval_frames.CLIP_TO_MODEL_INPUT),
                    "clip_to_roi": (
                        {"kind": "unverified", "offset": None, "reason": "replay_unverified"}
                        if unverified
                        else {"kind": "manifest_replay", "offset": source_start, "reason": None}
                    ),
                    "roi_to_original": (
                        {
                            "kind": "unverified",
                            "offset": None,
                            "method": "unverified",
                            "reason": "replay_unverified",
                        }
                        if unverified
                        else {
                            "kind": roi_kind,
                            "offset": 0,
                            "method": method,
                            "reason": None,
                        }
                    ),
                },
            }
        )

    verification = (
        {
            "verdict_id": "unverified",
            "method": "unverified",
            "evidence_sha256": None,
            "checked_at": "2026-11-24T12:00:00+00:00",
            "conditions": {
                "explicit_pairs": [False, False, False],
                "source_replay": [False, False, False],
            },
            "failed_conditions": ["replay_unverified"],
        }
        if unverified
        else {
            "verdict_id": f"replay@{RECEIPT_SHA[:12]}",
            "method": method,
            "evidence_sha256": RECEIPT_SHA,
            "checked_at": "2026-11-24T12:00:00+00:00",
            "conditions": {
                "explicit_pairs": [True, True, True] if method == "manifest_anchors" else [False, False, False],
                "source_replay": [True, True, True],
            },
            "failed_conditions": [],
        }
    )

    input_hash = hashlib.sha256(
        f"{candidate_id}|{run_id}|{method}|{clip_indices}|{source_start}".encode("utf-8")
    ).hexdigest()

    record: dict = {
        "record_schema": eval_frames.RECORD_SCHEMA,
        "candidate_id": candidate_id,
        "clip_sha256": L2_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "input_id": f"input@sha256:{input_hash}",
        "frame_count_convention": "decoded",
        "verification": verification,
        "lineage_check": "pass",
        "media": {
            "role": "clip",
            "path": l2_path,
            "sha256": L2_SHA,
            "fps": 30.0,
            "total_frames": 240,
            "width": 320,
            "height": 240,
            "size_bucket": "w_200_400",
            "size_bucket_source": eval_frames.SIZE_BUCKET_SOURCE,
        },
        "lineage_media": {
            "l0": {
                "role": "source_video",
                "path": l0_path,
                "sha256": L0_SHA,
                "declared_sha256": L0_SHA,
                "fps": 30.0,
                "total_frames": 1500,
                "total_frames_source": "decoded",
                "width": 1920,
                "height": 1080,
                "size_bucket": "w_gt_400",
                "size_bucket_source": eval_frames.SIZE_BUCKET_SOURCE,
                "frame_count_notes": None,
            },
            "l1": {
                "role": "roi_video",
                "path": l1_path,
                "sha256": L1_SHA,
                "declared_sha256": L1_SHA,
                "fps": 30.0,
                "total_frames": 1500,
                "total_frames_source": "decoded",
                "width": 320,
                "height": 240,
                "size_bucket": "w_200_400",
                "size_bucket_source": eval_frames.SIZE_BUCKET_SOURCE,
                "frame_count_notes": None,
            },
            "l2": {
                "role": "sub_video",
                "path": l2_path,
                "sha256": L2_SHA,
                "declared_sha256": L2_SHA,
                "fps": 30.0,
                "total_frames": 240,
                "total_frames_source": "decoded",
                "width": 320,
                "height": 240,
                "size_bucket": "w_200_400",
                "size_bucket_source": eval_frames.SIZE_BUCKET_SOURCE,
                "frame_count_notes": None,
            },
        },
        "frames": frame_rows,
    }
    if run_id is not None:
        record["run_id"] = run_id
    if extra:
        record.update(extra)
    assert eval_frames.verify_lineage(record) == []
    return record


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records),
        encoding="utf-8",
    )
    return path


class FakeFrameExtractor:
    """Deterministic stub extractor writing tagged fake PNG payloads without ffmpeg/cv2."""

    def __init__(self, fail_for_names: set[str] | None = None) -> None:
        self.calls: list[tuple[str, int, str]] = []
        self.fail_for_names = fail_for_names or set()

    def extract_video_frame(
        self,
        video_path: Path,
        frame_index: int,
        output_path: Path,
    ) -> FrameExtractionResult:
        self.calls.append((video_path.name, frame_index, output_path.name))
        if video_path.name in self.fail_for_names:
            return FrameExtractionResult(
                status="skipped",
                backend="fake",
                skip_reason=f"simulated_decode_failure:{video_path.name}",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"FAKEPNG:{video_path.name}:f{frame_index}".encode("utf-8")
        output_path.write_bytes(payload)
        return FrameExtractionResult(
            status="extracted",
            output_path=output_path,
            pts_seconds=round(frame_index / 30.0, 6),
            image_sha256=hashlib.sha256(payload).hexdigest(),
            backend="fake",
        )

    def copy_l3_image(
        self,
        source_image_path: Path,
        output_path: Path,
    ) -> FrameExtractionResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = source_image_path.read_bytes()
        output_path.write_bytes(data)
        return FrameExtractionResult(
            status="copied",
            output_path=output_path,
            image_sha256=hashlib.sha256(data).hexdigest(),
            backend="fake",
        )


def _walk_keys(obj) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys |= _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _walk_keys(item)
    return keys


# --------------------------------------------------------------------------- #
# 1. Valid five-label-input-record/3 resolution, binding & output artifacts
# --------------------------------------------------------------------------- #

def test_valid_v3_four_layer_resolution_and_outputs(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    (media_root / "videos").mkdir(parents=True)
    (media_root / "roi" / "videos").mkdir(parents=True)
    (media_root / "sub_video" / "videos").mkdir(parents=True)
    (media_root / "videos" / "video_0001.mp4").write_bytes(L0_BYTES)
    (media_root / "roi" / "videos" / "video_0001.mp4").write_bytes(L1_BYTES)
    (media_root / "sub_video" / "videos" / "video_0001_fracture_01.mp4").write_bytes(L2_BYTES)

    l3_dir = tmp_path / "l3_frames" / "run-20261124-01" / "video_0001_fracture_01"
    l3_dir.mkdir(parents=True)
    for idx in range(1, 4):
        (l3_dir / f"frame_{idx:03d}.png").write_bytes(f"L3_PNG_{idx}".encode("utf-8"))

    record = make_v3_record(media_root=media_root, clip_indices=(0, 120, 191), source_start=973)
    records_path = write_jsonl(tmp_path / "records.jsonl", [record])
    loaded = load_input_records(records_path)
    assert len(loaded) == 1

    out_dir = tmp_path / "evidence_out"
    fake = FakeFrameExtractor()
    run_index = extract_evidence_bundle(
        loaded,
        output_dir=out_dir,
        mode="extract_images",
        extractor=fake,
        l3_frames_dir=tmp_path / "l3_frames",
        input_records_dir=tmp_path,
    )

    assert run_index["records_processed"] == 1
    assert run_index["proof_strength"] == PROOF_STRENGTH
    assert run_index["replaces_full_receipt"] is False

    entry = run_index["entries"][0]
    manifest_path = out_dir / entry["evidence_manifest"]
    index_path = out_dir / entry["index_markdown"]
    assert manifest_path.is_file()
    assert index_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == EVIDENCE_SCHEMA
    assert manifest["anchor_basis"] == "run_actual_model_input_frames"
    assert manifest["mapping_directions"] == MAPPING_DIRECTIONS
    assert manifest["run_record"]["run_id"] == "run-20261124-01"
    assert manifest["run_record"]["input_id"] == record["input_id"]
    assert manifest["clip_identity"]["candidate_id"] == "video_0001_fracture_01"
    assert manifest["clip_identity"]["clip_sha256"] == L2_SHA
    assert manifest["media_digests"]["l0"]["recorded_sha256"] == L0_SHA
    assert manifest["media_digests"]["l0"]["observed_sha256"] == L0_SHA
    assert manifest["media_digests"]["l0"]["digest_match_on_disk"] is True
    assert manifest["media_digests"]["l1"]["recorded_sha256"] == L1_SHA
    assert manifest["media_digests"]["l1"]["observed_sha256"] == L1_SHA
    assert manifest["media_digests"]["l2"]["recorded_sha256"] == L2_SHA
    assert manifest["media_digests"]["l2"]["observed_sha256"] == L2_SHA

    # Anchored strictly on the 3 input frames in display_order
    assert len(manifest["frames"]) == 3
    f2 = manifest["frames"][2]
    assert f2["display_order"] == 2
    assert f2["mapping"]["clip_to_model_input"]["direction"] == "L2->L3"
    assert f2["mapping"]["clip_to_roi"]["direction"] == "L2->L1"
    assert f2["mapping"]["clip_to_roi"]["offset"] == 973
    assert f2["mapping"]["roi_to_original"]["direction"] == "L1->L0"
    assert f2["mapping"]["roi_to_original"]["offset"] == 0

    assert f2["layers"]["l3"]["frame_index"] == 2
    assert f2["layers"]["l3"]["extraction_status"] == "copied"
    assert f2["layers"]["l2"]["frame_index"] == 191
    assert f2["layers"]["l1"]["frame_index"] == 1164
    assert f2["layers"]["l0"]["frame_index"] == 1164
    assert f2["layers"]["l0"]["timestamp_source"] == "decoded_pts_seconds"
    for layer_key in ("l3", "l2", "l1", "l0"):
        rel = f2["layers"][layer_key]["extracted_image"]
        assert rel is not None
        assert (manifest_path.parent / rel).is_file()

    assert manifest["extraction_summary"]["extracted_count"] == 9
    assert manifest["extraction_summary"]["copied_count"] == 3
    assert manifest["extraction_summary"]["skipped_count"] == 0

    index_md = index_path.read_text(encoding="utf-8")
    assert "manual_visual_evidence_only" in index_md
    assert "replaces_full_receipt" in index_md
    assert "clip_to_model_input" in index_md
    assert "clip_to_roi" in index_md
    assert "roi_to_original" in index_md
    assert "**失效条件：**" in index_md


def test_per_run_isolation_for_same_clip(tmp_path: Path) -> None:
    rec_a = make_v3_record(run_id="run-alpha", clip_indices=(0, 50))
    rec_b = make_v3_record(run_id="run-beta", clip_indices=(10, 80))
    out_dir = tmp_path / "evidence_out"

    run_index = extract_evidence_bundle(
        [rec_a, rec_b],
        output_dir=out_dir,
        mode="metadata_only",
    )
    assert run_index["records_processed"] == 2
    paths = [e["evidence_manifest"] for e in run_index["entries"]]
    assert len(set(paths)) == 2
    assert paths[0].startswith("run-alpha__")
    assert paths[1].startswith("run-beta__")


# --------------------------------------------------------------------------- #
# 2. Strict rejection of v2 schema, legacy/reversed keys & lineage mismatch
# --------------------------------------------------------------------------- #

def test_rejects_v2_schema_and_missing_schema(tmp_path: Path) -> None:
    v2 = make_v3_record()
    v2["record_schema"] = "five-label-input-record/2"
    p_v2 = write_jsonl(tmp_path / "v2.jsonl", [v2])
    with pytest.raises(EvidenceError, match="five-label-input-record/3"):
        load_input_records(p_v2)

    untyped = make_v3_record()
    del untyped["record_schema"]
    p_untyped = write_jsonl(tmp_path / "untyped.jsonl", [untyped])
    with pytest.raises(EvidenceError, match="record_schema"):
        load_input_records(p_untyped)


@pytest.mark.parametrize(
    "legacy_key",
    ["source_to_media", "media_to_clip", "roi_to_source", "original_to_roi", "roi_to_clip"],
)
def test_rejects_legacy_and_reversed_mapping_keys(tmp_path: Path, legacy_key: str) -> None:
    bad = make_v3_record()
    bad["frames"][0]["frame_index_mapping"][legacy_key] = {"kind": "offset", "offset": 0, "reason": None}
    path = write_jsonl(tmp_path / f"bad_{legacy_key}.jsonl", [bad])
    with pytest.raises(EvidenceError, match=legacy_key):
        load_input_records(path)


def test_rejects_deprecated_source_frame_index_key(tmp_path: Path) -> None:
    bad = make_v3_record()
    bad["frames"][0]["source_frame_index"] = 973
    path = write_jsonl(tmp_path / "bad_sfi.jsonl", [bad])
    with pytest.raises(EvidenceError, match="source_frame_index"):
        load_input_records(path)


def test_rejects_lineage_mismatch(tmp_path: Path) -> None:
    # Break additive L2->L1 mapping: roi_frame_index != clip_frame_index + offset
    broken_offset = make_v3_record()
    broken_offset["frames"][0]["roi_frame_index"] = 999
    broken_offset["frames"][0]["original_source_frame_index"] = 999
    with pytest.raises(EvidenceError, match="lineage verification failed"):
        load_input_records(write_jsonl(tmp_path / "broken_offset.jsonl", [broken_offset]))

    # Break L2 digest identity
    broken_digest = make_v3_record()
    broken_digest["clip_sha256"] = "f" * 64
    with pytest.raises(EvidenceError, match="lineage verification failed"):
        load_input_records(write_jsonl(tmp_path / "broken_digest.jsonl", [broken_digest]))


def test_rejects_subvideo_manifest_digest_conflict(tmp_path: Path) -> None:
    rec = make_v3_record()
    sv_path = tmp_path / "subvideo_manifest.json"
    sv_path.write_text(
        json.dumps(
            {
                "schema": "tensile-unified-sub-video-manifest/1",
                "verification": {"mode": "basic", "frame_replay": "skipped"},
                "candidates": [
                    {
                        "candidate_id": rec["candidate_id"],
                        "source_video_id": "video_0001",
                        "output": {"sha256": "1" * 64},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sv_manifest = load_subvideo_manifest(sv_path)
    with pytest.raises(EvidenceError, match="output.sha256"):
        extract_evidence_bundle(
            [rec],
            output_dir=tmp_path / "out",
            mode="metadata_only",
            subvideo_manifest=sv_manifest,
        )


# --------------------------------------------------------------------------- #
# 3. Missing media, metadata-only, unverified & partial-layer skip behavior
# --------------------------------------------------------------------------- #

def test_missing_media_and_partial_layer_skip_never_fabricates_images(tmp_path: Path) -> None:
    # Provide ONLY L2 media file; L0, L1 videos and L3 PNGs are absent
    media_root = tmp_path / "partial_media"
    (media_root / "sub_video" / "videos").mkdir(parents=True)
    (media_root / "sub_video" / "videos" / "video_0001_fracture_01.mp4").write_bytes(L2_BYTES)

    rec = make_v3_record(media_root=media_root, clip_indices=(0, 30))
    out_dir = tmp_path / "out_partial"
    fake = FakeFrameExtractor()

    run_index = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="extract_images",
        extractor=fake,
        media_root=media_root,
    )
    manifest_path = out_dir / run_index["entries"][0]["evidence_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # L2 extracted (2 frames), while L3, L1, L0 are cleanly skipped (6 skipped entries)
    summary = manifest["extraction_summary"]
    assert summary["extracted_count"] == 2
    assert summary["copied_count"] == 0
    assert summary["skipped_count"] == 6
    skipped_layer_tags = {item["layer"] for item in summary["skipped_layers"]}
    assert skipped_layer_tags == {"L3", "L1", "L0"}

    # Ensure L3 was NOT fabricated from L2
    for frame in manifest["frames"]:
        assert frame["layers"]["l3"]["extraction_status"] == "skipped"
        assert "no_l2_substitution" in frame["layers"]["l3"]["skip_reason"]
        assert frame["layers"]["l3"]["extracted_image"] is None
        assert frame["layers"]["l2"]["extraction_status"] == "extracted"
        assert frame["layers"]["l1"]["extracted_image"] is None
        assert frame["layers"]["l0"]["extracted_image"] is None


def test_metadata_only_mode_writes_no_pngs(tmp_path: Path) -> None:
    rec = make_v3_record(clip_indices=(0, 60))
    out_dir = tmp_path / "out_meta"

    run_index = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="metadata_only",
        extractor=MetadataOnlyExtractor(),
    )
    manifest_path = out_dir / run_index["entries"][0]["evidence_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not (manifest_path.parent / "frames").exists()
    assert manifest["extraction_summary"]["metadata_only_count"] == 8
    assert manifest["extraction_summary"]["extracted_count"] == 0
    assert manifest["frames"][0]["layers"]["l1"]["timestamp_source"] == "nominal_index_div_fps"
    assert manifest["frames"][0]["layers"]["l2"]["timestamp_source"] == "record_pts_seconds"


def test_unverified_record_skips_l1_l0_and_sets_no_frame_level_replay(tmp_path: Path) -> None:
    rec = make_v3_record(method="unverified", clip_indices=(0, 15))
    out_dir = tmp_path / "out_unverified"

    run_index = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="extract_images",
        extractor=FakeFrameExtractor(),
    )
    manifest = json.loads((out_dir / run_index["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    pb = manifest["proof_boundaries"]
    assert pb["no_frame_level_replay"] is True
    assert "record_lineage_unverified" in pb["active_limitations"]
    assert "no_frame_level_replay" in pb["active_limitations"]

    f0 = manifest["frames"][0]
    assert f0["layers"]["l1"]["frame_index"] is None
    assert f0["layers"]["l0"]["frame_index"] is None
    assert f0["layers"]["l1"]["extraction_status"] == "skipped"
    assert f0["layers"]["l0"]["extraction_status"] == "skipped"


# --------------------------------------------------------------------------- #
# 4. DEC-005 proof-strength boundaries, audit_tier & Git output guard
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tier", ["basic", "none"])
def test_basic_and_none_audit_tiers_preserve_no_frame_level_replay(tmp_path: Path, tier: str) -> None:
    rec = make_v3_record(extra={"audit_tier": tier})
    sv_path = tmp_path / "sv.json"
    sv_path.write_text(
        json.dumps(
            {
                "schema": "tensile-unified-sub-video-manifest/1",
                "verification": {"mode": tier, "frame_replay": "skipped"},
                "candidates": [
                    {
                        "candidate_id": rec["candidate_id"],
                        "source_video_id": "video_0001",
                        "output": {"sha256": L2_SHA},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    roi_path = tmp_path / "roi.json"
    roi_path.write_text(
        json.dumps(
            {
                "schema": "roi-manifest/1",
                "videos": [
                    {
                        "video_id": "video_0001",
                        "status": "cropped",
                        "recipe_hash": "r" * 16,
                        "output": {"sha256": L1_SHA},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / f"out_{tier}"
    run_index = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="metadata_only",
        subvideo_manifest=load_subvideo_manifest(sv_path),
        roi_manifest=load_roi_manifest(roi_path),
    )
    manifest = json.loads((out_dir / run_index["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    pb = manifest["proof_boundaries"]
    assert pb["proof_strength"] == "manual_visual_evidence_only"
    assert pb["replaces_full_receipt"] is False
    assert pb["equals_frame_level_replay_pass"] is False
    assert pb["automated_pixel_comparison"] is False
    assert pb["automated_similarity_judgment"] is False
    assert pb["claims_verified_frame_correspondence"] is False
    assert pb["audit_tier"] == tier
    assert pb["no_frame_level_replay"] is True
    assert "no_frame_level_replay" in pb["active_limitations"]

    # Ensure zero similarity / pixel-comparison fields appear in frames or data sections
    # (the only allowed mention is the explicit False disclaimer flags inside proof_boundaries).
    non_boundary_payload = {k: v for k, v in manifest.items() if k != "proof_boundaries"}
    data_keys = _walk_keys(non_boundary_payload)
    for word in FORBIDDEN_SIMILARITY_WORDS:
        assert not any(word in key for key in data_keys), f"forbidden similarity key found: {word}"
    for key, val in pb.items():
        if any(word in key.lower() for word in FORBIDDEN_SIMILARITY_WORDS):
            assert val is False, f"proof_boundaries.{key} must be False, got {val!r}"

    # Verify ROI manifest binding recorded
    assert manifest["clip_identity"]["roi_manifest_binding"]["video_found"] is True
    assert manifest["clip_identity"]["roi_manifest_binding"]["recipe_hash"] == "r" * 16


def test_source_replay_mapping_and_media_root_relocation(tmp_path: Path) -> None:
    # Recorded paths point to /old/machine/..., while actual files live under media_root
    media_root = tmp_path / "relocated_media"
    (media_root / "videos").mkdir(parents=True)
    (media_root / "roi" / "videos").mkdir(parents=True)
    (media_root / "sub_video" / "videos").mkdir(parents=True)
    (media_root / "videos" / "video_0002.mp4").write_bytes(L0_BYTES)
    (media_root / "roi" / "videos" / "video_0002.mp4").write_bytes(L1_BYTES)
    (media_root / "sub_video" / "videos" / "video_0002_post_01.mp4").write_bytes(L2_BYTES)

    rec = make_v3_record(
        candidate_id="video_0002_post_01",
        source_video_id="video_0002",
        method="source_replay_mapping",
        clip_indices=(10, 40),
        source_start=500,
        media_root=Path("/old/machine/data"),
    )
    out_dir = tmp_path / "out_relocated"
    fake = FakeFrameExtractor()
    run_index = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="extract_images",
        extractor=fake,
        media_root=media_root,
    )
    manifest = json.loads((out_dir / run_index["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert manifest["run_record"]["verification"]["method"] == "source_replay_mapping"
    f0 = manifest["frames"][0]
    assert f0["mapping"]["roi_to_original"]["kind"] == "offset"
    assert f0["mapping"]["roi_to_original"]["offset"] == 0
    assert f0["layers"]["l2"]["frame_index"] == 10
    assert f0["layers"]["l1"]["frame_index"] == 510
    assert f0["layers"]["l0"]["frame_index"] == 510
    assert f0["layers"]["l0"]["extraction_status"] == "extracted"
    assert f0["layers"]["l1"]["extraction_status"] == "extracted"
    assert f0["layers"]["l2"]["extraction_status"] == "extracted"


def test_rejects_output_dir_inside_git_repo() -> None:
    inside_repo = REPO_ROOT / "tmp_should_be_rejected_evidence"
    with pytest.raises(EvidenceError, match="inside Git repository"):
        ensure_output_outside_git_repo(inside_repo)


def test_package_is_independent_of_subvideo_generation_and_checks() -> None:
    pkg_dir = REPO_ROOT / "script" / "frame_correspondence"
    for py_file in pkg_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("script.subvideo_generation")
                    assert not alias.name.startswith("script.checks")
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("script.subvideo_generation")
                assert not node.module.startswith("script.checks")


# --------------------------------------------------------------------------- #
# 5. Extractor backend behavior & CLI smoke tests
# --------------------------------------------------------------------------- #

def test_ffmpeg_extractor_parses_showinfo_pts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = tmp_path / "ffmpeg"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    out_png = tmp_path / "out" / "f.png"

    def fake_run(cmd, capture_output, text):
        assert "select=eq(n\\,12),showinfo" in cmd
        Path(cmd[-1]).write_bytes(b"PNGDATA")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="",
            stderr="[Parsed_showinfo_1 @ 0x0] n:   0 pts:  12000 pts_time:0.400000 pos:123",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    extractor = FfmpegFrameExtractor(ffmpeg_bin=str(fake_bin))
    res = extractor.extract_video_frame(video, 12, out_png)
    assert res.status == "extracted"
    assert res.pts_seconds == 0.4
    assert res.output_path == out_png
    assert res.image_sha256 == hashlib.sha256(b"PNGDATA").hexdigest()


def test_auto_extractor_handles_no_backends(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    class UnavailableFFmpeg(FfmpegFrameExtractor):
        def available(self) -> bool:
            return False

    class UnavailableCV:
        def available(self) -> bool:
            return False

    auto = AutoFrameExtractor(ffmpeg_extractor=UnavailableFFmpeg(ffmpeg_bin=""), opencv_extractor=UnavailableCV())  # type: ignore[arg-type]
    res = auto.extract_video_frame(video, 0, tmp_path / "x.png")
    assert res.status == "skipped"
    assert res.skip_reason == "no_frame_extractor_backend_available"


def test_l3_path_traversal_and_missing_required_ids_rejected(tmp_path: Path) -> None:
    from script.frame_correspondence.extractor import resolve_l3_image_path

    # Relative path escaping l3_frames_dir must never resolve
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"SECRET")
    l3_dir = tmp_path / "l3"
    l3_dir.mkdir()
    assert resolve_l3_image_path("../secret.png", candidate_id="c00", l3_frames_dir=l3_dir) is None

    # Missing candidate_id or input_id must raise clean EvidenceError
    missing_id = make_v3_record()
    missing_id["candidate_id"] = ""
    with pytest.raises(EvidenceError, match="candidate_id"):
        load_input_records(write_jsonl(tmp_path / "no_cid.jsonl", [missing_id]))

    missing_input_id = make_v3_record()
    del missing_input_id["input_id"]
    with pytest.raises(EvidenceError, match="input_id"):
        load_input_records(write_jsonl(tmp_path / "no_iid.jsonl", [missing_input_id]))


def test_opencv_extractor_sequential_decode_with_mock_cv2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types
    from script.frame_correspondence import OpenCVFrameExtractor

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    out_png = tmp_path / "cv_out" / "f.png"
    grab_calls: list[int] = []
    set_calls: list[tuple] = []

    class FakeCap:
        def __init__(self, path: str) -> None:
            self.path = path
            self.released = False

        def isOpened(self) -> bool:
            return True

        def set(self, *args) -> bool:
            set_calls.append(args)
            return True

        def grab(self) -> bool:
            grab_calls.append(1)
            return True

        def read(self):
            return True, b"IMG"

        def get(self, prop: int) -> float:
            return 250.0

        def release(self) -> None:
            self.released = True

    fake_cv2 = types.SimpleNamespace(
        CAP_PROP_POS_MSEC=0,
        VideoCapture=FakeCap,
        imwrite=lambda path, img: (Path(path).write_bytes(b"CVPNG") > 0),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    extractor = OpenCVFrameExtractor()
    res = extractor.extract_video_frame(video, 3, out_png)
    assert res.status == "extracted"
    assert res.backend == "opencv"
    assert res.pts_seconds == 0.25
    assert len(grab_calls) == 3
    assert set_calls == []  # never uses random seek
    assert out_png.is_file()


def test_cli_main_and_subprocess_smoke(tmp_path: Path) -> None:
    rec1 = make_v3_record(candidate_id="clip_a", run_id="run-1", clip_indices=(0, 20))
    rec2 = make_v3_record(candidate_id="clip_b", run_id="run-2", clip_indices=(5, 25))
    records_path = write_jsonl(tmp_path / "inputs.jsonl", [rec1, rec2])
    out_dir = tmp_path / "cli_out"

    # Direct main() filter by --clip-id and --run-id
    rc = main(
        [
            "--input-records",
            str(records_path),
            "--output-dir",
            str(out_dir),
            "--clip-id",
            "clip_b",
            "--run-id",
            "run-2",
            "--metadata-only",
        ]
    )
    assert rc == 0
    idx = json.loads((out_dir / "run_index.json").read_text(encoding="utf-8"))
    assert idx["records_processed"] == 1
    assert idx["entries"][0]["candidate_id"] == "clip_b"

    # Non-matching filter returns non-zero exit code
    rc_miss = main(
        [
            "--input-records",
            str(records_path),
            "--output-dir",
            str(tmp_path / "cli_out_miss"),
            "--clip-id",
            "does_not_exist",
            "--metadata-only",
        ]
    )
    assert rc_miss == 2

    # Subprocess module invocation: python -m script.frame_correspondence
    sub_out = tmp_path / "subproc_out"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "script.frame_correspondence",
            "--input-records",
            str(records_path),
            "--output-dir",
            str(sub_out),
            "--metadata-only",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "replaces_full_receipt=false" in proc.stdout
    assert (sub_out / "run_index.json").is_file()

    # Subprocess rejects legacy v2 record with non-zero exit code
    v2 = copy.deepcopy(rec1)
    v2["record_schema"] = "five-label-input-record/2"
    v2_path = write_jsonl(tmp_path / "v2.jsonl", [v2])
    proc_bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "script.frame_correspondence",
            "--input-records",
            str(v2_path),
            "--output-dir",
            str(tmp_path / "subproc_bad"),
            "--metadata-only",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc_bad.returncode == 2
    assert "five-label-input-record/3" in proc_bad.stderr


# --------------------------------------------------------------------------- #
# 6. Regression tests for Codex PR #21 review findings (BLOCKING 1-6 + ADV 7)
# --------------------------------------------------------------------------- #

def test_disk_sha256_mismatch_skips_decoding_and_records_observed_digest(tmp_path: Path) -> None:
    """Finding 1: never decode a tampered L0/L1/L2 video and attach old SHA-256."""
    media_root = tmp_path / "tampered_media"
    (media_root / "videos").mkdir(parents=True)
    (media_root / "roi" / "videos").mkdir(parents=True)
    (media_root / "sub_video" / "videos").mkdir(parents=True)
    (media_root / "videos" / "video_0001.mp4").write_bytes(L0_BYTES)
    tampered_l1 = b"TAMPERED-L1-VIDEO-BYTES"
    (media_root / "roi" / "videos" / "video_0001.mp4").write_bytes(tampered_l1)
    (media_root / "sub_video" / "videos" / "video_0001_fracture_01.mp4").write_bytes(L2_BYTES)

    rec = make_v3_record(media_root=media_root, clip_indices=(0, 30))
    out_dir = tmp_path / "out_tampered"
    fake = FakeFrameExtractor()

    run_index = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="extract_images",
        extractor=fake,
        media_root=media_root,
    )
    manifest = json.loads((out_dir / run_index["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))

    # L1 was NOT decoded (2 frames x 2 intact layers L0 & L2 = 4 calls, never 6)
    assert len(fake.calls) == 4
    called_files = {name for name, _, _ in fake.calls}
    assert "video_0001_fracture_01.mp4" in called_files
    # L0 shares filename video_0001.mp4 with L1, so check extracted counts directly
    assert manifest["media_digests"]["l1"]["recorded_sha256"] == L1_SHA
    assert manifest["media_digests"]["l1"]["observed_sha256"] == hashlib.sha256(tampered_l1).hexdigest()
    assert manifest["media_digests"]["l1"]["digest_match_on_disk"] is False
    assert manifest["media_digests"]["l0"]["digest_match_on_disk"] is True
    assert manifest["media_digests"]["l2"]["digest_match_on_disk"] is True
    assert "l1_disk_sha256_mismatch" in manifest["proof_boundaries"]["active_limitations"]

    for frame in manifest["frames"]:
        assert frame["layers"]["l1"]["extraction_status"] == "skipped"
        assert "l1_disk_sha256_mismatch" in frame["layers"]["l1"]["skip_reason"]
        assert frame["layers"]["l1"]["extracted_image"] is None
        assert frame["layers"]["l1"]["recorded_sha256"] == L1_SHA
        assert frame["layers"]["l1"]["observed_sha256"] == hashlib.sha256(tampered_l1).hexdigest()
        assert frame["layers"]["l2"]["extraction_status"] == "extracted"
        assert frame["layers"]["l0"]["extraction_status"] == "extracted"


def test_l3_multi_run_ambiguity_skipped_and_run_scoped_or_sha256_bound(tmp_path: Path) -> None:
    """Finding 2: multi-run same candidate must not silently reuse unscoped shared L3 PNGs."""
    rec_a = make_v3_record(candidate_id="clip_shared", run_id="run-A", clip_indices=(0,))
    rec_b = make_v3_record(candidate_id="clip_shared", run_id="run-B", clip_indices=(10,))

    # Case 1: Only unscoped shared directory exists -> BOTH runs must skip L3 (even when filtered!)
    shared_l3 = tmp_path / "shared_l3"
    (shared_l3 / "clip_shared").mkdir(parents=True)
    (shared_l3 / "clip_shared" / "frame_001.png").write_bytes(b"SHARED_AMBIGUOUS")

    jsonl_path = write_jsonl(tmp_path / "two_runs.jsonl", [rec_a, rec_b])
    out_filtered = tmp_path / "out_filtered_ambig"
    rc = main(
        [
            "--input-records",
            str(jsonl_path),
            "--output-dir",
            str(out_filtered),
            "--run-id",
            "run-A",
            "--l3-frames-dir",
            str(shared_l3),
            "--extract-images",
        ]
    )
    assert rc == 0
    idx = json.loads((out_filtered / "run_index.json").read_text(encoding="utf-8"))
    m_a = json.loads((out_filtered / idx["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert m_a["frames"][0]["layers"]["l3"]["extraction_status"] == "skipped"
    assert "l3_image_ambiguous_across_runs" in m_a["frames"][0]["layers"]["l3"]["skip_reason"]
    assert m_a["frames"][0]["layers"]["l3"]["extracted_image"] is None

    # Case 2: Run-scoped subdirectories exist -> each run copies its own L3 PNG
    scoped_l3 = tmp_path / "scoped_l3"
    (scoped_l3 / "run-A" / "clip_shared").mkdir(parents=True)
    (scoped_l3 / "run-B" / "clip_shared").mkdir(parents=True)
    (scoped_l3 / "run-A" / "clip_shared" / "frame_001.png").write_bytes(b"PNG_FROM_RUN_A")
    (scoped_l3 / "run-B" / "clip_shared" / "frame_001.png").write_bytes(b"PNG_FROM_RUN_B")

    out_scoped = tmp_path / "out_scoped"
    run_idx = extract_evidence_bundle(
        [rec_a, rec_b],
        output_dir=out_scoped,
        mode="extract_images",
        extractor=FakeFrameExtractor(),
        l3_frames_dir=scoped_l3,
    )
    ma = json.loads((out_scoped / run_idx["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    mb = json.loads((out_scoped / run_idx["entries"][1]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert ma["frames"][0]["layers"]["l3"]["extraction_status"] == "copied"
    assert ma["frames"][0]["layers"]["l3"]["binding_basis"] == "run_scoped_directory"
    assert ma["frames"][0]["layers"]["l3"]["observed_sha256"] == hashlib.sha256(b"PNG_FROM_RUN_A").hexdigest()
    assert mb["frames"][0]["layers"]["l3"]["extraction_status"] == "copied"
    assert mb["frames"][0]["layers"]["l3"]["observed_sha256"] == hashlib.sha256(b"PNG_FROM_RUN_B").hexdigest()

    # Case 3: Per-frame image_sha256 uniquely binds even in shared directory, and rejects mismatch
    rec_sha_ok = make_v3_record(candidate_id="clip_shared", run_id="run-C", clip_indices=(0,))
    rec_sha_ok["frames"][0]["image_sha256"] = hashlib.sha256(b"SHARED_AMBIGUOUS").hexdigest()
    rec_sha_bad = make_v3_record(candidate_id="clip_shared", run_id="run-D", clip_indices=(0,))
    rec_sha_bad["frames"][0]["image_sha256"] = "0" * 64

    out_sha = tmp_path / "out_sha_bound"
    idx_sha = extract_evidence_bundle(
        [rec_sha_ok, rec_sha_bad],
        output_dir=out_sha,
        mode="extract_images",
        extractor=FakeFrameExtractor(),
        l3_frames_dir=shared_l3,
    )
    m_ok = json.loads((out_sha / idx_sha["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    m_bad = json.loads((out_sha / idx_sha["entries"][1]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert m_ok["frames"][0]["layers"]["l3"]["extraction_status"] == "copied"
    assert m_ok["frames"][0]["layers"]["l3"]["binding_basis"] == "frame_sha256_verified"
    assert m_bad["frames"][0]["layers"]["l3"]["extraction_status"] == "skipped"
    assert "l3_image_sha256_mismatch" in m_bad["frames"][0]["layers"]["l3"]["skip_reason"]


def test_ffmpeg_does_not_reuse_stale_existing_png_on_empty_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3: ffmpeg returning 0 without emitting a frame must never report stale PNG."""
    fake_bin = tmp_path / "ffmpeg"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    out_png = tmp_path / "out" / "existing_frame.png"
    out_png.parent.mkdir(parents=True)
    out_png.write_bytes(b"STALE_OLD_PNG_BYTES")

    def fake_run_no_output(cmd, capture_output, text):
        # Simulate ffmpeg returning exit code 0 when select=eq(n,9999) matches nothing
        assert Path(cmd[-1]) != out_png  # must decode into a fresh temp file, never directly to out_png
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run_no_output)
    extractor = FfmpegFrameExtractor(ffmpeg_bin=str(fake_bin))
    res = extractor.extract_video_frame(video, 9999, out_png)
    assert res.status == "skipped"
    assert res.output_path is None
    assert "ffmpeg_decode_failed" in (res.skip_reason or "")
    # Stale file untouched and temp dir cleaned up
    assert out_png.read_bytes() == b"STALE_OLD_PNG_BYTES"
    assert [p.name for p in out_png.parent.iterdir()] == ["existing_frame.png"]


def test_rejects_symlink_escape_and_nested_git_inside_output_dir(tmp_path: Path) -> None:
    """Finding 4: reject symlink escapes into Git repo and nested .git dirs under output_dir."""
    from script.frame_correspondence.evidence import _run_slug_for_record

    rec = make_v3_record(candidate_id="clip_sec", run_id="run-sec", clip_indices=(0,))
    run_slug = _run_slug_for_record(rec)

    # Case 1: Symlink inside output_dir pointing into Git repo
    out_symlink = tmp_path / "out_symlink"
    out_symlink.mkdir()
    (out_symlink / run_slug).symlink_to(REPO_ROOT)
    with pytest.raises(EvidenceError, match="symlink|escapes|inside Git"):
        extract_evidence_bundle([rec], output_dir=out_symlink, mode="metadata_only")

    # Case 2: Nested .git repository inside output_dir/<run_slug>
    out_nested_git = tmp_path / "out_nested_git"
    (out_nested_git / run_slug / ".git").mkdir(parents=True)
    with pytest.raises(EvidenceError, match="inside Git repository"):
        extract_evidence_bundle([rec], output_dir=out_nested_git, mode="metadata_only")


def test_colliding_run_ids_get_distinct_dirs_and_existing_manifest_overwrite_rejected(
    tmp_path: Path,
) -> None:
    """Finding 5: 'run/a' vs 'run_a' never collide; conflicting existing manifest refuses overwrite."""
    rec_slash = make_v3_record(candidate_id="clip_x", run_id="run/a", clip_indices=(0,))
    rec_under = make_v3_record(candidate_id="clip_x", run_id="run_a", clip_indices=(0,))
    out_dir = tmp_path / "out_collision"

    # Run in two separate invocations targeting the same output_dir (simulates --run-id filtering)
    idx1 = extract_evidence_bundle([rec_slash], output_dir=out_dir, mode="metadata_only")
    idx2 = extract_evidence_bundle([rec_under], output_dir=out_dir, mode="metadata_only")

    p1 = idx1["entries"][0]["evidence_manifest"]
    p2 = idx2["entries"][0]["evidence_manifest"]
    assert p1 != p2
    assert (out_dir / p1).is_file()
    assert (out_dir / p2).is_file()

    # Now tamper with an existing manifest's binding identity and verify re-run refuses overwrite
    manifest_file = out_dir / p1
    tampered = json.loads(manifest_file.read_text(encoding="utf-8"))
    tampered["run_record"]["run_id"] = "different-other-run"
    manifest_file.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(EvidenceError, match="refusing to overwrite existing evidence manifest"):
        extract_evidence_bundle([rec_slash], output_dir=out_dir, mode="metadata_only")


@pytest.mark.parametrize("omitted_key", ["roi_frame_index", "original_source_frame_index", "clip_frame_index"])
def test_missing_frame_index_key_raises_evidence_error_and_cli_exit_2(
    tmp_path: Path, omitted_key: str
) -> None:
    """Finding 6: omitted index key in unverified record must return exit 2, never KeyError."""
    bad = make_v3_record(method="unverified", clip_indices=(0,))
    del bad["frames"][0][omitted_key]
    bad_path = write_jsonl(tmp_path / f"omit_{omitted_key}.jsonl", [bad])

    with pytest.raises(EvidenceError, match=omitted_key):
        load_input_records(bad_path)

    rc = main(
        [
            "--input-records",
            str(bad_path),
            "--output-dir",
            str(tmp_path / f"out_{omitted_key}"),
            "--metadata-only",
        ]
    )
    assert rc == 2

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "script.frame_correspondence",
            "--input-records",
            str(bad_path),
            "--output-dir",
            str(tmp_path / f"sub_out_{omitted_key}"),
            "--metadata-only",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert omitted_key in proc.stderr


def test_unmatched_subvideo_manifest_never_upgrades_audit_tier_to_full(tmp_path: Path) -> None:
    """Finding 7 (Advisory): only inherit audit_tier when candidate AND manifest_sha256 match."""
    # Case 1: manifest_sha256 mismatch -> must NOT inherit 'full'
    rec = make_v3_record(candidate_id="clip_tier", clip_indices=(0,))
    sv_wrong_sha = tmp_path / "sv_full_wrong_sha.json"
    sv_wrong_sha.write_text(
        json.dumps(
            {
                "schema": "tensile-unified-sub-video-manifest/1",
                "verification": {"mode": "full"},
                "candidates": [
                    {
                        "candidate_id": "clip_tier",
                        "source_video_id": "video_0001",
                        "output": {"sha256": L2_SHA},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sv_loaded = load_subvideo_manifest(sv_wrong_sha)
    assert sv_loaded["sha256"] != rec["manifest_sha256"]

    out_wrong = tmp_path / "out_wrong_manifest"
    idx_wrong = extract_evidence_bundle(
        [rec],
        output_dir=out_wrong,
        mode="metadata_only",
        subvideo_manifest=sv_loaded,
    )
    m_wrong = json.loads((out_wrong / idx_wrong["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert m_wrong["clip_identity"]["subvideo_manifest_binding"]["binding_verified"] is False
    assert m_wrong["proof_boundaries"]["audit_tier"] == "unknown"
    assert "subvideo_manifest_sha256_mismatch_tier_not_inherited" in m_wrong["proof_boundaries"]["active_limitations"]

    # Case 2: manifest_sha256 matches AND candidate matches -> inherits 'full' cleanly
    rec_matching = make_v3_record(candidate_id="clip_tier", clip_indices=(0,))
    rec_matching["manifest_sha256"] = sv_loaded["sha256"]
    out_match = tmp_path / "out_match_manifest"
    idx_match = extract_evidence_bundle(
        [rec_matching],
        output_dir=out_match,
        mode="metadata_only",
        subvideo_manifest=sv_loaded,
    )
    m_match = json.loads((out_match / idx_match["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert m_match["clip_identity"]["subvideo_manifest_binding"]["binding_verified"] is True
    assert m_match["proof_boundaries"]["audit_tier"] == "full"
    assert m_match["proof_boundaries"]["no_frame_level_replay"] is False
    assert m_match["proof_boundaries"]["replaces_full_receipt"] is False


# --------------------------------------------------------------------------- #
# 7. Regression tests for Codex PR #21 Round-2 review findings (Items 1-6)
# --------------------------------------------------------------------------- #

def test_same_run_id_multiple_input_ids_rejects_bare_run_dir_and_allows_input_slug(
    tmp_path: Path,
) -> None:
    """Round-2 Item 1: same (candidate_id, run_id) with distinct input_ids must not share bare <run_id> dir."""
    from script.frame_correspondence.evidence import _run_slug_for_record

    rec_1 = make_v3_record(candidate_id="clip_same_run", run_id="run-shared", clip_indices=(0,))
    rec_2 = make_v3_record(candidate_id="clip_same_run", run_id="run-shared", clip_indices=(15,))
    assert rec_1["input_id"] != rec_2["input_id"]

    # Case 1: Only bare <run_id>/<candidate_id>/frame_001.png exists -> ambiguous, must skip!
    bare_l3 = tmp_path / "bare_l3"
    (bare_l3 / "run-shared" / "clip_same_run").mkdir(parents=True)
    (bare_l3 / "run-shared" / "clip_same_run" / "frame_001.png").write_bytes(b"BARE_RUN_DIR_PNG")

    out_bare = tmp_path / "out_bare_ambig"
    idx_bare = extract_evidence_bundle(
        [rec_1, rec_2],
        output_dir=out_bare,
        mode="extract_images",
        extractor=FakeFrameExtractor(),
        l3_frames_dir=bare_l3,
    )
    for entry in idx_bare["entries"]:
        m = json.loads((out_bare / entry["evidence_manifest"]).read_text(encoding="utf-8"))
        l3 = m["frames"][0]["layers"]["l3"]
        assert l3["extraction_status"] == "skipped"
        assert "l3_image_ambiguous_same_run_id_multiple_input_ids" in l3["skip_reason"]
        assert l3["extracted_image"] is None

    # Case 2: Exact run_slug-scoped dirs exist -> each input_id copies its own PNG!
    slug_1 = _run_slug_for_record(rec_1)
    slug_2 = _run_slug_for_record(rec_2)
    assert slug_1 != slug_2
    exact_l3 = tmp_path / "exact_l3"
    (exact_l3 / slug_1 / "clip_same_run").mkdir(parents=True)
    (exact_l3 / slug_2 / "clip_same_run").mkdir(parents=True)
    (exact_l3 / slug_1 / "clip_same_run" / "frame_001.png").write_bytes(b"INPUT_1_EXACT_PNG")
    (exact_l3 / slug_2 / "clip_same_run" / "frame_001.png").write_bytes(b"INPUT_2_EXACT_PNG")

    out_exact = tmp_path / "out_exact_scoped"
    idx_exact = extract_evidence_bundle(
        [rec_1, rec_2],
        output_dir=out_exact,
        mode="extract_images",
        extractor=FakeFrameExtractor(),
        l3_frames_dir=exact_l3,
    )
    m1 = json.loads((out_exact / idx_exact["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    m2 = json.loads((out_exact / idx_exact["entries"][1]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert m1["frames"][0]["layers"]["l3"]["extraction_status"] == "copied"
    assert m1["frames"][0]["layers"]["l3"]["binding_basis"] == "input_scoped_directory"
    assert m1["frames"][0]["layers"]["l3"]["observed_sha256"] == hashlib.sha256(b"INPUT_1_EXACT_PNG").hexdigest()
    assert m2["frames"][0]["layers"]["l3"]["extraction_status"] == "copied"
    assert m2["frames"][0]["layers"]["l3"]["binding_basis"] == "input_scoped_directory"
    assert m2["frames"][0]["layers"]["l3"]["observed_sha256"] == hashlib.sha256(b"INPUT_2_EXACT_PNG").hexdigest()


def test_missing_record_manifest_sha256_never_verifies_subvideo_manifest_binding(
    tmp_path: Path,
) -> None:
    """Round-2 Item 2: record without manifest_sha256 must NOT inherit full tier or source_video_id."""
    rec = make_v3_record(candidate_id="clip_no_msha", source_video_id="video_0001", clip_indices=(0,))
    rec["manifest_sha256"] = None

    sv_path = tmp_path / "sv_full.json"
    sv_path.write_text(
        json.dumps(
            {
                "schema": "tensile-unified-sub-video-manifest/1",
                "verification": {"mode": "full"},
                "candidates": [
                    {
                        "candidate_id": "clip_no_msha",
                        "source_video_id": "video_WRONG_OVERRIDE",
                        "output": {"sha256": L2_SHA},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out_no_msha"
    idx = extract_evidence_bundle(
        [rec],
        output_dir=out_dir,
        mode="metadata_only",
        subvideo_manifest=load_subvideo_manifest(sv_path),
    )
    m = json.loads((out_dir / idx["entries"][0]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert m["clip_identity"]["subvideo_manifest_binding"]["binding_verified"] is False
    assert m["clip_identity"]["subvideo_manifest_binding"]["record_manifest_sha256_match"] is None
    assert m["proof_boundaries"]["audit_tier"] == "unknown"
    assert "subvideo_manifest_record_sha256_missing_tier_not_inherited" in m["proof_boundaries"]["active_limitations"]
    # source_video_id must remain derived from record L0 path, NOT overridden by unverified manifest
    assert m["clip_identity"]["source_video_id"] == "video_0001"


def test_preflight_duplicate_identity_fails_without_modifying_existing_snapshot(
    tmp_path: Path,
) -> None:
    """Round-2 Item 3: [A, A] duplicate batch fails in pre-flight before modifying any prior files."""
    rec_a = make_v3_record(candidate_id="clip_dup", run_id="run-dup", clip_indices=(0,))
    out_dir = tmp_path / "out_preflight"

    first_idx = extract_evidence_bundle([rec_a], output_dir=out_dir, mode="metadata_only")
    manifest_path = out_dir / first_idx["entries"][0]["evidence_manifest"]
    index_md_path = out_dir / first_idx["entries"][0]["index_markdown"]
    run_index_path = out_dir / "run_index.json"

    # Inject a marker into existing index.md & run_index.json to prove zero writes happen on failure
    index_md_path.write_text("SENTINEL_INDEX_MD", encoding="utf-8")
    run_index_before = run_index_path.read_bytes()
    manifest_before = manifest_path.read_bytes()

    with pytest.raises(EvidenceError, match="duplicate record identity"):
        extract_evidence_bundle([rec_a, copy.deepcopy(rec_a)], output_dir=out_dir, mode="metadata_only")

    assert index_md_path.read_text(encoding="utf-8") == "SENTINEL_INDEX_MD"
    assert run_index_path.read_bytes() == run_index_before
    assert manifest_path.read_bytes() == manifest_before


def test_atomic_writes_do_not_truncate_hard_linked_files(tmp_path: Path) -> None:
    """Round-2 Item 4: atomic replace writes new inodes without modifying hard-linked targets."""
    import os

    rec = make_v3_record(candidate_id="clip_hl", run_id="run-hl", clip_indices=(0,))
    out_dir = tmp_path / "out_hardlink"
    first_idx = extract_evidence_bundle([rec], output_dir=out_dir, mode="metadata_only")

    manifest_path = out_dir / first_idx["entries"][0]["evidence_manifest"]
    index_md_path = out_dir / first_idx["entries"][0]["index_markdown"]
    run_index_path = out_dir / "run_index.json"

    sentinel_dir = tmp_path / "hardlink_sentinels"
    sentinel_dir.mkdir()
    sent_manifest = sentinel_dir / "manifest.json"
    sent_index = sentinel_dir / "index.md"
    sent_run_index = sentinel_dir / "run_index.json"
    os.link(manifest_path, sent_manifest)
    os.link(index_md_path, sent_index)
    os.link(run_index_path, sent_run_index)

    orig_manifest_ino = sent_manifest.stat().st_ino
    orig_index_ino = sent_index.stat().st_ino
    orig_run_idx_ino = sent_run_index.stat().st_ino
    orig_index_bytes = sent_index.read_bytes()

    # Overwrite index_md via sentinel to check original inode contents remain untouched on re-run
    sent_index.write_bytes(b"ORIGINAL_HARDLINK_INODE_CONTENT")

    extract_evidence_bundle([rec], output_dir=out_dir, mode="metadata_only")

    # Sentinels keep their original inodes and bytes; output files got fresh inodes
    assert sent_manifest.stat().st_ino == orig_manifest_ino
    assert sent_index.stat().st_ino == orig_index_ino
    assert sent_run_index.stat().st_ino == orig_run_idx_ino
    assert sent_index.read_bytes() == b"ORIGINAL_HARDLINK_INODE_CONTENT"
    assert manifest_path.stat().st_ino != orig_manifest_ino
    assert index_md_path.stat().st_ino != orig_index_ino
    assert run_index_path.stat().st_ino != orig_run_idx_ino
    assert index_md_path.read_bytes() == orig_index_bytes


def test_rejects_bare_git_repository_and_subdirectories(tmp_path: Path) -> None:
    """Round-2 Item 5: bare Git repositories and their subdirectories must be rejected."""
    bare_repo = tmp_path / "bare_mirror.git"
    proc = subprocess.run(
        ["git", "init", "--bare", str(bare_repo)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    with pytest.raises(EvidenceError, match="inside Git repository"):
        ensure_output_outside_git_repo(bare_repo)

    with pytest.raises(EvidenceError, match="inside Git repository"):
        ensure_output_outside_git_repo(bare_repo / "sub" / "evidence_out")

    rec = make_v3_record(candidate_id="clip_bare", run_id="run-bare", clip_indices=(0,))
    with pytest.raises(EvidenceError, match="inside Git repository"):
        extract_evidence_bundle([rec], output_dir=bare_repo / "out", mode="metadata_only")


def test_ffmpeg_showinfo_parses_scientific_notation_pts_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-2 Item 6 (Advisory): pts_time in scientific notation (1e-05, 1.5e-03) parses accurately."""
    fake_bin = tmp_path / "ffmpeg"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    extractor = FfmpegFrameExtractor(ffmpeg_bin=str(fake_bin))

    for raw_ts, expected in (("1e-05", 1e-05), ("1.5e-03", 0.0015), ("2.25E+01", 22.5)):
        out_png = tmp_path / f"sci_{raw_ts}.png"

        def fake_run(cmd, capture_output, text, _ts=raw_ts):
            Path(cmd[-1]).write_bytes(b"PNGDATA")
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="",
                stderr=f"[Parsed_showinfo_1 @ 0x0] n:   0 pts:     1 pts_time:{_ts} pos:42",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        res = extractor.extract_video_frame(video, 0, out_png)
        assert res.status == "extracted"
        assert res.pts_seconds == pytest.approx(expected)
