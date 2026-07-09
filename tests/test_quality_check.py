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


def _reviewed_sub(has_fracture: bool, source_video: str = "video_0001") -> dict:
    return {
        "subvideo_id": f"{source_video}_sub",
        "source_video": source_video,
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
        {
            "source_video": "video_val",
            "has_fracture": True,
            "has_fracture_canonical": True,
            "selected_splits": ["fold_0_val"],
        },
        {
            "source_video": "video_unknown",
            "has_fracture_canonical": None,
            "selected_splits": ["fold_0_train"],
        },
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


def test_quality_check_rejects_reviewed_train_val_source_leakage(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(True, "video_0001"),
                    "selected_splits": ["fold_0_train"],
                },
                {
                    **_reviewed_sub(False, "video_0001"),
                    "subvideo_id": "video_0001_val_sub",
                    "selected_splits": ["fold_0_val"],
                },
                _reviewed_sub(False, "video_0002"),
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
        e["check"] == "cross_split_leakage"
        and e["detail"] == "video_source_overlap_between_fold_0_train_and_fold_0_val"
        and e["overlap"] == ["video_0001"]
        for e in errors
    )


def test_quality_check_rejects_reviewed_train_test_source_leakage(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    (merged / "test_inputs.json").write_text(
        json.dumps([{"id": "test_0001", "video_id": "video_0001"}]),
        encoding="utf-8",
    )
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [_reviewed_sub(True, "video_0001"), _reviewed_sub(False, "video_0002")]},
    )
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert any(
        e["check"] == "cross_split_leakage"
        and e["detail"] == "video_source_overlap_between_fold_0_train_and_test"
        and e["overlap"] == ["video_0001"]
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


def _make_sample(sid: str, content: str, prompt_version: str = "v1.0.0") -> dict:
    return {
        "id": sid,
        "videos": [f"data/03_subvideos/{sid}.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": content},
        ],
        "prompt_version": prompt_version,
    }


def _write_train_file(merged: Path, samples: list[dict]) -> None:
    merged.mkdir(parents=True, exist_ok=True)
    (merged / "test_inputs.json").write_text("[]", encoding="utf-8")
    (merged / "fold_0_train.json").write_text(
        json.dumps(samples, ensure_ascii=False), encoding="utf-8"
    )


def test_assistant_target_missing_evidence_section(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_bad",
                    "review_status": "approved",
                }
            ]
        },
    )
    bad = _make_sample(
        "sub_bad",
        '结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    _write_train_file(merged, [bad])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "assistant_target" and e["detail"] == "missing_evidence_section"
        for e in errors
    )


def test_assistant_target_rejects_confidence(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_bad",
                    "review_status": "approved",
                }
            ]
        },
    )
    bad = _make_sample(
        "sub_bad",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null,"confidence":0.9}',
    )
    _write_train_file(merged, [bad])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "assistant_target" and e["detail"] == "confidence_field_present"
        for e in errors
    )


def test_assistant_target_result_schema_mismatch(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_bad",
                    "review_status": "approved",
                }
            ]
        },
    )
    bad = _make_sample(
        "sub_bad",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂"}',
    )
    _write_train_file(merged, [bad])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "assistant_target" and e["detail"] == "result_schema_mismatch"
        for e in errors
    )


def test_prompt_version_mismatch(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_bad",
                    "review_status": "approved",
                }
            ]
        },
    )
    bad = _make_sample(
        "sub_bad",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
        prompt_version="v0.0.0",
    )
    _write_train_file(merged, [bad])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "prompt_version" and e["detail"] == "prompt_version_mismatch"
        for e in errors
    )


def test_review_status_not_approved(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_bad",
                    "review_status": "dropped",
                }
            ]
        },
    )
    sample = _make_sample(
        "sub_bad",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "review_status" and e["detail"] == "subvideo_not_approved"
        for e in errors
    )


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
        {
            "source_video": "video_val",
            "has_fracture": False,
            "has_fracture_canonical": False,
            "selected_splits": ["fold_0_val"],
        },
        {
            "source_video": "video_unknown",
            "has_fracture_canonical": None,
            "selected_splits": ["fold_0_train"],
        },
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


def test_quality_check_fails_when_prompt_library_missing(tmp_path, monkeypatch):
    """Patch: 模板库缺失时应显式报错。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
        prompt_library_path=tmp_path / "nonexistent" / "prompt_library.yaml",
    )

    assert any(
        e["check"] == "prompt_library"
        and e["detail"] == "prompt_library_missing_or_unreadable"
        for e in errors
    )


def test_quality_check_fails_when_prompt_library_missing_version(tmp_path, monkeypatch):
    """Patch: 模板库缺少 version 字段时应显式报错。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    bad_library = tmp_path / "bad_prompt_library.yaml"
    bad_library.write_text("system_prompt: test\n", encoding="utf-8")

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
        prompt_library_path=bad_library,
    )

    assert any(
        e["check"] == "prompt_library"
        and e["detail"] == "prompt_library_missing_version"
        for e in errors
    )
