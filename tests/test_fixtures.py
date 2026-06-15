from __future__ import annotations

import json
from pathlib import Path

from agent.sampling import is_boundary_sentinel
from agent.schema import ModelOutput


FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def test_sample_model_outputs_are_valid():
    cases = _load_json("sample_model_outputs.json")
    for case in cases:
        output = ModelOutput(**case["model_output"])
        assert output.has_fracture == case["model_output"]["has_fracture"]


def test_boundary_sentinel_cases_match_fixture():
    cases = _load_json("sample_model_outputs.json")
    left = next(c for c in cases if c["description"] == "left boundary sentinel")
    right = next(c for c in cases if c["description"] == "right boundary sentinel")

    assert is_boundary_sentinel(left["model_output"]["fracture_between"], 36) is True
    assert is_boundary_sentinel(right["model_output"]["fracture_between"], 36) is True


def test_sample_video_meta_has_required_fields():
    meta = _load_json("sample_video_meta.json")
    assert len(meta) >= 1
    for item in meta:
        assert "video_id" in item
        assert "fps" in item
        assert "total_frames" in item
        assert "duration" in item
        assert item["fps"] > 0
        assert item["total_frames"] > 0
