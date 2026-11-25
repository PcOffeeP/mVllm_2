"""Shared exception types for ``script.five_label_eval``."""
from __future__ import annotations


class InputError(ValueError):
    """Ambiguous or malformed local input identity."""
