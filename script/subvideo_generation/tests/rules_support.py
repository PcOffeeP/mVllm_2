"""Lookups shared by the rules / identity / audit contract tests.

This module deliberately contains **no test cases** (its name does not start with
``test_``), so it is neither collected nor counted.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_MODULE = "script.subvideo_generation.rules"
GENERATE_MODULE = "script.subvideo_generation.generate"
PILOT_MODULE = "script.subvideo_generation.pilot.pilot"


def load(name):
    return importlib.import_module(name)


def rules_module():
    """The new rule-registry module (absent until the implementation lands)."""
    return load(RULES_MODULE)


def generate_module():
    return load(GENERATE_MODULE)


def pilot_module():
    return load(PILOT_MODULE)


def digest_of(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def run_cli(*arguments):
    """Run the real orchestrator CLI in a subprocess (argparse and exit codes stay real)."""
    return subprocess.run([sys.executable, "-m", GENERATE_MODULE, *[str(a) for a in arguments]],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def audit_content():
    """Locate the content auditor required by the contract."""
    for name in (GENERATE_MODULE, "script.subvideo_generation.audit"):
        try:
            module = load(name)
        except ImportError:
            continue
        function = getattr(module, "audit_content", None)
        if function is not None:
            return function
    raise AssertionError(
        "audit_content(root, output) must be importable from script.subvideo_generation.generate")


def _clip(output, index):
    name = f"video_{index:04d}_pre_01"
    path = output / "videos" / f"{name}.mp4"
    path.write_bytes(f"synthetic clip {index}".encode())
    candidate = {"candidate_id": name, "filename": f"{name}.mp4", "output_path": f"videos/{name}.mp4",
                 "source_video_id": f"video_{index:04d}", "role": "pre", "sequence": 1,
                 "start_frame": 0, "end_frame": 60, "start_time": 0.0, "end_time": 6.0,
                 "status": "cropped", "output": {"sha256": digest_of(path)}}
    source = {"video_id": f"video_{index:04d}", "status": "planned",
              "source_path": f"data/videos/video_{index:04d}.mp4", "source_sha256": digest_of(path)}
    return candidate, source


def make_batch(root, *, legacy, clip_count=2, schema="tensile-unified-sub-video/1"):
    """Write a minimal batch under ``<root>/data/sub_video``; return (output, candidates).

    ``legacy=True`` reproduces the pre-change identity (``code`` + ``loader_code``,
    **no** ``rules`` key). ``legacy=False`` writes the new identity shape.
    """
    root = Path(root)
    output = root / "data" / "sub_video"
    (output / "videos").mkdir(parents=True, exist_ok=True)
    pairs = [_clip(output, index) for index in range(1, clip_count + 1)]
    candidates = [candidate for candidate, _ in pairs]
    sources = [source for _, source in pairs]
    inputs = {"data/annotation-table-full.csv": "0" * 64}
    if legacy:
        identity = {"schema": schema, "inputs": inputs,
                    "code": {"subvideo_generation/generate.py": "1" * 64},
                    "loader_code": {"subvideo_generation/_legacy/coverage/generate.py": "2" * 64}}
    else:
        try:
            registry = rules_module().rules()
        except ImportError:  # the content auditor must not need rules.py to exist
            registry = {"digest": "f" * 64, "fields": {}}
        identity = {"schema": schema, "input_mode": "official", "inputs": inputs,
                    "rules": registry,
                    "info": {"code_version": None, "toolchain": {}}}
    manifest = {"schema": schema, "identity": identity, "sources": sources,
                "candidates": candidates, "excluded_windows": [], "complete": True,
                "published": False, "plan_only": False}
    write_json(output / "manifest.json", manifest)
    write_json(output / "summary.json", {
        "scope": "all_sources", "source_count": len(sources),
        "source_status": {"planned": len(sources)},
        "candidate_count": len(candidates),
        "candidate_status": {"cropped": len(candidates)},
        "roles": {"pre": len(candidates)}, "complete": True, "published": False})
    return output, candidates
