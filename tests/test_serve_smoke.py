import base64

import pytest

from pipeline.production_contract import load_production_contract, production_contract_hash
from pipeline.scripts.serve_smoke import (
    build_analysis_payload,
    validate_analysis_response,
    validate_preflight,
)


def _historical_eval_binding(registry, model_id, eval_id):
    """按 pre-migration 状态装入 eval 绑定，不调用新严格准入 API。

    本文件测的是服务解析 / 预检 / 冒烟，eval ↔ 模型的绑定只是被携带的既有状态；
    新准入门禁本身由 tests/versioning/test_registry.py 与
    tests/versioning/test_eval_admission_restore.py 覆盖。装入前用真实读回
    （get_eval_run / get_model）核对一致，不一致直接 fail。
    """
    from mlflow.tracking import MlflowClient
    from versioning.mlflow_eval import get_eval_run, open_eval_store
    from versioning.registry import EVAL_ID_TAG, REGISTERED_MODEL_NAME, get_model

    model = get_model(registry, model_id)
    eval_record = get_eval_run(open_eval_store(registry.root), eval_id)
    assert eval_record.model_id == model_id, (
        f"eval {eval_id} 的 model_id {eval_record.model_id!r} 与 {model_id!r} 不一致"
    )
    assert eval_record.model_version_number == model.version, (
        f"eval {eval_id} 引用的数值版本 {eval_record.model_version_number} "
        f"与 model {model_id} 的实际版本 {model.version} 不一致"
    )
    assert eval_record.outcome == "passed", (
        f"eval {eval_id} 的 outcome 为 {eval_record.outcome!r}，服务世界只装入已通过记录"
    )
    MlflowClient(tracking_uri=registry.tracking_uri).set_model_version_tag(
        REGISTERED_MODEL_NAME, str(model.version), EVAL_ID_TAG, eval_id
    )
    bound = get_model(registry, model_id)
    assert bound.eval_id == eval_id, (
        f"model {model_id} 读回 eval_id 为 {bound.eval_id!r}，期望 {eval_id!r}"
    )


def _historical_alias(registry, model_id, alias):
    """按 pre-migration 状态装入既有 alias（set_alias 会走新准入并被历史记录拒绝）。"""
    from mlflow.tracking import MlflowClient
    from versioning.registry import (
        REGISTERED_MODEL_NAME,
        get_model,
        get_model_by_alias,
    )

    model = get_model(registry, model_id)
    MlflowClient(tracking_uri=registry.tracking_uri).set_registered_model_alias(
        REGISTERED_MODEL_NAME, alias, str(model.version)
    )
    assert get_model_by_alias(registry, alias).model_id == model_id, (
        f"alias {alias!r} 读回未指向 {model_id!r}"
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
def _service_fixture(tmp_path, artifact_kind="adapter", *, prompt_definition=None):
    from test_eval_run import _formal_eval_fixture, _fake_formal_runtime
    from finetune import eval_run
    from versioning.registry import open_registry_store, set_offline_backup_scope
    from versioning.manifest import export_model_manifest
    from versioning.materialize import materialize_current
    root, media, model, config = _formal_eval_fixture(tmp_path, scope="single_fold", kind=artifact_kind, service_contract=True, prompt_definition=prompt_definition)
    eval_run.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
        model_version=model.model_id, model_version_number=model.version, data_version="data-v4.1-r2",
        config=config, git_commit="fixture", media_root=media)
    with pytest.MonkeyPatch.context() as patch:
        _fake_formal_runtime(patch, service_contract=True, prompt_definition=prompt_definition)
        eval_run.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    _historical_eval_binding(registry, model.model_id, "eval-v4.1-r1")
    set_offline_backup_scope(registry, model.model_id, "adapter" if artifact_kind == "adapter" else "production_bundle")
    export_model_manifest(root / "records/models" / model.model_id / "manifest.yaml", store=registry, model_id=model.model_id)
    _historical_alias(registry, model.model_id, "candidate")
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
        with pytest.raises(ValueError, match="changed while loading|evaluated weights drifted|training base model drifted"):
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
    assert Path(binding["model_path"]) == root / "workspace/models/materialized" / model.model_id / model.deploy_target


# M8-R5: actual training/eval evidence gates; only trainer/inference are CPU substitutes.
def _migrated_prompt():
    import yaml
    from pathlib import Path
    return yaml.safe_load((Path(__file__).resolve().parents[1] / "records/prompts/prompt-v4.1-r1.yaml").read_text())


def test_service_concise_frozen_prompt_contract_and_retry(tmp_path):
    from copy import deepcopy
    from pipeline.model_registry import resolve_service_model, bind_service_contract
    from pipeline.v4_1_production_contract import load_v4_1_production_contract
    from pipeline.server_proxy import _request_mode, _fixed_payload, _deployment_snapshot, STARTUP_FIELDS
    from pipeline.scripts.serve_smoke import build_analysis_payload, validate_preflight
    definition = _migrated_prompt()
    root, _, _ = _service_fixture(tmp_path, prompt_definition=definition)
    binding = resolve_service_model(root, alias="candidate", service_mode="development")
    assert binding["prompt"] == definition
    assert len(binding["prompt_sha256"]) == 64
    fixed = load_v4_1_production_contract()
    before = deepcopy(fixed)
    contract = bind_service_contract(fixed, binding)
    assert fixed == before
    assert contract["contract_hash"] != fixed["contract_hash"]
    payload = build_analysis_payload(b"fixture mp4", contract)
    assert _request_mode(payload, contract) == "analysis"
    with pytest.raises(ValueError, match="prompts"):
        _request_mode(build_analysis_payload(b"fixture mp4", fixed), contract)
    retry = _fixed_payload(payload, "analysis", contract, "/fixture.mp4", previous_output="invalid")
    assert retry["messages"][0]["content"] == definition["system_prompt"]
    assert retry["messages"][1]["content"][1]["text"] == definition["user_prompt"]
    assert retry["messages"][-1]["content"] == fixed["analysis"]["retry_prompt"]
    assert contract["evidence"] == fixed["evidence"]
    config = {k: "fixture" for k in STARTUP_FIELDS}
    deployment = _deployment_snapshot(config, contract)
    validate_preflight({"contract_version": contract["contract_version"], "contract_hash": contract["contract_hash"], "deployment_manifest": deployment}, contract)
    changed = deepcopy(binding)
    changed["prompt"]["output_fields"] = ["unexpected"]
    with pytest.raises(ValueError):
        bind_service_contract(fixed, changed)


@pytest.mark.parametrize("when", ["before_resolve", "during_load"])
def test_concise_service_rejects_same_id_prompt_drift(tmp_path, monkeypatch, when):
    import json, sys, types, yaml
    from pipeline import server_proxy
    from pipeline.model_registry import resolve_service_model
    from pipeline.v4_1_production_contract import load_v4_1_production_contract
    definition = _migrated_prompt()
    root, _, model = _service_fixture(tmp_path, prompt_definition=definition)
    binding = resolve_service_model(root, alias="candidate", service_mode="development")
    fixed = load_v4_1_production_contract()
    def drift():
        changed = {**definition, **{k: fixed["analysis"][k] for k in ("system_prompt", "user_prompt")}}
        (root / "records/prompts/prompt-v4.1-r1.yaml").write_text(yaml.safe_dump(changed, allow_unicode=True))
    if when == "before_resolve":
        drift()
        with pytest.raises(ValueError, match="[Pp]rompt"):
            resolve_service_model(root, alias="candidate", service_mode="development")
        return
    config = {"max_frames": 8, "model_version": model.model_id, "adapter_version": model.model_id,
        "base_model_version": model.base_model, "processor_version": "fixture", "llamafactory_version": "fixture",
        "transformers_version": "fixture", "config_fingerprint": binding["fingerprint"], "runtime_device": "fixture", "runtime_dtype": "fixture"}
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(config))
    calls = []
    def load(args):
        calls.append("load")
        drift()
        return object()
    monkeypatch.setitem(sys.modules, "llamafactory.chat", types.SimpleNamespace(ChatModel=load))
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: calls.append("serve")))
    monkeypatch.setattr(sys, "argv", ["service", "--root", str(root), "--alias", "candidate", "--service-mode", "development", "--contract-version", "tensile-vlm/v4.1", "--deployment-manifest", str(path)])
    with pytest.raises(ValueError, match="[Pp]rompt"):
        server_proxy.main()
    assert calls == ["load"]


def test_concise_service_main_http_and_smoke_use_frozen_prompt(tmp_path, monkeypatch, capsys):
    import json, sys, types
    from fastapi.testclient import TestClient
    from pipeline import server_proxy
    from pipeline.model_registry import resolve_service_model
    from pipeline.scripts import serve_smoke
    from pipeline.v4_1_production_contract import load_v4_1_production_contract

    definition = _migrated_prompt()
    root, _, model = _service_fixture(tmp_path, prompt_definition=definition)
    binding = resolve_service_model(root, alias="candidate", service_mode="development")
    requests, clients = [], []
    class Capture:
        last_capture = None
        def reset_capture(self, video):
            self.last_capture = {"frames": [{"index": 0, "timestamp": 0.0}],
                "tensor_digest": "CPU fixture", "tensor_shape": [1, 1]}
    capture = Capture()
    monkeypatch.setattr(server_proxy, "configure_loaded_processor", lambda *a, **kw: capture)
    monkeypatch.setattr(server_proxy, "_install_mm_shape_diagnostics", lambda *a: None)
    processor = type("FixtureProcessor", (), {})()
    chat_model = types.SimpleNamespace(engine=types.SimpleNamespace(processor=processor))
    monkeypatch.setitem(sys.modules, "llamafactory.chat", types.SimpleNamespace(ChatModel=lambda args: chat_model))
    monkeypatch.setitem(sys.modules, "llamafactory.api.common", types.SimpleNamespace(SAFE_MEDIA_PATH=str(tmp_path / "media")))
    monkeypatch.setitem(sys.modules, "llamafactory.api.protocol", types.SimpleNamespace(ChatCompletionRequest=types.SimpleNamespace(model_validate=lambda x: x)))
    class Response:
        def __init__(self, content):
            self.content = content
            self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
        def model_dump(self, **kw):
            return {"choices": [{"message": {"role": "assistant", "content": self.content}}]}
    async def infer(request, model):
        requests.append(request)
        content = "invalid" if len(requests) == 1 else json.dumps({"clip_state": "未断裂", "fracture_mechanism": None, "fracture_site": None, "special_case": None}, ensure_ascii=False)
        return Response(content)
    monkeypatch.setitem(sys.modules, "llamafactory.api.chat", types.SimpleNamespace(create_chat_completion_response=infer))
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: clients.append(TestClient(app))))
    monkeypatch.delenv("API_KEY", raising=False)
    config = {"max_frames": 8, "model_version": model.model_id, "adapter_version": model.model_id,
        "base_model_version": model.base_model, "processor_version": "FixtureProcessor", "llamafactory_version": "fixture",
        "transformers_version": "fixture", "config_fingerprint": binding["fingerprint"], "runtime_device": "CPU", "runtime_dtype": "fixture"}
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(sys, "argv", ["service", "--root", str(root), "--alias", "candidate", "--service-mode", "development", "--contract-version", "tensile-vlm/v4.1", "--deployment-manifest", str(path)])
    assert server_proxy.main() == 0
    client = clients[0]
    preflight = client.get('/v1/tensile/contract').json()
    assert preflight['model_registry']['prompt'] == definition
    assert preflight['model_registry']['prompt_sha256'] == binding['prompt_sha256']
    fixed = load_v4_1_production_contract()
    assert preflight['contract_hash'] != fixed['contract_hash']
    rejected = client.post('/v1/chat/completions', json=serve_smoke.build_analysis_payload(b'CPU media fixture', fixed))
    assert rejected.status_code == 422 and requests == []
    from urllib.parse import urlparse
    def request_json(url, *, payload=None, **kw):
        response = client.get(urlparse(url).path) if payload is None else client.post(urlparse(url).path, json=payload)
        response.raise_for_status()
        return response.json()
    monkeypatch.setattr(serve_smoke, '_request_json', request_json)
    video = tmp_path / 'fixture.mp4'
    video.write_bytes(b'CPU media fixture')
    monkeypatch.setattr(sys, "argv", ["smoke", "--root", str(root), "--alias", "candidate", "--service-mode", "development", "--contract-version", "tensile-vlm/v4.1", "--video", str(video)])
    assert serve_smoke.main() == 0
    capsys.readouterr()
    assert len(requests) == 2
    for request in requests:
        assert request['messages'][0]['content'] == definition['system_prompt']
        assert request['messages'][1]['content'][1]['text'] == definition['user_prompt']
        assert request['max_tokens'] == fixed['analysis']['generation']['max_new_tokens']
    assert requests[1]['messages'][-1]['content'] == fixed['analysis']['retry_prompt']
    client.close()


@pytest.mark.parametrize("source", ["training", "evaluation", "current_missing", "current_symlink"])
def test_service_rejects_frozen_prompt_damage(tmp_path, source):
    import json, yaml
    from pipeline.model_registry import resolve_service_model
    from versioning.registry import _run_artifact_root, _eval_store, get_model
    from versioning.mlflow_eval import get_eval_run
    root, registry, model = _service_fixture(tmp_path, prompt_definition=_migrated_prompt())
    if source == "training":
        path = _run_artifact_root(registry, model.run_id) / "input/prompt.yaml"
        value = yaml.safe_load(path.read_text())
        value['system_prompt'] = 'changed frozen training'
        path.chmod(path.stat().st_mode | 0o200)  # Damage only this test's sealed fixture.
        path.write_text(yaml.safe_dump(value))
    elif source == "evaluation":
        model = get_model(registry, model.model_id)
        evaluation = get_eval_run(_eval_store(registry), model.eval_id)
        path = _run_artifact_root(registry, evaluation.run_id) / "input/evaluation.yaml"
        value = json.loads(path.read_text())
        value['prompt']['system_prompt'] = 'changed frozen evaluation'
        path.chmod(path.stat().st_mode | 0o200)  # Damage only this test's sealed fixture.
        path.write_text(json.dumps(value))
    else:
        path = root / 'records/prompts/prompt-v4.1-r1.yaml'
        if source == 'current_symlink':
            copied = tmp_path / 'same-prompt.yaml'
            copied.write_bytes(path.read_bytes())
        path.unlink()
        if source == 'current_symlink':
            path.symlink_to(copied)
    with pytest.raises((ValueError, FileNotFoundError)):
        resolve_service_model(root, alias='candidate', service_mode='development')


def test_service_rejects_individually_valid_but_different_evaluated_prompt(tmp_path, monkeypatch):
    import yaml
    from test_eval_run import _formal_eval_fixture, _fake_formal_runtime
    from test_train_with_contract import _mirror_prompt_checkout
    from finetune import eval_run
    from pipeline.model_registry import resolve_service_model
    from pipeline.v4_1_production_contract import load_v4_1_production_contract
    from versioning.registry import open_registry_store, set_offline_backup_scope
    from versioning.manifest import export_model_manifest
    from versioning.materialize import materialize_current
    definition = _migrated_prompt()
    root, media, model, config = _formal_eval_fixture(tmp_path, scope='single_fold', prompt_definition=definition)
    current = root / 'records/prompts/prompt-v4.1-r1.yaml'
    original = current.read_bytes()
    fixed = load_v4_1_production_contract()
    changed = {**definition, **{k: fixed['analysis'][k] for k in ('system_prompt', 'user_prompt')}}
    current.write_text(yaml.safe_dump(changed, allow_unicode=True))
    # store 副本被改成另一份合法 Prompt 时，checkout 副本随之同步，使 prepare
    # 阶段只受「两侧字节一致」这道门约束；本用例要验证的「evaluated Prompt
    # differs」由随后把 store 副本恢复成原内容触发。
    _mirror_prompt_checkout(root)
    eval_run.prepare_versioned_evaluation(root=root, eval_version='eval-v4.1-r1', model_version=model.model_id,
        model_version_number=model.version, data_version='data-v4.1-r2', config=config, git_commit='fixture', media_root=media)
    _fake_formal_runtime(monkeypatch, prompt_definition=changed)
    eval_run.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    registry = open_registry_store(root / 'workspace/mlflow', data_root=root / 'data')
    _historical_eval_binding(registry, model.model_id, 'eval-v4.1-r1')
    set_offline_backup_scope(registry, model.model_id, 'adapter')
    export_model_manifest(root / 'records/models' / model.model_id / 'manifest.yaml', store=registry, model_id=model.model_id)
    _historical_alias(registry, model.model_id, 'candidate')
    materialize_current(registry, alias='candidate', service_mode='development', models_root=root / 'workspace/models', records_root=root)
    current.write_bytes(original)
    with pytest.raises(ValueError, match='evaluated Prompt differs'):
        resolve_service_model(root, alias='candidate', service_mode='development')
