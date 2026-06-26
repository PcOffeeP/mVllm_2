"""Tests for ``ui/agent_app`` helper functions.

These tests verify the importable helper layer without requiring Streamlit.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

# The module must be importable without Streamlit.
from ui.agent_app import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    TaskItem,
    _event_log_html,
    _export_csv,
    _export_json,
    _export_jsonl,
    _find_video_files,
    _format_event_summary,
    _result_card_html,
    _result_to_row,
    _round_badge_html,
    _status_badge_html,
)

# =========================================================================
# Helpers
# =========================================================================


def _make_runner_result(
    ok: bool = True,
    status: str = "fracture",
    video_id: str = "video_0001",
    time_range: list[float] | None = None,
    fracture_type: str | None = None,
    location: str | None = None,
    confidence: float | None = None,
    unrecognized_reason: str | None = None,
    rounds: int = 3,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a runner result dict shaped like ``RunnerResult.model_dump()``."""
    if ok:
        inner: dict[str, Any] = {"video_id": video_id, "status": status}
        if time_range is not None:
            inner["time_range"] = time_range
        if fracture_type is not None:
            inner["fracture_type"] = fracture_type
        if location is not None:
            inner["location"] = location
        if confidence is not None:
            inner["confidence"] = confidence
        if unrecognized_reason is not None:
            inner["unrecognized_reason"] = unrecognized_reason
        return {"ok": True, "result": inner, "rounds": rounds}
    return {
        "ok": False,
        "result": None,
        "error": error or {"stage": "internal", "code": "TestError", "message": "test failure"},
        "rounds": rounds,
    }


# =========================================================================
# 1. File discovery (10 tests)
# =========================================================================


class TestFindVideoFiles:
    """Cover ``_find_video_files``."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty dir returns empty list."""
        d = tmp_path / "empty"
        d.mkdir()
        assert _find_video_files(d) == []

    def test_nonexistent_directory(self) -> None:
        """Non-existent dir returns empty list."""
        assert _find_video_files("/nonexistent/path/xyz123") == []

    def test_finds_mp4(self, tmp_path: Path) -> None:
        """Finds .mp4 files."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "test.mp4").write_text("dummy")
        result = _find_video_files(d)
        assert len(result) == 1
        assert result[0].name == "test.mp4"

    def test_finds_avi(self, tmp_path: Path) -> None:
        """Finds .avi files."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "clip.avi").write_text("dummy")
        assert len(_find_video_files(d)) == 1

    def test_finds_mov(self, tmp_path: Path) -> None:
        """Finds .mov files."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "movie.mov").write_text("dummy")
        assert len(_find_video_files(d)) == 1

    def test_finds_mkv(self, tmp_path: Path) -> None:
        """Finds .mkv files."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "file.mkv").write_text("dummy")
        assert len(_find_video_files(d)) == 1

    def test_finds_webm(self, tmp_path: Path) -> None:
        """Finds .webm files."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "clip.webm").write_text("dummy")
        assert len(_find_video_files(d)) == 1

    def test_case_insensitive_extension(self, tmp_path: Path) -> None:
        """Finds .MP4 and .Mp4."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "upper.MP4").write_text("dummy")
        (d / "mixed.Mp4").write_text("dummy")
        assert len(_find_video_files(d)) == 2

    def test_ignores_non_video(self, tmp_path: Path) -> None:
        """Only video extensions are returned."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "notes.txt").write_text("text")
        (d / "data.csv").write_text("csv")
        (d / "video.mp4").write_text("dummy")
        result = _find_video_files(d)
        assert len(result) == 1
        assert result[0].suffix == ".mp4"

    def test_sorted_order(self, tmp_path: Path) -> None:
        """Returned list is sorted alphabetically."""
        d = tmp_path / "vids"
        d.mkdir()
        (d / "z.mp4").write_text("dummy")
        (d / "a.mp4").write_text("dummy")
        (d / "m.mp4").write_text("dummy")
        names = [p.name for p in _find_video_files(d)]
        assert names == ["a.mp4", "m.mp4", "z.mp4"]


# =========================================================================
# 2. Result row normalization (10 tests)
# =========================================================================


class TestResultToRow:
    """Cover ``_result_to_row``."""

    def test_fracture_full(self) -> None:
        """Fracture result with all fields."""
        r = _make_runner_result(
            status="fracture",
            time_range=[1.2, 2.0],
            fracture_type="脆性断裂",
            location="inside_gauge",
            confidence=0.92,
        )
        row = _result_to_row(r)
        assert row["video_id"] == "video_0001"
        assert row["status"] == "fracture"
        assert row["has_fracture"] is True
        assert row["time_range"] == [1.2, 2.0]
        assert row["fracture_type"] == "脆性断裂"
        assert row["location"] == "inside_gauge"
        assert row["confidence"] == 0.92
        assert row["ok"] is True

    def test_no_fracture(self) -> None:
        """No_fracture status."""
        r = _make_runner_result(status="no_fracture", confidence=0.87)
        row = _result_to_row(r)
        assert row["status"] == "no_fracture"
        assert row["has_fracture"] is False
        assert row["confidence"] == 0.87

    def test_unrecognized(self) -> None:
        """Unrecognized status with reason."""
        r = _make_runner_result(
            status="unrecognized",
            unrecognized_reason="insufficient_confidence",
        )
        row = _result_to_row(r)
        assert row["status"] == "unrecognized"
        assert row["has_fracture"] is False
        assert row["unrecognized_reason"] == "insufficient_confidence"

    def test_failed_result(self) -> None:
        """Failed result with error envelope."""
        r = _make_runner_result(
            ok=False,
            error={"stage": "inference_transport", "code": "ConnectionError", "message": "timeout"},
        )
        row = _result_to_row(r)
        assert row["ok"] is False
        assert row["error_code"] == "ConnectionError"
        assert row["error_message"] == "timeout"

    def test_failed_result_no_error(self) -> None:
        """Failed result with empty error dict."""
        r = {"ok": False, "result": None, "rounds": 0, "error": {}}
        row = _result_to_row(r)
        assert row["ok"] is False
        assert row["error_code"] == ""
        assert row["error_message"] == ""

    def test_rounds_preserved(self) -> None:
        """Rounds count is preserved."""
        r = _make_runner_result(rounds=5)
        row = _result_to_row(r)
        assert row["rounds"] == 5

    def test_empty_input(self) -> None:
        """Empty dict produces row with defaults."""
        row = _result_to_row({})
        assert row["video_id"] == ""
        assert row["confidence"] == 0.0
        assert row["rounds"] == 0
        assert row["ok"] is True

    def test_missing_inner_result(self) -> None:
        """Missing result key produces defaults."""
        r = {"ok": True, "rounds": 2}
        row = _result_to_row(r)
        assert row["video_id"] == ""
        assert row["status"] == ""

    def test_none_confidence(self) -> None:
        """None confidence maps to 0.0."""
        r = _make_runner_result(status="no_fracture", confidence=None)
        row = _result_to_row(r)
        assert row["confidence"] == 0.0

    def test_empty_video_id(self) -> None:
        """Empty video_id produces empty string."""
        r = _make_runner_result(status="fracture", video_id="")
        row = _result_to_row(r)
        assert row["video_id"] == ""


# =========================================================================
# 3. Event summary (8 tests)
# =========================================================================


class TestFormatEventSummary:
    """Cover ``_format_event_summary``."""

    def test_video_started(self) -> None:
        s = _format_event_summary({"event_type": "video_started", "video_id": "v001"})
        assert "v001" in s

    def test_round_started(self) -> None:
        s = _format_event_summary({"event_type": "round_started", "round": 2, "display_round": 3})
        assert "第 3 轮" in s

    def test_round_started_fallback(self) -> None:
        """Uses round+1 when display_round is absent."""
        s = _format_event_summary({"event_type": "round_started", "round": 2})
        assert "第 3 轮" in s

    def test_llm_tool_call(self) -> None:
        s = _format_event_summary({"event_type": "llm_tool_call", "tool_name": "sample_and_infer"})
        assert "sample_and_infer" in s

    def test_sample_and_infer_finished(self) -> None:
        s = _format_event_summary({"event_type": "sample_and_infer_finished"})
        assert "模型推理完成" in s

    def test_state_updated(self) -> None:
        s = _format_event_summary({
            "event_type": "state_updated",
            "previous_state": "idle",
            "state": "running",
        })
        assert "idle" in s
        assert "running" in s
        assert "→" in s

    def test_video_finished(self) -> None:
        s = _format_event_summary({"event_type": "video_finished"})
        assert "完成" in s

    def test_video_failed(self) -> None:
        s = _format_event_summary({"event_type": "video_failed", "stage": "inference"})
        assert "失败" in s
        assert "inference" in s

    def test_unknown_event_type(self) -> None:
        s = _format_event_summary({"event_type": "custom_event"})
        assert s == "custom_event"

    def test_missing_event_type(self) -> None:
        s = _format_event_summary({})
        assert s == "unknown"


# =========================================================================
# 4. Export serialization (10 tests)
# =========================================================================


class TestExportJsonl:
    """Cover ``_export_jsonl``."""

    def test_single(self) -> None:
        r = _make_runner_result(video_id="v1")
        data = _export_jsonl([r])
        lines = data.decode("utf-8").strip().split("\n")
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["ok"] is True

    def test_multiple(self) -> None:
        results = [_make_runner_result(video_id="v1"), _make_runner_result(video_id="v2")]
        data = _export_jsonl(results)
        lines = data.decode("utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["result"]["video_id"] == "v1"
        assert json.loads(lines[1])["result"]["video_id"] == "v2"

    def test_empty_list(self) -> None:
        data = _export_jsonl([])
        assert data == b""

    def test_failed_results(self) -> None:
        r = _make_runner_result(ok=False)
        data = _export_jsonl([r])
        obj = json.loads(data.decode("utf-8").strip())
        assert obj["ok"] is False


class TestExportCsv:
    """Cover ``_export_csv``."""

    def test_single(self) -> None:
        r = _make_runner_result(video_id="v1", status="fracture")
        data = _export_csv([r])
        text = data.decode("utf-8")
        assert "v1" in text
        assert "fracture" in text

    def test_multiple(self) -> None:
        r1 = _make_runner_result(video_id="v1", status="fracture")
        r2 = _make_runner_result(video_id="v2", status="no_fracture")
        data = _export_csv([r1, r2])
        text = data.decode("utf-8")
        lines = text.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert "v1" in lines[1]
        assert "v2" in lines[2]

    def test_empty_list(self) -> None:
        data = _export_csv([])
        assert data.decode("utf-8").strip() == "video_id,status,has_fracture,time_range,fracture_type,location,confidence,unrecognized_reason,rounds,ok,error_code,error_message"

    def test_failed_results(self) -> None:
        r = _make_runner_result(ok=False)
        data = _export_csv([r])
        text = data.decode("utf-8")
        assert "TestError" in text
        assert "False" in text  # ok field


class TestExportJson:
    """Cover ``_export_json``."""

    def test_single(self) -> None:
        r = _make_runner_result(video_id="v1")
        data = _export_json([r])
        obj = json.loads(data.decode("utf-8"))
        assert len(obj) == 1
        assert obj[0]["result"]["video_id"] == "v1"

    def test_multiple(self) -> None:
        results = [_make_runner_result(video_id="v1"), _make_runner_result(video_id="v2")]
        data = _export_json(results)
        obj = json.loads(data.decode("utf-8"))
        assert len(obj) == 2

    def test_empty_list(self) -> None:
        data = _export_json([])
        assert json.loads(data.decode("utf-8")) == []

    def test_failed_results(self) -> None:
        r = _make_runner_result(ok=False)
        data = _export_json([r])
        obj = json.loads(data.decode("utf-8"))
        assert obj[0]["ok"] is False
        assert "error" in obj[0]


# =========================================================================
# 5. Task status transitions (8 tests)
# =========================================================================


class TestTaskStatusTransitions:
    """Cover ``TaskItem`` status transitions."""

    def test_default_status(self) -> None:
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4")
        assert task.status == STATUS_PENDING

    def test_default_fields(self) -> None:
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4")
        assert task.events == []
        assert task.result is None
        assert task.error is None

    def test_pending_to_running(self) -> None:
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4")
        task.status = STATUS_RUNNING
        assert task.status == STATUS_RUNNING

    def test_running_to_completed(self) -> None:
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4", status=STATUS_RUNNING)
        task.status = STATUS_COMPLETED
        task.result = {"ok": True, "result": {"video_id": "v1", "status": "fracture"}}
        assert task.status == STATUS_COMPLETED
        assert task.result["ok"] is True

    def test_running_to_failed(self) -> None:
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4", status=STATUS_RUNNING)
        task.status = STATUS_FAILED
        task.error = "connection error"
        assert task.status == STATUS_FAILED
        assert task.error == "connection error"

    def test_events_append(self) -> None:
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4")
        task.events.append({"event_type": "video_started"})
        task.events.append({"event_type": "video_finished"})
        assert len(task.events) == 2

    def test_dataclass_fields_present(self) -> None:
        """All required dataclass fields exist."""
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4")
        d = asdict(task)
        assert "video_id" in d
        assert "video_path" in d
        assert "status" in d
        assert "config_path" in d
        assert "work_dir" in d
        assert "events" in d
        assert "result" in d
        assert "error" in d

    def test_default_config_and_workdir(self) -> None:
        """Default config_path and work_dir."""
        task = TaskItem(video_id="v1", video_path="/p/v1.mp4")
        assert task.config_path == "agent/config.yaml"
        assert task.work_dir == "."


# =========================================================================
# 6. Badge HTML, event log HTML, result card HTML (10 tests)
# =========================================================================


class TestBadgeHtml:
    """Cover ``_status_badge_html`` and ``_round_badge_html``."""

    def test_status_pending_html(self) -> None:
        html = _status_badge_html("pending")
        assert "status-pending" in html
        assert "pending" in html

    def test_status_running_html(self) -> None:
        html = _status_badge_html("running")
        assert "status-running" in html
        assert "running" in html

    def test_status_completed_html(self) -> None:
        html = _status_badge_html("completed")
        assert "status-completed" in html
        assert "completed" in html

    def test_status_failed_html(self) -> None:
        html = _status_badge_html("failed")
        assert "status-failed" in html
        assert "failed" in html

    def test_unknown_status_html(self) -> None:
        """Unknown status uses pending style."""
        html = _status_badge_html("unknown")
        assert "status-pending" in html

    def test_round_badge_html(self) -> None:
        html = _round_badge_html(3)
        assert "round-badge" in html
        assert "第 3 轮" in html

    def test_round_badge_zero(self) -> None:
        html = _round_badge_html(0)
        assert "round-badge" in html
        assert "第 0 轮" in html


class TestEventLogHtml:
    """Cover ``_event_log_html``."""

    def test_wraps_text(self) -> None:
        html = _event_log_html("test log")
        assert "event-log" in html
        assert "test log" in html

    def test_multiline(self) -> None:
        html = _event_log_html("line1\nline2")
        assert "line1" in html
        assert "line2" in html

    def test_empty_string(self) -> None:
        html = _event_log_html("")
        assert "event-log" in html


class TestResultCardHtml:
    """Cover ``_result_card_html``."""

    def test_fracture_card(self) -> None:
        html = _result_card_html("fracture", "断裂检测", ["类型: 脆性", "置信度: 0.92"])
        assert "result-fracture" in html
        assert "断裂检测" in html
        assert "类型: 脆性" in html
        assert "置信度: 0.92" in html

    def test_no_fracture_card(self) -> None:
        html = _result_card_html("no_fracture", "未断裂")
        assert "result-no_fracture" in html
        assert "未断裂" in html

    def test_unrecognized_card(self) -> None:
        html = _result_card_html("unrecognized", "未识别")
        assert "result-unrecognized" in html
        assert "未识别" in html

    def test_failed_card(self) -> None:
        html = _result_card_html("failed", "失败")
        assert "result-failed" in html
        assert "失败" in html

    def test_unknown_status_no_class(self) -> None:
        """Unknown status produces no result-* class."""
        html = _result_card_html("weird", "something")
        assert "result-weird" not in html  # not in our CSS classes

    def test_no_detail_lines(self) -> None:
        """No detail lines when not provided."""
        html = _result_card_html("fracture", "summary")
        assert "summary" in html
        assert "<br>" not in html.rpartition("summary")[2]  # no extra br after summary


# =========================================================================
# 7. Streamlit missing → importable (4 tests)
# =========================================================================


class TestImportWithoutStreamlit:
    """Verify the module can be imported without Streamlit installed."""

    def test_taskitem_importable(self) -> None:
        """TaskItem is importable."""
        from ui.agent_app import TaskItem
        assert TaskItem is not None

    def test_helper_functions_importable(self) -> None:
        """All helper functions are importable."""
        from ui.agent_app import (
            _find_video_files,
            _format_event_summary,
            _result_to_row,
            _export_jsonl,
            _export_csv,
            _export_json,
            _status_badge_html,
            _round_badge_html,
            _event_log_html,
            _result_card_html,
        )
        assert callable(_find_video_files)
        assert callable(_format_event_summary)
        assert callable(_result_to_row)
        assert callable(_export_jsonl)
        assert callable(_export_csv)
        assert callable(_export_json)
        assert callable(_status_badge_html)
        assert callable(_round_badge_html)
        assert callable(_event_log_html)
        assert callable(_result_card_html)

    def test_st_is_none_when_not_installed(self) -> None:
        """st is None when Streamlit is absent."""
        from ui.agent_app import st as st_ref
        assert st_ref is None

    def test_main_not_called_on_import(self) -> None:
        """Import does not trigger main()."""
        # Just verifying no side effects - import already happened above
        import ui.agent_app
        assert hasattr(ui.agent_app, "main")


# =========================================================================
# Total: 10 + 10 + 10 + 10 + 8 + 12 + 4 = 64 tests
# =========================================================================
