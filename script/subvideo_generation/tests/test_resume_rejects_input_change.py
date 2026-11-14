"""R4: a changed input inventory is still a different batch."""
from __future__ import annotations

import pytest


def test_resume_refuses_changed_annotation_bytes(project):
    """Bytes move, parsed inventory does not: only the input identity can catch this."""
    root, g, descriptions, encoded = project
    g.run(root, plan_only=True, verification="full")
    csv_path = root / "data/annotation-table-full.csv"
    original = csv_path.read_bytes()
    csv_path.write_bytes(original + b"\n")
    manifest_path = root / "data/sub_video/manifest.json"
    before = manifest_path.read_bytes()

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True, verification="full")

    assert "input identity differs" in str(caught.value), (
        f"a changed input must be named explicitly, got: {caught.value}")
    assert manifest_path.read_bytes() == before, "a refused resume must not rewrite the batch"
    assert not encoded, "a refused resume must not encode anything"


def test_resume_refuses_a_changed_split_file(project):
    root, g, descriptions, encoded = project
    g.run(root, plan_only=True, verification="full")
    split = root / "data/splits/three-fold/fold_0_val.json"
    original = split.read_bytes()
    split.write_bytes(original + b"\n")

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True, verification="full")

    assert "input identity differs" in str(caught.value)
    assert not encoded


def test_resume_still_accepts_an_identical_batch(project):
    """Negative control: the same batch resumes without an input complaint."""
    root, g, descriptions, encoded = project
    g.run(root, plan_only=True, verification="full")

    resumed = g.run(root, resume=True, verification="full")

    assert resumed["complete"] is True
    assert len(encoded) == len(resumed["candidates"])
