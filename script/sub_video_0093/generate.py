#!/usr/bin/env python3
"""Verify and supplement only the presented 733-frame video_0093."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import tempfile
if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from script.sub_video import generate as legacy
from script.subvideo_pilot import aligned, geometry, pilot as base
from script.sub_video_all.generate import load_inputs
from script.sub_video_0093 import verification
PendingSource = legacy.PendingSource
SCHEMA="tensile-0093-supplement/1"

def code_identity():
    return verification._code()

def crop_video(roi_path: Path, output_path: Path, candidate: dict, roi_media: dict, source_proof: dict) -> dict:
    """Write an output only after independent, complete frame replay has passed."""
    verification.validate_source_receipt(source_proof, roi_path, candidate)
    fd, name = tempfile.mkstemp(prefix=".sub-video-", suffix=".mp4", dir=output_path.parent)
    os.close(fd)
    temporary = Path(name)
    temporary.unlink()
    try:
        base._checked(aligned.build_crop_command(roi_path, temporary, candidate))
        media = aligned.probe_video(temporary)
        if (media["total_frames"] != candidate["end_frame"] - candidate["start_frame"]
            or (media["width"], media["height"]) != (roi_media["width"], roi_media["height"])
            or media["duration"] < geometry.MIN_CANDIDATE_SECONDS - 1e-6):
            raise PendingSource("子视频帧数、分辨率或时长不符合窗口")
        proof = verification.verify_clip_replay(roi_path, temporary, candidate, roi_media, source_proof)
        digest = base.sha256_file(temporary)
        # Keep the document/source pins live through the final atomic publish.
        verification.validate_source_receipt(source_proof, roi_path, candidate)
        os.link(temporary, output_path)
        compact_media = {k: media[k] for k in ("duration", "total_frames", "fps", "width", "height", "time_base")}
        return {"sha256": digest, "media": compact_media, "full_decode": "passed", "frame_preserving_replay": proof,
                "frame_mapping": {"source_start_frame": candidate["start_frame"], "output_start_frame": 0,
                                  "anchors": proof["anchors"]}}
    finally:
        temporary.unlink(missing_ok=True)

def plan_windows(record: dict, media: dict):
    """Retain the old templates; decide guards on decoded PTS, not rounded labels."""
    windows, excluded = legacy.plan_windows(record, media)
    # geometry.add() compared four-decimal end_time to an unrounded guard,
    # erroneously removing exactly guard-aligned pre windows. Rebuild only these.
    windows = [w for w in windows if w["window_role"] != "pre_event"]
    excluded = [w for w in excluded if w["window_role"] != "pre_event"]
    times=media["timestamps"]; end_limit=times[record["event_frame"]]-.5
    virtual_end=record["event_frame"]/record["fps"]-.5
    strategy,targets=geometry._selected_pre_event_durations(record,virtual_end)
    positions=(0.,.5,1.) if strategy=="process_front_middle_back" else (1.,)
    seen=set()
    for target in targets:
        for position in positions:
            w=geometry._window_in_region(record,0.,virtual_end,target,position)
            if w is None:continue
            start,end=w["start_frame"],w["end_frame"]
            if (start,end) in seen:continue
            seen.add((start,end))
            end_pts=times[end] if end<len(times) else media["duration"]
            value=dict(w,window_role="pre_event",target_duration_seconds=target,
                duration_policy="standard",window_variant=(f"pre_event_{ {0.:'front',.5:'middle',1.:'back'}[position]}" if strategy=="process_front_middle_back" else strategy),
                event_position_ratio=None,event_kind="exact",source_frame_range=[start,end],
                start_time=times[start],end_time=end_pts,source_start_pts=times[start],source_end_pts=end_pts,
                duration=end_pts-times[start],source_duration=end_pts-times[start])
            if end_pts>end_limit+1e-9 or value["duration"]<1-1e-6:
                excluded.append(dict(value,reason="pre_window_crosses_real_pts_guard_or_too_short"))
            else:windows.append(value)
    return windows,excluded

def run(project_root: Path, output_dir: Path | None = None, *, plan_only=False, resume=False) -> dict:
    root=Path(project_root).resolve()
    output=Path(output_dir).resolve() if output_dir is not None else root/"data/sub_video/supplement_0093"
    parent_path=root/"data/sub_video/manifest.json"
    rows,rois,folds,hashes=load_inputs(root)
    row,roi=rows["video_0093"],rois["video_0093"]
    parent=base._load(parent_path)
    if any(c["source_video_id"]=="video_0093" for c in parent["candidates"]):
        raise base.PilotError("0093 already has parent candidates; refusing duplicate generation")
    if folds["video_0093"] != {str(i):"test" for i in range(3)}:
        raise base.PilotError("0093 is not the fixed test source")
    protected=[root/"data/videos",root/"data/roi",root/"data/splits",root/"script"]
    if output==root or output==parent_path.parent or (parent_path.parent/"videos") in output.parents or output==parent_path.parent/"videos" or any(output==p or p in output.parents or output in p.parents for p in protected):
        raise base.PilotError("output overlaps protected existing results or inputs")
    identity={"inputs":hashes,"parent_manifest_sha256":base.sha256_file(parent_path),"code":code_identity(),"policy":"presented_733_frames_727_728"}
    raw=root/"data/videos/video_0093.mp4";cropped=root/"data/roi/videos/video_0093.mp4"
    with base._run_lock(output):
        if output.exists():
            if not resume: raise base.PilotError("output exists; use resume")
            m=base._load(output/"manifest.json")
            if m.get("schema")!=SCHEMA or m.get("published") is not False:
                raise base.PilotError("0093 manifest schema or publication status changed")
            if m["identity"]!=identity:raise base.PilotError("resume identity changed")
            if len(m.get("sources",[]))!=1:raise base.PilotError("0093 resumed source inventory missing or duplicated")
        else:
            if resume:raise base.PilotError("missing output to resume")
            output.mkdir(parents=True)
            m={"schema":SCHEMA,"identity":identity,"sources":[],"candidates":[],"excluded_windows":[],"complete":False,"published":False}
        (output/"videos").mkdir(exist_ok=True)
        def save():
            base._atomic_json(output/"manifest.json",m)
            base._atomic_json(output/"summary.json",{"source_count":1,"source_status":m["sources"][0]["status"] if m["sources"] else "not_checked", "candidate_count":len(m["candidates"]),"cropped":sum(c["status"]=="cropped" for c in m["candidates"]),"complete":m["complete"],"published":False})
        if not m["sources"]:
            source={"video_id":"video_0093","scope":"test","folds":folds["video_0093"],"source_annotation":row}
            try:
                proof=verification.verify_source_replay(raw,cropped,roi,source_annotation=row)
                raw_media=aligned.probe_video(raw);roi_media=aligned.probe_video(cropped)
                windows,excluded=plan_windows(legacy.adapt_annotation(row,raw_media),raw_media)
                cs=legacy._name_candidates(windows,row,folds["video_0093"],proof["source_sha256"],proof["roi_sha256"])
                for c in cs:c.update(source_anchor_frames=[727,728],scope="test")
                m["candidates"]=cs;m["excluded_windows"]=excluded
                source.update(status="planned",frame_preserving_replay=proof,roi_media=roi_media)
            except (verification.ReplayUncertain,aligned.AlignmentUncertain,base.SkipSource) as exc:
                source.update(status="pending",reason=str(exc),details=getattr(exc,"details",{}))
            m["sources"].append(source);save()
        if len(m["sources"])!=1 or m["sources"][0].get("video_id")!="video_0093":
            raise base.PilotError("0093 source inventory changed")
        source=m["sources"][0]
        if source.get("source_annotation")!=row or source.get("scope")!="test" or source.get("folds")!=folds["video_0093"]:
            raise base.PilotError("0093 source annotation or test membership changed")
        if source["status"]=="planned":
            proof=source["frame_preserving_replay"]
            rec=dict(proof);seal=rec.pop("receipt_sha256",None)
            if (seal!=verification._digest(rec) or proof.get("code")!=code_identity()
                or proof.get("source_annotation")!=row or proof.get("source_sha256")!=base.sha256_file(raw)
                or proof.get("roi_sha256")!=base.sha256_file(cropped)
                or proof.get("roi_record_sha256")!=verification._digest(roi)):
                raise base.PilotError("0093 source proof changed")
            current_media=aligned.probe_video(raw)
            wm,em=plan_windows(legacy.adapt_annotation(row,current_media),current_media)
            expected=legacy._name_candidates(wm,row,folds["video_0093"],proof["source_sha256"],proof["roi_sha256"])
            for c in expected:c.update(source_anchor_frames=[727,728],scope="test")
            def fixed(c):return {k:v for k,v in c.items() if k not in {"status","output","reason"}}
            if ([fixed(c) for c in m["candidates"]]!=[fixed(c) for c in expected] or m["excluded_windows"]!=em):
                raise base.PilotError("0093 planned candidate inventory changed")
        elif m["candidates"]:
            raise base.PilotError("0093 unverified source has candidates")
        if not plan_only and source["status"]=="planned":
            for c in m["candidates"]:
                dest=output/c["output_path"]
                if c["status"]=="cropped":
                    if not dest.is_file() or base.sha256_file(dest)!=c["output"]["sha256"]:raise base.PilotError("recorded output changed")
                    cp=c["output"]["frame_preserving_replay"]; sealed=dict(cp); digest=sealed.pop("receipt_sha256",None)
                    if (digest!=verification._digest(sealed) or cp.get("status")!=verification.VERIFIED
                        or cp.get("source_receipt_sha256")!=source["frame_preserving_replay"]["receipt_sha256"]
                        or cp.get("output_sha256")!=c["output"]["sha256"]
                        or cp.get("window")!=verification.validate_source_receipt(source["frame_preserving_replay"],cropped,c)):
                        raise base.PilotError("0093 recorded clip proof changed")
                    info=verification._stream_info(dest);decoded=verification._decode_rgb(dest,info)
                    expected_anchors=[{"source_frame":i,"roi_frame":i,"output_frame":i-c["start_frame"]}
                        for i in c["source_anchor_frames"] if c["start_frame"]<=i<c["end_frame"]]
                    media=aligned.probe_video(dest)
                    if (cp.get("schema")!=verification.CLIP_SCHEMA or cp.get("code")!=code_identity()
                        or cp.get("toolchain")!=source["frame_preserving_replay"]["toolchain"]
                        or cp.get("decoded_frame_count")!=decoded["frame_count"]
                        or decoded["frame_count"]!=c["end_frame"]-c["start_frame"]
                        or cp.get("decoded_RGB_PTS_sequence_sha256")!=decoded["frame_sequence_sha256"]
                        or cp.get("anchors")!=expected_anchors
                        or c["output"].get("frame_mapping")!={"source_start_frame":c["start_frame"],"output_start_frame":0,"anchors":expected_anchors}
                        or c["output"].get("media")!={k:media[k] for k in ("duration","total_frames","fps","width","height","time_base")}):
                        raise base.PilotError("0093 recorded output decode or mapping changed")
                    continue
                if dest.exists():raise base.PilotError("unrecorded output exists")
                try:
                    result=crop_video(cropped,dest,c,source["roi_media"],source["frame_preserving_replay"])
                    try:
                        unchanged=(base.sha256_file(raw)==source["frame_preserving_replay"]["source_sha256"]
                            and base.sha256_file(cropped)==source["frame_preserving_replay"]["roi_sha256"]
                            and base.sha256_file(parent_path)==identity["parent_manifest_sha256"]
                            and all(base.sha256_file(root/p)==h for p,h in hashes.items())
                            and code_identity()==identity["code"])
                    except OSError:
                        unchanged=False
                    if not unchanged:
                        if dest.is_file() and base.sha256_file(dest)==result["sha256"]:dest.unlink()
                        raise base.PilotError("inputs changed during crop")
                    c.update(status="cropped",output=result)
                except (verification.ReplayUncertain,PendingSource) as exc:c.update(status="pending",reason=str(exc))
                save()
        if (base.sha256_file(parent_path)!=identity["parent_manifest_sha256"] or any(base.sha256_file(root/p)!=h for p,h in hashes.items()) or code_identity()!=identity["code"]):
            raise base.PilotError("inputs changed during run")
        m["complete"]=not plan_only and source["status"]=="planned" and bool(m["candidates"]) and all(c["status"]=="cropped" for c in m["candidates"])
        save();return m

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root",type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--plan-only",action="store_true");parser.add_argument("--resume",action="store_true")
    a=parser.parse_args();m=run(a.project_root,a.output_dir,plan_only=a.plan_only,resume=a.resume)
    print(base.canonical_bytes(m["sources"][0]).decode());return 0 if a.plan_only or m["complete"] else 2
if __name__=="__main__":raise SystemExit(main())
