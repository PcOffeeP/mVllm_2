"""R7: a non-pinned FFmpeg must degrade honestly, not crash and not masquerade."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from script.subvideo_generation._legacy.core import verification
from script.subvideo_generation.tests.rules_support import digest_of


VERIFIED_VERSION = "4.4.2"
LOCAL_VERSION = "8.1.1"


def _fake_tools(tmp_path, version):
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        path = Path(tmp_path) / name
        path.write_text(f"#!/bin/sh\necho '{name} version {version}'\n", encoding="utf-8")
        path.chmod(0o755)
        tools[name] = path
    return tools


def _pin_tools(monkeypatch, tools, version, *, missing=None):
    monkeypatch.setattr(verification.shutil, "which",
                        lambda name: None if name == missing else str(tools[name]))

    def fake_run(command, **_kwargs):
        name = Path(str(command[0])).name
        return subprocess.CompletedProcess(command, 0,
                                           stdout=f"{name} version {version} Copyright (c) test\n",
                                           stderr="")

    monkeypatch.setattr(verification.subprocess, "run", fake_run)


def test_local_ffmpeg_is_reported_as_degraded(tmp_path, monkeypatch):
    tools = _fake_tools(tmp_path, LOCAL_VERSION)
    _pin_tools(monkeypatch, tools, LOCAL_VERSION)

    result = verification._toolchain()

    assert isinstance(result, dict), "a non-pinned FFmpeg must be reported, not raised"
    assert result["degraded"] is True
    assert result["equivalent_to_verified_toolchain"] is False
    for name in ("ffmpeg", "ffprobe"):
        assert Path(result[name]["path"]).name == name
        assert LOCAL_VERSION in result[name]["version"]
        assert result[name]["binary_sha256"] == digest_of(tools[name])
    assert result.get("status") != verification.VERIFIED, (
        "a degraded toolchain must not be recorded as a verified replay toolchain")


def test_pinned_ffmpeg_is_reported_as_verified(tmp_path, monkeypatch):
    tools = _fake_tools(tmp_path, VERIFIED_VERSION)
    _pin_tools(monkeypatch, tools, VERIFIED_VERSION)

    result = verification._toolchain()

    assert result["degraded"] is False
    assert result["equivalent_to_verified_toolchain"] is True
    assert VERIFIED_VERSION in result["ffmpeg"]["version"]


def test_missing_ffmpeg_is_still_a_hard_error(tmp_path, monkeypatch):
    tools = _fake_tools(tmp_path, VERIFIED_VERSION)
    _pin_tools(monkeypatch, tools, VERIFIED_VERSION, missing="ffprobe")

    with pytest.raises(verification.ReplayUncertain):
        verification._toolchain()


def test_failed_version_probe_is_still_a_hard_error(tmp_path, monkeypatch):
    tools = _fake_tools(tmp_path, VERIFIED_VERSION)
    monkeypatch.setattr(verification.shutil, "which", lambda name: str(tools[name]))

    def broken_run(command, **_kwargs):
        raise OSError("cannot execute " + str(command[0]))

    monkeypatch.setattr(verification.subprocess, "run", broken_run)

    with pytest.raises(Exception) as caught:
        verification._toolchain()

    message = str(caught.value).lower()
    assert "cannot execute" in message or "replay" in message, (
        f"an unprobeable toolchain must raise loudly, got: {caught.value}")
