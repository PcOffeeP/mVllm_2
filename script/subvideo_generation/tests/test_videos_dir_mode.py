"""Red-phase contract for the new "videos directory" input mode.

Each test names one behaviour that `script.subvideo_generation.virtual` and the
`--videos-dir` CLI switch must provide: scanning a directory of source videos,
planning windows through a single policy point, writing an independent schema
batch, and refusing unsafe / ambiguous invocations with the exact wording the
migration contract requires.

No production media is read: synthetic clips are encoded with FFmpeg into a
per-test temporary project. The `data/` tree of the repository is never touched
and `--project-root` always points at a temporary directory.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from script.subvideo_generation.tests.test_generation_contract import digest, encode


REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATE_MODULE = "script.subvideo_generation.generate"
VIRTUAL_MODULE = "script.subvideo_generation.virtual"
PILOT_MODULE = "script.subvideo_generation.pilot.pilot"
OFFICIAL_BATCH = Path("data") / "sub_video"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def import_virtual():
    """Import the videos-dir module; fails loudly (red) until it exists."""
    return importlib.import_module(VIRTUAL_MODULE)


def run_cli(*arguments):
    """Run the real CLI in a subprocess so argparse/exit codes stay observable."""
    return subprocess.run(
        [sys.executable, "-m", GENERATE_MODULE, *[str(a) for a in arguments]],
        cwd=REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")},
    )


def console(result):
    return (result.stdout or "") + (result.stderr or "")


def option_help_block(help_text, option):
    """Return the help text belonging to one option inside the options section."""
    section = help_text.split("options:", 1)[-1]
    match = re.compile(rf"^[ \t]+{re.escape(option)}(?:[ =]|,|$)", re.MULTILINE).search(section)
    assert match, f"{option} is not documented in the CLI --help output"
    rest = section[match.end():]
    following = re.search(r"\n[ \t]+(?=-{1,2}\S)", rest)
    return rest[:following.start()] if following else rest


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_manifest(path, value):
    """Write a batch record the same way the implementation seals its own records."""
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")


def find_key(value, key, path="$"):
    """Recursively collect the paths where `key` occurs in a decoded JSON value."""
    found = []
    if isinstance(value, dict):
        for name, child in value.items():
            where = f"{path}.{name}"
            if name == key:
                found.append(where)
            found.extend(find_key(child, key, where))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_key(child, key, f"{path}[{index}]"))
    return found


def snapshot(output):
    """Bytes of the batch records plus clip names and mtimes (no re-encode check)."""
    videos = Path(output) / "videos"
    clips = {p.name: p.stat().st_mtime_ns for p in sorted(videos.iterdir())} if videos.is_dir() else {}
    return {
        "manifest": (Path(output) / "manifest.json").read_bytes(),
        "summary": (Path(output) / "summary.json").read_bytes(),
        "clips": clips,
    }


def encode_window_source(path, seconds, pattern="testsrc2"):
    """Encode a synthetic clip, replacing any existing file at the same path.

    `-y` is mandatory: FFmpeg 8.1.1 refuses to overwrite an existing output when
    stdin is not a terminal, yet still exits 0, so `check=True` alone would let a
    rewrite silently do nothing (the file would keep its old bytes).
    """
    path = Path(path)
    previous = digest(path) if path.is_file() else None
    encode(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{pattern}=size=96x64:rate=10",
            "-t", str(seconds), "-threads", "1", "-c:v", "libx264", "-crf", "18",
            "-pix_fmt", "yuv420p", str(path)])
    assert path.is_file() and path.stat().st_size > 0, f"FFmpeg wrote no media to {path}"
    if previous is not None:
        assert digest(path) != previous, (
            f"rewriting {path.name} kept the previous bytes; the test setup did not take effect")


# --------------------------------------------------------------------------- #
# fixtures (synthetic media only; module scope keeps encoding cheap)
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    """Two synthetic source clips: 3 s (shorter than a window) and 25 s (tail window)."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg required for the videos-dir mode contract")
    root = tmp_path_factory.mktemp("videos-dir-media")
    directory = root / "inputs" / "videos"
    directory.mkdir(parents=True)
    encode_window_source(directory / "short_03s.mp4", 3)
    encode_window_source(directory / "long_25s.mp4", 25)
    return directory


@pytest.fixture(scope="module")
def batch(videos, tmp_path_factory):
    """One full videos-dir generation, shared by the read-only contract checks."""
    root = tmp_path_factory.mktemp("videos-dir-batch")
    project = root / "project"
    project.mkdir()
    output = project / "virtual_batch"
    result = run_cli("--project-root", project, "--videos-dir", videos, "--output-dir", output)
    return {"result": result, "project": project, "output": output, "videos": videos}


def batch_manifest(batch):
    return load_json(batch["output"] / "manifest.json")


def batch_summary(batch):
    return load_json(batch["output"] / "summary.json")


# --------------------------------------------------------------------------- #
# 0. module contract
# --------------------------------------------------------------------------- #

def test_virtual_module_declares_its_own_schema_and_error_type():
    """Contract: SCHEMA string and VirtualError derives from the pilot error."""
    virtual = import_virtual()
    base = importlib.import_module(PILOT_MODULE)

    assert virtual.SCHEMA == "tensile-virtual-sub-video/1"
    assert issubclass(virtual.VirtualError, base.PilotError)
    assert virtual.VirtualError is not base.PilotError


def test_virtual_run_matches_the_documented_signature():
    """Contract: run(project_root, videos_dir, output_dir, *, plan_only, resume)."""
    virtual = import_virtual()

    parameters = inspect.signature(virtual.run).parameters

    positional = [name for name, p in parameters.items()
                  if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
    assert positional[:3] == ["project_root", "videos_dir", "output_dir"]
    for name in ("plan_only", "resume"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, f"{name} must be keyword-only"
        assert parameters[name].default is False, f"{name} must default to False"


# --------------------------------------------------------------------------- #
# 1. CLI surface
# --------------------------------------------------------------------------- #

def test_cli_help_documents_videos_dir_mode_and_its_relation_to_the_110_source_mode():
    """Contract: --videos-dir exists and its help states it bypasses the 110-source mode."""
    result = run_cli("--help")

    assert result.returncode == 0, console(result)
    assert "--videos-dir" in result.stdout
    block = option_help_block(result.stdout, "--videos-dir")
    assert "110" in block, f"--videos-dir help must mention the 110-source mode it bypasses: {block!r}"


# --------------------------------------------------------------------------- #
# 2./3. the single policy point
# --------------------------------------------------------------------------- #

def test_plan_virtual_windows_emits_full_strided_windows_then_a_tail_window():
    """Contract: 20 s windows every 15 s, tail window instead of dropping the remainder."""
    virtual = import_virtual()
    # Only the three documented keys are supplied: any other key read would KeyError.
    media = {"duration": 47.0, "fps": 10.0, "total_frames": 470}

    windows = virtual.plan_virtual_windows(media)

    assert [round(w["start_seconds"], 6) for w in windows] == [0.0, 15.0, 30.0]
    assert [round(w["end_seconds"] - w["start_seconds"], 6) for w in windows[:2]] == [20.0, 20.0]
    assert round(windows[-1]["end_seconds"], 6) == 47.0
    assert [(w["start_frame"], w["end_frame"]) for w in windows] == [(0, 200), (150, 350), (300, 470)]
    assert [w["sequence"] for w in windows] == [1, 2, 3]


def test_plan_virtual_windows_keeps_a_clip_shorter_than_the_window_as_one_window():
    """Contract: a whole clip under 20 s yields exactly one window 0 -> end, never zero."""
    virtual = import_virtual()
    media = {"duration": 7.0, "fps": 10.0, "total_frames": 70}

    windows = virtual.plan_virtual_windows(media)

    assert len(windows) == 1, "a clip shorter than the target window must not be dropped"
    assert round(windows[0]["start_seconds"], 6) == 0.0
    assert round(windows[0]["end_seconds"], 6) == 7.0, "the short window must not be padded to 20 s"
    assert (windows[0]["start_frame"], windows[0]["end_frame"]) == (0, 70)


# --------------------------------------------------------------------------- #
# 4./5. directory scanning
# --------------------------------------------------------------------------- #

def test_scan_videos_dir_returns_only_top_level_mp4_files_in_name_order(tmp_path):
    """Contract: non-recursive *.mp4 collection, sorted by file name."""
    virtual = import_virtual()
    directory = tmp_path / "videos"
    directory.mkdir()
    (directory / "b.mp4").write_bytes(b"synthetic b")
    (directory / "a.mp4").write_bytes(b"synthetic a")
    (directory / "notes.txt").write_text("not a video", encoding="utf-8")
    (directory / "nested").mkdir()
    (directory / "nested" / "c.mp4").write_bytes(b"synthetic nested c")

    found = virtual.scan_videos_dir(directory)

    assert [Path(p).name for p in found] == ["a.mp4", "b.mp4"]
    assert all(isinstance(p, Path) for p in found), "scan must return Path objects"


def test_scan_videos_dir_rejects_a_missing_directory(tmp_path):
    """Contract wording: 'videos dir not found'."""
    virtual = import_virtual()

    with pytest.raises(virtual.VirtualError) as caught:
        virtual.scan_videos_dir(tmp_path / "does-not-exist")

    assert "videos dir not found" in str(caught.value)


def test_scan_videos_dir_rejects_a_path_that_is_a_file(tmp_path):
    """Contract wording: 'videos dir is not a directory'."""
    virtual = import_virtual()
    path = tmp_path / "single.mp4"
    path.write_bytes(b"synthetic")

    with pytest.raises(virtual.VirtualError) as caught:
        virtual.scan_videos_dir(path)

    assert "videos dir is not a directory" in str(caught.value)


@pytest.mark.parametrize("content", ["empty", "no_mp4"])
def test_scan_videos_dir_rejects_a_directory_without_mp4(tmp_path, content):
    """Contract wording: 'videos dir contains no mp4 files'."""
    virtual = import_virtual()
    directory = tmp_path / content
    directory.mkdir()
    if content == "no_mp4":
        (directory / "readme.md").write_text("no clips here", encoding="utf-8")

    with pytest.raises(virtual.VirtualError) as caught:
        virtual.scan_videos_dir(directory)

    assert "videos dir contains no mp4 files" in str(caught.value)


def test_scan_videos_dir_rejects_symlink_entries(tmp_path):
    """Contract wording: 'videos dir contains symlink'."""
    virtual = import_virtual()
    directory = tmp_path / "videos"
    directory.mkdir()
    (directory / "a.mp4").write_bytes(b"synthetic a")
    target = tmp_path / "outside.mp4"
    target.write_bytes(b"synthetic outside")
    (directory / "link.mp4").symlink_to(target)

    with pytest.raises(virtual.VirtualError) as caught:
        virtual.scan_videos_dir(directory)

    assert "videos dir contains symlink" in str(caught.value)


def test_scan_videos_dir_rejects_a_non_regular_entry_named_like_a_video(tmp_path):
    """Contract wording: 'videos dir contains non-regular entry'."""
    virtual = import_virtual()
    directory = tmp_path / "videos"
    directory.mkdir()
    (directory / "a.mp4").write_bytes(b"synthetic a")
    (directory / "nested.mp4").mkdir()

    with pytest.raises(virtual.VirtualError) as caught:
        virtual.scan_videos_dir(directory)

    assert "videos dir contains non-regular entry" in str(caught.value)


# --------------------------------------------------------------------------- #
# 6./7. CLI argument contract
# --------------------------------------------------------------------------- #

def test_cli_videos_dir_mode_requires_an_explicit_output_dir(videos, tmp_path):
    """Contract wording: 'requires an explicit --output-dir'."""
    result = run_cli("--project-root", tmp_path, "--videos-dir", videos)

    assert result.returncode != 0
    assert "requires an explicit --output-dir" in console(result)


def test_cli_rejects_audit_only_combined_with_videos_dir(videos, tmp_path):
    """Contract wording: 'cannot be combined with --videos-dir'."""
    result = run_cli("--project-root", tmp_path, "--audit-only",
                     "--videos-dir", videos, "--output-dir", tmp_path / "out")

    assert result.returncode != 0
    assert "cannot be combined with --videos-dir" in console(result)


# --------------------------------------------------------------------------- #
# 8. end-to-end batch layout and independent schema
# --------------------------------------------------------------------------- #

def test_batch_videos_match_the_recorded_output_paths(batch):
    """Contract: videos/<stem>_window_NN.mp4 for every candidate, nothing else."""
    result = batch["result"]
    assert result.returncode == 0, console(result)
    manifest = batch_manifest(batch)

    on_disk = {p.name for p in (batch["output"] / "videos").iterdir() if p.is_file()}
    recorded = {Path(c["output_path"]).name for c in manifest["candidates"]}

    assert recorded == on_disk
    assert on_disk == {Path(c["filename"]).name for c in manifest["candidates"]}
    assert all(c["output_path"] == f"videos/{c['filename']}" for c in manifest["candidates"])
    for name in on_disk:
        assert re.fullmatch(r"(short_03s|long_25s)_window_\d{2}\.mp4", name), f"unexpected clip name {name!r}"


def test_batch_manifest_declares_an_unpublished_virtual_batch(batch):
    """Contract: virtual schema, videos_dir input mode, never training/published."""
    result = batch["result"]
    assert result.returncode == 0, console(result)
    manifest = batch_manifest(batch)

    assert manifest["schema"] == "tensile-virtual-sub-video/1"
    assert manifest["input_mode"] == "videos_dir"
    assert manifest["for_training"] is False
    assert manifest["published"] is False
    assert manifest["complete"] is True

    sources = manifest["sources"]
    assert {s["video_id"] for s in sources} == {"short_03s", "long_25s"}
    for source in sources:
        for key in ("video_id", "source_path", "source_sha256", "status"):
            assert key in source, f"source record is missing {key!r}: {sorted(source)}"
        assert source["source_sha256"] == digest(Path(source["source_path"]))
        assert Path(source["source_path"]).name == f"{source['video_id']}.mp4"

    for candidate in manifest["candidates"]:
        for key in ("candidate_id", "filename", "output_path", "source_video_id",
                    "role", "sequence", "start_frame", "end_frame", "status"):
            assert key in candidate, f"candidate record is missing {key!r}: {sorted(candidate)}"
        assert candidate["role"] == "window"
        assert candidate["status"] == "cropped"
        assert candidate["start_frame"] < candidate["end_frame"]
        assert candidate["source_video_id"] in {"short_03s", "long_25s"}

    # 3 s -> one short window; 25 s -> one full window plus the tail window.
    per_source = {key: sum(c["source_video_id"] == key for c in manifest["candidates"])
                  for key in ("short_03s", "long_25s")}
    assert per_source == {"short_03s": 1, "long_25s": 2}


def test_batch_manifest_and_summary_never_carry_folds(batch):
    """Contract: the videos-dir mode has no split, so 'folds' must appear nowhere."""
    result = batch["result"]
    assert result.returncode == 0, console(result)

    manifest = batch_manifest(batch)
    summary = batch_summary(batch)

    assert find_key(manifest, "folds") == []
    assert find_key(summary, "folds") == []


def test_batch_summary_agrees_with_the_manifest(batch):
    """Contract: summary counts and flags restate the manifest."""
    result = batch["result"]
    assert result.returncode == 0, console(result)
    manifest, summary = batch_manifest(batch), batch_summary(batch)

    for key in ("source_count", "source_status", "candidate_count", "candidate_status",
                "complete", "for_training", "published", "input_mode"):
        assert key in summary, f"summary is missing {key!r}: {sorted(summary)}"
    assert summary["source_count"] == len(manifest["sources"])
    assert summary["candidate_count"] == len(manifest["candidates"])
    assert summary["complete"] == manifest["complete"]
    assert summary["for_training"] is False
    assert summary["published"] is False
    assert summary["input_mode"] == "videos_dir"


# --------------------------------------------------------------------------- #
# 9. determinism
# --------------------------------------------------------------------------- #

def test_two_runs_of_the_same_input_produce_identical_candidates(videos, tmp_path):
    """Contract: same input bytes -> same candidate ids and frame ranges."""
    project = tmp_path / "project"
    project.mkdir()
    signatures = []
    for name in ("batch_a", "batch_b"):
        output = project / name
        result = run_cli("--project-root", project, "--videos-dir", videos, "--output-dir", output)
        assert result.returncode == 0, console(result)
        manifest = load_json(output / "manifest.json")
        signatures.append({c["candidate_id"]: (c["start_frame"], c["end_frame"])
                           for c in manifest["candidates"]})

    assert signatures[0], "the deterministic comparison needs at least one candidate"
    assert signatures[0] == signatures[1]


# --------------------------------------------------------------------------- #
# 10./11./12. output reuse, resume and input identity
# --------------------------------------------------------------------------- #

def test_second_run_without_resume_is_refused_and_writes_nothing(batch):
    """Contract wording: 'nonempty output exists'; existing bytes stay untouched."""
    first = batch["result"]
    assert first.returncode == 0, console(first)
    before = snapshot(batch["output"])

    again = run_cli("--project-root", batch["project"],
                    "--videos-dir", batch["videos"], "--output-dir", batch["output"])

    assert again.returncode != 0
    assert "nonempty output exists" in console(again)
    assert snapshot(batch["output"]) == before, "a refused run must not rewrite records or clips"


def test_resume_with_unchanged_inputs_keeps_the_candidates_and_skips_re_encoding(batch):
    """Contract: resume on identical inputs succeeds, encodes nothing, rewrites no clip."""
    first = batch["result"]
    assert first.returncode == 0, console(first)
    before_candidates = {(c["candidate_id"]): (c["start_frame"], c["end_frame"])
                         for c in batch_manifest(batch)["candidates"]}
    before = snapshot(batch["output"])

    resumed = run_cli("--project-root", batch["project"], "--videos-dir", batch["videos"],
                      "--output-dir", batch["output"], "--resume")

    assert resumed.returncode == 0, console(resumed)
    after_candidates = {(c["candidate_id"]): (c["start_frame"], c["end_frame"])
                        for c in batch_manifest(batch)["candidates"]}
    after = snapshot(batch["output"])
    assert after_candidates == before_candidates
    assert after["clips"] == before["clips"], "resume must not re-encode or add clips"


def test_resume_rejects_changed_input_video_bytes(videos, tmp_path):
    """Contract wording: 'virtual resume metadata identity differs'."""
    inputs = tmp_path / "inputs"
    shutil.copytree(videos, inputs)
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"
    first = run_cli("--project-root", project, "--videos-dir", inputs, "--output-dir", output)
    assert first.returncode == 0, console(first)
    before = snapshot(output)

    target = inputs / "short_03s.mp4"
    before_sha = digest(target)
    encode_window_source(target, 4, pattern="testsrc")  # different bytes, still decodable
    assert digest(target) != before_sha

    resumed = run_cli("--project-root", project, "--videos-dir", inputs,
                      "--output-dir", output, "--resume")

    assert resumed.returncode != 0
    assert "virtual resume metadata identity differs" in console(resumed)
    after = snapshot(output)
    assert after["clips"] == before["clips"], "a refused resume must not re-encode or add clips"
    assert after["manifest"] == before["manifest"], "a refused resume must not rewrite the manifest"


# --------------------------------------------------------------------------- #
# 13./14. safety rails and untouched legacy behaviour
# --------------------------------------------------------------------------- #

def test_output_dir_may_not_be_the_official_batch_directory(videos, tmp_path):
    """Contract wording: 'must not be the official batch directory' (fake project root)."""
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    output = project / OFFICIAL_BATCH

    result = run_cli("--project-root", project, "--videos-dir", videos, "--output-dir", output)

    assert result.returncode != 0
    assert "must not be the official batch directory" in console(result)
    assert not output.exists(), "the official batch directory must not be created"


def test_legacy_mode_without_output_dir_does_not_require_one(tmp_path, monkeypatch):
    """Contract: the --output-dir requirement belongs to the videos-dir mode only."""
    generate = importlib.import_module(GENERATE_MODULE)
    calls = []

    def recording_run(project_root, output_dir=None, *, plan_only=False, resume=False):
        calls.append({"project_root": project_root, "output_dir": output_dir,
                      "plan_only": plan_only, "resume": resume})
        return {"schema": "stub", "sources": [], "candidates": [],
                "complete": True, "published": False}

    monkeypatch.setattr(generate, "run", recording_run)
    monkeypatch.setattr(generate, "summarize", lambda manifest: {"stub": True})
    monkeypatch.setattr(sys, "argv", ["generate.py", "--project-root", str(tmp_path)])

    code = generate.main()

    assert code == 0, "the 110-source path must still run without --output-dir"
    assert len(calls) == 1
    assert calls[0]["output_dir"] is None, "legacy mode must keep passing its default output dir"


# --------------------------------------------------------------------------- #
# H1..H7: defects found by independent review of the delivered implementation
# --------------------------------------------------------------------------- #

def test_sources_report_cropped_when_every_window_is_encoded(batch):
    """H1: a source status must state what happened to its clips, never 'planned'."""
    result = batch["result"]
    assert result.returncode == 0, console(result)
    manifest, summary = batch_manifest(batch), batch_summary(batch)

    statuses = {s["video_id"]: s["status"] for s in manifest["sources"]}

    assert statuses == {"short_03s": "cropped", "long_25s": "cropped"}, (
        f"an all-encoded source must report 'cropped', got {statuses}")
    assert all("reason" not in s for s in manifest["sources"]), "a successful source carries no reason"
    assert summary["source_status"] == {"cropped": 2}
    assert manifest["complete"] is True


def test_a_single_unreadable_video_does_not_abort_the_whole_batch(tmp_path):
    """H2: one undecodable mp4 fails its own source, the rest of the batch still runs."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg required for the videos-dir mode contract")
    inputs = tmp_path / "videos"
    inputs.mkdir()
    encode_window_source(inputs / "good_03s.mp4", 3)
    (inputs / "broken.mp4").write_bytes(b"not a valid mp4\n")
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"

    result = run_cli("--project-root", project, "--videos-dir", inputs, "--output-dir", output)

    assert result.returncode == 2, f"an unfinished batch exits 2, not a hard abort: {console(result)}"
    for name in ("manifest.json", "summary.json"):
        assert (output / name).is_file(), f"{name} must exist even though one source failed"
    manifest = load_json(output / "manifest.json")
    summary = load_json(output / "summary.json")
    sources = {s["video_id"]: s for s in manifest["sources"]}
    assert set(sources) == {"broken", "good_03s"}
    assert sources["broken"]["status"] == "failed"
    assert sources["broken"].get("reason"), "a failed source must explain itself"
    assert sources["good_03s"]["status"] == "cropped"
    good_clips = [c for c in manifest["candidates"] if c["source_video_id"] == "good_03s"]
    assert good_clips and all(c["status"] == "cropped" for c in good_clips)
    assert all((output / c["output_path"]).is_file() for c in good_clips)
    assert [c for c in manifest["candidates"] if c["source_video_id"] == "broken"] == []
    assert manifest["complete"] is False
    assert summary["source_status"] == {"cropped": 1, "failed": 1}


def test_resume_finishes_candidates_left_unfinished_by_a_failed_run(videos, tmp_path):
    """H3: --resume continues an incomplete batch instead of refusing it forever.

    The stopped batch is reproduced from disk state only (one candidate rolled back
    to "planned", its clip removed, its source marked failed), so this test does not
    depend on how the implementation wires its encoding callable.
    """
    virtual = import_virtual()
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"
    finished_run = virtual.run(project, videos, output)
    assert finished_run["complete"] is True

    manifest_path = output / "manifest.json"
    manifest = load_json(manifest_path)
    blocked = "long_25s_window_02"
    interrupted = next(c for c in manifest["candidates"] if c["candidate_id"] == blocked)
    untouched = {c["candidate_id"]: c["output_path"] for c in manifest["candidates"]
                 if c["status"] == "cropped" and c["candidate_id"] != blocked}
    assert untouched, "the interrupted batch must already hold finished windows"
    interrupted["status"] = "planned"
    interrupted.pop("output_sha256", None)
    interrupted.pop("output_frames", None)
    (output / interrupted["output_path"]).unlink()
    source = next(s for s in manifest["sources"]
                  if s["video_id"] == interrupted["source_video_id"])
    source["status"] = "failed"
    source["reason"] = "injected: window left unencoded"
    manifest["complete"] = False
    write_manifest(manifest_path, manifest)
    mtimes_before = {cid: (output / path).stat().st_mtime_ns for cid, path in untouched.items()}

    resumed = virtual.run(project, videos, output, resume=True)

    assert resumed["complete"] is True, "resume must finish the remaining candidates"
    assert all(c["status"] == "cropped" for c in resumed["candidates"])
    recovered = next(c for c in resumed["candidates"] if c["candidate_id"] == blocked)
    assert recovered.get("output_sha256"), "the recovered window must record its encoded bytes"
    assert (output / recovered["output_path"]).is_file()
    on_disk = {str(p.relative_to(output)) for p in (output / "videos").iterdir()}
    assert on_disk == {c["output_path"] for c in resumed["candidates"]}, (
        "resume must write exactly the missing window and nothing else")
    for candidate_id, recorded_path in untouched.items():
        assert (output / recorded_path).stat().st_mtime_ns == mtimes_before[candidate_id], (
            f"resume must not re-encode the already finished window {candidate_id}")
    assert {s["video_id"]: s["status"] for s in resumed["sources"]} == {
        "short_03s": "cropped", "long_25s": "cropped"}, "the recovered source must report cropped"


def test_identity_records_the_window_strategy_and_the_virtual_code(videos, tmp_path):
    """H4: the batch identity must pin the window policy and the virtual module."""
    virtual = import_virtual()
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"

    virtual.run(project, videos, output)

    identity = load_json(output / "manifest.json")["identity"]
    assert {"window_seconds", "step_seconds", "role"} <= set(identity.get("strategy", {})), (
        f"identity.strategy must record the window policy, got {identity.get('strategy')!r}")
    assert identity["strategy"]["window_seconds"] == virtual.WINDOW_SECONDS
    assert identity["strategy"]["step_seconds"] == virtual.STEP_SECONDS
    assert identity["strategy"]["role"] == "window"
    code_keys = list(identity.get("code", {}))
    assert any(str(key).endswith("virtual.py") for key in code_keys), (
        f"identity.code must hash the virtual mode module itself, got {code_keys}")


def test_resume_rejects_a_changed_window_strategy(videos, tmp_path, monkeypatch):
    """H4: a different window policy is a different batch identity."""
    virtual = import_virtual()
    base = importlib.import_module(PILOT_MODULE)
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"
    first = virtual.run(project, videos, output)
    assert first["complete"] is True
    before = (output / "manifest.json").read_bytes()

    monkeypatch.setattr(virtual, "WINDOW_SECONDS", virtual.WINDOW_SECONDS + 5)

    with pytest.raises(base.PilotError) as caught:
        virtual.run(project, videos, output, resume=True)

    assert "virtual resume metadata identity differs" in str(caught.value)
    assert (output / "manifest.json").read_bytes() == before, "a refused resume must not rewrite records"


def test_output_dir_may_not_live_inside_the_videos_dir(videos, tmp_path):
    """H5: the batch directory must never be created inside the scanned input directory."""
    inputs = tmp_path / "videos"
    shutil.copytree(videos, inputs)
    project = tmp_path / "project"
    project.mkdir()
    output = inputs / "batch"

    result = run_cli("--project-root", project, "--videos-dir", inputs, "--output-dir", output)

    assert result.returncode == 1, console(result)
    assert "output must not be inside the videos dir" in console(result)
    assert not output.exists(), "a refused output must not be created inside the input directory"


def test_cli_rejects_portable_audit_combined_with_videos_dir(videos, tmp_path):
    """H6: the portable-audit conflict must name the option that was actually passed."""
    result = run_cli("--project-root", tmp_path, "--portable-audit",
                     "--videos-dir", videos, "--output-dir", tmp_path / "out")

    assert result.returncode == 2, console(result)
    assert "--portable-audit cannot be combined with --videos-dir" in console(result)
    assert "--audit-only cannot be combined" not in console(result)


def test_official_code_identity_excludes_the_virtual_mode_module():
    """H7: the 110-source batch identity must not move when the virtual policy changes."""
    generate = importlib.import_module(GENERATE_MODULE)

    identity = generate.code_identity()

    assert "subvideo_generation/generate.py" in identity
    offenders = [key for key in identity if str(key).endswith("virtual.py")]
    assert offenders == [], f"official 110-source identity must not include the virtual mode: {offenders}"


# --------------------------------------------------------------------------- #
# M1..M5: defects found by the second independent review
# --------------------------------------------------------------------------- #

def test_plan_only_marks_every_source_planned_and_fails_nothing(videos, tmp_path):
    """M1: --plan-only encodes nothing, so no source may be reported as failed."""
    project = tmp_path / "project"
    project.mkdir()
    output = project / "plan_only_batch"

    result = run_cli("--project-root", project, "--videos-dir", videos,
                     "--output-dir", output, "--plan-only")

    assert result.returncode == 0, console(result)
    manifest = load_json(output / "manifest.json")
    summary = load_json(output / "summary.json")
    statuses = {s["video_id"]: s["status"] for s in manifest["sources"]}
    assert statuses == {"short_03s": "planned", "long_25s": "planned"}, (
        f"a planned-only source is neither cropped nor failed, got {statuses}")
    assert all(s.get("reason") for s in manifest["sources"]), (
        "a planned-only source must record that nothing was encoded")
    assert summary["source_status"] == {"planned": 2}, (
        f"nothing failed in a plan-only run, got {summary['source_status']}")
    assert manifest["complete"] is False
    assert manifest["candidates"], "planning must still record the windows"
    assert all(c["status"] == "planned" for c in manifest["candidates"])
    assert list((output / "videos").iterdir()) == [], "plan_only must not encode any clip"


def test_an_unreadable_video_is_isolated_instead_of_aborting_the_batch(tmp_path):
    """M2: an unreadable source fails its own record, never the whole batch."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg required for the videos-dir mode contract")
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions, the fixture cannot express this case")
    inputs = tmp_path / "videos"
    inputs.mkdir()
    encode_window_source(inputs / "good_03s.mp4", 3)
    locked = inputs / "locked_03s.mp4"
    encode_window_source(locked, 3)
    locked.chmod(0o000)
    try:
        project = tmp_path / "project"
        project.mkdir()
        output = project / "batch"

        result = run_cli("--project-root", project, "--videos-dir", inputs, "--output-dir", output)

        assert result.returncode == 2, f"an unfinished batch exits 2, not a hard abort: {console(result)}"
        manifest = load_json(output / "manifest.json")
        summary = load_json(output / "summary.json")
        sources = {s["video_id"]: s for s in manifest["sources"]}
        assert set(sources) == {"locked_03s", "good_03s"}
        assert sources["locked_03s"]["status"] == "failed"
        assert sources["locked_03s"].get("reason"), "an unreadable source must explain itself"
        assert sources["locked_03s"].get("source_sha256") is None, (
            "an unreadable source cannot claim a source hash")
        assert "locked_03s.mp4" not in manifest["identity"]["videos"], (
            "identity must not claim to pin a file whose bytes were never hashed")
        assert sources["good_03s"]["status"] == "cropped"
        good_clips = [c for c in manifest["candidates"] if c["source_video_id"] == "good_03s"]
        assert good_clips and all(c["status"] == "cropped" for c in good_clips)
        assert all((output / c["output_path"]).is_file() for c in good_clips)
        assert [c for c in manifest["candidates"] if c["source_video_id"] == "locked_03s"] == []
        assert manifest["complete"] is False
        assert summary["source_status"] == {"cropped": 1, "failed": 1}
    finally:
        locked.chmod(0o600)


def test_resume_after_plan_only_clears_the_plan_only_flag(videos, tmp_path):
    """M3: encoding a plan-only batch makes it a real batch, plan_only must follow."""
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"
    planned = run_cli("--project-root", project, "--videos-dir", videos,
                      "--output-dir", output, "--plan-only")
    assert planned.returncode == 0, console(planned)
    assert list((output / "videos").iterdir()) == []

    resumed = run_cli("--project-root", project, "--videos-dir", videos,
                      "--output-dir", output, "--resume")

    assert resumed.returncode == 0, console(resumed)
    manifest = load_json(output / "manifest.json")
    summary = load_json(output / "summary.json")
    assert manifest["plan_only"] is False, "a batch that encoded every clip is no longer plan-only"
    assert manifest["complete"] is True
    assert {s["video_id"]: s["status"] for s in manifest["sources"]} == {
        "short_03s": "cropped", "long_25s": "cropped"}
    assert all(c["status"] == "cropped" for c in manifest["candidates"])
    assert all((output / c["output_path"]).is_file() for c in manifest["candidates"])
    assert summary["complete"] is True
    assert summary["source_status"] == {"cropped": 2}
    assert summary["candidate_status"] == {"cropped": len(manifest["candidates"])}


def test_resumed_sources_carry_the_same_media_fields_as_fresh_ones(videos, tmp_path, monkeypatch):
    """M4: a source recovered by resume must look like a source planned fresh."""
    virtual = import_virtual()
    base = importlib.import_module(PILOT_MODULE)
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"
    real_probe = virtual.aligned.probe_video
    failing = {"path": (videos / "short_03s.mp4").resolve(), "active": True}

    def flaky_probe(path, *args, **kwargs):
        if failing["active"] and Path(path).resolve() == failing["path"]:
            raise base.PilotError("injected probe failure")
        return real_probe(path, *args, **kwargs)

    monkeypatch.setattr(virtual.aligned, "probe_video", flaky_probe)
    first = virtual.run(project, videos, output)

    assert first["complete"] is False
    blocked = next(s for s in first["sources"] if s["video_id"] == "short_03s")
    assert blocked["status"] == "failed" and blocked.get("reason")
    failing["active"] = False

    resumed = virtual.run(project, videos, output, resume=True)

    assert resumed["complete"] is True
    sources = {s["video_id"]: s for s in resumed["sources"]}
    media_fields = ("total_frames", "fps", "duration")
    healthy = {name for name in media_fields if name in sources["long_25s"]}
    recovered = {name for name in media_fields if name in sources["short_03s"]}
    assert healthy == set(media_fields), "a freshly planned source must record its media fields"
    assert recovered == healthy, (
        f"a source recovered by resume must record the same media fields as a fresh one: "
        f"{sorted(recovered)} != {sorted(healthy)}")
    assert sources["short_03s"]["status"] == "cropped"


def test_identity_pins_the_shared_media_pipeline(videos, tmp_path):
    """M5: the batch identity must pin the probe/crop pipeline it actually used."""
    virtual = import_virtual()
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"

    virtual.run(project, videos, output)

    code = load_json(output / "manifest.json")["identity"]["code"]
    keys = list(code)
    for filename in ("virtual.py", "pilot.py", "aligned.py"):
        located = [key for key in keys if str(key).endswith(filename)]
        assert located, (
            f"identity.code must pin {filename}, got {keys}")
        for key in located:
            assert isinstance(code[key], str) and re.fullmatch(r"[0-9a-f]{64}", code[key]), (
                f"identity.code[{key!r}] must be a sha256 hex digest, got {code[key]!r}")
