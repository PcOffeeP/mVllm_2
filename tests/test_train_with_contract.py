from __future__ import annotations

import sys

from finetune.train_with_contract import LLAMAFACTORY_SRC, ROOT


def test_training_entrypoint_prefers_current_repository_llamafactory() -> None:
    assert LLAMAFACTORY_SRC == ROOT / "LlamaFactory/src"
    assert sys.path.index(str(LLAMAFACTORY_SRC)) < sys.path.index(str(ROOT))
