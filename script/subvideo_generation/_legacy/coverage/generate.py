#!/usr/bin/env python3
"""Append non-event 20-second coverage candidates without altering an existing batch."""
from __future__ import annotations
import argparse
from bisect import bisect_left
from collections import Counter
from fractions import Fraction
import csv
from pathlib import Path
import os
import sys
import tempfile
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[4]))
from script.subvideo_generation._legacy.all_sources import generate as inputs
from script.subvideo_generation._legacy.core import generate as labels, verification as core
from script.subvideo_generation.pilot import aligned, pilot as base
from script.subvideo_generation._legacy.coverage import verification
DEFAULT_IDS=tuple('video_'+x for x in ('0005','0015','0021','0034','0036','0042','0049','0050','0054','0056','0058','0064','0078','0087','0094','0096','0107'))
SCHEMA='tensile-sub-video-coverage/1'

def plan_windows(media):
    from script.subvideo_generation import rules
    window=rules.COVERAGE_WINDOW_SECONDS; step=rules.COVERAGE_STEP_SECONDS
    times=media['timestamps'];end=media['duration']; count=media['total_frames']
    if count!=len(times) or not times or end<=0 or times[0]!=0 or any(b<=a for a,b in zip(times,times[1:])) or end<=times[-1]:
        raise base.PilotError('invalid coverage playback timeline')
    desired=[]
    if end<=window:desired=[(0.,end)]
    else:
        start=0.
        while start+window<=end+1e-9:
            desired.append((start,min(start+window,end)));start+=step
        if abs(desired[-1][1]-end)>1e-9:desired.append((end-window,end))
    bounds=times+[end];windows=[];seen=set()
    def nearest(t):
        p=bisect_left(bounds,t); options=[i for i in (p-1,p) if 0<=i<len(bounds)]
        return min(options,key=lambda i:(abs(bounds[i]-t),i))
    for a,b in desired:
        start,stop=nearest(a),count if abs(b-end)<1e-9 else nearest(b)
        if start>=stop or (start,stop) in seen:continue
        seen.add((start,stop));duration=bounds[stop]-bounds[start]
        windows.append({'start_frame':start,'end_frame':stop,'source_frame_range':[start,stop],
            'start_time':bounds[start],'end_time':bounds[stop],'source_start_pts':bounds[start],'source_end_pts':bounds[stop],
            'duration':duration,'source_duration':duration,'target_duration_seconds':window,'step_seconds':step,
            'window_role':'coverage','event_kind':'none_unlocated','source_anchor_frames':[],
            'window_variant':'full_short_source' if end<window else 'tail_aligned' if abs(a-(len(windows)*step))>1e-9 else 'regular_stride'})
    # Overlapping strides leave no gaps; a stride wider than the window is a sparse
    # schedule by construction, so the gap clause only applies while step<=window.
    if (not windows or windows[0]['start_frame']!=0 or windows[-1]['end_frame']!=count
        or (step<=window and any(b['start_frame']>a['end_frame'] for a,b in zip(windows,windows[1:])))):
        raise base.PilotError('coverage has no complete decodable schedule')
    return windows

def crop_video(roi_path,output_path,candidate,roi_media,source_proof):
    verification.validate_source_receipt(source_proof,roi_path,candidate)
    fd,name=tempfile.mkstemp(prefix='.coverage-',suffix='.mp4',dir=output_path.parent);os.close(fd);temp=Path(name);temp.unlink()
    try:
        base._checked(aligned.build_crop_command(roi_path,temp,candidate))
        media=aligned.probe_video(temp)
        proof=verification.verify_clip_replay(roi_path,temp,candidate,roi_media,source_proof)
        result={'sha256':base.sha256_file(temp),'media':{k:media[k] for k in ('duration','total_frames','fps','width','height','time_base')},
                'full_decode':'passed','frame_preserving_replay':proof,'frame_mapping':{'source_start_frame':candidate['start_frame'],'output_start_frame':0,'anchors':[]}}
        verification.validate_source_receipt(source_proof,roi_path,candidate)
        os.link(temp,output_path)
        return result
    finally:temp.unlink(missing_ok=True)

def summarize(m):
    return {'scope':'coverage_supplement','source_count':len(m['sources']),'source_status':dict(Counter(s['status'] for s in m['sources'])),
            'source_reasons':dict(Counter(s['reason'] for s in m['sources'] if s.get('reason'))),
            'candidate_count':len(m['candidates']),'candidate_status':dict(Counter(c['status'] for c in m['candidates'])),
            'complete':m['complete'],'published':False,'manual_review':'required_for_every_publishable_clip',
            'split_counts':dict(Counter(c['scope'] for c in m['candidates']))}

def _verified_inputs(root):
    """Cross-check the shared loader against the actual fixed input files."""
    loader_code=inputs.orchestration_code()
    rows,rois,folds,hashes=inputs.load_inputs(root)
    split_dir=root/'data/splits/three-fold';lists={};independent_hashes={}
    for name in ['test.json']+[f'fold_{i}_{part}.json' for i in range(3) for part in ('train','val')]:
        path=split_dir/name;values=base._load(path).get('video_ids')
        if not isinstance(values,list) or not values or any(not isinstance(v,str) for v in values) or len(set(values))!=len(values):
            raise base.PilotError('invalid fixed split membership')
        lists[name]=set(values);independent_hashes[str(path.relative_to(root))]=base.sha256_file(path)
    test=lists['test.json'];dev=lists['fold_0_train.json']|lists['fold_0_val.json']
    vals=[lists[f'fold_{i}_val.json'] for i in range(3)]
    if (test&dev or sum(map(len,vals))!=len(dev) or set.union(*vals)!=dev
        or any(lists[f'fold_{i}_train.json']&vals[i] or lists[f'fold_{i}_train.json']|vals[i]!=dev for i in range(3))):
        raise base.PilotError('fixed split partition conflict')
    universe=test|dev;independent_folds={key:{str(i):'test' if key in test else 'val' if key in vals[i] else 'train' for i in range(3)} for key in universe}
    independent_rows={}
    annotation=root/'data/annotation-table-full.csv'
    with annotation.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            key=row.get('id')
            if key not in universe or key in independent_rows:raise base.PilotError('annotation inventory mismatch')
            independent_rows[key]=row
    roi_path=root/'data/roi/manifest.json';independent_rois={}
    for row in base._load(roi_path)['videos']:
        key=row.get('video_id')
        if key not in universe or key in independent_rois:raise base.PilotError('ROI inventory mismatch')
        independent_rois[key]=row
    for path in (annotation,roi_path):independent_hashes[str(path.relative_to(root))]=base.sha256_file(path)
    if (set(independent_rows)!=universe or set(independent_rois)!=universe or rows!=independent_rows
        or rois!=independent_rois or folds!=independent_folds or hashes!=independent_hashes):
        raise base.PilotError('input loader disagrees with actual annotation, ROI or fixed split files')
    return rows,rois,folds,hashes,loader_code

def _check_parent_membership(parent_data,folds,selected,loader_code):
    sources={source['video_id']:source for source in parent_data['sources']}
    if len(sources)!=len(parent_data['sources']):raise base.PilotError('duplicate parent sources')
    parent_code=parent_data.get('identity',{}).get('orchestration_code')
    if parent_code is not None and parent_code!=loader_code:raise base.PilotError('input loader differs from parent batch identity')
    for key in selected:
        if key not in sources:raise base.PilotError('supplement source missing from parent')
        expected_scope='test' if folds[key]['0']=='test' else 'development'
        if ('folds' in sources[key] and sources[key]['folds']!=folds[key]) or ('scope' in sources[key] and sources[key]['scope']!=expected_scope):
            raise base.PilotError('parent membership differs from fixed splits')
    return sources

def run(project_root,output_dir=None,*,plan_only=False,resume=False,source_ids=DEFAULT_IDS):
    root=Path(project_root).resolve(); output=Path(output_dir) if output_dir is not None else root/'data/sub_video/supplement'
    if not output.is_absolute():output=root/output
    output=output.resolve(); parent=root/'data/sub_video/manifest.json'
    selected=tuple(source_ids)
    if not selected or len(set(selected))!=len(selected) or not set(selected)<=set(DEFAULT_IDS):raise base.PilotError('unapproved or duplicate supplement sources')
    protected=[root/'data/videos',root/'data/roi',root/'data/splits',root/'script',root/'docs',parent.parent/'videos']
    if output==root or output==parent.parent or any(output==p or p in output.parents or output in p.parents for p in protected):raise base.PilotError('unsafe supplement output path')
    rows,rois,folds,hashes,loader_code=_verified_inputs(root)
    parent_data=base._load(parent);parent_sources=_check_parent_membership(parent_data,folds,selected,loader_code)
    if not set(selected)<=set(parent_sources) or any(c['source_video_id'] in selected for c in parent_data['candidates']):raise base.PilotError('source absent from parent or already has parent candidates')
    parent_inputs=parent_data.get('identity',{}).get('inputs',{})
    if any(k in parent_inputs and parent_inputs[k]!=v for k,v in hashes.items()):
        raise base.PilotError('current metadata differs from parent batch inputs')
    if any('source_annotation' in parent_sources[k] and parent_sources[k]['source_annotation']!=rows[k] for k in selected):
        raise base.PilotError('current source annotation differs from parent batch')
    hashes['data/sub_video/manifest.json']=base.sha256_file(parent)
    identity={'schema':SCHEMA,'inputs':hashes,'code':verification.code(),'media_code':core._code(),'loader_code':loader_code,'source_ids':sorted(selected),
              'window_seconds':20,'step_seconds':15,'parent_manifest_sha256':hashes['data/sub_video/manifest.json']}
    def unchanged():
        return all((root/p).is_file() and base.sha256_file(root/p)==sha for p,sha in hashes.items()) and verification.code()==identity['code'] and core._code()==identity['media_code'] and inputs.orchestration_code()==identity['loader_code']
    with base._run_lock(output):
        if output.exists():
            if not resume:raise base.PilotError('supplement output exists; use explicit resume')
            m=base._load(output/'manifest.json')
            if m.get('identity')!=identity:raise base.PilotError('supplement resume identity differs')
        else:
            if resume:raise base.PilotError('cannot resume missing supplement')
            output.mkdir(parents=True);m={'schema':SCHEMA,'identity':identity,'sources':[],'candidates':[],'complete':False,'published':False}
        (output/'videos').mkdir(exist_ok=True)
        def save():
            base._atomic_json(output/'manifest.json',m);base._atomic_json(output/'summary.json',summarize(m))
        save();known={s['video_id'] for s in m['sources']}
        for key in sorted(set(selected)-known):
            row,roi=rows[key],rois[key];source={'video_id':key,'source_annotation':row,'folds':folds[key],'scope':'test' if folds[key]['0']=='test' else 'development'}
            try:
                if not unchanged():raise base.PilotError('supplement inputs or loader changed before source validation')
                raw=root/'data/videos'/(key+'.mp4');cropped=root/'data/roi/videos'/(key+'.mp4')
                if roi.get('status')!='success':raise core.ReplayUncertain('ROI_not_available')
                raw_media,roi_media=aligned.probe_video(raw),aligned.probe_video(cropped)
                proof=core.verify_source_replay(raw,cropped,roi,source_annotation=row)
                if raw_media['total_frames']!=roi_media['total_frames']:raise core.ReplayUncertain('source_ROI_frame_count_mismatch')
                windows=plan_windows(raw_media)
                source.update(status='planned',source_path=str(raw.relative_to(root)),roi_path=str(cropped.relative_to(root)),source_sha256=proof['source_sha256'],roi_sha256=proof['roi_sha256'],roi_media=roi_media,frame_preserving_replay=proof)
                for sequence,w in enumerate(windows,1):
                    name=f'{key}_coverage_{sequence:02d}'
                    m['candidates'].append(dict(w,candidate_id=name,filename=name+'.mp4',source_video_id=key,scope=source['scope'],folds=folds[key],
                        role='coverage',sequence=sequence,output_path=f'videos/{name}.mp4',source_sha256=proof['source_sha256'],roi_sha256=proof['roi_sha256'],
                        source_labels=labels._source_labels(row),candidate_labels=labels.candidate_labels(row,'coverage'),final_labels=None,labels_status='unreviewed',manual_review='required',
                        review={'status':'未审核','decision':None,'change_notes':''},status='planned'))
            except (core.ReplayUncertain,aligned.AlignmentUncertain,FileNotFoundError) as e:source.update(status='pending',reason=str(e))
            except (base.PilotError,KeyError,TypeError,ValueError,OSError) as e:source.update(status='failed',reason=f'{type(e).__name__}: {e}')
            m['sources'].append(source);save()
        source_map={s['video_id']:s for s in m['sources']}
        if len(source_map)!=len(m['sources']) or set(source_map)!=set(selected):
            raise base.PilotError('supplement source inventory differs from requested sources')
        expected_candidates={}
        for key,s in source_map.items():
            scope='test' if folds[key]['0']=='test' else 'development'
            if s.get('folds')!=folds[key] or s.get('scope')!=scope or s.get('source_annotation')!=rows[key]:
                raise base.PilotError('supplement source membership or annotation mismatch')
            if s['status']!='planned':continue
            if s.get('source_path')!='data/videos/'+key+'.mp4' or s.get('roi_path')!='data/roi/videos/'+key+'.mp4':
                raise base.PilotError('supplement source paths mismatch')
            current=aligned.probe_video(root/s['source_path'])
            for sequence,w in enumerate(plan_windows(current),1):
                expected_candidates[f'{key}_coverage_{sequence:02d}']=(key,sequence,w)
        if len(m['candidates'])!=len(expected_candidates) or {c['candidate_id'] for c in m['candidates']}!=set(expected_candidates):
            raise base.PilotError('supplement candidate inventory mismatch')
        for c in m['candidates']:
            key,sequence,w=expected_candidates[c['candidate_id']];s=source_map[key]
            if (c.get('scope')!=s['scope'] or c.get('folds')!=folds[key] or c.get('sequence')!=sequence
                or any(c.get(k)!=v for k,v in w.items())):
                raise base.PilotError('supplement candidate membership or schedule mismatch')
            verification.validate_source_receipt(s['frame_preserving_replay'],root/s['roi_path'],c)
        admitted={s['video_id']:s for s in m['sources'] if s['status']=='planned'}
        if not unchanged():raise base.PilotError('supplement inputs or loader changed before generation')
        if not plan_only:
            for c in m['candidates']:
                destination=output/c['output_path']
                if c['status']=='cropped':
                    if not destination.is_file() or base.sha256_file(destination)!=c['output']['sha256']:raise base.PilotError('recorded supplement output missing or changed')
                    continue
                if destination.exists():raise base.PilotError('unrecorded output exists; refusing overwrite')
                s=admitted[c['source_video_id']]
                try:
                    if not unchanged():raise base.PilotError('supplement inputs or loader changed before crop')
                    result=crop_video(root/s['roi_path'],destination,c,s['roi_media'],s['frame_preserving_replay'])
                    try:
                        stable=(unchanged() and base.sha256_file(root/s['source_path'])==s['source_sha256']
                                and base.sha256_file(root/s['roi_path'])==s['roi_sha256'])
                    except OSError:
                        stable=False
                    if not stable:
                        if destination.is_file() and base.sha256_file(destination)==result['sha256']:destination.unlink()
                        raise base.PilotError('supplement inputs changed during crop')
                    c.update(status='cropped',output=result);c.pop('reason',None)
                except (core.ReplayUncertain,aligned.AlignmentUncertain) as e:c.update(status='pending',reason=str(e))
                except (base.PilotError,OSError,ValueError) as e:c.update(status='failed',reason=f'{type(e).__name__}: {e}')
                save()
        for s in admitted.values():
            if base.sha256_file(root/s['source_path'])!=s['source_sha256'] or base.sha256_file(root/s['roi_path'])!=s['roi_sha256']:raise base.PilotError('supplement media changed')
        if not unchanged():raise base.PilotError('supplement inputs/code changed')
        m['plan_only']=bool(plan_only);m['complete']=not plan_only and all(s['status']=='planned' for s in m['sources']) and all(c['status']=='cropped' for c in m['candidates']);save();return m

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[4]);parser.add_argument('--output-dir',type=Path);parser.add_argument('--plan-only',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    try:m=run(args.project_root,args.output_dir,plan_only=args.plan_only,resume=args.resume)
    except (base.PilotError,OSError,ValueError,KeyError) as e:parser.exit(1,str(e)+'\n')
    print(base.canonical_bytes(summarize(m)).decode(),end='');return 0 if args.plan_only or m['complete'] else 2
if __name__=='__main__':raise SystemExit(main())


def audit_outputs(project_root, output_dir):
    """Check historical receipts against current bytes after relocation; do not rewrite receipts."""
    root,out=Path(project_root).resolve(),Path(output_dir).resolve()
    m=base._load(out/'manifest.json');rows,rois,folds,_,loader_code=_verified_inputs(root)
    if loader_code!=m['identity'].get('loader_code'):raise base.PilotError('supplement audit loader identity mismatch')
    _check_parent_membership(base._load(root/'data/sub_video/manifest.json'),folds,m['identity']['source_ids'],loader_code)
    for name,sha in m['identity']['inputs'].items():
        if base.sha256_file(root/name)!=sha:raise base.PilotError('relocated supplement input identity mismatch')
    selected=set(m['identity']['source_ids']);sources={s['video_id']:s for s in m['sources']}
    if set(sources)!=selected or len(sources)!=len(m['sources']):raise base.PilotError('supplement source inventory mismatch')
    expected={}
    for key,s in sources.items():
        scope='test' if folds[key]['0']=='test' else 'development'
        if s['folds']!=folds[key] or s['scope']!=scope or s['source_annotation']!=rows[key]:raise base.PilotError('supplement source membership/annotation mismatch')
        if s['status']!='planned':continue
        raw,cropped=root/s['source_path'],root/s['roi_path']
        proof=s['frame_preserving_replay'];sealed=dict(proof);seal=sealed.pop('receipt_sha256',None)
        if (core._digest(sealed)!=seal or proof['schema']!=core.SOURCE_SCHEMA or proof['status']!=core.VERIFIED
            or proof['source_annotation']!=rows[key] or proof['source_annotation_sha256']!=core._digest(rows[key])
            or proof['roi_record_sha256']!=core._digest(rois[key])
            or base.sha256_file(raw)!=proof['source_sha256'] or base.sha256_file(cropped)!=proof['roi_sha256']):
            raise base.PilotError('supplement source historical proof mismatch')
        current_media=aligned.probe_video(raw)
        bound_pts=[Fraction(t) for t in proof['source_decode']['normalized_pts']]
        if (len(bound_pts)!=len(current_media['timestamps'])
            or any(abs(t-Fraction(str(actual)))>Fraction(1,1000000) for t,actual in zip(bound_pts,current_media['timestamps']))
            or abs(Fraction(proof['source_decode']['usable_end'])-Fraction(str(current_media['duration'])))>Fraction(1,1000000)):
            raise base.PilotError('supplement bound source timeline differs from current media')
        for sequence,w in enumerate(plan_windows(current_media),1):
            expected[f'{key}_coverage_{sequence:02d}']=(key,sequence,w)
    if len(m['candidates'])!=len(expected) or {c['candidate_id'] for c in m['candidates']}!=set(expected):raise base.PilotError('supplement candidate inventory mismatch')
    checked=0
    for c in m['candidates']:
        key,sequence,w=expected[c['candidate_id']];s=sources[key];source=s['frame_preserving_replay']
        if any(c.get(k)!=v for k,v in w.items()) or c['sequence']!=sequence or c['folds']!=folds[key] or c['scope']!=s['scope']:
            raise base.PilotError('supplement candidate window/membership mismatch')
        if (c['source_labels']!=labels._source_labels(rows[key]) or c['candidate_labels']!=labels.candidate_labels(rows[key],'coverage') or c['final_labels'] is not None
            or c['labels_status']!='unreviewed' or c['manual_review']!='required' or c['role']!='coverage'
            or c['filename']!=c['candidate_id']+'.mp4' or c['output_path']!='videos/'+c['filename']):raise base.PilotError('supplement candidate label/identity mismatch')
        if c['status']!='cropped':continue
        o=c['output'];clip=o['frame_preserving_replay'];sealed=dict(clip);seal=sealed.pop('receipt_sha256',None)
        source_pts=[Fraction(t) for t in source['source_decode']['normalized_pts']]
        source_end=Fraction(source['source_decode']['usable_end'])
        start,stop=c['start_frame'],c['end_frame']
        expected_window={'source_frame_range':[start,stop],'source_start_pts':str(source_pts[start]),
                         'source_end_pts':str(source_pts[stop] if stop<len(source_pts) else source_end),
                         'event_kind':'none_unlocated','source_anchor_frames':[],
                         'target_duration_seconds':20,'step_seconds':15}

        media=out/c['output_path'];info=core._stream_info(media);decoded=core._decode_rgb(media,info);actual=aligned.probe_video(media)
        if (core._digest(sealed)!=seal or clip['schema']!=verification.SCHEMA or clip['status']!=core.VERIFIED
            or clip['source_receipt_sha256']!=source['receipt_sha256'] or clip['source_sha256']!=source['source_sha256']
            or clip['roi_sha256']!=source['roi_sha256'] or clip['code']!=source['code'] or clip['toolchain']!=source['toolchain']
            or clip['window']!=expected_window or clip['anchors']!=[]
            or c['source_sha256']!=source['source_sha256'] or c['roi_sha256']!=source['roi_sha256']
            or clip.get('supplement_code')!=m['identity']['code'] or source['code']!=m['identity']['media_code']
            or base.sha256_file(media)!=clip['output_sha256'] or o['sha256']!=clip['output_sha256']
            or decoded['frame_sequence_sha256']!=clip['decoded_RGB_PTS_sequence_sha256'] or decoded['frame_count']!=c['end_frame']-c['start_frame']
            or clip['decoded_frame_count']!=decoded['frame_count']
            or o['media']!={k:actual[k] for k in ('duration','total_frames','fps','width','height','time_base')}
            or o['frame_mapping']!={'source_start_frame':c['start_frame'],'output_start_frame':0,'anchors':[]}):raise base.PilotError('supplement output historical proof mismatch')
        checked+=1
    disk={str(p.relative_to(out)) for p in (out/'videos').glob('*.mp4')};recorded={c['output_path'] for c in m['candidates'] if c['status']=='cropped'}
    if disk!=recorded:raise base.PilotError('supplement output files missing or unrecorded')
    if inputs.orchestration_code()!=loader_code:raise base.PilotError('input loader changed during audit')
    if any(base.sha256_file(root/name)!=sha for name,sha in m['identity']['inputs'].items()):raise base.PilotError('supplement inputs changed during audit')
    return {'status':'historical_evidence_matches_current_bytes','verified_outputs':checked,'limitations':['not_new_frame_replay','not_human_label_review']}
