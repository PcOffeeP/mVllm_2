from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_no_oob as vnoob


class TestIsValidFractureBetween:
    def test_adjacent_interval_passes(self):
        assert vnoob._is_valid_fracture_between([5, 6], n=10) is True

    def test_first_adjacent_interval_passes(self):
        assert vnoob._is_valid_fracture_between([0, 1], n=10) is True

    def test_left_boundary_sentinel_passes(self):
        assert vnoob._is_valid_fracture_between([0, 0], n=10) is True

    def test_right_boundary_sentinel_passes(self):
        assert vnoob._is_valid_fracture_between([9, 9], n=10) is True

    def test_non_adjacent_non_sentinel_fails(self):
        assert vnoob._is_valid_fracture_between([0, 2], n=10) is False
        assert vnoob._is_valid_fracture_between([3, 5], n=10) is False

    def test_same_index_not_at_boundary_fails(self):
        assert vnoob._is_valid_fracture_between([5, 5], n=10) is False

    def test_malformed_fails(self):
        assert vnoob._is_valid_fracture_between([1], n=10) is False
        assert vnoob._is_valid_fracture_between([1, 2, 3], n=10) is False

    def test_right_sentinel_without_n_fails(self):
        """若缺少总帧数，无法确认 [k, k] 是否为 [N-1, N-1]，应拒绝。"""
        assert vnoob._is_valid_fracture_between([9, 9], n=None) is False

    def test_left_sentinel_without_n_passes(self):
        """[0, 0] 是明确的左边界哨兵，无需总帧数。"""
        assert vnoob._is_valid_fracture_between([0, 0], n=None) is True


def test_main_skips_when_generated_metadata_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vnoob, "ROOT", tmp_path)

    assert vnoob.main() == 0
    captured = capsys.readouterr()
    assert "SKIP: generated subvideo metadata does not exist" in captured.out
