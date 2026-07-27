#!/usr/bin/env python3
"""Derive an immutable prompt-clarified view of the coverage-first 3k data."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_source_aware_3k import (  # noqa: E402
    COVERAGE_FIRST_POLICY_VERSION,
    DEFAULT_SEEDS,
    SourceAware3kError,
    _canonical_bytes,
    _pretty_bytes,
    _sha256_bytes,
    _write_immutable_directory,
    build_source_aware_3k,
)
from pipeline.current_data import current_data_paths  # noqa: E402

SCHEMA_VERSION = "tensile-vlm-v4.1-prompt-clarified-sampling/v1"
POLICY_VERSION = "source-aware-3k-coverage-first-prompt-clarified/v1"
SOURCE_SAMPLING_ID = "source-aware-3k-2a84e8b6cfc3"
SOURCE_SAMPLING_MANIFEST_SHA256 = (
    "d939fc004e3f9af4b4b0dad1ecad4ba6d9b8f4c862ee87fe4c47aae7c28a7038"
)
DEFAULT_PROMPT_OVERLAY = (
    ROOT / "pipeline/contracts/tensile_vlm_v4_1_prompt_clarified.json"
)


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kError(f"无法读取 {label}: {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_overlay(path: Path) -> dict[str, Any]:
    overlay = _read_json(path, "prompt overlay")
    analysis = overlay.get("analysis") if isinstance(overlay, Mapping) else None
    if (
        not isinstance(overlay, Mapping)
        or overlay.get("schema_version")
        != "tensile-vlm-v4.1-analysis-prompt-overlay/v1"
        or overlay.get("base_contract_version") != "tensile-vlm/v4.1"
        or not isinstance(overlay.get("base_contract_hash"), str)
        or not isinstance(overlay.get("prompt_revision_id"), str)
        or not isinstance(analysis, Mapping)
        or not isinstance(analysis.get("system_prompt"), str)
        or not isinstance(analysis.get("user_prompt"), str)
    ):
        raise SourceAware3kError("prompt overlay 身份或 analysis 字段非法")
    return dict(overlay)


def sampling_identity(
    *,
    prompt_overlay_sha256: str,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_sampling_id": SOURCE_SAMPLING_ID,
        "source_sampling_manifest_sha256": SOURCE_SAMPLING_MANIFEST_SHA256,
        "prompt_overlay_sha256": prompt_overlay_sha256,
    }
    return f"source-aware-3k-prompt-clarified-{_sha256_bytes(_canonical_bytes(payload))[:12]}"


def _rewrite_dataset(
    rows: Any,
    *,
    analysis: Mapping[str, Any],
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise SourceAware3kError(f"{label} 不是列表")
    rewritten: list[dict[str, Any]] = []
    for index, source_row in enumerate(rows):
        if not isinstance(source_row, Mapping):
            raise SourceAware3kError(f"{label}[{index}] 不是对象")
        row = copy.deepcopy(dict(source_row))
        messages = row.get("messages")
        if (
            not isinstance(messages, list)
            or len(messages) != 3
            or [item.get("role") for item in messages]
            != ["system", "user", "assistant"]
        ):
            raise SourceAware3kError(f"{label}[{index}] messages 结构非法")
        messages[0]["content"] = analysis["system_prompt"]
        messages[1]["content"] = f"<video>\n{analysis['user_prompt']}"
        rewritten.append(row)
    return rewritten


def build_prompt_clarified_source_aware_3k(
    *,
    release_dir: Path,
    media_root: Path,
    output_root: Path,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    verify_media: bool = False,
    validate_only: bool = False,
    prompt_overlay_path: Path = DEFAULT_PROMPT_OVERLAY,
) -> tuple[Path, dict[str, Any]]:
    """Validate the source artifact and freeze only the clarified prompt view."""
    normalized_seeds = tuple(int(seed) for seed in seeds)
    source_dir, source_summary = build_source_aware_3k(
        release_dir=release_dir,
        media_root=media_root,
        output_root=output_root,
        seeds=normalized_seeds,
        verify_media=verify_media,
        validate_only=True,
        policy_version=COVERAGE_FIRST_POLICY_VERSION,
        coverage_first=True,
    )
    source_manifest_path = source_dir / "sampling_manifest.json"
    if (
        source_dir.name != SOURCE_SAMPLING_ID
        or _sha256(source_manifest_path) != SOURCE_SAMPLING_MANIFEST_SHA256
    ):
        raise SourceAware3kError("coverage-first source sampling 身份漂移")
    source_manifest = _read_json(source_manifest_path, "source sampling manifest")
    overlay = _validate_overlay(prompt_overlay_path)
    overlay_sha256 = _sha256(prompt_overlay_path)
    sampling_id = sampling_identity(prompt_overlay_sha256=overlay_sha256)
    prompt_identity = {
        "prompt_revision_id": overlay["prompt_revision_id"],
        "prompt_overlay_path": str(prompt_overlay_path.relative_to(ROOT)),
        "prompt_overlay_sha256": overlay_sha256,
        "changed_variable": overlay["changed_variable"],
    }
    files: dict[str, bytes] = {
        "dataset_info.json": (source_dir / "dataset_info.json").read_bytes(),
    }
    analysis = overlay["analysis"]
    dataset_paths = [
        Path(f"datasets/seed_{seed}.json") for seed in normalized_seeds
    ] + [Path("datasets/fold_0_validation.json")]
    for relative in dataset_paths:
        rows = _read_json(source_dir / relative, str(relative))
        rewritten = _rewrite_dataset(
            rows,
            analysis=analysis,
            label=str(relative),
        )
        files[str(relative)] = _pretty_bytes(rewritten)
    manifest = {
        **source_manifest,
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "sampling_id": sampling_id,
        "source_sampling": {
            "sampling_id": SOURCE_SAMPLING_ID,
            "sampling_manifest_sha256": SOURCE_SAMPLING_MANIFEST_SHA256,
        },
        "prompt_overlay": prompt_identity,
    }
    files["sampling_manifest.json"] = _pretty_bytes(manifest)
    file_manifest = [
        {
            "path": relative,
            "size_bytes": len(content),
            "sha256": _sha256_bytes(content),
        }
        for relative, content in sorted(files.items())
    ]
    summary = {
        **source_summary,
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "sampling_id": sampling_id,
        "source_sampling": manifest["source_sampling"],
        "prompt_overlay": prompt_identity,
        "files": file_manifest,
    }
    output_dir = Path(output_root) / sampling_id
    if not validate_only or output_dir.exists():
        _write_immutable_directory(output_dir, files=files, summary=summary)
    return output_dir, summary


def parse_args() -> argparse.Namespace:
    paths = current_data_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=paths.training_releases / "v4.1.0-ecb5aeb9657c",
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        default=paths.compatibility_workspace,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=paths.metadata / "v4_1/source_aware_3k",
    )
    parser.add_argument("--verify-media", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output, summary = build_prompt_clarified_source_aware_3k(
        release_dir=args.release_dir,
        media_root=args.media_root,
        output_root=args.output_root,
        verify_media=args.verify_media,
        validate_only=args.validate_only,
    )
    print(
        json.dumps(
            {
                "output_dir": str(output),
                "sampling_id": summary["sampling_id"],
                "prompt_overlay": summary["prompt_overlay"],
                "expected_optimizer_steps_per_seed": summary[
                    "expected_optimizer_steps_per_seed"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
