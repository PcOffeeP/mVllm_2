"""Launch LLaMA-Factory training with the MiniCPM child-processor contract."""

from __future__ import annotations

import os

# Avoid W&B interactive login prompt; keep offline logging.
# User can override via shell env (e.g., WANDB_MODE=online, WANDB_API_KEY=xxx).
os.environ.setdefault("WANDB_MODE", "offline")

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LLAMAFACTORY_SRC = ROOT / "LlamaFactory" / "src"
if str(LLAMAFACTORY_SRC) not in sys.path:
    sys.path.insert(0, str(LLAMAFACTORY_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))

from pipeline.llamafactory_contract import install_training_processor_contract


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 finetune/train_with_contract.py <training-yaml>")
    install_training_processor_contract()

    config_path = sys.argv[1]
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    import llamafactory

    loaded_from = Path(llamafactory.__file__).resolve()
    if not loaded_from.is_relative_to(LLAMAFACTORY_SRC.resolve()):
        raise RuntimeError(
            "LLaMA-Factory source drifted: "
            f"expected_under={LLAMAFACTORY_SRC.resolve()} actual={loaded_from}"
        )

    from llamafactory.train.tuner import run_exp

    run_exp(config)


if __name__ == "__main__":
    main()
