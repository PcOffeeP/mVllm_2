"""Fail-closed identities and restricted artifacts for one-time Stage D evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_sealed_test_release import (
    READY_STATUS,
    SEALED_GROUND_TRUTH_SCHEMA_VERSION,
    SEALED_TEST_RELEASE_SCHEMA_VERSION,
)

PREPARATION_SCHEMA_VERSION = "tensile-vlm/stage-d-preparation/v1"
AUTHORIZATION_SCHEMA_VERSION = "tensile-vlm/stage-d-authorization/v1"
RUN_IDENTITY_SCHEMA_VERSION = "tensile-vlm/stage-d-run/v1"
CLAIM_SCHEMA_VERSION = "tensile-vlm/stage-d-one-time-claim/v1"
RESTRICTED_REPORT_SCHEMA_VERSION = "tensile-vlm/stage-d-restricted-report/v1"
PUBLIC_GATE_SCHEMA_VERSION = "tensile-vlm/stage-d-public-gate/v1"
AUTHORIZATION_SCOPE = "one_time_sealed_clip_evaluation"
FOUR_STATES = ("未断裂", "临界未断裂", "发生断裂", "已断裂")
FRACTURE_STATES = ("临界未断裂", "发生断裂", "已断裂")
DEFAULT_THRESHOLDS = {
    "runtime_failure_count": 0,
    "strict_valid_rate": 1.0,
    "fracture_three_state_macro_recall": 0.30,
    "four_state_macro_recall": 0.4006,
    "已断裂_recall": 0.15,
    "未断裂_recall": 0.70,
    "joint_correct_rate": 0.3921,
}


class StageDRuntimeError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StageDRuntimeError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StageDRuntimeError(f"{label}不是合法 JSON: {path}") from exc


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StageDRuntimeError(f"{label}必须是对象")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise StageDRuntimeError(f"{label}必须是列表")
    return value


def atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.read_bytes() != content:
            raise StageDRuntimeError(f"拒绝覆盖身份不同的冻结文件: {path}")
        os.chmod(path, mode)
        return
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def git_head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def git_commit_time(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", "HEAD"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _verified_file(
    release_dir: Path,
    entry: Mapping[str, Any],
) -> Path:
    relative = entry.get("path")
    if not isinstance(relative, str) or not relative:
        raise StageDRuntimeError("sealed release file path 非法")
    root = release_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise StageDRuntimeError(f"sealed release file 越界: {relative}")
    if (
        not path.is_file()
        or path.stat().st_size != entry.get("size_bytes")
        or sha256_file(path) != entry.get("sha256")
    ):
        raise StageDRuntimeError(f"sealed release file 漂移: {relative}")
    expected_mode = 0o600
    if (path.stat().st_mode & 0o777) != expected_mode:
        raise StageDRuntimeError(
            f"sealed release file 权限必须是 0600: {relative}"
        )
    return path


def load_sealed_release(
    release_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    release_dir = Path(release_dir).resolve()
    manifest_path = release_dir / "manifest/release_manifest.json"
    manifest = dict(
        require_mapping(
            read_json(manifest_path, "sealed release manifest"),
            "sealed release manifest",
        )
    )
    if (
        manifest.get("schema_version") != SEALED_TEST_RELEASE_SCHEMA_VERSION
        or manifest.get("status") != READY_STATUS
        or manifest.get("immutable") is not True
        or manifest.get("sealed") is not True
        or manifest.get("access_policy", {}).get(
            "one_time_evaluation_authorized"
        )
        is not False
    ):
        raise StageDRuntimeError("sealed release 状态或访问策略非法")
    if (release_dir.stat().st_mode & 0o777) != 0o700:
        raise StageDRuntimeError("sealed release 目录权限必须是 0700")
    entries = [
        require_mapping(row, "sealed release file")
        for row in require_list(manifest.get("files"), "sealed release files")
    ]
    file_index = {str(row.get("path")): row for row in entries}
    if len(file_index) != len(entries):
        raise StageDRuntimeError("sealed release files 路径重复")
    for entry in entries:
        _verified_file(release_dir, entry)
    truth_entry = file_index.get("metadata/sealed_ground_truth.json")
    if truth_entry is None or truth_entry.get("access") != "restricted":
        raise StageDRuntimeError("sealed release 缺少受限 ground truth")
    truth_path = release_dir / "metadata/sealed_ground_truth.json"
    truth = require_mapping(
        read_json(truth_path, "sealed ground truth"),
        "sealed ground truth",
    )
    candidates = [
        dict(require_mapping(row, "sealed candidate"))
        for row in require_list(truth.get("candidates"), "sealed candidates")
    ]
    ids = [str(row.get("candidate_id") or "") for row in candidates]
    sources = {str(row.get("source_video") or "") for row in candidates}
    if (
        truth.get("schema_version") != SEALED_GROUND_TRUTH_SCHEMA_VERSION
        or truth.get("release_id") != manifest.get("release_id")
        or truth.get("candidate_count") != len(candidates)
        or manifest.get("counts", {}).get("admitted_candidates")
        != len(candidates)
        or any(not item for item in ids)
        or len(ids) != len(set(ids))
        or "" in sources
        or manifest.get("counts", {}).get("admitted_sources") != len(sources)
    ):
        raise StageDRuntimeError("sealed ground truth 身份、数量或来源非法")
    for row in candidates:
        if (
            not isinstance(row.get("labels"), Mapping)
            or not isinstance(row.get("video_path"), str)
            or not isinstance(row.get("video_sha256"), str)
            or not isinstance(row.get("frames"), list)
            or not row["frames"]
        ):
            raise StageDRuntimeError(
                f"{row.get('candidate_id')}: sealed candidate 非法"
            )
    return manifest, candidates, sha256_file(manifest_path)


def _artifact(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise StageDRuntimeError(f"{label}不存在: {path}")
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _validate_model_acceptance(
    path: Path,
    *,
    model_dir: Path,
    expected_aggregate_sha256: str,
) -> dict[str, Any]:
    payload = require_mapping(
        read_json(path, "Stage B intermediate acceptance"),
        "Stage B intermediate acceptance",
    )
    merged = require_mapping(
        require_mapping(payload.get("models"), "acceptance.models").get(
            "merged_bf16"
        ),
        "acceptance.models.merged_bf16",
    )
    if (
        payload.get("schema_version")
        != "tensile-vlm-v4.1-stage-b-intermediate-acceptance/v1"
        or payload.get("status") != "accepted_as_intermediate_with_known_limits"
        or payload.get("original_stage_b_quality_gate_passed") is not False
        or payload.get("stage_d_independent_model_acceptance_authorized")
        is not False
        or merged.get("hash_mode") != "full"
        or merged.get("aggregate_sha256") != expected_aggregate_sha256
        or Path(str(merged.get("path_at_freeze"))).resolve()
        != Path(model_dir).resolve()
    ):
        raise StageDRuntimeError(
            "Stage B intermediate acceptance 与模型或既有限制不一致"
        )
    return {
        "acceptance_id": payload["acceptance_id"],
        "manifest": _artifact(path, "Stage B intermediate acceptance"),
        "original_quality_gate_passed": False,
        "stage_d_authorized_by_stage_b": False,
    }


def build_preparation(
    *,
    project_root: Path,
    release_dir: Path,
    model_dir: Path,
    model_aggregate_sha256: str,
    stage_b_acceptance_path: Path,
    deployment_summary_path: Path,
    agent_acceptance_summary_path: Path,
    contract_path: Path,
    runner_path: Path,
    evaluator_path: Path,
    output_root: Path,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    release, candidates, release_manifest_sha256 = load_sealed_release(
        release_dir
    )
    model_dir = Path(model_dir).resolve()
    if not model_dir.is_dir():
        raise StageDRuntimeError(f"merged BF16 model 不存在: {model_dir}")
    acceptance = _validate_model_acceptance(
        stage_b_acceptance_path,
        model_dir=model_dir,
        expected_aggregate_sha256=model_aggregate_sha256,
    )
    deployment_summary = require_mapping(
        read_json(deployment_summary_path, "Stage E deployment summary"),
        "Stage E deployment summary",
    )
    if (
        deployment_summary.get("acceptance_id") != acceptance["acceptance_id"]
        or deployment_summary.get("contract_hash") != release.get(
            "contract_hash"
        )
        or deployment_summary.get("model_aggregate_sha256")
        != model_aggregate_sha256
        or deployment_summary.get("authorization_scope", {}).get(
            "stage_d_independent_model_acceptance"
        )
        is not False
    ):
        raise StageDRuntimeError("Stage E deployment 与模型、契约或权限不一致")
    agent_summary = require_mapping(
        read_json(agent_acceptance_summary_path, "Stage F acceptance summary"),
        "Stage F acceptance summary",
    )
    if (
        agent_summary.get("stage_b_intermediate_acceptance_id")
        != acceptance["acceptance_id"]
        or agent_summary.get("visual_contract_hash")
        != release.get("contract_hash")
        or agent_summary.get("heldout_semantics_opened") is not False
    ):
        raise StageDRuntimeError("Stage F acceptance 与 Stage B/contract 不一致")
    contract = require_mapping(read_json(contract_path, "V4.1 contract"), "contract")
    normalized_contract = dict(contract)
    declared_contract_hash = normalized_contract.pop("contract_hash", None)
    if (
        contract.get("contract_version") != "tensile-vlm/v4.1"
        or declared_contract_hash
        != sha256_bytes(canonical_bytes(normalized_contract))
        or declared_contract_hash != release.get("contract_hash")
    ):
        raise StageDRuntimeError("V4.1 contract 身份漂移")
    analysis = require_mapping(contract.get("analysis"), "contract.analysis")
    generation = require_mapping(
        analysis.get("generation"), "contract.analysis.generation"
    )
    effective_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds is not None:
        effective_thresholds = dict(thresholds)
    if effective_thresholds != DEFAULT_THRESHOLDS:
        raise StageDRuntimeError("Stage D 固定阈值不允许漂移")
    seed = {
        "code_commit": git_head(project_root),
        "release_id": release["release_id"],
        "release_manifest_sha256": release_manifest_sha256,
        "model_aggregate_sha256": model_aggregate_sha256,
        "stage_b_acceptance_sha256": acceptance["manifest"]["sha256"],
        "deployment_summary_sha256": sha256_file(deployment_summary_path),
        "agent_acceptance_summary_sha256": sha256_file(
            agent_acceptance_summary_path
        ),
        "contract_hash": declared_contract_hash,
        "runner_sha256": sha256_file(runner_path),
        "evaluator_sha256": sha256_file(evaluator_path),
        "thresholds": effective_thresholds,
        "generation": dict(generation),
        "sample_count": len(candidates),
    }
    preparation_id = (
        "stage-d-preparation-" + sha256_bytes(canonical_bytes(seed))[:12]
    )
    return {
        "schema_version": PREPARATION_SCHEMA_VERSION,
        "preparation_id": preparation_id,
        "status": "prepared_awaiting_one_time_authorization",
        "created_at": git_commit_time(project_root),
        "code_commit": seed["code_commit"],
        "sealed_test": {
            "release_id": release["release_id"],
            "release_dir": str(Path(release_dir).resolve()),
            "manifest_sha256": release_manifest_sha256,
            "sample_count": len(candidates),
            "source_count": release["counts"]["admitted_sources"],
            "access_policy": release["access_policy"],
        },
        "model": {
            "path": str(model_dir),
            "aggregate_sha256": model_aggregate_sha256,
            "precision": "BF16",
            "disposition": "intermediate_development_model",
        },
        "stage_b": acceptance,
        "stage_e": {
            "summary": _artifact(
                deployment_summary_path, "Stage E deployment summary"
            ),
            "production_alias": False,
        },
        "stage_f": {
            "summary": _artifact(
                agent_acceptance_summary_path,
                "Stage F acceptance summary",
            ),
            "agent_acceptance_id": agent_summary["agent_acceptance_id"],
            "agent_runtime_commit": agent_summary["agent_runtime_commit"],
        },
        "contract": {
            "version": contract["contract_version"],
            "hash": declared_contract_hash,
            "file": _artifact(contract_path, "V4.1 contract"),
            "generation": dict(generation),
        },
        "execution": {
            "runner": _artifact(runner_path, "Stage D runner"),
            "evaluator": _artifact(evaluator_path, "V4.1 evaluator"),
            "output_root": str(Path(output_root).resolve()),
            "resume_policy": "same_identity_only",
            "one_time_claim_required_before_first_model_call": True,
            "pre_stage_g_visibility": "pass_fail_and_integrity_only",
        },
        "thresholds": effective_thresholds,
        "authorization": {
            "authorized": False,
            "required_schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "scope": AUTHORIZATION_SCOPE,
        },
        "identity_seed": seed,
    }


def freeze_preparation(path: Path, preparation: Mapping[str, Any]) -> None:
    atomic_write(path, pretty_bytes(preparation), mode=0o600)


def build_authorization(
    *,
    prepared_manifest_path: Path,
    authorized_by: str,
    user_authorization_reference: str,
    authorized_at: str | None = None,
) -> dict[str, Any]:
    prepared = require_mapping(
        read_json(prepared_manifest_path, "Stage D preparation"),
        "Stage D preparation",
    )
    if (
        prepared.get("schema_version") != PREPARATION_SCHEMA_VERSION
        or prepared.get("status") != "prepared_awaiting_one_time_authorization"
        or prepared.get("authorization", {}).get("authorized") is not False
        or not authorized_by.strip()
        or not user_authorization_reference.strip()
    ):
        raise StageDRuntimeError("Stage D preparation 或授权主体非法")
    seed = {
        "prepared_manifest_sha256": sha256_file(prepared_manifest_path),
        "preparation_id": prepared["preparation_id"],
        "sealed_test_release_id": prepared["sealed_test"]["release_id"],
        "sealed_test_manifest_sha256": prepared["sealed_test"][
            "manifest_sha256"
        ],
        "model_aggregate_sha256": prepared["model"]["aggregate_sha256"],
        "scope": AUTHORIZATION_SCOPE,
        "authorized_by": authorized_by.strip(),
        "authorized_at": authorized_at
        or datetime.now(timezone.utc).isoformat(),
        "user_authorization_reference": user_authorization_reference.strip(),
    }
    body = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorized": True,
        "one_time": True,
        **seed,
    }
    authorization_id = (
        "stage-d-authorization-" + sha256_bytes(canonical_bytes(body))[:12]
    )
    return {"authorization_id": authorization_id, **body}


def validate_authorization(
    path: Path,
    *,
    prepared_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared = dict(
        require_mapping(
            read_json(prepared_manifest_path, "Stage D preparation"),
            "Stage D preparation",
        )
    )
    authorization = dict(
        require_mapping(
            read_json(path, "Stage D authorization"),
            "Stage D authorization",
        )
    )
    authorization_id = authorization.pop("authorization_id", None)
    expected_id = (
        "stage-d-authorization-"
        + sha256_bytes(canonical_bytes(authorization))[:12]
    )
    if (
        prepared.get("schema_version") != PREPARATION_SCHEMA_VERSION
        or prepared.get("code_commit")
        != git_head(Path(__file__).resolve().parents[1])
        or authorization.get("schema_version") != AUTHORIZATION_SCHEMA_VERSION
        or authorization_id != expected_id
        or authorization.get("authorized") is not True
        or authorization.get("one_time") is not True
        or authorization.get("scope") != AUTHORIZATION_SCOPE
        or authorization.get("prepared_manifest_sha256")
        != sha256_file(prepared_manifest_path)
        or authorization.get("preparation_id") != prepared.get("preparation_id")
        or authorization.get("sealed_test_release_id")
        != prepared.get("sealed_test", {}).get("release_id")
        or authorization.get("sealed_test_manifest_sha256")
        != prepared.get("sealed_test", {}).get("manifest_sha256")
        or authorization.get("model_aggregate_sha256")
        != prepared.get("model", {}).get("aggregate_sha256")
        or not str(authorization.get("authorized_by") or "").strip()
        or not str(
            authorization.get("user_authorization_reference") or ""
        ).strip()
    ):
        raise StageDRuntimeError("Stage D authorization 身份或绑定无效")
    for section, key in (
        ("stage_b", "manifest"),
        ("stage_e", "summary"),
        ("stage_f", "summary"),
        ("contract", "file"),
        ("execution", "runner"),
        ("execution", "evaluator"),
    ):
        descriptor = require_mapping(
            require_mapping(prepared.get(section), f"prepared.{section}").get(
                key
            ),
            f"prepared.{section}.{key}",
        )
        artifact_path = Path(str(descriptor.get("path") or ""))
        if (
            not artifact_path.is_file()
            or artifact_path.stat().st_size != descriptor.get("size_bytes")
            or sha256_file(artifact_path) != descriptor.get("sha256")
        ):
            raise StageDRuntimeError(
                f"Stage D prepared artifact 漂移: {section}.{key}"
            )
    if not Path(str(prepared.get("model", {}).get("path") or "")).is_dir():
        raise StageDRuntimeError("Stage D prepared model path 不存在")
    authorization["authorization_id"] = authorization_id
    return prepared, authorization


def build_run_identity(
    prepared: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    seed = {
        "preparation_id": prepared["preparation_id"],
        "authorization_id": authorization["authorization_id"],
        "code_commit": prepared["code_commit"],
        "release_id": prepared["sealed_test"]["release_id"],
        "release_manifest_sha256": prepared["sealed_test"][
            "manifest_sha256"
        ],
        "model_aggregate_sha256": prepared["model"]["aggregate_sha256"],
        "contract_hash": prepared["contract"]["hash"],
        "runner_sha256": prepared["execution"]["runner"]["sha256"],
        "evaluator_sha256": prepared["execution"]["evaluator"]["sha256"],
        "thresholds": prepared["thresholds"],
        "generation": prepared["contract"]["generation"],
        "sample_count": prepared["sealed_test"]["sample_count"],
    }
    run_id = "stage-d-run-" + sha256_bytes(canonical_bytes(seed))[:12]
    return {
        "schema_version": RUN_IDENTITY_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "authorized_not_started",
        "identity": seed,
        "visibility_until_stage_g_complete": (
            "pass_fail_and_integrity_only"
        ),
    }


def claim_one_time_run(
    claim_path: Path,
    *,
    run_identity: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    claim = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "release_id": run_identity["identity"]["release_id"],
        "run_id": run_identity["run_id"],
        "authorization_id": authorization["authorization_id"],
        "preparation_id": run_identity["identity"]["preparation_id"],
        "claimed_at": datetime.now(timezone.utc).isoformat(),
        "purpose": AUTHORIZATION_SCOPE,
    }
    claim_path = Path(claim_path)
    if claim_path.exists():
        existing = require_mapping(
            read_json(claim_path, "Stage D one-time claim"),
            "Stage D one-time claim",
        )
        comparable = dict(existing)
        comparable.pop("claimed_at", None)
        expected = dict(claim)
        expected.pop("claimed_at", None)
        if comparable != expected:
            raise StageDRuntimeError(
                "sealed release 已被其他 Stage D run claim"
            )
        return dict(existing)
    atomic_write(claim_path, pretty_bytes(claim), mode=0o600)
    return claim


def _recall(records: Iterable[Mapping[str, Any]], state: str) -> float | None:
    selected = [
        row for row in records if row["target"]["clip_state"] == state
    ]
    if not selected:
        return None
    correct = sum(
        isinstance(row.get("prediction"), Mapping)
        and row["prediction"].get("clip_state") == state
        for row in selected
    )
    return correct / len(selected)


def restricted_metrics(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise StageDRuntimeError("Stage D records 为空")
    recalls = {state: _recall(records, state) for state in FOUR_STATES}
    if any(value is None for value in recalls.values()):
        raise StageDRuntimeError("Stage D sealed release 未覆盖完整四状态")
    fracture_macro = sum(
        float(recalls[state]) for state in FRACTURE_STATES
    ) / len(FRACTURE_STATES)
    four_macro = sum(float(recalls[state]) for state in FOUR_STATES) / 4
    return {
        "sample_count": len(records),
        "clip_state_recall": {
            state: round(float(recalls[state]), 6) for state in FOUR_STATES
        },
        "fracture_three_state_macro_recall": round(fracture_macro, 6),
        "four_state_macro_recall": round(four_macro, 6),
        "已断裂_recall": round(float(recalls["已断裂"]), 6),
        "未断裂_recall": round(float(recalls["未断裂"]), 6),
        "joint_correct_rate": round(
            sum(
                bool((row.get("scores") or {}).get("joint_correct"))
                for row in records
            )
            / len(records),
            6,
        ),
        "strict_valid_rate": round(
            sum(row.get("strict_valid") is True for row in records)
            / len(records),
            6,
        ),
        "runtime_failure_count": sum(
            bool(row.get("runtime_error")) for row in records
        ),
    }


def build_gate_reports(
    *,
    run_identity: Mapping[str, Any],
    records: list[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = restricted_metrics(records)
    gate_results: dict[str, dict[str, Any]] = {}
    public_results: dict[str, dict[str, Any]] = {}
    for name, threshold in thresholds.items():
        value = metrics[name]
        if name == "runtime_failure_count":
            passed = int(value) == int(threshold)
            comparison = "equals"
        else:
            passed = float(value) >= float(threshold)
            comparison = "at_least"
        gate_results[name] = {
            "value": value,
            "threshold": threshold,
            "comparison": comparison,
            "passed": passed,
        }
        public_results[name] = {"passed": passed}
    passed = all(row["passed"] for row in gate_results.values())
    restricted = {
        "schema_version": RESTRICTED_REPORT_SCHEMA_VERSION,
        "run_id": run_identity["run_id"],
        "sample_count": len(records),
        "metrics": metrics,
        "gates": gate_results,
        "passed": passed,
        "sealed_test_exposed": True,
    }
    public = {
        "schema_version": PUBLIC_GATE_SCHEMA_VERSION,
        "run_id": run_identity["run_id"],
        "status": "completed",
        "integrity": {
            "record_count_matches_release": len(records)
            == run_identity["identity"]["sample_count"],
            "runtime_failure_zero": metrics["runtime_failure_count"] == 0,
            "strict_contract_100_percent": metrics["strict_valid_rate"] == 1.0,
        },
        "gates": public_results,
        "passed": passed,
        "sealed_test_exposed": True,
        "stage_g_may_start": True,
        "semantic_metrics_withheld_until_stage_g_complete": True,
    }
    return restricted, public
