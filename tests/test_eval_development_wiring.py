"""Synthetic formal development wiring: no real model, data or GPU execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finetune import eval_run as runtime
from finetune.eval_semantics import freeze_blind_policy, rules_digest, seal_judgment
from test_eval_run import _formal_eval_fixture, _fake_formal_runtime, _labels


def _config(config):
    return {**config, "scorer": "semantic-v4.1",
            "source_groups": {f"video_{i:04d}": f"specimen-{i}" for i in range(3)},
            "thresholds": {"four_state_macro_recall": .65, "per_state_recall": .50,
                "joint_correct_rate": .50, "fracture_mechanism_macro_f1": .50,
                "fracture_site_macro_f1": .60}}


def _policy():
    actors = [{"id": name, "model": "synthetic-judge", "model_sha256": "a" * 64,
               "prompt_sha256": "b" * 64} for name in ("first", "second", "arbiter")]
    return {"participants": actors[:2], "arbiter": actors[2], "manual_sha256": "c" * 64,
            "rules_sha256": rules_digest(), "aggregation": "unanimous-per-field",
            "retry_policy": {"runtime_failure_retries": 1, "answer_selection": "forbidden"}}


def _prepare(root, media, model, config, identity="eval-v4.1-r1"):
    return runtime.prepare_versioned_evaluation(root=root, eval_version=identity,
        model_version=model.model_id, model_version_number=model.version,
        data_version="data-v4.1-r2", config=config, git_commit="synthetic", media_root=media)


def test_semantic_formal_freezes_all_rows_and_exports_insufficient_support(tmp_path, monkeypatch):
    root, media, model, config = _formal_eval_fixture(tmp_path)
    path = _prepare(root, media, model, _config(config))
    frozen = json.loads(path.read_bytes())
    assert frozen["scoring_protocol"] == "semantic-v4.1"
    assert frozen["metric_definitions"] == runtime.SEMANTIC_METRICS
    assert "separate state gates" in frozen["aggregation"]
    assert set(frozen["majority_baselines"]) == {"fold0", "fold1", "fold2"}
    calls = _fake_formal_runtime(monkeypatch)
    record = runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert len(calls) == 3
    assert record.workflow_state == "completed" and record.outcome == "failed"
    output = root / "workspace/evaluations/eval-v4.1-r1/output"
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["development_gates"]["outcome"] == "insufficient_evidence"
    assert summary["semantic"]["support"]["total"] == 3
    assert summary["majority_baseline"]
    manifest = json.loads(runtime.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1").read_bytes())
    assert manifest["scoring_protocol"] == "semantic-v4.1"
    assert manifest["development_evidence_status"] == "insufficient_evidence"
    assert manifest["sample_count"] == 3
    assert "raw_records.jsonl" in manifest["artifacts"]


@pytest.mark.parametrize("change", [
    {"source_groups": {"video_0000": "shared", "video_0001": "shared", "video_0002": "third"}},
    {"source_groups": {"video_0000": "first"}},
    {"thresholds": {"joint_correct_rate": 0}},
    {"generation": {"do_sample": True}},
    {"scorer": "strict-v4.1"},
])
def test_semantic_policy_rejects_leakage_drift_and_old_scorer(tmp_path, change):
    root, media, model, config = _formal_eval_fixture(tmp_path)
    with pytest.raises(ValueError):
        _prepare(root, media, model, {**_config(config), **change})


def test_semantic_blind_resume_never_reruns_model_and_seals_evidence(tmp_path, monkeypatch):
    from versioning.mlflow_eval import open_eval_store, get_eval_run
    from versioning.registry import open_registry_store, _run_artifact_root
    root, media, model, config = _formal_eval_fixture(tmp_path)
    policy = _policy()
    _prepare(root, media, model, {**_config(config), "blind_policy": policy})
    calls = _fake_formal_runtime(monkeypatch, invalid_output=True)
    with pytest.raises(runtime.EvaluationReviewPending):
        runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert len(calls) == 3
    store = open_eval_store(root / "workspace/mlflow")
    pending = get_eval_run(store, "eval-v4.1-r1")
    assert pending.workflow_state == "running" and pending.outcome is None
    assert all(child.status == "FINISHED" for child in pending.folds.values())
    raw = root / "workspace/evaluations/eval-v4.1-r1/output/raw_records.jsonl"
    raw_bytes = raw.read_bytes()
    raw_digest = hashlib.sha256(b"bad json").hexdigest()
    sealed = freeze_blind_policy(policy)
    evidence = {"policy": policy, "initial": [seal_judgment(actor_id=actor["id"],
        raw_sha256=raw_digest, policy_sha256=sealed["sha256"], fields=_labels("未断裂"), sequence=i + 1)
        for i, actor in enumerate(policy["participants"])], "disclosed_at": 3, "sealed_at": 4,
        "access_scope": "anonymous-raw-and-manual-only"}
    reviews = tmp_path / "reviews.json"
    infrastructure_failure = {**evidence, "initial": [seal_judgment(actor_id="first",
        raw_sha256=raw_digest, policy_sha256=sealed["sha256"], fields={}, sequence=1,
        status="infrastructure_failure", elapsed_seconds=3, cost=2), evidence["initial"][1]]}
    reviews.write_text(json.dumps({raw_digest: infrastructure_failure}, ensure_ascii=False))
    monkeypatch.setattr(runtime, "load_model", lambda *a, **k: pytest.fail("review resume loaded a model"))
    with pytest.raises(runtime.EvaluationReviewPending):
        runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    assert get_eval_run(store, "eval-v4.1-r1").workflow_state == "running"
    assert raw.read_bytes() == raw_bytes
    # Identical sealed import retries are idempotent and consume no new judge attempt.
    with pytest.raises(runtime.EvaluationReviewPending):
        runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    attempt_dir = raw.parent / "review_attempts"
    assert [p.name for p in attempt_dir.iterdir()] == ["0001.json"]
    changed_completed = {**evidence, "initial": [evidence["initial"][0], seal_judgment(actor_id="second",
        raw_sha256=raw_digest, policy_sha256=sealed["sha256"], fields=_labels("临界未断裂"), sequence=2)]}
    reviews.write_text(json.dumps({raw_digest: changed_completed}, ensure_ascii=False))
    with pytest.raises(ValueError, match="completed blind judgment"):
        runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    assert len(list(attempt_dir.iterdir())) == 1
    reviews.write_text(json.dumps({raw_digest: evidence}, ensure_ascii=False))
    manifest = runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    assert raw.read_bytes() == raw_bytes
    assert json.loads(manifest.read_bytes())["outcome"] == "failed"  # unsupported classes remain missing
    summary = json.loads((raw.parent / "summary.json").read_bytes())
    assert summary["blind_import_audit"]["attempt_count"] == 2
    assert summary["blind_import_audit"]["infrastructure_failure_count"] == 1
    assert summary["blind_import_audit"]["cost"] == 2
    assert summary["blind_import_audit"]["elapsed_seconds"] == 3
    completed = get_eval_run(store, "eval-v4.1-r1")
    registry = open_registry_store(store.root, data_root=root / "data")
    artifact = _run_artifact_root(registry, completed.run_id)
    proof = artifact / "blind_reviews.json"
    proof.write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        runtime.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")


def _paired_fixture(tmp_path, monkeypatch):
    from test_train_with_contract import _versioned_data_fixture, _mirror_prompt_checkout
    from test_model_sources import base_files
    from finetune.train_prepare_run import prepare_versioned_run, execute_versioned_run
    from versioning.registry import open_registry_store, register_model, register_base_model
    root, media, _, _ = _versioned_data_fixture(tmp_path)
    _mirror_prompt_checkout(root)
    base = base_files(tmp_path / "paired-base")
    (base / "source-provenance.json").write_text(json.dumps({"schema": "tensile-base-provenance/v1",
        "upstream_source": "org/synthetic", "upstream_revision": "fixed-fixture-revision", "verified_by": "synthetic fixture"}))
    configs = {f"fold{i}": {"model_name_or_path": str(base), "seed": i} for i in range(3)}
    prepare_versioned_run(root=root, train_version="train-v4.1-r1", data_version="data-v4.1-r2",
        prompt_version="prompt-v4.1-r1", media_root=media, fold_configs=configs,
        git_commit="synthetic", environment={"python": "synthetic CPU fixture"})
    def tune(config):
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        (output / "adapter_config.json").write_text("{}")
        (output / "adapter_model.safetensors").write_bytes(b"synthetic adapter")
        (output / "train_results.json").write_text('{"loss":0.1}')
    monkeypatch.setattr("finetune.train_with_contract.run_training", tune)
    execute_versioned_run(root=root, train_version="train-v4.1-r1")
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    trained = register_model(registry, "model-v4.1-r1", train_id="train-v4.1-r1", source_scope="cross_validation", deploy_target=None,
        artifacts={f"fold{i}": {"adapter": f"artifacts/fold{i}/adapter"} for i in range(3)})
    baseline = register_base_model(registry, "model-v4.1-r2", model_path=base,
        upstream_source="org/synthetic", upstream_revision="fixed-fixture-revision", git_commit="synthetic")
    config = _config({"scope": "cross_validation", "split": "validation", "artifact_kind": "adapter",
        "scorer": "semantic-v4.1", "sample_selection": "all", "quantization_bit": None,
        "aggregation": "pooled", "generation": runtime.FORMAL_GENERATION})
    return root, media, trained, baseline, config


def test_registered_base_paired_formal_cli_revalidates_both_runs(tmp_path, monkeypatch, capsys):
    from versioning.cli import main
    root, media, trained, base, config = _paired_fixture(tmp_path, monkeypatch)
    _prepare(root, media, base, {**config, "artifact_kind": "model", "prompt_version": "prompt-v4.1-r1"}, "eval-v4.1-r1")
    _prepare(root, media, trained, config, "eval-v4.1-r2")
    calls = _fake_formal_runtime(monkeypatch)
    runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r2")
    assert len(calls) == 6
    monkeypatch.setattr(runtime, "load_model", lambda *a, **k: pytest.fail("compare loaded weights"))
    assert main(["eval", "compare", "eval-v4.1-r2", "--root", str(root),
                 "--baseline-eval-version", "eval-v4.1-r1"]) == 0
    result = root / "records/evaluations/eval-v4.1-r2/paired/eval-v4.1-r1.json"
    report = json.loads(result.read_bytes())
    assert report["comparison"]["relative_improvement_is_gate"] is False
    assert report["comparison"]["measurement_complete"] is True
    assert report["comparison"]["sample_count"] == 3


def test_completed_real_fold_is_evaluated_without_parent_promotion(tmp_path, monkeypatch):
    from test_model_sources import diagnostic_model
    # Invoke the existing synthetic fixture body explicitly; no hardware runtime.
    store, model, parent, root = diagnostic_model.__wrapped__(tmp_path, monkeypatch)
    media = tmp_path / "original/workspace/data"
    config = _config({"scope": "single_fold", "split": "validation", "artifact_kind": "adapter",
        "scorer": "semantic-v4.1", "sample_selection": "all", "quantization_bit": None,
        "aggregation": "pooled", "generation": runtime.FORMAL_GENERATION})
    frozen = json.loads(_prepare(root, media, model, config).read_bytes())
    assert frozen["folds"] == [2]
    calls = _fake_formal_runtime(monkeypatch)
    result = runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert len(calls) == 1 and set(result.folds) == {2} and result.outcome == "failed"
    from versioning.mlflow_train import open_train_store, get_train_run
    assert get_train_run(open_train_store(store.root), parent.train_id).workflow_state == "partial"


def _rich_data_fixture(tmp_path):
    import yaml
    from versioning.data_release import seal_payload
    from versioning.migration import _release_content_digest
    from versioning.prompts import create_prompt
    root, media = tmp_path / "store", tmp_path / "original/workspace/data"
    release = root / "data/releases/data-v4.1-r2"
    mechanisms = ["韧性断裂", "脆性断裂", "界面脱粘", "爆炸性断裂", "半脆半韧断裂"]
    sites = ["inside_gauge", "outside_gauge_non_root", "grip_root"]
    templates = [_labels("未断裂"), _labels("临界未断裂"),
        *[_labels("发生断裂", mechanism, sites[i % 3]) for i, mechanism in enumerate(mechanisms)],
        _labels("已断裂", mechanisms[0], sites[0]),
        {**_labels("无法判断"), "special_case": "未夹紧"},
        {**_labels("无法判断"), "special_case": "视频异常"}]
    rows = []
    for fold in range(3):
        for i, target in enumerate(templates):
            candidate = f"video_{fold * 100 + i:04d}"
            path = media / "derived/subvideos" / f"{candidate}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic independent media")
            rows.append({"videos": [f"data/03_subvideos/{candidate}.mp4"], "messages": [
                {"role": "system", "content": "old system"}, {"role": "user", "content": "<video>\nold user"},
                {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)}]})
    n = len(templates)
    for fold in range(3):
        for split in ("train", "validation"):
            path = release / f"datasets/{split}/fold_{fold}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps([row for i, row in enumerate(rows) if (i // n == fold) == (split == "validation")], ensure_ascii=False))
    (release / "release.yaml").write_text(yaml.safe_dump({"version": "data-v4.1-r2", "protocol": "tensile-vlm/v4.1",
        "state": "sealed", "purpose": "development", "training_allowed": True, "status": "active",
        "description": "synthetic supported classes", "sample_count": len(rows), "source_batches": ["fixture"],
        "splits": {f"fold_{i}": {"train": n * 2, "validation": n} for i in range(3)}}))
    seal_payload(release)
    receipt = root / "migration_receipts/data-v4.1-r2.receipt.yaml"
    receipt.parent.mkdir()
    receipt.write_text(yaml.safe_dump({"target_identity": "data-v4.1-r2", "target_path": "data/releases/data-v4.1-r2/release.yaml",
        "status": "committed", "target_release_digest": _release_content_digest(release)}))
    create_prompt(root, "v4.1", version="prompt-v4.1-r1", system_prompt="frozen system", user_prompt="frozen user", output_fields=list(_labels("未断裂")))
    return root, media, release, rows


@pytest.mark.parametrize("collapse", [False, True])
def test_complete_semantic_formal_pass_and_collapsed_fold_gate(tmp_path, monkeypatch, collapse):
    from types import SimpleNamespace
    from versioning.registry import open_registry_store, _run_eval_gate, PromotionGateRejected
    monkeypatch.setattr("test_train_with_contract._versioned_data_fixture", _rich_data_fixture)
    root, media, model, _, config = _paired_fixture(tmp_path, monkeypatch)
    groups = {path.stem: path.stem for path in (media / "derived/subvideos").iterdir()}
    _prepare(root, media, model, {**config, "source_groups": groups})
    frozen = runtime.verify_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    targets = {s["candidate_id"]: s["target"] for rows in frozen["samples"].values() for s in rows}
    _fake_formal_runtime(monkeypatch)
    def infer(model, processor, video_path, prompt, **kwargs):
        candidate = Path(video_path).stem
        target = _labels("未断裂") if collapse and int(candidate.removeprefix("video_")) < 100 else targets[candidate]
        return SimpleNamespace(raw_output=json.dumps(target, ensure_ascii=False), sampled_timestamps=[0.0],
            generated_token_count=10, hit_token_limit=False)
    monkeypatch.setattr(runtime, "run_model_on_video_detailed", infer)
    record = runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert record.outcome == ("failed" if collapse else "passed")
    summary = json.loads((root / "workspace/evaluations/eval-v4.1-r1/output/summary.json").read_bytes())
    assert all(v for k, v in summary["development_gates"]["gates"].items() if k.startswith("pooled_"))
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    # Development can report passed while remaining ineligible as final quality.
    with pytest.raises(PromotionGateRejected):
        _run_eval_gate(registry, record.eval_id, require_passed=True)
    assert runtime.export_versioned_evaluation(root=root, eval_version=record.eval_id).is_file()


def _archived_module(path):
    import subprocess
    import types
    source = subprocess.check_output(["git", "show", f"512cc8b4:{path}"], cwd=runtime.ROOT)
    module = types.ModuleType("historical_" + Path(path).stem)
    module.__file__ = str(runtime.ROOT / path)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module, source


def _archived_runtime(monkeypatch):
    legacy, source = _archived_module("finetune/eval_run.py")
    legacy_holdout, holdout_source = _archived_module("finetune/eval_holdout.py")
    original_sha = legacy._sha256
    archived = {"finetune/eval_run.py": hashlib.sha256(source).hexdigest(),
                "finetune/eval_holdout.py": hashlib.sha256(holdout_source).hexdigest()}
    def historical_sha(path):
        relative = str(Path(path).relative_to(runtime.ROOT)) if Path(path).is_relative_to(runtime.ROOT) else None
        return archived[relative] if relative in archived else original_sha(path)
    legacy._sha256 = historical_sha
    legacy_holdout.ev = legacy
    import sys
    monkeypatch.setitem(sys.modules, "finetune.eval_holdout", legacy_holdout)
    return legacy, legacy_holdout, archived


def test_actual_archived_strict_record_preserves_export_and_existing_alias(tmp_path, monkeypatch):
    from mlflow.tracking import MlflowClient
    from versioning.registry import (open_registry_store, finalize_model_evaluation,
        set_alias, get_model_by_alias, get_model, PromotionGateRejected, REGISTERED_MODEL_NAME)
    root, media, model, config = _formal_eval_fixture(tmp_path, scope="single_fold")
    legacy, _, archived = _archived_runtime(monkeypatch)
    calls = _fake_formal_runtime(monkeypatch)
    legacy.load_model = runtime.load_model
    legacy.run_model_on_video_detailed = runtime.run_model_on_video_detailed
    _prepare_legacy = dict(root=root, eval_version="eval-v4.1-r1", model_version=model.model_id,
        model_version_number=model.version, data_version="data-v4.1-r2", config=config, git_commit="synthetic", media_root=media)
    legacy.prepare_versioned_evaluation(**_prepare_legacy)
    result = legacy.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert len(calls) == 1 and result.outcome == "passed"
    frozen = runtime.verify_versioned_evaluation(root=root, eval_version=result.eval_id)
    assert frozen["implementation_sha256"]["finetune/eval_run.py"] == archived["finetune/eval_run.py"]
    runtime.export_versioned_evaluation(root=root, eval_version=result.eval_id)
    runtime.prepare_versioned_evaluation(**_prepare_legacy)  # idempotent historical prepare
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    with pytest.raises(PromotionGateRejected, match="new admission"):
        finalize_model_evaluation(registry, model.model_id, eval_id=result.eval_id)
    assert get_model(registry, model.model_id).eval_id is None
    # Reconstruct only the registry state that could already exist with this
    # archived implementation. New strict promotion is deliberately prohibited.
    client = MlflowClient(tracking_uri=registry.tracking_uri)
    for name, value in {"eval_id": result.eval_id, "offline_backup_scope": "adapter"}.items():
        client.set_model_version_tag(REGISTERED_MODEL_NAME, str(model.version), name, value)
    client.set_registered_model_alias(REGISTERED_MODEL_NAME, "candidate", str(model.version))
    assert get_model_by_alias(registry, "candidate").eval_id == result.eval_id
    assert finalize_model_evaluation(registry, model.model_id, eval_id=result.eval_id).eval_id == result.eval_id
    assert set_alias(registry, model.model_id, "candidate").eval_id == result.eval_id
    # A future adapter edit is an actual byte change, and is not implicitly trusted.
    modified = tmp_path / "unreviewed.py"
    modified.write_bytes((runtime.ROOT / "finetune/eval_run.py").read_bytes() + b"\n# unreviewed adapter bytes\n")
    original_sha = runtime._sha256
    monkeypatch.setattr(runtime, "_sha256", lambda p: original_sha(modified) if Path(p) == runtime.ROOT / "finetune/eval_run.py" else original_sha(p))
    with pytest.raises(ValueError, match="drift|implementation"):
        runtime.verify_versioned_evaluation(root=root, eval_version=result.eval_id)
    with pytest.raises(ValueError, match="implementation"):
        runtime.export_versioned_evaluation(root=root, eval_version=result.eval_id)
    assert not runtime._implementation_matches(frozen, "finetune/eval_run.py", "f" * 64)


def test_actual_archived_holdout_uses_its_original_seven_gates(tmp_path, monkeypatch):
    from test_eval_holdout import prepare_holdout, forbid_truth
    root, registry, truth, kwargs = prepare_holdout(tmp_path, monkeypatch, prepare=False)
    legacy, old_holdout, archived = _archived_runtime(monkeypatch)
    legacy.load_model = runtime.load_model
    legacy.run_model_on_video_detailed = runtime.run_model_on_video_detailed
    legacy.prepare_versioned_evaluation(**kwargs)
    legacy.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    old_holdout.score_holdout_evaluation(root=root, eval_version="eval-v4.1-r1", executor="synthetic")
    # Restore the actual current holdout validator before the current runtime
    # verifies and exports: verify resolves build_holdout_input through
    # sys.modules and must not receive the archived signature.
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("current_holdout", runtime.ROOT / "finetune/eval_holdout.py")
    current_holdout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(current_holdout)
    monkeypatch.setitem(sys.modules, "finetune.eval_holdout", current_holdout)
    frozen = runtime.verify_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert frozen["implementation_sha256"]["finetune/eval_holdout.py"] == archived["finetune/eval_holdout.py"]
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        manifest = runtime.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert json.loads(manifest.read_bytes())["outcome"] == "passed"


def test_blind_attempt_budget_and_attempt_drift_are_formally_enforced(tmp_path, monkeypatch):
    from versioning.mlflow_eval import open_eval_store, get_eval_run
    from versioning.registry import open_registry_store, _run_artifact_root
    root, media, model, config = _formal_eval_fixture(tmp_path)
    policy = _policy()
    _prepare(root, media, model, {**_config(config), "blind_policy": policy})
    _fake_formal_runtime(monkeypatch, invalid_output=True)
    with pytest.raises(runtime.EvaluationReviewPending):
        runtime.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    raw_digest = hashlib.sha256(b"bad json").hexdigest()
    policy_digest = freeze_blind_policy(policy)["sha256"]
    def evidence(status, duration):
        return {"policy": policy, "initial": [seal_judgment(actor_id="first", raw_sha256=raw_digest,
            policy_sha256=policy_digest, fields={} if status == "infrastructure_failure" else _labels("未断裂"),
            sequence=1, status=status, elapsed_seconds=duration),
            seal_judgment(actor_id="second", raw_sha256=raw_digest, policy_sha256=policy_digest,
                fields=_labels("未断裂"), sequence=2)], "disclosed_at": 3, "sealed_at": 4,
            "access_scope": "anonymous-raw-and-manual-only"}
    reviews = tmp_path / "budget-reviews.json"
    for duration in (1, 2):
        reviews.write_text(json.dumps({raw_digest: evidence("infrastructure_failure", duration)}, ensure_ascii=False))
        with pytest.raises(runtime.EvaluationReviewPending):
            runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    reviews.write_text(json.dumps({raw_digest: evidence("completed", 3)}, ensure_ascii=False))
    with pytest.raises(ValueError, match="at most one retry"):
        runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    output = root / "workspace/evaluations/eval-v4.1-r1/output"
    assert len(list((output / "review_attempts").iterdir())) == 2
    store = open_eval_store(root / "workspace/mlflow")
    record = get_eval_run(store, "eval-v4.1-r1")
    assert record.workflow_state == "running" and record.outcome is None
    registry = open_registry_store(store.root, data_root=root / "data")
    artifact = _run_artifact_root(registry, record.run_id) / "review_attempts/0001.json"
    original = artifact.read_bytes()
    artifact.chmod(0o644)
    artifact.write_text("{}")
    with pytest.raises(ValueError, match="attempt digest"):
        runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
    artifact.write_bytes(original)
    # Local evidence drift is also rejected before any further review can be adopted.
    local = output / "review_attempts/0001.json"
    local.chmod(0o644)
    local.write_text("{}")
    with pytest.raises(ValueError, match="attempt digest"):
        runtime.resume_versioned_evaluation(root=root, eval_version="eval-v4.1-r1", blind_reviews=reviews)
