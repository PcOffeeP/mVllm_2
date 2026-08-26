"""Runtime release pointer tests for finetune/v4_1_runtime.py.

Verifies that RELEASE_ID is derived from the current release pointer and that
the frozen release expectations are anchored to the git-tracked pointer file,
preventing a self-certification attack where a tampered manifest is used as
its own expected value.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from finetune.v4_1_runtime import (
    RELEASE_ID,
    RELEASE_SCHEMA_VERSION,
    V4_1FinetuneError,
    load_release_expectations,
    validate_release,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _pointer(
    project_root: Path,
    *,
    release_id: str = RELEASE_ID,
    contract_hash: str,
) -> Path:
    """Create an isolated copy of the release pointer under project_root."""
    pointer = {
        "release_id": release_id,
        "release_dir": f"workspace/data/releases/{release_id}",
        "manifest": f"workspace/data/releases/{release_id}/manifest/release_manifest.json",
        "expected_contract_hash": contract_hash,
    }
    pointer_path = project_root / "finetune/active_data_release.json"
    _write_json(pointer_path, pointer)
    return pointer_path


def _manifest(
    release_id: str,
    *,
    contract_hash: str,
    counts: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "status": "training_ready",
        "immutable": True,
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": contract_hash,
        "label_semantics": "frame_window_authoritative",
        "counts": counts,
        "files": [],
    }


def _write_manifest(
    project_root: Path,
    release_id: str,
    manifest: dict[str, object],
) -> Path:
    manifest_path = (
        project_root
        / "workspace/data/releases"
        / release_id
        / "manifest/release_manifest.json"
    )
    _write_json(manifest_path, manifest)
    return manifest_path


def test_release_id_matches_active_pointer() -> None:
    pointer = json.loads(
        Path("finetune/active_data_release.json").read_text(encoding="utf-8")
    )
    assert RELEASE_ID == pointer["release_id"]
    assert RELEASE_ID.startswith("v4.1.0-")


def test_release_id_not_hardcoded_stale_value() -> None:
    assert RELEASE_ID != "v4.1.0-760050fad303"


def test_load_release_expectations_reads_frozen_manifest(
    tmp_path: Path,
) -> None:
    release_id = "v4.1.0-testmanifest"
    counts = {
        "published_candidates": 1678,
        "excluded_candidates": 12,
        "reviewed_candidates": 900,
        "automatic_unreviewed_candidates": 766,
    }
    contract_hash = "47e393" + "0" * 58
    _pointer(tmp_path, release_id=release_id, contract_hash=contract_hash)
    _write_manifest(
        tmp_path,
        release_id,
        _manifest(release_id, contract_hash=contract_hash, counts=counts),
    )

    expectations = load_release_expectations(
        project_root=tmp_path,
        release_id=release_id,
    )

    assert expectations["contract_hash"] == contract_hash
    assert expectations["counts"] == counts


def test_load_release_expectations_contract_hash_drift_fail_closed(
    tmp_path: Path,
) -> None:
    release_id = "v4.1.0-testmanifest"
    _pointer(tmp_path, release_id=release_id, contract_hash="47e393" + "0" * 58)
    _write_manifest(
        tmp_path,
        release_id,
        _manifest(
            release_id,
            contract_hash="deadbeef" + "0" * 56,
            counts={"published_candidates": 1678},
        ),
    )

    with pytest.raises(V4_1FinetuneError, match="contract_hash 漂移"):
        load_release_expectations(
            project_root=tmp_path,
            release_id=release_id,
        )


def test_load_release_expectations_missing_pointer_field_fail_closed(
    tmp_path: Path,
) -> None:
    release_id = "v4.1.0-testmanifest"
    pointer = {
        "release_id": release_id,
        "release_dir": f"workspace/data/releases/{release_id}",
        "manifest": f"workspace/data/releases/{release_id}/manifest/release_manifest.json",
    }
    _write_json(tmp_path / "finetune/active_data_release.json", pointer)

    with pytest.raises(
        V4_1FinetuneError, match="expected_contract_hash"
    ):
        load_release_expectations(
            project_root=tmp_path,
            release_id=release_id,
        )


def test_load_release_expectations_fails_closed_without_workspace(
    tmp_path: Path,
) -> None:
    release_id = "v4.1.0-missing"
    _pointer(tmp_path, release_id=release_id, contract_hash="47e393" + "0" * 58)

    with pytest.raises(
        V4_1FinetuneError, match="必须在挂载 workspace 的训练机上执行"
    ):
        load_release_expectations(
            project_root=tmp_path,
            release_id=release_id,
        )


def test_validate_release_contract_hash_drift_fail_closed(
    tmp_path: Path,
) -> None:
    release_id = "v4.1.0-testmanifest"
    contract_hash = "47e393" + "0" * 58
    _pointer(tmp_path, release_id=release_id, contract_hash=contract_hash)
    _write_manifest(
        tmp_path,
        release_id,
        _manifest(
            release_id,
            contract_hash=contract_hash,
            counts={"published_candidates": 1678},
        ),
    )

    with pytest.raises(V4_1FinetuneError, match="contract_hash 漂移"):
        validate_release(
            tmp_path,
            release_id=release_id,
            expected_contract_hash="deadbeef" + "0" * 56,
            expected_schema_version=RELEASE_SCHEMA_VERSION,
            expected_counts={"published_candidates": 1678},
        )


def test_validate_release_counts_drift_fail_closed(
    tmp_path: Path,
) -> None:
    release_id = "v4.1.0-testmanifest"
    contract_hash = "47e393" + "0" * 58
    _pointer(tmp_path, release_id=release_id, contract_hash=contract_hash)
    _write_manifest(
        tmp_path,
        release_id,
        _manifest(
            release_id,
            contract_hash=contract_hash,
            counts={"published_candidates": 1678},
        ),
    )

    with pytest.raises(V4_1FinetuneError, match="published_candidates 漂移"):
        validate_release(
            tmp_path,
            release_id=release_id,
            expected_contract_hash=contract_hash,
            expected_schema_version=RELEASE_SCHEMA_VERSION,
            expected_counts={"published_candidates": 1275},
        )


def test_missing_active_data_release_fails_closed(
    tmp_path: Path,
) -> None:
    """Importing without a release pointer must fail without touching the real file.

    We copy the runtime module into an isolated project tree that lacks the
    pointer file and import from there, leaving the repository pointer intact.
    """
    repo_root = Path(__file__).parent.parent.resolve()
    isolated_finetune = tmp_path / "finetune"
    isolated_finetune.mkdir(parents=True)
    (isolated_finetune / "__init__.py").write_text("")
    (isolated_finetune / "v4_1_runtime.py").write_bytes(
        (repo_root / "finetune" / "v4_1_runtime.py").read_bytes()
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", "import finetune.v4_1_runtime"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert (
        "active_data_release.json" in result.stderr
        or "release pointer" in result.stderr
    )
