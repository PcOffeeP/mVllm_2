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


def test_missing_status_strict_blocks(tmp_path):
    meta = tmp_path / "meta.json"
    dec = tmp_path / "dec.json"
    out = tmp_path / "out.json"

    _write_json(meta, {"subvideos": [{"subvideo_id": "sv1", "type": "t"}]})
    _write_json(dec, {"decisions": [{"subvideo_id": "sv1"}]})

    with pytest.raises(RuntimeError, match="严格模式"):
        ard.apply_review_decisions(meta, dec, out, strict=True)


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
