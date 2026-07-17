"""Pure-function model output normalizer for structured fracture predictions.

This module is self-contained — it does not import from any other project module,
read files, use network, or log. All dependencies (allowed types, frame count) are
passed explicitly by the caller.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_FRACTURE_TYPES: set[str] = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂",
}

ALLOWED_NON_FRACTURE_TYPES: set[str] = {"未断裂", "未夹紧"}

ALLOWED_LOCATIONS: set[str] = {"inside_gauge", "outside_gauge"}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_valid_interval(val: Any, frame_count: int) -> bool:
    """Return True if *val* is a valid ``[i, i+1]`` with ``0 <= i < N-1``."""
    if not isinstance(val, list) or len(val) != 2:
        return False
    i, j = val
    if not (isinstance(i, int) and isinstance(j, int)):
        return False
    if i != j - 1:
        return False
    if i < 0 or j >= frame_count:
        return False
    return True


def _coerce_has_fracture(raw: dict) -> tuple[Any, list[str]]:
    """Extract and coerce the raw *has_fracture* value to bool | None.

    Handles common model quirks (string literals, numeric booleans).
    Returns ``(has_fracture, repairs)``.
    """
    repairs: list[str] = []
    raw_val = raw.get("has_fracture")

    if raw_val is True or raw_val is False:
        return raw_val, repairs

    if raw_val is None:
        return None, repairs

    # String booleans
    if isinstance(raw_val, str):
        stripped = raw_val.strip().lower()
        if stripped == "true":
            repairs.append(f"has_fracture string coerced: {raw_val!r} -> True")
            return True, repairs
        if stripped == "false":
            repairs.append(f"has_fracture string coerced: {raw_val!r} -> False")
            return False, repairs
        if stripped in ("null", "none", ""):
            repairs.append(f"has_fracture string coerced: {raw_val!r} -> None")
            return None, repairs

    # Numeric booleans
    if raw_val == 1:
        repairs.append("has_fracture numeric coerced: 1 -> True")
        return True, repairs
    if raw_val == 0:
        repairs.append("has_fracture numeric coerced: 0 -> False")
        return False, repairs

    repairs.append(f"has_fracture={raw_val!r} is unrecognized; treating as None")
    return None, repairs


def _parse_string_interval(val: Any) -> tuple[Any, str | None]:
    """Try to parse a string like ``'[1, 2]'`` into ``[1, 2]``.

    Returns ``(parsed_value, repair_flag_or_None)``.
    """
    if not isinstance(val, str):
        return val, None
    stripped = val.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return val, None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return val, None
    if not isinstance(parsed, list) or len(parsed) != 2:
        return val, None
    if not all(isinstance(x, int) for x in parsed):
        return val, None
    return parsed, f"string_interval_converted: {stripped} -> {parsed}"


def _normalize_fracture_between(
    raw_val: Any, frame_count: int, repairs: list[str]
) -> Any:
    """Normalize *fracture_between* under Rule 3 (has_fracture is True).

    Always returns a valid interval ``[i, i+1]`` or ``None``.
    Appends repair flags to *repairs* when a value is dropped.
    """
    if raw_val is None:
        return None

    if _is_valid_interval(raw_val, frame_count):
        return raw_val

    repairs.append(
        f"fracture_between={raw_val!r} is invalid (frame_count={frame_count}); set to None"
    )
    return None


def _normalize_type(
    raw_val: Any, has_fracture: bool | None, repairs: list[str]
) -> Any:
    """Normalize *type* based on the *has_fracture* state.

    Returns a valid type string or ``None``.
    """
    if raw_val is None:
        return None

    if has_fracture is True:
        if raw_val in ALLOWED_FRACTURE_TYPES:
            return raw_val
        repairs.append(
            f"type={raw_val!r} is not a valid fracture type; set to None"
        )
        return None

    if has_fracture is False:
        if raw_val in ALLOWED_NON_FRACTURE_TYPES:
            return raw_val
        repairs.append(
            f"type={raw_val!r} is not a non-fracture type; set to '未断裂'"
        )
        return "未断裂"

    # has_fracture is None
    if raw_val is not None:
        repairs.append(f"type={raw_val!r} set to None (has_fracture is None)")
    return None


def _normalize_location(
    raw_val: Any, has_fracture: bool | None, repairs: list[str]
) -> Any:
    """Normalize *location* based on the *has_fracture* state.

    Returns a valid location string or ``None``.
    """
    if raw_val is None:
        return None

    if has_fracture is True:
        if raw_val in ALLOWED_LOCATIONS:
            return raw_val
        repairs.append(
            f"location={raw_val!r} is not a valid location; set to None"
        )
        return None

    if has_fracture is False:
        repairs.append(
            f"location={raw_val!r} set to None (has_fracture is False)"
        )
        return None

    # has_fracture is None
    repairs.append(
        f"location={raw_val!r} set to None (has_fracture is None)"
    )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_structured_output(
    raw: dict, frame_count: int
) -> tuple[dict, list[str]]:
    """Normalize a model's structured JSON output.

    Args:
        raw: Raw model output parsed as a Python dict. May contain type errors,
             string representations of booleans, malformed intervals, etc.
        frame_count: Number of sampled frames *N* (typically 8). Used to validate
                     the *fracture_between* interval.

    Returns:
        ``(normalized, repair_flags)``

        - **normalized**: A dict with exactly four keys —
          ``has_fracture``, ``fracture_between``, ``type``, ``location``.
          Every value is in a valid state per the normalization rules below.
        - **repair_flags**: A list of human-readable strings describing each
          repair that was applied. Empty list if no repairs were needed.

    Normalization rules (applied in priority order):

    1. **``has_fracture`` is ``False``**
       - ``fracture_between`` → ``None`` (forced)
       - ``location`` → ``None`` (forced)
       - ``type``: if not in ``{"未断裂", "未夹紧"}`` → ``"未断裂"``

    2. **``has_fracture`` is ``None``**
       - ``fracture_between`` → ``None``
       - ``type`` → ``None``
       - ``location`` → ``None``

    3. **``has_fracture`` is ``True``**
       - ``fracture_between``: if not a valid ``[i, i+1]`` (``0 <= i < N-1``) or
         ``None`` → ``None`` (invalid intervals are dropped, never clipped)
       - ``type``: if not in ``ALLOWED_FRACTURE_TYPES`` → ``None``
       - ``location``: if not in ``ALLOWED_LOCATIONS`` → ``None``

    Additional repairs applied before the rules above:

    - String representation of a list (e.g. ``"[1, 2]"``) is safely parsed into
      a Python list before validation.
    - String / numeric representations of booleans (``"true"``, ``1``, etc.) are
      coerced into Python ``bool`` or ``None``.
    """
    repairs: list[str] = []

    # --- Coerce has_fracture ---
    has_fracture, hf_repairs = _coerce_has_fracture(raw)
    repairs.extend(hf_repairs)

    # --- Extra repair: string interval conversion ---
    fracture_between, interval_flag = _parse_string_interval(
        raw.get("fracture_between")
    )
    if interval_flag:
        repairs.append(interval_flag)

    raw_type = raw.get("type")
    raw_location = raw.get("location")

    # --- Apply rules by has_fracture state ---

    if has_fracture is False:
        # Rule 1
        if fracture_between is not None:
            repairs.append(
                "has_fracture=false: fracture_between set to None"
            )
        fracture_between = None

        location = _normalize_location(raw_location, False, repairs)

        type_val = _normalize_type(raw_type, False, repairs)

    elif has_fracture is None:
        # Rule 2
        if fracture_between is not None:
            repairs.append(
                "has_fracture=null: fracture_between set to None"
            )
        fracture_between = None

        type_val = _normalize_type(raw_type, None, repairs)
        location = _normalize_location(raw_location, None, repairs)

    elif has_fracture is True:
        # Rule 3 — NEVER change has_fracture to False
        fracture_between = _normalize_fracture_between(
            fracture_between, frame_count, repairs
        )
        type_val = _normalize_type(raw_type, True, repairs)
        location = _normalize_location(raw_location, True, repairs)

    else:
        # Defensive: should not be reachable after _coerce_has_fracture
        fracture_between = None
        type_val = None
        location = None

    normalized: dict[str, Any] = {
        "has_fracture": has_fracture,
        "fracture_between": fracture_between,
        "type": type_val,
        "location": location,
    }

    return normalized, repairs


def validate_structured_output(normalized: dict, frame_count: int) -> bool:
    """Quick validity check for a **already-normalized** output dict.

    This is **not** a schema validator against the raw model output — it checks
    that the normalized dict is self-consistent and structurally sound.

    Checks performed:

    - All four required keys exist.
    - ``has_fracture`` is ``bool`` or ``None``.
    - ``fracture_between`` is ``None`` or a valid ``[i, i+1]`` interval.
    - ``type`` is consistent with ``has_fracture``.
    - ``location`` is ``None`` or in ``ALLOWED_LOCATIONS``.

    Args:
        normalized: A dict produced by ``normalize_structured_output`` (or
                    structurally equivalent).
        frame_count: Number of sampled frames, used to validate the interval.

    Returns:
        ``True`` if the dict passes all checks, ``False`` otherwise.
    """
    # Required keys
    for key in ("has_fracture", "fracture_between", "type", "location"):
        if key not in normalized:
            return False

    hf = normalized["has_fracture"]
    fb = normalized["fracture_between"]
    t = normalized["type"]
    loc = normalized["location"]

    # has_fracture must be bool or None
    if hf is not True and hf is not False and hf is not None:
        return False

    # fracture_between: None or valid interval
    if fb is not None and not _is_valid_interval(fb, frame_count):
        return False

    # type consistency
    if hf is True:
        if t is not None and t not in ALLOWED_FRACTURE_TYPES:
            return False
    elif hf is False:
        if t not in ALLOWED_NON_FRACTURE_TYPES:
            return False
    else:  # None
        if t is not None:
            return False

    # location consistency
    if loc is not None and loc not in ALLOWED_LOCATIONS:
        return False
    if hf is False and loc is not None:
        return False
    if hf is None and loc is not None:
        return False

    return True


def needs_retry(normalized: dict) -> bool:
    """Determine whether the model call should be retried.

    Returns ``True`` when ``has_fracture`` is ``True`` but one or more
    secondary fields (``fracture_between``, ``type``, ``location``) are
    ``None`` — i.e. the model detected a fracture but could not produce
    sufficient detail.  This is a signal to the caller that a retry (with
    a different prompt or temperature) may help.

    Args:
        normalized: A dict produced by ``normalize_structured_output``.

    Returns:
        ``True`` if a retry is advisable, ``False`` otherwise.
    """
    if normalized.get("has_fracture") is not True:
        return False
    return (
        normalized.get("fracture_between") is None
        or normalized.get("type") is None
        or normalized.get("location") is None
    )
