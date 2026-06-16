"""Model-response parser with schema validation and fallback heuristics."""

from __future__ import annotations

import json
import re

from agent.schema import ModelOutput


class ResultParser:
    """Parser for raw text model responses.

    The parser strips markdown fences, attempts ``json.loads``, and validates
    the result against the model-output schema using ``agent.schema.ModelOutput``.
    ``expected_schema`` is accepted for interface compatibility but the
    authoritative schema is always the contract defined in
    ``docs/model_agent_interface.md`` section 2.
    """

    # Basic JSON object heuristic used when json.loads fails.
    _JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

    @classmethod
    def parse(cls, raw_text: str, expected_schema: dict | None = None) -> dict | None:
        """Return a parsed dict, or ``None`` if parsing/validation fails.

        Args:
            raw_text: Raw model text response.
            expected_schema: Kept for API compatibility; not used directly.

        Returns:
            A dict conforming to the model output schema, or ``None``.
        """
        text = (raw_text or "").strip()
        if not text:
            return None

        text = cls._strip_markdown(text)

        data = cls._try_load(text)
        if data is None:
            # Fallback: try to extract the first JSON object from noisy output.
            match = cls._JSON_OBJECT_RE.search(text)
            if match:
                data = cls._try_load(match.group(0))
        if data is None or not isinstance(data, dict):
            return None

        # Keep only contract fields to tolerate models that emit extra keys.
        contract_fields = {
            "has_fracture",
            "fracture_between",
            "type",
            "location",
            "confidence",
        }
        filtered = {k: v for k, v in data.items() if k in contract_fields}

        # Schema validation using Pydantic.  Convert to ModelOutput and back to
        # a plain dict so callers always receive the contract fields.
        try:
            validated = ModelOutput(**filtered)
        except Exception:
            return None

        return validated.model_dump()

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove surrounding `` ```json ... ``` `` fences."""
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _try_load(text: str) -> dict | list | None:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
