"""Explicit adapter trust for strict evaluation records frozen at Git 512cc8b4.

A historical digest is accepted only by the exact audited adapter bytes below.
Changing an adapter requires another compatibility review and an explicit table
update; this never treats arbitrary new source as equivalent to old evidence.
"""

# Populated after the adapter implementation is finalized and tested.
STRICT_ADAPTERS = {'finetune/eval_run.py': {'frozen_sha256': '67c9da220108adf612d0ad92d617548be8df43e8ffe86df723d6ed96e83da5ef', 'adapter_sha256': '560c7b404e9d6c2104e7dcbeb44e89101d124e2586cb9d44112e74682e40b8bf'}, 'finetune/eval_holdout.py': {'frozen_sha256': 'd5ba919cfc94b4c774032c4580ad867e19cee6cebe8885118ad41c8ea16ea4cb', 'adapter_sha256': '386cc8fe1299ef9435bedc399f4b4403ee34a8d20ef8c60d6982fafa5cfa65c7'}}


def strict_adapter_matches(source: str, *, frozen_digest: str, current_digest: str) -> bool:
    pair = STRICT_ADAPTERS.get(source)
    return bool(pair and pair["frozen_sha256"] == frozen_digest and
                pair["adapter_sha256"] == current_digest)
