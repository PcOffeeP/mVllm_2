"""Exact audited adapters for Git 512cc8b4 strict and 30e96f97 A/B records.

A historical digest is accepted only by the exact audited adapter bytes below.
Changing an adapter requires another compatibility review and an explicit table
update; this never treats arbitrary new source as equivalent to old evidence.
"""

# Populated after the adapter implementation is finalized and tested.
STRICT_ADAPTERS = {'finetune/eval_run.py': {'frozen_sha256': '67c9da220108adf612d0ad92d617548be8df43e8ffe86df723d6ed96e83da5ef', 'adapter_sha256': 'b80cacca8c8939128ddbe6bfdec2c21f3c2ac8d3af7e760bde8956c924049a39'}, 'finetune/eval_holdout.py': {'frozen_sha256': 'd5ba919cfc94b4c774032c4580ad867e19cee6cebe8885118ad41c8ea16ea4cb', 'adapter_sha256': 'f96e56568d04c94eda43f1a2a653ca874c0c08dc3b8fa077bf5d25a1ad1718fc'}}


def strict_adapter_matches(source: str, *, frozen_digest: str, current_digest: str) -> bool:
    pair = STRICT_ADAPTERS.get(source)
    return bool(pair and pair["frozen_sha256"] == frozen_digest and
                pair["adapter_sha256"] == current_digest)


# The A/B release added semantic development; its identities keep their
# original meaning. These are exact audited file adapters, never global
# historical hash acceptance, and never confer independent quality status.
AB_FROZEN_SOURCES = {
    "finetune/eval_run.py": "560c7b404e9d6c2104e7dcbeb44e89101d124e2586cb9d44112e74682e40b8bf",
    "finetune/eval_holdout.py": "386cc8fe1299ef9435bedc399f4b4403ee34a8d20ef8c60d6982fafa5cfa65c7",
}


def evaluation_adapter_matches(source: str, *, scorer: str, frozen_digest: str, current_digest: str) -> bool:
    if scorer == "strict-v4.1" and strict_adapter_matches(source,
            frozen_digest=frozen_digest, current_digest=current_digest):
        return True
    pair = STRICT_ADAPTERS.get(source)
    return bool(scorer in {"strict-v4.1", "semantic-v4.1"} and pair and
                AB_FROZEN_SOURCES.get(source) == frozen_digest and
                pair["adapter_sha256"] == current_digest)
