"""Synthetic decoded-frame and PTS checks for the aligned entry."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from subvideo_pilot import aligned


def _video(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required')
    path = tmp_path / 'source.mp4'
    # Low-frequency, distinct block pictures remain recognisable after lossy
    # encoding; adjacent near-static pictures intentionally cannot establish
    # a unique frame identity under the compression-error envelope.
    import numpy as np
    blocks = np.random.default_rng(4738).integers(20, 230, (60, 6, 8, 3), dtype=np.uint8)
    frames = blocks.repeat(16, axis=1).repeat(16, axis=2)
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                    '-s', '128x96', '-r', '10', '-i', '-', '-threads', '1',
                    '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', str(path)],
                   input=frames.tobytes(), check=True)
    return path


def test_actual_frame_crop_has_recorded_anchor_and_picture_sequence(tmp_path):
    source = _video(tmp_path)
    media = aligned.probe_video(source)
    candidate = {'start_frame': 10, 'end_frame': 40, 'source_anchor_frames': [29, 30],
                 'roi_sha256': aligned.base.sha256_file(source)}
    output = tmp_path / 'output.mp4'
    result = aligned.crop_video(source, output, candidate, media, aligned._features(source))
    assert result['media']['total_frames'] == 30
    assert result['frame_mapping']['anchors'] == [
        {'source_frame': 29, 'roi_frame': 29, 'output_frame': 19},
        {'source_frame': 30, 'roi_frame': 30, 'output_frame': 20}]
    assert result['picture_correspondence']['decoded_frames'] == 30
    with pytest.raises(FileExistsError):
        aligned.crop_video(source, output, candidate, media, aligned._features(source))


def test_real_pts_probe_accepts_nonuniform_monotonic_timestamps(tmp_path):
    source = _video(tmp_path)
    path = tmp_path / 'irregular.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-vf',
                    'setpts=PTS+if(gte(N\\,20)\\,0.02/TB\\,0)', '-vsync', '0',
                    '-enc_time_base', '-1', '-threads', '1', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    media = aligned.probe_video(path)
    assert media['total_frames'] == 60
    assert media['timestamp_validation'] == 'decoded_monotonic_pts_no_constant_rate_grid'
    gaps = [b - a for a, b in zip(media['timestamps'], media['timestamps'][1:])]
    assert max(gaps) - min(gaps) > 0.01


def test_displaced_anchor_remains_ambiguous_inside_compression_error_envelope():
    import numpy as np
    expected = np.array([10, 20, 30, 50, 80, 100, 120, 140, 51, 180, 200, 220],
                        dtype=np.uint8)[:, None, None]
    actual = expected.copy()
    actual[3] = 51
    actual[8] = 52  # Real frame 3 moved here, plus a tolerated coding error of 2.
    with pytest.raises(aligned.AlignmentUncertain, match='ambiguous') as caught:
        aligned.compare_sequences(expected, actual, [3])
    assert caught.value.details['compatible_alternative_count'] >= 1
