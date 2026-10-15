"""Offline, vocabulary-only tokenizer diagnostics; never an admission provider.

The supplied executable is a reviewed, digest-pinned helper. This tool does not
download, start Ollama, instantiate a model context, normalize input, or approve
an equivalence mapping. A packaged x86 library observation is not an observation
of a native arm64 server. All paths and hashes must be explicit in the spec.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile


MODEL_REVISIONS = {
    "qwen3.5:9b": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
    "ornith-1.5:9b": "489cb97981b8654bcfcf30ce1f94ed1b62e07b53",
}
MODEL_MANIFESTS = {
    "qwen3.5:9b": "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7",
    "ornith-1.5:9b": "e5df7dcdd8a263994df62d610317e07be0d6af23f96fcbd8543273058fce575e",
}
INSTALLED_LIBRARIES = {
    "llama": "/Applications/Ollama.app/Contents/Resources/libllama.0.3.0.dylib",
    "ggml": "/Applications/Ollama.app/Contents/Resources/libggml.0.22.0.dylib",
    "ggml_base": "/Applications/Ollama.app/Contents/Resources/libggml-base.0.22.0.dylib",
}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verified_file(spec):
    path = Path(spec["path"])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("explicit absolute ordinary file required")
    expected = spec["sha256"]
    if not isinstance(expected, str) or re.fullmatch("[0-9a-f]{64}", expected) is None or digest(path) != expected:
        raise ValueError(f"file digest mismatch: {path}")
    return path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def require_x86_image(path):
    with path.open("rb") as source:
        header = source.read(8)
    if len(header) != 8 or struct.unpack("<II", header) != (0xFEEDFACF, 0x01000007):
        raise ValueError("thin x86_64 Mach-O executable/library required")


def inspect(spec):
    """Replay fixed public cases against HF and an explicitly pinned helper."""
    if spec["scope"] != "installed-package-x86_64-dylib-vocab-only":
        raise ValueError("unsupported observation scope")
    if spec["llama_cpp_commit"] != "d222767c7a6516559a3f49e7721b6c6b1acc87b4":
        raise ValueError("exact reference revision required")
    helper = verified_file(spec["helper"])
    require_x86_image(helper)
    if set(spec["installed_libraries"]) != set(INSTALLED_LIBRARIES):
        raise ValueError("all three installed library roles required")
    for role, expected_path in INSTALLED_LIBRARIES.items():
        item = spec["installed_libraries"][role]
        if item["path"] != expected_path:
            raise ValueError("fixed installed library path required")
        require_x86_image(verified_file(item))
    for item in spec["implementation_files"]:
        verified_file(item)
    hf_path = verified_file(spec["hf_material"])
    assets_path = verified_file(spec["hf_asset_inventory"])
    previous_path = verified_file(spec["previous_reference"])
    hf = json.loads(hf_path.read_text())
    assets = json.loads(assets_path.read_text())
    previous = json.loads(previous_path.read_text())
    if hf.get("synthetic_messages_only") is not True or hf.get("model_inference_executed") is not False:
        raise ValueError("only previously frozen public synthetic material accepted")
    if set(spec["models"]) != set(MODEL_REVISIONS) or set(hf["models"]) != set(MODEL_REVISIONS):
        raise ValueError("both fixed model identities required")
    for model, revision in MODEL_REVISIONS.items():
        material, inventory = hf["models"][model], assets["models"][model]
        if material["upstream_revision"] != revision or inventory["hf_revision"] != revision:
            raise ValueError("fixed HF revision mismatch")
        root = Path(spec["models"][model]["hf_assets"])
        if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
            raise ValueError("explicit ordinary HF directory required")
        if set(p.name for p in root.iterdir()) != set(inventory["files"]):
            raise ValueError("HF directory inventory mismatch")
        for name, item in inventory["files"].items():
            verified_file({"path": str(root / name), "sha256": item["sha256"]})
        if spec["models"][model]["manifest"]["sha256"] != MODEL_MANIFESTS[model]:
            raise ValueError("fixed approved model manifest required")
        verified_file(spec["models"][model]["manifest"])
        manifest = json.loads(Path(spec["models"][model]["manifest"]["path"]).read_text())
        gguf = verified_file(spec["models"][model]["gguf"])
        layers = [x for x in manifest["layers"] if x["mediaType"] == "application/vnd.ollama.image.model"]
        if len(layers) != 1 or layers[0]["digest"] != "sha256:" + spec["models"][model]["gguf"]["sha256"]:
            raise ValueError("manifest GGUF binding mismatch")
        with gguf.open("rb") as source:
            if source.read(4) != b"GGUF":
                raise ValueError("GGUF file required")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from transformers import AutoTokenizer

    report = {"schema_version": "ollama-packaged-tokenizer-observation/v1",
        "created_at": datetime.now(timezone.utc).isoformat(), "spec": spec,
        "model_generation_executed": False, "real_test_used": False,
        "independent_equivalence_approval": False, "deployment_proof": False,
        "installed_native_arm64_server_executed": False,
        "network_denied_for_helper": True, "models": {},
        "limitations": ["Actual installed package x86_64 dynamic library only; not native arm64 server execution.",
            "Exact source revision and compatible headers are evidence, not a reproducible build proof of the signed library.",
            "Finite public synthetic cases do not establish equivalence for all Unicode strings.",
            "Original prompt bytes are passed unchanged; no NFC/NFD conversion or template substitution occurs."]}
    with tempfile.TemporaryDirectory(prefix="tokenizer-parity-") as work:
        for model, material in hf["models"].items():
            tokenizer = AutoTokenizer.from_pretrained(spec["models"][model]["hf_assets"], local_files_only=True, trust_remote_code=False)
            raw_cases = [(c["id"], c["rendered_prompt"], c["token_ids"]) for c in material["cases"]]
            for case in previous["normalization_diagnostics"][model]["cases"]:
                raw_cases.append(("diagnostic-" + case["id"], case["text"], case["auto_tokenizer_ids"]))
            budget_text = "cafe\u0301 " * 4000
            budget_rendered = tokenizer.apply_chat_template([{"role": "user", "content": budget_text}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False)
            budget_ids = tokenizer.encode(budget_rendered, add_special_tokens=False)
            raw_cases.append(("diagnostic-budget-nfd-4000", budget_rendered, budget_ids))
            paths = []
            for index, (_, raw, expected) in enumerate(raw_cases):
                if len(raw.encode()) > 1024 * 1024 or tokenizer.encode(raw, add_special_tokens=False) != expected:
                    raise ValueError("public frozen HF case no longer reproduces")
                path = Path(work) / f"{index}.txt"
                path.write_bytes(raw.encode("utf-8"))
                paths.append(str(path))
            command = ["/usr/bin/arch", "-x86_64", str(helper), spec["models"][model]["gguf"]["path"], *paths]
            result = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)",
                "/usr/bin/time", "-l", *command], capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": work})
            if result.returncode != 0:
                raise ValueError(f"vocabulary helper failed: {result.returncode}: {result.stderr[-1000:]}")
            if "vocab only - skipping tensors" not in result.stderr:
                raise ValueError("missing vocabulary-only execution marker")
            images = [line.removeprefix("AUDIT_IMAGE=") for line in result.stderr.splitlines() if line.startswith("AUDIT_IMAGE=")]
            pinned_libraries = {str(Path(item["path"]).resolve()): item for item in spec["installed_libraries"].values()}
            packaged_images = [str(Path(image).resolve()) for image in images
                               if "/Applications/Ollama.app/Contents/Resources/" in image]
            if not packaged_images or set(packaged_images) != set(pinned_libraries):
                raise ValueError("actual loaded packaged libraries differ from pinned inventory")
            for library in pinned_libraries.values():
                verified_file(library)
            observed = [json.loads(line) for line in result.stdout.splitlines()]
            if len(observed) != len(raw_cases) or any(not isinstance(ids, list) or any(type(i) is not int or i < 0 for i in ids) for ids in observed):
                raise ValueError("helper token result shape invalid")
            comparisons = []
            previous_ids = {c["id"]: c["gguf_token_ids"] for c in previous["models"][model]["cases"]}
            previous_ids.update({"diagnostic-" + c["id"]: c["gguf_ids"] for c in previous["normalization_diagnostics"][model]["cases"]})
            for (name, raw, expected), ids in zip(raw_cases, observed):
                comparisons.append({"id": name, "raw_utf8_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "hf_count": len(expected), "installed_x86_count": len(ids), "installed_x86_ids": ids,
                    "complete_ids_equal_hf": ids == expected,
                    "complete_ids_equal_previous_reference": ids == previous_ids[name] if name in previous_ids else None})
                if name == "diagnostic-budget-nfd-4000":
                    comparisons[-1]["budget_diagnostic"] = {"generation_rule": "('cafe' + U+0301 + ' ') repeated exactly 4000 times",
                        "raw_content_utf8_sha256": hashlib.sha256(budget_text.encode()).hexdigest(),
                        "rendering": "unmodified fixed HF template; one user message; generation prompt true; thinking false",
                        "hf_token_ids": expected, "max_output_tokens": 512, "context_limit": 8192,
                        "hf_input_plus_output_within_budget": len(expected) + 512 <= 8192,
                        "installed_x86_input_plus_output_within_budget": len(ids) + 512 <= 8192}
            report["models"][model] = {"cases": comparisons,
                "actual_loaded_packaged_libraries": packaged_images,
                "actual_loaded_images": images,
                "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
                "stderr": result.stderr,
                "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                "max_rss_bytes": int(re.search(r"(\d+)\s+maximum resident set size", result.stderr).group(1)),
                "vocab_only_log_present": True}
    report["comparison_count"] = sum(len(m["cases"]) for m in report["models"].values())
    report["hf_equal_count"] = sum(c["complete_ids_equal_hf"] for m in report["models"].values() for c in m["cases"])
    report["previous_reference_comparison_count"] = sum(c["complete_ids_equal_previous_reference"] is not None for m in report["models"].values() for c in m["cases"])
    report["previous_reference_equal_count"] = sum(c["complete_ids_equal_previous_reference"] is True for m in report["models"].values() for c in m["cases"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.spec, args.output):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("symlink input/output paths are forbidden")
    if not args.spec.is_file():
        raise ValueError("ordinary spec file required")
    if args.output.exists():
        raise ValueError("refusing to overwrite observation output")
    result = inspect(json.loads(args.spec.read_text()))
    with args.output.open("x") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("comparison_count", "hf_equal_count", "previous_reference_equal_count")}))


if __name__ == "__main__":
    main()
