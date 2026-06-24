"""Launch LLaMA-Factory training with the MiniCPM child-processor contract."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LLAMAFACTORY_SRC = ROOT / "LlamaFactory" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLAMAFACTORY_SRC) not in sys.path:
    sys.path.insert(0, str(LLAMAFACTORY_SRC))

from pipeline.llamafactory_contract import install_training_processor_contract


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 finetune/train_with_contract.py <training-yaml>")
    install_training_processor_contract()
    from llamafactory.train.tuner import run_exp

    run_exp([sys.argv[1]])


if __name__ == "__main__":
    main()
