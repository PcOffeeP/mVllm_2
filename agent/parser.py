"""Minimal model-response parser that cleans markdown and returns JSON."""

from __future__ import annotations

import json


class ResultParser:
    """Parser for raw text model responses."""

    @classmethod
    def parse(cls, raw_text: str, expected_schema: dict | None = None) -> dict | None:
        """Return a parsed dict, or ``None`` if parsing/validation fails.

        This method strips surrounding whitespace, removes `` ```json ... ``` ``
        markdown fences, and attempts ``json.loads``. ``expected_schema`` is kept
        in the signature for contract compatibility; future validation may use it.
        """
        text = (raw_text or "").strip()
        if not text:
            return None

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        return data
