"""Temporary 110-source projects; no production media is opened.

Only expensive media IO is faked. Input loading, policy routing, planning,
receipt seals/window checks, persistence and inventory validation stay real.
"""
from fractions import Fraction
import csv
import json
from pathlib import Path

import pytest

from script.subvideo_generation.tests.rules_support import FRACTURE_ANCHOR_FIELDS
from script.subvideo_generation.tests.test_generation_contract import annotation, digest, media
from script.subvideo_generation.tests.test_unclamped_contract import anchor_document


# The video_id allowlist the orchestrator used to carry for the coverage route. It no
# longer exists in the code; it is kept here *only* as a negative control, so that a
# fixture whose coverage rows happened to reproduce it could be caught (an id-based
# route would then look feature-based and the whole suite would stay green).
RETIRED_COVERAGE_IDS = {"video_" + n for n in (
    "0005", "0015", "0021", "0034", "0036", "0042", "0049", "0050",
    "0054", "0056", "0058", "0064", "0078", "0087", "0094", "0096", "0107")}

# The sources whose synthetic annotation rows actually carry the coverage features, i.e.
# what the criterion must route. Two shapes qualify: no fracture anchor + an undecidable
# 断裂状态 (the retired rows), and no fracture anchor + 异常_视频异常=是 (video_0108, an
# *unbroken* source whose video is flagged abnormal, i.e. the real shape of video_0107).
# Deliberately *not* the retired list: video_0107 is a plain unbroken source here (no
# abnormal-video flag) and video_0003 is coverage although it was never on the list.
COVERAGE_IDS = (RETIRED_COVERAGE_IDS - {"video_0107"}) | {"video_0003", "video_0108"}
TEST_IDS = {"video_0005", "video_0093"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def project(tmp_path, monkeypatch):
    from script.subvideo_generation import generate as g
    root = tmp_path / "project"
    ids = [f"video_{i:04d}" for i in range(1, 111)]
    dev = sorted(set(ids) - TEST_IDS)
    split = root / "data/splits/three-fold"
    write_json(split / "test.json", {"video_ids": sorted(TEST_IDS)})
    for fold in range(3):
        val = dev[fold::3]
        write_json(split / f"fold_{fold}_val.json", {"video_ids": val})
        write_json(split / f"fold_{fold}_train.json", {"video_ids": sorted(set(dev) - set(val))})
    rows, rois = [], []
    descriptions = {}
    for key in ids:
        row = annotation(key, 断裂状态="未断裂", 断裂模式="无", 断裂位置="无",
                         断裂帧_前="无", 断裂帧_后="无", 断裂时间点="无")
        description = media(count=60, fps=10)
        if key == "video_0003":
            # Coverage through the other accepted wording, and without the 视频异常
            # flag the retired rows carry: the route must not depend on either.
            row.update(断裂状态="无法判断")
            description = media(count=360, fps=10)
        elif key == "video_0108":
            # 视频异常 without any fracture anchor: the criterion must route it to coverage,
            # and its candidate labels must start from the source's own 未断裂 state
            # instead of the unified uncertain wording.
            row.update(断裂状态="未断裂", 断裂模式="无", 断裂位置="无", 异常_视频异常="是",
                       **{name: "无" for name in FRACTURE_ANCHOR_FIELDS})
            description = media(count=360, fps=10)
        elif key in COVERAGE_IDS:
            row.update(断裂状态="无法确定", 断裂模式="无法确定", 断裂位置="无法确定", 异常_视频异常="是")
            description = media(count=360, fps=10)
        elif key == "video_0002":
            row.update(异常_未夹紧="是", 视频帧率="30")
            description = media(count=194, fps=30)
        elif key == "video_0093":
            row.update(断裂状态="发生断裂", 断裂模式="脆性断裂", 断裂位置="标距内",
                       断裂帧_前="727", 断裂帧_后="728", 断裂时间点=str(728 / 30), 视频帧率="30")
            description = media(count=733, fps=30)
        description["time_base"] = "1/1000000"
        rows.append(row)
        descriptions[key] = description
        for directory in ("data/videos", "data/roi/videos"):
            path = root / directory / f"{key}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"synthetic:{directory}:{key}".encode())
        rois.append({"video_id": key, "status": "success",
                     "source": {"sha256": digest(root / "data/videos" / f"{key}.mp4")},
                     "decision": {"source_sha256": digest(root / "data/videos" / f"{key}.mp4")},
                     "output": {"sha256": digest(root / "data/roi/videos" / f"{key}.mp4")}})
    csv_path = root / "data/annotation-table-full.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    write_json(root / "data/roi/manifest.json", {"videos": rois})
    anchor_document(root / "docs/subvideo-current-logic.md", [
        ("video_0002", 174, digest(root / "data/videos/video_0002.mp4"))])
    monkeypatch.setattr(g.special_verification, "APPROVED_SOURCE_SHA256", digest(root / "data/videos/video_0093.mp4"))

    def probe(path):
        path = Path(path)
        if path.parent.name == "videos" and path.parent.parent.name in {"data", "roi"}:
            return dict(descriptions[path.stem])
        return json.loads(path.read_text())["media"]

    def decoded(path, _info, **_kwargs):
        description = probe(path)
        return {"frame_count": description["total_frames"], "frame_sequence_sha256": digest(path)}

    for verifier in (g.core, g.special_verification):
        monkeypatch.setattr(verifier, "_toolchain", lambda: {"synthetic_media_boundary": True})
        monkeypatch.setattr(verifier, "_stream_info", probe)
        monkeypatch.setattr(verifier, "_decode_rgb", decoded)
        def source_proof(raw, roi, record, *, source_annotation=None, phenomenon_anchor=None,
                         verifier=verifier):
            description = probe(raw)
            fps = Fraction(str(description["fps"]))
            decode = {"frame_count": description["total_frames"], "time_base": "1/1000000",
                      "normalized_pts": [str(Fraction(i) / fps) for i in range(description["total_frames"])],
                      "usable_end": str(Fraction(description["total_frames"]) / fps)}
            if source_annotation["id"] == "video_0093":
                decode["presentation_evidence"] = {"declared_frame_count": 771, "presented_frame_count": 733,
                    "discarded_preroll_frames": 38, "mapping": "unedited_i_equals_presented_i_plus_38"}
            return verifier._seal({"schema": verifier.SOURCE_SCHEMA, "status": verifier.VERIFIED,
                "video_id": source_annotation["id"], "source_path": str(raw), "roi_path": str(roi),
                "source_sha256": digest(raw), "roi_sha256": digest(roi),
                "reference_sha256": digest(roi), "decision_sha256": verifier._digest(record.get("decision", {})),
                "roi_record_sha256": verifier._digest(record), "source_annotation": source_annotation,
                "source_annotation_sha256": verifier._digest(source_annotation),
                "phenomenon_anchor": phenomenon_anchor,
                "phenomenon_anchor_sha256": verifier._digest(phenomenon_anchor) if phenomenon_anchor else None,
                "source_decode": decode, "roi_decode": decode,
                "code": verifier._code(), "toolchain": verifier._toolchain()})
        monkeypatch.setattr(verifier, "verify_source_replay", source_proof)
    monkeypatch.setattr(g.aligned, "probe_video", probe)

    encoded = []
    def crop(roi, destination, candidate, roi_media, source_proof):
        key = candidate["source_video_id"]
        verifier = g.special_verification if key == "video_0093" else g.core
        # Two separate things are checked here. This assertion is the fixture's own,
        # independent expectation of the route (an id list that predates the run), so a
        # planning regression is reported as the route it broke rather than as a proof
        # mismatch further down. The verifier is then picked by the role the planner
        # actually produced, so a coverage candidate is validated by the coverage verifier
        # even while the expectation above is still red.
        assert (key in COVERAGE_IDS) == (candidate.get("role") == "coverage"), (
            f"fixture expects coverage route for {key} = {key in COVERAGE_IDS}, but the "
            f"planner produced role={candidate.get('role')!r} for candidate "
            f"{candidate.get('candidate_id')!r}")
        clip_verifier = g.coverage_verification if candidate.get("role") == "coverage" else verifier
        window = clip_verifier.validate_source_receipt(source_proof, roi, candidate)
        description = dict(roi_media, total_frames=candidate["end_frame"] - candidate["start_frame"],
                           duration=candidate["duration"])
        write_json(destination, {"candidate_id": candidate["candidate_id"], "media": description})
        encoded.append(candidate["candidate_id"])
        anchors = [{"source_frame": i, "roi_frame": i, "output_frame": i - candidate["start_frame"]}
                   for i in candidate["source_anchor_frames"] if candidate["start_frame"] <= i < candidate["end_frame"]]
        proof = verifier._seal({"schema": getattr(clip_verifier, "CLIP_SCHEMA", None) or clip_verifier.SCHEMA,
            "status": verifier.VERIFIED, "source_receipt_sha256": source_proof["receipt_sha256"],
            "proof_type": "independent_absolute_select_replay_of_trim_output",
            "supplement_code": g.coverage_verification.code(),
            "source_sha256": source_proof["source_sha256"], "roi_sha256": source_proof["roi_sha256"],
            "output_sha256": digest(destination), "window": window, "anchors": anchors,
            "decoded_frame_count": description["total_frames"], "decoded_RGB_PTS_sequence_sha256": digest(destination),
            "code": source_proof["code"], "toolchain": source_proof["toolchain"]})
        return {"sha256": digest(destination), "media": {k: description[k] for k in (
            "duration", "total_frames", "fps", "width", "height", "time_base")},
            "full_decode": "passed", "frame_preserving_replay": proof,
            "frame_mapping": {"source_start_frame": candidate["start_frame"], "output_start_frame": 0, "anchors": anchors}}
    for module in (g.legacy, g.coverage, g.special):
        monkeypatch.setattr(module, "crop_video", crop)

    # The fast (``basic`` / ``none``) verification path cuts through
    # ``aligned.crop_video`` and must never reach a frame-level verifier. This stub
    # therefore only echoes what planning already decided: it stands in for the
    # encoded clip's bytes, the ``ffprobe`` of those bytes, and the planned frame
    # mapping -- none of it is derived from a decoded RGB/PTS comparison. It stays
    # out of the full path, which keeps using the ``legacy``/``coverage``/``special``
    # stub above unchanged.
    def crop_without_frame_replay(source, destination, candidate, roi_media, roi_features=None,
                                  source_proof=None, verification="full"):
        key = candidate["source_video_id"]
        assert (key in COVERAGE_IDS) == (candidate.get("role") == "coverage"), (
            f"fixture expects coverage route for {key} = {key in COVERAGE_IDS}, but the "
            f"planner produced role={candidate.get('role')!r} for candidate "
            f"{candidate.get('candidate_id')!r}")
        description = dict(roi_media, total_frames=candidate["end_frame"] - candidate["start_frame"],
                           duration=candidate["duration"])
        write_json(destination, {"candidate_id": candidate["candidate_id"], "media": description})
        encoded.append(candidate["candidate_id"])
        anchors = [{"source_frame": i, "roi_frame": i, "output_frame": i - candidate["start_frame"]}
                   for i in candidate["source_anchor_frames"]
                   if candidate["start_frame"] <= i < candidate["end_frame"]]
        result = {"sha256": digest(destination),
                  "frame_mapping": {"source_start_frame": candidate["start_frame"],
                                    "output_start_frame": 0, "anchors": anchors}}
        if verification != "none":  # ``none`` must not probe the output at all.
            result["media"] = {k: description[k] for k in (
                "duration", "total_frames", "fps", "width", "height", "time_base")}
        if verification != "full":
            result["verification"] = {"mode": verification, "frame_replay": "skipped"}
        return result
    monkeypatch.setattr(g.aligned, "crop_video", crop_without_frame_replay)
    return root, g, descriptions, encoded
