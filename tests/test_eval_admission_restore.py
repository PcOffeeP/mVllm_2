"""Admission and disaster recovery with synthetic identities and temporary stores only.

Gate tests inject already-validated record snapshots at the validation boundary;
registry mutation and backup/restore tests use real temporary SQLite/filesystems.
No model, Ollama, SSH, project test split, or external account is accessed.
"""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from finetune import eval_run as ev
from versioning import registry as reg
from tests.test_full_training import full_model
from tests.test_model_sources import base_model, diagnostic_model
from tests.test_eval_holdout import forbid_truth
from tests.test_eval_holdout_semantic import prepare as prepare_independent, import_reviews
from finetune.eval_holdout import prepare_holdout_review, seal_holdout_review, score_holdout_evaluation
from versioning import backup
from versioning.mlflow_eval import get_eval_run, open_eval_store
from mlflow.tracking import MlflowClient


def evaluation(*, purpose="quality", protocol="semantic-holdout-v4.1", **changes):
    return SimpleNamespace(eval_id="eval-v4.1-r2", model_id="model-v4.1-r1",
        model_version_number=1, workflow_state="completed", outcome="passed",
        scope="full", purpose=purpose, protocol=protocol, run_id="synthetic-run", **changes)


def validated_quality():
    return {"scoring_protocol": "semantic-holdout-v4.1", "review_integrity": {
        "synthetic": False, "technical_isolation_verified": True,
        "real_model_deployment_verified": True}}


@pytest.mark.parametrize("purpose,protocol,actual_protocol", [
    ("development", "semantic-v4.1", "semantic-v4.1"),
    ("legacy", "strict-v4.1", "semantic-v4.1"),
    ("quality", "semantic-holdout-v4.1", "semantic-v4.1"),
    ("performance", "performance-v1", "performance-v1"),
    ("quality", "semantic-v4.1", "semantic-v4.1"),
])
def test_passed_development_or_performance_never_substitutes_for_quality(
        tmp_path, monkeypatch, purpose, protocol, actual_protocol):
    store = SimpleNamespace(root=tmp_path)
    record = evaluation(purpose=purpose, protocol=protocol)
    monkeypatch.setattr(reg, "_eval_store", lambda s: s)
    monkeypatch.setattr(reg, "validate_eval_for_conclusion", lambda *a: record)
    monkeypatch.setattr(reg, "_validate_eval_execution_artifacts",
        lambda *a: {**validated_quality(), "scoring_protocol": actual_protocol})
    with pytest.raises(reg.PromotionGateRejected, match="substitute"):
        reg._run_eval_gate(store, record.eval_id, require_passed=True)


@pytest.mark.parametrize("field,value", [
    ("synthetic", True), ("synthetic", None),
    ("technical_isolation_verified", False),
    ("real_model_deployment_verified", False),
])
def test_independent_quality_requires_verified_real_isolation(
        tmp_path, monkeypatch, field, value):
    record, evidence = evaluation(), validated_quality()
    evidence["review_integrity"][field] = value
    monkeypatch.setattr(reg, "_eval_store", lambda s: s)
    monkeypatch.setattr(reg, "validate_eval_for_conclusion", lambda *a: record)
    monkeypatch.setattr(reg, "_validate_eval_execution_artifacts", lambda *a: evidence)
    with pytest.raises(reg.PromotionGateRejected, match="real verified"):
        reg._run_eval_gate(SimpleNamespace(root=tmp_path), record.eval_id, require_passed=True)


@pytest.mark.parametrize("purpose,protocol,gate_purpose,allowed", [
    ("legacy", "strict-v4.1", "quality", True),
    ("quality", "semantic-holdout-v4.1", "quality", False),
    ("performance", "performance-v1", "performance", False),
])
def test_missing_validator_document_only_preserves_legacy_read_seam(
        monkeypatch, purpose, protocol, gate_purpose, allowed):
    record = evaluation(purpose=purpose, protocol=protocol)
    monkeypatch.setattr(reg, "_eval_store", lambda s: s)
    monkeypatch.setattr(reg, "validate_eval_for_conclusion", lambda *a: record)
    monkeypatch.setattr(reg, "_validate_eval_execution_artifacts", lambda *a: None)
    if allowed:
        assert reg._run_eval_gate(None, record.eval_id, require_passed=True,
            purpose=gate_purpose) is record
    else:
        with pytest.raises(reg.PromotionGateRejected):
            reg._run_eval_gate(None, record.eval_id, require_passed=True,
                purpose=gate_purpose)


def test_public_finalize_rejects_passed_development_without_registry_mutation(tmp_path, monkeypatch):
    root, store, model = full_model(tmp_path, monkeypatch)
    record = evaluation(purpose="development", protocol="semantic-v4.1")
    monkeypatch.setattr(reg, "validate_eval_for_conclusion", lambda *a: record)
    monkeypatch.setattr(reg, "_validate_eval_execution_artifacts",
        lambda *a: {"scoring_protocol": "semantic-v4.1"})
    with pytest.raises(reg.PromotionGateRejected, match="development"):
        reg.finalize_model_evaluation(store, model.model_id, eval_id=record.eval_id)
    current = reg.get_model(store, model.model_id)
    assert current.eval_id is None and current.performance_eval_id is None
    assert not current.production_approved and not current.aliases


@pytest.mark.parametrize("fixture_name", ["base_model", "diagnostic_model"])
def test_development_only_sources_cannot_bind_performance_or_gain_production(
        fixture_name, request, monkeypatch):
    store, model, *_ = request.getfixturevalue(fixture_name)
    # A passed performance proof must not be enough even before quality binding.
    monkeypatch.setattr(reg, "_run_eval_gate", lambda *a, **k: evaluation(
        purpose="performance", protocol="performance-v1"))
    for operation in (
        lambda: reg.bind_model_performance(store, model.model_id, eval_id="eval-v4.1-r2"),
        lambda: reg.approve_model_for_production(store, model.model_id),
        lambda: reg.finalize_model_evaluation(store, model.model_id, eval_id="eval-v4.1-r2"),
    ):
        with pytest.raises(reg.PromotionGateRejected, match="base and diagnostic"):
            operation()
    current = reg.get_model(store, model.model_id)
    assert current.performance_eval_id is None and current.eval_id is None
    assert not current.production_approved and not current.aliases


def paired_inputs():
    return {"model": {"model_id": "model-v4.1-r1", "version": 1,
                      "weights": {"adapter_model.safetensors": "a" * 64}},
        "prompt": {"version": "prompt-v4.1-r1", "sha256": "b" * 64},
        "config": {"generation": {"do_sample": False, "num_beams": 1},
                   "quantization_bit": None, "artifact_kind": "adapter",
                   "runtime_variant": {"dtype": "bfloat16", "preprocessing_sha256": "c" * 64},
                   "device": {"runtime_device": "cuda:0", "gpu_count": 1}},
        "implementation_sha256": {
            "finetune/validation/video_loader.py": "c" * 64,
            "pipeline/preprocessing/minicpm_preprocessor.py": "d" * 64}}


@pytest.mark.parametrize("damage", [
    "numeric_version", "model_identity", "weights", "prompt", "generation",
    "quantization", "artifact_kind", "frame_loader", "preprocessing",
    "synthetic", "missing_display", "missing_synthetic", "failed",
    "missing_runtime_attestation", "attestation_dtype", "attestation_device", "attestation_extra",
])
def test_performance_pair_rejects_wrong_identity_variant_or_missing_display(monkeypatch, damage):
    model = SimpleNamespace(model_id="model-v4.1-r1", version=1)
    quality = evaluation()
    performance = evaluation(purpose="performance", protocol="performance-v1")
    frozen_quality = paired_inputs()
    frozen_performance = deepcopy(frozen_quality)
    proof = {"synthetic": False, "e2e_verified": True, "outcome": "passed"}
    quality_proof = {"runtime_attestation": {key: deepcopy(frozen_quality["config"][key])
        for key in ("runtime_variant", "device", "quantization_bit")}}
    if damage == "numeric_version": performance.model_version_number = 2
    elif damage == "model_identity": performance.model_id = "model-v4.1-r3"
    elif damage == "weights": frozen_performance["model"]["weights"]["adapter_model.safetensors"] = "e" * 64
    elif damage == "prompt": frozen_performance["prompt"]["sha256"] = "e" * 64
    elif damage == "generation": frozen_performance["config"]["generation"]["do_sample"] = True
    elif damage == "quantization": frozen_performance["config"]["quantization_bit"] = 4
    elif damage == "artifact_kind": frozen_performance["config"]["artifact_kind"] = "merged"
    elif damage == "frame_loader": frozen_performance["implementation_sha256"]["finetune/validation/video_loader.py"] = "e" * 64
    elif damage == "preprocessing": frozen_performance["implementation_sha256"]["pipeline/preprocessing/minicpm_preprocessor.py"] = "e" * 64
    elif damage == "synthetic": proof["synthetic"] = True
    elif damage == "missing_display": proof["e2e_verified"] = False
    elif damage == "missing_synthetic": proof.pop("synthetic")
    elif damage == "failed": proof["outcome"] = "failed"
    elif damage == "missing_runtime_attestation": quality_proof = {}
    elif damage == "attestation_dtype": quality_proof["runtime_attestation"]["runtime_variant"]["dtype"] = "float16"
    elif damage == "attestation_device": quality_proof["runtime_attestation"]["device"]["gpu_count"] = 2
    elif damage == "attestation_extra": quality_proof["runtime_attestation"]["unverified"] = True
    monkeypatch.setattr(ev, "validate_evaluation_execution_artifacts",
        lambda **k: proof if k["record"] is performance else quality_proof)
    monkeypatch.setattr(reg, "_evaluation_input", lambda s, r:
        frozen_quality if r is quality else frozen_performance)
    with pytest.raises(reg.PromotionGateRejected,
        match="runtime attestation" if "attestation" in damage else None):
        reg._validate_performance_pair(None, model, performance, quality)


def test_matching_real_pair_passes_but_performance_only_does_not_grant_approval(tmp_path, monkeypatch):
    root, store, model = full_model(tmp_path, monkeypatch)
    performance = evaluation(purpose="performance", protocol="performance-v1")
    performance.model_version_number = model.version
    monkeypatch.setattr(reg, "_run_eval_gate", lambda *a, **k: performance)
    monkeypatch.setattr(ev, "validate_evaluation_execution_artifacts", lambda **k:
        {"synthetic": False, "e2e_verified": True, "outcome": "passed"}
        if k["record"] is performance else {"runtime_attestation": {
            key: paired_inputs()["config"][key] for key in ("runtime_variant", "device", "quantization_bit")}})
    bound = reg.bind_model_performance(store, model.model_id, eval_id=performance.eval_id)
    assert bound.performance_eval_id == performance.eval_id
    assert bound.eval_id is None and not bound.production_approved and not bound.aliases
    with pytest.raises(reg.PromotionGateRejected):
        reg.approve_model_for_production(store, model.model_id)
    monkeypatch.setattr(reg, "_evaluation_input", lambda *a: paired_inputs())
    reg._validate_performance_pair(store, bound, performance, evaluation())
    with pytest.raises(reg.ModelVersionConflict, match="rebound"):
        reg.bind_model_performance(store, model.model_id, eval_id="eval-v4.1-r3")


def test_new_quality_cannot_gain_service_admission_without_performance():
    model = SimpleNamespace(source_scope="full", performance_eval_id=None)
    with pytest.raises(reg.PromotionGateRejected, match="bound performance"):
        reg._validate_new_service_admission(None, model, evaluation())


def tree_bytes(root):
    # Process locks are ephemeral and must be recreated, never restored locked.
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(".lock")}


def backup_args(root, drive):
    return dict(data_root=root / "data", prompts_root=root,
        models_root=root / "workspace/models/materialized", backup_root=drive)


def restore_args(root):
    return dict(data_root=root / "data", prompts_root=root,
        models_root=root / "workspace/models/materialized", mlflow_root=root / "workspace/mlflow")


def prepared_phase(tmp_path, monkeypatch, phase):
    root, store, truth, kwargs, manual = prepare_independent(tmp_path, monkeypatch, blind=True)
    version = kwargs["eval_version"]
    if phase in {"exposed", "sealed", "consumed"}:
        prepare_holdout_review(root=root, eval_version=version, manual=manual)
    if phase in {"sealed", "consumed"}:
        # Failed infrastructure attempts are durable costs, not a fresh review after restore.
        with pytest.raises(ev.EvaluationReviewPending):
            seal_holdout_review(root=root, eval_version=version,
                blind_reviews=import_reviews(root, tmp_path, failed=True))
        seal_holdout_review(root=root, eval_version=version,
            blind_reviews=import_reviews(root, tmp_path))
    if phase == "consumed":
        score_holdout_evaluation(root=root, eval_version=version, executor="synthetic")
    return root, store, truth, version


@pytest.mark.parametrize("phase", ["inferred", "exposed", "sealed"])
def test_in_progress_unscoped_evaluation_restores_raw_authorization_and_review_attempts(
        tmp_path, monkeypatch, phase):
    root, store, truth, version = prepared_phase(tmp_path, monkeypatch, phase)
    workspace = ev._formal_workspace(root, version)
    source_files = tree_bytes(workspace)
    prereg_files = tree_bytes(root / "evaluations/staging" / version)
    auth_files = tree_bytes(truth.parent.parent / "authorization")
    run = get_eval_run(open_eval_store(store.root), version)
    assert reg.get_model(store, "model-v4.1-r1").offline_backup_scope is None
    drive = tmp_path / "drive"
    catalog = backup.create_backup(store, **backup_args(root, drive))
    evaluation_objects = [obj for obj in catalog.objects if obj.object_type == "evaluation_workspace"]
    assert evaluation_objects, "in-flight evaluation must be retained independently of model backup scope"
    catalog_paths = [f.path for obj in evaluation_objects for f in obj.files]
    assert any(path.endswith("restricted/predictions.json") for path in catalog_paths)
    if phase == "sealed":
        assert any(path.endswith("restricted/judge.json") for path in catalog_paths)
        assert any("review_attempts/0001.json" in path for path in catalog_paths)
    fresh = tmp_path / "restored"
    monkeypatch.setattr(ev, "load_model", lambda *a, **k: pytest.fail("restore must never load a model"))
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        backup.restore_backup(drive, **restore_args(fresh))
    restored_workspace = ev._formal_workspace(fresh, version)
    assert tree_bytes(restored_workspace) == source_files
    assert tree_bytes(fresh / "evaluations/staging" / version) == prereg_files
    assert tree_bytes(fresh / "data/releases/data-v4.1-r3/authorization") == auth_files
    restored = get_eval_run(open_eval_store(fresh / "workspace/mlflow"), version)
    assert (restored.run_id, restored.workflow_state, restored.outcome) == (
        run.run_id, run.workflow_state, run.outcome)
    for path in (restored_workspace / "restricted", *(restored_workspace / "restricted").rglob("*")):
        assert path.stat().st_mode & 0o077 == 0, f"restored private artifact leaked permissions: {path}"
    assert not (fresh / "data/releases/data-v4.1-r3/authorization/consumed.yaml").exists()


def test_consumed_disaster_recovery_is_same_run_and_never_reopens_truth_or_inference(tmp_path, monkeypatch):
    from versioning.manifest import export_model_manifest
    root, store, truth, version = prepared_phase(tmp_path, monkeypatch, "consumed")
    model = reg.set_offline_backup_scope(store, "model-v4.1-r1", "adapter")
    export_model_manifest(root / f"records/models/{model.model_id}/manifest.yaml",
        store=store, model_id=model.model_id)
    reg.materialize_model(store, model.model_id, root / "workspace/models/materialized")
    workspace_bytes = tree_bytes(ev._formal_workspace(root, version))
    auth_bytes = tree_bytes(truth.parent.parent / "authorization")
    run = get_eval_run(open_eval_store(store.root), version)
    drive = tmp_path / "drive"
    backup.create_backup(store, **backup_args(root, drive))
    # Move only this test's generated store out of the way. The old absolute
    # locations disappear, so recovery cannot silently consult the source store.
    root.rename(tmp_path / "unavailable-original-store")
    monkeypatch.setattr(ev, "load_model", lambda *a, **k: pytest.fail("recovery must not rerun inference"))
    backup.restore_backup(drive, **restore_args(root))
    assert tree_bytes(ev._formal_workspace(root, version)) == workspace_bytes
    assert tree_bytes(truth.parent.parent / "authorization") == auth_bytes
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        manifest = score_holdout_evaluation(root=root, eval_version=version, executor="synthetic")
        assert manifest == ev.export_versioned_evaluation(root=root, eval_version=version)
        with pytest.raises(ValueError, match="consumed|exposed"):
            ev.execute_versioned_evaluation(root=root, eval_version=version)
    restored = get_eval_run(open_eval_store(root / "workspace/mlflow"), version)
    assert (restored.run_id, restored.workflow_state, restored.outcome) == (
        run.run_id, "completed", run.outcome)
    assert tree_bytes(truth.parent.parent / "authorization") == auth_bytes
    assert tree_bytes(ev._formal_workspace(root, version) / "restricted") == {
        path.removeprefix("restricted/"): data for path, data in workspace_bytes.items()
        if path.startswith("restricted/")}


@pytest.mark.parametrize("suffix", ["restricted/predictions.json", "restricted/judge.json", "authorization/pre_registration.yaml"])
def test_backup_content_drift_is_rejected_before_any_restore_write(tmp_path, monkeypatch, suffix):
    root, store, truth, version = prepared_phase(tmp_path, monkeypatch, "sealed")
    drive = tmp_path / "drive"
    catalog = backup.create_backup(store, **backup_args(root, drive))
    candidates = [drive / f.path for obj in catalog.objects
        if obj.object_type == "evaluation_workspace" and obj.object_id == version
        for f in obj.files if f.path.endswith(suffix)]
    assert len(candidates) == 1
    candidates[0].chmod(0o600)
    candidates[0].write_bytes(candidates[0].read_bytes() + b"\nsynthetic corruption")
    fresh = tmp_path / "restore-must-not-exist"
    with pytest.raises(backup.BackupIntegrityError):
        backup.restore_backup(drive, **restore_args(fresh))
    assert not fresh.exists()


def test_backup_refuses_public_permissions_for_private_raw_before_publication(tmp_path, monkeypatch):
    root, store, truth, version = prepared_phase(tmp_path, monkeypatch, "exposed")
    private_raw = ev._formal_workspace(root, version) / "restricted/predictions.json"
    private_raw.chmod(0o444)
    drive = tmp_path / "drive"
    with pytest.raises(backup.BackupSourceSetError, match="owner-only"):
        backup.create_backup(store, **backup_args(root, drive))
    assert not drive.exists()


@pytest.fixture
def completed_strict(tmp_path, monkeypatch):
    from tests.test_eval_holdout import prepare_holdout
    root, store, truth, kwargs = prepare_holdout(tmp_path, monkeypatch)
    version = kwargs["eval_version"]
    ev.execute_versioned_evaluation(root=root, eval_version=version)
    score_holdout_evaluation(root=root, eval_version=version, executor="synthetic")
    assert get_eval_run(open_eval_store(store.root), version).outcome == "passed"
    return root, store, truth, version


def historical_model_tags(store, version, *, approved=False, alias=None):
    """Install a pre-existing registry snapshot, never invoke a new admission."""
    client = MlflowClient(tracking_uri=store.tracking_uri)
    model = reg.get_model(store, "model-v4.1-r1")
    tags = {"eval_id": version, "offline_backup_scope": "production_bundle"}
    if approved:
        tags["production_approved"] = "true"
    for name, value in tags.items():
        client.set_model_version_tag(reg.REGISTERED_MODEL_NAME, str(model.version), name, value)
    if alias:
        client.set_registered_model_alias(reg.REGISTERED_MODEL_NAME, alias, str(model.version))
    return reg.get_model(store, model.model_id)


def model_state(record):
    # MLflow search_model_versions and get_model_version_by_alias expose alias
    # membership differently; compare persistent model state separately.
    return {k: v for k, v in asdict(record).items() if k != "aliases"}


def test_new_passed_strict_evaluation_cannot_finalize(completed_strict):
    root, store, truth, version = completed_strict
    before = reg.get_model(store, "model-v4.1-r1")
    with pytest.raises(reg.PromotionGateRejected, match="new admission"):
        reg.finalize_model_evaluation(store, before.model_id, eval_id=version)
    assert reg.get_model(store, before.model_id) == before


@pytest.mark.parametrize("operation", ["approve", "alias"])
def test_legacy_binding_cannot_create_new_approval_or_alias(completed_strict, operation):
    root, store, truth, version = completed_strict
    before = historical_model_tags(store, version)
    with pytest.raises(reg.PromotionGateRejected, match="new admission"):
        if operation == "approve":
            reg.approve_model_for_production(store, before.model_id)
        else:
            reg.set_alias(store, before.model_id, "candidate")
    assert reg.get_model(store, before.model_id) == before


def test_historical_strict_approval_and_alias_restore_and_recover_only_same_identity(
        completed_strict, tmp_path, monkeypatch):
    from versioning.manifest import export_model_manifest
    root, store, truth, version = completed_strict
    before = historical_model_tags(store, version, approved=True, alias="production")
    export_model_manifest(root / f"records/models/{before.model_id}/manifest.yaml",
        store=store, model_id=before.model_id)
    reg.materialize_model(store, before.model_id, root / "workspace/models/materialized")
    drive = tmp_path / "historical-drive"
    backup.create_backup(store, **backup_args(root, drive))
    root.rename(tmp_path / "unavailable-historical-source")
    backup.restore_backup(drive, **restore_args(root))
    restored_store = reg.open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        guard.setattr(ev, "load_model", lambda *a, **k: pytest.fail("historical restore must not infer"))
        routed = reg.get_model_by_alias(restored_store, "production")
        assert model_state(routed) == model_state(before) and "production" in routed.aliases
        assert model_state(reg.approve_model_for_production(restored_store, before.model_id)) == model_state(before)
        assert model_state(reg.finalize_model_evaluation(restored_store, before.model_id, eval_id=version)) == model_state(before)
        assert model_state(reg.set_alias(restored_store, before.model_id, "production")) == model_state(before)
        with pytest.raises(reg.PromotionGateRejected, match="new admission"):
            reg.set_alias(restored_store, before.model_id, "candidate")
        with pytest.raises(reg.ModelVersionConflict):
            reg.finalize_model_evaluation(restored_store, before.model_id, eval_id="eval-v4.1-r9")
    assert model_state(reg.get_model(restored_store, before.model_id)) == model_state(before)
    assert reg.get_model_by_alias(restored_store, "production").version == before.version


@pytest.mark.parametrize("phase", ["sealed", "consumed"])
def test_relocated_same_identity_resumes_score_without_old_store_or_inference(
        tmp_path, monkeypatch, phase):
    from versioning.manifest import export_model_manifest
    root, store, truth, version = prepared_phase(tmp_path, monkeypatch, phase)
    model = reg.set_offline_backup_scope(store, "model-v4.1-r1", "adapter")
    export_model_manifest(root / f"records/models/{model.model_id}/manifest.yaml",
        store=store, model_id=model.model_id)
    reg.materialize_model(store, model.model_id, root / "workspace/models/materialized")
    frozen_bytes = (ev._formal_workspace(root, version) / "input/evaluation.yaml").read_bytes()
    private_bytes = tree_bytes(ev._formal_workspace(root, version) / "restricted")
    claim_bytes = tree_bytes(truth.parent.parent / "authorization")
    record = get_eval_run(open_eval_store(store.root), version)
    drive, fresh = tmp_path / "relocation-drive", tmp_path / "relocated-project"
    backup.create_backup(store, **backup_args(root, drive))
    root.rename(tmp_path / "unavailable-source")
    assert not root.exists()
    backup.restore_backup(drive, **restore_args(fresh))
    for name in ("restore-catalog.yaml", "restore-locations.json"):
        proof = fresh / "workspace/mlflow" / name
        assert proof.is_file() and proof.stat().st_mode & 0o777 == 0o400
    monkeypatch.setattr(ev, "load_model", lambda *a, **k: pytest.fail("relocation cannot rerun inference"))
    restored_truth = fresh / "data/releases/data-v4.1-r3/sealed_ground_truth/labels.json"
    def finish():
        manifest = score_holdout_evaluation(root=fresh, eval_version=version, executor="synthetic")
        assert manifest.is_file()
        assert ev.export_versioned_evaluation(root=fresh, eval_version=version) == manifest
        with pytest.raises(ValueError, match="consumed|exposed"):
            ev.execute_versioned_evaluation(root=fresh, eval_version=version)
    if phase == "consumed":
        with monkeypatch.context() as guard:
            forbid_truth(guard, restored_truth)
            finish()
        assert tree_bytes(ev._formal_workspace(fresh, version) / "restricted") == private_bytes
    else:
        finish()
        restored_private = tree_bytes(ev._formal_workspace(fresh, version) / "restricted")
        assert all(restored_private[path] == data for path, data in private_bytes.items())
    assert (ev._formal_workspace(fresh, version) / "input/evaluation.yaml").read_bytes() == frozen_bytes
    restored_auth = tree_bytes(restored_truth.parent.parent / "authorization")
    assert all(restored_auth[path] == data for path, data in claim_bytes.items())
    assert "exposed.yaml" in restored_auth and "consumed.yaml" in restored_auth
    restored_record = get_eval_run(open_eval_store(fresh / "workspace/mlflow"), version)
    assert restored_record.run_id == record.run_id and restored_record.workflow_state == "completed"
    assert not root.exists(), "recovery must not recreate or consult the original store"


@pytest.mark.parametrize("damage", ["missing_base", "changed_base", "changed_media",
    "changed_locator", "writable_locator", "public_catalog"])
def test_relocated_recovery_refuses_dependency_or_locator_drift_before_truth(
        tmp_path, monkeypatch, damage):
    from versioning.manifest import export_model_manifest
    root, store, truth, version = prepared_phase(tmp_path, monkeypatch, "sealed")
    model = reg.set_offline_backup_scope(store, "model-v4.1-r1", "adapter")
    export_model_manifest(root / f"records/models/{model.model_id}/manifest.yaml",
        store=store, model_id=model.model_id)
    reg.materialize_model(store, model.model_id, root / "workspace/models/materialized")
    drive, fresh = tmp_path / "drive", tmp_path / "fresh"
    backup.create_backup(store, **backup_args(root, drive))
    root.rename(tmp_path / "unavailable-source")
    backup.restore_backup(drive, **restore_args(fresh))
    if damage in {"missing_base", "changed_base"}:
        weight = Path(model.base_model) / "model.safetensors"
        if damage == "missing_base":
            weight.unlink()
        else:
            weight.write_bytes(b"changed external synthetic dependency")
    elif damage == "changed_media":
        media = next((fresh / "data/releases/data-v4.1-r3/media").glob("*.mp4"))
        media.chmod(0o600)
        media.write_bytes(b"changed managed synthetic media")
    elif damage == "changed_locator":
        locator = fresh / "workspace/mlflow/restore-locations.json"
        data = json.loads(locator.read_bytes())
        data["evaluations"][version]["restored_media_root"] = str(tmp_path / "arbitrary-media")
        locator.chmod(0o600)
        locator.write_text(json.dumps(data))
        locator.chmod(0o400)
    elif damage == "writable_locator":
        (fresh / "workspace/mlflow/restore-locations.json").chmod(0o600)
    else:
        (fresh / "workspace/mlflow/restore-catalog.yaml").chmod(0o444)
    restored_truth = fresh / "data/releases/data-v4.1-r3/sealed_ground_truth/labels.json"
    monkeypatch.setattr(ev, "load_model", lambda *a, **k: pytest.fail("invalid recovery must not infer"))
    with monkeypatch.context() as guard:
        forbid_truth(guard, restored_truth)
        with pytest.raises(ValueError):
            score_holdout_evaluation(root=fresh, eval_version=version, executor="synthetic")
    assert not (restored_truth.parent.parent / "authorization/consumed.yaml").exists()
    assert (restored_truth.parent.parent / "authorization/exposed.yaml").is_file()
