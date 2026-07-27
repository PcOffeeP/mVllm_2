#!/usr/bin/env python3
"""Run the authorized one-time V4.1 Stage D sealed evaluation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.run_v4_1_evaluation import (
    _load_contract,
    evaluate_one,
)
from finetune.v4_1_stage_d_runtime import (
    StageDRuntimeError,
    atomic_write,
    build_gate_reports,
    build_run_identity,
    claim_one_time_run,
    load_sealed_release,
    pretty_bytes,
    read_json,
    require_mapping,
    validate_authorization,
)
from finetune.validation.model_runtime import load_model

FINETUNE = ROOT / "finetune"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def _prepare_output(
    output_dir: Path,
    run_identity: Mapping[str, Any],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    identity_path = output_dir / "run_identity.json"
    if identity_path.exists():
        if read_json(identity_path, "Stage D run identity") != dict(
            run_identity
        ):
            raise StageDRuntimeError("Stage D output run identity 漂移")
    else:
        atomic_write(identity_path, pretty_bytes(run_identity), mode=0o600)
    return (
        output_dir / "evaluation_records.jsonl",
        output_dir / "runtime_failures.csv",
    )


def _load_existing_records(
    path: Path,
    expected_candidates: list[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    expected = {
        str(row["candidate_id"]): row for row in expected_candidates
    }
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StageDRuntimeError(
                f"{path}:{line_no}: 非法 JSONL；需按身份隔离后恢复"
            ) from exc
        candidate_id = row.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or candidate_id not in expected
            or candidate_id in records
        ):
            raise StageDRuntimeError(
                f"{path}:{line_no}: candidate_id 越界或重复"
            )
        candidate = expected[candidate_id]
        if (
            row.get("source_video") != candidate.get("source_video")
            or row.get("video_path") != candidate.get("video_path")
            or row.get("target") != candidate.get("labels")
            or not isinstance(row.get("scores"), Mapping)
            or not isinstance(row.get("strict_valid"), bool)
        ):
            raise StageDRuntimeError(
                f"{path}:{line_no}: record 与 sealed candidate 身份不一致"
            )
        records[candidate_id] = row
    return records


def _write_failures(
    path: Path,
    records: list[Mapping[str, Any]],
) -> None:
    rows = [
        {
            "candidate_id": row["candidate_id"],
            "video_path": row["video_path"],
            "runtime_error": row["runtime_error"],
        }
        for row in records
        if row.get("runtime_error")
    ]
    content_lines = ["candidate_id,video_path,runtime_error"]
    for row in rows:
        values = []
        for key in ("candidate_id", "video_path", "runtime_error"):
            value = str(row[key]).replace('"', '""')
            values.append(f'"{value}"')
        content_lines.append(",".join(values))
    atomic_write(
        path,
        ("\n".join(content_lines) + "\n").encode(),
        mode=0o600,
    )


def _write_final(
    output_dir: Path,
    run_identity: Mapping[str, Any],
    records: list[dict[str, Any]],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    restricted, public = build_gate_reports(
        run_identity=run_identity,
        records=records,
        thresholds=thresholds,
    )
    atomic_write(
        output_dir / "evaluation_summary.restricted.json",
        pretty_bytes(restricted),
        mode=0o600,
    )
    atomic_write(
        output_dir / "stage_d_gate.json",
        pretty_bytes(public),
        mode=0o600,
    )
    _write_failures(output_dir / "runtime_failures.csv", records)
    return public


def main() -> int:
    args = parse_args()
    prepared, authorization = validate_authorization(
        args.authorization,
        prepared_manifest_path=args.prepared_manifest,
    )
    run_identity = build_run_identity(prepared, authorization)
    release, candidates, release_manifest_sha256 = load_sealed_release(
        Path(prepared["sealed_test"]["release_dir"])
    )
    if (
        release["release_id"] != run_identity["identity"]["release_id"]
        or release_manifest_sha256
        != run_identity["identity"]["release_manifest_sha256"]
        or len(candidates) != run_identity["identity"]["sample_count"]
    ):
        raise StageDRuntimeError("Stage D release 与 run identity 不一致")
    output_root = Path(prepared["execution"]["output_root"])
    output_dir = output_root / run_identity["run_id"]
    claim_path = (
        output_root.parent
        / "v4_1_stage_d_claims"
        / release["release_id"]
        / "claim.json"
    )
    if args.validate_only:
        print(
            json.dumps(
                {
                    "mode": "validate-only",
                    "run_id": run_identity["run_id"],
                    "release_id": release["release_id"],
                    "sample_count": len(candidates),
                    "output_dir": str(output_dir),
                    "claim_path": str(claim_path),
                    "model_call_started": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    records_path, _ = _prepare_output(output_dir, run_identity)
    claim_one_time_run(
        claim_path,
        run_identity=run_identity,
        authorization=authorization,
    )
    expected_ids = [str(row["candidate_id"]) for row in candidates]
    existing = _load_existing_records(records_path, candidates)
    if len(existing) == len(candidates):
        ordered = [existing[item] for item in expected_ids]
        public = _write_final(
            output_dir,
            run_identity,
            ordered,
            prepared["thresholds"],
        )
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return 0

    contract, _ = _load_contract()
    processor, model = load_model(str(prepared["model"]["path"]))
    analysis = require_mapping(contract.get("analysis"), "contract.analysis")
    records_path.touch(mode=0o600, exist_ok=True)
    os.chmod(records_path, 0o600)
    with records_path.open("a", encoding="utf-8") as handle:
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            if candidate_id in existing:
                continue
            sample = {
                "candidate_id": candidate_id,
                "source_video": candidate["source_video"],
                "video_path": candidate["video_path"],
                "target": candidate["labels"],
            }
            record = evaluate_one(
                sample=sample,
                model=model,
                processor=processor,
                system_prompt=str(analysis["system_prompt"]),
                user_prompt=str(analysis["user_prompt"]),
            )
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            existing[candidate_id] = record
            print(
                f"progress={len(existing)}/{len(candidates)}",
                flush=True,
            )
    ordered = [existing[item] for item in expected_ids]
    public = _write_final(
        output_dir,
        run_identity,
        ordered,
        prepared["thresholds"],
    )
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
