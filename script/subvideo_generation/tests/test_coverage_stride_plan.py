"""F5: lock the coverage stride by behaviour, not only by a short golden source.

``video_0005`` is only 30 s long, so a golden snapshot of it cannot see a changed
stride. These synthetic schedules can: 90 s of 10 fps material exercises the full
20 s / 15 s grid plus the tail window.
"""
from __future__ import annotations

import pytest

from script.subvideo_generation._legacy.coverage import generate as coverage
from script.subvideo_generation.tests.rules_support import rules_module


def synthetic_media(seconds, fps=10):
    frames = int(round(seconds * fps))
    return {"timestamps": [index / fps for index in range(frames)],
            "duration": float(seconds), "total_frames": frames, "fps": fps}


def test_ninety_second_source_uses_the_approved_stride_and_tail_window():
    windows = coverage.plan_windows(synthetic_media(90))

    assert [window["start_time"] for window in windows] == [0.0, 15.0, 30.0, 45.0, 60.0, 70.0]
    assert [window["end_time"] for window in windows] == [20.0, 35.0, 50.0, 65.0, 80.0, 90.0]
    assert [(window["start_frame"], window["end_frame"]) for window in windows] == [
        (0, 200), (150, 350), (300, 500), (450, 650), (600, 800), (700, 900)]


def test_coverage_stride_follows_the_registered_rule_constant(monkeypatch):
    """The stride must live in ``rules`` instead of inside ``plan_windows``."""
    rules = rules_module()
    monkeypatch.setattr(rules, "COVERAGE_STEP_SECONDS", 30)
    if hasattr(coverage, "COVERAGE_STEP_SECONDS"):  # tolerate a module-level rebinding
        monkeypatch.setattr(coverage, "COVERAGE_STEP_SECONDS", 30)

    windows = coverage.plan_windows(synthetic_media(90))

    starts = [window["start_time"] for window in windows]
    assert starts[:3] == [0.0, 30.0, 60.0], (
        f"the coverage stride must follow rules.COVERAGE_STEP_SECONDS, got starts {starts}")


def test_coverage_window_length_follows_the_registered_rule_constant(monkeypatch):
    rules = rules_module()
    monkeypatch.setattr(rules, "COVERAGE_WINDOW_SECONDS", 10)
    if hasattr(coverage, "COVERAGE_WINDOW_SECONDS"):
        monkeypatch.setattr(coverage, "COVERAGE_WINDOW_SECONDS", 10)

    windows = coverage.plan_windows(synthetic_media(90))

    lengths = [round(window["end_time"] - window["start_time"], 6) for window in windows]
    assert lengths[:2] == [10.0, 10.0], (
        f"the coverage window length must follow rules.COVERAGE_WINDOW_SECONDS, got {lengths}")
