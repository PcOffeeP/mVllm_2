#!/usr/bin/env python3
"""Validate any immutable V4.1 release through the finetuning runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.v4_1_runtime import (
    RELEASE_SCHEMA_VERSION,
    validate_release,
)


def validate_versioned_training_release(root: Path, version: str, *, inputs_path: Path | None = None):
    """Check a readable release against its existing publication evidence.

    Migrated objects use the committed migration receipt. Seven-stage objects
    use the original explicit inputs and full publication validator instead.
    Neither route changes a release or falls back to a legacy active pointer.
    """
    from versioning.ids import parse_data_id
    from versioning.data_release import (
        assert_payload_sealed, load_release_metadata, validate_training_reference,
    )
    from versioning.migration import _release_content_digest

    parsed = parse_data_id(version)
    root = Path(root).absolute()
    release = root / "data/releases" / version
    if any(path.is_symlink() for path in (release, *release.parents)):
        raise ValueError("release path must not contain symlinks")
    validate_training_reference(root / "data", version)
    meta = load_release_metadata(root / "data", version)
    if meta.protocol.removeprefix("tensile-vlm/") != parsed.protocol:
        raise ValueError("release protocol mismatch")
    if any(path.is_symlink() for path in release.rglob("*")):
        raise ValueError("release payload must not contain symlinks")
    assert_payload_sealed(release)
    if inputs_path is not None:
        from versioning.data_pipeline import run_input_release_validate
        if len(meta.source_batches) != 1:
            raise ValueError("seven-stage release must bind one source batch")
        run_input_release_validate(root, inputs_path=inputs_path,
            batch=meta.source_batches[0], version=version)
    else:
        receipt_path = root / "migration_receipts" / f"{version}.receipt.yaml"
        if any(path.is_symlink() for path in (receipt_path, *receipt_path.parents)):
            raise ValueError("migration receipt path must not contain symlinks")
        try:
            receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("release requires a committed migration receipt or explicit data inputs") from exc
        if (not isinstance(receipt, dict) or receipt.get("status") != "committed"
                or receipt.get("target_identity") != version
                or receipt.get("target_path") != f"data/releases/{version}/release.yaml"
                or receipt.get("target_release_digest") != _release_content_digest(release)):
            raise ValueError("migration receipt does not match release content")
    # M3 semantic publication has payload/; the completed legacy-copy migrator
    # deliberately preserves its flat declared file layout.
    return meta, release / "payload" if inputs_path is not None else release


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", default=None)
    parser.add_argument("--expected-contract-hash", default=None)
    parser.add_argument(
        "--expected-schema-version",
        default=None,
    )
    parser.add_argument("--verify-media", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_release(
        ROOT,
        release_id=args.release_id,
        expected_contract_hash=args.expected_contract_hash,
        expected_schema_version=args.expected_schema_version,
        verify_media=args.verify_media,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
