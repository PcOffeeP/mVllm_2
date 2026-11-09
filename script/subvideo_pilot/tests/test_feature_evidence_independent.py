"""Synthetic native-detail evidence; none of these measurements grants admission."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from script.subvideo_pilot import aligned, anchor_evidence


def assert_analysis_only(result):
    assert result["analysis_status"] == "evidence_only_pending"
    assert result["automatic_generation_allowed"] is False
    assert result["changes_production_state"] is False


def test_two_pixel_local_change_survives_an_identical_coarse_feature():
    expected = np.full((512, 512), 100, dtype=np.uint8)
    changed = expected.copy()
    changed[255:257, 255:257] = 130
    actual = np.stack([expected, changed, np.full_like(expected, 180)])
    # This is a deliberate coarse-feature collision, supplied independently.
    # Native evidence must retain the small region that coarse pooling lost.
    coarse = np.zeros((3, 64, 64), dtype=np.uint8)
    result = anchor_evidence.analyze_anchor(
        expected, actual, 0, tile_size=16,
        coarse_expected_anchor=coarse[0], coarse_actual_frames=coarse,
    )
    row = result["frames"][1]
    assert row["coarse_mae"] == 0
    assert row["native_max_pixel_error"] == 30
    assert row["native_mae"] == pytest.approx(120 / (512 * 512))
    assert row["tile_max_mae"] > 100 * row["native_mae"]
    assert row["tile_max_gradient_mae"] > 0
    assert 1 in result["competing_frames_within_current_coarse_envelope"]
    assert result["coarse_implementation"] == "supplied_aligned_features"
    assert_analysis_only(result)


def test_distant_near_frame_with_codec_noise_is_retained_without_a_winner():
    values = np.asarray([0, 220, 120, 50, 180, 100, 200, 90, 51, 140, 230, 30], dtype=np.uint8)
    actual = np.broadcast_to(values[:, None, None], (12, 128, 128)).copy()
    expected = actual[3].copy()
    actual[3] = 51
    actual[8] = 52
    result = anchor_evidence.analyze_anchor(expected, actual, 3)
    assert len(result["frames"]) == 12
    assert result["frames"][3]["native_mae"] == 1
    assert result["frames"][8]["native_mae"] == 2
    assert 8 in result["competing_frames_within_current_coarse_envelope"]
    assert_analysis_only(result)


def test_all_static_competitors_remain_visible_and_pending():
    expected = np.full((64, 64), 117, dtype=np.uint8)
    result = anchor_evidence.analyze_anchor(expected, np.stack([expected] * 7), 3)
    assert result["competing_frames_within_current_coarse_envelope"] == [0, 1, 2, 4, 5, 6]
    assert [row["frame_index"] for row in result["frames"]] == list(range(7))
    assert all(row["native_mae"] == row["tile_max_mae"] == 0 for row in result["frames"])
    assert_analysis_only(result)


def test_experimental_analysis_cannot_relax_production_static_frame_gate():
    frames = np.full((5, 64, 64), 117, dtype=np.uint8)
    thresholds = (aligned.MAX_MEAN_PIXEL_ERROR, aligned.MIN_ANCHOR_MARGIN)
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(frames, frames, [2])
    result = anchor_evidence.analyze_anchor(frames[2], frames, 2)
    assert_analysis_only(result)
    assert (aligned.MAX_MEAN_PIXEL_ERROR, aligned.MIN_ANCHOR_MARGIN) == thresholds
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(frames, frames, [2])


def test_one_pixel_crop_shift_with_padding_remains_measurable():
    source = np.broadcast_to(np.arange(50, dtype=np.uint8) * 4, (40, 50)).copy()
    # The expected crop/pad operation is constructed outside production code.
    expected = np.pad(source[6:22, 5:29], ((2, 4), (3, 1)), constant_values=0)
    shifted = np.pad(source[6:22, 6:30], ((2, 4), (3, 1)), constant_values=0)
    result = anchor_evidence.analyze_anchor(expected, np.stack([expected, shifted]), 0, tile_size=7)
    assert result["frames"][0]["native_mae"] == 0
    assert result["frames"][1]["native_mae"] > 0
    assert result["frames"][1]["tile_max_gradient_mae"] > 0
    # Nonmultiple dimensions still have complete, nonoverlapping tile coverage.
    coverage = np.zeros(expected.shape, dtype=np.int8)
    for tile in result["tiles"]:
        y, x, h, w = [tile[key] for key in ("top", "left", "height", "width")]
        coverage[y:y+h, x:x+w] += 1
    assert np.all(coverage == 1)
    assert_analysis_only(result)


def test_wrong_padding_dimensions_are_not_silently_registered_or_resized():
    expected = np.zeros((22, 28), dtype=np.uint8)
    with pytest.raises(ValueError, match="geometry mismatch"):
        anchor_evidence.analyze_anchor(expected, [np.zeros((22, 27), dtype=np.uint8)], 0)


@pytest.mark.parametrize("shape", [(1, 1), (1, 2), (2, 1)])
def test_tiny_native_images_have_finite_evidence_and_no_resolution_claim(shape):
    expected = np.full(shape, 117, dtype=np.uint8)
    result = anchor_evidence.analyze_anchor(expected, [expected, expected + 1], 0, tile_size=16)
    assert result["native_detail_warning"] == "native_picture_smaller_than_coarse_feature_no_added_resolution"
    assert len(result["tiles"]) == 1
    assert result["frames"][1]["native_mae"] == 1
    assert result["frames"][1]["tile_max_mae"] == 1
    if shape == (1, 1):
        assert result["frames"][1]["tile_gradient_mae"] == [None]
    json.dumps(result, allow_nan=False)
    assert_analysis_only(result)


@pytest.mark.parametrize("expected", [
    np.empty((0, 4)), np.full((4, 4), np.nan), np.full((4, 4), -1),
    np.full((4, 4), 256), np.zeros((4, 4, 3)),
])
def test_invalid_native_anchor_cannot_produce_evidence(expected):
    with pytest.raises(ValueError):
        anchor_evidence.analyze_anchor(expected, [expected], 0)


@pytest.mark.parametrize("anchor_index", [-1, 2, True])
def test_invalid_claimed_anchor_is_an_explicit_input_error(anchor_index):
    expected = np.full((4, 4), 117, dtype=np.uint8)
    with pytest.raises(ValueError):
        anchor_evidence.analyze_anchor(expected, [expected, expected], anchor_index)


@pytest.mark.parametrize("tile_size", [0, -1, True])
def test_invalid_tile_size_cannot_silently_drop_local_evidence(tile_size):
    expected = np.full((4, 4), 117, dtype=np.uint8)
    with pytest.raises(ValueError):
        anchor_evidence.analyze_anchor(expected, [expected], 0, tile_size=tile_size)


def test_supplied_coarse_frame_coverage_mismatch_is_an_explicit_input_error():
    expected = np.full((32, 32), 117, dtype=np.uint8)
    with pytest.raises(ValueError, match="counts differ"):
        anchor_evidence.analyze_anchor(
            expected, [expected] * 3, 0,
            coarse_expected_anchor=np.zeros((64, 64), dtype=np.uint8),
            coarse_actual_frames=np.zeros((2, 64, 64), dtype=np.uint8),
        )


@pytest.mark.parametrize("video_id", ["video_0002", "video_0015", "video_0050", "video_9999"])
def test_project_analysis_respects_held_and_test_ids_before_media_access(video_id, tmp_path, monkeypatch):
    dev = {name: {} for name in ("video_0002", "video_0015", "video_0050", "video_0001")}
    monkeypatch.setattr(anchor_evidence.base, "load_inputs", lambda _root: (dev, {}, {}, {}))

    def media_access_forbidden(*_args, **_kwargs):
        pytest.fail("held/test media must not be read for experimental analysis")

    monkeypatch.setattr(anchor_evidence.base, "sha256_file", media_access_forbidden)
    monkeypatch.setattr(anchor_evidence.aligned, "probe_video", media_access_forbidden)
    with pytest.raises(anchor_evidence.base.PilotError):
        anchor_evidence.analyze_project_anchor(tmp_path, video_id, 0)
    assert not list(tmp_path.rglob("*"))


def test_native_frame_stream_cannot_deadlock_when_decoder_stderr_pipe_fills():
    # A separate process group bounds this regression even if the reader blocks.
    # The real child writes more than pipe capacity to stderr *before* stdout.
    # Draining stdout then stderr sequentially cannot finish this protocol.
    wrapper = textwrap.dedent(r'''
        from pathlib import Path
        import sys
        from script.subvideo_pilot import anchor_evidence

        producer = (
            "import sys; "
            "sys.stderr.buffer.write(b'x' * (1024 * 1024)); sys.stderr.flush(); "
            "sys.stdout.buffer.write(bytes([7]) * 4); sys.stdout.flush()"
        )
        anchor_evidence._native_command = lambda _path, _filter: [sys.executable, '-c', producer]
        frames = list(anchor_evidence._native_frames(Path('synthetic-not-a-video'), 2, 2))
        assert len(frames) == 1 and frames[0].tolist() == [[7, 7], [7, 7]]
        print('native-frame-stream-finished')
    ''')
    process = subprocess.Popen(
        [sys.executable, "-c", wrapper], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=2)
        pytest.fail("native frame reader deadlocked while decoder filled stderr")
    assert process.returncode == 0, stderr.decode(errors="replace")
    assert stdout.strip() == b"native-frame-stream-finished"
