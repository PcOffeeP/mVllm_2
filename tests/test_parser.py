from __future__ import annotations

import pytest

from agent.parser import ResultParser


def test_parse_plain_json():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92}'
    parsed = ResultParser.parse(raw)
    assert parsed == {
        "has_fracture": True,
        "fracture_between": [17, 18],
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": pytest.approx(0.92),
    }


def test_parse_json_with_markdown_fence():
    raw = '```json\n{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null, "confidence": 0.88}\n```'
    parsed = ResultParser.parse(raw)
    assert parsed["has_fracture"] is False
    assert parsed["type"] == "未断裂"


def test_parse_invalid_json_returns_none():
    assert ResultParser.parse("not json") is None


def test_parse_rejects_schema_violations():
    # has_fracture=true but type is a non-fracture class.
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "未断裂", "location": "inside_gauge", "confidence": 0.92}'
    assert ResultParser.parse(raw) is None


def test_parse_rejects_confidence_out_of_range():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 1.5}'
    assert ResultParser.parse(raw) is None


def test_parse_extracts_json_from_noise():
    raw = 'Some explanation text before {\n  "has_fracture": false,\n  "fracture_between": null,\n  "type": "未夹紧",\n  "location": null,\n  "confidence": 0.7\n} and after.'
    parsed = ResultParser.parse(raw)
    assert parsed["type"] == "未夹紧"
    assert parsed["confidence"] == pytest.approx(0.7)


def test_parse_empty_and_none_input():
    assert ResultParser.parse("") is None
    assert ResultParser.parse(None) is None  # type: ignore[arg-type]


def test_parse_ignores_extra_fields():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92, "reasoning": "some extra"}'
    parsed = ResultParser.parse(raw)
    assert parsed is not None
    assert "reasoning" not in parsed
    assert parsed["type"] == "韧性断裂"
