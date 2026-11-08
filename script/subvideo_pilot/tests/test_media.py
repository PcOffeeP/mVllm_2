"""Synthetic media verifies actual frame cuts and resumable identity binding."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from subvideo_pilot import pilot


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


@pytest.fixture
def synthetic_root(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required for synthetic media test')
    root = tmp_path / 'project'
    raw_dir = root / 'data/videos'; raw_dir.mkdir(parents=True)
    roi_dir = root / 'data/roi/videos'; roi_dir.mkdir(parents=True)
    fixture = tmp_path / 'fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10',
                    '-t', '6', '-threads', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(fixture)], check=True)
    dev = [f'video_{i:04d}' for i in range(1, 4)]
    rows, roi_rows = [], []
    for i, video_id in enumerate(dev):
        raw = raw_dir / f'{video_id}.mp4'; roi = roi_dir / raw.name
        shutil.copyfile(fixture, raw); shutil.copyfile(fixture, roi)
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        rows.append({'id': video_id, '断裂状态': '发生断裂' if i == 0 else '未断裂' if i == 1 else '无法确定',
                     '断裂模式': '脆性断裂' if i == 0 else '无',
                     '异常_未夹紧': '否', '异常_视频异常': '否', '异常_爆炸性断裂': '否',
                     '断裂时间点': '3' if i == 0 else '无',
                     '断裂帧_前': '29' if i == 0 else '无', '断裂帧_后': '30' if i == 0 else '无'})
        roi_rows.append({'video_id': video_id, 'status': 'success', 'source': {'sha256': digest},
                         'output': {'sha256': digest}, 'decision': {'source_sha256': digest}})
    annotation = root / 'data/annotation-table-full.csv'
    with annotation.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        # No video or ROI entry exists for test; accessing it would fail.
        writer.writerow({'id': 'video_9999', '断裂状态': '发生断裂'})
    split = root / 'data/splits/three-fold'
    write_json(split / 'test.json', {'video_ids': ['video_9999']})
    for i in range(3):
        write_json(split / f'fold_{i}_train.json', {'video_ids': [v for v in dev if v != dev[i]]})
        write_json(split / f'fold_{i}_val.json', {'video_ids': [dev[i]]})
    write_json(root / 'data/roi/manifest.json', {'videos': roi_rows})
    return root


def test_synthetic_plan_crop_and_resume_preserve_frames(synthetic_root, tmp_path):
    output = tmp_path / 'cuts'
    plan = pilot.run(synthetic_root, output, plan_only=True)
    assert plan['model_sampling_gate'] == 'not_run'
    assert plan['five_category_labels'] == 'not_assigned_pending_clip_review'
    assert not list((output / 'videos').glob('*.mp4'))
    assert {s['video_id'] for s in plan['sources']} == {'video_0001', 'video_0002', 'video_0003'}
    assert plan['sources'][-1]['reason'] == 'unsupported_or_uncertain_source_state'
    materialized = pilot.run(synthetic_root, output, resume=True)
    assert materialized['complete']
    assert materialized['candidates']
    for row in materialized['candidates']:
        assert row['status'] == 'cropped'
        assert row['manual_review'] == 'required'
        assert row['labels_status'] == 'unassigned'
        assert row['output']['media']['total_frames'] == row['end_frame'] - row['start_frame']
    before = (output / 'manifest.json').read_bytes()
    pilot.run(synthetic_root, output, resume=True)
    assert (output / 'manifest.json').read_bytes() == before


def test_output_replacement_is_refused(synthetic_root, tmp_path):
    output = tmp_path / 'cuts'
    plan = pilot.run(synthetic_root, output, plan_only=True)
    first = plan['candidates'][0]
    orphan = output / first['output_path']; orphan.write_bytes(b'not owned')
    with pytest.raises(pilot.PilotError, match='unrecorded output'):
        pilot.run(synthetic_root, output, resume=True)
    assert orphan.read_bytes() == b'not owned'


def test_changed_input_prevents_resume(synthetic_root, tmp_path):
    output = tmp_path / 'cuts'; pilot.run(synthetic_root, output, plan_only=True)
    table = synthetic_root / 'data/annotation-table-full.csv'
    table.write_bytes(table.read_bytes() + b'\n')
    with pytest.raises(pilot.PilotError, match='resume input or code identity differs'):
        pilot.run(synthetic_root, output, resume=True)


@pytest.mark.parametrize('duration,total_frames,post_allowed', [
    (32.5, 324, False),  # Header duration is 0.1 s longer than decoded coverage.
    (32.4, 325, False),  # The shorter reported duration also limits usable data.
    (32.5, 325, True),   # Exactly 2 s after the event's 0.5 s guard.
    (32.6, 326, True),
])
def test_post_gate_uses_shorter_decoded_or_reported_endpoint(duration, total_frames, post_allowed):
    record = {'video_id': 'video_0001', 'duration': duration, 'fps': 10,
              'total_frames': total_frames, 'type': '脆性断裂',
              'has_fracture_canonical': True, 'is_abnormal_canonical': False,
              'event_time': 30.0, 'event_time_reliable': True,
              'location_canonical': None}
    raw = pilot.geometry._raw_candidates_for_source(record, references=())
    assert any(w['window_role'] == 'post_event' for w in raw)
    accepted, excluded = pilot.plan_windows(record)
    assert any(w['window_role'] == 'post_event' for w in accepted) is post_allowed
    assert any(w['reason'] == 'post_source_remaining_after_guard_less_than_two_seconds'
               for w in excluded) is (not post_allowed)
