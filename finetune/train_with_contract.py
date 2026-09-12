"""Launch LLaMA-Factory training with the MiniCPM child-processor contract."""

from __future__ import annotations

import os

# Avoid W&B interactive login prompt; keep offline logging.
# User can override via shell env (e.g., WANDB_MODE=online, WANDB_API_KEY=xxx).
os.environ.setdefault("WANDB_MODE", "offline")

import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LLAMAFACTORY_SRC = ROOT / "LlamaFactory" / "src"
for preferred in (str(LLAMAFACTORY_SRC), str(ROOT)):
    while preferred in sys.path:
        sys.path.remove(preferred)
sys.path.insert(0, str(LLAMAFACTORY_SRC))
sys.path.insert(1, str(ROOT))

from pipeline.llamafactory_contract import install_training_processor_contract


class _TrainingLoader(yaml.SafeLoader):
    """Do not silently replace frozen parameters through duplicate YAML keys."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or not key:
                raise ValueError("training config keys must be non-empty strings")
            if key in result:
                raise ValueError(f"duplicate training config key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def run_training(config: Mapping[str, Any]) -> None:
    """Execute supplied parameters; callers own identity gates and Run events.

    Keep this adapter free of path selection so versioning can pass the actual
    frozen input without reopening an editable YAML between validation and use.
    The tuner may mutate its arguments, so it receives a private deep copy.
    Exceptions intentionally propagate to the lifecycle owner.
    """
    if not isinstance(config, Mapping) or not config or any(
        not isinstance(key, str) or not key for key in config
    ):
        raise ValueError("training config must be a non-empty string-keyed mapping")
    actual_config = deepcopy(dict(config))

    import llamafactory

    loaded_from = Path(llamafactory.__file__).resolve()
    if not loaded_from.is_relative_to(LLAMAFACTORY_SRC.resolve()):
        raise RuntimeError(
            "LLaMA-Factory source drifted: "
            f"expected_under={LLAMAFACTORY_SRC.resolve()} actual={loaded_from}"
        )

    install_training_processor_contract()
    from llamafactory.train.tuner import run_exp

    run_exp(actual_config)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 finetune/train_with_contract.py <training-yaml>")
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        config = yaml.load(handle, Loader=_TrainingLoader)
    run_training(config)


if __name__ == "__main__":
    main()
