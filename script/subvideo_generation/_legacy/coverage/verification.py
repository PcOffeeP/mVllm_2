"""Strict frame evidence for non-event coverage windows."""
from __future__ import annotations
from fractions import Fraction
from pathlib import Path
import tempfile
from script.subvideo_generation._legacy.core import verification as core, generate as labels
from script.subvideo_generation.pilot import pilot as base

SCHEMA = 'tensile-coverage-clip-replay/1'

def code():
    return {p.name:base.sha256_file(p) for p in sorted(Path(__file__).parent.glob('*.py'))}

def validate_source_receipt(proof, roi_path, candidate):
    receipt=dict(proof); seal=receipt.pop('receipt_sha256',None)
    if (proof.get('schema')!=core.SOURCE_SCHEMA or proof.get('status')!=core.VERIFIED
        or core._digest(receipt)!=seal):
        raise core.ReplayUncertain('coverage_source_proof_invalid')
    if (base.sha256_file(Path(proof['source_path']))!=proof['source_sha256']
        or base.sha256_file(roi_path)!=proof['roi_sha256']
        or candidate['source_sha256']!=proof['source_sha256'] or candidate['roi_sha256']!=proof['roi_sha256']
        or candidate['source_video_id']!=proof['video_id']
        or core._digest(proof['source_annotation'])!=proof['source_annotation_sha256']):
        raise core.ReplayUncertain('coverage_source_identity_mismatch')
    expected_name=f"{proof['video_id']}_coverage_{candidate.get('sequence',0):02d}"
    if (candidate.get('candidate_id')!=expected_name or candidate.get('filename')!=expected_name+'.mp4'
        or candidate.get('output_path')!='videos/'+expected_name+'.mp4'
        or candidate.get('source_labels')!=labels._source_labels(proof['source_annotation'])):
        raise core.ReplayUncertain('coverage_candidate_identity_or_source_labels_mismatch')
    if candidate.get('source_anchor_frames')!=[] or candidate.get('event_kind')!='none_unlocated':
        raise core.ReplayUncertain('coverage_must_not_invent_event')
    if (candidate.get('candidate_labels') is not None or candidate.get('final_labels') is not None
        or candidate.get('labels_status')!='unreviewed' or candidate.get('manual_review')!='required'):
        raise core.ReplayUncertain('coverage_requires_unassigned_human_labels')
    pts=[Fraction(t) for t in proof['source_decode']['normalized_pts']]
    end=Fraction(proof['source_decode']['usable_end']); bounds=pts+[end]
    count=len(pts)
    if not pts or end<=0: raise core.ReplayUncertain('coverage_empty_source')
    desired=[]
    if end<=20: desired=[(Fraction(0),end)]
    else:
        start=Fraction(0)
        while start+20<=end:
            desired.append((start,start+20));start+=15
        if desired[-1][1]!=end:desired.append((end-20,end))
    def nearest(t):return min(range(len(bounds)),key=lambda i:(abs(bounds[i]-t),i))
    ranges=[]
    for a,b in desired:
        pair=(nearest(a),count if b==end else nearest(b))
        if pair not in ranges and pair[0]<pair[1]:ranges.append(pair)
    start,stop=candidate['start_frame'],candidate['end_frame']
    if (type(start)is not int or type(stop)is not int or (start,stop) not in ranges
        or candidate.get('source_frame_range')!=[start,stop] or candidate.get('role')!='coverage'
        or candidate.get('sequence')!=ranges.index((start,stop))+1
        or candidate.get('target_duration_seconds')!=20 or candidate.get('step_seconds')!=15):
        raise core.ReplayUncertain('coverage_window_not_in_approved_schedule')
    for key,value in [('start_time',bounds[start]),('end_time',bounds[stop]),('source_start_pts',bounds[start]),('source_end_pts',bounds[stop]),('duration',bounds[stop]-bounds[start]),('source_duration',bounds[stop]-bounds[start])]:
        if abs(Fraction(str(candidate[key]))-value)>Fraction(1,1000000):raise core.ReplayUncertain('coverage_time_fields_mismatch')
    return {'source_frame_range':[start,stop],'source_start_pts':str(bounds[start]),'source_end_pts':str(bounds[stop]),
            'event_kind':'none_unlocated','source_anchor_frames':[],'target_duration_seconds':20,'step_seconds':15}

def verify_clip_replay(roi_path, output_path, candidate, roi_media, source_proof):
    roi_path,output_path=Path(roi_path),Path(output_path)
    identity=code(); candidate_sha=core._digest(candidate)
    window=validate_source_receipt(source_proof,roi_path,candidate)
    info=core._stream_info(output_path); decoded=core._decode_rgb(output_path,info); digest=base.sha256_file(output_path)
    start,end=window['source_frame_range']
    with tempfile.TemporaryDirectory(prefix='coverage-replay-') as tmp:
        reference=Path(tmp)/'reference.mp4';command=core.clip_reference_command(roi_path,reference,start,end);core._checked(command)
        ref_info=core._stream_info(reference);ref=core._decode_rgb(reference,ref_info)
        expected=[Fraction(t) for t in source_proof['roi_decode']['normalized_pts']][start:end]
        expected=[t-expected[0] for t in expected]
        if (base.sha256_file(reference)!=digest or info!=ref_info or decoded['frames']!=ref['frames']
            or decoded['frame_count']!=end-start or [Fraction(t) for t in decoded['normalized_pts']]!=expected
            or [info['width'],info['height']]!=[roi_media['width'],roi_media['height']]):
            raise core.ReplayUncertain('coverage_complete_RGB_PTS_or_file_mismatch')
    validate_source_receipt(source_proof,roi_path,candidate)
    if code()!=identity or core._digest(candidate)!=candidate_sha or base.sha256_file(output_path)!=digest:
        raise core.ReplayUncertain('coverage_identity_changed_during_check')
    return core._seal({'schema':SCHEMA,'status':core.VERIFIED,'proof_type':'independent_absolute_select_replay_of_trim_output',
        'source_receipt_sha256':source_proof['receipt_sha256'],'source_sha256':source_proof['source_sha256'],
        'roi_sha256':source_proof['roi_sha256'],'output_sha256':digest,'toolchain':source_proof['toolchain'],
        'code':source_proof['code'],'supplement_code':identity,'window':window,'decoded_frame_count':decoded['frame_count'],
        'decoded_RGB_PTS_sequence_sha256':decoded['frame_sequence_sha256'],'command':command,'anchors':[],
        'limitations':['no_inferred_event','not_human_label_review']})
