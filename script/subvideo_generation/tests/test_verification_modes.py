"""Contract for the three verification modes and for source-parallel generation.

The user narrowed the batch to "generate + basic output check + human review",
so the orchestrator has to offer ``full`` / ``basic`` / ``none`` side by side and
record honestly which of them produced a batch. It also has to cut the 110
independent sources in parallel without changing the batch it writes.

Every assertion below is about an observable batch or an observable call: the
fixture's media IO is synthetic, no production media is read.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

import pytest

from script.subvideo_generation import generate as g
from script.subvideo_generation.tests.rules_support import run_cli
from script.subvideo_generation.tests.test_generation_contract import digest


OUTPUT = Path("data") / "sub_video"
MEDIA_FIELDS = ("duration", "total_frames", "fps", "width", "height", "time_base")
FAST_MODES = ("basic", "none")

# Every function that decides "the output really is the same frames as the ROI".
# ``basic`` and ``none`` must not reach any of them.
FRAME_LEVEL_VERIFIERS = (
    ("core", "verify_source_replay"),
    ("special_verification", "verify_source_replay"),
    ("core", "verify_clip_replay"),
    ("special_verification", "verify_clip_replay"),
    ("coverage_verification", "verify_clip_replay"),
    ("aligned", "compare_sequences"),
    ("aligned", "_features"),
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def cropped(manifest):
    return [c for c in manifest["candidates"] if c["status"] == "cropped"]


def planned_sources(manifest):
    return [s for s in manifest["sources"] if s["status"] == "planned"]


def manifest_text(root, directory=OUTPUT):
    return (Path(root) / directory / "manifest.json").read_text(encoding="utf-8")


def planned_anchors(candidate):
    """The frame mapping planning already decided; no decode is needed to know it."""
    start = candidate["start_frame"]
    return [{"source_frame": i, "roi_frame": i, "output_frame": i - start}
            for i in candidate["source_anchor_frames"] if start <= i < candidate["end_frame"]]


def audit_mode(audit):
    """The mode an audit reports, under either documented key."""
    if "verification_mode" in audit:
        return audit["verification_mode"]
    record = audit.get("verification")
    return record.get("mode") if isinstance(record, dict) else None


def console(result):
    return (result.stdout or "") + (result.stderr or "")


def forbidden(name):
    """A test double that records the call and fails the test if it happens."""
    def call(*_args, **_kwargs):
        raise AssertionError(f"fast verification must not call {name}")
    return call


def fail_probe_for(monkeypatch, key, error):
    """Make one source's ROI probe fail during planning, leaving the rest intact."""
    original = g.aligned.probe_video

    def probe(path):
        path = Path(path)
        if path.stem == key and path.parent.name == "videos" and path.parent.parent.name == "roi":
            raise error
        return original(path)

    monkeypatch.setattr(g.aligned, "probe_video", probe)


# --------------------------------------------------------------------------- #
# 1. defaults: Python and CLI both default to ``basic``
# --------------------------------------------------------------------------- #

def test_run_defaults_to_basic_verification(project):
    root, _, _, _ = project

    manifest = g.run(root)

    record = manifest.get("verification") or {}
    assert record.get("mode") == "basic", (
        "the Python default must be the fast mode, not full replay; "
        f"got {record!r}")


def test_run_signature_declares_the_three_modes_and_serial_jobs():
    parameters = inspect.signature(g.run).parameters

    assert getattr(g, "VERIFICATION_MODES", None) == ("full", "basic", "none")
    assert getattr(g, "DEFAULT_VERIFICATION", None) == "basic"
    assert parameters["verification"].default == "basic", (
        "run() must default to verification='basic', "
        f"got {parameters['verification'].default!r}")
    assert parameters["verification"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["jobs"].default == 1, (
        f"run() must default to jobs=1, got {parameters['jobs'].default!r}")
    assert parameters["jobs"].kind is inspect.Parameter.KEYWORD_ONLY


def test_explicit_full_verification_is_selectable(project):
    root, _, _, encoded = project

    manifest = g.run(root, verification="full")

    assert manifest["complete"] is True and len(cropped(manifest)) == len(encoded) > 0
    assert g.core.VERIFIED in manifest_text(root)


def test_cli_documents_the_verification_modes_and_the_jobs_switch():
    result = run_cli("--help")

    assert result.returncode == 0, console(result)
    text = console(result)
    for token in ("--verification", "--jobs", "full", "basic", "none"):
        assert token in text, f"the CLI must document {token!r}, got:\n{text}"


@pytest.mark.parametrize("switch", ["--videos-dir", "--audit-only"])
@pytest.mark.parametrize("option", [("--verification", "full"), ("--jobs", "2")])
def test_cli_rejects_verification_or_jobs_next_to_a_mode_that_cannot_use_them(
        tmp_path, option, switch):
    videos, output = tmp_path / "videos", tmp_path / "out"
    videos.mkdir()
    (videos / "a.mp4").write_bytes(b"synthetic clip")
    arguments = {"--videos-dir": ("--videos-dir", videos, "--output-dir", output),
                 "--audit-only": ("--audit-only", "--output-dir", output)}[switch]

    result = run_cli("--project-root", tmp_path, *arguments, *option)

    assert result.returncode != 0, (
        f"{option[0]} must be a usage error next to {switch}, "
        f"got rc=0 with {console(result)!r}")
    assert "cannot be combined" in console(result), console(result)


@pytest.mark.parametrize("changes", [{"verification": "thorough"}, {"verification": ""},
                                     {"jobs": 0}, {"jobs": -1}, {"jobs": "2"}, {"jobs": 2.0}])
def test_run_rejects_an_illegal_verification_or_jobs_value(project, changes):
    root, _, _, encoded = project

    with pytest.raises(g.base.PilotError):
        g.run(root, **changes)

    assert encoded == [], "an illegal mode must be rejected before any clip is cut"


# --------------------------------------------------------------------------- #
# 2. ``full`` keeps the batch shape it has today, key for key
# --------------------------------------------------------------------------- #

def test_full_verification_keeps_the_recorded_manifest_shape(project):
    root, _, _, encoded = project

    manifest = g.run(root, verification="full")

    assert "verification" not in manifest, (
        "a full batch must not gain a modes block: "
        f"got {manifest.get('verification')!r}")
    assert planned_sources(manifest)
    for source in planned_sources(manifest):
        assert "verification" not in source
        assert source["frame_preserving_replay"]["status"] == g.core.VERIFIED
    clips = cropped(manifest)
    assert len(clips) == len(encoded) > 0
    for candidate in clips:
        assert "verification" not in candidate["output"], (
            f"{candidate['candidate_id']} gained a modes block in a full batch")
        assert candidate["output"]["frame_preserving_replay"]["status"] == g.core.VERIFIED
        assert candidate["output"]["full_decode"] == "passed"


# --------------------------------------------------------------------------- #
# 3. ``basic`` skips every frame-level check but keeps the honest basics
# --------------------------------------------------------------------------- #

def test_basic_verification_never_calls_a_frame_level_verifier(project, monkeypatch):
    root, _, _, encoded = project
    calls = []

    def watched(name):
        def call(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"basic verification must not call {name}")
        return call

    for module, function in FRAME_LEVEL_VERIFIERS:
        monkeypatch.setattr(getattr(g, module), function, watched(f"{module}.{function}"))

    manifest = g.run(root, verification="basic")

    assert calls == [], f"basic verification decoded frames through {calls}"
    assert manifest["complete"] is True
    assert len(cropped(manifest)) == len(encoded) > 0


def test_basic_verification_keeps_bytes_media_and_the_planned_frame_mapping(project):
    root, _, _, _ = project

    manifest = g.run(root, verification="basic")

    clips = cropped(manifest)
    assert clips
    for candidate in clips:
        record = candidate["output"]
        path = root / OUTPUT / candidate["output_path"]
        assert record["sha256"] == digest(path), (
            f"{candidate['candidate_id']} must still record the bytes it wrote")
        assert set(record["media"]) == set(MEDIA_FIELDS)
        assert record["media"]["total_frames"] == candidate["end_frame"] - candidate["start_frame"]
        roi = g.aligned.probe_video(root / "data/roi/videos" / (candidate["source_video_id"] + ".mp4"))
        assert (record["media"]["width"], record["media"]["height"]) == (roi["width"], roi["height"])
        assert record["frame_mapping"] == {"source_start_frame": candidate["start_frame"],
                                           "output_start_frame": 0,
                                           "anchors": planned_anchors(candidate)}
        assert record.get("full_decode") != "passed", (
            f"{candidate['candidate_id']} claims a full decode that basic verification never ran")


# --------------------------------------------------------------------------- #
# 4. honesty: a fast batch says out loud what it did not check
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", FAST_MODES)
def test_fast_mode_manifest_text_never_claims_a_frame_replay(project, mode):
    root, _, _, _ = project

    g.run(root, verification=mode)

    assert g.core.VERIFIED == "verified_frame_preserving_replay"
    assert g.core.VERIFIED not in manifest_text(root), (
        f"a {mode} batch must not contain the verified status anywhere")


@pytest.mark.parametrize("mode", FAST_MODES)
def test_fast_mode_records_a_skipped_frame_replay_at_every_layer(project, mode):
    root, _, _, _ = project

    manifest = g.run(root, verification=mode)

    top = manifest["verification"]
    assert top["mode"] == mode
    assert top["frame_replay"] == "skipped"
    assert isinstance(top["reason"], str) and top["reason"].strip(), (
        f"the {mode} batch must state why frame replay was skipped, got {top.get('reason')!r}")
    sources = manifest["sources"]
    assert sources
    for source in sources:
        assert source["verification"]["mode"] == mode
        assert source["verification"]["frame_replay"] == "skipped"
        assert "frame_preserving_replay" not in source, (
            f"{source['video_id']} still records a frame replay proof in {mode} mode")
    clips = cropped(manifest)
    assert clips
    for candidate in clips:
        record = candidate["output"]["verification"]
        assert record["mode"] == mode
        assert record["frame_replay"] == "skipped"
        assert "frame_preserving_replay" not in candidate["output"], (
            f"{candidate['candidate_id']} still records a frame replay proof in {mode} mode")


# --------------------------------------------------------------------------- #
# 5. ``none`` drops the output probe as well
# --------------------------------------------------------------------------- #

def test_none_verification_omits_output_media_and_never_probes_the_output(project, monkeypatch):
    root, _, _, _ = project
    output = (root / OUTPUT).resolve()
    original = g.aligned.probe_video

    def guard(path):
        resolved = Path(path).resolve()
        if output in resolved.parents:
            raise AssertionError(f"none verification must not probe the encoded output: {resolved}")
        return original(path)

    monkeypatch.setattr(g.aligned, "probe_video", guard)

    manifest = g.run(root, verification="none")

    clips = cropped(manifest)
    assert clips
    for candidate in clips:
        assert "media" not in candidate["output"], (
            f"{candidate['candidate_id']} recorded ffprobe output in none mode")
        assert candidate["output"]["sha256"], "the bytes must still be hashed"


# --------------------------------------------------------------------------- #
# 6. ``--jobs`` parallelises sources without changing the batch
# --------------------------------------------------------------------------- #

def test_parallel_jobs_produce_the_same_manifest_and_summary_as_serial(project):
    root, _, _, _ = project

    serial = g.run(root, "out-serial", verification="basic", jobs=1)
    parallel = g.run(root, "out-parallel", verification="basic", jobs=2)

    assert serial["complete"] is True and parallel["complete"] is True
    assert len(parallel["sources"]) == 110
    assert g.base.canonical_bytes(serial) == g.base.canonical_bytes(parallel), (
        "cutting sources in parallel must not reorder or reshape the batch")
    for name in ("manifest.json", "summary.json"):
        assert (root / "out-serial" / name).read_bytes() == (root / "out-parallel" / name).read_bytes(), (
            f"{name} differs between jobs=1 and jobs=2")


def test_parallel_jobs_can_be_combined_with_plan_only(project):
    root, _, _, encoded = project

    manifest = g.run(root, plan_only=True, verification="basic", jobs=2)

    assert manifest["plan_only"] is True and manifest["complete"] is False
    assert manifest["candidates"]
    assert all(c["status"] == "planned" for c in manifest["candidates"])
    assert encoded == [], "plan-only must not encode, whatever the job count"


def test_a_failing_source_aborts_a_parallel_run_naming_that_source(project, monkeypatch):
    root, _, _, _ = project
    original = g.aligned.crop_video

    def explode(source, destination, candidate, *args, **kwargs):
        if candidate["source_video_id"] == "video_0001":
            raise RuntimeError("boom")
        return original(source, destination, candidate, *args, **kwargs)

    monkeypatch.setattr(g.aligned, "crop_video", explode)

    with pytest.raises(Exception) as caught:
        g.run(root, verification="basic", jobs=2)

    assert "video_0001" in str(caught.value), (
        "a worker failure must name the source it came from, got "
        f"{type(caught.value).__name__}: {caught.value}")
    json.loads((root / OUTPUT / "manifest.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 7. resume: the mode is part of what a batch was written under
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("written,resumed", [("full", "basic"), ("basic", "full")])
def test_resume_rejects_a_batch_written_in_another_verification_mode(project, written, resumed):
    root, _, _, _ = project
    g.run(root, verification=written)

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True, verification=resumed)

    assert "verification" in str(caught.value).lower(), (
        f"resuming a {written} batch as {resumed} must say why, got: {caught.value}")


# --------------------------------------------------------------------------- #
# 8. audit: a fast batch is auditable, and the audit says what it did not check
# --------------------------------------------------------------------------- #

def test_audit_outputs_accepts_a_basic_batch_and_declares_the_mode(project):
    root, _, _, _ = project
    g.run(root, verification="basic")

    audit = g.audit_outputs(root, root / OUTPUT)

    assert audit_mode(audit) == "basic", (
        f"the audit must report the mode the batch was written under, got {sorted(audit)}")
    limitations = audit["limitations"]
    assert any("no_frame" in item for item in limitations), (
        f"the audit must state that frames were not replayed, got {limitations}")
    assert g.core.VERIFIED not in json.dumps(audit), (
        "a basic audit must not report a verified frame replay")


def test_audit_batch_routes_a_basic_batch_to_the_basic_audit(project):
    root, _, _, _ = project
    g.run(root, verification="basic")

    routed = g.audit_batch(root, root / OUTPUT)

    assert routed.get("verdict") != "content_only", (
        "a basic batch keeps its input identity, so it is not a content-only batch")
    assert audit_mode(routed) == "basic", (
        f"audit_batch must keep the mode visible, got {sorted(routed)}")


# --------------------------------------------------------------------------- #
# 9. a planning failure must name its source, just like a cutting failure
#     (gap: only the cutting worker wrapped its exceptions)
# --------------------------------------------------------------------------- #

def test_a_planning_crash_in_a_parallel_run_names_that_source(project, monkeypatch):
    root, _, _, _ = project
    fail_probe_for(monkeypatch, "video_0001", RuntimeError("boom"))

    with pytest.raises(Exception) as caught:
        g.run(root, verification="basic", jobs=2)

    assert "video_0001" in str(caught.value), (
        "a planning-stage worker failure must name the source it came from, got "
        f"{type(caught.value).__name__}: {caught.value}")


def test_a_planning_pilot_error_in_a_parallel_run_names_that_source(project, monkeypatch):
    root, _, _, _ = project
    original = g._plan_source

    def plan(project_root, key, *args, **kwargs):
        if key == "video_0001":
            raise g.base.PilotError("planned boom")
        return original(project_root, key, *args, **kwargs)

    monkeypatch.setattr(g, "_plan_source", plan)

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, verification="basic", jobs=2)

    assert "video_0001" in str(caught.value), (
        "a planning-stage PilotError must name the source it came from, got: " + str(caught.value))


# --------------------------------------------------------------------------- #
# 10. an unplanned (pending/failed) source is still honest about the mode
#     (gap: only planned sources carried the skipped record)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("error,status", [(g.legacy.PendingSource, "pending"),
                                          (g.base.PilotError, "failed")],
                         ids=["pending", "failed"])
def test_a_fast_batch_records_the_skipped_replay_for_an_unplanned_source(
        project, monkeypatch, error, status):
    root, _, _, _ = project
    fail_probe_for(monkeypatch, "video_0001", error("injected source failure"))

    manifest = g.run(root, verification="basic")

    source = next(s for s in manifest["sources"] if s["video_id"] == "video_0001")
    assert source["status"] == status, source.get("reason")
    note = source.get("verification") or {}
    assert note.get("mode") == "basic", (
        f"a {status} source in a basic batch must still record the mode, got {note!r}")
    assert note.get("frame_replay") == "skipped", (
        f"a {status} source in a basic batch must record that no frame replay ran, got {note!r}")
    assert "frame_preserving_replay" not in source


def test_a_full_batch_records_no_verification_note_on_an_unplanned_source(project, monkeypatch):
    root, _, _, _ = project
    fail_probe_for(monkeypatch, "video_0001", g.legacy.PendingSource("injected source failure"))

    manifest = g.run(root, verification="full")

    source = next(s for s in manifest["sources"] if s["video_id"] == "video_0001")
    assert source["status"] == "pending"
    assert "verification" not in source, (
        f"a full batch must keep unplanned sources key-for-key unchanged, got {source['verification']!r}")


@pytest.mark.parametrize("mode", FAST_MODES)
def test_every_layer_of_a_fast_batch_records_the_skipped_replay(project, monkeypatch, mode):
    root, _, _, _ = project
    fail_probe_for(monkeypatch, "video_0001", g.legacy.PendingSource("injected source failure"))
    fail_crop_for(monkeypatch, "video_0002", g.legacy.PendingSource("injected cut failure"))

    manifest = g.run(root, verification=mode)

    assert manifest["verification"]["mode"] == mode
    assert manifest["verification"]["frame_replay"] == "skipped"
    assert manifest["verification"]["reason"].strip()
    sources = manifest["sources"]
    assert len(sources) == 110
    assert any(s["status"] != "planned" for s in sources), (
        "this test needs one unplanned source to prove the record is not planned-only")
    for source in sources:
        note = source.get("verification") or {}
        assert note.get("mode") == mode, f"{source['video_id']} ({source['status']}) has {note!r}"
        assert note.get("frame_replay") == "skipped"
        assert "frame_preserving_replay" not in source
    candidates = manifest["candidates"]
    assert candidates
    assert {c["status"] for c in candidates} >= {"cropped", "pending"}, (
        "this test needs both a cut window and an archived failure to prove the record is "
        f"not cropped-only, got {sorted({c['status'] for c in candidates})}")
    for candidate in candidates:
        note = candidate.get("verification") or {}
        assert note.get("mode") == mode, (
            f"candidate {candidate['candidate_id']} ({candidate['status']}) has {note!r}")
        assert note.get("frame_replay") == "skipped"
        assert "frame_preserving_replay" not in candidate
    clips = cropped(manifest)
    assert clips
    for candidate in clips:
        assert candidate["output"]["verification"]["mode"] == mode
        assert candidate["output"]["verification"]["frame_replay"] == "skipped"
        assert "frame_preserving_replay" not in candidate["output"]


# --------------------------------------------------------------------------- #
# 11. ``jobs`` must really overlap sources, and merge in plan order
#     (gap: equivalence alone also passes when jobs silently degenerates to serial)
# --------------------------------------------------------------------------- #

def overlap_crops(monkeypatch, barrier, entered):
    """Make the first two cuttings wait for each other; a serial run times out."""
    original = g.aligned.crop_video
    lock = threading.Lock()

    def crop(source, destination, candidate, *args, **kwargs):
        with lock:
            first_pair = len(entered) < 2
            entered.append(candidate["source_video_id"])
        if first_pair:
            barrier.wait()
        return original(source, destination, candidate, *args, **kwargs)

    monkeypatch.setattr(g.aligned, "crop_video", crop)


def test_two_workers_cut_different_sources_at_the_same_time(project, monkeypatch):
    root, _, _, _ = project
    barrier = threading.Barrier(2, timeout=10)
    entered = []
    overlap_crops(monkeypatch, barrier, entered)

    try:
        manifest = g.run(root, verification="basic", jobs=2)
    except Exception as exc:  # a serial run breaks the barrier and lands here
        pytest.fail("jobs=2 never had two sources in flight at once: "
                    f"{type(exc).__name__}: {exc}")

    assert len(set(entered)) >= 2, f"only {entered} was cut"
    assert barrier.broken is False, "a worker timed out waiting for a second worker"
    assert manifest["complete"] is True


def test_a_slow_early_source_does_not_reorder_a_parallel_batch(project, monkeypatch):
    root, _, _, _ = project
    original = g.aligned.crop_video
    finished, lock = [], threading.Lock()

    def crop(source, destination, candidate, *args, **kwargs):
        if candidate["source_video_id"] == "video_0001":
            time.sleep(0.8)  # the first key in plan order finishes last
        result = original(source, destination, candidate, *args, **kwargs)
        with lock:
            finished.append(candidate["source_video_id"])
        return result

    monkeypatch.setattr(g.aligned, "crop_video", crop)

    serial = g.run(root, "out-serial", verification="basic", jobs=1)
    serial_finished = list(finished)
    del finished[:]
    parallel = g.run(root, "out-parallel", verification="basic", jobs=2)

    assert serial_finished[-1] != "video_0001"
    assert finished[-1] == "video_0001", (
        "the slow source must finish out of plan order for this test to mean anything, "
        f"got the last three as {finished[-3:]}")
    assert g.base.canonical_bytes(serial) == g.base.canonical_bytes(parallel), (
        "results must be merged in plan order, not in completion order")
    for name in ("manifest.json", "summary.json"):
        assert (root / "out-serial" / name).read_bytes() == (root / "out-parallel" / name).read_bytes(), (
            f"{name} differs between jobs=1 and jobs=2")


# --------------------------------------------------------------------------- #
# 12. the real fast crop path, not the fixture's stub
# --------------------------------------------------------------------------- #

def synthetic_video(directory, *, frames=60, rate=10, size="64x48"):
    """Encode a tiny deterministic clip with FFmpeg; no project media is read."""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is required to encode a synthetic clip")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "roi.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={frames / rate}",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    return path


def fast_candidate(source, *, start=0, end=20, anchors=(0, 10, 19)):
    """The plan-side fields the fast crop is allowed to read."""
    return {"candidate_id": "synthetic_0001_pre_01", "start_frame": start, "end_frame": end,
            "source_anchor_frames": [i for i in anchors if start <= i < end],
            "roi_sha256": digest(source)}


def test_real_basic_crop_records_bytes_media_and_mapping_but_no_replay(tmp_path, monkeypatch):
    source = synthetic_video(tmp_path / "roi")
    roi_media = g.aligned.probe_video(source)
    candidate = fast_candidate(source)
    output = tmp_path / "out" / "videos" / "synthetic_0001_pre_01.mp4"
    output.parent.mkdir(parents=True)
    for module, function in ((g.core, "verify_clip_replay"),
                             (g.aligned, "compare_sequences"),
                             (g.aligned.replay, "verify_clip_replay"),
                             (g.aligned.replay, "verify_source_replay"),
                             (g.aligned, "_features")):
        monkeypatch.setattr(module, function, forbidden(f"{module.__name__}.{function}"))

    result = g.aligned.crop_video(source, output, candidate, roi_media, verification="basic")

    assert result["sha256"] == digest(output), "the recorded digest must be the bytes on disk"
    assert result["media"]["total_frames"] == candidate["end_frame"] - candidate["start_frame"]
    assert (result["media"]["width"], result["media"]["height"]) == (roi_media["width"], roi_media["height"])
    assert set(result["media"]) == set(MEDIA_FIELDS)
    assert result["frame_mapping"] == {"source_start_frame": candidate["start_frame"],
                                       "output_start_frame": 0,
                                       "anchors": planned_anchors(candidate)}
    assert result["verification"]["mode"] == "basic"
    assert result["verification"]["frame_replay"] == "skipped"
    assert "frame_preserving_replay" not in result
    assert result.get("full_decode") != "passed", "a basic crop decodes nothing"


def test_real_none_crop_never_probes_the_output(tmp_path, monkeypatch):
    source = synthetic_video(tmp_path / "roi")
    roi_media = g.aligned.probe_video(source)
    candidate = fast_candidate(source)
    output = tmp_path / "out" / "videos" / "synthetic_0001_pre_01.mp4"
    output.parent.mkdir(parents=True)
    monkeypatch.setattr(g.aligned, "probe_video", forbidden("aligned.probe_video"))

    result = g.aligned.crop_video(source, output, candidate, roi_media, verification="none")

    assert "media" not in result, f"none must not record an output probe, got {sorted(result)}"
    assert result["sha256"] == digest(output), "the bytes must still be hashed"
    assert result["verification"]["mode"] == "none"
    assert result["frame_mapping"] == {"source_start_frame": candidate["start_frame"],
                                       "output_start_frame": 0,
                                       "anchors": planned_anchors(candidate)}
    assert "frame_preserving_replay" not in result


# --------------------------------------------------------------------------- #
# 13. a cutting failure must name its source in every job count
#     (gap: only the parallel worker wrapped, and it re-raised PilotError bare)
# --------------------------------------------------------------------------- #

def fail_crop_for(monkeypatch, key, error):
    """Make one source's cutting fail, leaving every other source intact."""
    original = g.aligned.crop_video

    def crop(source, destination, candidate, *args, **kwargs):
        if candidate["source_video_id"] == key:
            raise error
        return original(source, destination, candidate, *args, **kwargs)

    monkeypatch.setattr(g.aligned, "crop_video", crop)


@pytest.mark.parametrize("jobs", [1, 2], ids=["jobs-1", "jobs-2"])
def test_a_cut_crash_names_that_source(project, monkeypatch, jobs):
    root, _, _, _ = project
    fail_crop_for(monkeypatch, "video_0001", RuntimeError("boom"))

    with pytest.raises(Exception) as caught:
        g.run(root, verification="basic", jobs=jobs)

    assert "video_0001" in str(caught.value), (
        f"a cutting-stage failure must name the source it came from at jobs={jobs}, got "
        f"{type(caught.value).__name__}: {caught.value}")


@pytest.mark.parametrize("jobs", [1, 2], ids=["jobs-1", "jobs-2"])
def test_an_output_collision_names_that_source(project, monkeypatch, jobs):
    """An interrupted earlier process left a file where this run wants to write."""
    root, _, _, _ = project
    planned = g.run(root, plan_only=True, verification="basic", jobs=1)
    victim = next(c for c in planned["candidates"] if c["source_video_id"] == "video_0002")
    output = root / OUTPUT
    original = g._cut_candidate
    planted = threading.Event()

    def cut(project_root, out, source, candidate, *args, **kwargs):
        if candidate["source_video_id"] == "video_0002":
            assert planted.wait(timeout=30), "the colliding source never got its turn"
        result = original(project_root, out, source, candidate, *args, **kwargs)
        if candidate["source_video_id"] == "video_0001":
            (output / victim["output_path"]).write_bytes(b"planted by an interrupted process")
            planted.set()
        return result

    monkeypatch.setattr(g, "_cut_candidate", cut)

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True, verification="basic", jobs=jobs)

    message = str(caught.value)
    assert "unrecorded output exists" in message, (
        f"the collision path was not reached at jobs={jobs}: {message}")
    assert "video_0002" in message, (
        f"an output collision must name the source it belongs to at jobs={jobs}, got: {message}")
    json.loads((output / "manifest.json").read_text(encoding="utf-8"))


def test_an_archived_cut_failure_still_does_not_abort_the_batch(project, monkeypatch):
    """A per-source failure that ``_cut_candidate`` archives must stay archived."""
    root, _, _, _ = project
    fail_crop_for(monkeypatch, "video_0001", g.legacy.PendingSource("injected cut failure"))

    manifest = g.run(root, verification="basic", jobs=1)

    failed = [c for c in manifest["candidates"] if c["source_video_id"] == "video_0001"]
    assert failed and all(c["status"] == "pending" for c in failed), (
        f"an admitted-but-uncut window must stay a recorded pending window, got "
        f"{[c['status'] for c in failed]}")
    assert all("injected cut failure" in c["reason"] for c in failed)
    assert [c for c in manifest["candidates"] if c["status"] == "cropped"], (
        "the other 109 sources must still be cut")
    assert manifest["complete"] is False


# --------------------------------------------------------------------------- #
# 14. ``summary.json`` must state the mode of a fast batch on its own
#     (gap: the summary carried no mode at all)
# --------------------------------------------------------------------------- #

FULL_SUMMARY_KEYS = {
    "scope", "source_count", "source_status", "source_reasons", "strategies",
    "candidate_count", "candidate_status", "roles", "excluded_windows",
    "split_counts", "fold_counts", "complete", "published", "reused_candidates",
    "toolchain", "manual_review",
}


def read_summary(root, directory=OUTPUT):
    return json.loads((root / directory / "summary.json").read_text(encoding="utf-8"))


def summary_mode(summary):
    """The mode a summary reports, under either documented key."""
    record = summary.get("verification")
    if isinstance(record, dict):
        return record.get("mode"), record.get("frame_replay")
    return summary.get("verification_mode"), summary.get("frame_replay")


@pytest.mark.parametrize("mode", FAST_MODES)
def test_fast_batch_summary_declares_the_mode(project, mode):
    root, _, _, _ = project
    g.run(root, verification=mode)

    reported, frame_replay = summary_mode(read_summary(root))

    assert reported == mode, (
        f"summary.json must state that this batch is {mode}, got {read_summary(root)}")
    assert frame_replay == "skipped", (
        "summary.json must state that no frame replay ran, got "
        f"{read_summary(root).get('frame_replay')!r}")


def test_full_batch_summary_keeps_its_exact_key_set(project):
    root, _, _, _ = project
    g.run(root, verification="full")

    summary = read_summary(root)

    assert set(summary) == FULL_SUMMARY_KEYS, (
        "a full batch's summary must not gain or lose a key; "
        f"added {sorted(set(summary) - FULL_SUMMARY_KEYS)}, "
        f"missing {sorted(FULL_SUMMARY_KEYS - set(summary))}")


# --------------------------------------------------------------------------- #
# 15. an explicit ``--jobs 1`` is still an explicit switch
#     (gap: argparse could not tell "given as 1" from "not given")
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("switch", ["--videos-dir", "--audit-only"])
def test_cli_rejects_an_explicit_jobs_one_next_to_a_mode_that_cannot_use_it(tmp_path, switch):
    videos, output = tmp_path / "videos", tmp_path / "out"
    videos.mkdir()
    (videos / "a.mp4").write_bytes(b"synthetic clip")
    arguments = {"--videos-dir": ("--videos-dir", videos, "--output-dir", output),
                 "--audit-only": ("--audit-only", "--output-dir", output)}[switch]

    result = run_cli("--project-root", tmp_path, *arguments, "--jobs", "1")

    assert result.returncode != 0, (
        f"an explicit --jobs 1 must be a usage error next to {switch}, "
        f"got rc=0 with {console(result)!r}")
    assert "cannot be combined" in console(result), console(result)


# --------------------------------------------------------------------------- #
# 16. every candidate record states the mode, whatever happened to it
#     (gap: only a cropped candidate's ``output`` carried the record)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", FAST_MODES)
def test_every_planned_candidate_records_the_skipped_replay(project, mode):
    root, _, _, _ = project

    manifest = g.run(root, plan_only=True, verification=mode)

    candidates = manifest["candidates"]
    assert candidates and all(c["status"] == "planned" for c in candidates)
    for candidate in candidates:
        note = candidate.get("verification") or {}
        assert note.get("mode") == mode, (
            f"candidate {candidate['candidate_id']} carries {note!r}, expected the batch mode")
        assert note.get("frame_replay") == "skipped"
        assert "frame_preserving_replay" not in candidate
        assert "output" not in candidate


def test_a_pending_candidate_records_the_skipped_replay(project, monkeypatch):
    root, _, _, _ = project
    fail_crop_for(monkeypatch, "video_0001", g.legacy.PendingSource("injected cut failure"))

    manifest = g.run(root, verification="basic", jobs=1)

    archived = [c for c in manifest["candidates"] if c["source_video_id"] == "video_0001"]
    assert archived and all(c["status"] == "pending" for c in archived)
    for candidate in archived:
        note = candidate.get("verification") or {}
        assert note.get("mode") == "basic", (
            f"a pending candidate must still record the batch mode, got {note!r}")
        assert note.get("frame_replay") == "skipped"
        assert "output" not in candidate
    cut = cropped(manifest)
    assert cut, "the remaining sources must still be cut"
    for candidate in cut:
        assert candidate["verification"]["mode"] == "basic"
        assert candidate["output"]["verification"]["mode"] == "basic", (
            "the output layer keeps its own record next to the candidate-level one")


def test_a_full_batch_records_no_verification_note_on_any_candidate(project):
    root, _, _, _ = project

    manifest = g.run(root, verification="full")

    candidates = manifest["candidates"]
    assert candidates and all(c["status"] == "cropped" for c in candidates)
    for candidate in candidates:
        assert "verification" not in candidate, (
            f"{candidate['candidate_id']} gained a candidate-level mode block in a full batch: "
            f"{candidate['verification']!r}")
    assert g.core.VERIFIED in manifest_text(root), "a full batch must still carry its frame proofs"
