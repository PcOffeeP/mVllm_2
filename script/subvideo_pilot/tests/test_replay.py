"""Synthetic exact replay evidence and independently selected clip checks."""
import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from subvideo_pilot import aligned, replay


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def media(tmp_path, monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required')
    source, roi = tmp_path/'source.mp4', tmp_path/'roi.mp4'
    frames = np.random.default_rng(121).integers(20,230,(60,4,6,3),dtype=np.uint8).repeat(16,1).repeat(16,2)
    subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
                    '-s','96x64','-r','10','-i','-','-c:v','libx264','-pix_fmt','yuv420p',str(source)],
                   input=frames.tobytes(),check=True)
    # Expected ROI uses a separately written fixed command, not source_command().
    subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-i',str(source),'-map','0:v:0',
                    '-vf','crop=64:48:2:4,setsar=1','-vsync','0','-c:v','libx264','-preset','fast','-crf','23',
                    '-pix_fmt','yuv420p','-an','-movflags','+faststart',str(roi)],check=True)
    record={'video_id':'video_0001','source':{'sha256':sha(source)},
            'decision':{'source_sha256':sha(source),'mode':'fixed_roi','source_resolution':[96,64],
                        'pixel_box':{'x':2,'y':4,'width':64,'height':48}},
            'output':{'sha256':sha(roi),'encoding':{'video_codec':'libx264','preset':'fast','crf':23,
                        'pixel_format':'yuv420p','audio':'dropped','frame_sync':'vsync_0_passthrough'},
                      'geometry':{'filter':'crop=64:48:2:4,setsar=1',
                                  'effective_pixel_box':{'x':2,'y':4,'width':64,'height':48},
                                  'pad_pixels':{'left':0,'right':0,'top':0,'bottom':0},'output_resolution':[64,48]}}}
    annotation={'id':'video_0001','断裂状态':'发生断裂','断裂帧_前':'29','断裂帧_后':'30','断裂时间点':'3',
                '异常_未夹紧':'否','异常_视频异常':'否','异常_爆炸性断裂':'否'}
    # The native test runner is not 4.4.2. Only this prerequisite is simulated;
    # all actual synthetic encoding, decoding, frame/PTS and SHA checks execute.
    monkeypatch.setattr(replay,'_toolchain',lambda:{'synthetic_runtime_gate':'4.4.2 prerequisite simulated'})
    return source,roi,record,annotation


def test_source_replay_and_independent_clip_select_match_complete_sequences(media,tmp_path):
    source,roi,record,annotation=media
    proof=replay.verify_source_replay(source,roi,record,source_annotation=annotation)
    assert proof['status']==replay.VERIFIED
    assert proof['source_decode']['frame_count']==proof['roi_decode']['frame_count']==60
    assert proof['reference_sha256']==sha(roi)
    candidate={'source_video_id':'video_0001','start_frame':10,'end_frame':50,'source_frame_range':[10,50],
               'source_anchor_frames':[29,30],'event_kind':'exact','window_role':'transition',
               'source_sha256':sha(source),'roi_sha256':sha(roi)}
    output=tmp_path/'clip.mp4'
    subprocess.run(aligned.build_crop_command(roi,output,candidate),check=True)
    receipt=replay.verify_clip_replay(roi,output,candidate,{'width':64,'height':48},proof)
    assert receipt['status']==replay.VERIFIED
    assert receipt['decoded_frame_count']==40
    assert receipt['anchors'][1]['output_frame']==20
    assert 'select=' in receipt['command'][receipt['command'].index('-vf')+1]
    assert sha(output)==receipt['output_sha256']


def test_replay_rejects_temporal_filter_and_changed_input_pin(media):
    source,roi,record,annotation=media
    bad=copy.deepcopy(record); bad['output']['geometry']['filter']='crop=64:48:2:4,reverse,setsar=1'
    with pytest.raises(replay.ReplayUncertain,match='whitelist'):
        replay.verify_source_replay(source,roi,bad,source_annotation=annotation)
    bad=copy.deepcopy(record); bad['decision']['source_sha256']='0'*64
    with pytest.raises(replay.ReplayUncertain,match='identity'):
        replay.verify_source_replay(source,roi,bad,source_annotation=annotation)


def test_clip_replay_checks_annotation_guard_before_reference_generation(media,tmp_path):
    source,roi,record,annotation=media
    proof=replay.verify_source_replay(source,roi,record,source_annotation=annotation)
    candidate={'source_video_id':'video_0001','start_frame':30,'end_frame':60,'source_frame_range':[30,60],
               'source_anchor_frames':[29,30],'event_kind':'exact','window_role':'post_event',
               'source_sha256':sha(source),'roi_sha256':sha(roi)}
    with pytest.raises(replay.ReplayUncertain,match='post_guard'):
        replay.verify_clip_replay(roi,tmp_path/'not-created.mp4',candidate,{'width':64,'height':48},proof)
