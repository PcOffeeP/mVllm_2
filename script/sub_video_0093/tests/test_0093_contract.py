"""Independent presented-frame checks using a real MP4 edit-list fixture."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from script.sub_video_0093 import verification as v, generate as g
from script.subvideo_pilot import aligned
from script.sub_video import generate as legacy


def encode(args):
    subprocess.run(args,check=True,capture_output=True)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def example(tmp_path,monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required for real synthetic media')
    # Only the installed-version boundary is simulated, all bytes/frames are real.
    monkeypatch.setattr(v,'_toolchain',lambda:{'synthetic_version_gate':'simulated'})
    full=tmp_path/'all771.mp4';raw=tmp_path/'source.mp4';roi=tmp_path/'roi.mp4'
    encode(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=32x32:rate=30',
            '-frames:v','771','-threads','1','-c:v','libx264','-g','1000','-keyint_min','1000',
            '-sc_threshold','0','-pix_fmt','yuv420p',str(full)])
    encode(['ffmpeg','-v','error','-ss','1.2666666667','-i',str(full),'-c','copy',str(raw)])
    filt='format=yuv444p,pad=36:34:2:1:color=black,setsar=1'
    encode(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-ignore_editlist','0','-threads','1','-i',str(raw),
            '-map','0:v:0','-vf',filt,'-vsync','0','-threads','2','-c:v','libx264','-preset','fast',
            '-crf','23','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(roi)])
    monkeypatch.setattr(v,'APPROVED_SOURCE_SHA256',sha(raw))
    row={'id':'video_0093','断裂状态':'发生断裂','断裂模式':'脆性断裂','断裂位置':'标距内',
         '断裂帧_前':'727','断裂帧_后':'728','断裂时间点':str(728/30),'视频帧率':'30',
         '异常_未夹紧':'否','异常_视频异常':'否','异常_爆炸性断裂':'否',
         '断裂时间范围_下界':'','断裂时间范围_上界':''}
    rec={'video_id':'video_0093','status':'success','source':{'sha256':sha(raw)},
         'decision':{'source_sha256':sha(raw),'mode':'no_crop','source_resolution':[32,32]},
         'output':{'sha256':sha(roi),'encoding':{'codec':'libx264','preset':'fast','crf':23,
                    'pixel_format':'yuv420p','audio':'dropped','frame_sync':'passthrough'},
                   'geometry':{'filter':filt,'pad_pixels':{'left':2,'right':2,'top':1,'bottom':1},
                               'crop_pixels':dict.fromkeys(('top','bottom','left','right'),0),
                               'output_resolution':[36,34]}}}
    return raw,roi,row,rec


def test_real_editlist_733_is_tail_of_771_and_keeps_original_metadata(example):
    raw,roi,row,rec=example; info=v._stream_info(raw)
    assert info['metadata_frame_count']==771
    before=copy.deepcopy(info)
    with pytest.raises(v.ReplayUncertain,match='metadata_frame_count'):
        v.decode_playback(raw,info)
    decoded=v.decode_playback(raw,info,allow_confirmed_preroll=True)
    assert info==before
    assert decoded['frame_count']==733
    assert decoded['presentation_evidence']['discarded_preroll_frames']==38
    assert decoded['normalized_pts'][727]=='727/30'
    assert decoded['normalized_pts'][728]=='364/15'


@pytest.mark.parametrize('change',['source_sha','id','frames'])
def test_exception_is_limited_to_bound_source_id_and_confirmed_frames(example,monkeypatch,change):
    raw,roi,row,rec=example
    if change=='source_sha':monkeypatch.setattr(v,'APPROVED_SOURCE_SHA256','0'*64)
    elif change=='id':row=dict(row,id='video_0092')
    else:row=dict(row,断裂帧_后='729')
    with pytest.raises(v.ReplayUncertain):v.verify_source_replay(raw,roi,rec,source_annotation=row)


@pytest.mark.parametrize('filt',['fps=15','reverse','format=yuv444p,pad=36:34:2:1:color=black,setpts=PTS/2,setsar=1'])
def test_time_filters_cannot_masquerade_as_static_padding(example,filt):
    raw,roi,row,rec=example;rec=copy.deepcopy(rec);rec['output']['geometry']['filter']=filt
    with pytest.raises(v.ReplayUncertain):v.source_command(raw,raw.parent/'ref.mp4',rec,v._stream_info(raw))


def test_strict_source_proof_accepts_true_preroll_and_rejects_wrong_roi_pixels(example):
    raw,roi,row,rec=example
    proof=v.verify_source_replay(raw,roi,rec,source_annotation=row)
    assert proof['status']==v.VERIFIED and proof['source_info']['metadata_frame_count']==771
    assert proof['source_decode']['frame_count']==proof['roi_decode']['frame_count']==733
    assert proof['source_annotation']==row
    bad=raw.parent/'bad.mp4'
    encode(['ffmpeg','-v','error','-i',str(roi),'-vf','negate','-vsync','0','-c:v','libx264',
            '-preset','fast','-crf','23','-pix_fmt','yuv420p','-an',str(bad)])
    bad_record=copy.deepcopy(rec);bad_record['output']['sha256']=sha(bad)
    with pytest.raises(v.ReplayUncertain):v.verify_source_replay(raw,bad,bad_record,source_annotation=row)


def test_clip_mapping_uses_presented_727_728_and_rejects_one_frame_shift(example,monkeypatch):
    raw,roi,row,rec=example;proof=v.verify_source_replay(raw,roi,rec,source_annotation=row)
    media=aligned.probe_video(raw);rm=aligned.probe_video(roi)
    windows,_=legacy.plan_windows(legacy.adapt_annotation(row,media),media)
    # The confirmed event is close to the end: old templates may have no event window.
    # Exercise the independent crop boundary with a valid interval that includes both anchors.
    start,end=660,733
    end_time=media['duration']
    window={'window_role':'transition','event_kind':'exact','start_frame':start,'end_frame':end,
            'source_frame_range':[start,end],'start_time':media['timestamps'][start],'end_time':end_time,
            'source_start_pts':media['timestamps'][start],'source_end_pts':end_time,
            'duration':end_time-media['timestamps'][start],'source_duration':end_time-media['timestamps'][start],
            'target_duration_seconds':2.0,'duration_policy':'standard','window_variant':None}
    c=legacy._name_candidates([window],row,{'0':'test','1':'test','2':'test'},sha(raw),sha(roi))[0]
    c.update(source_anchor_frames=[727,728],scope='test')
    target=raw.parent/'clip.mp4'; output=g.crop_video(roi,target,c,rm,proof)
    assert output['frame_preserving_replay']['anchors']==[
        {'source_frame':i,'roi_frame':i,'output_frame':i-c['start_frame']} for i in (727,728)]
    assert c['scope']=='test' and all(x=='test' for x in c['folds'].values())
    shifted=dict(c,start_frame=c['start_frame']-1,end_frame=c['end_frame']-1)
    wrong=raw.parent/'shifted.mp4'
    encode(aligned.build_crop_command(roi,wrong,shifted))
    with pytest.raises(v.ReplayUncertain):v.verify_clip_replay(roi,wrong,c,rm,proof)


def test_run_refuses_bad_roi_without_modifying_parent_or_inputs(example,monkeypatch,tmp_path):
    raw,roi,row,rec=example; root=tmp_path/'project';(root/'data/videos').mkdir(parents=True)
    (root/'data/roi/videos').mkdir(parents=True);(root/'data/sub_video').mkdir()
    shutil.copyfile(raw,root/'data/videos/video_0093.mp4');shutil.copyfile(roi,root/'data/roi/videos/video_0093.mp4')
    parent=root/'data/sub_video/manifest.json';parent.write_text(json.dumps({'candidates':[{'source_video_id':'video_0001','unchanged':True}]}))
    before=parent.read_bytes();original={str(p):sha(p) for p in (raw,roi)}
    monkeypatch.setattr(g,'load_inputs',lambda r:({'video_0093':row},{'video_0093':rec},{'video_0093':dict.fromkeys(('0','1','2'),'test')},{}))
    def reject(*a,**k):raise v.ReplayUncertain('source_replay_full_RGB_PTS_sequence_mismatch')
    monkeypatch.setattr(v,'verify_source_replay',reject)
    m=g.run(root)
    assert m['sources'][0]['status']=='pending' and m['candidates']==[] and not m['complete']
    assert not list((root/'data/sub_video/supplement_0093/videos').glob('*.mp4'))
    assert parent.read_bytes()==before and original=={str(p):sha(p) for p in (raw,roi)}


def test_presented_count_exception_does_not_accept_unedited_771(example):
    raw,roi,row,rec=example
    full=raw.parent/'all771.mp4'
    with pytest.raises(v.ReplayUncertain,match='presented_frame_count'):
        v.decode_playback(full,v._stream_info(full),allow_confirmed_preroll=True)


def test_full_run_adds_only_0093_test_outputs_and_preserves_existing_results(example,monkeypatch,tmp_path):
    raw,roi,row,rec=example;root=tmp_path/'full-project'
    (root/'data/videos').mkdir(parents=True);(root/'data/roi/videos').mkdir(parents=True)
    (root/'data/sub_video/videos').mkdir(parents=True)
    shutil.copyfile(raw,root/'data/videos/video_0093.mp4');shutil.copyfile(roi,root/'data/roi/videos/video_0093.mp4')
    parent=root/'data/sub_video/manifest.json';parent.write_text(json.dumps({'candidates':[{'source_video_id':'video_0001'}]}))
    sentinel=root/'data/sub_video/videos/old.mp4';sentinel.write_bytes(b'old verified output must survive')
    csv_path=root/'data/annotation-table-full.csv';csv_path.write_text('read-only synthetic annotation')
    hashes={'data/annotation-table-full.csv':sha(csv_path)}
    original={str(p):p.read_bytes() for p in (parent,sentinel,csv_path)}
    monkeypatch.setattr(g,'load_inputs',lambda r:({'video_0093':row},{'video_0093':rec},{'video_0093':dict.fromkeys(('0','1','2'),'test')},hashes))
    m=g.run(root)
    assert m['complete'] and m['candidates']
    assert {c['source_video_id'] for c in m['candidates']}=={'video_0093'}
    # The tail event cannot fit an old event template; don't force a shifted rupture window.
    assert {c['role'] for c in m['candidates']}=={'pre'}
    for c in m['candidates']:
        assert c['scope']=='test' and set(c['folds'].values())=={'test'}
        assert c['status']=='cropped' and c['manual_review']=='required' and c['final_labels'] is None
        assert sha(root/'data/sub_video/supplement_0093'/c['output_path'])==c['output']['sha256']
        assert c['output']['frame_preserving_replay']['status']==v.VERIFIED
    assert original=={str(p):p.read_bytes() for p in (parent,sentinel,csv_path)}
    again=g.run(root,resume=True)
    assert again==m
    with pytest.raises(Exception,match='output exists'):
        g.run(root)


def test_different_encoder_threads_cannot_pass_on_matching_pts_alone(example):
    raw,roi,row,rec=example;other=raw.parent/'different-threads.mp4'
    filt='format=yuv444p,pad=36:34:2:1:color=black,setsar=1'
    encode(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-ignore_editlist','0',
            '-threads','1','-i',str(raw),'-map','0:v:0','-vf',filt,'-vsync','0','-threads','1',
            '-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-an',
            '-movflags','+faststart',str(other)])
    assert sha(other)!=sha(roi), 'fixture must demonstrate distinct encoder output'
    left=v._decode_rgb(roi,v._stream_info(roi));right=v._decode_rgb(other,v._stream_info(other))
    assert left['normalized_pts']==right['normalized_pts'] and left['frame_count']==right['frame_count']==733
    changed=copy.deepcopy(rec);changed['output']['sha256']=sha(other)
    with pytest.raises(v.ReplayUncertain,match='SHA_mismatch'):
        v.verify_source_replay(raw,other,changed,source_annotation=row)


def test_precise_728_event_guard_avoids_rounded_display_seconds_rejection(example):
    raw,roi,row,rec=example;media=aligned.probe_video(raw)
    windows,excluded=g.plan_windows(legacy.adapt_annotation(row,media),media)
    pre=[w for w in windows if w['window_role']=='pre_event']
    assert {(w['start_frame'],w['end_frame']) for w in pre}=={(653,713),(563,713),(113,713)}
    assert not any(w['window_role'] in {'transition','post_event'} for w in windows)
    for window in pre:
        assert window['end_time'] <= media['timestamps'][728]-.5+1e-8


def _project(example,monkeypatch,tmp_path):
    raw,roi,row,rec=example;root=tmp_path/'resume-project'
    (root/'data/videos').mkdir(parents=True);(root/'data/roi/videos').mkdir(parents=True)
    (root/'data/sub_video/videos').mkdir(parents=True)
    shutil.copyfile(raw,root/'data/videos/video_0093.mp4');shutil.copyfile(roi,root/'data/roi/videos/video_0093.mp4')
    parent=root/'data/sub_video/manifest.json';parent.write_text(json.dumps({'candidates':[{'source_video_id':'video_0001'}]}))
    sentinel=root/'data/sub_video/videos/preserved.mp4';sentinel.write_bytes(b'preserved')
    monkeypatch.setattr(g,'load_inputs',lambda r:({'video_0093':row},{'video_0093':rec},{'video_0093':dict.fromkeys(('0','1','2'),'test')},{}))
    return root,parent,sentinel


@pytest.mark.parametrize('attack',['scope','folds','drop_candidate','drop_source','duplicate_source','frame','target','source_proof','schema','published'])
def test_resume_rejects_tampered_inventory_before_any_new_output(example,monkeypatch,tmp_path,attack):
    root,parent,sentinel=_project(example,monkeypatch,tmp_path)
    m=g.run(root,plan_only=True);out=root/'data/sub_video/supplement_0093';assert m['candidates']
    if attack=='schema':m['schema']='untrusted-schema'
    elif attack=='published':m['published']=True
    elif attack=='scope':m['candidates'][0]['scope']='development'
    elif attack=='folds':m['candidates'][0]['folds']['0']='train'
    elif attack=='drop_candidate':m['candidates'].pop()
    elif attack=='drop_source':m['sources']=[]
    elif attack=='duplicate_source':m['sources'].append(copy.deepcopy(m['sources'][0]))
    elif attack=='frame':m['candidates'][0]['start_frame']+=1;m['candidates'][0]['source_frame_range'][0]+=1
    elif attack=='target':m['candidates'][0]['target_duration_seconds']=999
    else:m['sources'][0]['frame_preserving_replay']['mapping']='wrong source frame'
    (out/'manifest.json').write_text(json.dumps(m))
    before={str(p):p.read_bytes() for p in (parent,sentinel)}
    def no_encode(*a,**k):raise AssertionError('tampered resume must be refused before crop')
    monkeypatch.setattr(g,'crop_video',no_encode)
    with pytest.raises(g.base.PilotError):g.run(root,resume=True)
    assert not list((out/'videos').glob('*.mp4'))
    assert before=={str(p):p.read_bytes() for p in (parent,sentinel)}


@pytest.mark.parametrize('attack',['anchors','decoded_digest','media','frame_mapping'])
def test_completed_resume_rejects_tampered_output_even_with_resealed_proof(example,monkeypatch,tmp_path,attack):
    root,parent,sentinel=_project(example,monkeypatch,tmp_path)
    m=g.run(root);assert m['complete'];out=root/'data/sub_video/supplement_0093'
    original={str(p):sha(p) for p in (out/'videos').glob('*.mp4')}
    c=m['candidates'][0];proof=c['output']['frame_preserving_replay']
    if attack=='anchors':proof['anchors']=[{'source_frame':727,'roi_frame':727,'output_frame':0}]
    elif attack=='decoded_digest':proof['decoded_RGB_PTS_sequence_sha256']='0'*64
    elif attack=='media':c['output']['media']['total_frames']=99999
    else:c['output']['frame_mapping']['source_start_frame']=99999
    if attack in {'anchors','decoded_digest'}:
        proof.pop('receipt_sha256');proof['receipt_sha256']=v._digest(proof)
    (out/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(g.base.PilotError):g.run(root,resume=True)
    assert original=={str(p):sha(p) for p in (out/'videos').glob('*.mp4')}


def test_loader_dependency_is_pinned_and_changes_invalidate_resume_and_proof(example,monkeypatch,tmp_path):
    loader=Path(g.load_inputs.__code__.co_filename).resolve()
    key='sub_video_all/generate.py'
    real_code=v._code()
    assert key in real_code and real_code[key]==sha(loader)
    root,parent,sentinel=_project(example,monkeypatch,tmp_path)
    m=g.run(root,plan_only=True);assert m['candidates']
    source=m['sources'][0];c=m['candidates'][0]
    changed=dict(real_code);changed[key]='f'*64
    monkeypatch.setattr(v,'_code',lambda:changed)
    with pytest.raises(g.base.PilotError,match='identity changed'):
        g.run(root,resume=True)
    with pytest.raises(v.ReplayUncertain,match='receipt_not_current'):
        v.validate_source_receipt(source['frame_preserving_replay'],root/'data/roi/videos/video_0093.mp4',c)
    assert not list((root/'data/sub_video/supplement_0093/videos').glob('*.mp4'))
