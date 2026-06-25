"""LoRA adapter path helpers for each cross-validation fold."""

from __future__ import annotations


FOLD_ADAPTER_PATHS: dict[int, str] = {
    0: "LlamaFactory/saves/minicpmv4_5/lora/sft_3k0",
    1: "LlamaFactory/saves/minicpmv4_5/lora/sft_3k1",
    2: "LlamaFactory/saves/minicpmv4_5/lora/sft_3k2",
}


def get_adapter_path(fold: int) -> str:
    """Return the expected LoRA adapter directory for ``fold``.

    Args:
        fold: Cross-validation fold index (0, 1 or 2).

    Returns:
        Relative path to the LoRA adapter directory.

    Raises:
        ValueError: If ``fold`` is not 0, 1 or 2.
    """
    if fold not in FOLD_ADAPTER_PATHS:
        raise ValueError(f"fold must be one of {sorted(FOLD_ADAPTER_PATHS)}, got {fold}")
    return FOLD_ADAPTER_PATHS[fold]


def list_supported_folds() -> list[int]:
    """Return the list of supported fold indices."""
    return sorted(FOLD_ADAPTER_PATHS.keys())
