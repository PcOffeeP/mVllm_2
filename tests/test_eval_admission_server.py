"""Qualified serving runtime forwarding; constructors are synthetic test doubles."""
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pipeline import model_registry, server_proxy


@pytest.fixture
def serving_runtime(tmp_path, monkeypatch):
    runtime = {"generation": {"do_sample": False, "num_beams": 1,
            "max_new_tokens": 128, "video_max_frames": 8},
        "quantization_bit": 4,
        "runtime_variant": {"dtype": "bfloat16", "preprocessing_sha256": "a" * 64,
            "quantization": {"quant_type": "nf4", "double_quant": True,
                "compute_dtype": "bfloat16", "quant_storage": "uint8",
                "skip_modules": ["resampler"], "excluded_module_dtype": "bfloat16"}},
        "device": {"runtime_device": "cuda:0", "gpu_count": 1}}
    binding = {"model_version": "model-v4.1-r1", "base_model_version": "frozen-base",
        "fingerprint": "b" * 64, "model_path": "/synthetic/unused-model",
        "adapter_path": "/synthetic/unused-adapter", "evaluation_runtime": runtime}
    startup = {"max_frames": 8, "model_version": binding["model_version"],
        "adapter_version": binding["model_version"], "base_model_version": binding["base_model_version"],
        "config_fingerprint": binding["fingerprint"], "processor_version": "fixture",
        "llamafactory_version": "fixture", "transformers_version": "fixture",
        "runtime_device": "cuda:0", "runtime_dtype": "bfloat16"}
    path = tmp_path / "startup.json"
    path.write_text(json.dumps(startup))
    args = SimpleNamespace(root=tmp_path, alias="production", service_mode="production",
        contract_version="tensile-vlm/v4.1", deployment_manifest=path,
        host="127.0.0.1", port=9999)
    quantized = type("Linear4bit", (), {"__module__": "bitsandbytes.nn.modules"})()
    quantized.compute_dtype = "torch.bfloat16"
    resampler_parameter = SimpleNamespace(dtype="torch.bfloat16")
    loaded = SimpleNamespace(device="cuda:0", dtype="torch.uint8", is_loaded_in_4bit=True,
        config=SimpleNamespace(quantization_config={"bnb_4bit_quant_type": "nf4",
            "bnb_4bit_use_double_quant": True, "bnb_4bit_compute_dtype": "bfloat16",
            "bnb_4bit_quant_storage": "uint8"}), quantized_module=quantized,
        named_modules=lambda: [("adapter", quantized)],
        named_parameters=lambda: [("resampler.weight", resampler_parameter)])
    events = []
    def load(kwargs):
        events.append(("load", deepcopy(kwargs)))
        return SimpleNamespace(engine=SimpleNamespace(model=loaded))
    monkeypatch.setattr(server_proxy, "_parse_args", lambda: args)
    monkeypatch.setattr(model_registry, "resolve_service_model", lambda *a, **k: binding)
    monkeypatch.setattr(model_registry, "bind_service_contract", lambda contract, _: contract)
    monkeypatch.setattr(server_proxy, "create_integrated_app", lambda *a, **k: events.append(("app", k)))
    monkeypatch.setitem(sys.modules, "llamafactory.chat", SimpleNamespace(ChatModel=load))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *a, **k: events.append(("serve", k))))
    return binding, startup, path, loaded, events


def test_server_loads_and_serves_exact_qualified_runtime(serving_runtime):
    binding, startup, path, loaded, events = serving_runtime
    assert server_proxy.main() == 0
    assert [name for name, _ in events] == ["load", "app", "serve"]
    forwarded = events[0][1]
    assert forwarded["model_name_or_path"] == binding["model_path"]
    assert forwarded["adapter_name_or_path"] == binding["adapter_path"]
    assert forwarded["max_new_tokens"] == 128
    assert forwarded["do_sample"] is False and forwarded["num_beams"] == 1
    assert forwarded["quantization_bit"] == 4
    assert forwarded["infer_dtype"] == "bfloat16" and forwarded["device_map"] == "cuda:0"
    assert events[1][1]["service_binding"] == binding


@pytest.mark.parametrize("field,value", [("runtime_device", "cpu"), ("runtime_dtype", "float16")])
def test_startup_runtime_mismatch_fails_before_loading(serving_runtime, field, value):
    binding, startup, path, loaded, events = serving_runtime
    startup[field] = value
    path.write_text(json.dumps(startup))
    with pytest.raises(ValueError, match="qualified performance"):
        server_proxy.main()
    assert events == []


@pytest.mark.parametrize("field,value", [
    ("device", "cpu"), ("compute_dtype", "torch.float16"), ("is_loaded_in_4bit", False),
])
def test_actual_loaded_runtime_mismatch_never_opens_service(serving_runtime, field, value):
    binding, startup, path, loaded, events = serving_runtime
    setattr(loaded.quantized_module if field == "compute_dtype" else loaded, field, value)
    with pytest.raises(ValueError, match="loaded runtime|module compute_dtype"):
        server_proxy.main()
    assert [name for name, _ in events] == ["load"]


def test_frame_variant_mismatch_fails_before_loading(serving_runtime):
    binding, startup, path, loaded, events = serving_runtime
    binding["evaluation_runtime"]["generation"]["video_max_frames"] = 16
    with pytest.raises(ValueError, match="frame configuration"):
        server_proxy.main()
    assert events == []


@pytest.mark.parametrize("dtype,accepted", [("torch.bfloat16", True), ("torch.float16", False)])
def test_nonquantized_runtime_checks_actual_compute_dtype(serving_runtime, dtype, accepted):
    binding, startup, path, loaded, events = serving_runtime
    binding["evaluation_runtime"]["quantization_bit"] = None
    loaded.is_loaded_in_4bit, loaded.dtype = False, dtype
    if accepted:
        assert server_proxy.main() == 0
        assert [name for name, _ in events] == ["load", "app", "serve"]
        assert "quantization_bit" not in events[0][1]
    else:
        with pytest.raises(ValueError, match="loaded runtime dtype"):
            server_proxy.main()
        assert [name for name, _ in events] == ["load"]
