from __future__ import annotations

import pytest

from agent.sampling import (
    fracture_between_to_frame_range,
    fracture_between_to_time_range,
    frame_to_time,
    is_boundary_sentinel,
    time_to_frame,
)


def test_frame_to_time_and_back():
    fps = 30.0
    assert frame_to_time(150, fps) == pytest.approx(5.0)
    assert time_to_frame(5.0, fps) == 150
    assert time_to_frame(5.017, fps) == 151


def test_time_to_frame_rejects_non_positive_fps():
    with pytest.raises(ValueError):
        time_to_frame(1.0, 0.0)


def test_fracture_between_to_time_range():
    frames = [
        {"input_index": 0, "original_frame": 100, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 108, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 116, "timestamp": 2.0},
    ]
    assert fracture_between_to_time_range([1, 2], frames) == [1.0, 2.0]
    assert fracture_between_to_frame_range([0, 1], frames) == [100, 108]


def test_fracture_between_out_of_range():
    frames = [
        {"input_index": 0, "original_frame": 100, "timestamp": 0.0},
    ]
    with pytest.raises(ValueError):
        fracture_between_to_time_range([0, 1], frames)


def test_boundary_sentinel_detection():
    assert is_boundary_sentinel([0, 0], 10) is True
    assert is_boundary_sentinel([9, 9], 10) is True
    assert is_boundary_sentinel([4, 5], 10) is False
    assert is_boundary_sentinel(None, 10) is False
    assert is_boundary_sentinel([0, 0], 0) is False
