import base64

import pytest

from pipeline.production_contract import load_production_contract, production_contract_hash
from pipeline.scripts.serve_smoke import (
    build_analysis_payload,
    validate_analysis_response,
    validate_preflight,
)


def test_build_analysis_payload_uses_canonical_prompts_and_one_mp4():
    contract = load_production_contract()
    payload = build_analysis_payload(b"video-bytes", contract)

    assert payload["stream"] is False
    assert len(payload["messages"]) == 2
    assert payload["messages"][0] == {
        "role": "system",
        "content": contract["analysis"]["system_prompt"],
    }
    content = payload["messages"][1]["content"]
    assert content[1] == {"type": "text", "text": contract["analysis"]["user_prompt"]}
    encoded = content[0]["video_url"]["url"].removeprefix("data:video/mp4;base64,")
    assert base64.b64decode(encoded) == b"video-bytes"


def test_build_analysis_payload_rejects_empty_video():
    with pytest.raises(ValueError, match="must not be empty"):
        build_analysis_payload(b"", load_production_contract())


def test_validate_preflight_requires_local_contract_identity():
    contract = load_production_contract()
    valid = {
        "contract_version": contract["contract_version"],
        "contract_hash": production_contract_hash(),
        "deployment_manifest": {
            "contract_version": contract["contract_version"],
            "contract_hash": production_contract_hash(),
        },
    }
    validate_preflight(valid)

    valid["contract_hash"] = "drift"
    with pytest.raises(RuntimeError, match="contract_hash"):
        validate_preflight(valid)


def test_validate_analysis_response_requires_evidence_and_identity():
    response = {
        "choices": [{"message": {"content": "{}"}}],
        "preprocessing": {
            "frames": [{"index": 0, "timestamp": 0.0}],
            "deployment_manifest": {"contract_hash": production_contract_hash()},
        },
    }
    validate_analysis_response(response)

    response["preprocessing"]["frames"] = []
    with pytest.raises(RuntimeError, match="frame table"):
        validate_analysis_response(response)


# M5 Test List: public startup must resolve a qualified alias/current before
# model loading; no raw path, invalid model, cache drift or mode bypass;
# management/delivery/smoke use the same binding; no actual GPU in these tests.
def _service_fixture(tmp_path, artifact_kind="adapter"):
    from pathlib import Path
    from mlflow.tracking import MlflowClient
    from versioning.data_release import stage_release, seal_release
    from versioning.prompts import create_prompt
    from versioning.mlflow_train import (open_train_store, create_train_run, create_fold_run,
        end_fold_run, log_train_summary, transition_train_state)
    from versioning.mlflow_eval import (open_eval_store, create_eval_run, create_eval_fold_run,
        end_eval_fold_run, log_eval_summary, transition_eval_state)
    from versioning.registry import (open_registry_store, register_model, finalize_model_evaluation,
        set_offline_backup_scope, set_alias)
    from versioning.manifest import export_model_manifest
    from versioning.materialize import materialize_current
    from pipeline.v4_1_production_contract import load_v4_1_production_contract
    root = tmp_path / "store"
    data = root / "data"
    work = data / "working/batch"
    work.mkdir(parents=True)
    (work / "media.txt").write_text("CPU fixture")
    stage_release(data, "batch", "v4.1", version="data-v4.1-r1")
    seal_release(data, "data-v4.1-r1", purpose="development", description="fixture",
        sample_count=1, source_batches=["batch"], splits={"fold0": {"train": 1, "validation": 1}})
    contract = load_v4_1_production_contract()
    create_prompt(root, "v4.1", version="prompt-v4.1-r1", system_prompt=contract["analysis"]["system_prompt"],
        user_prompt=contract["analysis"]["user_prompt"], output_fields=contract["model_output_fields"])
    base = tmp_path / "base_model"
    base.mkdir()
    (base / "model.safetensors").write_bytes(b"base fixture")
    train = open_train_store(root / "workspace/mlflow")
    parent = create_train_run(train, "train-v4.1-r1", data_version="data-v4.1-r1",
        prompt_version="prompt-v4.1-r1", git_commit="fixture", base_model=str(base), config={"fixture": True})
    for i in range(3):
        create_fold_run(train, "train-v4.1-r1", i)
        end_fold_run(train, "train-v4.1-r1", i, "FINISHED", metrics={"loss": .2})
    log_train_summary(train, "train-v4.1-r1", {"loss": .2})
    transition_train_state(train, "train-v4.1-r1", "completed")
    adapter = tmp_path / artifact_kind
    adapter.mkdir()
    (adapter / ("adapter_model.safetensors" if artifact_kind == "adapter" else "model.safetensors")).write_bytes(b"weights fixture")
    MlflowClient(tracking_uri=train.tracking_uri).log_artifacts(parent.run_id, str(adapter), f"fold0/{artifact_kind}")
    registry = open_registry_store(train.root, data_root=data)
    model = register_model(registry, "model-v4.1-r1", train_id="train-v4.1-r1",
        artifacts={"fold0": {artifact_kind: f"artifacts/fold0/{artifact_kind}"}},
        deploy_target=f"artifacts/fold0/{artifact_kind}")
    evaluations = open_eval_store(train.root)
    create_eval_run(evaluations, "eval-v4.1-r1", model_id=model.model_id, model_version_number=model.version,
        data_version="data-v4.1-r1", config="synthetic fixture", git_commit="fixture",
        scope="single_fold", split="validation", data_root=data)
    create_eval_fold_run(evaluations, "eval-v4.1-r1", 0, model_artifact=f"fold0/{artifact_kind}",
        data_split="validation/fold0", sample_count=1, records="fixture", failures="fixture")
    end_eval_fold_run(evaluations, "eval-v4.1-r1", 0, "FINISHED", metrics={"score": 1.})
    log_eval_summary(evaluations, "eval-v4.1-r1", {"score": 1.})
    transition_eval_state(evaluations, "eval-v4.1-r1", "completed", outcome="passed")
    finalize_model_evaluation(registry, model.model_id, eval_id="eval-v4.1-r1")
    set_offline_backup_scope(registry, model.model_id, "adapter" if artifact_kind == "adapter" else "production_bundle")
    export_model_manifest(root / "records/models" / model.model_id / "manifest.yaml", store=registry, model_id=model.model_id)
    set_alias(registry, model.model_id, "candidate")
    materialize_current(registry, alias="candidate", service_mode="development",
        models_root=root / "workspace/models", records_root=root)
    return root, registry, model


def test_service_resolver_rejects_missing_alias_and_invalid_mode(tmp_path):
    from pipeline.model_registry import resolve_service_model
    with pytest.raises(ValueError):
        resolve_service_model(tmp_path, alias="candidate", service_mode="production")
    with pytest.raises(ValueError):
        resolve_service_model(tmp_path, alias="candidate", service_mode="development")


def test_service_resolver_returns_only_qualified_exact_paths(tmp_path):
    from pathlib import Path
    from pipeline.model_registry import resolve_service_model
    root, registry, model = _service_fixture(tmp_path)
    selected = resolve_service_model(root, alias="candidate", service_mode="development")
    assert selected["model_version"] == model.model_id
    assert selected["model_version_number"] == model.version
    assert Path(selected["model_path"]) == Path(model.base_model)
    assert Path(selected["adapter_path"]).name == "adapter"
    assert len(selected["fingerprint"]) == 64


def test_service_resolver_rejects_modified_materialized_bytes(tmp_path):
    from pipeline.model_registry import resolve_service_model
    root, registry, model = _service_fixture(tmp_path)
    cache = root / "workspace/models/materialized" / model.model_id / "artifacts/fold0/adapter/adapter_model.safetensors"
    cache.write_bytes(b"wrong cached weights")
    with pytest.raises(ValueError, match="content|artifact"):
        resolve_service_model(root, alias="candidate", service_mode="development")


def test_service_main_no_alias_stops_before_engine_import(tmp_path, monkeypatch):
    import sys, json
    from pipeline import server_proxy
    config = tmp_path / "startup.json"
    config.write_text(json.dumps({}))
    monkeypatch.setattr(sys, "argv", ["server_proxy", "--root", str(tmp_path), "--alias", "candidate",
        "--service-mode", "development", "--contract-version", "tensile-vlm/v4.1", "--deployment-manifest", str(config)])
    with pytest.raises(ValueError):
        server_proxy.main()


def test_service_main_rejects_raw_model_path(monkeypatch):
    import sys
    from pipeline import server_proxy
    monkeypatch.setattr(sys, "argv", ["server_proxy", "--model", "/raw/model", "--deployment-manifest", "old.json"])
    with pytest.raises(SystemExit) as caught:
        server_proxy.main()
    assert caught.value.code == 2


@pytest.mark.parametrize("drift_during_load", [False, True])
def test_service_main_loads_only_resolved_model(tmp_path, monkeypatch, drift_during_load):
    import json, sys, types
    from pipeline.model_registry import resolve_service_model
    from pipeline import server_proxy
    root, registry, model = _service_fixture(tmp_path)
    binding = resolve_service_model(root, alias="candidate", service_mode="development")
    config = {"max_frames": 8, "model_version": model.model_id, "adapter_version": model.model_id,
        "base_model_version": model.base_model, "processor_version": "fixture processor",
        "llamafactory_version": "fixture", "transformers_version": "fixture",
        "config_fingerprint": binding["fingerprint"], "runtime_device": "fixture", "runtime_dtype": "fixture"}
    path = tmp_path / "startup.json"
    path.write_text(json.dumps(config))
    calls = []
    chat = types.ModuleType("llamafactory.chat")
    def load(args):
        calls.append(args)
        if drift_during_load:
            from pathlib import Path
            (Path(binding["model_path"]) / "model.safetensors").write_bytes(b"changed during load")
        return object()
    chat.ChatModel = load
    uvicorn = types.ModuleType("uvicorn")
    uvicorn.run = lambda app, **kwargs: calls.append("serve")
    monkeypatch.setitem(sys.modules, "llamafactory.chat", chat)
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
    monkeypatch.setattr(server_proxy, "create_integrated_app", lambda model, config, **kwargs: object())
    monkeypatch.setattr(sys, "argv", ["server_proxy", "--root", str(root), "--alias", "candidate",
        "--service-mode", "development", "--contract-version", "tensile-vlm/v4.1", "--deployment-manifest", str(path)])
    if drift_during_load:
        with pytest.raises(ValueError, match="changed while loading"):
            server_proxy.main()
        assert len(calls) == 1
        return
    assert server_proxy.main() == 0
    assert calls[0]["model_name_or_path"] == binding["model_path"]
    assert calls[0]["adapter_name_or_path"] == binding["adapter_path"]
    assert calls[1] == "serve"


def test_public_delivery_no_longer_accepts_legacy_development_exception(tmp_path):
    import scripts.serve_validate_delivery as delivery
    with pytest.raises(ValueError):
        delivery.validate_components(tmp_path)


def test_public_delivery_and_management_share_registry_gate(tmp_path, monkeypatch, capsys):
    import sys, json
    import scripts.serve_validate_delivery as delivery
    import scripts.serve_manage_model_registry as management
    root, registry, model = _service_fixture(tmp_path)
    report = delivery.validate_components(root, alias="candidate", service_mode="development")
    assert report["passed"] is True
    assert report["runtime_verified"] is False
    assert report["model_version"] == model.model_id
    monkeypatch.setattr(sys, "argv", ["registry", "--root", str(root), "resolve-current", "--alias", "candidate", "--service-mode", "development"])
    assert management.main() == 0
    assert json.loads(capsys.readouterr().out)["model_version"] == model.model_id


def test_smoke_rejects_service_binding_drift():
    from pipeline.scripts.serve_smoke import validate_service_binding
    binding = {"model_version": "model-v4.1-r1", "model_version_number": 1,
               "fingerprint": "a" * 64, "model_path": "/base", "adapter_path": "/adapter",
               "base_model_version": "/base"}
    public = {k: v for k, v in binding.items()
              if k not in {"model_path", "adapter_path", "base_model_version"}}
    payload = {"model_registry": public, "deployment_manifest": {
        "model_version": binding["model_version"], "config_fingerprint": binding["fingerprint"]}}
    validate_service_binding(payload, binding)
    payload["model_registry"] = {**public, "model_version_number": 2}
    with pytest.raises(RuntimeError, match="Registry"):
        validate_service_binding(payload, binding)


def test_smoke_requires_explicit_route_before_http(monkeypatch):
    import sys
    from pipeline.scripts import serve_smoke
    monkeypatch.setattr(sys, "argv", ["smoke", "--video", "/missing.mp4"])
    with pytest.raises(SystemExit) as caught:
        serve_smoke.main()
    assert caught.value.code == 2


@pytest.mark.parametrize("fault", ["invalid", "wrong_current", "cache", "production", "backend"])
def test_service_main_rejects_before_loader(tmp_path, monkeypatch, fault):
    import sys, types
    from pipeline import server_proxy
    from versioning.registry import mark_model_invalid
    root, registry, model = _service_fixture(tmp_path)
    if fault == "invalid":
        mark_model_invalid(registry, model.model_id)
    elif fault == "wrong_current":
        (root / "workspace/models/current").unlink()
    elif fault == "cache":
        (root / "workspace/models/materialized" / model.model_id /
         "artifacts/fold0/adapter/adapter_model.safetensors").write_bytes(b"wrong")
    elif fault == "backend":
        (root / "workspace/mlflow/mlflow.db").write_bytes(b"corrupt database")
    calls = []
    chat = types.ModuleType("llamafactory.chat")
    chat.ChatModel = lambda args: calls.append(args)
    monkeypatch.setitem(sys.modules, "llamafactory.chat", chat)
    monkeypatch.setattr(sys, "argv", ["server_proxy", "--root", str(root), "--alias", "candidate",
        "--service-mode", "production" if fault == "production" else "development",
        "--contract-version", "tensile-vlm/v4.1", "--deployment-manifest", str(tmp_path / "absent.json")])
    with pytest.raises(Exception) as caught:
        server_proxy.main()
    assert not isinstance(caught.value, FileNotFoundError), "must reject before reading startup metadata"
    assert calls == []


def test_service_resolver_merged_uses_deploy_target_without_adapter(tmp_path):
    from pathlib import Path
    from pipeline.model_registry import resolve_service_model
    root, registry, model = _service_fixture(tmp_path, artifact_kind="merged")
    binding = resolve_service_model(root, alias="candidate", service_mode="development")
    assert binding["adapter_path"] is None
    assert Path(binding["model_path"]) == root / "workspace/models/materialized" / model.model_id / "artifacts/fold0/merged"
