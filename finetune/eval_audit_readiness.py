"""Offline, inventory-only review preparation; never deployment/admission proof.

Only explicitly supplied local tokenizer/audit assets and installed dependency
metadata/code bytes are read. No tokenizer is instantiated and no service, model,
evaluation store or truth is accessed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import stat

from finetune import eval_review_deployment as deployment
from finetune.eval_review import MODEL_DIGESTS


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ordinary(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("explicit absolute symlink-free local path required")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError("ordinary local directory required" if directory else "ordinary local file required")
    return path


def _identity(path):
    info = path.stat()
    return {"path": str(path), "size_bytes": info.st_size, "sha256": _sha(path),
            "mode": oct(stat.S_IMODE(info.st_mode)), "owner_uid": info.st_uid,
            "group_or_world_writable": bool(info.st_mode & 0o022)}


def draft_templates():
    """Unfilled drafts deliberately fail production source/audit validation."""
    sources, audits = {}, {}
    for model, digest in MODEL_DIGESTS.items():
        sources[model] = {"path": None, "upstream_source": None, "upstream_revision": None,
            "model_sha256": digest, "files": {},
            "libraries": {name: {"version": None, "code_sha256": None}
                          for name in ("transformers", "tokenizers")},
            "implementation_sha256": None, "ollama_template_sha256": None,
            "tokenizer_equivalence_audit": {"path": None, "sha256": None}}
        audits[model] = {"schema_version": "tensile-reviewed-tokenizer-equivalence/v2",
            "purpose": "precall-context-budget", "reviewer": {"id": None, "role": None},
            "reviewed_at": None, "review_source": None,
            "binding": {"compatibility_counter": None},
            "compatibility_assets": {"manifest": {"path": None, "sha256": None},
                                     "gguf": {"path": None, "sha256": None}},
            "gguf_counter_source": None, "basis": [], "golden_cases": []}
    return {"draft_only": True, "tokenizer_sources": sources, "equivalence_audits": audits}


def _expected_static_binding(model, spec):
    return {"model": model, "model_sha256": MODEL_DIGESTS[model],
        "upstream_source": spec["upstream_source"], "upstream_revision": spec["upstream_revision"],
        "tokenizer_files": spec["files"], "libraries": spec["libraries"],
        "provider_implementation_sha256": spec["implementation_sha256"],
        "format": "hf-rendered-raw-generate-v1", "enable_thinking": False, "add_special_tokens": False}


def _audit_static_schema_errors(value, model, spec):
    """Inspect declarations only; do not authenticate, tokenize or infer."""
    errors = []
    def nonempty(item):
        return isinstance(item, str) and bool(item.strip())
    def digest(item):
        return isinstance(item, str) and len(item) == 64 and all(c in "0123456789abcdef" for c in item)
    required = {"schema_version", "purpose", "reviewer", "reviewed_at", "review_source",
                "binding", "gguf_counter_source", "basis", "golden_cases"}
    is_v2 = value.get("schema_version") == "tensile-reviewed-tokenizer-equivalence/v2"
    if is_v2:
        required.add("compatibility_assets")
    if set(value) != required:
        errors.append("audit requires exact declared fields")
    if value.get("schema_version") not in ("tensile-reviewed-tokenizer-equivalence/v1",
                                            "tensile-reviewed-tokenizer-equivalence/v2"):
        errors.append("audit schema_version invalid")
    if value.get("purpose") != "precall-context-budget":
        errors.append("audit purpose invalid")
    reviewer = value.get("reviewer")
    if (not isinstance(reviewer, dict) or set(reviewer) != {"id", "role"}
        or not nonempty(reviewer.get("id")) or reviewer.get("role") != "independent-tokenizer-auditor"):
        errors.append("audit reviewer requires named independent-tokenizer-auditor")
    try:
        stamp = datetime.fromisoformat(value.get("reviewed_at"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timezone required")
    except (ValueError, TypeError):
        errors.append("audit reviewed_at requires ISO time with timezone")
    if not nonempty(value.get("review_source")):
        errors.append("audit review_source missing or invalid")
    source = value.get("gguf_counter_source")
    if (not isinstance(source, dict) or set(source) != {"method", "implementation", "model_sha256"}
        or source.get("method") != "independent-gguf-tokenizer" or source.get("model_sha256") != MODEL_DIGESTS[model]):
        errors.append("audit GGUF counter method/model binding invalid")
    implementation = source.get("implementation") if isinstance(source, dict) else None
    if (not isinstance(implementation, dict) or set(implementation) != {"name", "version", "sha256"}
        or not nonempty(implementation.get("name")) or not nonempty(implementation.get("version"))
        or not digest(implementation.get("sha256"))):
        errors.append("audit GGUF counter implementation identity invalid")
    binding = value.get("binding")
    expected_binding = _expected_static_binding(model, spec)
    binding_fields = set(expected_binding) | {"special_token_behavior"}
    if is_v2:
        binding_fields.add("compatibility_counter")
        errors.extend(_compatibility_schema_errors(value, spec))
    if (not isinstance(binding, dict) or set(binding) != binding_fields
        or any(binding.get(key) != expected for key, expected in expected_binding.items())):
        errors.append("audit exact static binding fields/source/model mismatch")
    special = binding.get("special_token_behavior") if isinstance(binding, dict) else None
    if (not isinstance(special, dict) or set(special) != {"add_bos_token", "add_eos_token", "special_tokens_map_sha256"}
        or any(special.get(key) is not None and type(special.get(key)) is not bool for key in ("add_bos_token", "add_eos_token"))
        or not digest(special.get("special_tokens_map_sha256"))):
        errors.append("audit declared special-token behavior invalid; actual behavior remains unchecked")
    basis = value.get("basis")
    if not isinstance(basis, list) or not basis:
        errors.append("audit basis missing")
    else:
        for ref in basis:
            if (not isinstance(ref, dict) or set(ref) != {"path", "sha256", "description"}
                or not nonempty(ref.get("path")) or not Path(ref["path"]).is_absolute()
                or not digest(ref.get("sha256")) or not nonempty(ref.get("description"))):
                errors.append("audit basis declaration invalid")
    cases = value.get("golden_cases")
    seen = set()
    if not isinstance(cases, list) or not cases:
        errors.append("audit frozen golden cases missing")
    else:
        for case in cases:
            if not isinstance(case, dict) or set(case) != {"id", "messages", "rendered_prompt_sha256", "token_ids"}:
                errors.append("audit golden-case exact fields invalid")
                continue
            identity, messages, tokens = case["id"], case["messages"], case["token_ids"]
            if not nonempty(identity) or identity in seen:
                errors.append("audit golden-case id missing/duplicate")
            else:
                seen.add(identity)
            if (not isinstance(messages, list) or not messages or any(
                not isinstance(item, dict) or set(item) != {"role", "content"}
                or item.get("role") not in ("system", "user", "assistant") or not isinstance(item.get("content"), str)
                for item in messages)):
                errors.append("audit golden-case messages invalid")
            if not digest(case["rendered_prompt_sha256"]):
                errors.append("audit golden-case rendered prompt digest invalid")
            if not isinstance(tokens, list) or not tokens or any(type(item) is not int or item < 0 for item in tokens):
                errors.append("audit golden-case token ids invalid")
    return errors


def _compatibility_schema_errors(value, spec):
    """Check v2 declarations without loading an encoder or opening GGUF bytes."""
    errors = []
    def digest(item):
        return isinstance(item, str) and len(item) == 64 and all(c in "0123456789abcdef" for c in item)
    assets = value.get("compatibility_assets")
    if not isinstance(assets, dict) or set(assets) != {"manifest", "gguf"}:
        return ["audit compatibility assets require exact manifest/GGUF declarations"]
    for asset in assets.values():
        if (not isinstance(asset, dict) or set(asset) != {"path", "sha256"}
            or not isinstance(asset.get("path"), str) or not Path(asset["path"]).is_absolute()
            or not digest(asset.get("sha256"))):
            errors.append("audit compatibility asset path/digest declaration invalid")
    if errors:
        return errors
    if assets["manifest"]["sha256"] != spec["model_sha256"]:
        errors.append("audit compatibility manifest/model binding mismatch")
    binding = value.get("binding")
    counter = binding.get("compatibility_counter") if isinstance(binding, dict) else None
    expected = {"method": "qwen35-gguf-compatible-encoder/v1", "normalizer": None,
        "parse_special": True, "add_special_tokens": False,
        "runtime_regex": deployment._QWEN35_RUNTIME_REGEX,
        "gguf_sha256": assets["gguf"]["sha256"], "manifest_sha256": assets["manifest"]["sha256"],
        "original_tokenizer_sha256": spec["files"].get("tokenizer.json", {}).get("sha256"),
        "provider_implementation_sha256": spec["implementation_sha256"]}
    digest_fields = {"gguf_tokenizer_metadata_sha256", "derived_tokenizer_sha256", "unused_token_ids_sha256"}
    count_fields = {"token_count", "merge_count", "added_token_count", "encoder_token_count"}
    if (not isinstance(counter, dict) or set(counter) != set(expected) | digest_fields | count_fields | {"loader_control_overrides"}
        or any(type(counter.get(key)) is not type(item) or counter.get(key) != item for key, item in expected.items())
        or expected["original_tokenizer_sha256"] is None
        or any(not digest(counter.get(key)) for key in digest_fields)
        or any(type(counter.get(key)) is not int or counter[key] <= 0 for key in count_fields)):
        errors.append("audit compatibility counter exact identity/binding invalid")
    if isinstance(counter, dict):
        overrides = counter.get("loader_control_overrides")
        expected_overrides = list(range(248060, 248066)) if spec["model_sha256"] == MODEL_DIGESTS["qwen3.5:9b"] else []
        if (not isinstance(overrides, list) or any(type(item) is not int for item in overrides)
            or overrides != expected_overrides):
            errors.append("audit compatibility counter loader control overrides invalid")
    return errors


def _compatibility_inventory(value, blockers, model):
    """Inventory the small manifest; GGUF identity remains a declaration only."""
    assets = value["compatibility_assets"]
    result = {"gguf_bytes_read": False, "gguf_byte_identity_verified": False}
    manifest_path = _ordinary(assets["manifest"]["path"])
    gguf = _ordinary(assets["gguf"]["path"])
    if manifest_path.samefile(gguf):
        raise ValueError("compatibility manifest must not alias GGUF bytes")
    manifest = _identity(manifest_path)
    result["manifest"] = manifest
    manifest["byte_identity_matches"] = manifest["sha256"] == assets["manifest"]["sha256"]
    info = gguf.stat()
    result["gguf"] = {"path": str(gguf), "size_bytes": info.st_size,
        "declared_sha256": assets["gguf"]["sha256"], "mode": oct(stat.S_IMODE(info.st_mode)),
        "group_or_world_writable": bool(info.st_mode & 0o022)}
    content = json.loads(Path(manifest["path"]).read_bytes())
    layers = content.get("layers") if isinstance(content, dict) else None
    model_layers = ([layer for layer in layers if isinstance(layer, dict)
                     and layer.get("mediaType") == "application/vnd.ollama.image.model"]
                    if isinstance(layers, list) else [])
    result["declared_model_layer_matches"] = (len(model_layers) == 1
        and model_layers[0].get("digest") == "sha256:" + assets["gguf"]["sha256"]
        and type(model_layers[0].get("size")) is int and model_layers[0]["size"] == info.st_size)
    if not manifest["byte_identity_matches"] or not result["declared_model_layer_matches"]:
        blockers.append(f"{model}: compatibility manifest bytes or declared GGUF model layer mismatch")
    if manifest["group_or_world_writable"] or result["gguf"]["group_or_world_writable"]:
        blockers.append(f"{model}: compatibility manifest/GGUF is group/world writable")
    return result


def _audit_inventory(model, spec, blockers):
    descriptor = spec["tokenizer_equivalence_audit"]
    audit = {"verified_equivalence": False, "golden_cases_executed": False,
             "audit_static_schema_valid": False}
    try:
        path = _ordinary(descriptor["path"])
        audit["file"] = _identity(path)
        audit["byte_identity_matches"] = audit["file"]["sha256"] == descriptor["sha256"]
        if not audit["byte_identity_matches"]:
            blockers.append(f"{model}: equivalence audit byte drift")
        if audit["file"]["group_or_world_writable"]:
            blockers.append(f"{model}: equivalence audit is group/world writable")
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("audit must be a JSON object")
        errors = _audit_static_schema_errors(value, model, spec)
        audit["audit_static_schema_valid"] = not errors
        audit["static_schema_errors"] = errors
        blockers.extend(f"{model}: {error}" for error in errors)
        audit["current_mapping_schema"] = value.get("schema_version") == "tensile-reviewed-tokenizer-equivalence/v2"
        if not audit["current_mapping_schema"]:
            blockers.append(f"{model}: current production mapping requires a newly reviewed v2 audit; v1 is historical only")
        elif not _compatibility_schema_errors(value, spec):
            audit["compatibility_assets"] = _compatibility_inventory(value, blockers, model)
        # These are untrusted declarations, not verification of an auditor or
        # GGUF implementation, and must never be reused as deployment evidence.
        audit["declared_review"] = {key: value.get(key) for key in
            ("schema_version", "purpose", "reviewer", "reviewed_at", "review_source", "gguf_counter_source")}
        binding = value.get("binding")
        static_binding = _expected_static_binding(model, spec)
        binding_fields = set(static_binding) | {"special_token_behavior"}
        if audit["current_mapping_schema"]:
            binding_fields.add("compatibility_counter")
        audit["static_binding_matches"] = (isinstance(binding, dict)
            and set(binding) == binding_fields
            and all(key in binding and binding[key] == expected for key, expected in static_binding.items())
            and (not audit["current_mapping_schema"] or not _compatibility_schema_errors(value, spec)))
        if not audit["static_binding_matches"]:
            blockers.append(f"{model}: audit static source/model binding missing or mismatched")
        basis = value.get("basis")
        audit["basis"] = []
        gguf_path = None
        if audit["current_mapping_schema"]:
            assets = value.get("compatibility_assets")
            declared_gguf = assets.get("gguf") if isinstance(assets, dict) else None
            if not isinstance(declared_gguf, dict) or not isinstance(declared_gguf.get("path"), str):
                raise ValueError("v2 GGUF path unavailable; audit basis bytes not read")
            gguf_path = _ordinary(declared_gguf["path"])
        if not isinstance(basis, list) or not basis:
            blockers.append(f"{model}: audit basis missing")
        else:
            for reference in basis:
                if (not isinstance(reference, dict) or set(reference) != {"path", "sha256", "description"}
                    or not isinstance(reference["description"], str) or not reference["description"].strip()):
                    raise ValueError("audit basis requires explicit path/digest/description")
                basis_path = _ordinary(reference["path"])
                if gguf_path is not None and basis_path.samefile(gguf_path):
                    raise ValueError("inventory cannot read GGUF bytes as audit basis")
                entry = {"description": reference["description"], **_identity(basis_path)}
                entry["byte_identity_matches"] = entry["sha256"] == reference["sha256"]
                audit["basis"].append(entry)
                if not entry["byte_identity_matches"] or entry["group_or_world_writable"]:
                    blockers.append(f"{model}: audit basis byte drift or writable permissions: {entry['path']}")
        cases = value.get("golden_cases")
        audit["declared_golden_case_count"] = len(cases) if isinstance(cases, list) else None
        if not isinstance(cases, list) or not cases:
            blockers.append(f"{model}: frozen golden cases missing")
    except (OSError, ValueError, TypeError) as exc:
        audit["error"] = str(exc)
        blockers.append(f"{model}: equivalence audit unavailable or malformed: {exc}")
    return audit


def inventory(tokenizer_sources=None, *, include_template=False):
    blockers = []
    provider_sha = _sha(Path(deployment.__file__))
    report = {"schema_version": "tensile-review-readiness-inventory/v1", "inventory_only": True,
        "deployment_proof": False, "ready_for_real_review": False,
        "approved_models": dict(MODEL_DIGESTS), "provider_source_sha256": provider_sha,
        "libraries": {}, "tokenizer_sources": None, "blockers": blockers,
        "not_checked": ["installed Ollama models or templates", "tokenizer loading or golden execution",
            "GGUF bytes or GGUF/HF algorithm equivalence or reviewer authenticity", "process isolation",
            "client display instrumentation", "model inference or evaluation/admission state"]}
    for name in ("transformers", "tokenizers"):
        try:
            report["libraries"][name] = {"available": True, **deployment.installed_library_identity(name)}
        except (metadata.PackageNotFoundError, OSError, ValueError) as exc:
            report["libraries"][name] = {"available": False, "error": str(exc)}
            blockers.append(f"installed dependency missing or unreadable: {name}")
    if tokenizer_sources is None:
        blockers.append("explicit tokenizer sources JSON missing; reviewed mapping and asset inventory unknown")
    else:
        source_report = {"schema_valid": False, "models": {}}
        report["tokenizer_sources"] = source_report
        try:
            path = _ordinary(tokenizer_sources)
            source_report["file"] = _identity(path)
            if source_report["file"]["group_or_world_writable"]:
                blockers.append("tokenizer sources JSON is group/world writable")
            sources = json.loads(path.read_bytes())
            deployment.validate_tokenizer_sources(sources)
            source_report["schema_valid"] = True
            for model, spec in sources.items():
                entry = {"assets": [], "byte_inventory_matches": False}
                source_report["models"][model] = entry
                try:
                    root = _ordinary(spec["path"], directory=True)
                    info = root.stat()
                    entry["directory"] = {"path": str(root), "mode": oct(stat.S_IMODE(info.st_mode)),
                        "owner_uid": info.st_uid}
                    if info.st_mode & 0o022:
                        blockers.append(f"{model}: tokenizer directory is group/world writable")
                    files = list(root.iterdir())
                    if {asset.name for asset in files} != set(spec["files"]):
                        raise ValueError("tokenizer inventory has missing or extra assets; no asset bytes read")
                    for asset in files:
                        _ordinary(asset)
                    actual = {}
                    for asset in files:
                        identity = _identity(_ordinary(asset))
                        entry["assets"].append(identity)
                        actual[asset.name] = {key: identity[key] for key in ("sha256", "size_bytes")}
                        if identity["group_or_world_writable"]:
                            blockers.append(f"{model}: tokenizer asset is group/world writable: {asset.name}")
                    entry["byte_inventory_matches"] = actual == spec["files"]
                    if not entry["byte_inventory_matches"]:
                        blockers.append(f"{model}: tokenizer asset byte inventory drift")
                except (OSError, ValueError, TypeError) as exc:
                    entry["asset_error"] = str(exc)
                    blockers.append(f"{model}: tokenizer assets unavailable: {exc}")
                if spec["implementation_sha256"] != provider_sha:
                    blockers.append(f"{model}: provider source digest drift")
                for name, expected in spec["libraries"].items():
                    actual = report["libraries"][name]
                    if not actual.get("available") or {key: actual.get(key) for key in expected} != expected:
                        blockers.append(f"{model}: installed {name} identity missing or mismatched")
                entry["audit"] = _audit_inventory(model, spec, blockers)
        except (OSError, ValueError, TypeError) as exc:
            source_report["error"] = str(exc)
            blockers.append(f"tokenizer sources unavailable or schema invalid: {exc}")
    # Even a fully matching inventory cannot authorize a real review.
    blockers.append("inventory cannot establish reviewed tokenizer equivalence, deployment isolation or real-review authorization")
    if include_template:
        report["templates"] = draft_templates()
    return report


def write_output(path, report):
    path = Path(path)
    if any(parent.is_symlink() for parent in path.absolute().parents):
        raise ValueError("output parents must be symlink-free")
    data = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-sources", help="Explicit absolute local sources JSON; never downloads or loads tokenizers")
    parser.add_argument("--template", action="store_true", help="Include deliberately incomplete, non-production draft templates")
    parser.add_argument("--output", help="New JSON file only, owner-readable/writable; otherwise stdout")
    args = parser.parse_args(argv)
    report = inventory(args.tokenizer_sources, include_template=args.template)
    if args.output:
        write_output(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
