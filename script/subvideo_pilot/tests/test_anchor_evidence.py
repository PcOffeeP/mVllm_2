"""Experimental native/local measurements never grant generation admission."""
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from subvideo_pilot import anchor_evidence as evidence


def test_small_local_change_is_visible_but_never_automatically_accepted():
    expected = np.full((256, 256), 80, np.uint8)
    changed = expected.copy(); changed[120:124, 120:128] = 160
    result = evidence.analyze_anchor(expected, np.stack([expected, changed]), 0)
    other = result['frames'][1]
    assert other['coarse_mae'] < 5
    assert other['native_mae'] == pytest.approx(0.0390625)
    assert other['tile_max_mae'] == pytest.approx(10)
    assert result['competing_frames_within_current_coarse_envelope'] == [1]
    assert result['analysis_status'] == 'evidence_only_pending'
    assert not result['automatic_generation_allowed']
    assert not result['changes_production_state']


def test_supplied_production_coarse_features_are_kept_as_evidence():
    expected = np.zeros((32, 32), np.uint8)
    actual = np.stack([expected, np.full_like(expected, 100)])
    coarse = np.zeros((2, 64, 64), np.uint8)
    result = evidence.analyze_anchor(expected, actual, 0, coarse_expected_anchor=coarse[0], coarse_actual_frames=coarse)
    assert result['frames'][1]['coarse_mae'] == 0
    assert result['frames'][1]['native_mae'] == 100
    assert result['competing_frames_within_current_coarse_envelope'] == [1]
    assert result['automatic_generation_allowed'] is False


def test_project_analysis_uses_effective_crop_and_does_not_write_results(tmp_path, monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required')
    root = tmp_path / 'project'; raw = root/'data/videos/video_0001.mp4'; roi = root/'data/roi/videos/video_0001.mp4'
    raw.parent.mkdir(parents=True); roi.parent.mkdir(parents=True)
    frames = np.random.default_rng(44).integers(20, 230, (8, 4, 6, 3), dtype=np.uint8).repeat(16, 1).repeat(16, 2)
    subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','96x64','-r','8','-i','-',
                    '-threads','1','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(raw)], input=frames.tobytes(),check=True)
    subprocess.run(['ffmpeg','-v','error','-i',str(raw),'-vf','crop=64:48:2:4:exact=1,format=yuv444p,pad=72:56:4:4',
                    '-vsync','0','-threads','1','-c:v','libx264','-crf','23','-pix_fmt','yuv420p',str(roi)],check=True)
    sha = evidence.base.sha256_file
    record = {'source':{'sha256':sha(raw)},'output':{'sha256':sha(roi),'geometry':{
              'geometry_status':'verified_from_filter_and_source_format',
              'effective_pixel_box':{'x':2,'y':4,'width':64,'height':48},
              'requested_pixel_box':{'x':3,'y':5,'width':64,'height':48},
              'pad_pixels':{'left':4,'right':4,'top':4,'bottom':4}}},
              'decision':{'source_sha256':sha(raw)}}
    monkeypatch.setattr(evidence.base,'load_inputs',lambda _: ({'video_0001':{}},{'video_0001':record},{},{}))
    before = {p.relative_to(root):sha(p) for p in root.rglob('*') if p.is_file()}
    result = evidence.analyze_project_anchor(root,'video_0001',3)
    after = {p.relative_to(root):sha(p) for p in root.rglob('*') if p.is_file()}
    assert before == after
    assert result['searched_frame_count'] == 8
    assert result['native_shape'] == [56,72]
    assert 'crop=64:48:2:4:exact=1' in result['identity']['source_ROI_effective_transform']
    assert result['frames'][3]['native_mae'] < 5
    assert result['analysis_status'] == 'evidence_only_pending'
    assert result['automatic_generation_allowed'] is False


@pytest.mark.parametrize('exit_code', [0, 7])
def test_native_reader_handles_stderr_before_stdout_without_pipe_deadlock(exit_code):
    # Run the wrapper in a bounded subprocess so a regression fails promptly.
    # Its synthetic child emits 1 MiB of diagnostics before producing pictures.
    child = ("import sys; sys.stderr.buffer.write(b'x' * (1024 * 1024)); "
             "sys.stderr.buffer.write(b'FINAL_DIAGNOSTIC'); sys.stderr.flush(); "
             "sys.stdout.buffer.write(bytes(range(8))); sys.stdout.flush(); "
             f"sys.exit({exit_code})")
    wrapper = '''
from pathlib import Path
import sys
from script.subvideo_pilot import anchor_evidence as e
child = sys.argv[1]
e._native_command = lambda *_: [sys.executable, '-c', child]
if int(sys.argv[2]):
    try:
        list(e._native_frames(Path('synthetic-no-media'), 2, 2))
    except e.base.PilotError as exc:
        assert 'FINAL_DIAGNOSTIC' in str(exc)
        assert len(str(exc)) < 4200
    else:
        raise AssertionError('nonzero child must fail')
else:
    frames = list(e._native_frames(Path('synthetic-no-media'), 2, 2))
    assert len(frames) == 2
    assert frames[1].tolist() == [[4, 5], [6, 7]]
'''
    subprocess.run([sys.executable, '-c', wrapper, child, str(exit_code)],
                   cwd=Path(__file__).resolve().parents[3], check=True, timeout=10)


def test_native_reader_reaps_child_when_consumer_stops_early(monkeypatch):
    command = [sys.executable, '-c',
               "import sys,time; sys.stdout.buffer.write(bytes(range(4))); sys.stdout.flush(); time.sleep(60)"]
    monkeypatch.setattr(evidence, '_native_command', lambda *_: command)
    popen = evidence.subprocess.Popen
    children = []
    def capture(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(evidence.subprocess, 'Popen', capture)
    frames = evidence._native_frames(Path('synthetic-no-media'), 2, 2)
    assert next(frames).tolist() == [[0, 1], [2, 3]]
    frames.close()
    assert len(children) == 1
    assert children[0].poll() is not None


def test_native_reader_rejects_zero_frame_size_before_starting_child(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('invalid dimensions must not start a child')
    monkeypatch.setattr(evidence.subprocess, 'Popen', forbidden)
    with pytest.raises(ValueError, match='positive integers'):
        list(evidence._native_frames(Path('synthetic-no-media'), 0, 2))
