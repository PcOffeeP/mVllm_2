"""Synthetic performance accounting/authority only: no real model or test data."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from finetune.eval_performance import PerformanceRecorder, replay_performance_evidence
from finetune.eval_semantics import default_rules
from versioning.performance import (ControlledPerformanceSession, digest, performance_binding,
    validate_media_metadata, validate_performance_plan)

RAW = json.dumps({"clip_state": "未断裂", "fracture_mechanism": None, "fracture_site": None, "special_case": None}, ensure_ascii=False)


def plan():
    from pipeline.v4_1_production_contract import load_v4_1_production_contract
    contract = load_v4_1_production_contract()
    return {"schema_version": "tensile-vlm/v4.1-performance-evaluation", "purpose": "performance", "protocol": "performance-v1",
        "eval_version": "eval-v4.1-r1", "data_version": "data-v4.1-r2", "model": {"model_id": "model-v4.1-r1", "version": 1},
        "prompt": {"version": "prompt-v4.1-r1", "system_prompt": contract["analysis"]["system_prompt"],
            "user_prompt": contract["analysis"]["user_prompt"], "output_fields": contract["model_output_fields"]},
        "semantic_rules": default_rules(), "config": {"scope": "single_fold", "split": "validation", "fold": 0,
            "artifact_kind": "model", "generation": {"do_sample": False, "num_beams": 1, "max_new_tokens": 256, "video_max_frames": 8},
            "quantization_bit": None, "runtime_variant": {"dtype": "bfloat16", "preprocessing_sha256": "a"*64, "llamafactory_version": "fixture", "transformers_version": "fixture"},
            "device": {"runtime_device": "cuda:0", "gpu_count": 1}, "phase": "formal", "budget_gpu_hours": 20,
            "executor": "fixture", "session_id": "fixture-session", "issued_at": 0, "expires_at": 100000,
            "policies": {**{k: "fixture-policy" for k in ("media_strata", "cache", "repetition", "retry", "cold_start", "client_instrumentation")},"warmup":{"request_ids":[]}},
            # These are test-fixture parameters, never business defaults.
            "resource_growth_policy": {"algorithm": "window-net-growth", "metric": "vram_bytes", "window_seconds": 1800, "min_samples": 2, "max_growth_bytes": 100}},
        "media_allowlist": [{"media_id": "fixture-media", "path": "/fixture/development.mp4", "sha256": hashlib.sha256(b"media").hexdigest(),
            "metadata": {"duration": 60, "size_bytes": 5, "container": "mp4", "codec": "h264", "bit_depth": 8, "width": 1920, "height": 1080, "fps": 60}}]}


def complete(recorder, identity, at, *, latency=1, warmup=False, failed=False):
    recorder.event(identity, "uploaded", at, media_id="fixture-media", warmup=warmup)
    if failed:
        recorder.event(identity, "error", at+.1, warmup=warmup)
    recorder.event(identity, "auto_parse", at+.2, warmup=warmup, parser="strict", raw_output=RAW)
    recorder.event(identity, "backend_complete", at+.5, warmup=warmup)
    recorder.event(identity, "display_complete", at+latency, warmup=warmup)


def test_synthetic_all_gates_cannot_become_formal_pass():
    r = PerformanceRecorder(plan())
    r.runtime_collector=collector_fixture(r.plan)
    r.resource(0, vram_bytes=100, rss_bytes=100, gpu_seconds=0)
    for i in range(100):
        complete(r, str(i), i*20)
    r.resource(1800, vram_bytes=100, rss_bytes=100, gpu_seconds=1800)
    r.resource(2000, vram_bytes=100, rss_bytes=100, gpu_seconds=2000)
    report = r.report(observed_until=2000)
    assert all(report["expected_gates"].values())
    assert report["synthetic"] and report["outcome"] == "synthetic" and not report["e2e_verified"]
    evidence = r.evidence(observed_until=2000)
    assert replay_performance_evidence(plan(), evidence) == report
    evidence["synthetic"] = False
    real_claim = replay_performance_evidence(plan(), evidence)
    assert real_claim["outcome"] == "incomplete" and not real_claim["e2e_verified"]


@pytest.mark.parametrize("latency,ontime,failed", [(300,1,0),(300.001,0,0),(600,0,0),(660,0,0),(660.001,0,1)])
def test_absolute_display_boundaries(latency, ontime, failed):
    r = PerformanceRecorder(plan())
    complete(r, "same", 0, latency=latency)
    report = r.report(observed_until=latency)
    assert report["on_time_count"] == ontime and report["failure_count"] == failed


def test_retry_never_resets_upload_or_erases_failure():
    r = PerformanceRecorder(plan())
    complete(r, "same", 0, latency=301, failed=True)
    r.event("same", "retry", 302)
    with pytest.raises(ValueError, match="reset"):
        r.event("same", "uploaded", 303, media_id="fixture-media")
    with pytest.raises(ValueError, match="duplicate"):
        r.event("same", "backend_complete", 304)
    assert r.report(observed_until=304)["request_count"] == 1
    assert r.report(observed_until=304)["failure_count"] == 1


def test_backend_timeout_remains_even_before_client_deadline():
    r = PerformanceRecorder(plan())
    r.event("same", "uploaded", 0, media_id="fixture-media")
    r.event("same", "auto_parse", 599, parser="strict", raw_output=RAW)
    r.event("same", "backend_complete", 600.001)
    r.event("same", "display_complete", 601)
    assert r.report(observed_until=601)["failure_count"] == 1


def test_warmup_agent_partial_and_budget_fail_closed():
    p=plan();p["config"]["policies"]["warmup"]={"request_ids":["warm"]}
    r = PerformanceRecorder(p)
    complete(r, "warm", 0, warmup=True)
    r.event("one", "uploaded", 2, media_id="fixture-media")
    with pytest.raises(ValueError, match="complete"):
        r.event("one", "auto_parse", 3, parser="rule", raw_output='{"clip_state":"未断裂"}')
    r.event("one", "auto_parse", 3, parser="agent")
    with pytest.raises(ValueError, match="automatic completion"):
        r.event("one", "backend_complete", 4)
    r.event("one", "error", 4)
    r.resource(5, vram_bytes=0, rss_bytes=0, gpu_seconds=20*3600)
    with pytest.raises(ValueError, match="budget"):
        r.event("two", "uploaded", 6, media_id="fixture-media")
    report = r.report(observed_until=6)
    assert report["warmup_request_count"] == 1 and report["request_count"] == 1 and report["failure_count"] == 1
    assert report["stop_reason"] == "gpu_budget_exhausted"
    evidence = r.evidence(observed_until=6)
    evidence["stop_reason"] = None
    with pytest.raises(ValueError, match="erased"):
        replay_performance_evidence(p, evidence)


def test_growth_policy_is_explicit_and_resource_series_cannot_reset():
    p = plan()
    del p["config"]["resource_growth_policy"]
    with pytest.raises(ValueError, match="pre-execution"):
        PerformanceRecorder(p)
    r = PerformanceRecorder(plan())
    r.resource(0, vram_bytes=0, rss_bytes=0, gpu_seconds=0)
    r.resource(1800, vram_bytes=101, rss_bytes=0, gpu_seconds=1800)
    assert not r.report(observed_until=1800)["expected_gates"]["no_sustained_growth"]
    with pytest.raises(ValueError, match="reset"):
        r.resource(1801, vram_bytes=0, rss_bytes=0, gpu_seconds=1)


@pytest.mark.parametrize("key,value", [("duration",60.01),("size_bytes",100*1024**2+1),("codec","hevc"),("bit_depth",10),("width",1921),("height",1081),("fps",61)])
def test_performance_media_specification(key, value):
    metadata = plan()["media_allowlist"][0]["metadata"]
    metadata[key] = value
    with pytest.raises(ValueError):
        validate_media_metadata(metadata)


@pytest.mark.parametrize("change", ["version", "purpose", "test", "ttl", "executor", "session", "budget"])
def test_authority_rejects_before_loading(change, monkeypatch):
    p = plan()
    kwargs = {"now":1,"executor":"fixture","session_id":"fixture-session"}
    if change == "version": p["model"]["model_id"]="candidate"
    elif change == "purpose": p["purpose"]="quality"
    elif change == "test": p["config"]["split"]="test"
    elif change == "ttl": kwargs["now"]=100000
    elif change == "executor": kwargs["executor"]="other"
    elif change == "session": kwargs["session_id"]="other"
    else: p["config"]["budget_gpu_hours"]=21
    with pytest.raises(ValueError):
        validate_performance_plan(p, **kwargs)


def test_controlled_session_load_and_cleanup_only_its_server(monkeypatch):
    p = plan()
    loaded = []
    monkeypatch.setattr("versioning.registry.validate_model_for_evaluation", lambda *a: None)
    monkeypatch.setattr("finetune.eval_run._model_binding", lambda value: p["model"])
    monkeypatch.setattr(ControlledPerformanceSession, "sample_resources", lambda self: None)
    received = []
    async def adapter(scope, receive, send):
        received.append(await receive())
    def factory(model, startup, **kw):
        assert kw["contract"]["contract_version"] == "tensile-vlm/v4.1"
        assert kw["contract"]["analysis"]["system_prompt"] == p["prompt"]["system_prompt"]
        return adapter
    def loader(value):
        loaded.append(value)
        return object(), {"model_version":p["model"]["model_id"]}, performance_binding(p)
    session = ControlledPerformanceSession(p, store=object(), executor="fixture", session_id="fixture-session", loader=loader,
        revalidate=lambda:digest(p), clock=lambda:1, adapter_factory=factory)
    app = session.create_app()
    assert len(loaded)==1
    async def invoke():
        outgoing=[]
        await app({"type":"http","method":"POST","headers":[(b"x-performance-session",b"bad")]}, None, lambda v: _append(outgoing,v))
        assert outgoing[0]["status"]==403
    async def _append(outgoing,value): outgoing.append(value)
    asyncio.run(invoke())
    assert not received
    own=SimpleNamespace(should_exit=False)
    other=SimpleNamespace(should_exit=False)
    session.server=own
    session.close()
    assert own.should_exit and not other.should_exit
    with pytest.raises(ValueError, match="closed"):
        session.authorize(session.token)


def test_session_loopback_ttl_and_budget_before_loader(monkeypatch):
    p=plan()
    with pytest.raises(ValueError, match="loopback"):
        ControlledPerformanceSession(p,store=None,executor="fixture",session_id="fixture-session",loader=None,revalidate=lambda:None,host="0.0.0.0")
    clock=[0]
    monkeypatch.setattr("versioning.registry.validate_model_for_evaluation",lambda *a:None)
    monkeypatch.setattr("finetune.eval_run._model_binding",lambda value:p["model"])
    calls=[]
    session=ControlledPerformanceSession(p,store=object(),executor="fixture",session_id="fixture-session",loader=lambda value:calls.append(value),revalidate=lambda:digest(p),clock=lambda:clock[0])
    clock[0]=72000
    with pytest.raises(ValueError, match="budget"):
        session.create_app()
    assert not calls


def test_observation_idle_time_cannot_satisfy_continuous_processing():
    r=PerformanceRecorder(plan())
    for i in range(100):
        complete(r,str(i),i*2)
    report=r.report(observed_until=2000)
    assert report["elapsed_seconds"] == 198.5
    assert not report["expected_gates"]["minimum_duration"]
    assert len(report["request_gap_seconds"]) == 99


def test_two_backend_serial_requests_leave_display_unverified():
    r=PerformanceRecorder(plan())
    for i in range(2):
        r.event(str(i),"uploaded",i*3,media_id="fixture-media")
        r.event(str(i),"auto_parse",i*3+1,parser="strict",raw_output=RAW)
        r.event(str(i),"backend_complete",i*3+2)
    report=r.report(observed_until=5)
    assert report["request_count"] == 2 and report["on_time_count"] == 0
    assert report["timing_scope"] == "backend-only" and not report["e2e_verified"]


def test_controlled_http_retry_uses_original_deadline_and_buffers_response(monkeypatch):
    import base64
    p=plan()
    monkeypatch.setattr("versioning.registry.validate_model_for_evaluation",lambda *a:None)
    monkeypatch.setattr("finetune.eval_run._model_binding",lambda value:p["model"])
    monkeypatch.setattr(ControlledPerformanceSession,"sample_resources",lambda self:None)
    at=[1]
    timeouts=[]
    async def adapter(scope,receive,send):
        await receive()
        await send({"type":"http.response.start","status":500,"headers":[]})
        await send({"type":"http.response.body","body":b"failure"})
    async def wait_for(coro,timeout):
        timeouts.append(timeout)
        return await coro
    monkeypatch.setattr(asyncio,"wait_for",wait_for)
    session=ControlledPerformanceSession(p,store=object(),executor="fixture",session_id="fixture-session",
        loader=lambda value:(object(),{"model_version":p["model"]["model_id"]},performance_binding(p)),revalidate=lambda:digest(p),clock=lambda:at[0],adapter_factory=lambda *a,**k:adapter)
    app=session.create_app()
    payload={"model":p["model"]["model_id"],"messages":[{"role":"system","content":p["prompt"]["system_prompt"]},
        {"role":"user","content":[{"type":"video_url","video_url":{"url":"data:video/mp4;base64,"+base64.b64encode(b"media").decode()}},{"type":"text","text":p["prompt"]["user_prompt"]}]}]}
    async def invoke():
        sent=[]
        async def receive(): return {"type":"http.request","body":json.dumps(payload).encode()}
        async def send(message): sent.append(message)
        await app({"type":"http","method":"POST","headers":[(b"x-performance-session",session.token.encode()),(b"x-performance-request-id",b"same")]},receive,send)
        assert sum(m["type"]=="http.response.start" for m in sent)==1
    asyncio.run(invoke())
    at[0]=591
    asyncio.run(invoke())
    assert timeouts==[600,10]
    assert session.recorder.report(observed_until=591)["request_count"]==1
    assert session.recorder.report(observed_until=591)["failure_count"]==1


@pytest.mark.parametrize("artifact_kind",["model","merged"])
def test_actual_default_loader_resolves_full_scope_without_alias(monkeypatch,tmp_path,artifact_kind):
    import sys
    from versioning.performance import RegistryPerformanceLoader
    import versioning.registry as registry
    p=plan()
    record=SimpleNamespace(model_id="model-v4.1-r1",version=1,source_kind="trained",source_scope="full",source_evidence={},
        artifacts={"full":{artifact_kind:"artifacts/full/"+artifact_kind}},base_model="base-source")
    p["model"]["source_scope"]="full"
    p["config"]["artifact_kind"]=artifact_kind
    checked=[]
    monkeypatch.setattr(registry,"validate_model_for_evaluation",lambda *a:record)
    def materialize(store,identity,target):
        checked.append((identity,target))
        return Path(target)/identity
    monkeypatch.setattr(registry,"materialize_model",materialize)
    monkeypatch.setattr(registry,"validate_materialized_artifacts",lambda *a:None)
    monkeypatch.setattr(registry,"_complete_base_inventory",lambda path: {"path":str(path)})
    monkeypatch.setattr(registry,"_artifact_tree",lambda path:{})
    args=[]
    def chat_model(config):
        args.append(config)
        return SimpleNamespace(engine=SimpleNamespace(model=SimpleNamespace(device="cuda:0",dtype="torch.bfloat16",is_loaded_in_4bit=False),processor=object()))
    monkeypatch.setitem(sys.modules,"llamafactory.chat",SimpleNamespace(ChatModel=chat_model))
    monkeypatch.setattr("importlib.metadata.version",lambda name:"fixture")
    loader=RegistryPerformanceLoader(object())
    _,startup,receipt=loader(p)
    assert args[0]["model_name_or_path"].endswith("model-v4.1-r1/artifacts/full/"+artifact_kind)
    assert "adapter_name_or_path" not in args[0]
    assert receipt==performance_binding(p) and startup["model_version"]==p["model"]["model_id"]
    cache=Path(loader.cache.name)
    loader.close()
    assert not cache.exists()


def test_prepare_import_export_rechecks_data_model_and_synthetic(tmp_path,monkeypatch):
    from tests.test_train_with_contract import _versioned_data_fixture
    from tests.test_model_sources import base_files
    from versioning.registry import open_registry_store,register_base_model
    from finetune.eval_performance import (prepare_performance_evaluation,verify_performance_evaluation,
        execute_performance_evaluation,export_performance_evaluation)
    root,media,_,_=_versioned_data_fixture(tmp_path)
    base=base_files(tmp_path/"base")
    (base/"source-provenance.json").write_text(json.dumps({"schema":"tensile-base-provenance/v1","upstream_source":"fixture/base","upstream_revision":"fixture-revision","verified_by":"fixture"}))
    registry=open_registry_store(root/"workspace/mlflow",data_root=root/"data")
    model=register_base_model(registry,"model-v4.1-r1",model_path=base,upstream_source="fixture/base",upstream_revision="fixture-revision",git_commit="fixture")
    def probe(path):
        return {**plan()["media_allowlist"][0]["metadata"],"size_bytes":Path(path).stat().st_size}
    monkeypatch.setattr("finetune.eval_performance.probe_media",probe)
    config=plan()["config"]
    config.update(prompt_version="prompt-v4.1-r1",media_ids=["video_0000"])
    config["runtime_variant"]["preprocessing_sha256"]=hashlib.sha256(Path("pipeline/preprocessing/minicpm_preprocessor.py").read_bytes()).hexdigest()
    path=prepare_performance_evaluation(root=root,eval_version="eval-v4.1-r1",model_version=model.model_id,model_version_number=model.version,
        data_version="data-v4.1-r2",config=config,git_commit="fixture",media_root=media)
    value=verify_performance_evaluation(root=root,eval_version="eval-v4.1-r1")
    r=PerformanceRecorder(value)
    r.event("one","uploaded",0,media_id="video_0000")
    r.event("one","auto_parse",1,parser="strict",raw_output=RAW)
    r.event("one","backend_complete",2)
    evidence=tmp_path/"evidence.json"
    evidence.write_text(json.dumps(r.evidence(observed_until=2)))
    manifest_path=execute_performance_evaluation(root=root,eval_version="eval-v4.1-r1",evidence_path=evidence)
    manifest=json.loads(manifest_path.read_bytes())
    assert manifest["purpose"]=="performance" and manifest["synthetic"] and not manifest["e2e_verified"]
    assert export_performance_evaluation(root=root,eval_version="eval-v4.1-r1")==manifest_path
    with pytest.raises(FileExistsError):
        execute_performance_evaluation(root=root,eval_version="eval-v4.1-r1",evidence_path=evidence)
    media_path=Path(value["media_allowlist"][0]["path"])
    original_media=media_path.read_bytes()
    media_path.write_bytes(b"changed development media")
    with pytest.raises(ValueError,match="drift"):
        export_performance_evaluation(root=root,eval_version="eval-v4.1-r1")
    media_path.write_bytes(original_media)
    prompt_path=root/"records/prompts/prompt-v4.1-r1.yaml"
    original_prompt=prompt_path.read_text()
    prompt_path.write_text(original_prompt.replace("frozen system","changed system"))
    with pytest.raises(ValueError,match="drift"):
        export_performance_evaluation(root=root,eval_version="eval-v4.1-r1")
    prompt_path.write_text(original_prompt)
    monkeypatch.setattr("versioning.data_release.load_release_metadata",lambda *a:SimpleNamespace(purpose="holdout",training_allowed=False))
    with pytest.raises(ValueError,match="development"):
        export_performance_evaluation(root=root,eval_version="eval-v4.1-r1")


def test_lifecycle_actual_clock_and_stage_gaps_are_explicit():
    r=PerformanceRecorder(plan())
    r.set_lifecycle(cold_start_started_at=1,ready_at=10)
    complete(r,"one",11)
    report=r.report(observed_until=12)
    assert report["cold_start"]["seconds"]==9
    assert report["stage_measurement_gaps"]==["read","preprocess"]
    assert replay_performance_evidence(plan(),r.evidence(observed_until=12))==report
    with pytest.raises(ValueError,match="reset"):
        r.set_lifecycle(cold_start_started_at=1,ready_at=11)


def test_create_app_load_then_reject_closes_only_own_loader(monkeypatch):
    p=plan()
    monkeypatch.setattr("versioning.registry.validate_model_for_evaluation",lambda *a:None)
    monkeypatch.setattr("finetune.eval_run._model_binding",lambda value:p["model"])
    closed=[]
    class Loader:
        def __call__(self,value):
            return object(),{"model_version":"wrong"},performance_binding(value)
        def close(self): closed.append("own")
    session=ControlledPerformanceSession(p,store=object(),executor="fixture",session_id="fixture-session",loader=Loader(),
        revalidate=lambda:digest(p),clock=lambda:1,adapter_factory=lambda *a,**k:None)
    with pytest.raises(ValueError,match="startup"):
        session.create_app()
    assert closed==["own"] and session.closed


def quantized_stub(*, compute="bfloat16", storage="uint8", model_dtype="uint8", double=True, quant_type="nf4", module_compute="bfloat16", resampler_dtype="bfloat16", resampler_quantized=False):
    class Linear4bit:
        __module__="bitsandbytes.nn.modules"
        compute_dtype=module_compute
    return SimpleNamespace(device="cuda:0",dtype=model_dtype,is_loaded_in_4bit=True,
        config=SimpleNamespace(quantization_config={"bnb_4bit_quant_type":quant_type,"bnb_4bit_use_double_quant":double,
            "bnb_4bit_compute_dtype":compute,"bnb_4bit_quant_storage":storage}),named_modules=lambda:[("linear",Linear4bit()), *(([("resampler",Linear4bit())]) if resampler_quantized else [])],
        named_parameters=lambda:[("resampler.weight",SimpleNamespace(dtype=resampler_dtype))])


def test_4bit_compute_dtype_is_attested_separately_from_uint8_storage():
    from versioning.performance import validate_loaded_runtime
    c=plan()["config"]
    c["quantization_bit"]=4
    c["runtime_variant"]["quantization"]={"quant_type":"nf4","double_quant":True,"compute_dtype":"bfloat16","quant_storage":"uint8","skip_modules":["resampler"],"excluded_module_dtype":"bfloat16"}
    attested=validate_loaded_runtime(quantized_stub(),c)
    assert attested["runtime_dtype"]=="bfloat16" and attested["quantization"]["quant_storage"]=="uint8"


@pytest.mark.parametrize("damage",[{"compute":"float16"},{"double":False},{"quant_type":"fp4"},{"module_compute":"float16"},{"storage":"bfloat16"},{"resampler_dtype":"float32"},{"resampler_quantized":True}])
def test_4bit_loaded_quantization_drift_rejected(damage):
    from versioning.performance import validate_loaded_runtime
    c=plan()["config"]
    c["quantization_bit"]=4
    c["runtime_variant"]["quantization"]={"quant_type":"nf4","double_quant":True,"compute_dtype":"bfloat16","quant_storage":"uint8","skip_modules":["resampler"],"excluded_module_dtype":"bfloat16"}
    with pytest.raises(ValueError):
        validate_loaded_runtime(quantized_stub(**damage),c)


def receipt_policy(p, client_key, server_key):
    from versioning.performance_receipts import public_key_hex,server_source_digest,CLOCK
    return {"schema_version":"tensile.performance-display-policy/v1","client_id":"synthetic-client",
        "client_source_sha256":"c"*64,"instrumentation_sha256":"d"*64,"server_source_sha256":server_source_digest(),
        "client_public_key":public_key_hex(client_key),"server_public_key":public_key_hex(server_key),
        "session_id":p["config"]["session_id"],"clock_protocol":CLOCK}


def attested_synthetic_recording(count=100, *, reset_second_clock=False):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from versioning.performance_receipts import make_backend_receipt,make_display_receipt,sign_document,seal_server_evidence
    client,server=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
    p=plan()
    p["config"]["client_attestation_policy"]=receipt_policy(p,client,server)
    r=PerformanceRecorder(p,synthetic=True)
    r.runtime_collector=collector_fixture(p)
    r.resource(0,vram_bytes=100,rss_bytes=100,gpu_seconds=0)
    for i in range(count):
        request_id=str(i)
        nonce=f"{i+1:064x}"
        at=i*20
        r.event(request_id,"uploaded",at,media_id="fixture-media",upload_nonce=nonce)
        r.event(request_id,"auto_parse",at+.2,parser="strict",raw_output=RAW)
        r.event(request_id,"backend_complete",at+.5)
        backend=sign_document(make_backend_receipt(p,request_id=request_id,media_id="fixture-media",upload_at=at,backend_at=at+.5,
            raw_output=RAW,upload_nonce=nonce,synthetic=True,nonce=f"{i+500:064x}"),server)
        start=int((at+100)*1e9)
        if reset_second_clock and i==1:
            start=1_000_000_000
        client_receipt=sign_document(make_display_receipt(p,backend,upload_complete_monotonic_ns=start,display_complete_monotonic_ns=start+1_000_000_000),client)
        r.event(request_id,"display_complete",at+1)
        r.display_receipts[request_id]={"backend_receipt":backend,"client_receipt":client_receipt}
    if count>=100:
        r.resource(1800,vram_bytes=100,rss_bytes=100,gpu_seconds=1800)
        r.resource(2000,vram_bytes=100,rss_bytes=100,gpu_seconds=2000)
        end=2000
    else:
        end=(count-1)*20+1
    evidence=r.evidence(observed_until=end)
    core={k:v for k,v in evidence.items() if k!="server_attestation"}
    r.server_attestation=seal_server_evidence(p,core,server)
    return p,r,r.evidence(observed_until=end),client,server


def test_signed_display_receiver_trust_can_verify_without_upgrading_synthetic():
    p,r,evidence,_,_=attested_synthetic_recording()
    report=replay_performance_evidence(p,evidence)
    assert all(report["expected_gates"].values())
    assert report["display_signature_trust_verified"] and report["verified_display_receipt_count"]==100
    assert report["timing_scope"]=="signed-display-e2e"
    assert report["synthetic"] and not report["e2e_verified"] and report["outcome"]=="synthetic"
    evidence["synthetic"]=False
    with pytest.raises(ValueError,match="ledger"):
        replay_performance_evidence(p,evidence)


@pytest.mark.parametrize("damage",["signature","source","output","session","nonce","clock","missing_server","tampered_server","request"])
def test_signed_display_receipt_forgery_and_binding_rejected(damage):
    from versioning.performance_receipts import sign_document,seal_server_evidence
    p,_,evidence,client,server=attested_synthetic_recording(count=1)
    if damage=="missing_server":
        evidence["server_attestation"]=None
        report=replay_performance_evidence(p,evidence)
        assert not report["display_signature_trust_verified"] and not report["e2e_verified"]
        return
    if damage=="tampered_server":
        evidence["resources"]=[]
        evidence["observed_until"]=2
        with pytest.raises(ValueError,match="ledger"):
            replay_performance_evidence(p,evidence)
        return
    receipt=evidence["display_receipts"]["0"]["client_receipt"]
    payload=receipt["payload"]
    if damage=="signature": receipt["signature"]="00"*64
    elif damage=="source": payload["instrumentation_sha256"]="e"*64
    elif damage=="output": payload["output_sha256"]="e"*64
    elif damage=="session": payload["session_id"]="different"
    elif damage=="nonce": payload["upload_nonce"]="e"*64
    elif damage=="clock": payload["display_complete_monotonic_ns"]=payload["upload_complete_monotonic_ns"]-1
    else: payload["request_id"]="different"
    if damage!="signature": evidence["display_receipts"]["0"]["client_receipt"]=sign_document(payload,client)
    core={k:v for k,v in evidence.items() if k!="server_attestation"}
    evidence["server_attestation"]=seal_server_evidence(p,core,server)
    with pytest.raises(ValueError):
        replay_performance_evidence(p,evidence)


def test_signed_client_clock_cannot_reset_across_serial_requests():
    p,_,evidence,_,_=attested_synthetic_recording(count=2,reset_second_clock=True)
    with pytest.raises(ValueError,match="clock reset"):
        replay_performance_evidence(p,evidence)


def test_live_receipt_receiver_is_idempotent_and_locks_first_display(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from versioning.performance_receipts import make_display_receipt,sign_document
    client,server=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
    p=plan();p["config"]["client_attestation_policy"]=receipt_policy(p,client,server)
    monkeypatch.setattr("versioning.registry.validate_model_for_evaluation",lambda *a:None)
    monkeypatch.setattr("finetune.eval_run._model_binding",lambda value:p["model"])
    session=ControlledPerformanceSession(p,store=object(),executor="fixture",session_id="fixture-session",loader=lambda p:None,
        revalidate=lambda:digest(p),clock=lambda:3,server_signing_key=server)
    session.recorder=PerformanceRecorder(p,synthetic=True)
    r=session.recorder
    r.event("one","uploaded",0,media_id="fixture-media",upload_nonce="a"*64)
    r.event("one","auto_parse",1,parser="strict",raw_output=RAW)
    r.event("one","backend_complete",2)
    backend=session.backend_receipt("one")
    payload=make_display_receipt(p,backend,upload_complete_monotonic_ns=0,display_complete_monotonic_ns=3_000_000_000)
    receipt=sign_document(payload,client)
    assert session.accept_display_receipt(receipt)["display_at"]==3
    assert session.accept_display_receipt(receipt)["display_at"]==3
    assert len([e for e in r.events if e["kind"]=="display_complete"])==1
    payload["display_complete_monotonic_ns"]=4_000_000_000
    with pytest.raises(ValueError,match="locked"):
        session.accept_display_receipt(sign_document(payload,client))


def collector_fixture(p):
    # A synthetic algorithm fixture only, never proof of a real runtime.
    return {"schema_version":"tensile.performance-runtime-collector/v1","qualified":True,
        "runtime_binding_sha256":digest(performance_binding(p)),"observes_achat_exceptions":True,"clean_session_end":True}


def test_signed_display_without_runtime_collector_cannot_gain_eligibility():
    from versioning.performance_receipts import seal_server_evidence
    p,_,evidence,_,server=attested_synthetic_recording(count=1)
    evidence["runtime_collector"]=None
    evidence["server_attestation"]=seal_server_evidence(p,{k:v for k,v in evidence.items() if k!="server_attestation"},server)
    report=replay_performance_evidence(p,evidence)
    assert report["display_signature_trust_verified"]
    assert not report["runtime_collector_qualified"] and not report["e2e_verified"]


def test_actual_runtime_oom_is_observed_before_generic_500():
    from versioning.performance import ObservedPerformanceRuntime
    events=[]
    class Runtime:
        async def achat(self):
            raise MemoryError("synthetic out of memory")
    wrapped=ObservedPerformanceRuntime(Runtime(),events.append)
    async def generic_adapter():
        try:
            await wrapped.achat()
        except Exception:
            return 500
    assert asyncio.run(generic_adapter())==500 and events==["oom"]
    r=PerformanceRecorder(plan())
    r.event("one","uploaded",0,media_id="fixture-media")
    r.event("one","oom",1)
    assert not r.report(observed_until=1)["expected_gates"]["no_oom_or_crash"]


def test_frozen_net_growth_policy_tolerates_noisy_staircase():
    p=plan();p["config"]["resource_growth_policy"].update(window_seconds=3,min_samples=4)
    r=PerformanceRecorder(p)
    for at,value in enumerate([0,101,100,201]):
        r.resource(at,vram_bytes=value,rss_bytes=0,gpu_seconds=at)
    assert not r.report(observed_until=3)["expected_gates"]["no_sustained_growth"]


def test_cancelled_backend_thread_blocks_later_requests_and_formal_eligibility(monkeypatch):
    import base64
    import threading
    p=plan()
    monkeypatch.setattr("versioning.registry.validate_model_for_evaluation",lambda *a:None)
    monkeypatch.setattr("finetune.eval_run._model_binding",lambda value:p["model"])
    monkeypatch.setattr(ControlledPerformanceSession,"sample_resources",lambda self:None)
    release=threading.Event()
    entered=threading.Event()
    class Runtime:
        async def achat(self):
            entered.set()
            return await asyncio.to_thread(release.wait)
    invocations=[]
    def factory(runtime,*a,**kwargs):
        async def adapter(scope,receive,send):
            invocations.append("started")
            await receive()
            await runtime.achat()
        return adapter
    session=ControlledPerformanceSession(p,store=object(),executor="fixture",session_id="fixture-session",loader=lambda p:(Runtime(),{"model_version":p["model"]["model_id"]},performance_binding(p)),
        revalidate=lambda:digest(p),clock=lambda:1,adapter_factory=factory)
    app=session.create_app()
    payload={"model":p["model"]["model_id"],"messages":[{"role":"system","content":p["prompt"]["system_prompt"]},{"role":"user","content":[
        {"type":"video_url","video_url":{"url":"data:video/mp4;base64,"+base64.b64encode(b"media").decode()}},{"type":"text","text":p["prompt"]["user_prompt"]}]}]}
    original_wait_for=asyncio.wait_for
    async def short_wait(coro,timeout):
        return await original_wait_for(coro,timeout=.02)
    monkeypatch.setattr(asyncio,"wait_for",short_wait)
    async def invoke(identity):
        outgoing=[]
        async def receive(): return {"type":"http.request","body":json.dumps(payload).encode()}
        async def send(message): outgoing.append(message)
        await app({"type":"http","method":"POST","headers":[(b"x-performance-session",session.token.encode()),(b"x-performance-request-id",identity.encode())]},receive,send)
        return outgoing
    async def exercise():
        try:
            assert (await invoke("first"))[0]["status"]==403
            assert entered.is_set() and not release.is_set()
            assert (await invoke("second"))[0]["status"]==403
            assert invocations==["started"]
            report=session.recorder.report(observed_until=1)
            assert report["stop_reason"]=="runtime_timeout_ambiguous"
            assert not report["runtime_collector_qualified"] and not report["e2e_verified"]
        finally:
            release.set()
    asyncio.run(exercise())


def test_frozen_warmup_ids_prevent_hidden_formal_failures_and_reclassification():
    p=plan();p["config"]["policies"]["warmup"]={"request_ids":["warm-only"]}
    r=PerformanceRecorder(p)
    with pytest.raises(ValueError,match="warmup requests must terminate"):
        r.event("formal","uploaded",0,media_id="fixture-media")
    complete(r,"warm-only",0,warmup=True)
    r.event("formal","uploaded",2,media_id="fixture-media")
    r.event("formal","error",3)
    with pytest.raises(ValueError,match="warmup class"):
        r.event("hide-failure","uploaded",4,media_id="fixture-media",warmup=True)
    with pytest.raises(ValueError,match="drift"):
        r.event("formal","retry",4,warmup=True)
    with pytest.raises(ValueError,match="after formal"):
        r.event("warm-only","uploaded",4,media_id="fixture-media",warmup=True)
    report=r.report(observed_until=4)
    assert report["request_count"]==1 and report["failure_count"]==1
    p["config"]["policies"]["warmup"]="arbitrary warmups"
    with pytest.raises(ValueError,match="explicit unique request_ids"):
        PerformanceRecorder(p)


def test_signed_synthetic_ledger_cannot_hide_formal_failure_as_extra_warmup():
    from versioning.performance_receipts import seal_server_evidence
    p,_,evidence,_,server=attested_synthetic_recording(count=1)
    for event in evidence["events"]:
        event["warmup"]=True
    evidence["server_attestation"]=seal_server_evidence(p,{k:v for k,v in evidence.items() if k!="server_attestation"},server)
    with pytest.raises(ValueError,match="warmup class"):
        replay_performance_evidence(p,evidence)


def test_actual_quality_and_performance_input_builders_share_required_frame_sources(tmp_path,monkeypatch):
    """Real builder outputs on temporary synthetic stores, no model execution.

    The independent strict and semantic builders share these frame sources;
    comparing actual emitted inputs catches an omitted D pin that hand-built
    paired-input mocks would conceal. No conclusion or admission is forged.
    """
    from tests.test_eval_holdout import prepare_holdout,forbid_truth
    from finetune.eval_holdout import build_holdout_input,SEMANTIC_SOURCES
    from finetune.eval_performance import build_performance_input
    root,registry,truth,quality_kwargs=prepare_holdout(tmp_path,monkeypatch,prepare=False)
    with monkeypatch.context() as guard:
        forbid_truth(guard,truth)
        quality=build_holdout_input(**quality_kwargs)
    config=plan()["config"]
    config.update(artifact_kind="adapter",media_ids=["video_0000"])
    config["runtime_variant"]["preprocessing_sha256"]=hashlib.sha256(Path("pipeline/preprocessing/minicpm_preprocessor.py").read_bytes()).hexdigest()
    media_root=tmp_path/"original/workspace/data"
    def probe(path):
        return {**plan()["media_allowlist"][0]["metadata"],"size_bytes":Path(path).stat().st_size}
    performance=build_performance_input(root=root,eval_version="eval-v4.1-r2",model_version=quality["model"]["model_id"],
        model_version_number=quality["model"]["version"],data_version="data-v4.1-r2",config=config,git_commit="synthetic",
        media_root=media_root,probe=probe)
    assert performance["model"]==quality["model"] and performance["prompt"]==quality["prompt"]
    for key in ("generation","artifact_kind","quantization_bit"):
        assert performance["config"][key]==quality["config"][key]
    frame_sources={"finetune/validation/video_loader.py","pipeline/preprocessing/minicpm_preprocessor.py"}
    assert frame_sources <= set(SEMANTIC_SOURCES)
    for source in frame_sources:
        actual=hashlib.sha256(Path(source).read_bytes()).hexdigest()
        assert performance["implementation_sha256"][source]==quality["implementation_sha256"][source]==actual
