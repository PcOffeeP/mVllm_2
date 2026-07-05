from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

from pipeline.scripts import quality_check


def _write_meta(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_merged_dir(tmp_path: Path) -> Path:
    merged = tmp_path / "data" / "06_merged"
    merged.mkdir(parents=True)
    (merged / "test_inputs.json").write_text("[]", encoding="utf-8")
    return merged


def _make_reviewed_meta(tmp_path: Path) -> Path:
    meta = tmp_path / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    return meta


def _reviewed_sub(has_fracture: bool) -> dict:
    return {
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "selected_splits": ["fold_0_train"],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }


def test_quality_check_defaults_to_label_reviewed_meta():
    default = inspect.signature(
        quality_check.run_quality_check
    ).parameters["subvideos_meta_path"].default
    assert str(default).endswith("subvideos_meta.label_reviewed.json")


def test_quality_check_fails_when_reviewed_meta_missing(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=tmp_path / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json",
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio" and e["detail"] == "reviewed_metadata_missing"
        for e in errors
    )


def test_reviewed_ratio_fails_on_all_positive(tmp_path, monkeypatch):
    """Patch 4: 人工审核后全为正样本应报 error。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(True)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio"
        and e["detail"] == "missing_positive_or_negative_samples"
        for e in errors
    )


def test_reviewed_ratio_fails_on_all_negative(tmp_path, monkeypatch):
    """Patch 4: 人工审核后全为负样本应报 error。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(False), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio"
        and e["detail"] == "missing_positive_or_negative_samples"
        for e in errors
    )


def test_reviewed_ratio_fails_on_high_positive_ratio(tmp_path, monkeypatch):
    """Patch 4: 人工审核后正负比 3:1 应报 error。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [
            _reviewed_sub(True),
            _reviewed_sub(True),
            _reviewed_sub(True),
            _reviewed_sub(False),
        ]},
    )
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio"
        and e["detail"] == "manual_review_ratio_out_of_range"
        for e in errors
    )


def test_quality_check_cli_returns_nonzero_on_bad_ratio(tmp_path, monkeypatch):
    """Patch 4: ratio 异常时 CLI 返回非 0。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(True)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    monkeypatch.setattr(sys, "argv", [
        "quality_check.py",
        "--merged-dir", str(merged),
        "--subvideos-meta", str(meta),
        "--report", str(tmp_path / "report.json"),
        "--project-root", str(tmp_path),
    ])
    rc = quality_check.main()
    assert rc != 0


def test_reviewed_ratio_is_none_when_no_negatives(tmp_path, monkeypatch):
    """阻断项：neg==0 时 ratio 应为 None，不能是 Infinity。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(True)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    reviewed_ratio = summary["reviewed_ratio"]
    assert reviewed_ratio is not None
    assert reviewed_ratio["ratio"] is None
    # 验证生成的 JSON 可被标准 json 解析，不含 Infinity。
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["reviewed_ratio"]["ratio"] is None
    assert any(
        e["check"] == "reviewed_ratio"
        and e["detail"] == "missing_positive_or_negative_samples"
        for e in errors
    )


def test_reviewed_ratio_is_none_when_no_train_samples(tmp_path, monkeypatch):
    """阻断项：total==0 时 ratio 应为 None，不能是 Infinity。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [
        {"has_fracture": True, "has_fracture_canonical": True, "selected_splits": ["fold_0_val"]},
        {"has_fracture_canonical": None, "selected_splits": ["fold_0_train"]},
    ]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    reviewed_ratio = summary["reviewed_ratio"]
    assert reviewed_ratio is not None
    assert reviewed_ratio["positive"] == 0
    assert reviewed_ratio["negative"] == 0
    assert reviewed_ratio["total"] == 0
    assert reviewed_ratio["ratio"] is None
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["reviewed_ratio"]["ratio"] is None
    assert any(
        e["check"] == "reviewed_ratio" and e["detail"] == "no_reviewed_samples"
        for e in errors
    )


def test_quality_check_rejects_unreviewed_meta(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = tmp_path / "data" / "07_metadata" / "subvideos_meta.json"
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio" and e["detail"] == "unreviewed_metadata_rejected"
        for e in errors
    )


def test_quality_check_allows_unreviewed_meta_when_opt_in(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = tmp_path / "data" / "07_metadata" / "subvideos_meta.json"
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
        allow_unreviewed_meta=True,
    )

    assert not any(
        e["check"] == "reviewed_ratio" and e["detail"] == "unreviewed_metadata_rejected"
        for e in errors
    )


def test_quality_check_fails_on_corrupt_reviewed_meta(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    meta.write_text('{"subvideos": [}', encoding="utf-8")
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio" and e["detail"] == "reviewed_metadata_invalid"
        for e in errors
    )
    assert (tmp_path / "report.json").exists()


def test_quality_check_fails_on_non_utf8_reviewed_meta(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    meta.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "reviewed_ratio" and e["detail"] == "reviewed_metadata_invalid"
        for e in errors
    )
    assert (tmp_path / "report.json").exists()


def test_quality_check_single_error_for_corrupt_meta(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    meta.write_text('{"subvideos": [}', encoding="utf-8")
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    reviewed_metadata_errors = [
        e for e in errors
        if e["check"] == "reviewed_ratio" and e["detail"] == "reviewed_metadata_invalid"
    ]
    assert len(reviewed_metadata_errors) == 1


def test_quality_check_rejects_test_sharegpt_file(tmp_path, monkeypatch):
    """Patch: merged 目录下不应存在 test.json。"""
    merged = _make_merged_dir(tmp_path)
    (merged / "test.json").write_text("[]", encoding="utf-8")
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "test_sharegpt" and e["detail"] == "test_sharegpt_file_exists"
        for e in errors
    )


def test_quality_check_rejects_mock_processor_fingerprint(tmp_path, monkeypatch):
    """Patch: label_reviewed 元数据中的 processor_fingerprint 不能含 mock。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(True),
                    "processor_fingerprint": "mock:processor",
                },
                _reviewed_sub(False),
            ]
        },
    )
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "processor_fingerprint"
        and "mock" in e["detail"].lower()
        for e in errors
    )


def test_reviewed_ratio_skips_unknown_and_val_only_splits(tmp_path, monkeypatch):
    """警告项：只统计含 train split 的样本，并排除 has_fracture_canonical 为 None。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [
        _reviewed_sub(True),
        {"has_fracture": False, "has_fracture_canonical": False, "selected_splits": ["fold_0_val"]},
        {"has_fracture_canonical": None, "selected_splits": ["fold_0_train"]},
    ]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    reviewed_ratio = summary["reviewed_ratio"]
    assert reviewed_ratio is not None
    assert reviewed_ratio["positive"] == 1
    assert reviewed_ratio["negative"] == 0
    assert reviewed_ratio["total"] == 1
    assert reviewed_ratio["ratio"] is None
    assert any(
        e["check"] == "reviewed_ratio"
        and e["detail"] == "missing_positive_or_negative_samples"
        for e in errors
    )

