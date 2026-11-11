"""Coverage-window behavior using only tiny temporary synthetic videos."""
import csv
import json
from pathlib import Path
import shutil
import pytest
from script.sub_video import verification as core
from script.sub_video.tests.test_generation_contract import annotation, digest, encode, media
from script.sub_video.tests.test_unclamped_contract import anchor_document


def generator():
    from script.sub_video_supplement import generate
    return generate


@pytest.mark.parametrize('seconds,expected', [(.5,[(0,.5)]),(19,[(0,19)]),(20,[(0,20)]),(21,[(0,20),(1,21)]),(35,[(0,20),(15,35)]),(36,[(0,20),(15,35),(16,36)]),(40,[(0,20),(15,35),(20,40)]),(45,[(0,20),(15,35),(25,45)]),(50,[(0,20),(15,35),(30,50)])])
def test_requested_stride_and_full_tail(seconds,expected):
    description=media(count=round(seconds*10),fps=10)
    windows=generator().plan_windows(description)
    assert [(w['start_frame']/10,w['end_frame']/10) for w in windows]==expected
    assert len({tuple(w['source_frame_range']) for w in windows})==len(windows)
    assert windows[0]['start_frame']==0
    assert windows[-1]['end_frame']==description['total_frames']
    assert all(a['end_frame']>=b['start_frame'] for a,b in zip(windows,windows[1:]))


def test_nonuniform_pts_define_window_boundaries():
    description=media(count=400,fps=10)
    description.update(timestamps=[i*.1+(.007 if i%2 else 0) for i in range(400)],duration=40.)
    windows=generator().plan_windows(description)
    assert windows[-1]['end_frame']==400 and windows[-1]['end_time']==40.
    for w in windows:
        assert w['start_time']==description['timestamps'][w['start_frame']]
        assert abs(w['end_time']-w['start_time']-20)<.11


@pytest.fixture
def project(tmp_path,monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg needed')
    monkeypatch.setattr(core,'_toolchain',lambda:{'synthetic_version_gate':'simulated'})
    root=tmp_path/'project';split=root/'data/splits/three-fold';split.mkdir(parents=True)
    dev=['video_0015','video_0021','video_0034'];ids=dev+['video_0005']
    (split/'test.json').write_text(json.dumps({'video_ids':['video_0005']}))
    for i in range(3):
        for part,values in [('val',[dev[i]]),('train',[v for v in dev if v!=dev[i]])]:
            (split/f'fold_{i}_{part}.json').write_text(json.dumps({'video_ids':values}))
    rows=[annotation(v,断裂状态='无法确定',断裂模式='无法确定',断裂位置='无法确定',断裂帧_前='无',断裂帧_后='无',断裂时间点='',异常_视频异常='是') for v in ids]
    with (root/'data/annotation-table-full.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    source=tmp_path/'source.mp4';roi=tmp_path/'roi.mp4'
    encode(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=10','-t','6','-threads','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
    encode(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-i',str(source),'-map','0:v:0','-vf','crop=64:48:2:4,setsar=1','-vsync','0','-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(roi)])
    records=[]
    for v in ids:
        for directory,origin in [('data/videos',source),('data/roi/videos',roi)]:
            dest=root/directory/(v+'.mp4');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,dest)
        records.append({'video_id':v,'status':'success','source':{'sha256':digest(source)},'decision':{'source_sha256':digest(source),'mode':'fixed_roi','source_resolution':[96,64],'pixel_box':{'x':2,'y':4,'width':64,'height':48}},'output':{'sha256':digest(roi),'encoding':{'video_codec':'libx264','preset':'fast','crf':23,'pixel_format':'yuv420p','audio':'dropped','frame_sync':'vsync_0_passthrough'},'geometry':{'filter':'crop=64:48:2:4,setsar=1','effective_pixel_box':{'x':2,'y':4,'width':64,'height':48},'pad_pixels':{'left':0,'right':0,'top':0,'bottom':0},'output_resolution':[64,48]}}})
    (root/'data/roi/manifest.json').write_text(json.dumps({'videos':records}))
    anchor_document(root/'docs/subvideo-current-logic.md')
    parent=root/'data/sub_video';(parent/'videos').mkdir(parents=True)
    from script.sub_video_all import generate as all_sources
    _,_,memberships,input_hashes=all_sources.load_inputs(root)
    input_hashes['docs/subvideo-current-logic.md']=digest(root/'docs/subvideo-current-logic.md')
    (parent/'manifest.json').write_text(json.dumps({'identity':{'inputs':input_hashes,'code':core._code(),'orchestration_code':all_sources.orchestration_code()},'sources':[{'video_id':v,'status':'pending','folds':memberships[v],'scope':'test' if v=='video_0005' else 'development','source_annotation':next(r for r in rows if r['id']==v)} for v in ids],'candidates':[]}))
    (parent/'summary.json').write_text('{"untouched":true}')
    (parent/'audit.json').write_text('{"untouched":true}')
    (parent/'videos/old_keep.mp4').write_bytes(b'existing-result-do-not-change')
    return root


def snapshot(root):
    paths=[root/'data/annotation-table-full.csv',root/'docs/subvideo-current-logic.md']
    paths+=list((root/'data/splits/three-fold').glob('*.json'))+list((root/'data/sub_video').glob('*.json'))+list((root/'data/sub_video/videos').glob('*'))
    return {str(p.relative_to(root)):p.read_bytes() for p in paths}


def test_real_outputs_preserve_parent_partition_and_original_unknown_labels(project):
    g=generator();root=project;before=snapshot(root)
    result=g.run(root,source_ids=['video_0015','video_0005']);out=root/'data/sub_video/supplement'
    assert snapshot(root)==before
    assert {s['video_id'] for s in result['sources']}=={'video_0015','video_0005'}
    assert len(result['candidates'])==2
    for c in result['candidates']:
        assert c['status']=='cropped' and c['role']=='coverage'
        assert c['candidate_labels'] is None and c['final_labels'] is None
        assert c['manual_review']=='required' and c['labels_status']=='unreviewed'
        assert c['source_labels']['断裂状态']=='无法确定'
        assert c['source_labels']['异常情况']['视频异常']=='是'
        assert c['event_kind']=='none_unlocated'
        assert c['source_frame_range']==[0,60]
        assert c['start_time']==0 and c['end_time']==pytest.approx(6.)
        assert c['output']['media']['total_frames']==60
        assert digest(out/c['output_path'])==c['output']['sha256']
        assert c['output']['frame_preserving_replay']['status']==core.VERIFIED
        if c['source_video_id']=='video_0005':assert set(c['folds'].values())=={'test'}
        else:assert list(c['folds'].values()).count('train')==2
    assert len(list((out/'videos').glob('*.mp4')))==2
    assert json.loads((out/'manifest.json').read_text())==result
    assert result['published'] is False


@pytest.mark.parametrize('change',['parent','csv','split'])
def test_resume_rejects_changed_inputs(project,change):
    g=generator();root=project;out=root/'data/sub_video/supplement'
    g.run(root,plan_only=True,source_ids=['video_0015'])
    paths={'parent':root/'data/sub_video/manifest.json','csv':root/'data/annotation-table-full.csv','split':root/'data/splits/three-fold/fold_0_train.json'}
    p=paths[change];p.write_bytes(p.read_bytes()+b'\n')
    with pytest.raises(Exception):g.run(root,resume=True,source_ids=['video_0015'])
    assert not list((out/'videos').glob('*.mp4'))


def test_source_already_in_parent_cannot_be_generated_again(project):
    root=project;p=root/'data/sub_video/manifest.json';m=json.loads(p.read_text());m['candidates']=[{'source_video_id':'video_0015'}];p.write_text(json.dumps(m))
    with pytest.raises(Exception):generator().run(root,source_ids=['video_0015'])
    assert (root/'data/sub_video/videos/old_keep.mp4').read_bytes()==b'existing-result-do-not-change'


def test_existing_output_is_not_overwritten(project):
    g=generator();r=g.run(project,source_ids=['video_0015']);dest=project/'data/sub_video/supplement'/r['candidates'][0]['output_path'];b=dest.read_bytes()
    with pytest.raises(Exception):g.run(project,source_ids=['video_0015'])
    assert dest.read_bytes()==b


def test_source_proof_failure_cannot_generate_output(project,monkeypatch):
    def reject(*a,**kw):raise core.ReplayUncertain('injected_source_proof_failure')
    monkeypatch.setattr(core,'verify_source_replay',reject)
    r=generator().run(project,source_ids=['video_0015'])
    assert not any(c['status']=='cropped' for c in r['candidates'])
    assert not list((project/'data/sub_video/supplement/videos').glob('*.mp4'))


def refresh_parent_input_identity(root):
    # Fixture construction happens before generation; bind its final media metadata.
    from script.sub_video_all import generate as all_sources
    _,_,_,hashes=all_sources.load_inputs(root)
    hashes['docs/subvideo-current-logic.md']=digest(root/'docs/subvideo-current-logic.md')
    p=root/'data/sub_video/manifest.json';m=json.loads(p.read_text());m['identity']['inputs']=hashes;p.write_text(json.dumps(m))


def replace_media(root,tmp_path,video_id,*,short=False,seconds="6"):
    source=tmp_path/('source-short.mp4' if short else 'source-vfr.mp4');roi=tmp_path/('roi-short.mp4' if short else 'roi-vfr.mp4')
    cmd=['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=10','-t',('0.5' if short else seconds)]
    encode(cmd+['-threads','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
    encode(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-i',str(source),'-map','0:v:0','-vf','crop=64:48:2:4,setsar=1','-vsync','0','-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(roi)])
    shutil.copyfile(source,root/'data/videos'/f'{video_id}.mp4');shutil.copyfile(roi,root/'data/roi/videos'/f'{video_id}.mp4')
    path=root/'data/roi/manifest.json';data=json.loads(path.read_text());record=next(r for r in data['videos'] if r['video_id']==video_id)
    record['source']['sha256']=record['decision']['source_sha256']=digest(source);record['output']['sha256']=digest(roi);path.write_text(json.dumps(data));refresh_parent_input_identity(root)


def test_actual_subsecond_source_is_kept_whole(project,tmp_path):
    replace_media(project,tmp_path,'video_0015',short=True)
    result=generator().run(project,source_ids=['video_0015'])
    assert len(result['candidates'])==1
    c=result['candidates'][0]
    assert c['status']=='cropped' and c['source_frame_range']==[0,5]
    assert c['output']['media']['duration']==pytest.approx(.5)


def test_actual_nonuniform_source_keeps_all_decoded_frames(project,tmp_path):
    # Nonuniform frame PTS are retained through both actual media proofs.
    source=tmp_path/'nonuniform.mp4';roi=tmp_path/'nonuniform-roi.mp4'
    encode(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=10','-t','6','-vf',"settb=1/1000,setpts='N*100+if(eq(mod(N,2),1),20,0)'",'-fps_mode','vfr','-enc_time_base','1:1000','-threads','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
    encode(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-i',str(source),'-map','0:v:0','-vf','crop=64:48:2:4,setsar=1','-vsync','0','-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(roi)])
    shutil.copyfile(source,project/'data/videos/video_0015.mp4');shutil.copyfile(roi,project/'data/roi/videos/video_0015.mp4')
    p=project/'data/roi/manifest.json';d=json.loads(p.read_text());r=next(x for x in d['videos'] if x['video_id']=='video_0015');r['source']['sha256']=r['decision']['source_sha256']=digest(source);r['output']['sha256']=digest(roi);p.write_text(json.dumps(d));refresh_parent_input_identity(project)
    from script.subvideo_pilot import aligned
    src=aligned.probe_video(source);intervals=[round(b-a,3) for a,b in zip(src['timestamps'],src['timestamps'][1:])]
    assert len(set(intervals))>1,'test must actually encode nonuniform PTS'
    result=generator().run(project,source_ids=['video_0015']);c=result['candidates'][0]
    assert c['status']=='cropped' and c['end_frame']==src['total_frames']
    assert c['output']['frame_preserving_replay']['decoded_frame_count']==src['total_frames']


def test_independent_select_rejects_actual_wrong_frame_trim(project,monkeypatch):
    from script.subvideo_pilot import aligned
    original=aligned.build_crop_command
    def wrong(roi,path,candidate):
        changed=dict(candidate,start_frame=candidate['start_frame']+1,end_frame=candidate['end_frame']-1)
        return original(roi,path,changed)
    monkeypatch.setattr(aligned,'build_crop_command',wrong)
    r=generator().run(project,source_ids=['video_0015'])
    assert r['candidates'][0]['status'] in {'pending','failed'}
    assert not list((project/'data/sub_video/supplement/videos').glob('*.mp4'))


@pytest.mark.parametrize('field,value',[('source_anchor_frames',[3]),('event_kind','exact'),('candidate_labels',{'断裂状态':'未断裂'})])
def test_coverage_verifier_rejects_invented_event_or_labels(project,field,value):
    g=generator();r=g.run(project,plan_only=True,source_ids=['video_0015']);c=r['candidates'][0];s=r['sources'][0]
    c[field]=value
    from script.sub_video_supplement import verification as v
    with pytest.raises(core.ReplayUncertain):v.validate_source_receipt(s['frame_preserving_replay'],project/s['roi_path'],c)


def test_real_long_source_covers_start_stride_and_tail(project,tmp_path):
    replace_media(project,tmp_path,'video_0015',seconds='36')
    result=generator().run(project,source_ids=['video_0015'])
    assert [(c['start_frame'],c['end_frame']) for c in result['candidates']]==[(0,200),(150,350),(160,360)]
    assert all(c['status']=='cropped' and c['output']['media']['total_frames']==200 for c in result['candidates'])
    assert len({c['output_path'] for c in result['candidates']})==3


def test_changed_live_roi_is_not_treated_as_verified(project):
    path=project/'data/roi/videos/video_0015.mp4';path.write_bytes(path.read_bytes()+b'changed')
    result=generator().run(project,source_ids=['video_0015'])
    assert not any(c['status']=='cropped' for c in result['candidates'])
    assert not list((project/'data/sub_video/supplement/videos').glob('*.mp4'))


@pytest.mark.parametrize('where,field',[('sources','scope'),('sources','folds'),('candidates','scope'),('candidates','folds')])
def test_resume_cannot_turn_test_supplement_into_train(project,where,field):
    g=generator();before=snapshot(project);r=g.run(project,plan_only=True,source_ids=['video_0005'])
    target=r[where][0];target[field]='development' if field=='scope' else {'0':'train','1':'train','2':'train'}
    path=project/'data/sub_video/supplement/manifest.json';path.write_text(json.dumps(r))
    try:
        result=g.run(project,resume=True,source_ids=['video_0005'])
    except Exception:
        result=None
    assert not list((project/'data/sub_video/supplement/videos').glob('*.mp4'))
    assert result is None or not any(c['status']=='cropped' for c in result['candidates'])
    assert snapshot(project)==before


@pytest.mark.parametrize('damage',['drop_candidate','duplicate_candidate','change_window','drop_source','duplicate_source'])
def test_resume_rejects_incomplete_or_replaced_window_inventory(project,damage):
    g=generator();before=snapshot(project);r=g.run(project,plan_only=True,source_ids=['video_0015'])
    if damage=='drop_candidate':r['candidates']=[]
    elif damage=='duplicate_candidate':r['candidates'].append(dict(r['candidates'][0]))
    elif damage=='change_window':
        c=r['candidates'][0];c['start_frame']=1;c['source_frame_range'][0]=1;c['start_time']=.1;c['duration']=5.9
    elif damage=='drop_source':r['sources']=[]
    elif damage=='duplicate_source':r['sources'].append(dict(r['sources'][0]))
    p=project/'data/sub_video/supplement/manifest.json';p.write_text(json.dumps(r))
    with pytest.raises(Exception):g.run(project,resume=True,source_ids=['video_0015'])
    assert not list((project/'data/sub_video/supplement/videos').glob('*.mp4'))
    assert snapshot(project)==before


def test_relocated_audit_uses_current_bytes_and_redecodes_every_output(project,tmp_path,monkeypatch):
    g=generator();r=g.run(project,source_ids=['video_0015','video_0005'])
    moved=tmp_path/'relocated';shutil.copytree(project,moved)
    project.rename(tmp_path/'historical-path-unavailable')
    assert not project.exists()
    original=core._decode_rgb;decoded=[]
    def observe(path,info):
        if '/supplement/videos/' in str(path):decoded.append(str(path))
        return original(path,info)
    monkeypatch.setattr(core,'_decode_rgb',observe)
    result=g.audit_outputs(moved,moved/'data/sub_video/supplement')
    assert result['verified_outputs']==len(r['candidates'])==len(decoded)
    persisted=json.loads((moved/'data/sub_video/supplement/manifest.json').read_text())
    assert persisted==r,'migration audit must preserve original sealed proof data'


@pytest.mark.parametrize('damage',['scope','labels','drop_candidate','duplicate_source','mapping','roi'])
def test_relocated_audit_refuses_scope_label_inventory_or_media_tampering(project,damage):
    g=generator();r=g.run(project,source_ids=['video_0005']);c=r['candidates'][0];out=project/'data/sub_video/supplement'
    if damage=='scope':c['scope']='development'
    elif damage=='labels':c['candidate_labels']={'断裂状态':'未断裂'}
    elif damage=='drop_candidate':r['candidates']=[]
    elif damage=='duplicate_source':r['sources'].append(dict(r['sources'][0]))
    elif damage=='mapping':c['output']['frame_mapping']['source_start_frame']=1
    elif damage=='roi':
        p=project/'data/roi/videos/video_0005.mp4';p.write_bytes(p.read_bytes()+b'changed')
    (out/'manifest.json').write_text(json.dumps(r))
    with pytest.raises(Exception):g.audit_outputs(project,out)


@pytest.mark.parametrize('field,value',[('source_start_pts','1/10'),('source_end_pts','59/10'),('target_duration_seconds',21),('step_seconds',16),('source_anchor_frames',[3]),('event_kind','exact')])
def test_audit_refuses_resealed_clip_window_contract_tampering(project,field,value):
    g=generator();r=g.run(project,source_ids=['video_0015']);clip=r['candidates'][0]['output']['frame_preserving_replay']
    clip['window'][field]=value
    clip['receipt_sha256']=core._digest({k:v for k,v in clip.items() if k!='receipt_sha256'})
    out=project/'data/sub_video/supplement';(out/'manifest.json').write_text(json.dumps(r))
    with pytest.raises(Exception):g.audit_outputs(project,out)


@pytest.mark.parametrize('field,value',[('window_variant','fabricated_tail'),('target_duration_seconds',19),('step_seconds',14)])
def test_audit_refuses_candidate_policy_tampering(project,field,value):
    g=generator();r=g.run(project,source_ids=['video_0015']);r['candidates'][0][field]=value
    out=project/'data/sub_video/supplement';(out/'manifest.json').write_text(json.dumps(r))
    with pytest.raises(Exception):g.audit_outputs(project,out)


@pytest.mark.parametrize('phase',['plan','resume','audit'])
def test_untrusted_loader_cannot_relabel_fixed_test_as_train(project,monkeypatch,phase):
    g=generator();out=project/'data/sub_video/supplement'
    if phase=='resume':g.run(project,plan_only=True,source_ids=['video_0005'])
    if phase=='audit':g.run(project,source_ids=['video_0005'])
    original=g.inputs.load_inputs
    def corrupted(root):
        rows,rois,folds,hashes=original(root)
        folds['video_0005']={'0':'train','1':'train','2':'train'}
        return rows,rois,folds,hashes
    monkeypatch.setattr(g.inputs,'load_inputs',corrupted)
    before=snapshot(project)
    with pytest.raises(Exception):
        if phase=='audit':g.audit_outputs(project,out)
        else:g.run(project,plan_only=phase=='plan',resume=phase=='resume',source_ids=['video_0005'])
    assert snapshot(project)==before
    if phase!='audit':assert not list((out/'videos').glob('*.mp4'))


@pytest.mark.parametrize('phase',['plan','resume','audit'])
def test_changed_loader_source_identity_is_refused(project,monkeypatch,phase):
    g=generator();out=project/'data/sub_video/supplement'
    if phase=='resume':g.run(project,plan_only=True,source_ids=['video_0015'])
    if phase=='audit':g.run(project,source_ids=['video_0015'])
    original=g.base.sha256_file
    loader=Path(g.inputs.__file__).resolve()
    def changed(path):
        return '0'*64 if Path(path).resolve()==loader else original(path)
    monkeypatch.setattr(g.base,'sha256_file',changed)
    before=snapshot(project)
    with pytest.raises(Exception):
        if phase=='audit':g.audit_outputs(project,out)
        else:g.run(project,plan_only=phase=='plan',resume=phase=='resume',source_ids=['video_0015'])
    assert snapshot(project)==before
    if phase!='audit':assert not list((out/'videos').glob('*.mp4'))


@pytest.mark.parametrize('field',['scope','folds'])
def test_parent_membership_cannot_contradict_fixed_split_files(project,field):
    g=generator();parent=project/'data/sub_video/manifest.json';m=json.loads(parent.read_text());s=next(s for s in m['sources'] if s['video_id']=='video_0005')
    s[field]='development' if field=='scope' else {'0':'train','1':'train','2':'train'};parent.write_text(json.dumps(m))
    before=snapshot(project)
    with pytest.raises(Exception):g.run(project,source_ids=['video_0005'])
    assert snapshot(project)==before
    assert not list((project/'data/sub_video/supplement/videos').glob('*.mp4'))
