"""Synthetic offline inventory tests; no model, real evaluation or test data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from finetune import eval_audit_readiness as readiness


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sources(tmp_path, monkeypatch):
    libraries = {name: {"version": "synthetic", "code_sha256": "a" * 64}
                 for name in ("transformers", "tokenizers")}
    monkeypatch.setattr(readiness.deployment, "installed_library_identity", lambda name: libraries[name])
    value = {}
    for index, (model, digest) in enumerate(readiness.MODEL_DIGESTS.items()):
        root = tmp_path / str(index)
        root.mkdir(mode=0o700)
        asset = root / "tokenizer.json"
        asset.write_bytes(b"synthetic tokenizer bytes, never loaded")
        basis = tmp_path / f"basis-{index}.txt"
        basis.write_text("synthetic audit basis, not reviewed equivalence")
        spec = {"path": str(root), "upstream_source": "synthetic", "upstream_revision": "fixture",
            "model_sha256": digest, "files": {asset.name: {"sha256": sha(asset), "size_bytes": asset.stat().st_size}},
            "libraries": deepcopy(libraries), "implementation_sha256": sha(Path(readiness.deployment.__file__)),
            "ollama_template_sha256": "b" * 64}
        binding = {"model": model, "model_sha256": digest, "upstream_source": spec["upstream_source"],
            "upstream_revision": spec["upstream_revision"], "tokenizer_files": spec["files"],
            "libraries": spec["libraries"], "provider_implementation_sha256": spec["implementation_sha256"],
            "format": "hf-rendered-raw-generate-v1", "enable_thinking": False, "add_special_tokens": False,
            "special_token_behavior": {"add_bos_token": False, "add_eos_token": None,
                "special_tokens_map_sha256": "c" * 64}}
        audit = tmp_path / f"audit-{index}.json"
        audit.write_text(json.dumps({"schema_version": "tensile-reviewed-tokenizer-equivalence/v1",
            "purpose": "precall-context-budget", "reviewer": {"id": "synthetic-only", "role": "independent-tokenizer-auditor"},
            "reviewed_at": "2026-01-01T00:00:00+00:00", "review_source": "synthetic fixture",
            "binding": binding, "gguf_counter_source": {"method": "independent-gguf-tokenizer",
                "model_sha256": digest, "implementation": {"name": "synthetic-counter", "version": "fixture", "sha256": "d" * 64}},
            "basis": [{"path": str(basis), "sha256": sha(basis), "description": "synthetic basis"}],
            # Structurally valid synthetic declarations are never executed or
            # treated as authentic GGUF/HF equivalence evidence.
            "golden_cases": [{"id": "synthetic", "messages": [{"role": "user", "content": "fixture"}],
                "rendered_prompt_sha256": "e" * 64, "token_ids": [11, 12]}]}))
        spec["tokenizer_equivalence_audit"] = {"path": str(audit), "sha256": sha(audit)}
        value[model] = spec
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(value))
    return path, value


def test_default_inventory_never_imports_models_networks_or_reads_data():
    script = """
import builtins, socket
from importlib import metadata
from pathlib import Path
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers', 'tokenizers', 'ollama', 'requests', 'httpx'}:
        raise AssertionError('model/network import: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
def forbidden(*args, **kwargs): raise AssertionError('network/tokenizer/store access')
socket.socket = forbidden
from finetune import eval_audit_readiness as module
def missing(name): raise metadata.PackageNotFoundError(name)
module.deployment.installed_library_identity = missing
module.deployment.verify_local_deployment = forbidden
module.deployment._load_local_tokenizer = forbidden
module.deployment.local_metadata_transport = forbidden
original_read = Path.read_bytes
def guarded_read(path):
    if path != Path(module.deployment.__file__): raise AssertionError('unrequested file: ' + str(path))
    return original_read(path)
Path.read_bytes = guarded_read
result = module.inventory()
assert result['ready_for_real_review'] is False
assert all(not item['available'] for item in result['libraries'].values())
"""
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_matching_bytes_remain_inventory_not_equivalence_or_deployment(sources, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("tokenizer/deployment verification forbidden")
    monkeypatch.setattr(readiness.deployment, "_load_local_tokenizer", forbidden)
    monkeypatch.setattr(readiness.deployment, "verify_tokenizer_equivalence_audit", forbidden)
    result = readiness.inventory(sources[0])
    assert result["inventory_only"] and not result["deployment_proof"] and not result["ready_for_real_review"]
    assert result["tokenizer_sources"]["schema_valid"]
    for item in result["tokenizer_sources"]["models"].values():
        assert item["byte_inventory_matches"]
        assert item["audit"]["byte_identity_matches"] and item["audit"]["static_binding_matches"]
        assert item["audit"]["audit_static_schema_valid"]
        assert not item["audit"]["verified_equivalence"] and not item["audit"]["golden_cases_executed"]
    assert len(result["blockers"]) == 1


@pytest.mark.parametrize("field,bad", [
    ("schema_version", "unapproved"), ("purpose", "other"),
    ("reviewer", {"bad": "yes"}), ("reviewer", {"id": "", "role": "independent-tokenizer-auditor"}),
    ("reviewer", {"id": "fixture", "role": "model-owner"}),
    ("reviewed_at", "not-a-date"), ("reviewed_at", "2026-01-01T00:00:00"),
    ("review_source", 1), ("gguf_counter_source", {"bad": "yes"}),
    ("golden_cases", [{"id": "fake"}]), ("basis", []),
])
def test_malformed_audit_declarations_rejected_offline(sources, field, bad):
    path, value = sources
    model, spec = next(iter(value.items()))
    audit_path = Path(spec["tokenizer_equivalence_audit"]["path"])
    audit = json.loads(audit_path.read_text())
    audit[field] = bad
    audit_path.write_text(json.dumps(audit))
    spec["tokenizer_equivalence_audit"]["sha256"] = sha(audit_path)
    path.write_text(json.dumps(value))
    result = readiness.inventory(path)
    assert result["tokenizer_sources"]["schema_valid"]
    report = result["tokenizer_sources"]["models"][model]["audit"]
    assert not report["audit_static_schema_valid"] and report["static_schema_errors"]
    assert len(result["blockers"]) > 1 and not result["ready_for_real_review"]


@pytest.mark.parametrize("change", ["extra_field", "counter_method", "counter_digest", "counter_impl", "counter_sha",
    "golden_token_type", "golden_messages", "golden_sha", "golden_duplicate", "special_tokens",
    "extra_binding", "binding_model", "extra_special"])
def test_exact_fields_counter_identity_and_golden_structure_rejected(sources, change):
    path, value = sources
    model, spec = next(iter(value.items()))
    audit_path = Path(spec["tokenizer_equivalence_audit"]["path"])
    audit = json.loads(audit_path.read_text())
    if change == "extra_field":
        audit["unapproved"] = True
    elif change == "counter_method":
        audit["gguf_counter_source"]["method"] = "hf-only"
    elif change == "counter_digest":
        audit["gguf_counter_source"]["model_sha256"] = "f" * 64
    elif change == "counter_impl":
        audit["gguf_counter_source"]["implementation"]["name"] = ""
    elif change == "counter_sha":
        audit["gguf_counter_source"]["implementation"]["sha256"] = "short"
    elif change == "golden_token_type":
        audit["golden_cases"][0]["token_ids"] = [True, "12"]
    elif change == "golden_messages":
        audit["golden_cases"][0]["messages"] = [{"role": "tool", "content": "no"}]
    elif change == "golden_sha":
        audit["golden_cases"][0]["rendered_prompt_sha256"] = "invalid"
    elif change == "golden_duplicate":
        audit["golden_cases"].append(deepcopy(audit["golden_cases"][0]))
    elif change == "extra_binding":
        audit["binding"]["unapproved"] = True
    elif change == "binding_model":
        audit["binding"]["model_sha256"] = "f" * 64
    elif change == "extra_special":
        audit["binding"]["special_token_behavior"]["unapproved"] = True
    else:
        audit["binding"]["special_token_behavior"] = {}
    audit_path.write_text(json.dumps(audit))
    spec["tokenizer_equivalence_audit"]["sha256"] = sha(audit_path)
    path.write_text(json.dumps(value))
    result = readiness.inventory(path)
    assert not result["tokenizer_sources"]["models"][model]["audit"]["audit_static_schema_valid"]
    assert len(result["blockers"]) > 1


def test_writable_sources_json_has_explicit_blocker(sources):
    path, _ = sources
    path.chmod(0o666)
    result = readiness.inventory(path)
    assert result["tokenizer_sources"]["schema_valid"]
    assert "tokenizer sources JSON is group/world writable" in result["blockers"]


@pytest.mark.parametrize("change", ["asset", "audit", "basis", "dependency", "permissions", "missing"])
def test_explicit_asset_drift_missing_dependencies_and_permissions_are_reported(sources, monkeypatch, change):
    path, value = sources
    spec = next(iter(value.values()))
    if change == "asset":
        (Path(spec["path"]) / "tokenizer.json").write_bytes(b"changed")
    elif change == "audit":
        Path(spec["tokenizer_equivalence_audit"]["path"]).write_text("{}")
    elif change == "basis":
        audit = json.loads(Path(spec["tokenizer_equivalence_audit"]["path"]).read_text())
        Path(audit["basis"][0]["path"]).write_text("changed")
    elif change == "dependency":
        def missing(name):
            raise readiness.metadata.PackageNotFoundError(name)
        monkeypatch.setattr(readiness.deployment, "installed_library_identity", missing)
    elif change == "permissions":
        (Path(spec["path"]) / "tokenizer.json").chmod(0o666)
    else:
        (Path(spec["path"]) / "tokenizer.json").unlink()
    result = readiness.inventory(path)
    assert len(result["blockers"]) > 1
    assert not result["ready_for_real_review"]


def test_sources_and_asset_symlinks_rejected(sources, tmp_path):
    path, value = sources
    link = tmp_path / "source-link.json"
    link.symlink_to(path)
    assert not readiness.inventory(link)["tokenizer_sources"]["schema_valid"]
    root = Path(next(iter(value.values()))["path"])
    asset = root / "tokenizer.json"
    asset.unlink()
    asset.symlink_to(path)
    result = readiness.inventory(path)
    assert "symlink" in " ".join(result["blockers"])


def test_extra_directory_file_is_never_read(sources, monkeypatch):
    path, value = sources
    extra = Path(next(iter(value.values()))["path"]) / "unlisted.json"
    extra.write_text("unlisted content must not be inspected")
    original = Path.read_bytes
    def guarded(item):
        assert item != extra, "unlisted asset was read"
        return original(item)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = readiness.inventory(path)
    assert "extra assets" in " ".join(result["blockers"])


def test_drafts_have_no_invented_audit_or_golden_and_fail_production_validation():
    template = readiness.draft_templates()
    assert template["draft_only"]
    for audit in template["equivalence_audits"].values():
        assert audit["reviewed_at"] is None and audit["reviewer"]["id"] is None
        assert audit["basis"] == [] and audit["golden_cases"] == []
    with pytest.raises(ValueError):
        readiness.deployment.validate_tokenizer_sources(template["tokenizer_sources"])


def test_explicit_output_owner_only_exclusive_and_no_symlink(tmp_path):
    path = tmp_path / "inventory.json"
    readiness.write_output(path, {"inventory_only": True})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        readiness.write_output(path, {})
    assert json.loads(path.read_text()) == {"inventory_only": True}
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(FileExistsError):
        readiness.write_output(link, {})
    directory_link = tmp_path / "linked-dir"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        readiness.write_output(directory_link / "new.json", {})
    assert not (tmp_path / "new.json").exists()


def test_cli_stdout_contains_explicit_nonadmission_status(monkeypatch, capsys):
    monkeypatch.setattr(readiness.deployment, "installed_library_identity", lambda name: {"version": "fixture", "code_sha256": "a" * 64})
    assert readiness.main(["--template"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["inventory_only"] and not result["ready_for_real_review"]
    assert result["templates"]["draft_only"]
