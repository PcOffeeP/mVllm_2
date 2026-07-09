from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .constants import ALLOWED_LOCATIONS, ALLOWED_TYPES, CORE_FIELDS, FRACTURE_TYPES


@dataclass(frozen=True)
class FormatResult:
    json_valid: bool
    schema_valid: bool
    payload: dict[str, Any] | None
    errors: list[str]

    @property
    def format_valid(self) -> bool:
        return self.json_valid and self.schema_valid


def parse_model_output(raw_output: Any) -> FormatResult:
    text = str(raw_output or "").strip()
    text = text.replace("```json", "").replace("```JSON", "").replace("```", "").strip()
    if not text:
        return FormatResult(False, False, None, ["empty output"])
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return FormatResult(False, False, None, [f"json decode error: {exc.msg}"])
    if not isinstance(payload, dict):
        return FormatResult(False, False, None, ["top-level JSON is not an object"])
    schema_valid, errors = validate_payload(payload)
    return FormatResult(True, schema_valid, payload, errors)


def validate_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    keys = set(payload)
    required = set(CORE_FIELDS)
    missing = sorted(required - keys)
    extra = sorted(keys - required)
    if missing:
        errors.append(f"missing fields: {missing}")
    if extra:
        errors.append(f"extra fields: {extra}")
    if missing:
        return False, errors

    has_fracture = payload.get("has_fracture")
    fracture_between = payload.get("fracture_between")
    prediction_type = payload.get("type")
    location = payload.get("location")
    confidence = payload.get("confidence")

    if has_fracture not in (True, False, None):
        errors.append(f"has_fracture must be true/false/null, got {has_fracture!r}")
    if prediction_type not in ALLOWED_TYPES:
        errors.append(f"type is not allowed: {prediction_type!r}")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        errors.append(f"confidence must be a number, got {confidence!r}")
    elif not 0.0 <= float(confidence) <= 1.0:
        errors.append(f"confidence out of range [0, 1]: {confidence!r}")

    if prediction_type in FRACTURE_TYPES:
        if has_fracture is not True:
            errors.append(f"fracture type requires has_fracture=true, got {has_fracture!r}")
        if not _valid_fracture_between(fracture_between):
            errors.append(f"fracture type requires adjacent fracture_between [i, i+1] in 0-7, got {fracture_between!r}")
        if location not in ALLOWED_LOCATIONS:
            errors.append(f"fracture type requires location inside_gauge/outside_gauge, got {location!r}")
    elif prediction_type in ("未断裂", "未夹紧"):
        if has_fracture is not False:
            errors.append(f"{prediction_type} requires has_fracture=false, got {has_fracture!r}")
        if fracture_between is not None:
            errors.append(f"{prediction_type} requires fracture_between=null, got {fracture_between!r}")
        if location is not None:
            errors.append(f"{prediction_type} requires location=null, got {location!r}")
    elif prediction_type == "视频异常":
        if has_fracture is not None:
            errors.append(f"视频异常 requires has_fracture=null, got {has_fracture!r}")
        if fracture_between is not None:
            errors.append(f"视频异常 requires fracture_between=null, got {fracture_between!r}")
        if location is not None:
            errors.append(f"视频异常 requires location=null, got {location!r}")

    return not errors, errors


def _valid_fracture_between(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    start, end = value
    if isinstance(start, bool) or isinstance(end, bool):
        return False
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return 0 <= start < end <= 7 and end == start + 1


def compare_prediction(payload: dict[str, Any] | None, target: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for field in CORE_FIELDS:
        expected = target.get(field)
        predicted = payload.get(field) if payload else None
        if field == "confidence":
            correct = isinstance(predicted, (int, float)) and not isinstance(predicted, bool) and 0.0 <= float(predicted) <= 1.0
            results[field] = {"status": "checked", "expected": "number in [0, 1]", "predicted": predicted, "correct": correct}
        elif expected is _UNAVAILABLE:
            results[field] = {"status": "unavailable", "expected": None, "predicted": predicted, "correct": None}
        else:
            results[field] = {"status": "checked", "expected": expected, "predicted": predicted, "correct": predicted == expected}
    return results


def prediction_correct(field_results: dict[str, dict[str, Any]]) -> bool | None:
    checked = [result for result in field_results.values() if result["status"] == "checked"]
    if not checked:
        return None
    return all(result["correct"] is True for result in checked)


class _Unavailable:
    pass


_UNAVAILABLE = _Unavailable()


def unavailable() -> Any:
    return _UNAVAILABLE
