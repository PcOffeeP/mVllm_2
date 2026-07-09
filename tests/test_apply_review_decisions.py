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
