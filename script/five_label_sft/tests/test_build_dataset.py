"""Unit and integration tests for dual-channel Fold SFT dataset builder and anti-leakage guards."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any
import zlib

import pytest

from script.five_label_eval.errors import InputError
from script.five_label_eval.frames import RECORD_SCHEMA, SAMPLING_RULE, SHORT_CLIP_POLICY, sample_frame_indices
from script.five_label_eval.score import extract
from script.five_label_sft.build_dataset import (
    PNG_MAGIC,
    build_dataset_info_fragment,
    build_fold_sft_dataset,
    build_sharegpt_record,
    main as build_main,
)
from script.five_label_sft.constants import REPO_ROOT
from script.five_label_sft.data_guards import (
    assert_no_fold_leakage,
    canonicalize_and_verify_target_json,
    load_fold_isolation_context,
    select_confirmed_fold_train_samples,
)
from script.subvideo_review.server import ReviewApp, STORE_SCHEMA, canonical, digest


VALID_LABELS: dict[str, Any] = {
    "断裂状态": "发生断裂",
    "断裂模式": "韧性断裂",
    "断裂位置": "标距内",
    "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
    "断裂现象": {"伸长": "是", "颈缩": "是", "开裂": "否", "界面分离": "否", "断后脱夹": "否"},
}


def _make_revision(
    candidate: dict[str, Any],
    *,
    review_id: str,
    status: str = "confirmed",
    labels: dict[str, Any] | None = None,
    created_at: str = "2026-11-27T01:00:00+00:00",
    override_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "review_id": review_id,
        "candidate_id": candidate["candidate_id"],
        "source_id": candidate["source_id"],
        "source_type": candidate["source_type"],
        "clip_sha256": candidate["clip_sha256"],
        "manifest_sha256": candidate["manifest_sha256"],
        "review_subject_sha256": candidate["review_subject_sha256"],
        "review_status": status,
        "labels": VALID_LABELS if labels is None else labels,
        "created_at": created_at,
    }
    if override_fields:
        row.update(override_fields)
    row["revision_sha256"] = digest(canonical(row))
    return row


def _create_synthetic_repo(tmp_path: Path) -> dict[str, Any]:
    """Create a minimal self-contained repo fixture compatible with ReviewApp and DEC-007."""
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs/label.md").write_text("# label rules v1\n", encoding="utf-8")

    splits_dir = tmp_path / "data/splits/three-fold"
    splits_dir.mkdir(parents=True)
    # 2 clean train sources (video_0002, video_0003), 1 DEC-007 excluded train source (video_0079),
    # 1 val source (video_0001), 1 test source (video_0005)
    fold_train = {
        0: ["video_0002", "video_0003", "video_0079"],
        1: ["video_0001", "video_0003", "video_0079"],
        2: ["video_0001", "video_0002"],
    }
    fold_val = {
        0: ["video_0001"],
        1: ["video_0002"],
        2: ["video_0003", "video_0079"],
    }
    test_ids = ["video_0005"]
    for k in (0, 1, 2):
        (splits_dir / f"fold_{k}_train.json").write_text(
            json.dumps({"split": f"fold_{k}_train", "video_ids": fold_train[k]}), encoding="utf-8"
        )
        (splits_dir / f"fold_{k}_val.json").write_text(
            json.dumps({"split": f"fold_{k}_val", "video_ids": fold_val[k]}), encoding="utf-8"
        )
    (splits_dir / "test.json").write_text(json.dumps({"split": "test", "video_ids": test_ids}), encoding="utf-8")
    (splits_dir / "manifest.json").write_text(json.dumps({"folds": 3}), encoding="utf-8")

    # Copy official DEC-007 exclusions file
    (tmp_path / "data/splits/dev-exclusions.json").write_bytes(
        (REPO_ROOT / "data/splits/dev-exclusions.json").read_bytes()
    )

    def _source_entry(sid: str) -> dict[str, Any]:
        return {
            "video_id": sid,
            "source_type": "real",
            "source_sha256": hashlib.sha256(f"src:{sid}".encode()).hexdigest(),
            "roi_sha256": hashlib.sha256(f"roi:{sid}".encode()).hexdigest(),
        }

    def _cand_entry(cid: str, sid: str, role: str, w: int, h: int, tf: int) -> dict[str, Any]:
        scope = "test" if sid in test_ids else "development"
        folds = (
            {str(k): "test" for k in (0, 1, 2)}
            if scope == "test"
            else {str(k): ("train" if sid in fold_train[k] else "val") for k in (0, 1, 2)}
        )
        return {
            "candidate_id": cid,
            "source_video_id": sid,
            "source_type": "real",
            "role": role,
            "scope": scope,
            "folds": folds,
            "output_path": f"videos/{cid}.mp4",
            "output": {
                "sha256": hashlib.sha256(f"clip:{cid}".encode()).hexdigest(),
                "media": {"width": w, "height": h, "total_frames": tf, "fps": 30.0},
            },
        }

    sources = [_source_entry(s) for s in ("video_0001", "video_0002", "video_0003", "video_0005", "video_0079")]
    candidates = [
        _cand_entry("video_0002_pre_01", "video_0002", "pre", 300, 400, 60),
        _cand_entry("video_0002_fracture_01", "video_0002", "fracture", 804, 1072, 180),
        _cand_entry("video_0003_post_01", "video_0003", "post", 150, 200, 90),  # will be draft
        _cand_entry("video_0003_pre_01", "video_0003", "pre", 150, 200, 90),  # confirmed then returned
        _cand_entry("video_0003_coverage_01", "video_0003", "coverage", 150, 200, 90),  # isolated old revision only
        _cand_entry("video_0079_fracture_01", "video_0079", "fracture", 400, 500, 60),  # DEC-007 excluded
        _cand_entry("video_0001_fracture_01", "video_0001", "fracture", 400, 500, 60),  # fold 0 val
        _cand_entry("video_0005_fracture_01", "video_0005", "fracture", 400, 500, 60),  # fixed test
    ]

    sub_dir = tmp_path / "data/sub_video"
    sub_dir.mkdir(parents=True)
    manifest_path = sub_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema": "subvideo-manifest/1", "sources": sources, "candidates": candidates}, ensure_ascii=False),
        encoding="utf-8",
    )

    eval_dir = tmp_path / "data/eval-subsets"
    eval_dir.mkdir(parents=True)
    (eval_dir / "eval-dev-v1.json").write_text(
        json.dumps(["video_0001_fracture_01", "video_0002_pre_01"]), encoding="utf-8"
    )
    (eval_dir / "eval-test-v1.json").write_text(json.dumps(["video_0005_fracture_01"]), encoding="utf-8")

    prompt_dir = tmp_path / "script/five_label_eval/prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "five_label_v2.txt").write_bytes((REPO_ROOT / "script/five_label_eval/prompts/five_label_v2.txt").read_bytes())

    rev_dir = tmp_path / "data/subvideo-review"
    rev_dir.mkdir(parents=True)
    reviews_path = rev_dir / "reviews.json"

    app = ReviewApp(tmp_path, manifest=manifest_path, records=reviews_path)
    revisions = [
        _make_revision(app.candidates["video_0002_pre_01"], review_id="rev-1", status="confirmed"),
        _make_revision(app.candidates["video_0002_fracture_01"], review_id="rev-2", status="confirmed"),
        # Draft must be skipped
        _make_revision(app.candidates["video_0003_post_01"], review_id="rev-3", status="draft"),
        # Confirmed earlier, later returned -> latest is returned, must be skipped
        _make_revision(
            app.candidates["video_0003_pre_01"],
            review_id="rev-4a",
            status="confirmed",
            created_at="2026-11-26T01:00:00+00:00",
        ),
        _make_revision(
            app.candidates["video_0003_pre_01"],
            review_id="rev-4b",
            status="returned",
            created_at="2026-11-27T01:00:00+00:00",
        ),
        # Historical isolated revision (mismatched review_subject_sha256) -> must be skipped
        _make_revision(
            app.candidates["video_0003_coverage_01"],
            review_id="rev-5",
            status="confirmed",
            override_fields={"review_subject_sha256": "0" * 64},
        ),
        # Confirmed DEC-007 excluded, fold 0 val, and fixed test -> all must be excluded from fold 0 train
        _make_revision(app.candidates["video_0079_fracture_01"], review_id="rev-6", status="confirmed"),
        _make_revision(app.candidates["video_0001_fracture_01"], review_id="rev-7", status="confirmed"),
        _make_revision(app.candidates["video_0005_fracture_01"], review_id="rev-8", status="confirmed"),
    ]
    reviews_path.write_text(
        json.dumps({"schema": STORE_SCHEMA, "revisions": revisions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"root": tmp_path, "app": app, "manifest_path": manifest_path, "reviews_path": reviews_path}


def _make_valid_1x1_png(r: int, g: int, b: int) -> bytes:
    """Create a genuine decodable 1x1 RGB PNG byte stream using only Python stdlib."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)

    ihdr = struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw_scanline = bytes([0, r & 0xFF, g & 0xFF, b & 0xFF])
    idat = zlib.compress(raw_scanline)
    return PNG_MAGIC + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _write_fake_frames_and_manifest(
    root: Path,
    manifest_sha: str,
    samples: list[dict[str, Any]],
    num_frames: int,
) -> tuple[Path, Path]:
    frames_dir = root / "l3_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    records_path = frames_dir / f"records_{num_frames}f.jsonl"
    lines: list[str] = []
    for s_idx, s in enumerate(samples):
        cid = s["candidate_id"]
        cdir = frames_dir / cid
        cdir.mkdir(parents=True, exist_ok=True)
        indices = sample_frame_indices(s["total_frames"], num_frames)
        frame_rows = []
        for order, fidx in enumerate(indices):
            fname = f"frame_{order:02d}.png"
            raw = _make_valid_1x1_png(s_idx + 1, order, fidx % 256)
            (cdir / fname).write_bytes(raw)
            frame_rows.append(
                {
                    "display_order": order,
                    "decode_order": order,
                    "clip_frame_index": fidx,
                    "image": fname,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        rec = {
            "record_schema": RECORD_SCHEMA,
            "candidate_id": cid,
            "clip_sha256": s["clip_sha256"],
            "manifest_sha256": manifest_sha,
            "sampling": {
                "sampling_rule": SAMPLING_RULE,
                "target_frame_count": num_frames,
                "short_clip_policy": SHORT_CLIP_POLICY,
                "resize": None,
            },
            "frames": frame_rows,
        }
        lines.append(json.dumps(rec, ensure_ascii=False))
    records_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return frames_dir, records_path


def test_dual_channel_format_and_filtering_on_synthetic_repo(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    root = fx["root"]
    ctx = load_fold_isolation_context(0, repo_root=root)
    samples, _ = select_confirmed_fold_train_samples(ctx)
    assert [s.candidate_id for s in samples] == ["video_0002_fracture_01", "video_0002_pre_01"]

    sample_meta = [
        {"candidate_id": s.candidate_id, "clip_sha256": s.clip_sha256, "total_frames": s.total_frames}
        for s in samples
    ]

    # 1. 8f images channel with verified frames_manifest + PNG SHA-256
    fdir8, rec8 = _write_fake_frames_and_manifest(tmp_path / "m8", ctx.manifest_sha256, sample_meta, 8)
    out8 = tmp_path / "out_images_8f"
    summary8 = build_fold_sft_dataset(
        fold=0,
        modality="images",
        num_frames=8,
        output_dir=out8,
        frames_manifest=rec8,
        frames_dir=fdir8,
        repo_root=root,
    )
    assert summary8["isolation_checks"]["exported_candidate_count"] == 2
    assert summary8["skipped_revisions"]["isolated_history_only_candidates"] == 1
    assert summary8["skipped_revisions"]["skipped_non_confirmed_by_status"] == {"draft": 1, "returned": 1}
    assert summary8["skipped_revisions"]["skipped_confirmed_dec007_excluded"] == 1
    assert summary8["skipped_revisions"]["skipped_confirmed_outside_fold_train"] == 2  # val + test

    ds8 = json.loads((out8 / f"{summary8['dataset_name']}.json").read_text(encoding="utf-8"))
    info8 = json.loads((out8 / "dataset_info.json").read_text(encoding="utf-8"))
    assert len(ds8) == 2
    for row in ds8:
        assert [m["role"] for m in row["messages"]] == ["user", "assistant"]
        assert row["messages"][0]["content"].startswith("<image>" * 8 + "\n")
        assert row["messages"][0]["content"].count("<image>") == 8
        assert row["messages"][0]["content"].count("<video>") == 0
        assert len(row["images"]) == 8
        assert "videos" not in row
        parsed = extract(row["messages"][1]["content"])
        assert parsed["strict_format_valid"] is True
        assert parsed["issues"] == []
        assert parsed["conflicts"] == []
    assert info8[summary8["dataset_name"]]["formatting"] == "sharegpt"
    assert info8[summary8["dataset_name"]]["columns"] == {"messages": "messages", "images": "images"}

    # 2. 16f <video> channel with nested videos: [[f0..f15]] and no system turn
    fdir16, rec16 = _write_fake_frames_and_manifest(tmp_path / "m16", ctx.manifest_sha256, sample_meta, 16)
    out16 = tmp_path / "out_video_16f"
    summary16 = build_fold_sft_dataset(
        fold=0,
        modality="video",
        num_frames=16,
        output_dir=out16,
        frames_manifest=rec16,
        frames_dir=fdir16,
        repo_root=root,
    )
    ds16 = json.loads((out16 / f"{summary16['dataset_name']}.json").read_text(encoding="utf-8"))
    info16 = json.loads((out16 / "dataset_info.json").read_text(encoding="utf-8"))
    assert len(ds16) == 2
    for row in ds16:
        assert [m["role"] for m in row["messages"]] == ["user", "assistant"]
        assert row["messages"][0]["content"].startswith("<video>\n")
        assert row["messages"][0]["content"].count("<video>") == 1
        assert row["messages"][0]["content"].count("<image>") == 0
        assert len(row["videos"]) == 1
        assert len(row["videos"][0]) == 16
        assert "images" not in row
    assert info16[summary16["dataset_name"]]["columns"] == {"messages": "messages", "videos": "videos"}


def test_anti_leakage_guard_blocks_val_test_dec007_and_eval_test(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    ctx = load_fold_isolation_context(0, repo_root=fx["root"])

    # Inject fold_0_val source
    with pytest.raises(InputError, match="fold_0_val"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "video_0001_fracture_01", "source_id": "video_0001", "source_type": "real"}],
        )

    # Inject fixed test.json source
    with pytest.raises(InputError, match="test.json"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "video_0005_fracture_01", "source_id": "video_0005", "source_type": "real"}],
        )

    # Inject DEC-007 excluded dev source (video_0079 / video_0006)
    with pytest.raises(InputError, match="DEC-007"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "video_0079_fracture_01", "source_id": "video_0079", "source_type": "real"}],
        )

    # Inject DEC-007 isolated virtual video even if disguised as clean train source
    isolated_vid = next(iter(ctx.exclusions.isolated_virtual_ids))
    with pytest.raises(InputError, match="DEC-007"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": isolated_vid, "source_id": "video_0002", "source_type": "real"}],
        )

    # Inject eval-test-v1 candidate_id even if source_id is spoofed as a clean train source
    with pytest.raises(InputError, match="eval-test-v1 candidates"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "video_0005_fracture_01", "source_id": "video_0002", "source_type": "real"}],
        )

    # Inject eval-dev-v1 ∩ fold_0_val candidate_id even if source_id is spoofed as a clean train source
    with pytest.raises(InputError, match="eval-dev-v1 ∩ fold_0_val"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "video_0001_fracture_01", "source_id": "video_0002", "source_type": "real"}],
        )

    # Inject unknown candidate_id attached to clean train source -> must fail closed
    with pytest.raises(InputError, match="unknown candidate_id"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "totally_unknown_cid", "source_id": "video_0002", "source_type": "real"}],
        )

    # Inject mismatched source_id for a valid train candidate_id -> must fail closed
    with pytest.raises(InputError, match="manifest source_id"):
        assert_no_fold_leakage(
            ctx,
            [{"candidate_id": "video_0002_pre_01", "source_id": "video_0003", "source_type": "real"}],
        )


def test_custom_mismatched_splits_dir_fails_closed(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    other_splits = tmp_path / "other_splits"
    other_splits.mkdir()
    with pytest.raises(InputError, match="custom splits_dir"):
        load_fold_isolation_context(0, repo_root=fx["root"], splits_dir=other_splits)


def test_build_dataset_refuses_protected_output_dirs_reserved_names_and_symlink_targets(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    root = fx["root"]
    for bad_out in (
        root / "data/splits/evil_out",
        root / "data/SPLITS/evil_out",
        root / "data/roi/evil_out",
        "data//sub_video/evil_out",
        "Data/Sub_Video/evil_out",
        "LlamaFactory//saves/evil_out",
        "LLAMAFACTORY/SAVES/evil_out",
    ):
        with pytest.raises(InputError, match="protected path"):
            build_fold_sft_dataset(
                fold=0,
                modality="images",
                num_frames=8,
                output_dir=bad_out,
                allow_missing_frames_dry_run=True,
                repo_root=root,
            )

    # Reserved artifact names must be rejected so dataset JSON never overwrites dataset_info/build_summary/preflight
    for reserved in ("dataset_info", "build_summary", "preflight_report"):
        with pytest.raises(InputError, match="reserved bundle artifact"):
            build_fold_sft_dataset(
                fold=0,
                modality="images",
                num_frames=8,
                output_dir=tmp_path / f"reserved_{reserved}",
                dataset_name=reserved,
                allow_missing_frames_dry_run=True,
                repo_root=root,
            )

    # Symlink target inside normal output_dir pointing to protected test.json MUST fail even with overwrite=True
    test_split_path = root / "data/splits/three-fold/test.json"
    original_test_bytes = test_split_path.read_bytes()
    sym_out = tmp_path / "normal_out_with_symlink"
    sym_out.mkdir()
    (sym_out / "dataset_info.json").symlink_to(test_split_path)
    with pytest.raises(InputError, match="protected path|symlink"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=sym_out,
            allow_missing_frames_dry_run=True,
            repo_root=root,
            overwrite=True,
        )
    assert test_split_path.read_bytes() == original_test_bytes

    # Natural numeric sorting of frame_1.png .. frame_10.png under explicit dry-run frames_dir
    ctx = load_fold_isolation_context(0, repo_root=root)
    samples, _ = select_confirmed_fold_train_samples(ctx)
    fdir = tmp_path / "nat_frames"
    for s in samples:
        cdir = fdir / s.candidate_id
        cdir.mkdir(parents=True)
        for idx in (10, 2, 1, 8, 3, 4, 5, 6):
            (cdir / f"frame_{idx}.png").write_bytes(PNG_MAGIC + f"{idx}".encode())
    out_dir = tmp_path / "nat_out"
    summary = build_fold_sft_dataset(
        fold=0,
        modality="images",
        num_frames=8,
        output_dir=out_dir,
        frames_dir=fdir,
        allow_missing_frames_dry_run=True,
        repo_root=root,
    )
    ds = json.loads((out_dir / f"{summary['dataset_name']}.json").read_text(encoding="utf-8"))
    names = [Path(p).name for p in ds[0]["images"]]
    assert names == ["frame_1.png", "frame_2.png", "frame_3.png", "frame_4.png", "frame_5.png", "frame_6.png", "frame_8.png", "frame_10.png"]


def test_symlink_frame_rejected_fail_closed(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    root = fx["root"]
    ctx = load_fold_isolation_context(0, repo_root=root)
    samples, _ = select_confirmed_fold_train_samples(ctx)
    sample_meta = [
        {"candidate_id": s.candidate_id, "clip_sha256": s.clip_sha256, "total_frames": s.total_frames}
        for s in samples
    ]
    fdir8, rec8 = _write_fake_frames_and_manifest(tmp_path / "sym", ctx.manifest_sha256, sample_meta, 8)
    real_outside = tmp_path / "outside.png"
    real_outside.write_bytes(PNG_MAGIC + b"outside")
    target = fdir8 / samples[0].candidate_id / "frame_00.png"
    target.unlink()
    target.symlink_to(real_outside)

    with pytest.raises(InputError, match="symlink"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=tmp_path / "out_sym",
            frames_manifest=rec8,
            frames_dir=fdir8,
            repo_root=root,
        )


def test_target_json_rejects_invalid_enum_and_combination_conflict() -> None:
    bad_enum = json.loads(json.dumps(VALID_LABELS))
    bad_enum["断裂模式"] = "无"
    with pytest.raises(InputError, match="invalid confirmed labels"):
        canonicalize_and_verify_target_json(bad_enum)

    bad_legacy = json.loads(json.dumps(VALID_LABELS))
    bad_legacy["断裂状态"] = "无法确定"
    with pytest.raises(InputError, match="invalid confirmed labels"):
        canonicalize_and_verify_target_json(bad_legacy)

    conflict = json.loads(json.dumps(VALID_LABELS))
    conflict["断裂状态"] = "未断裂"
    conflict["异常情况"]["爆炸性断裂"] = "是"
    with pytest.raises(InputError, match="互斥"):
        canonicalize_and_verify_target_json(conflict)


def test_tampered_revision_sha256_fails_closed(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    reviews_path = fx["reviews_path"]
    payload = json.loads(reviews_path.read_text(encoding="utf-8"))
    payload["revisions"][0]["labels"]["断裂状态"] = "已断裂"  # without updating revision_sha256
    reviews_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(InputError, match="ReviewApp"):
        load_fold_isolation_context(0, repo_root=fx["root"])


def test_frame_sha256_mismatch_and_missing_frames_fail_closed(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    root = fx["root"]
    ctx = load_fold_isolation_context(0, repo_root=root)
    samples, _ = select_confirmed_fold_train_samples(ctx)
    sample_meta = [
        {"candidate_id": s.candidate_id, "clip_sha256": s.clip_sha256, "total_frames": s.total_frames}
        for s in samples
    ]

    # Missing frames_manifest without --allow-missing-frames-dry-run must fail closed
    with pytest.raises(InputError, match="requires --frames-manifest"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=tmp_path / "fail_no_frames",
            repo_root=root,
        )

    # Supplying --frames-dir alone without --frames-manifest in non-dry-run mode MUST fail closed
    # (prevents mismatched PNGs from another clip from pairing silently with train labels)
    fdir8, rec8 = _write_fake_frames_and_manifest(tmp_path / "tamper", ctx.manifest_sha256, sample_meta, 8)
    with pytest.raises(InputError, match="requires --frames-manifest"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=tmp_path / "fail_dir_only",
            frames_dir=fdir8,
            repo_root=root,
        )

    # Supplying --frame-path-prefix in non-dry-run mode MUST fail closed
    # (prevents decoupling SHA-256-verified local PNGs from unverified emitted paths)
    with pytest.raises(InputError, match="--frame-path-prefix is forbidden"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=tmp_path / "fail_prefix",
            frames_manifest=rec8,
            frames_dir=fdir8,
            frame_path_prefix="/other/unverified/8f_cache",
            repo_root=root,
        )

    # Swapping/corrupting PNG bytes against frames-manifest SHA-256 must fail closed
    (fdir8 / samples[0].candidate_id / "frame_00.png").write_bytes(PNG_MAGIC + b"wrong_clip_frame")
    with pytest.raises(InputError, match="sha256 mismatch"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=tmp_path / "fail_sha",
            frames_manifest=rec8,
            frames_dir=fdir8,
            repo_root=root,
        )


def test_verified_manifest_export_overwrite_guard_and_extra_exclusions_provenance(tmp_path: Path) -> None:
    fx = _create_synthetic_repo(tmp_path)
    root = fx["root"]
    ctx = load_fold_isolation_context(0, repo_root=root)
    samples, _ = select_confirmed_fold_train_samples(ctx)
    sample_meta = [
        {"candidate_id": s.candidate_id, "clip_sha256": s.clip_sha256, "total_frames": s.total_frames}
        for s in samples
    ]
    fdir8, rec8 = _write_fake_frames_and_manifest(tmp_path / "direct", ctx.manifest_sha256, sample_meta, 8)
    out_dir = tmp_path / "out_direct"

    # Optional supplemental exclusions file preserves official + extra hashes separately
    extra_excl = tmp_path / "extra_exclusions.json"
    extra_excl.write_text(
        json.dumps(
            {
                "schema": "tensile-dev-exclusions/1",
                "decision_id": "DEC-EXTRA",
                "excluded_dev_sources": [],
                "isolated_virtual_videos": [],
            }
        ),
        encoding="utf-8",
    )

    summary = build_fold_sft_dataset(
        fold=0,
        modality="images",
        num_frames=8,
        output_dir=out_dir,
        frames_manifest=rec8,
        frames_dir=fdir8,
        exclusions_path=extra_excl,
        repo_root=root,
    )
    assert summary["dry_run_missing_frames"] is False
    assert summary["inputs"]["dev_exclusions_path"] == "data/splits/dev-exclusions.json"
    assert summary["inputs"]["dev_exclusions_extra_path"] == str(extra_excl)
    assert summary["inputs"]["dev_exclusions_extra_sha256"] == hashlib.sha256(extra_excl.read_bytes()).hexdigest()

    # Second write without overwrite=True must refuse
    with pytest.raises(InputError, match="refusing to overwrite"):
        build_fold_sft_dataset(
            fold=0,
            modality="images",
            num_frames=8,
            output_dir=out_dir,
            frames_manifest=rec8,
            frames_dir=fdir8,
            repo_root=root,
            overwrite=False,
        )

    # Second write with overwrite=True succeeds via atomic replacement on regular files
    summary2 = build_fold_sft_dataset(
        fold=0,
        modality="images",
        num_frames=8,
        output_dir=out_dir,
        frames_manifest=rec8,
        frames_dir=fdir8,
        repo_root=root,
        overwrite=True,
    )
    assert summary2["fingerprints"]["dataset_sha256"] == summary["fingerprints"]["dataset_sha256"]


def test_sharegpt_record_rejects_placeholder_in_prompt_and_non_strict_target() -> None:
    _, valid_json = canonicalize_and_verify_target_json(VALID_LABELS)
    with pytest.raises(InputError, match="placeholders"):
        build_sharegpt_record(
            modality="video",
            num_frames=8,
            prompt_text="bad <video> prompt",
            target_json=valid_json,
            frame_paths=[f"/tmp/f{i}.png" for i in range(8)],
        )
    with pytest.raises(InputError, match="non-strict"):
        build_sharegpt_record(
            modality="video",
            num_frames=8,
            prompt_text="clean prompt",
            target_json=f"```json\n{valid_json}\n```",
            frame_paths=[f"/tmp/f{i}.png" for i in range(8)],
        )
    info = build_dataset_info_fragment(dataset_name="demo", file_name="demo.json", modality="video")
    assert info["demo"]["columns"]["videos"] == "videos"


def test_real_repo_fold0_dry_run_both_channels(tmp_path: Path) -> None:
    """Read-only dry-run against real repo manifest.json & reviews.json verifying Fold 0 counts & zero leakage."""
    out_img = tmp_path / "real_fold0_images_8f"
    rc_img = build_main(
        [
            "--fold",
            "0",
            "--modality",
            "images",
            "--num-frames",
            "8",
            "--output-dir",
            str(out_img),
            "--allow-missing-frames-dry-run",
            "--repo-root",
            str(REPO_ROOT),
        ]
    )
    assert rc_img == 0
    sum_img = json.loads((out_img / "build_summary.json").read_text(encoding="utf-8"))
    assert sum_img["dry_run_missing_frames"] is True
    assert sum_img["isolation_checks"]["clean_train_source_pool_count"] == 58
    # Current confirmed clean Fold 0 train count (210 eval-dev-v1 - 69 fold_0_val = 141; grows as B3 is confirmed)
    assert sum_img["isolation_checks"]["exported_candidate_count"] >= 141
    assert sum_img["isolation_checks"]["fold_val_source_overlap"] == 0
    assert sum_img["isolation_checks"]["test_source_overlap"] == 0
    assert sum_img["isolation_checks"]["eval_test_v1_candidate_overlap"] == 0
    assert sum_img["isolation_checks"]["eval_dev_v1_fold_val_candidate_overlap"] == 0
    assert sum_img["isolation_checks"]["dec007_excluded_overlap"] == 0
    assert sum_img["preflight_summary"]["exceeds_cutoff_count"] == 0
    assert sum_img["preflight_summary"]["short_clip_count"] == 0

    out_vid = tmp_path / "real_fold0_video_16f"
    rc_vid = build_main(
        [
            "--fold",
            "0",
            "--modality",
            "video",
            "--num-frames",
            "16",
            "--output-dir",
            str(out_vid),
            "--allow-missing-frames-dry-run",
            "--fail-on-lf-downscale",
            "--repo-root",
            str(REPO_ROOT),
        ]
    )
    assert rc_vid == 0
    sum_vid = json.loads((out_vid / "build_summary.json").read_text(encoding="utf-8"))
    assert sum_vid["isolation_checks"]["exported_candidate_count"] == sum_img["isolation_checks"]["exported_candidate_count"]
    assert sum_vid["preflight_summary"]["vllm_alignment_clean"] is True
    assert sum_vid["preflight_summary"]["exceeds_cutoff_count"] == 0
