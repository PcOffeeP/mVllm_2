"""Offline regression cases for unchanged-text, GGUF-bound judge counting.

All assets below are generated synthetic byte-level vocabularies and metadata.
They contain no model tensors, production tokenizer files or evaluation data.
Run with the separately prepared review environment's tokenizers on PYTHONPATH.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

# 本模块需要真实 tokenizers 的用例由 _needs_tokenizers 逐项 skip；GGUF 头部解析与
# 资产哈希等纯 stdlib 用例不依赖 tokenizers，仍真跑（缺包时不制造覆盖损失）。
# review 环境 workspace/review-environment/python311 已被清理（仅剩 bin 空壳），缺
# tokenizers 包；这是环境清理的连带成本，处置待定，见 docs/pending-blockers.md PB-017。
_needs_tokenizers = pytest.mark.skipif(
    importlib.util.find_spec("tokenizers") is None,
    reason=(
        "review 环境 workspace/review-environment/python311 已被清理（仅剩 bin 空壳），"
        "缺 tokenizers 包；属清理连带成本，见 docs/pending-blockers.md PB-017"
    ),
)

from finetune import eval_review_deployment as provider
from finetune.eval_review import LocalOllamaBroker, MODEL_DIGESTS


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _descriptor(path):
    return {"path": str(path), "sha256": _sha(path)}


def _string(text):
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _value(value):
    if isinstance(value, str):
        return 8, _string(value)
    if type(value) is bool:
        return 7, struct.pack("<?", value)
    if type(value) is int:
        return 4, struct.pack("<I", value)
    if isinstance(value, list):
        subtype = 8 if not value or isinstance(value[0], str) else 6
        data = b"".join(_string(item) if subtype == 8 else struct.pack("<f", item) for item in value)
        return 9, struct.pack("<IQ", subtype, len(value)) + data
    raise AssertionError(type(value))


def _gguf(path, metadata, *, suffix=b""):
    # A nonzero declared tensor count makes accidental tensor-descriptor reads
    # observable: the file ends immediately after metadata unless suffix given.
    out = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 1, len(metadata)))
    for key, item in metadata.items():
        kind, payload = _value(item)
        out.extend(_string(key) + struct.pack("<I", kind) + payload)
    path.write_bytes(out + suffix)


def _byte_alphabet():
    visible = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    mapping = {value: chr(value) for value in visible}
    for value in range(256):
        if value not in mapping:
            mapping[value] = chr(256 + sum(index not in visible for index in range(value)))
    return mapping


class Renderer:
    add_bos_token = False
    add_eos_token = False
    special_tokens_map = {"eos_token": "<synthetic-2>"}

    def __init__(self):
        self.calls = []

    def apply_chat_template(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        assert kwargs == {"tokenize": False, "add_generation_prompt": True, "enable_thinking": False}
        return "?" * 12 + messages[0]["content"]


@pytest.fixture
def assets(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    alphabet = _byte_alphabet()
    tokens = [alphabet[value] for value in range(256)]
    merges = []
    def merge(left, right):
        result = left + right
        if result not in tokens:
            tokens.append(result)
        merges.append(left + " " + right)
        return result
    ca = merge("c", "a")
    caf = merge(ca, "f")
    cafe = merge(caf, "e")
    accent = merge(alphabet[0xcc], alphabet[0x81])
    acute_e = merge(alphabet[0xc3], alphabet[0xa9])
    cafe_acute = merge(caf, acute_e)
    leading = merge(alphabet[32], "c")
    leading = merge(leading, "a")
    leading = merge(leading, "f")
    merge(leading, "e")
    merge(leading, acute_e)
    # Existing word merges have earlier ranks than leading-space merges.
    merge(alphabet[32], cafe)
    merge(alphabet[32], cafe_acute)
    # Full installed-family shape, but every unused entry is unmistakably a
    # synthetic placeholder. No production vocabulary is opened or copied.
    tokens.extend(f"synthetic-unused-{index}" for index in range(248044 - len(tokens)))
    vocab = {token: index for index, token in enumerate(tokens)}
    added = [{"id": 248044 + offset, "content": f"<synthetic-{offset}>",
              "single_word": False, "lstrip": False, "rstrip": False,
              "normalized": False, "special": offset < 14} for offset in range(26)]
    tokens.extend(item["content"] for item in added)
    tokens.extend(f"[PAD{index}]" for index in range(250))
    bytelevel = {"type": "ByteLevel", "add_prefix_space": False, "trim_offsets": False, "use_regex": False}
    original = {"version": "1.0", "truncation": None, "padding": None,
        "added_tokens": added, "normalizer": {"type": "NFC"},
        "pre_tokenizer": {"type": "Sequence", "pretokenizers": [
            {"type": "Split", "pattern": {"Regex": provider._QWEN35_HF_REGEX},
             "behavior": "Isolated", "invert": False}, bytelevel]},
        "post_processor": bytelevel, "decoder": bytelevel,
        "model": {"type": "BPE", "dropout": None, "unk_token": None,
            "continuing_subword_prefix": "", "end_of_word_suffix": "", "fuse_unk": False,
            "byte_fallback": False, "ignore_merges": False, "vocab": vocab, "merges": merges}}
    hf = root / "hf"
    hf.mkdir()
    _write_json(hf / "tokenizer.json", original)
    metadata = {"tokenizer.chat_template": "synthetic ignored GGUF template",
        "tokenizer.ggml.add_eos_token": False, "tokenizer.ggml.add_padding_token": False,
        "tokenizer.ggml.eos_token_id": 248046, "tokenizer.ggml.padding_token_id": 248044,
        "tokenizer.ggml.merges": merges, "tokenizer.ggml.model": "gpt2", "tokenizer.ggml.pre": "qwen35",
        "tokenizer.ggml.scores": list(range(248070)) + [-1.0] * 250,
        "tokenizer.ggml.token_type": [1] * 248044 + [3] * 14 + [4] * 262,
        "tokenizer.ggml.tokens": tokens}
    model = root / "synthetic.gguf"
    manifest = root / "manifest.json"
    def save():
        _gguf(model, metadata)
        _write_json(manifest, {"layers": [{"mediaType": "application/vnd.ollama.image.model",
            "digest": "sha256:" + _sha(model), "size": model.stat().st_size}]})
        # Replace only the in-process fixed trust anchor with the synthetic
        # manifest; byte/layer/mapping verification itself remains production.
        monkeypatch.setitem(provider.MODEL_DIGESTS, "qwen3.5:9b", _sha(manifest))
        return {"gguf": _descriptor(model), "manifest": _descriptor(manifest)}
    pinned = save()
    spec = {"path": str(hf), "model_sha256": _sha(manifest)}
    return {"root": root, "original": original, "metadata": metadata, "spec": spec,
            "assets": pinned, "save": save, "renderer": Renderer(), "accent": accent}


def _build(assets):
    return provider.build_compatible_tokenizer(assets["spec"], assets["renderer"], assets=assets["assets"])


@_needs_tokenizers
def test_original_assets_renderer_and_raw_unicode_are_unchanged(assets):
    from tokenizers import Tokenizer
    path = Path(assets["spec"]["path"]) / "tokenizer.json"
    before = path.read_bytes()
    pure_hf = Tokenizer.from_str(before.decode())
    counter = _build(assets)
    nfd, nfc = "cafe\u0301", "caf\u00e9"
    assert pure_hf.encode(nfd).ids == pure_hf.encode(nfc).ids
    assert counter.encode(nfd) != counter.encode(nfc)
    assert len(counter.encode(nfd)) == 2 and len(counter.encode(nfc)) == 1
    messages = [{"role": "user", "content": nfd + " [PAD7] <synthetic-2>"}]
    result = provider.LocalTokenCounter({"synthetic": counter}).render("synthetic", messages)
    assert result["prompt"] == "?" * 12 + messages[0]["content"]
    assert assets["renderer"].calls[0][0] == messages
    assert path.read_bytes() == before
    assert counter.encode("[PAD7]") == [248077]
    assert counter.encode("<synthetic-2>") == [248046]
    assert counter.encode("<synthetic-20>") == [248064]
    with pytest.raises(ValueError, match="never adds BOS/EOS"):
        counter.encode(nfd, add_special_tokens=True)


@_needs_tokenizers
def test_4013_vs_8013_budget_counterexample_is_rejected_before_transport(assets, monkeypatch):
    from tokenizers import Tokenizer
    counter = _build(assets)
    messages = [{"role": "user", "content": "cafe\u0301 " * 4000}]
    rendered = provider.LocalTokenCounter({"synthetic": counter}).render("synthetic", messages)
    pure_hf = Tokenizer.from_str(json.dumps(assets["original"]))
    assert len(pure_hf.encode(rendered["prompt"]).ids) == 4013
    assert len(rendered["token_ids"]) == 8013
    assert 4013 + 512 <= 8192 < 8013 + 512
    model = next(iter(MODEL_DIGESTS))
    broker = LocalOllamaBroker(allow_real_model_calls=True,
        token_counter=provider.LocalTokenCounter({model: counter}), runtime_directory=assets["root"] / "broker")
    calls = []
    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(ValueError, match="context|budget"):
        broker.generate({"model": model, "messages": messages, "stream": False,
            "keep_alive": 0, "think": False,
            "options": {"num_ctx": 8192, "num_predict": 512, "temperature": 0}})
    assert calls == []


@_needs_tokenizers
def test_contraction_casefold_is_ascii_only_and_pad_literals_are_recognized(assets):
    from tokenizers import Regex, pre_tokenizers
    counter = _build(assets)
    hf_split = pre_tokenizers.Split(Regex(provider._QWEN35_HF_REGEX), "isolated")
    runtime_split = counter.encoder.pre_tokenizer
    for text in ("'s", "'S", "'t", "'T", "'re", "'RE", "'ll", "'LL"):
        assert len(hf_split.pre_tokenize_str(text)) == 1
        assert len(runtime_split.pre_tokenize_str(text)) == 1
    # Rust regex's Unicode insensitive matching accepts long s as ASCII s;
    # installed qwen35 uses explicit ASCII alternatives and must split it.
    assert len(hf_split.pre_tokenize_str("'ſmore")) == 2
    assert len(runtime_split.pre_tokenize_str("'ſmore")) == 1
    assert counter.encode("[PAD0][PAD249]") == [248070, 248319]


@_needs_tokenizers
def test_ornith_audio_controls_are_atomic_and_unused_padding_is_not_added(assets, monkeypatch):
    metadata = assets["metadata"]
    for key in ("tokenizer.ggml.add_eos_token", "tokenizer.ggml.add_padding_token", "tokenizer.ggml.scores"):
        metadata.pop(key)
    metadata["tokenizer.ggml.add_bos_token"] = False
    metadata["tokenizer.ggml.token_type"] = [1] * 248044 + [3] * 14 + [4] * 2 + [3] * 6 + [4] * 4 + [3] * 7 + [5] * 243
    metadata["tokenizer.ggml.tokens"][248070:] = ["<|audio_start|>", "<|audio_end|>", "<tts_pad>",
        "<tts_text_bos>", "<tts_text_eod>", "<tts_text_bos_single>", "<|audio_pad|>"] + [f"[PAD{index}]" for index in range(248077, 248320)]
    assets["assets"] = assets["save"]()
    assets["spec"]["model_sha256"] = assets["assets"]["manifest"]["sha256"]
    monkeypatch.setitem(provider.MODEL_DIGESTS, "qwen3.5:9b", "0" * 64)
    monkeypatch.setitem(provider.MODEL_DIGESTS, "ornith-1.5:9b", assets["spec"]["model_sha256"])
    counter = _build(assets)
    assert counter.encode("<|audio_start|><|audio_pad|>") == [248070, 248076]
    assert counter.encode("[PAD248077]") != [248077]
    assert "[PAD248077]" not in counter.encoder.get_vocab(with_added_tokens=True)
    assert counter.compatibility_counter_identity["encoder_token_count"] == 248077
    assert counter.encode("cafe\u0301") != counter.encode("caf\u00e9")


@_needs_tokenizers
@pytest.mark.parametrize("target", ["gguf", "manifest"])
def test_asset_byte_drift_is_rejected_even_when_explicit_assets_are_supplied(assets, target):
    path = Path(assets["assets"][target]["path"])
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="identity|drift"):
        _build(assets)


@_needs_tokenizers
@pytest.mark.parametrize("change", ["vocab", "merges", "special", "pre", "types", "score", "padding"])
def test_complete_gguf_mapping_drift_is_rejected_after_repinning_bytes(assets, change):
    value = assets["metadata"]
    if change == "vocab":
        value["tokenizer.ggml.tokens"][12345] += "changed"
    elif change == "merges":
        value["tokenizer.ggml.merges"] = list(reversed(value["tokenizer.ggml.merges"]))
    elif change == "special":
        value["tokenizer.ggml.tokens"][248045] = "<wrong-control>"
    elif change == "pre":
        value["tokenizer.ggml.pre"] = "qwen2"
    elif change == "types":
        value["tokenizer.ggml.token_type"][248070] = 3
    elif change == "score":
        value["tokenizer.ggml.scores"][101] = 0
    else:
        value["tokenizer.ggml.add_padding_token"] = True
    assets["assets"] = assets["save"]()
    assets["spec"]["model_sha256"] = assets["assets"]["manifest"]["sha256"]
    with pytest.raises(ValueError, match="unsupported|differ"):
        _build(assets)


@_needs_tokenizers
@pytest.mark.parametrize("change", ["vocab", "merges", "normalizer", "special"])
def test_original_hf_mapping_cannot_silently_change(assets, change):
    value = assets["original"]
    if change == "vocab":
        token = next(iter(value["model"]["vocab"]))
        value["model"]["vocab"][token] = 123
    elif change == "merges":
        value["model"]["merges"] = list(reversed(value["model"]["merges"]))
    elif change == "normalizer":
        value["normalizer"] = None
    else:
        value["added_tokens"][0]["normalized"] = True
    _write_json(Path(assets["spec"]["path"]) / "tokenizer.json", value)
    with pytest.raises(ValueError, match="unsupported|differ"):
        _build(assets)


def test_header_reader_stops_before_tensor_descriptors_and_rejects_duplicates(tmp_path):
    path = tmp_path / "tiny.gguf"
    metadata = {"general.architecture": "synthetic", "tokenizer.ggml.pre": "qwen35"}
    _gguf(path, metadata, suffix=b"NOT A TENSOR DESCRIPTOR OR PAYLOAD")
    assert provider._read_gguf_tokenizer_metadata(path) == {"tokenizer.ggml.pre": "qwen35"}
    duplicate = b"GGUF" + struct.pack("<IQQ", 3, 0, 2)
    entry = _string("tokenizer.ggml.pre") + struct.pack("<I", 8) + _string("qwen35")
    path.write_bytes(duplicate + entry + entry)
    with pytest.raises(ValueError, match="duplicate"):
        provider._read_gguf_tokenizer_metadata(path)


@pytest.mark.parametrize("payload", [b"GGUF" + struct.pack("<IQQ", 2, 0, 0),
    b"GGUF" + struct.pack("<IQQ", 3, 0, 10001),
    b"GGUF" + struct.pack("<IQQQ", 3, 0, 1, 64 * 1024 * 1024),
    b"GGUF" + struct.pack("<IQQ", 3, 0, 1)])
def test_malformed_or_unbounded_metadata_is_rejected(tmp_path, payload):
    path = tmp_path / "bad.gguf"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        provider._read_gguf_tokenizer_metadata(path)


@_needs_tokenizers
def test_old_pure_hf_audit_cannot_authorize_compatible_counter(assets):
    path = assets["root"] / "old-audit.json"
    _write_json(path, {"schema_version": "tensile-reviewed-tokenizer-equivalence/v1"})
    assets["spec"]["tokenizer_equivalence_audit"] = _descriptor(path)
    with pytest.raises(ValueError, match="newly reviewed v2"):
        provider.build_compatible_tokenizer(assets["spec"], assets["renderer"])
    counter = _build(assets)
    with pytest.raises(ValueError, match="reviewed tokenizer mapping"):
        provider.verify_tokenizer_equivalence_audit(next(iter(MODEL_DIGESTS)), assets["spec"], counter)


def _reviewed_mapping(assets, counter):
    from finetune.eval_semantics import content_digest
    spec = assets["spec"]
    path = Path(spec["path"]) / "tokenizer.json"
    spec.update(upstream_source="synthetic/offline-tokenizer", upstream_revision="a" * 40,
        files={"tokenizer.json": {"sha256": _sha(path), "size_bytes": path.stat().st_size}},
        libraries={name: {"version": "synthetic", "code_sha256": "b" * 64}
                   for name in ("transformers", "tokenizers")},
        implementation_sha256=_sha(Path(provider.__file__)))
    basis = assets["root"] / "independent-basis.txt"
    basis.write_text("Synthetic independent tokenizer audit fixture; not a production mapping.")
    raw = "?" * 12 + "[PAD7]"
    audit = {"schema_version": "tensile-reviewed-tokenizer-equivalence/v2",
        "purpose": "precall-context-budget", "reviewer": {"id": "synthetic-reviewer",
            "role": "independent-tokenizer-auditor"}, "reviewed_at": "2026-10-16T00:00:00+08:00",
        "review_source": "synthetic independent fixture only",
        "binding": {"model": "qwen3.5:9b", "model_sha256": spec["model_sha256"],
            "upstream_source": spec["upstream_source"], "upstream_revision": spec["upstream_revision"],
            "tokenizer_files": spec["files"], "libraries": spec["libraries"],
            "provider_implementation_sha256": spec["implementation_sha256"],
            "format": "hf-rendered-raw-generate-v1", "enable_thinking": False,
            "add_special_tokens": False, "special_token_behavior": {"add_bos_token": False,
                "add_eos_token": False, "special_tokens_map_sha256": content_digest(counter.special_tokens_map)},
            "compatibility_counter": copy.deepcopy(counter.compatibility_counter_identity)},
        "compatibility_assets": copy.deepcopy(assets["assets"]),
        "gguf_counter_source": {"method": "independent-gguf-tokenizer",
            "implementation": {"name": "synthetic-independent-counter", "version": "fixture", "sha256": "d" * 64},
            "model_sha256": spec["model_sha256"]},
        "basis": [{**_descriptor(basis), "description": "synthetic review evidence"}],
        "golden_cases": [{"id": "literal-pad-unmodified", "messages": [{"role": "user", "content": "[PAD7]"}],
            "rendered_prompt_sha256": hashlib.sha256(raw.encode()).hexdigest(), "token_ids": [63] * 12 + [248077]}]}
    audit_path = assets["root"] / "reviewed-v2.json"
    def save():
        _write_json(audit_path, audit)
        spec["tokenizer_equivalence_audit"] = _descriptor(audit_path)
    save()
    return audit, save


@_needs_tokenizers
def test_reviewed_v2_mapping_checks_unchanged_prompt_and_complete_golden_ids(assets):
    counter = _build(assets)
    audit, _ = _reviewed_mapping(assets, counter)
    result = provider.verify_tokenizer_equivalence_audit("qwen3.5:9b", assets["spec"], counter)
    assert result["reviewed_artifact"] == audit
    assert result["golden_case_count"] == 1
    assert result["sha256"] == assets["spec"]["tokenizer_equivalence_audit"]["sha256"]
    rebuilt = provider.build_compatible_tokenizer(assets["spec"], assets["renderer"])
    assert provider.verify_tokenizer_equivalence_audit("qwen3.5:9b", assets["spec"], rebuilt) == result


@_needs_tokenizers
@pytest.mark.parametrize("change", ["counter", "implementation", "golden", "assets"])
def test_reviewed_v2_mapping_cannot_approve_drift_by_repinning_audit(assets, change):
    counter = _build(assets)
    audit, save = _reviewed_mapping(assets, counter)
    if change == "counter":
        counter.compatibility_counter_identity["runtime_regex"] = "different tokenizer rule"
    elif change == "implementation":
        assets["spec"]["implementation_sha256"] = "e" * 64
    elif change == "golden":
        audit["golden_cases"][0]["token_ids"][-1] -= 1
    else:
        audit["compatibility_assets"]["gguf"]["sha256"] = "f" * 64
    save()
    with pytest.raises(ValueError, match="drift|mismatch|identity"):
        if change == "assets":
            # The production consumer builds from audit assets before checking
            # its resulting counter identity and golden cases.
            provider.build_compatible_tokenizer(assets["spec"], assets["renderer"])
        else:
            provider.verify_tokenizer_equivalence_audit("qwen3.5:9b", assets["spec"], counter)


def test_frozen_provider_implementation_bytes_cannot_drift(assets):
    path = Path(assets["spec"]["path"]) / "tokenizer.json"
    assets["spec"].update(files={"tokenizer.json": {"sha256": _sha(path), "size_bytes": path.stat().st_size}},
        implementation_sha256="e" * 64)
    with pytest.raises(ValueError, match="implementation drift"):
        provider._check_assets(assets["spec"])
