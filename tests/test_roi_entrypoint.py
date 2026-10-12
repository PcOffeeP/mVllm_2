from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROI_SCRIPT = Path(__file__).resolve().parents[1] / "pipeline/scripts/roi_annotation_app.py"


@pytest.mark.parametrize("launcher", ["direct", "streamlit"])
def test_roi_help_from_outside_checkout(tmp_path: Path, launcher: str):
    """Both launch paths must resolve pipeline without the caller's PYTHONPATH."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if launcher == "direct":
        command = [sys.executable, "-B", str(ROI_SCRIPT), "--help"]
    else:
        # Use Streamlit's path setup, then execute only argparse's help path.
        # bootstrap.run would start a server, which this regression does not need.
        command = [
            sys.executable,
            "-B",
            "-c",
            "import runpy, sys; "
            "from streamlit.web import bootstrap; "
            "script = sys.argv[1]; "
            "bootstrap._fix_sys_path(script); "
            "sys.argv = [script, '--', '--help']; "
            "runpy.run_path(script, run_name='__main__')",
            str(ROI_SCRIPT),
        ]

    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout
    for option in ("--metadata", "--output", "--project-root"):
        assert option in result.stdout
    assert list(tmp_path.iterdir()) == []
