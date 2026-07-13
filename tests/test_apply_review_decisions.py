import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import apply_label_corrections as alc
import apply_review_decisions as ard


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_apply_review_decisions_approved_syncs_type_canonical(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "type": "old_type",
                    "type_canonical": "old_type",
                    "has_fracture": True,
                    "location": "left",
                }
            ]
        },
    )
    _write_json(
        dec,
        {
            "decisions": [
                {
                    "subvideo_id": "sv1",
                    "status": "approved",
                    "corrected_labels": {"type": "new_type"},
                }
            ]
        },
    )

    summary = ard.apply_review_decisions(meta, dec, out, strict=True)
    assert summary["status_counts"]["approved"] == 1
    assert summary["blockers"] == []

    out_data = json.loads(out.read_text())
    sub = out_data["subvideos"][0]
    assert sub["type"] == "new_type"
    assert sub["type_canonical"] == "new_type"


def test_apply_review_drops_unverified_edited_fracture_interval(tmp_path):
    meta, decisions, video_meta = (tmp_path / name for name in ("meta.json", "decisions.json", "video_meta.json"))
    output = tmp_path / "out.json"
    _write_json(meta, {"subvideos": [
        {"subvideo_id": "video_0001_keep", "source_video": "video_0001", "actual_frame_mapping": [{"original_frame": 0}, {"original_frame": 10}, {"original_frame": 20}]},
        {"subvideo_id": "video_0002_drop", "source_video": "video_0002", "actual_frame_mapping": [{"original_frame": 0}, {"original_frame": 10}, {"original_frame": 20}]},
    ]})
    _write_json(decisions, {"decisions": [
        {"subvideo_id": "video_0001_keep", "status": "approved", "original_labels": {"fracture_between": [0, 1]}, "corrected_labels": {"fracture_between": [1, 2]}},
        {"subvideo_id": "video_0002_drop", "status": "approved", "original_labels": {"fracture_between": [0, 1]}, "corrected_labels": {"fracture_between": None}},
    ]})
    _write_json(video_meta, [
        {"video_id": "video_0001", "has_fracture_canonical": True, "event_time_reliable": True, "event_frame_effective": 15},
        {"video_id": "video_0002", "has_fracture_canonical": True, "event_time_reliable": True, "event_frame_effective": 5},
    ])

    summary = ard.apply_review_decisions(
        meta, decisions, output, strict=True,
        interval_verification_video_meta_path=video_meta,
    )

    assert summary["interval_verification"] == {"retained": 1, "dropped": 1}
    rows = {row["subvideo_id"]: row for row in json.loads(output.read_text())["subvideos"]}
    assert rows["video_0001_keep"]["review_status"] == "approved"
    assert rows["video_0002_drop"]["review_status"] == "dropped"
    assert rows["video_0002_drop"]["interval_verification"]["reason"] == "missing_reviewed_interval"


def test_missing_status_strict_blocks(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(meta, {"subvideos": [{"subvideo_id": "sv1", "type": "t"}]})
    _write_json(dec, {"decisions": [{"subvideo_id": "sv1"}]})

    with pytest.raises(RuntimeError, match="严格模式"):
        ard.apply_review_decisions(meta, dec, out, strict=True)


def test_neg_before_is_auto_approved_without_a_manual_decision(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sv_neg_before",
                    "crop_type": "neg_before",
                    "has_fracture": False,
                    "type": "未断裂",
                },
                {"subvideo_id": "sv_manual", "type": "韧性断裂"},
            ]
        },
    )
    _write_json(dec, {"decisions": [{"subvideo_id": "sv_manual", "status": "approved"}]})

    summary = ard.apply_review_decisions(meta, dec, out, strict=True)

    assert summary["blockers"] == []
    assert summary["status_counts"]["approved"] == 2
    sub = json.loads(out.read_text(encoding="utf-8"))["subvideos"][0]
    assert sub["review_status"] == "approved"
    assert sub["reviewed_at"] is None


def test_missing_status_no_strict_marked_invalid(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(meta, {"subvideos": [{"subvideo_id": "sv1", "type": "t"}]})
    _write_json(dec, {"decisions": [{"subvideo_id": "sv1"}]})

    summary = ard.apply_review_decisions(meta, dec, out, strict=False)
    assert summary["blockers"] == []
    assert summary["status_counts"]["invalid_status(None)"] == 1


def test_invalid_status_strict_blocks(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(meta, {"subvideos": [{"subvideo_id": "sv1", "type": "t"}]})
    _write_json(dec, {"decisions": [{"subvideo_id": "sv1", "status": "bad_status"}]})

    with pytest.raises(RuntimeError, match="严格模式"):
        ard.apply_review_decisions(meta, dec, out, strict=True)


def test_invalid_status_no_strict_passes_and_counts(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(meta, {"subvideos": [{"subvideo_id": "sv1", "type": "t"}]})
    _write_json(dec, {"decisions": [{"subvideo_id": "sv1", "status": "bad_status"}]})

    summary = ard.apply_review_decisions(meta, dec, out, strict=False)
    assert summary["blockers"] == []
    assert summary["status_counts"]["invalid_status(bad_status)"] == 1

    out_data = json.loads(out.read_text())
    assert out_data["subvideos"][0]["review_status"] == "invalid_status(bad_status)"


def test_missing_subvideo_id_in_metadata_raises(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(meta, {"subvideos": [{"type": "t"}]})
    _write_json(dec, {"decisions": []})

    with pytest.raises(ValueError, match="subvideo_id"):
        ard.apply_review_decisions(meta, dec, out, strict=True)


def test_no_strict_allows_unreviewed_and_needs_regenerate(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {"subvideo_id": "sv1", "type": "t"},
                {"subvideo_id": "sv2", "type": "t"},
                {"subvideo_id": "sv3", "type": "t"},
            ]
        },
    )
    _write_json(
        dec,
        {
            "decisions": [
                {"subvideo_id": "sv1", "status": "approved"},
                {"subvideo_id": "sv2", "status": "needs_regenerate"},
            ]
        },
    )

    summary = ard.apply_review_decisions(meta, dec, out, strict=False)
    assert summary["status_counts"]["approved"] == 1
    assert summary["status_counts"]["needs_regenerate"] == 1
    assert summary["status_counts"]["unreviewed"] == 1
    assert summary["blockers"] == []
    assert out.exists()


def test_apply_label_corrections_syncs_type_canonical(tmp_path):
    meta = tmp_path / "meta.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "review_status": "approved",
                    "type": "old_type",
                    "corrected_labels": {"type": "corrected_type"},
                }
            ]
        },
    )

    summary = alc.apply_label_corrections(meta, out)
    assert summary["corrected"] == 1

    out_data = json.loads(out.read_text())
    sub = out_data["subvideos"][0]
    assert sub["type"] == "corrected_type"
    assert sub["type_canonical"] == "corrected_type"


def test_apply_label_corrections_approved_no_corrected_syncs_type_canonical(tmp_path):
    meta = tmp_path / "meta.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "review_status": "approved",
                    "type": "current_type",
                    "corrected_labels": None,
                }
            ]
        },
    )

    summary = alc.apply_label_corrections(meta, out)
    assert summary["corrected"] == 0
    assert summary["skipped"] == 1

    out_data = json.loads(out.read_text())
    sub = out_data["subvideos"][0]
    assert sub["type"] == "current_type"
    assert sub["type_canonical"] == "current_type"


def test_apply_label_corrections_output_only_includes_approved(tmp_path):
    meta = tmp_path / "meta.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "review_decisions": {
                "decisions": [
                    {"subvideo_id": "sv_approved", "status": "approved"},
                    {"subvideo_id": "sv_dropped", "status": "dropped"},
                ]
            },
            "subvideos": [
                {
                    "subvideo_id": "sv_approved",
                    "review_status": "approved",
                    "type": "old_type",
                    "corrected_labels": {"type": "corrected_type"},
                },
                {
                    "subvideo_id": "sv_dropped",
                    "review_status": "dropped",
                    "type": "old_type",
                },
                {
                    "subvideo_id": "sv_approved_no_correction",
                    "review_status": "approved",
                    "type": "current_type",
                },
            ],
        },
    )

    summary = alc.apply_label_corrections(meta, out)
    assert summary["approved_output"] == 2
    assert summary["excluded"] == 1

    out_data = json.loads(out.read_text())
    assert len(out_data["subvideos"]) == 2
    assert out_data["subvideos"][0]["subvideo_id"] == "sv_approved"
    assert out_data["subvideos"][0]["type"] == "corrected_type"
    assert out_data["subvideos"][1]["type"] == "current_type"

    excluded_ids = {e["subvideo_id"] for e in out_data["excluded_subvideos"]}
    assert excluded_ids == {"sv_dropped"}

    assert "review_decisions" in out_data


def test_apply_label_corrections_rejects_non_dropped_excluded(tmp_path):
    meta = tmp_path / "meta.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sv_approved",
                    "review_status": "approved",
                    "type": "old_type",
                    "corrected_labels": {"type": "corrected_type"},
                },
                {
                    "subvideo_id": "sv_unreviewed",
                    "review_status": "unreviewed",
                    "type": "old_type",
                },
                {
                    "subvideo_id": "sv_needs",
                    "review_status": "needs_regenerate",
                    "type": "old_type",
                },
                {
                    "subvideo_id": "sv_bad",
                    "review_status": "bad_status",
                    "type": "old_type",
                },
                {
                    "subvideo_id": "sv_missing",
                    "type": "old_type",
                },
            ]
        },
    )

    with pytest.raises(ValueError, match="excluded_subvideos"):
        alc.apply_label_corrections(meta, out)

    assert not out.exists()


@pytest.mark.parametrize("bad_item", [None, "not-a-dict"])
def test_apply_label_corrections_rejects_non_object_excluded_subvideos(
    tmp_path, bad_item
):
    """_validate_excluded_subvideos 必须拒绝非对象项，避免非法记录被静默忽略。"""
    with pytest.raises(ValueError, match="非对象项"):
        alc._validate_excluded_subvideos([bad_item])


@pytest.mark.parametrize("bad_subvideo_id", [None, "", "<unknown>"])
def test_apply_label_corrections_rejects_invalid_subvideo_id_in_excluded_subvideos(
    tmp_path, bad_subvideo_id
):
    """非 approved 子视频的 subvideo_id 无效时，应拒绝写出 label_reviewed 文件。"""
    meta = tmp_path / "meta.json"
    out = tmp_path / "out.json"

    _write_json(
        meta,
        {
            "subvideos": [
                {
                    "subvideo_id": "sv_approved",
                    "review_status": "approved",
                    "type": "old_type",
                    "corrected_labels": {"type": "corrected_type"},
                },
                {
                    "subvideo_id": bad_subvideo_id,
                    "review_status": "dropped",
                    "type": "old_type",
                },
            ]
        },
    )

    with pytest.raises(ValueError, match="subvideo_id"):
        alc.apply_label_corrections(meta, out)

    assert not out.exists()
