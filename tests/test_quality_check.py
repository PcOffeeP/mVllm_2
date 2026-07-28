from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

from pipeline.scripts.archive import quality_check


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


def test_pure_sharegpt_sample_contract_rejects_metadata_and_explanation(tmp_path):
    """新训练 JSON 不允许 metadata，也不允许旧的解释/结果前缀。"""
    merged = _make_merged_dir(tmp_path)
    sample = {
        "videos": ["data/03_subvideos/sub.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'},
        ],
        "metadata": {"source_video": "video_0001"},
    }
    _write_train_file(merged, [sample])
    errors: list[dict] = []
    quality_check._validate_assistant_targets(merged, errors, [])
    assert any(e["check"] == "sample_schema" for e in errors)
    assert any(e.get("detail") == "contains_removed_explanation_section" for e in errors)


def test_pure_sharegpt_sample_contract_accepts_json_only(tmp_path):
    """新契约仅允许 videos/messages 与严格四字段 JSON target。"""
    merged = _make_merged_dir(tmp_path)
    sample = {
        "videos": ["data/03_subvideos/sub.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": '{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'},
        ],
    }
    _write_train_file(merged, [sample])
    errors: list[dict] = []
    quality_check._validate_assistant_targets(merged, errors, [])
    assert errors == []


def test_quality_check_accepts_v1_video_anomaly_contract(tmp_path):
    """V1 协议规定 null 判定必须输出“视频异常”，其余字段为 null。"""
    merged = _make_merged_dir(tmp_path)
    sample = {
        "videos": ["data/03_subvideos/sub.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {
                "role": "assistant",
                "content": '{"has_fracture":null,"fracture_between":null,"type":"视频异常","location":null}',
            },
        ],
    }
    _write_train_file(merged, [sample])
    errors: list[dict] = []
    warnings: list[dict] = []

    quality_check._validate_assistant_targets(merged, errors, warnings)

    assert errors == []
    assert warnings == []


def test_quality_check_ignores_non_training_json_artifacts(tmp_path):
    """评测输入和答案不是 ShareGPT 训练样本，不应套用训练 schema。"""
    merged = _make_merged_dir(tmp_path)
    (merged / "test_subvideo_inputs.json").write_text(
        json.dumps([{"id": "eval-1", "video_path": "data/03_subvideos/eval.mp4"}]),
        encoding="utf-8",
    )
    (merged / "test_subvideo_ground_truth.json").write_text(
        json.dumps([{"id": "eval-1", "has_fracture": False}]),
        encoding="utf-8",
    )
    errors: list[dict] = []

    quality_check._validate_assistant_targets(merged, errors, [])

    assert errors == []


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


def test_quality_check_accepts_label_reviewed_derived_meta(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = (
        tmp_path
        / "data"
        / "07_metadata"
        / "subvideos_meta.filtered_neg_before.label_reviewed.json"
    )
    _write_meta(meta, {"subvideos": [_reviewed_sub(True), _reviewed_sub(False)]})
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )

    assert not any(
        e["check"] == "reviewed_ratio"
        and e["detail"] == "unreviewed_metadata_rejected"
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


def test_quality_check_rejects_invalid_excluded_subvideo_id(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [_reviewed_sub(True), _reviewed_sub(False)],
            "excluded_subvideos": [
                {"subvideo_id": "<unknown>", "review_status": "dropped"}
            ],
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
        e["check"] == "excluded_subvideos"
        and e["detail"] == "invalid_subvideo_id"
        and e["subvideo_id"] == "<unknown>"
        for e in errors
    )


def test_quality_check_rejects_excluded_subvideo_without_dropped_status(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [_reviewed_sub(True), _reviewed_sub(False)],
            "excluded_subvideos": [
                {"subvideo_id": "video_0001_drop", "review_status": "approved"}
            ],
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
        e["check"] == "excluded_subvideos"
        and e["detail"] == "review_status_not_dropped"
        and e["subvideo_id"] == "video_0001_drop"
        for e in errors
    )


def test_quality_check_rejects_excluded_subvideos_not_a_list(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [_reviewed_sub(True), _reviewed_sub(False)],
            "excluded_subvideos": {"subvideo_id": "video_0001_drop"},
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
        e["check"] == "excluded_subvideos"
        and e["detail"] == "excluded_subvideos_not_a_list"
        for e in errors
    )


def test_quality_check_rejects_excluded_subvideo_not_an_object(tmp_path, monkeypatch):
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [_reviewed_sub(True), _reviewed_sub(False)],
            "excluded_subvideos": ["video_0001_drop"],
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
        e["check"] == "excluded_subvideos"
        and e["detail"] == "excluded_subvideo_not_an_object"
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
    (merged / "fold_0_train.json").write_text(
        json.dumps([{"metadata": {"source_video": "video_0001"}}]),
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


def _make_sample(sid: str, content: str, prompt_version: str = "v2.1.0") -> dict:
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


def test_review_status_approved_authoritative_with_dropped_metadata_fails(tmp_path, monkeypatch):
    """权威 approved，但 metadata.review_status=dropped，质量门失败。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_mismatch",
                    "review_status": "approved",
                }
            ]
        },
    )
    sample = _make_sample(
        "sub_mismatch",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    sample["metadata"] = {"subvideo_id": "sub_mismatch", "review_status": "dropped"}
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "review_status"
        and e["detail"] == "metadata_review_status_mismatch"
        for e in errors
    )
    assert any(
        e["authoritative"] == "approved" and e["metadata"] == "dropped"
        for e in errors
        if e.get("check") == "review_status"
        and e.get("detail") == "metadata_review_status_mismatch"
    )


def test_review_status_approved_authoritative_with_missing_metadata_passes(tmp_path, monkeypatch):
    """权威 approved，metadata 不含 review_status 时允许通过（不视为不一致）。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_missing",
                    "review_status": "approved",
                }
            ]
        },
    )
    sample = _make_sample(
        "sub_missing",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    sample["metadata"] = {"subvideo_id": "sub_missing"}
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert not any(e["check"] == "review_status" for e in errors)


def test_review_status_approved_authoritative_with_approved_metadata_passes(tmp_path, monkeypatch):
    """权威 approved，metadata.review_status=approved，质量门通过。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_ok",
                    "review_status": "approved",
                }
            ]
        },
    )
    sample = _make_sample(
        "sub_ok",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    sample["metadata"] = {"subvideo_id": "sub_ok", "review_status": "approved"}
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert not any(e["check"] == "review_status" for e in errors)


def test_quality_check_reads_prompt_version_from_sample_metadata(tmp_path, monkeypatch):
    """优先从训练样本 metadata 读取 prompt_version。"""
    merged = _make_merged_dir(tmp_path)
    sample = _make_sample(
        "sub_ok",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
        prompt_version="v0.0.0",  # 顶层错误，应被忽略
    )
    sample["metadata"] = {
        "subvideo_id": "sub_ok",
        "source_video": "video_0001",
        "video_path": "data/03_subvideos/sub_ok.mp4",
        "prompt_version": "v2.1.0",
        "review_status": "approved",
        "reviewed_at": "2026-07-09T12:00:00+00:00",
        "fracture_between": None,
        "location_canonical": None,
        "type": "未断裂",
        "has_fracture_canonical": False,
    }
    _write_train_file(merged, [sample])
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [
            {**_reviewed_sub(False), "subvideo_id": "sub_ok", "review_status": "approved"}
        ]},
    )
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert not any(e["check"] == "prompt_version" for e in errors)


def test_quality_check_rejects_metadata_review_status_overriding_authoritative(
    tmp_path, monkeypatch
):
    """metadata 中的 review_status 不能覆盖 label_reviewed 权威状态。"""
    merged = _make_merged_dir(tmp_path)
    sample = {
        "id": "sub_ok",
        "videos": ["data/03_subvideos/sub_ok.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'},
        ],
        "prompt_version": "v2.1.0",
        "metadata": {
            "subvideo_id": "sub_ok",
            "source_video": "video_0001",
            "video_path": "data/03_subvideos/sub_ok.mp4",
            "prompt_version": "v2.1.0",
            "review_status": "approved",
            "reviewed_at": "2026-07-09T12:00:00+00:00",
            "fracture_between": None,
            "location_canonical": None,
            "type": "未断裂",
            "has_fracture_canonical": False,
        },
    }
    _write_train_file(merged, [sample])
    meta = _make_reviewed_meta(tmp_path)
    # reviewed_meta 中记录为 dropped，metadata 中 approved，应报错且 mismatch 为 error
    _write_meta(
        meta,
        {"subvideos": [
            {**_reviewed_sub(False), "subvideo_id": "sub_ok", "review_status": "dropped"}
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
        e["check"] == "review_status" and e["detail"] == "subvideo_not_approved"
        for e in errors
    )
    assert any(
        e["check"] == "review_status"
        and e["detail"] == "metadata_review_status_mismatch"
        for e in errors
    )


def test_quality_check_fallback_to_reviewed_meta_for_review_status(tmp_path, monkeypatch):
    """当样本没有 metadata 时，仍能从 reviewed_meta 回退读取 review_status。"""
    merged = _make_merged_dir(tmp_path)
    sample = _make_sample(
        "sub_ok",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    # 没有 metadata，依赖 reviewed_meta 的 review_status
    _write_train_file(merged, [sample])
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [
            {**_reviewed_sub(False), "subvideo_id": "sub_ok", "review_status": "approved"}
        ]},
    )
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert not any(e["check"] == "review_status" for e in errors)


def test_quality_check_fallback_to_reviewed_meta_when_metadata_missing_review_status(
    tmp_path, monkeypatch
):
    """metadata 存在但缺少 review_status 时，应回退到 reviewed_meta。"""
    merged = _make_merged_dir(tmp_path)
    sample = _make_sample(
        "sub_ok",
        '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}',
    )
    sample["metadata"] = {
        "subvideo_id": "sub_ok",
        "source_video": "video_0001",
        "video_path": "data/03_subvideos/sub_ok.mp4",
        "prompt_version": "v2.1.0",
        "reviewed_at": "2026-07-09T12:00:00+00:00",
        "fracture_between": None,
        "location_canonical": None,
        "type": "未断裂",
        "has_fracture_canonical": False,
    }
    _write_train_file(merged, [sample])
    (tmp_path / "data" / "03_subvideos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "03_subvideos" / "sub_ok.mp4").write_bytes(b"")
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [
            {**_reviewed_sub(False), "subvideo_id": "sub_ok", "review_status": "approved"}
        ]},
    )
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert not any(e["check"] == "review_status" for e in errors)


def test_quality_check_uses_actual_frame_mapping_from_metadata_for_boundary_check(
    tmp_path, monkeypatch
):
    """fracture_between 边界检查应优先使用 metadata.actual_frame_mapping。"""
    merged = _make_merged_dir(tmp_path)
    (tmp_path / "data" / "03_subvideos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "03_subvideos" / "sub_pos.mp4").write_bytes(b"")
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [
            {**_reviewed_sub(True), "subvideo_id": "sub_pos", "review_status": "approved"}
        ]},
    )
    sample = _make_sample(
        "sub_pos",
        '判断依据：x\n结果：{"has_fracture":true,"fracture_between":[2,3],"type":"韧性断裂","location":"inside_gauge"}',
    )
    sample["metadata"] = {
        "subvideo_id": "sub_pos",
        "source_video": "video_0001",
        "video_path": "data/03_subvideos/sub_pos.mp4",
        "prompt_version": "v2.1.0",
        "review_status": "approved",
        "reviewed_at": "2026-07-09T12:00:00+00:00",
        "fracture_between": [2, 3],
        "location_canonical": "inside_gauge",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
            {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
            {"input_index": 2, "original_frame": 20, "timestamp": 2.0},
            {"input_index": 3, "original_frame": 30, "timestamp": 3.0},
        ],
    }
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert not any(e["check"] == "fracture_between" for e in errors)


def test_quality_check_detects_out_of_bounds_fracture_between_from_metadata_mapping(
    tmp_path, monkeypatch
):
    """metadata.actual_frame_mapping 长度不足时，越界 fracture_between 应被检测。"""
    merged = _make_merged_dir(tmp_path)
    (tmp_path / "data" / "03_subvideos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "03_subvideos" / "sub_bad.mp4").write_bytes(b"")
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {"subvideos": [
            {**_reviewed_sub(True), "subvideo_id": "sub_bad", "review_status": "approved"}
        ]},
    )
    sample = _make_sample(
        "sub_bad",
        '判断依据：x\n结果：{"has_fracture":true,"fracture_between":[4,5],"type":"韧性断裂","location":"inside_gauge"}',
    )
    sample["metadata"] = {
        "subvideo_id": "sub_bad",
        "source_video": "video_0001",
        "video_path": "data/03_subvideos/sub_bad.mp4",
        "prompt_version": "v2.1.0",
        "review_status": "approved",
        "reviewed_at": "2026-07-09T12:00:00+00:00",
        "fracture_between": [4, 5],
        "location_canonical": "inside_gauge",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
            {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
            {"input_index": 2, "original_frame": 20, "timestamp": 2.0},
            {"input_index": 3, "original_frame": 30, "timestamp": 3.0},
        ],
    }
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "fracture_between" and e["detail"] == "out_of_bounds_or_not_adjacent"
        for e in errors
    )


def test_review_status_metadata_approved_but_authoritative_dropped(tmp_path, monkeypatch):
    """训练样本 metadata 自称 approved，但 label_reviewed 中是 dropped，应报错。"""
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
    sample = {
        "videos": ["data/03_subvideos/sub_bad.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'},
        ],
        "metadata": {
            "subvideo_id": "sub_bad",
            "review_status": "approved",
        },
    }
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
    assert any(
        e["check"] == "review_status"
        and e["detail"] == "metadata_review_status_mismatch"
        for e in errors
    )


def test_review_status_missing_in_authoritative_map(tmp_path, monkeypatch):
    """权威映射中不存在该子视频时，质量门应报错。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(meta, {"subvideos": [_reviewed_sub(False)]})
    sample = {
        "videos": ["data/03_subvideos/unknown_sub.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'},
        ],
        "metadata": {
            "subvideo_id": "unknown_sub",
            "review_status": "approved",
        },
    }
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    assert any(
        e["check"] == "review_status"
        and e["detail"] == "subvideo_not_found_in_reviewed_meta"
        for e in errors
    )


def test_sample_id_prefers_metadata_subvideo_id(tmp_path, monkeypatch):
    """训练样本没有顶层 id 时，质量门错误信息中的 id 来自 metadata.subvideo_id。"""
    merged = _make_merged_dir(tmp_path)
    meta = _make_reviewed_meta(tmp_path)
    _write_meta(
        meta,
        {
            "subvideos": [
                {
                    **_reviewed_sub(False),
                    "subvideo_id": "sub_meta",
                    "review_status": "dropped",
                }
            ]
        },
    )
    sample = {
        "videos": ["data/03_subvideos/sub_meta.mp4"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "<video>"},
            {"role": "assistant", "content": '判断依据：x\n结果：{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'},
        ],
        "metadata": {
            "subvideo_id": "sub_meta",
        },
    }
    _write_train_file(merged, [sample])
    monkeypatch.setattr(quality_check, "_validate_train_ratios", lambda *args: None)

    errors, _warnings, _summary = quality_check.run_quality_check(
        merged_dir=merged,
        subvideos_meta_path=meta,
        report_path=tmp_path / "report.json",
        project_root=tmp_path,
    )
    review_errors = [e for e in errors if e["check"] == "review_status"]
    assert review_errors
    assert all(e.get("id") == "sub_meta" for e in review_errors)
