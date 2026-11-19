"""Contract for writing the sub-video audit record to disk.

The capability under test is an explicit ``--write-audit`` / ``write_audit_record()``
that persists the audit verdict as the record schema already on disk, atomically,
and only for the batch that was actually audited and only with the validation that
was actually performed.

Sections 1-8 pin the record's content, its refusals and the CLI switch surface.
Sections 9-13 pin the four properties a naive implementation can violate while
still looking green: (A) the record must reach ``audit.json`` through a staged
temporary file that is moved into place, (B) both digests must describe the bytes
that are on disk rather than a canonical re-serialisation of the parsed objects,
(C) a ``basic`` batch must record exactly the basic validation and no frame-level
replay receipts, and (D) one CLI write must audit the batch once, inside the same
batch lock critical section that replaces the record.

Every batch here is synthetic (110 sources, media IO faked by the shared
``project`` fixture); no production media, label or record file is read or
written. The document schema below is restated from the single existing record
(``data/sub_video/audit.json``) instead of importing it, so a schema drift fails
here rather than silently following the implementation.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import types

import pytest

from script.subvideo_generation.pilot.pilot import PilotError


# --------------------------------------------------------------------------- #
# the record schema, restated from the only existing record
# --------------------------------------------------------------------------- #

AUDIT_SCHEMA = "tensile-unified-sub-video-audit/1"
LABEL_STATUS = "candidate_labels_only_unreviewed"
DESCRIPTION = "候选标签是初值；所有片段须根据画面由人工审核，覆盖片段不推测事件或标签。"
ISSUE_DETACH_AFTER_FRACTURE = "未断裂片段的断后脱夹需复核"
ISSUE_UNBROKEN_VS_EXPLOSIVE = "未断裂与爆炸性断裂互斥"

RECORD_FIELDS = {
    "schema", "manifest_sha256", "checked_sources", "checked_candidates",
    "source_replays_recorded", "clip_replays_recorded", "generation_validation",
    "candidates_needing_attention", "issue_counts", "label_status", "description",
    "candidates",
}
# The record also carries one hand-written note block for the special source
# (``video_0093``). It is human prose that no generic writer can derive from a
# synthetic batch, so it is not demanded here; anything else added on top of the
# fields below is tolerated because the reader ignores unknown top-level keys.
GENERATION_VALIDATION_FIELDS = {"method", "scope", "validated_outputs",
                                "run_summary_sha256", "limitations"}
CANDIDATE_FIELDS = {"candidate_id", "source_video_id", "scope", "issues"}
# The three files a complete batch already has; a record is the only thing a write
# may add, and a failed write must leave nothing else behind.
BATCH_ENTRIES = {"manifest.json", "summary.json", "videos"}
AUDIT_STATUS = "current_bytes_and_planned_inventory_verified"
RECORD_NAME = "audit.json"
INJECTED_FAILURE = "synthetic final move failure"
# What a ``basic`` batch may honestly claim. Restated here instead of read from
# ``audit_outputs`` so that a weakened or strengthened declaration in the record
# has to disagree with this list. ``not_pinned_toolchain`` is appended by the
# audit whenever the replay toolchain is not the pinned one (always true behind
# the fixture's synthetic media boundary), so it is checked separately.
BASIC_LIMITATIONS = ["no_frame_level_replay", "no_source_timeline_replay",
                     "no_clip_frame_correspondence", "not_new_frame_replay",
                     "not_human_label_review", "not_data_publication"]
TOOLCHAIN_LIMITATION = "not_pinned_toolchain"
# Declarations that would be stronger than a basic batch actually performed.
OVERCLAIMS = ("full_output_decode_and_current_receipts",
              "byte_receipt_and_source_timeline_only",
              "full_frame_replay_verified")
RECORD_TYPES = {"schema": str, "manifest_sha256": str, "checked_sources": int,
                "checked_candidates": int, "source_replays_recorded": int,
                "clip_replays_recorded": int, "generation_validation": dict,
                "candidates_needing_attention": int, "issue_counts": dict,
                "label_status": str, "description": str, "candidates": list}

# The sources whose annotations this module retags before the batch is cut, so the
# record has to reproduce a known a/b/c/control shape of the two issue criteria.
DETACH_ONLY = "video_0001"     # 未断裂 source with 现象_断后脱夹=是
EXPLOSIVE_ONLY = "video_0004"  # fracture source with 异常_爆炸性断裂=是
BOTH_ISSUES = "video_0007"     # both of the above on one source
CONTROL = "video_0010"         # neither

FRACTURE_RETAG = {"断裂状态": "发生断裂", "断裂模式": "爆炸性断裂",
                  "异常_爆炸性断裂": "是", "断裂帧_前": "29", "断裂帧_后": "30"}
RETAGGED = {
    DETACH_ONLY: {"现象_断后脱夹": "是"},
    EXPLOSIVE_ONLY: dict(FRACTURE_RETAG),
    BOTH_ISSUES: dict(FRACTURE_RETAG, **{"现象_断后脱夹": "是"}),
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def sha256_of(path):
    """Independent digest of a file's bytes; the writer's own helper is never reused."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retag_annotations(root):
    """Give a few sources the annotation shape the audit is supposed to flag."""
    path = Path(root) / "data" / "annotation-table-full.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        change = RETAGGED.get(row["id"])
        if change:
            row.update(change)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return {row["id"] for row in rows}


def issues_from_labels(labels):
    """The two criteria, read from the label paths the review server uses.

    ``断后脱夹`` lives under ``断裂现象``, ``爆炸性断裂`` under ``异常情况``, and both
    criteria only fire for a candidate labelled 未断裂.
    """
    if labels.get("断裂状态") != "未断裂":
        return []
    issues = []
    if (labels.get("断裂现象") or {}).get("断后脱夹") == "是":
        issues.append(ISSUE_DETACH_AFTER_FRACTURE)
    if (labels.get("异常情况") or {}).get("爆炸性断裂") == "是":
        issues.append(ISSUE_UNBROKEN_VS_EXPLOSIVE)
    return issues


def expected_issues(manifest):
    """``{candidate_id: [issue, ...]}`` reconstructed from the batch's own labels."""
    return {candidate["candidate_id"]: issues_from_labels(candidate["candidate_labels"])
            for candidate in manifest["candidates"]}


def read_record(output):
    return json.loads((Path(output) / "audit.json").read_text(encoding="utf-8"))


def read_manifest(output):
    return json.loads((Path(output) / "manifest.json").read_text(encoding="utf-8"))


def entries_of(output):
    """Every name in the batch directory, so a half record or a stray temp file shows up."""
    return {path.name for path in Path(output).iterdir()}


def run_cli(g, monkeypatch, *arguments):
    """Run the real ``main()`` in this process so the fixture's media doubles apply."""
    monkeypatch.setattr(sys, "argv", ["generate", *[str(argument) for argument in arguments]])
    try:
        return g.main()
    except SystemExit as exit_:  # argparse usage errors, and ``parser.exit`` on refusal
        return exit_.code


def sentinel_record(marker):
    return {"schema": "sentinel-write-must-not-happen", "marker": marker}


def canonical_bytes(value):
    """The canonical serialisation, restated: what an in-memory digest would hash."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def canonical_digest_of(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def re_serialise(path):
    """Rewrite a JSON file with different bytes and identical meaning."""
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    Path(path).write_text(json.dumps(value, ensure_ascii=True, separators=(",", ":")),
                          encoding="utf-8")


def caused_by(exception, text):
    """Whether a raised error, or the error it was raised from, mentions ``text``."""
    seen = set()
    while exception is not None and id(exception) not in seen:
        seen.add(id(exception))
        if text in str(exception):
            return True
        exception = exception.__cause__ or exception.__context__
    return False


def watch_record_moves(monkeypatch, *, fail=False, extra=None):
    """Observe (and optionally break) the final move that lands the record.

    The fault is injected at the *last* step, after the record's bytes have been
    staged, so an implementation that writes ``audit.json`` in place instead of
    moving a staged file never reaches this hook and cannot pass the callers.
    ``os.rename`` is intercepted as well, so a staged write is caught whichever
    of the two moves it uses; every other destination is passed straight through.
    """
    moves = []
    real = {"replace": os.replace, "rename": os.rename}

    def make(real_move):
        def hook(src, dst, *args, **kwargs):
            if Path(dst).name != RECORD_NAME:
                return real_move(src, dst, *args, **kwargs)
            entry = {"source": Path(src), "target": Path(dst),
                     "staged": Path(src).is_file()}
            if extra is not None:
                entry.update(extra())
            moves.append(entry)
            if fail:
                raise OSError(INJECTED_FAILURE)
            return real_move(src, dst, *args, **kwargs)
        return hook

    monkeypatch.setattr(os, "replace", make(real["replace"]))
    monkeypatch.setattr(os, "rename", make(real["rename"]))
    return moves


AUDIT_ENTRY = re.compile("audit", re.IGNORECASE)


def trace_audits_and_locks(monkeypatch, g):
    """Count how often the batch is really audited, and follow the batch lock.

    Every module-level function whose name mentions the audit is wrapped, because
    the audit may be reached through a router (``audit_batch``), through the two
    functions that do the work (``audit_outputs``, ``audit_content``), or through
    an unlocked body that a lock-taking wrapper delegates to. The wrappers build a
    call tree instead of judging names: a call that made no further audit call of
    its own *is* one execution of the audit work. "The batch was audited once" is
    therefore counted independently of which name routed the call, and a second
    execution in the same CLI call shows up as a second leaf.

    Each wrapped call also collects the batch-lock tokens that were held at any
    point while it ran, so "the audit happened inside the critical section that
    replaced the record" is checkable without assuming which call took the lock:
    the tokens of every execution must still be held when the record is moved.
    """
    state = {"calls": [], "active": [], "acquisitions": []}
    stack = []

    def wrap(name, original):
        def traced(*args, **kwargs):
            node = {"entry": name, "locks": set(state["active"]), "children": []}
            (stack[-1]["children"] if stack else state["calls"]).append(node)
            stack.append(node)
            try:
                return original(*args, **kwargs)
            finally:
                stack.pop()
        return traced

    for name, value in list(vars(g).items()):
        if isinstance(value, types.FunctionType) and AUDIT_ENTRY.search(name):
            monkeypatch.setattr(g, name, wrap(name, value))
    real_lock = g.base._run_lock

    @contextlib.contextmanager
    def tracked_lock(output):
        with real_lock(output):
            token = object()
            state["active"].append(token)
            state["acquisitions"].append(token)
            for node in stack:
                node["locks"].add(token)
            try:
                yield
            finally:
                state["active"].remove(token)

    monkeypatch.setattr(g.base, "_run_lock", tracked_lock)
    return state


def audit_executions(state):
    """The traced calls that did the audit work themselves, i.e. its executions."""
    def leaves(nodes):
        found = []
        for node in nodes:
            found.extend(leaves(node["children"]) if node["children"] else [node])
        return found

    return leaves(state["calls"])


# --------------------------------------------------------------------------- #
# one batch for the whole module; every test starts from the pristine copy
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def generated_batch(tmp_path_factory):
    """Cut one complete 110-source batch and keep an untouched copy of it.

    The shared ``project`` fixture is function scoped, so its body is called
    directly with a module-scoped monkeypatch: building the batch costs far more
    than auditing it, and a green run has to stay inside a few minutes.
    """
    from script.subvideo_generation.tests.conftest import project

    workspace = tmp_path_factory.mktemp("audit-record")
    patcher = pytest.MonkeyPatch()
    try:
        root, g, _descriptions, _encoded = project.__wrapped__(workspace / "project", patcher)
        retag_annotations(root)
        manifest = g.run(root)
        assert manifest["complete"] is True, "the fixture must produce a complete batch"
        output = root / "data" / "sub_video"
        pristine = tmp_path_factory.mktemp("audit-record-pristine") / "sub_video"
        shutil.copytree(output, pristine)
        yield types.SimpleNamespace(root=root, g=g, output=output, pristine=pristine)
    finally:
        patcher.undo()


@pytest.fixture
def batch(generated_batch):
    """A pristine, complete batch: audits may write, tamper and refuse freely."""
    output = generated_batch.output
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(generated_batch.pristine, output)
    return generated_batch


# --------------------------------------------------------------------------- #
# 1. the normal write has the schema the downstream reader already accepts
# --------------------------------------------------------------------------- #

def test_write_audit_records_the_documented_schema(batch, monkeypatch, capsys):
    manifest = read_manifest(batch.output)

    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root, "--audit-only", "--write-audit")

    assert code == 0, f"a valid batch must be written, got {capsys.readouterr()}"
    record = read_record(batch.output)
    assert RECORD_FIELDS <= set(record), (
        f"the record is missing {sorted(RECORD_FIELDS - set(record))}")
    assert record["schema"] == AUDIT_SCHEMA
    assert record["label_status"] == LABEL_STATUS
    assert record["description"] == DESCRIPTION
    assert {name: type(record[name]) for name in RECORD_TYPES} == RECORD_TYPES, (
        "every documented field must keep its type, got "
        f"{ {name: type(record[name]).__name__ for name in RECORD_TYPES} }")
    assert set(record["generation_validation"]) == GENERATION_VALIDATION_FIELDS, (
        "generation_validation must keep its five keys, got "
        f"{sorted(record['generation_validation'])}")
    assert record["checked_sources"] == len(manifest["sources"])
    assert record["checked_candidates"] == len(manifest["candidates"])
    for entry in record["candidates"]:
        assert set(entry) == CANDIDATE_FIELDS, (
            f"candidate entries carry exactly {sorted(CANDIDATE_FIELDS)}, got {sorted(entry)}")


# --------------------------------------------------------------------------- #
# 2. both digests are taken from the bytes that are actually on disk
# --------------------------------------------------------------------------- #

def test_write_audit_hashes_the_batch_bytes_it_audited(batch):
    record = batch.g.write_audit_record(batch.root)

    assert record["manifest_sha256"] == sha256_of(batch.output / "manifest.json"), (
        "manifest_sha256 must be the digest of the manifest.json currently on disk")
    assert record["generation_validation"]["run_summary_sha256"] == sha256_of(
        batch.output / "summary.json"), (
        "run_summary_sha256 must be the digest of the summary.json currently on disk")
    assert read_record(batch.output) == record, (
        "the returned record must be exactly what was written")


# --------------------------------------------------------------------------- #
# 3. the issue criteria are unions over the hit candidates, not sums over hits
# --------------------------------------------------------------------------- #

def test_write_audit_counts_each_criterion_once_per_hit_candidate(batch):
    manifest = read_manifest(batch.output)
    expected = expected_issues(manifest)
    by_source = {}
    for candidate in manifest["candidates"]:
        issues = expected[candidate["candidate_id"]]
        if not issues:
            continue
        hits = by_source.setdefault(candidate["source_video_id"], {"detach": 0, "explosive": 0, "both": 0})
        if len(issues) == 2:
            hits["both"] += 1
        elif issues == [ISSUE_DETACH_AFTER_FRACTURE]:
            hits["detach"] += 1
        else:
            hits["explosive"] += 1
    only_detach = by_source.get(DETACH_ONLY, {}).get("detach", 0)
    only_explosive = by_source.get(EXPLOSIVE_ONLY, {}).get("explosive", 0)
    both = by_source.get(BOTH_ISSUES, {}).get("both", 0)

    assert only_detach > 0 and only_explosive > 0 and both > 0, (
        f"the fixture must produce all three hit shapes, got {by_source}")

    record = batch.g.write_audit_record(batch.root)

    assert record["issue_counts"][ISSUE_DETACH_AFTER_FRACTURE] == only_detach + both, (
        "a candidate that hits both criteria counts once per criterion")
    assert record["issue_counts"][ISSUE_UNBROKEN_VS_EXPLOSIVE] == only_explosive + both
    assert record["candidates_needing_attention"] == only_detach + only_explosive + both, (
        "a candidate that hits both criteria is still one candidate needing attention")
    assert len(record["candidates"]) == only_detach + only_explosive + both, (
        "only candidates with at least one issue belong in the record")


def test_write_audit_lists_the_hit_candidates_with_their_source_issues(batch):
    manifest = read_manifest(batch.output)
    expected = expected_issues(manifest)
    candidates = {candidate["candidate_id"]: candidate for candidate in manifest["candidates"]}

    record = batch.g.write_audit_record(batch.root)

    recorded = {entry["candidate_id"]: entry for entry in record["candidates"]}
    assert set(recorded) == {name for name, issues in expected.items() if issues}, (
        "the recorded candidate list must be exactly the candidates that hit a criterion")
    assert CONTROL not in {candidates[name]["source_video_id"] for name in recorded}, (
        f"the control source {CONTROL} hits neither criterion and must not be listed")
    for name, entry in recorded.items():
        candidate = candidates[name]
        assert entry["source_video_id"] == candidate["source_video_id"]
        assert entry["scope"] == candidate["scope"]
        assert sorted(entry["issues"]) == sorted(expected[name]), (
            f"{name} must carry its own source-label issues, got {entry['issues']}")


# --------------------------------------------------------------------------- #
# 4. a batch that is not the audited batch is refused, and nothing is written
# --------------------------------------------------------------------------- #

def test_identity_mismatch_is_refused_and_the_existing_record_is_untouched(batch):
    sentinel = sentinel_record("identity-mismatch")
    (batch.output / "audit.json").write_text(json.dumps(sentinel), encoding="utf-8")
    manifest_path = batch.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["identity"]["rules"]["digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PilotError) as error:
        batch.g.write_audit_record(batch.root, batch.output, replace=True)

    assert "digest differs" in str(error.value), (
        f"the refusal must name the changed identity, got {error.value}")
    assert json.loads((batch.output / "audit.json").read_text(encoding="utf-8")) == sentinel, (
        "a refused audit must leave the previous record byte for byte")


def test_cli_reports_an_identity_mismatch_instead_of_writing(batch, monkeypatch, capsys):
    manifest_path = batch.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["identity"]["inputs"] = {"data/other.csv": "1" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root,
                   "--audit-only", "--write-audit")

    assert code not in (0, None), "a refused write must exit non-zero"
    assert "identity differs" in capsys.readouterr().err, (
        "stderr must explain why the record was refused")
    assert not (batch.output / "audit.json").exists(), "a refused audit must not create a record"


# --------------------------------------------------------------------------- #
# 5. an existing record needs the explicit replace switch
# --------------------------------------------------------------------------- #

def test_existing_record_is_refused_without_replace(batch):
    sentinel_text = json.dumps(sentinel_record("do-not-overwrite"), ensure_ascii=False, indent=2)
    (batch.output / "audit.json").write_text(sentinel_text, encoding="utf-8")

    with pytest.raises(PilotError) as error:
        batch.g.write_audit_record(batch.root, batch.output)

    assert "audit.json" in str(error.value), (
        f"the refusal must name the record it refused to overwrite, got {error.value}")
    assert (batch.output / "audit.json").read_text(encoding="utf-8") == sentinel_text


def test_replace_audit_overwrites_the_existing_record(batch, monkeypatch, capsys):
    (batch.output / "audit.json").write_text(json.dumps(sentinel_record("stale"), indent=2),
                                             encoding="utf-8")

    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root,
                   "--audit-only", "--write-audit", "--replace-audit")

    assert code == 0, f"--replace-audit must allow the overwrite, got {capsys.readouterr()}"
    record = read_record(batch.output)
    assert "marker" not in record, "the stale record must be gone"
    assert record["manifest_sha256"] == sha256_of(batch.output / "manifest.json"), (
        "the replaced record must describe the batch that is on disk now")


# --------------------------------------------------------------------------- #
# 6. the write is atomic: a failed write leaves no half record and no litter
# --------------------------------------------------------------------------- #

def _fail_when_the_record_is_serialised(monkeypatch, base):
    """Break only the record's own serialisation, so the audit run stays intact."""
    original = base.canonical_bytes

    def canonical_bytes(value):
        if isinstance(value, dict) and value.get("schema") == AUDIT_SCHEMA:
            raise RuntimeError("synthetic atomic write failure")
        return original(value)

    monkeypatch.setattr(base, "canonical_bytes", canonical_bytes)


def test_a_failed_atomic_write_leaves_no_partial_record(batch, monkeypatch):
    _fail_when_the_record_is_serialised(monkeypatch, batch.g.base)

    with pytest.raises((PilotError, RuntimeError)):
        batch.g.write_audit_record(batch.root, batch.output)

    assert entries_of(batch.output) == BATCH_ENTRIES, (
        f"a failed write must add no record and no temporary file, got {entries_of(batch.output)}")


def test_a_failed_atomic_write_keeps_the_previous_record(batch, monkeypatch):
    sentinel_text = json.dumps(sentinel_record("survives-failure"), indent=2)
    (batch.output / "audit.json").write_text(sentinel_text, encoding="utf-8")
    _fail_when_the_record_is_serialised(monkeypatch, batch.g.base)

    with pytest.raises((PilotError, RuntimeError)):
        batch.g.write_audit_record(batch.root, batch.output, replace=True)

    assert (batch.output / "audit.json").read_text(encoding="utf-8") == sentinel_text, (
        "a failed replacement must not damage the record it was replacing")
    assert entries_of(batch.output) == BATCH_ENTRIES | {"audit.json"}, (
        f"a failed write must leave no temporary file behind, got {entries_of(batch.output)}")


# --------------------------------------------------------------------------- #
# 7. without --write-audit nothing is persisted
# --------------------------------------------------------------------------- #

def test_audit_only_without_write_audit_prints_and_persists_nothing(batch, monkeypatch, capsys):
    assert not (batch.output / "audit.json").exists(), "the fixture must start without a record"

    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root, "--audit-only")

    printed = capsys.readouterr()
    assert code == 0, printed
    audit = json.loads(printed.out)
    assert audit["status"] == AUDIT_STATUS, (
        f"stdout must stay the audit verdict, got {printed.out[:200]!r}")
    assert not (batch.output / "audit.json").exists(), (
        "printing the audit must not write the record")


# --------------------------------------------------------------------------- #
# 8. the new switches only exist in the combinations they are meaningful in
# --------------------------------------------------------------------------- #

ILLEGAL_COMBINATIONS = {
    "plan-only": ("--audit-only", "--plan-only", "--write-audit"),
    "resume": ("--audit-only", "--resume", "--write-audit"),
    "verification": ("--audit-only", "--verification", "full", "--write-audit"),
    "jobs": ("--audit-only", "--jobs", "2", "--write-audit"),
    "videos-dir": ("--videos-dir", "CLIPS", "--output-dir", "OUTPUT", "--write-audit"),
    "replace-without-write": ("--audit-only", "--replace-audit"),
}


@pytest.mark.parametrize("name", sorted(ILLEGAL_COMBINATIONS))
def test_cli_rejects_an_illegal_write_switch_combination(tmp_path, monkeypatch, capsys, name):
    clips, output = tmp_path / "clips", tmp_path / "output"
    clips.mkdir()
    arguments = [clips if item == "CLIPS" else output if item == "OUTPUT" else item
                 for item in ILLEGAL_COMBINATIONS[name]]

    from script.subvideo_generation import generate as g
    code = run_cli(g, monkeypatch, "--project-root", tmp_path, *arguments)

    stderr = capsys.readouterr().err
    assert code == 2, f"{name} must be an argparse usage error, got rc={code} with {stderr!r}"
    assert "unrecognized arguments" not in stderr, (
        f"{name} must be rejected by the switch's own rule, not by an unknown option: {stderr!r}")
    assert re.search(r"cannot be combined|requires|conflict|mutually|not allowed", stderr), (
        f"{name} must be reported as a conflicting combination, got {stderr!r}")


# --------------------------------------------------------------------------- #
# 9. (A) the record reaches audit.json through a staged file moved into place
# --------------------------------------------------------------------------- #
# A write that opens audit.json and writes into it has no temporary file to move,
# so it never reaches 9's hook: the failure injected below would not happen, the
# call would not raise, and both tests would fail. A record that is serialised
# from memory into the destination also leaves a half file behind when it breaks
# mid-way; here the break is at the move, i.e. after the bytes exist.

def test_a_failed_record_move_leaves_no_new_record_and_no_temporary_file(batch, monkeypatch):
    moves = watch_record_moves(monkeypatch, fail=True)

    with pytest.raises(Exception) as error:
        batch.g.write_audit_record(batch.root, batch.output)

    assert moves, ("the record must be staged and moved into place; nothing was moved, so "
                   "audit.json is written in place")
    assert all(move["staged"] for move in moves), (
        f"the failure must land after the record's bytes were staged, got {moves}")
    assert isinstance(error.value, OSError) or caused_by(error.value, INJECTED_FAILURE), (
        f"the final move's failure must reach the caller, got {error.value!r}")
    assert not (batch.output / RECORD_NAME).exists(), (
        "a failed move must not leave an audit.json behind")
    assert entries_of(batch.output) == BATCH_ENTRIES, (
        f"a failed move must clean up its staged file, got {entries_of(batch.output)}")


def test_a_failed_record_move_keeps_the_previous_record(batch, monkeypatch):
    sentinel_text = json.dumps(sentinel_record("survives-a-failed-move"), indent=2)
    (batch.output / RECORD_NAME).write_text(sentinel_text, encoding="utf-8")
    moves = watch_record_moves(monkeypatch, fail=True)

    with pytest.raises(Exception):
        batch.g.write_audit_record(batch.root, batch.output, replace=True)

    assert moves, "a replacement must also be staged and moved into place"
    assert (batch.output / RECORD_NAME).read_text(encoding="utf-8") == sentinel_text, (
        "a failed move must leave the record it was replacing byte for byte")
    assert entries_of(batch.output) == BATCH_ENTRIES | {RECORD_NAME}, (
        f"a failed move must clean up its staged file, got {entries_of(batch.output)}")


# --------------------------------------------------------------------------- #
# 10. (B) both digests describe the bytes on disk, not a canonical rewrite
# --------------------------------------------------------------------------- #
# The batch's own manifest.json / summary.json are re-serialised with identical
# meaning and different bytes. The audit still accepts them (it compares parsed
# objects), so a digest taken from a canonical re-serialisation of the parsed
# objects is *not* the digest of the file, and the assertions below fail.

def test_record_digests_describe_the_bytes_on_disk_not_a_canonical_rewrite(batch):
    for name in ("manifest.json", "summary.json"):
        before = sha256_of(batch.output / name)
        re_serialise(batch.output / name)
        assert sha256_of(batch.output / name) != before, f"{name} must change bytes"
        assert sha256_of(batch.output / name) != canonical_digest_of(batch.output / name), (
            f"{name} on disk must differ from its canonical serialisation, else this test is green "
            "for the wrong reason")
    manifest_on_disk = sha256_of(batch.output / "manifest.json")
    summary_on_disk = sha256_of(batch.output / "summary.json")

    record = batch.g.write_audit_record(batch.root, batch.output)

    assert record["manifest_sha256"] == manifest_on_disk, (
        "manifest_sha256 must be the digest of the manifest.json bytes on disk")
    assert record["generation_validation"]["run_summary_sha256"] == summary_on_disk, (
        "run_summary_sha256 must be the digest of the summary.json bytes on disk")
    assert record["manifest_sha256"] != canonical_digest_of(batch.output / "manifest.json"), (
        "a digest of a canonical re-serialisation is not the digest of the audited bytes")
    assert (record["generation_validation"]["run_summary_sha256"]
            != canonical_digest_of(batch.output / "summary.json")), (
        "a digest of a canonical re-serialisation is not the digest of the audited bytes")


# --------------------------------------------------------------------------- #
# 11. (C) a basic batch declares exactly the validation it performed
# --------------------------------------------------------------------------- #
# The fixture cuts a ``basic`` batch: encoded output bytes and their metadata are
# checked, no frame is replayed in either direction. A record that copies the
# stronger declaration of an older full batch (``full_output_decode_and_current_
# receipts``, ``110``/``1621`` receipts) has to fail here.

def test_basic_batch_record_declares_only_basic_validation(batch):
    record = batch.g.write_audit_record(batch.root, batch.output)
    validation = record["generation_validation"]

    assert validation["scope"] == "output_bytes_and_metadata_only", (
        f"a basic batch may not claim {validation['scope']!r}")
    limitations = [item for item in validation["limitations"] if item != TOOLCHAIN_LIMITATION]
    assert limitations == BASIC_LIMITATIONS, (
        f"a basic batch's limitations must be exactly {BASIC_LIMITATIONS}, got {limitations}")
    assert set(validation["limitations"]) <= set(BASIC_LIMITATIONS) | {TOOLCHAIN_LIMITATION}, (
        f"the record claims limitations this batch does not have: {validation['limitations']}")
    text = json.dumps(record, ensure_ascii=False)
    for overclaim in OVERCLAIMS:
        assert overclaim not in text, (
            f"a basic batch must not declare {overclaim!r}: {validation}")


def test_basic_batch_record_limitations_match_the_audit_that_produced_it(batch):
    record = batch.g.write_audit_record(batch.root, batch.output)
    audited = batch.g.audit_batch(batch.root, batch.output)

    assert audited["validation_level"] == "output_bytes_and_metadata_only", (
        f"the fixture batch must audit as a basic batch, got {audited['validation_level']!r}")
    assert record["generation_validation"]["limitations"] == audited["limitations"], (
        "the record must repeat the audit's own limitations item for item, not a "
        f"subset or a superset: {record['generation_validation']['limitations']} != "
        f"{audited['limitations']}")


def test_basic_batch_record_counts_the_outputs_the_audit_validated(batch):
    manifest = read_manifest(batch.output)
    cropped = sum(candidate["status"] == "cropped" for candidate in manifest["candidates"])
    assert 0 < cropped < 1621, f"the fixture batch must not look like a full batch, got {cropped}"

    record = batch.g.write_audit_record(batch.root, batch.output)

    assert record["generation_validation"]["validated_outputs"] == cropped, (
        "validated_outputs must be the number of outputs this audit validated, not a "
        f"hard-coded figure: {record['generation_validation']['validated_outputs']} != {cropped}")
    assert record["checked_candidates"] == len(manifest["candidates"])


def test_basic_batch_record_reports_no_frame_replay_receipts(batch):
    manifest = read_manifest(batch.output)
    assert not any("frame_preserving_replay" in source for source in manifest["sources"]), (
        "the fixture batch must carry no source frame replay receipt")
    assert not any("frame_preserving_replay" in (candidate.get("output") or {})
                   for candidate in manifest["candidates"]), (
        "the fixture batch must carry no clip frame replay receipt")

    record = batch.g.write_audit_record(batch.root, batch.output)

    assert record["source_replays_recorded"] == 0, (
        f"a basic batch records no source frame replay, got {record['source_replays_recorded']}")
    assert record["clip_replays_recorded"] == 0, (
        f"a basic batch records no clip frame replay, got {record['clip_replays_recorded']}")


# --------------------------------------------------------------------------- #
# 12. (D) one CLI write audits the batch once, inside the lock it writes in
# --------------------------------------------------------------------------- #
# The batch is only trustworthy while it cannot change. Auditing, building the
# record, digesting the files and replacing audit.json therefore have to happen
# once, in one batch-lock critical section -- not twice, and not in a window
# where another writer may swap the batch between the audit and the write.
#
# Both properties are counted on the work, not on a name: the batch lock is not
# reentrant, so an implementation that audits inside the write lock must call an
# unlocked body of the audit, and the outermost audit call is then not
# ``audit_batch``. Judging the router's name would reject the only safe shape.
# What is pinned instead: the audit work executes once (one trace leaf), it runs
# under a batch-lock acquisition, and every acquisition it ran under is still
# held when the record is moved into place.

def test_cli_write_audit_audits_the_batch_once(batch, monkeypatch, capsys):
    state = trace_audits_and_locks(monkeypatch, batch.g)

    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root,
                   "--audit-only", "--write-audit")

    assert code == 0, f"a valid batch must be written, got {capsys.readouterr()}"
    executions = audit_executions(state)
    assert len(executions) == 1, (
        "one CLI write must run the audit work exactly once, so the printed verdict and "
        "the written record cannot describe two different batches; it ran "
        f"{len(executions)} times as {[node['entry'] for node in executions] or 'no audited call'}")


def test_cli_write_audit_audits_and_writes_in_one_lock_critical_section(batch, monkeypatch, capsys):
    state = trace_audits_and_locks(monkeypatch, batch.g)
    moves = watch_record_moves(monkeypatch, extra=lambda: {"locks": list(state["active"])})

    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root,
                   "--audit-only", "--write-audit")

    assert code == 0, f"a valid batch must be written, got {capsys.readouterr()}"
    assert len(moves) == 1, (
        f"the record must be moved into place exactly once, got {moves}")
    executions = audit_executions(state)
    assert executions, "the CLI write must audit the batch"
    assert all(node["locks"] for node in executions), (
        "the audit must run inside the batch lock, or the batch can change while it is audited")
    replaced_under = set(moves[0]["locks"])
    assert all(node["locks"] <= replaced_under for node in executions), (
        "the record must be replaced while the critical section the audit ran in is still "
        "held; instead the audit and the write took separate lock acquisitions, leaving a "
        "window in which the batch can be replaced")
    assert state["active"] == [], "the batch lock must be released after the write"


def test_audit_batch_on_its_own_still_takes_the_batch_lock(batch, monkeypatch):
    state = trace_audits_and_locks(monkeypatch, batch.g)

    audited = batch.g.audit_batch(batch.root, batch.output)

    assert audited["status"] == AUDIT_STATUS, (
        f"audit_batch must still return the audit verdict, got {sorted(audited)}")
    assert audited["validation_level"] == "output_bytes_and_metadata_only", (
        "audit_batch must still return the audit of this basic batch, got "
        f"{audited['validation_level']!r}")
    assert len(state["acquisitions"]) == 1, (
        "a direct audit_batch call must acquire the batch lock exactly once, got "
        f"{len(state['acquisitions'])}")
    executions = audit_executions(state)
    assert len(executions) == 1, (
        "a direct audit_batch call must still audit the batch once, got "
        f"{[node['entry'] for node in executions]}")
    assert executions[0]["locks"], (
        "audit_batch must keep guarding its own audit with the batch lock")
    assert state["active"] == [], "audit_batch must release the batch lock"


# --------------------------------------------------------------------------- #
# 13. (5) the verdict is printed only once the record is on disk
# --------------------------------------------------------------------------- #
# Printing the audit JSON and then failing to write reads as a half success. The
# contract asserted here: on success stdout still carries the verdict, and a
# failed write must not have printed it first.

def test_cli_write_audit_prints_the_verdict_after_the_record_is_written(batch, monkeypatch, capsys):
    code = run_cli(batch.g, monkeypatch, "--project-root", batch.root,
                   "--audit-only", "--write-audit")

    printed = capsys.readouterr()
    assert code == 0, printed
    assert json.loads(printed.out)["status"] == AUDIT_STATUS, (
        f"a successful write must still print the verdict, got {printed.out[:200]!r}")
    assert (batch.output / RECORD_NAME).is_file()


def test_cli_write_audit_does_not_print_success_before_the_write(batch, monkeypatch, capsys):
    watch_record_moves(monkeypatch, fail=True)

    try:
        code = run_cli(batch.g, monkeypatch, "--project-root", batch.root,
                       "--audit-only", "--write-audit")
    except (OSError, PilotError):
        code = "raised"

    printed = capsys.readouterr()
    assert code != 0, f"a failed write must not report success, got rc={code!r}"
    assert AUDIT_STATUS not in printed.out, (
        "a failed write must not have printed the audit verdict first: "
        f"stdout was {printed.out[:300]!r}")
    assert not (batch.output / RECORD_NAME).exists(), "a failed write must not leave a record"
