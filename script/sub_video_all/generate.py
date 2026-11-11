#!/usr/bin/env python3
"""Generate every fixed source once, preserving development/test and fold membership."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import csv
from pathlib import Path
import os
import sys
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from script.sub_video import generate as legacy, anchors, verification
from script.subvideo_pilot import pilot as base, aligned
PendingSource = legacy.PendingSource
adapt_annotation = legacy.adapt_annotation
plan_windows = legacy.plan_windows
_present = legacy._present
SCHEMA = "tensile-all-source-sub-video/1"

def orchestration_code():
    return {p.name: base.sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))}

def load_inputs(project_root: Path):
    root = Path(project_root).resolve()
    dev_rows, dev_rois, folds, hashes = base.load_inputs(root)
    payload = base._load(root / "data/splits/three-fold/test.json")
    test_ids = payload["video_ids"]
    if (not test_ids or len(set(test_ids)) != len(test_ids)
        or set(test_ids) & set(dev_rows)):
        raise base.PilotError("invalid or overlapping fixed test members")
    expected = set(dev_rows) | set(test_ids)
    rows = {}
    with (root / "data/annotation-table-full.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row.get("id")
            if key not in expected or key in rows:
                raise base.PilotError("duplicate or unexpected source annotation")
            rows[key] = row
    roi_rows = {}
    for row in base._load(root / "data/roi/manifest.json")["videos"]:
        key = row.get("video_id")
        if key not in expected or key in roi_rows:
            raise base.PilotError("duplicate or unexpected ROI record")
        roi_rows[key] = row
    if set(rows) != expected or set(roi_rows) != expected:
        raise base.PilotError("complete source/ROI annotation coverage mismatch")
    for key in test_ids:
        folds[key] = {str(i): "test" for i in range(3)}
    return rows, roi_rows, folds, hashes

def _sealed(receipt, schema):
    if not isinstance(receipt, dict):
        raise ReuseError("missing reuse proof")
    value = dict(receipt)
    seal = value.pop("receipt_sha256", None)
    if (receipt.get("schema") != schema or receipt.get("status") != verification.VERIFIED
        or seal != verification._digest(value) or receipt.get("code") != verification._code()
        or receipt.get("toolchain") != verification._toolchain()):
        raise ReuseError("reuse proof seal, code or toolchain mismatch")

class ReuseError(base.PilotError):
    pass

class ReuseIndex:
    """Validate historical records; never relabel their sealed proof as new evidence."""
    def __init__(self, manifests=(), input_hashes=None):
        self.sources = {}
        self._media_cache = {}
        self.candidates = {}
        self.manifests = []
        for entry in manifests:
            path = Path(entry).resolve()
            data = base._load(path)
            ident = data.get("identity", {})
            if data.get("schema") != legacy.SCHEMA or ident.get("code") != verification._code():
                raise ReuseError("reuse manifest schema or media code mismatch")
            if input_hashes is not None and ident.get("inputs") != input_hashes:
                raise ReuseError("reuse metadata input identity mismatch")
            digest = base.sha256_file(path)
            self.manifests.append((path, digest))
            sources = {}
            for source in data["sources"]:
                key = source["video_id"]
                if key in sources:
                    raise ReuseError("duplicate donor source")
                sources[key] = source
                if source.get("status") == "planned":
                    self.sources.setdefault(key, []).append((source, path, digest))
            seen = set()
            for candidate in data["candidates"]:
                key = candidate["candidate_id"]
                if key in seen:
                    raise ReuseError("duplicate donor candidate")
                seen.add(key)
                if candidate.get("status") == "cropped":
                    source = sources.get(candidate["source_video_id"])
                    if not source or source.get("status") != "planned":
                        raise ReuseError("cropped donor has no admitted source")
                    self.candidates.setdefault(key, []).append((candidate, source, path, digest))
    def proof_for_receipt(self, digest):
        for records in self.sources.values():
            for source, _, _ in records:
                proof = source["frame_preserving_replay"]
                if proof["receipt_sha256"] == digest:
                    return copy.deepcopy(proof)
        raise ReuseError("unknown historical source proof")
    def check_manifests(self):
        if any(not p.is_file() or base.sha256_file(p) != digest for p, digest in self.manifests):
            raise ReuseError("reuse manifest changed during run")
    @staticmethod
    def _source(source, row, roi, raw, cropped):
        proof = source["frame_preserving_replay"]
        _sealed(proof, verification.SOURCE_SCHEMA)
        if (source.get("source_annotation") != row
            or proof.get("source_annotation") != row
            or proof.get("source_annotation_sha256") != verification._digest(row)
            or proof.get("video_id") != row["id"]
            or proof.get("source_sha256") != base.sha256_file(raw)
            or proof.get("roi_sha256") != base.sha256_file(cropped)
            or proof.get("roi_record_sha256") != verification._digest(roi)
            or proof.get("decision_sha256") != verification._digest(roi.get("decision", {}))
            or proof.get("source_sha256") != base.sha256_file(Path(proof["source_path"]))):
            raise ReuseError("reuse source identity mismatch")
        verification._validate_phenomenon_anchor(proof.get("phenomenon_anchor"), row,
            proof["source_sha256"], proof["source_decode"]["frame_count"])
        return proof
    def source_proof(self, video_id, row, roi, raw, cropped):
        self.check_manifests()
        records = self.sources.get(video_id, [])
        if not records:
            return None
        proof = self._source(records[0][0], row, roi, raw, cropped)
        if proof.get("phenomenon_anchor"):
            for path, _ in self.manifests:
                identity = base._load(path)["identity"]
                if proof["phenomenon_anchor"]["document_sha256"] != identity["inputs"].get(anchors.DOCUMENT):
                    raise ReuseError("reuse anchor does not match input document")
        return copy.deepcopy(proof)
    def adopt(self, expected, destination, *, row, roi_path, roi_record, validate_only=False):
        self.check_manifests()
        records = self.candidates.get(expected["candidate_id"], [])
        if not records:
            return None
        checked = []
        ignore = {"status", "output", "reason", "scope"}
        def comparable(item):
            value = {k:copy.deepcopy(v) for k,v in item.items() if k not in ignore}
            if isinstance(value.get("phenomenon_anchor"), dict):
                value["phenomenon_anchor"].pop("document_path", None)
            return value
        for candidate, source, manifest_path, digest in records:
            # Complete candidate metadata (including labels and frame parameters) must agree.
            if comparable(candidate) != comparable(expected):
                raise ReuseError("reuse candidate conflicts with current planned window or labels")
            proof = self._source(source, row, roi_record,
                                 Path(source["frame_preserving_replay"]["source_path"]), roi_path)
            window = verification.validate_source_receipt(proof, roi_path, candidate)
            output = candidate["output"]
            receipt = output["frame_preserving_replay"]
            _sealed(receipt, verification.CLIP_SCHEMA)
            relative = Path(candidate["output_path"])
            if relative.is_absolute() or relative.parts != ("videos", candidate["filename"]):
                raise ReuseError("unsafe donor output path")
            media = manifest_path.parent / relative
            if not media.is_file() or media.is_symlink():
                raise ReuseError("donor output missing or symlinked")
            actual_sha = base.sha256_file(media)
            expected_anchors = [{"source_frame":i,"roi_frame":i,"output_frame":i-candidate["start_frame"]}
                for i in candidate["source_anchor_frames"] if candidate["start_frame"] <= i < candidate["end_frame"]]
            if (actual_sha != output["sha256"] or actual_sha != receipt.get("output_sha256")
                or receipt.get("source_receipt_sha256") != proof["receipt_sha256"]
                or receipt.get("source_sha256") != proof["source_sha256"]
                or receipt.get("roi_sha256") != proof["roi_sha256"]
                or receipt.get("window") != window or receipt.get("anchors") != expected_anchors
                or receipt.get("decoded_frame_count") != candidate["end_frame"]-candidate["start_frame"]
                or output.get("full_decode") != "passed" or output.get("frame_mapping",{}).get("anchors") != expected_anchors):
                raise ReuseError("reuse clip proof/input/output mapping mismatch")
            if actual_sha not in self._media_cache:
                actual_media = aligned.probe_video(media)
                actual_decode = verification._decode_rgb(media, verification._stream_info(media))
                self._media_cache[actual_sha] = (
                    {k:actual_media[k] for k in ("duration", "total_frames", "fps", "width", "height", "time_base")},
                    actual_decode["frame_sequence_sha256"], actual_decode["frame_count"])
            expected_media, sequence_sha, decoded_count = self._media_cache[actual_sha]
            if (output.get("media") != expected_media
                or sequence_sha != receipt.get("decoded_RGB_PTS_sequence_sha256")
                or decoded_count != receipt.get("decoded_frame_count")
                or output.get("frame_mapping", {}).get("source_start_frame") != candidate["start_frame"]
                or output.get("frame_mapping", {}).get("output_start_frame") != 0):
                raise ReuseError("reuse media properties, decoded frames or frame mapping mismatch")
            checked.append((media, actual_sha, output, proof, manifest_path, digest))
        if len({item[1] for item in checked}) != 1:
            raise ReuseError("same candidate ID has conflicting donor media")
        media, sha, output, proof, manifest_path, digest = checked[0]
        original_candidate = records[0][0]
        self.check_manifests()
        if validate_only:
            return copy.deepcopy(output)
        os.link(media, destination)  # no encoding, no overwriting
        try:
            if base.sha256_file(destination) != sha:
                raise ReuseError("reuse media changed during linking")
            verification.validate_source_receipt(proof, roi_path, original_candidate)
            self.check_manifests()
        except BaseException:
            if destination.is_file() and base.sha256_file(destination) == sha:
                destination.unlink()
            raise
        result = copy.deepcopy(output)
        result["reuse_provenance"] = {"manifest_path":str(manifest_path),"manifest_sha256":digest,
            "media_path":str(media), "source_receipt_sha256":proof["receipt_sha256"],
            "policy":"verified_original_bytes_and_unmodified_original_receipts"}
        return result

def summarize(manifest):
    result = {"scope":"all_sources", "source_count":len(manifest["sources"]),
        "source_status":dict(Counter(s["status"] for s in manifest["sources"])),
        "source_reasons":dict(Counter(s["reason"] for s in manifest["sources"] if s.get("reason"))),
        "candidate_count":len(manifest["candidates"]),
        "candidate_status":dict(Counter(c["status"] for c in manifest["candidates"])),
        "roles":dict(Counter(c["role"] for c in manifest["candidates"])),
        "excluded_windows":len(manifest["excluded_windows"]), "complete":manifest["complete"],
        "published":False, "manual_review":"required_for_every_publishable_clip"}
    result["reused_candidates"] = sum("reuse_provenance" in c.get("output",{}) for c in manifest["candidates"])
    result["split_counts"] = {scope:sum(c["scope"]==scope for c in manifest["candidates"]) for scope in ("development","test")}
    result["fold_counts"] = {str(i):{part:sum(c["folds"][str(i)]==part for c in manifest["candidates"]) for part in ("train","val","test")} for i in range(3)}
    return result
def _logical_candidate(item):
    value = {k:copy.deepcopy(v) for k,v in item.items() if k not in {"status", "output", "reason"}}
    if isinstance(value.get("phenomenon_anchor"), dict):
        value["phenomenon_anchor"].pop("document_path", None)
    return value

def audit_outputs(project_root: Path, output_dir: Path) -> dict:
    """Bind unchanged historical sealed receipts to current project bytes, without rewriting them."""
    root, output = Path(project_root).resolve(), Path(output_dir).resolve()
    manifest = base._load(output / "manifest.json")
    rows, rois, folds, hashes = load_inputs(root)
    document = root / anchors.DOCUMENT
    if document.is_file():
        hashes[anchors.DOCUMENT] = base.sha256_file(document)
    if hashes != manifest["identity"]["inputs"]:
        raise ReuseError("relocated metadata identity mismatch")
    sources = {s["video_id"]:s for s in manifest["sources"]}
    if len(sources) != len(manifest["sources"]) or set(sources) != set(rows):
        raise ReuseError("completed source inventory missing, duplicated or unexpected")
    candidates = manifest["candidates"]
    if (len({c["candidate_id"] for c in candidates}) != len(candidates)
        or len({c["output_path"] for c in candidates}) != len(candidates)):
        raise ReuseError("completed candidate IDs or paths duplicated")
    for key, source in sources.items():
        expected_scope = "test" if folds[key]["0"] == "test" else "development"
        if source.get("scope") != expected_scope or source.get("folds") != folds[key] or source.get("source_annotation") != rows[key]:
            raise ReuseError("completed source membership or annotation mismatch")
    verified = 0
    expected_candidates = {}
    current_anchors = anchors.load_anchors(document) if document.is_file() else {}
    for key, source_record in sources.items():
        if source_record["status"] != "planned":
            continue
        raw_path = root / "data/videos" / (key+".mp4")
        source_media = aligned.probe_video(raw_path)
        record = adapt_annotation(rows[key], source_media, current_anchors.get(key))
        windows, _ = plan_windows(record, source_media)
        planned = legacy._name_candidates(windows, rows[key], folds[key],
            base.sha256_file(raw_path), base.sha256_file(root / "data/roi/videos" / (key+".mp4")))
        for entry in planned:
            entry["source_anchor_frames"] = record["anchor_frames"]
            entry["scope"] = "test" if folds[key]["0"] == "test" else "development"
        expected_candidates[key] = {entry["candidate_id"]:entry for entry in planned}
    expected_ids = set().union(*(set(value) for value in expected_candidates.values())) if expected_candidates else set()
    if expected_ids != {c["candidate_id"] for c in candidates}:
        raise ReuseError("candidate inventory does not cover the planned source windows")
    for candidate in manifest["candidates"]:
        if candidate["status"] != "cropped":
            continue
        output_record = candidate["output"]
        clip = output_record["frame_preserving_replay"]
        receipt_sha = clip["source_receipt_sha256"]
        source = manifest.get("source_receipts", {}).get(receipt_sha)
        if source is None:
            source = sources[candidate["source_video_id"]]["frame_preserving_replay"]
        for receipt, schema in ((source, verification.SOURCE_SCHEMA), (clip, verification.CLIP_SCHEMA)):
            raw = dict(receipt); seal = raw.pop("receipt_sha256", None)
            if receipt.get("schema") != schema or receipt.get("status") != verification.VERIFIED or seal != verification._digest(raw):
                raise ReuseError("historical receipt seal mismatch")
        key = candidate["source_video_id"]
        expected_candidate = expected_candidates[key].get(candidate["candidate_id"])
        if expected_candidate is None or _logical_candidate(expected_candidate) != _logical_candidate(candidate):
            raise ReuseError("completed candidate metadata differs from current independently planned window")
        relative = Path(candidate["output_path"])
        if relative.parts != ("videos", candidate["filename"]):
            raise ReuseError("unsafe completed output path")
        media = output / relative
        actual = aligned.probe_video(media)
        decoded = verification._decode_rgb(media, verification._stream_info(media))
        if (output_record.get("media") != {k:actual[k] for k in ("duration", "total_frames", "fps", "width", "height", "time_base")}
            or decoded["frame_sequence_sha256"] != clip["decoded_RGB_PTS_sequence_sha256"]
            or decoded["frame_count"] != clip["decoded_frame_count"]
            or output_record["frame_mapping"]["source_start_frame"] != candidate["start_frame"]
            or output_record["frame_mapping"]["output_start_frame"] != 0
            or candidate["source_labels"] != legacy._source_labels(rows[key])
            or candidate["candidate_labels"] != legacy.candidate_labels(rows[key], candidate["role"])):
            raise ReuseError("completed output metadata or candidate labels mismatch")
        if (source["receipt_sha256"] != receipt_sha or source["source_annotation"] != rows[key]
            or source["roi_record_sha256"] != verification._digest(rois[key])
            or source["source_sha256"] != base.sha256_file(root / "data/videos" / (key+".mp4"))
            or source["roi_sha256"] != base.sha256_file(root / "data/roi/videos" / (key+".mp4"))
            or candidate["folds"] != folds[key]
            or clip["source_sha256"] != source["source_sha256"] or clip["roi_sha256"] != source["roi_sha256"]
            or base.sha256_file(media) != output_record["sha256"] or output_record["sha256"] != clip["output_sha256"]
            or clip["window"]["source_frame_range"] != candidate["source_frame_range"]
            or candidate["source_frame_range"] != [candidate["start_frame"], candidate["end_frame"]]
            or clip["anchors"] != [{"source_frame":i,"roi_frame":i,"output_frame":i-candidate["start_frame"]}
                for i in candidate["source_anchor_frames"] if candidate["start_frame"] <= i < candidate["end_frame"]]
            or output_record["frame_mapping"]["anchors"] != clip["anchors"]
            or clip["code"] != source["code"] or clip["toolchain"] != source["toolchain"]):
            raise ReuseError("historical evidence no longer matches current project bytes or window")
        if source.get("phenomenon_anchor") and source["phenomenon_anchor"]["document_sha256"] != hashes.get(anchors.DOCUMENT):
            raise ReuseError("relocated phenomenon document mismatch")
        verified += 1
    return {"status":"historical_evidence_matches_current_bytes", "verified_outputs":verified,
            "limitations":["not_new_frame_replay", "not_human_label_review"]}

def run(project_root: Path, output_dir: Path | None = None, *, plan_only=False, resume=False, reuse_manifests=()) -> dict:
    root = Path(project_root).resolve()
    output = (root / "data/sub_video") if output_dir is None else Path(output_dir)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    # Protect all existing inputs, even when the output path is customized.
    protected = [root / "data/videos", root / "data/roi", root / "data/splits", root / "script"]
    if output == root or any(output == p or p in output.parents or output in p.parents for p in protected):
        raise base.PilotError("output directory overlaps protected inputs")
    rows, rois, folds, hashes = load_inputs(root)
    anchor_path = root / anchors.DOCUMENT
    anchor_document_sha = base.sha256_file(anchor_path) if anchor_path.is_file() else None
    anchor_records, anchor_issue = {}, None
    if anchor_document_sha is not None:
        hashes[anchors.DOCUMENT] = anchor_document_sha
        try:
            anchor_records = anchors.load_anchors(anchor_path)
        except (anchors.AnchorError, UnicodeError) as exc:
            anchor_issue = str(exc)
    selected = set(rows)
    donors = ReuseIndex(reuse_manifests, hashes)
    identity = {"reuse_manifests": {str(p):h for p,h in donors.manifests}, "schema": SCHEMA, "scope": "all_sources", "inputs": hashes,
                "code": verification._code(), "orchestration_code": orchestration_code(), "guard_seconds": .5, "post_remaining_seconds": 2.0,
                "phenomenon_document": {"path": anchors.DOCUMENT, "sha256": anchor_document_sha}}
    with base._run_lock(output):
        if output.exists():
            if not resume:
                raise base.PilotError("output already exists; use another directory or explicit --resume")
            manifest = base._load(output / "manifest.json")
            if not reuse_manifests and all(c["status"] == "cropped" for c in manifest["candidates"]):
                identity["reuse_manifests"] = manifest["identity"].get("reuse_manifests", {})
                audit_outputs(root, output)
            if manifest.get("identity") != identity:
                raise base.PilotError("resume input, selected fold or code identity differs")
        else:
            if resume:
                raise base.PilotError("cannot resume a missing directory")
            output.mkdir(parents=True)
            manifest = {"schema": SCHEMA, "identity": identity, "sources": [], "candidates": [],
                        "excluded_windows": [], "source_receipts": {}, "complete": False, "published": False, "plan_only": bool(plan_only)}
        (output / "videos").mkdir(exist_ok=True)
        def save():
            base._atomic_json(output / "manifest.json", manifest)
            base._atomic_json(output / "summary.json", summarize(manifest))
        save()
        known = {s["video_id"] for s in manifest["sources"]}
        for video_id in sorted(selected - known):
            row, roi = rows[video_id], rois[video_id]
            source = {"video_id": video_id, "source_annotation": row, "folds": folds[video_id],
                      "scope": "test" if folds[video_id]["0"] == "test" else "development"}
            try:
                # Check label-only skip conditions before reading any source media.
                event_fields = ("断裂帧_前", "断裂帧_后", "断裂时间点", "断裂时间范围_下界", "断裂时间范围_上界")
                if row.get("异常_视频异常") == "是" and not any(_present(row.get(k)) for k in event_fields):
                    raise PendingSource("视频异常")
                if row.get("异常_未夹紧") == "是":
                    if anchor_issue or video_id not in anchor_records:
                        raise PendingSource(anchor_issue or "未夹紧：缺少现象时刻")
                elif video_id in anchor_records:
                    raise PendingSource("现象帧记录与未夹紧标签不匹配")
                if roi.get("status") != "success":
                    raise PendingSource("ROI不可用")
                raw, cropped = root / "data/videos" / (video_id + ".mp4"), root / "data/roi/videos" / (video_id + ".mp4")
                source_sha, roi_sha = base.sha256_file(raw), base.sha256_file(cropped)
                if (source_sha != roi.get("source", {}).get("sha256") or roi_sha != roi.get("output", {}).get("sha256")
                    or roi.get("decision", {}).get("source_sha256") != source_sha):
                    raise PendingSource("源视频、ROI或裁剪决定身份不一致")
                raw_media, roi_media = aligned.probe_video(raw), aligned.probe_video(cropped)
                if raw_media["total_frames"] != roi_media["total_frames"]:
                    raise PendingSource("源视频与ROI帧数不一致")
                phenomenon_anchor = anchor_records.get(video_id)
                if phenomenon_anchor and phenomenon_anchor["source_sha256"] != source_sha:
                    raise PendingSource("未夹紧：现象帧记录的源视频身份不一致")
                record = adapt_annotation(row, raw_media, phenomenon_anchor=phenomenon_anchor)
                windows, excluded = plan_windows(record, raw_media)
                proof = donors.source_proof(video_id, row, roi, raw, cropped)
                if proof is None:
                    proof = verification.verify_source_replay(raw, cropped, roi, source_annotation=row,
                                                              phenomenon_anchor=phenomenon_anchor)
                source.update(status="planned", source_path=str(raw.relative_to(root)), roi_path=str(cropped.relative_to(root)),
                              source_sha256=source_sha, roi_sha256=roi_sha, roi_media=roi_media,
                              frame_preserving_replay=proof)
                manifest["excluded_windows"].extend(dict(w, source_video_id=video_id) for w in excluded)
                candidates = legacy._name_candidates(windows, row, folds[video_id], source_sha, roi_sha)
                for c in candidates:
                    c["source_anchor_frames"] = record["anchor_frames"]
                    if c.get("phenomenon_anchor"):
                        c["phenomenon_anchor"] = copy.deepcopy(proof["phenomenon_anchor"])
                    c["scope"] = "test" if folds[video_id]["0"] == "test" else "development"
                manifest["candidates"].extend(candidates)
                if not candidates:
                    source.update(status="pending", reason="没有满足时间边界和素材要求的窗口")
            except ReuseError:
                raise
            except (PendingSource, aligned.AlignmentUncertain, verification.ReplayUncertain, FileNotFoundError) as exc:
                source.update(status="pending", reason=str(exc))
            except (base.PilotError, ValueError, KeyError, TypeError, OSError) as exc:
                source.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
            manifest["sources"].append(source)
            save()
        admitted = {s["video_id"]: s for s in manifest["sources"] if s["status"] == "planned"}
        # Validate every recorded donor before encoding any missing clip.
        expected_by_id = {c["candidate_id"]:c for c in manifest["candidates"]}
        for key in donors.candidates:
            if key not in expected_by_id:
                raise ReuseError("donor output has no identical currently admitted candidate")
            c = expected_by_id[key]
            donors.adopt(c, output / c["output_path"], row=rows[c["source_video_id"]],
                         roi_path=root / admitted[c["source_video_id"]]["roi_path"],
                         roi_record=rois[c["source_video_id"]], validate_only=True)
        if not plan_only:
            for candidate in manifest["candidates"]:
                dest = output / candidate["output_path"]
                if candidate["status"] == "cropped":
                    if not dest.is_file() or base.sha256_file(dest) != candidate["output"]["sha256"]:
                        raise base.PilotError("recorded output missing or changed")
                    continue
                if dest.exists():
                    raise base.PilotError("unrecorded output exists; no overwrite")
                source = admitted[candidate["source_video_id"]]
                try:
                    result = donors.adopt(candidate, dest, row=rows[candidate["source_video_id"]],
                                          roi_path=root / source["roi_path"], roi_record=rois[candidate["source_video_id"]])
                    if result is None:
                        result = legacy.crop_video(root / source["roi_path"], dest, candidate, source["roi_media"], source["frame_preserving_replay"])
                    try:
                        unchanged = (base.sha256_file(root / source["source_path"]) == source["source_sha256"]
                                     and base.sha256_file(root / source["roi_path"]) == source["roi_sha256"]
                                     and all(base.sha256_file(root / relative) == digest for relative, digest in hashes.items())
                                     and not (anchor_document_sha is None and anchor_path.exists()))
                    except OSError:
                        unchanged = False
                    if not unchanged:
                        # Only remove bytes produced by this call, never a replaced file.
                        if dest.is_file() and base.sha256_file(dest) == result["sha256"]:
                            dest.unlink()
                        raise base.PilotError("input media changed during crop")
                    if result.get("reuse_provenance"):
                        donor_proof = donors.proof_for_receipt(result["reuse_provenance"]["source_receipt_sha256"])
                        manifest["source_receipts"][donor_proof["receipt_sha256"]] = donor_proof
                    candidate.update(status="cropped", output=result)
                    candidate.pop("reason", None)
                except ReuseError:
                    raise
                except (PendingSource, verification.ReplayUncertain, aligned.AlignmentUncertain) as exc:
                    candidate.update(status="pending", reason=str(exc))
                except (base.PilotError, OSError, ValueError) as exc:
                    candidate.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
                save()
        for source in admitted.values():
            if (base.sha256_file(root / source["source_path"]) != source["source_sha256"]
                or base.sha256_file(root / source["roi_path"]) != source["roi_sha256"]):
                raise base.PilotError("input media changed during run")
        if any(base.sha256_file(root / relative) != digest for relative, digest in hashes.items()):
            raise base.PilotError("metadata inputs changed during run")
        if anchor_document_sha is None and anchor_path.exists():
            raise base.PilotError("phenomenon document appeared during run")
        if verification._code() != identity["code"] or orchestration_code() != identity["orchestration_code"]:
            raise base.PilotError("generation code changed during run")
        manifest["plan_only"] = bool(plan_only)
        manifest["complete"] = not plan_only and not any(s["status"] in {"pending", "failed"} for s in manifest["sources"]) and all(c["status"] == "cropped" for c in manifest["candidates"])
        save()
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--reuse-manifest', type=Path, action='append', default=[])
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.project_root, args.output_dir, plan_only=args.plan_only,
                     resume=args.resume, reuse_manifests=args.reuse_manifest)
    except (base.PilotError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc)+'\n')
    print(base.canonical_bytes(summarize(result)).decode(), end='')
    return 0 if args.plan_only or result['complete'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
