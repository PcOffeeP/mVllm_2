#!/usr/bin/env python3
"""Authorize Stage C only from passed, full-hash Stage B evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.run_v4_1_source_aware_3k import (
    RELEASE_ID,
    RESULT_ROOT,
    RUN_ID,
    SAMPLING_ID,
    SEEDS,
)


class StageCAuthorizationError(ValueError):
    """Stage B evidence does not authorize starting Stage C."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageCAuthorizationError(
            f"无法读取 {label} {path}: {exc}"
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StageCAuthorizationError(f"授权输入不存在: {path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def build_authorization(
    *,
    gate_report_path: Path,
    evidence_manifest_path: Path,
) -> tuple[str, dict[str, Any]]:
    gates = _read_json(gate_report_path, "Stage B gate report")
    evidence = _read_json(evidence_manifest_path, "Stage B evidence manifest")
    if (
        not isinstance(gates, Mapping)
        or gates.get("schema_version")
        != "tensile-vlm-v4.1-source-aware-3k-gates/v1"
        or gates.get("run_id") != RUN_ID
        or gates.get("release_id") != RELEASE_ID
        or gates.get("passed") is not True
    ):
        raise StageCAuthorizationError("Stage B gate report 未通过或身份漂移")
    gate_seeds = gates.get("seeds")
    if (
        not isinstance(gate_seeds, list)
        or [item.get("seed") for item in gate_seeds if isinstance(item, Mapping)]
        != list(SEEDS)
        or any(item.get("passed") is not True for item in gate_seeds)
    ):
        raise StageCAuthorizationError("Stage B 双 seed 未全部通过")
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("schema_version")
        != "tensile-vlm-v4.1-source-aware-3k-evidence/v1"
        or evidence.get("run_id") != RUN_ID
        or evidence.get("release_id") != RELEASE_ID
        or evidence.get("sampling_id") != SAMPLING_ID
        or evidence.get("model_hash_mode") != "full"
        or evidence.get("training_code_commit")
        != "f6ba152121d394141ddddaf73926e3a9c065d0a8"
        or not isinstance(evidence.get("evidence_freeze_code_commit"), str)
        or len(evidence["evidence_freeze_code_commit"]) != 40
    ):
        raise StageCAuthorizationError(
            "Stage B evidence 必须身份一致、区分训练/冻结代码且使用 full model hashes"
        )
    trainer_states = evidence.get("trainer_states")
    coverage = evidence.get("adapter_coverage")
    models = evidence.get("model_artifacts")
    if not all(isinstance(value, Mapping) for value in (trainer_states, coverage, models)):
        raise StageCAuthorizationError("Stage B evidence 缺少训练或模型身份")
    for seed in SEEDS:
        state = trainer_states.get(str(seed))
        seed_coverage = coverage.get(str(seed))
        if (
            not isinstance(state, Mapping)
            or state.get("global_step") != 1125
            or not isinstance(seed_coverage, Mapping)
            or seed_coverage.get("visual") is not True
            or not seed_coverage.get("visual_weight_count")
            or not seed_coverage.get("resampler_weight_count")
            or seed_coverage.get("resampler_saved") is not True
        ):
            raise StageCAuthorizationError(
                f"seed{seed} 训练步数或视觉 adapter 覆盖不完整"
            )
        for role in ("adapter", "merged_bf16"):
            artifact = models.get(f"seed{seed}_{role}")
            if (
                not isinstance(artifact, Mapping)
                or artifact.get("hash_mode") != "full"
                or not isinstance(artifact.get("aggregate_sha256"), str)
                or len(artifact["aggregate_sha256"]) != 64
            ):
                raise StageCAuthorizationError(
                    f"seed{seed} {role} 缺少 full-hash 身份"
                )
    gate_identity = _identity(gate_report_path)
    evidence_identity = _identity(evidence_manifest_path)
    seed = {
        "schema_version": "tensile-vlm-v4.1-stage-c-authorization/v1",
        "stage_b_run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "sampling_id": SAMPLING_ID,
        "gate_report_sha256": gate_identity["sha256"],
        "evidence_manifest_sha256": evidence_identity["sha256"],
    }
    authorization_id = (
        "stage-c-authorization-"
        + hashlib.sha256(
            json.dumps(seed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
    )
    payload = {
        **seed,
        "authorization_id": authorization_id,
        "status": "authorized",
        "stage_b_passed": True,
        "stage_c_authorized": True,
        "both_seeds_passed": list(SEEDS),
        "gate_report": gate_identity,
        "evidence_manifest": evidence_identity,
    }
    return authorization_id, payload


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise StageCAuthorizationError(
                f"拒绝覆盖已有 Stage C authorization: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate-report",
        type=Path,
        default=RESULT_ROOT / "stage_b_gate_report.json",
    )
    parser.add_argument(
        "--evidence-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=RESULT_ROOT / "stage_c_authorizations",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    authorization_id, payload = build_authorization(
        gate_report_path=args.gate_report,
        evidence_manifest_path=args.evidence_manifest,
    )
    output = args.output_root / authorization_id / "stage_c_authorization.json"
    if not args.validate_only:
        _write_immutable(output, payload)
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "frozen",
                "output": str(output),
                **payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
