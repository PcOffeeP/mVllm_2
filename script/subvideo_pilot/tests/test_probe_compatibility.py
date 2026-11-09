"""FFprobe 4.4 side-data section and fail-closed rotation parsing."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from subvideo_pilot import aligned


def _payload():
    return {'streams': [{'width': 16, 'height': 16, 'r_frame_rate': '30/1',
                         'time_base': '1/15360', 'duration': '0.066667',
                         'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': 0}]}],
            'frames': [{'best_effort_timestamp_time': '0.000000', 'pkt_duration_time': '0.033333'},
                       {'best_effort_timestamp_time': '0.033333', 'pkt_duration_time': '0.033333'}]}


def _mock_probe(monkeypatch, payload):
    commands = []
    def checked(command):
        commands.append(command)
        return SimpleNamespace(stdout=json.dumps(payload))
    monkeypatch.setattr(aligned.base, '_checked', checked)
    return commands


def test_ffprobe_44_side_data_list_section_and_zero_rotation(monkeypatch):
    commands = _mock_probe(monkeypatch, _payload())
    media = aligned.probe_video(Path('synthetic.mp4'))
    entries = commands[0][commands[0].index('-show_entries') + 1]
    assert 'stream_side_data_list=rotation,side_data_type' in entries
    assert 'stream_side_data=' not in entries
    assert media['rotation'] == 0
    assert media['total_frames'] == 2


@pytest.mark.parametrize('change,reason', [
    ({'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': 90}]}, 'unsupported_rotation'),
    ({'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': -90}]}, 'unsupported_rotation'),
    ({'tags': {'rotate': '180'}}, 'unsupported_rotation'),
    ({'side_data_list': [{'side_data_type': 'Display Matrix'}]}, 'without_readable_rotation'),
    ({'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': 'invalid'}]}, 'invalid_rotation'),
    ({'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': 'nan'}]}, 'invalid_rotation'),
    ({'side_data_list': {}}, 'invalid_rotation'),
])
def test_rotation_errors_remain_fail_closed(monkeypatch, change, reason):
    payload = copy.deepcopy(_payload())
    payload['streams'][0].update(change)
    _mock_probe(monkeypatch, payload)
    with pytest.raises(aligned.AlignmentUncertain, match=reason):
        aligned.probe_video(Path('synthetic.mp4'))


def test_missing_rotation_side_data_is_zero_without_a_display_matrix(monkeypatch):
    payload = _payload()
    payload['streams'][0].pop('side_data_list')
    _mock_probe(monkeypatch, payload)
    assert aligned.probe_video(Path('synthetic.mp4'))['rotation'] == 0
