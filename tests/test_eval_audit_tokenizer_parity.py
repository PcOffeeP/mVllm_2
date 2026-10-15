"""Synthetic protections for the explicit, offline vocabulary observation tool.

No production tokenizer, GGUF library, model, Ollama service or dataset is read.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
from types import SimpleNamespace

import pytest

from finetune import eval_audit_tokenizer_parity as audit


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode())
    return {"path": str(path), "sha256": sha(path)}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    nfd, nfc = "cafe\u0301", "caf\u00e9"
    impl = [pinned(root / "headers" / "llama.h", b"synthetic header, never compiled")]
    macho = struct.pack("<II", 0xFEEDFACF, 0x01000007)
    libraries = {}
    for role, real_path in audit.INSTALLED_LIBRARIES.items():
        name = Path(real_path).name
        libraries[role] = pinned(root / "Applications/Ollama.app/Contents/Resources" / name,
                                 macho + b"synthetic library, never loaded")
    monkeypatch.setattr(audit, "INSTALLED_LIBRARIES", {role: item["path"] for role, item in libraries.items()})
    models, hf_models, asset_models, prior_models, diagnostics = {}, {}, {}, {}, {}
    for index, (model, revision) in enumerate(audit.MODEL_REVISIONS.items()):
        directory = root / f"model-{index}"
        assets = directory / "hf"
        asset = pinned(assets / "tokenizer.json", b"synthetic HF asset, never loaded")
        gguf = pinned(directory / "weights.gguf", b"GGUF synthetic tiny vocabulary marker only")
        manifest = pinned(directory / "manifest.json", {"layers": [{"mediaType": "application/vnd.ollama.image.model",
                                                                     "digest": "sha256:" + gguf["sha256"]}]})
        models[model] = {"hf_assets": str(assets), "gguf": gguf, "manifest": manifest}
        hf_models[model] = {"upstream_revision": revision,
                            "cases": [{"id": "decomposed-original", "rendered_prompt": nfd, "token_ids": [11]}]}
        asset_models[model] = {"hf_revision": revision, "files": {"tokenizer.json": {"sha256": asset["sha256"]}}}
        prior_models[model] = {"cases": [{"id": "decomposed-original", "gguf_token_ids": [11, 12]}]}
        diagnostics[model] = {"cases": [{"id": "composed-control", "text": nfc,
                                         "auto_tokenizer_ids": [11], "gguf_ids": [11]}]}
    monkeypatch.setattr(audit, "MODEL_MANIFESTS", {model: item["manifest"]["sha256"] for model, item in models.items()})
    spec = {"scope": "installed-package-x86_64-dylib-vocab-only",
            "llama_cpp_commit": "d222767c7a6516559a3f49e7721b6c6b1acc87b4",
            "helper": pinned(root / "vocab-helper", macho + b"synthetic executable, never launched"),
            "installed_libraries": libraries,
            "implementation_files": impl, "models": models,
            "hf_material": pinned(root / "hf-material.json", {"synthetic_messages_only": True,
                "model_inference_executed": False, "models": hf_models}),
            "hf_asset_inventory": pinned(root / "assets.json", {"models": asset_models}),
            "previous_reference": pinned(root / "reference.json", {"models": prior_models,
                "normalization_diagnostics": diagnostics})}
    state = SimpleNamespace(spec=spec, raw=[], commands=[], loads=[], response_change=None,
                            model=next(iter(models)), root=root)

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            state.loads.append((path, kwargs))
            assert kwargs == {"local_files_only": True, "trust_remote_code": False}
            return cls()

        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == {"tokenize": False, "add_generation_prompt": True, "enable_thinking": False}
            assert messages == [{"role": "user", "content": "cafe\u0301 " * 4000}]
            return "synthetic-template:" + messages[0]["content"]

        def encode(self, raw, *, add_special_tokens):
            assert add_special_tokens is False
            if raw.startswith("synthetic-template:"):
                return [11] * 4000
            assert raw in (nfd, nfc)
            return [11]

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=FakeTokenizer))

    def runner(command, **kwargs):
        state.commands.append(command)
        assert command[:3] == ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"]
        assert command[3:8] == ["/usr/bin/time", "-l", "/usr/bin/arch", "-x86_64", spec["helper"]["path"]]
        assert kwargs["timeout"] == 60
        assert set(kwargs["env"]) == {"PATH", "LC_ALL", "HOME"}
        payloads = [Path(path).read_bytes() for path in command[9:]]
        state.raw.extend(payloads)
        ids = [[11, 12] * 4000 if payload.startswith(b"synthetic-template:") else
               [11, 12] if payload == nfd.encode() else [11] for payload in payloads]
        stderr = "vocab only - skipping tensors\n12345 maximum resident set size\n"
        stderr += "".join("AUDIT_IMAGE=" + item["path"] + "\n" for item in libraries.values())
        result = SimpleNamespace(returncode=0, stderr=stderr, stdout="\n".join(json.dumps(value) for value in ids))
        if state.response_change:
            state.response_change(result)
        return result

    monkeypatch.setattr(audit.subprocess, "run", runner)
    return state


def test_import_and_default_cli_cannot_touch_models_or_spawn():
    code = '''
import builtins, pathlib, socket, subprocess, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers', 'tokenizers', 'ollama', 'requests', 'httpx'}:
        raise AssertionError('unrequested dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
def forbidden(*args, **kwargs): raise AssertionError('unrequested read/network/execution')
socket.socket = forbidden
subprocess.run = forbidden
pathlib.Path.read_text = forbidden
pathlib.Path.read_bytes = forbidden
from finetune import eval_audit_tokenizer_parity as module
sys.argv = ['eval_audit_tokenizer_parity']
try:
    module.main()
except SystemExit as error:
    assert error.code == 2
else:
    raise AssertionError('explicit spec and output must be required')
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("artifact", ["helper", "header", "library", "hf_material", "hf_asset_inventory",
                                       "previous_reference", "hf_asset", "manifest", "gguf"])
def test_any_pinned_input_drift_stops_before_tokenizer_or_helper(fixture, artifact):
    spec = fixture.spec
    if artifact == "header":
        path = Path(spec["implementation_files"][0]["path"])
    elif artifact == "library":
        path = Path(spec["installed_libraries"]["llama"]["path"])
    elif artifact == "hf_asset":
        path = Path(spec["models"][fixture.model]["hf_assets"]) / "tokenizer.json"
    elif artifact in ("manifest", "gguf"):
        path = Path(spec["models"][fixture.model][artifact]["path"])
    else:
        path = Path(spec[artifact]["path"])
    path.write_bytes(path.read_bytes() + b" drift")
    with pytest.raises(ValueError, match="digest mismatch"):
        audit.inspect(spec)
    assert fixture.loads == [] and fixture.commands == []


@pytest.mark.parametrize("target", ["file", "parent"])
def test_symlink_input_cannot_reuse_identical_pinned_bytes(fixture, target):
    spec = fixture.spec
    if target == "file":
        value = spec["helper"]
        original = Path(value["path"])
        alias = fixture.root / "helper-link"
        alias.symlink_to(original)
        value["path"] = str(alias)
    else:
        directory = Path(spec["models"][fixture.model]["hf_assets"])
        alias = fixture.root / "hf-link"
        alias.symlink_to(directory, target_is_directory=True)
        spec["models"][fixture.model]["hf_assets"] = str(alias)
    with pytest.raises(ValueError, match="ordinary"):
        audit.inspect(spec)
    assert fixture.loads == [] and fixture.commands == []


def test_original_unicode_bytes_and_mismatches_are_retained(fixture):
    result = audit.inspect(fixture.spec)
    assert fixture.raw == ["cafe\u0301".encode(), "caf\u00e9".encode(),
                           ("synthetic-template:" + "cafe\u0301 " * 4000).encode()] * 2
    assert result["comparison_count"] == 6
    assert result["hf_equal_count"] == 2
    assert result["previous_reference_equal_count"] == 4
    for model in fixture.spec["models"]:
        mismatch, control, budget = result["models"][model]["cases"]
        assert mismatch["id"] == "decomposed-original"
        assert mismatch["raw_utf8_sha256"] == hashlib.sha256("cafe\u0301".encode()).hexdigest()
        assert (mismatch["hf_count"], mismatch["installed_x86_count"]) == (1, 2)
        assert mismatch["installed_x86_ids"] == [11, 12]
        assert not mismatch["complete_ids_equal_hf"] and control["complete_ids_equal_hf"]
        assert budget["complete_ids_equal_previous_reference"] is None
        assert not budget["complete_ids_equal_hf"]
        diagnostic = budget["budget_diagnostic"]
        assert diagnostic["hf_input_plus_output_within_budget"]
        assert not diagnostic["installed_x86_input_plus_output_within_budget"]
        assert (budget["hf_count"], budget["installed_x86_count"]) == (4000, 8000)
    assert not result["installed_native_arm64_server_executed"]
    assert not result["deployment_proof"] and not result["independent_equivalence_approval"]
    assert not result["model_generation_executed"] and not result["real_test_used"]


def test_native_arm_claim_rejected_before_execution(fixture):
    fixture.spec["scope"] = "installed-native-arm64-server"
    with pytest.raises(ValueError, match="scope"):
        audit.inspect(fixture.spec)
    assert fixture.loads == [] and fixture.commands == []


@pytest.mark.parametrize("failure", ["tensors", "wrong_library", "malformed_ids", "exit_failure"])
def test_untrusted_helper_output_is_not_reported_as_evidence(fixture, failure):
    def change(result):
        if failure == "tensors":
            result.stderr = result.stderr.replace("vocab only - skipping tensors", "weights were loaded")
        elif failure == "wrong_library":
            result.stderr = result.stderr.replace("libllama.0.3.0.dylib", "unapproved.dylib")
        elif failure == "malformed_ids":
            result.stdout = "[true]\n[11]"
        else:
            result.returncode = 1
    fixture.response_change = change
    with pytest.raises(ValueError):
        audit.inspect(fixture.spec)


@pytest.mark.parametrize("path_kind", ["existing", "dangling_symlink", "symlink_parent"])
def test_output_destination_rejected_before_inspection(tmp_path, monkeypatch, path_kind):
    root = tmp_path.resolve()
    output = root / "observation.json"
    if path_kind == "existing":
        output.write_text("preserve this result")
    elif path_kind == "dangling_symlink":
        output.symlink_to(root / "missing-target")
    else:
        actual = root / "actual"
        actual.mkdir()
        link = root / "alias"
        link.symlink_to(actual, target_is_directory=True)
        output = link / "observation.json"
    spec = root / "spec.json"
    spec.write_text("{}")
    calls = []
    monkeypatch.setattr(audit, "inspect", lambda value: calls.append(value))
    monkeypatch.setattr(sys, "argv", ["audit", "--spec", str(spec), "--output", str(output)])
    with pytest.raises(ValueError):
        audit.main()
    assert calls == []
    if path_kind == "existing":
        assert output.read_text() == "preserve this result"


def test_spec_symlink_is_rejected_before_inspection(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    target = root / "actual.json"
    target.write_text("{}")
    spec = root / "spec.json"
    spec.symlink_to(target)
    calls = []
    monkeypatch.setattr(audit, "inspect", lambda value: calls.append(value))
    monkeypatch.setattr(sys, "argv", ["audit", "--spec", str(spec), "--output", str(root / "out.json")])
    with pytest.raises(ValueError):
        audit.main()
    assert calls == []


@pytest.mark.parametrize("change", ["missing_role", "arbitrary_same_bytes", "arm_image"])
def test_installed_library_identity_is_not_caller_selectable(fixture, change):
    library = fixture.spec["installed_libraries"]["llama"]
    if change == "missing_role":
        del fixture.spec["installed_libraries"]["llama"]
    elif change == "arbitrary_same_bytes":
        path = fixture.root / "replacement.dylib"
        path.write_bytes(Path(library["path"]).read_bytes())
        library["path"] = str(path)
    else:
        path = Path(library["path"])
        path.write_bytes(struct.pack("<II", 0xFEEDFACF, 0x0100000C) + b"synthetic arm image")
        library["sha256"] = sha(path)
    with pytest.raises(ValueError, match="roles|fixed installed|x86_64"):
        audit.inspect(fixture.spec)
    assert fixture.loads == [] and fixture.commands == []


def test_wrong_helper_architecture_cannot_be_certified_x86(fixture):
    item = fixture.spec["helper"]
    path = Path(item["path"])
    path.write_bytes(struct.pack("<II", 0xFEEDFACF, 0x0100000C) + b"synthetic arm helper")
    item["sha256"] = sha(path)
    with pytest.raises(ValueError, match="x86_64"):
        audit.inspect(fixture.spec)
    assert fixture.loads == [] and fixture.commands == []


def test_library_byte_drift_during_helper_execution_cannot_produce_report(fixture):
    def change(result):
        path = Path(fixture.spec["installed_libraries"]["ggml"]["path"])
        path.write_bytes(path.read_bytes() + b"changed during execution")
    fixture.response_change = change
    with pytest.raises(ValueError, match="digest mismatch"):
        audit.inspect(fixture.spec)
    assert len(fixture.commands) == 1


def test_model_manifest_trust_anchor_cannot_be_replaced_with_self_pinned_manifest(fixture):
    item = fixture.spec["models"][fixture.model]["manifest"]
    path = Path(item["path"])
    manifest = json.loads(path.read_text())
    manifest["synthetic_unapproved_variant"] = True
    path.write_text(json.dumps(manifest))
    item["sha256"] = sha(path)
    with pytest.raises(ValueError, match="fixed approved model manifest"):
        audit.inspect(fixture.spec)
    assert fixture.loads == [] and fixture.commands == []
