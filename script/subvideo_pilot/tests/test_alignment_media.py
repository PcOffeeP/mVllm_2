"""Synthetic decoded-frame and PTS checks for the aligned entry."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from subvideo_pilot import aligned, replay


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


def test_actual_frame_crop_has_recorded_anchor_and_picture_sequence(tmp_path, monkeypatch):
    raw = _video(tmp_path)
    source = tmp_path / 'roi.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n', '-i', str(raw),
                    '-map', '0:v:0', '-vf', 'crop=128:96:0:0,setsar=1', '-vsync', '0',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
                    '-an', '-movflags', '+faststart', str(source)], check=True)
    sha = aligned.base.sha256_file
    roi = {'video_id':'video_0001','source':{'sha256':sha(raw)},
           'decision':{'source_sha256':sha(raw),'mode':'fixed_roi','source_resolution':[128,96],
                       'pixel_box':{'x':0,'y':0,'width':128,'height':96}},
           'output':{'sha256':sha(source),'encoding':{'video_codec':'libx264','preset':'fast','crf':23,
                     'pixel_format':'yuv420p','audio':'dropped','frame_sync':'vsync_0_passthrough'},
                     'geometry':{'filter':'crop=128:96:0:0,setsar=1',
                                 'effective_pixel_box':{'x':0,'y':0,'width':128,'height':96},
                                 'pad_pixels':{'left':0,'right':0,'top':0,'bottom':0},
                                 'output_resolution':[128,96]}}}
    row = {'id':'video_0001','断裂状态':'发生断裂','断裂帧_前':'29','断裂帧_后':'30'}
    monkeypatch.setattr(replay,'_toolchain',lambda:{'synthetic_version_gate':'4.4.2 simulated'})
    proof = replay.verify_source_replay(raw, source, roi, source_annotation=row)
    media = aligned.probe_video(source)
    candidate = {'start_frame': 10, 'end_frame': 40, 'source_anchor_frames': [29, 30],
                 'source_video_id':'video_0001','source_frame_range':[10,40],
                 'source_sha256':sha(raw),'event_kind':'exact','window_role':'transition',
                 'roi_sha256': sha(source)}
    output = tmp_path / 'output.mp4'
    result = aligned.crop_video(source, output, candidate, media, aligned._features(source), source_proof=proof)
    assert result['media']['total_frames'] == 30
    assert result['frame_mapping']['anchors'] == [
        {'source_frame': 29, 'roi_frame': 29, 'output_frame': 19},
        {'source_frame': 30, 'roi_frame': 30, 'output_frame': 20}]
    assert result['picture_correspondence']['decoded_frames'] == 30
    assert result['frame_preserving_replay']['status'] == replay.VERIFIED
    with pytest.raises(FileExistsError):
        aligned.crop_video(source, output, candidate, media, aligned._features(source), source_proof=proof)


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
