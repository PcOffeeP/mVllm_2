"""Frozen local judge/tokenizer deployment verification; no downloads or inference.

Only the default local provider can produce real deployment evidence. Injected
metadata/counter providers are for synthetic verification and remain synthetic.
"""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path

from finetune.eval_review import MODEL_DIGESTS, REVIEW_RUNTIME, probe_review_isolation
from finetune.eval_semantics import content_digest

TOKENIZER_FILES = frozenset(('tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
    'added_tokens.json', 'merges.txt', 'vocab.json', 'vocab.txt', 'tokenizer.model', 'config.json',
    'chat_template.jinja'))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def installed_library_identity(name):
    """Hash actual installed package bytes before importing its executable code."""
    if name not in ('transformers', 'tokenizers'):
        raise ValueError('unapproved local tokenizer dependency')
    distribution = metadata.distribution(name)
    inventory = {}
    for relative in distribution.files or ():
        if relative.parts and relative.parts[0] == name and relative.suffix in ('.py', '.so', '.dylib', '.pyd', '.json'):
            path = Path(distribution.locate_file(relative))
            if not path.is_file() or path.is_symlink():
                raise ValueError('local tokenizer library contains missing or symlink code')
            inventory[relative.as_posix()] = _sha(path)
    if not inventory:
        raise ValueError('local tokenizer dependency source inventory is empty')
    return {'version': distribution.version, 'code_sha256': content_digest(inventory)}


def validate_tokenizer_sources(sources):
    if not isinstance(sources, dict) or set(sources) != set(MODEL_DIGESTS):
        raise ValueError('freeze explicit local tokenizer sources for both approved judge models')
    for model, spec in sources.items():
        required = {'path', 'upstream_source', 'upstream_revision', 'model_sha256', 'files',
            'libraries', 'implementation_sha256', 'ollama_template_sha256', 'tokenizer_equivalence_audit'}
        if not isinstance(spec, dict) or set(spec) != required:
            raise ValueError('tokenizer source requires complete provenance/files/library/implementation/template identities')
        if (not isinstance(spec['path'], str) or not Path(spec['path']).is_absolute()
            or any(not isinstance(spec[key], str) or not spec[key].strip() for key in ('upstream_source', 'upstream_revision'))
            or spec['model_sha256'] != MODEL_DIGESTS[model]):
            raise ValueError('local tokenizer source/model identity mismatch')
        for key in ('implementation_sha256', 'ollama_template_sha256'):
            if not isinstance(spec[key], str) or len(spec[key]) != 64 or any(c not in '0123456789abcdef' for c in spec[key]):
                raise ValueError('local tokenizer requires full implementation/template SHA256')
        audit = spec['tokenizer_equivalence_audit']
        if (not isinstance(audit, dict) or set(audit) != {'path', 'sha256'}
            or not isinstance(audit['path'], str) or not Path(audit['path']).is_absolute()
            or not isinstance(audit['sha256'], str) or len(audit['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in audit['sha256'])):
            raise ValueError('explicit reviewed GGUF/HF tokenizer equivalence audit required')
        files = spec['files']
        if not isinstance(files, dict) or not files or set(files) - TOKENIZER_FILES:
            raise ValueError('tokenizer inventory must explicitly contain only approved local tokenizer assets')
        for identity in files.values():
            if (not isinstance(identity, dict) or set(identity) != {'sha256', 'size_bytes'}
                or not isinstance(identity['sha256'], str) or len(identity['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in identity['sha256'])
                or type(identity['size_bytes']) is not int or identity['size_bytes'] <= 0):
                raise ValueError('tokenizer asset requires actual complete byte identity')
        libraries = spec['libraries']
        if not isinstance(libraries, dict) or set(libraries) != {'transformers', 'tokenizers'}:
            raise ValueError('both local tokenizer dependencies must be frozen')
        for library in libraries.values():
            if (not isinstance(library, dict) or set(library) != {'version', 'code_sha256'}
                or not isinstance(library['version'], str) or not library['version'] or library['version'].lower() == 'unknown'
                or not isinstance(library['code_sha256'], str) or len(library['code_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in library['code_sha256'])):
                raise ValueError('tokenizer library requires exact installed version and source digest')
    return sources


def _check_assets(spec):
    root = Path(spec['path'])
    if any(path.is_symlink() for path in (root, *root.parents)) or not root.is_dir():
        raise ValueError('local tokenizer directory must be ordinary and symlink-free')
    files = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in files) or {path.name for path in files} != set(spec['files']):
        raise ValueError('local tokenizer inventory has missing/extra/symlink assets')
    actual = {path.name: {'size_bytes': path.stat().st_size, 'sha256': _sha(path)} for path in files}
    if actual != spec['files'] or spec['implementation_sha256'] != _sha(__file__):
        raise ValueError('local tokenizer asset/provider implementation drift')
    return actual


def _load_local_tokenizer(spec):
    for name, expected in spec['libraries'].items():
        if installed_library_identity(name) != expected:
            raise ValueError('local tokenizer installed dependency bytes/version drift')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(spec['path'], local_files_only=True, trust_remote_code=False)
    if not tokenizer.__class__.__module__.startswith('transformers.'):
        raise ValueError('local tokenizer provider must use trusted installed Transformers implementation')
    return tokenizer


# These rules implement only the two frozen qwen35/GPT-2 vocabularies.  They
# deliberately do not infer behavior for other GGUF pretokenizer families.
_QWEN35_HF_REGEX = r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+|\p{N}| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
_QWEN35_RUNTIME_REGEX = r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+|\p{N}| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"


def _file_sha256(path):
    """Bound large GGUF bytes without loading tensor data into memory."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_gguf_tokenizer_metadata(path):
    """Read bounded GGUF v3 metadata only; never seek into/load tensor data."""
    import struct
    limit = 64 * 1024 * 1024
    with Path(path).open('rb') as stream:
        def read(size):
            if type(size) is not int or size < 0 or stream.tell() + size > limit:
                raise ValueError('GGUF tokenizer metadata exceeds bounded header limit')
            raw = stream.read(size)
            if len(raw) != size:
                raise ValueError('truncated GGUF tokenizer header')
            return raw
        def number(fmt):
            return struct.unpack('<' + fmt, read(struct.calcsize(fmt)))[0]
        def string():
            try:
                return read(number('Q')).decode('utf-8')
            except UnicodeDecodeError as exc:
                raise ValueError('GGUF metadata is not valid UTF-8') from exc
        def value(kind, depth=0):
            if kind == 8:
                return string()
            if kind == 9:
                subtype, size = number('I'), number('Q')
                if depth or subtype == 9 or size > 1000000:
                    raise ValueError('unsupported GGUF tokenizer metadata array')
                return [value(subtype, depth + 1) for _ in range(size)]
            formats = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i',
                       6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}
            if kind not in formats:
                raise ValueError('unsupported GGUF metadata type')
            return number(formats[kind])
        if read(4) != b'GGUF' or number('I') != 3:
            raise ValueError('compatible counter requires GGUF v3')
        number('Q')  # Tensor count; no tensor descriptors or data are read.
        count = number('Q')
        if count > 10000:
            raise ValueError('GGUF metadata key count exceeds limit')
        result, seen = {}, set()
        for _ in range(count):
            key = string()
            if key in seen:
                raise ValueError('duplicate GGUF metadata key')
            seen.add(key)
            item = value(number('I'))
            if key.startswith('tokenizer.'):
                result[key] = item
        return result


def _compatibility_assets(spec):
    descriptor = spec['tokenizer_equivalence_audit']
    path = _ordinary_audit(descriptor['path'])
    if _sha(path) != descriptor['sha256']:
        raise ValueError('reviewed tokenizer equivalence audit byte drift')
    audit = json.loads(path.read_bytes())
    if audit.get('schema_version') != 'tensile-reviewed-tokenizer-equivalence/v2':
        raise ValueError('compatible counter requires a newly reviewed v2 mapping')
    assets = audit.get('compatibility_assets')
    return _validate_compatibility_assets(spec, assets)


def _validate_compatibility_assets(spec, assets):
    if not isinstance(assets, dict) or set(assets) != {'manifest', 'gguf'}:
        raise ValueError('compatible counter requires frozen manifest and GGUF assets')
    for name, identity in assets.items():
        if (not isinstance(identity, dict) or set(identity) != {'path', 'sha256'}
            or not isinstance(identity['sha256'], str) or len(identity['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in identity['sha256'])
            or _file_sha256(_ordinary_audit(identity['path'])) != identity['sha256']):
            raise ValueError('compatible counter manifest/GGUF byte identity drift')
    if assets['manifest']['sha256'] != spec['model_sha256']:
        raise ValueError('compatible counter manifest must be the frozen approved model')
    manifest = json.loads(Path(assets['manifest']['path']).read_bytes())
    layers = [layer for layer in manifest.get('layers', [])
              if layer.get('mediaType') == 'application/vnd.ollama.image.model']
    if len(layers) != 1 or layers[0].get('digest') != 'sha256:' + assets['gguf']['sha256']:
        raise ValueError('compatible counter GGUF is not the approved manifest model layer')
    if layers[0].get('size') != Path(assets['gguf']['path']).stat().st_size:
        raise ValueError('compatible counter GGUF model layer size drift')
    return assets


class CompatibleLocalTokenizer:
    """Keep frozen HF rendering; encode its exact output using GGUF rules."""
    def __init__(self, renderer, encoder, identity):
        self.renderer, self.encoder = renderer, encoder
        self.compatibility_counter_identity = identity
        self.add_bos_token = renderer.add_bos_token
        self.add_eos_token = renderer.add_eos_token
        self.special_tokens_map = renderer.special_tokens_map

    def apply_chat_template(self, *args, **kwargs):
        return self.renderer.apply_chat_template(*args, **kwargs)

    def encode(self, text, *, add_special_tokens=False):
        if add_special_tokens is not False:
            raise ValueError('compatible counter never adds BOS/EOS')
        return self.encoder.encode(text, add_special_tokens=False).ids


def build_compatible_tokenizer(spec, renderer, *, assets=None):
    """Derive a local encoder after checking every token, merge and special ID.

    The original HF files/renderer and text are never modified.  This is not a
    claim of native Ollama calibration: the separately reviewed mapping and
    golden cases remain mandatory in verify_local_deployment.
    """
    from tokenizers import Tokenizer
    assets = (_compatibility_assets(spec) if assets is None
              else _validate_compatibility_assets(spec, assets))
    gguf = _read_gguf_tokenizer_metadata(assets['gguf']['path'])
    original = json.loads((Path(spec['path']) / 'tokenizer.json').read_bytes())
    model = original.get('model', {})
    options = {key: item for key, item in model.items() if key not in ('vocab', 'merges')}
    expected_options = {'type': 'BPE', 'dropout': None, 'unk_token': None,
        'continuing_subword_prefix': '', 'end_of_word_suffix': '', 'fuse_unk': False,
        'byte_fallback': False, 'ignore_merges': False}
    bytelevel = {'type': 'ByteLevel', 'add_prefix_space': False, 'trim_offsets': False, 'use_regex': False}
    expected_pre = {'type': 'Sequence', 'pretokenizers': [
        {'type': 'Split', 'pattern': {'Regex': _QWEN35_HF_REGEX}, 'behavior': 'Isolated', 'invert': False}, bytelevel]}
    if (options != expected_options or original.get('normalizer') != {'type': 'NFC'}
        or original.get('pre_tokenizer') != expected_pre or original.get('post_processor') != bytelevel
        or original.get('decoder') != bytelevel or original.get('truncation') is not None
        or original.get('padding') is not None):
        raise ValueError('unsupported frozen HF qwen35 tokenizer rules')
    shared_keys = {'tokenizer.chat_template', 'tokenizer.ggml.eos_token_id',
        'tokenizer.ggml.merges', 'tokenizer.ggml.model', 'tokenizer.ggml.padding_token_id',
        'tokenizer.ggml.pre', 'tokenizer.ggml.token_type', 'tokenizer.ggml.tokens'}
    is_qwen = spec['model_sha256'] == MODEL_DIGESTS['qwen3.5:9b']
    is_ornith = spec['model_sha256'] == MODEL_DIGESTS['ornith-1.5:9b']
    variant_keys = ({'tokenizer.ggml.add_eos_token', 'tokenizer.ggml.add_padding_token',
                     'tokenizer.ggml.scores'} if is_qwen else {'tokenizer.ggml.add_bos_token'})
    if (not (is_qwen or is_ornith) or set(gguf) != shared_keys | variant_keys
        or gguf['tokenizer.ggml.model'] != 'gpt2' or gguf['tokenizer.ggml.pre'] != 'qwen35'
        or any(gguf.get(key, False) is not False for key in (
            'tokenizer.ggml.add_bos_token', 'tokenizer.ggml.add_eos_token', 'tokenizer.ggml.add_padding_token'))
        or gguf['tokenizer.ggml.eos_token_id'] != 248046
        or gguf['tokenizer.ggml.padding_token_id'] != 248044
        or renderer.add_bos_token is not False or renderer.add_eos_token is not False):
        raise ValueError('unsupported GGUF qwen35 special/pretokenizer settings')
    tokens, types = gguf['tokenizer.ggml.tokens'], gguf['tokenizer.ggml.token_type']
    vocabulary, added = model.get('vocab'), original.get('added_tokens')
    expected_types = ([1] * 248044 + [3] * 14 + [4] * 262 if is_qwen else
        [1] * 248044 + [3] * 14 + [4] * 2 + [3] * 6 + [4] * 4 + [3] * 7 + [5] * 243)
    if (not isinstance(vocabulary, dict) or len(vocabulary) != 248044
        or set(vocabulary.values()) != set(range(248044))
        or not isinstance(added, list) or len(added) != 26
        or len(tokens) != 248320 or len(set(tokens)) != len(tokens)
        or types != expected_types
        or (is_qwen and gguf['tokenizer.ggml.scores'] != list(range(248070)) + [-1.0] * 250)
        or any(tokens[index] != token for token, index in vocabulary.items())
        or gguf['tokenizer.ggml.merges'] != model.get('merges')):
        raise ValueError('GGUF/HF complete vocabulary, token types or ordered merges differ')
    for offset, token in enumerate(added):
        index = 248044 + offset
        expected = {'id': index, 'content': tokens[index], 'single_word': False,
                    'lstrip': False, 'rstrip': False, 'normalized': False, 'special': offset < 14}
        if token != expected:
            raise ValueError('HF/GGUF added-token rules or complete ID mapping differ')
    expected_tail = ([f'[PAD{i}]' for i in range(250)] if is_qwen else
        ['<|audio_start|>', '<|audio_end|>', '<tts_pad>', '<tts_text_bos>', '<tts_text_eod>',
         '<tts_text_bos_single>', '<|audio_pad|>'] + [f'[PAD{i}]' for i in range(248077, 248320)])
    if tokens[248070:] != expected_tail:
        raise ValueError('unsupported GGUF additional control/user-defined/unused token tail')
    derived = json.loads(json.dumps(original))
    derived['normalizer'] = None
    derived['pre_tokenizer']['pretokenizers'][0]['pattern']['Regex'] = _QWEN35_RUNTIME_REGEX
    # GGUF CONTROL/USER_DEFINED are atomically recognized with parse_special;
    # UNUSED entries must never become literal added-token matches.
    # llama's loader additionally marks six Qwen FIM/repository entries as
    # CONTROL. With parse_special=True they retain the same atomic IDs, but
    # preserve that effective classification in the encoder/audit identity.
    control_overrides = list(range(248060, 248066)) if is_qwen else []
    derived['added_tokens'] = [{'id': index, 'content': tokens[index],
        'single_word': False, 'lstrip': False, 'rstrip': False, 'normalized': False,
        'special': types[index] == 3 or index in control_overrides} for index in range(248044, len(tokens)) if types[index] in (3, 4)]
    encoder = Tokenizer.from_str(json.dumps(derived, ensure_ascii=False))
    expected_vocabulary = {token: index for index, token in enumerate(tokens) if types[index] != 5}
    if encoder.get_vocab(with_added_tokens=True) != expected_vocabulary:
        raise ValueError('constructed compatible counter vocabulary drift')
    identity = {'method': 'qwen35-gguf-compatible-encoder/v1',
        'normalizer': None, 'parse_special': True, 'add_special_tokens': False,
        'runtime_regex': _QWEN35_RUNTIME_REGEX, 'gguf_sha256': assets['gguf']['sha256'],
        'manifest_sha256': assets['manifest']['sha256'],
        'gguf_tokenizer_metadata_sha256': content_digest(gguf),
        'derived_tokenizer_sha256': content_digest(derived),
        'original_tokenizer_sha256': _sha(Path(spec['path']) / 'tokenizer.json'),
        'token_count': len(tokens), 'merge_count': len(model['merges']),
        'added_token_count': len(derived['added_tokens']),
        'encoder_token_count': len(expected_vocabulary),
        'loader_control_overrides': control_overrides,
        'unused_token_ids_sha256': content_digest([index for index, kind in enumerate(types) if kind == 5]),
        'provider_implementation_sha256': _sha(__file__)}
    return CompatibleLocalTokenizer(renderer, encoder, identity)


def local_metadata_transport(route, payload=None):
    """Fixed loopback metadata only. This function never sends raw or calls chat."""
    import urllib.request
    if route not in ('/api/tags', '/api/show') or (route == '/api/tags' and payload is not None):
        raise ValueError('unapproved local metadata route')
    if route == '/api/show' and (not isinstance(payload, dict) or set(payload) != {'model'} or payload['model'] not in MODEL_DIGESTS):
        raise ValueError('local model metadata request must contain only one approved model name')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('local judge metadata redirects forbidden')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(REVIEW_RUNTIME['endpoint'] + route, data=data,
        headers={'Content-Type': 'application/json'}, method='GET' if data is None else 'POST')
    with opener.open(request, timeout=120) as stream:
        return json.loads(stream.read())


class LocalTokenCounter:
    def __init__(self, tokenizers):
        self.tokenizers = tokenizers

    def render(self, model, messages):
        if model not in self.tokenizers:
            raise ValueError('no frozen tokenizer for requested local judge')
        tokenizer = self.tokenizers[model]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False,
            add_generation_prompt=True, enable_thinking=False)
        if not isinstance(prompt, str) or not prompt:
            raise ValueError('local tokenizer did not render the frozen non-thinking prompt')
        token_ids = tokenizer.encode(prompt, add_special_tokens=False)
        if not isinstance(token_ids, list) or not token_ids or any(type(value) is not int for value in token_ids):
            raise ValueError('local tokenizer did not provide a complete exact token sequence')
        return {'prompt': prompt, 'token_ids': token_ids}

    def __call__(self, model, messages):
        return len(self.render(model, messages)['token_ids'])


def verify_local_deployment(*, sources, binding, allow_local_metadata=False,
                            transport=None, tokenizer_factory=None):
    if not allow_local_metadata:
        raise ValueError('explicit local metadata verification authorization required; no requests sent')
    validate_tokenizer_sources(sources)
    synthetic = transport is not None or tokenizer_factory is not None
    transport = local_metadata_transport if transport is None else transport
    factory = _load_local_tokenizer if tokenizer_factory is None else tokenizer_factory
    isolation = probe_review_isolation()
    installed = transport('/api/tags')
    tokenizers, identities = {}, {}
    for model, spec in sources.items():
        assets = _check_assets(spec)
        matches = [item for item in installed.get('models', []) if item.get('name') == model]
        if len(matches) != 1 or matches[0].get('digest', '').removeprefix('sha256:') != MODEL_DIGESTS[model]:
            raise ValueError('approved local judge installed model digest drift')
        info = transport('/api/show', {'model': model})
        template = info.get('template')
        if not isinstance(template, str) or hashlib.sha256(template.encode()).hexdigest() != spec['ollama_template_sha256']:
            raise ValueError('approved local judge chat template drift')
        tokenizers[model] = factory(spec)
        if tokenizer_factory is None:
            tokenizers[model] = build_compatible_tokenizer(spec, tokenizers[model])
        equivalence = verify_tokenizer_equivalence_audit(model, spec, tokenizers[model])
        identities[model] = {'model_sha256': MODEL_DIGESTS[model], 'template_sha256': spec['ollama_template_sha256'],
            'tokenizer_sources_sha256': content_digest(spec), 'files': assets,
            'libraries': spec['libraries'], 'equivalence_audit_sha256': equivalence['sha256'],
            'equivalence_audit': equivalence,
            'equivalence_trust': 'operator-supplied-independently-reviewed-mapping'}
    counter = LocalTokenCounter(tokenizers)
    # Verify the counter is usable without any model inference or restricted raw.
    for model in tokenizers:
        if counter(model, [{'role': 'user', 'content': 'synthetic counter verification'}]) <= 0:
            raise ValueError('local tokenizer counter verification failed')
    evidence = {'schema_version': 'tensile-local-review-deployment/v1', 'binding': binding,
        'runtime': REVIEW_RUNTIME, 'models': identities, 'isolation': isolation,
        'implementation_sha256': _sha(__file__), 'synthetic': synthetic,
        'real_model_deployment_verified': not synthetic}
    return {**evidence, 'sha256': content_digest(evidence)}, counter


def _ordinary_audit(path):
    path = Path(path)
    if not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise ValueError('tokenizer audit/reference must be an ordinary explicit local file')
    return path


def verify_tokenizer_equivalence_audit(model, spec, tokenizer):
    """Check a reviewed mapping and its golden cases, not prove GGUF algorithms.

    The future operator is responsible for the independent reviewer's identity,
    source and GGUF tokenization evidence. We verify exact binding, referenced
    bytes and local golden cases; a boolean/equivalence assertion is insufficient.
    """
    from datetime import datetime
    descriptor = spec['tokenizer_equivalence_audit']
    path = _ordinary_audit(descriptor['path'])
    if _sha(path) != descriptor['sha256']:
        raise ValueError('reviewed tokenizer equivalence audit byte drift')
    value = json.loads(path.read_bytes())
    compatibility = getattr(tokenizer, 'compatibility_counter_identity', None)
    required = {'schema_version', 'purpose', 'reviewer', 'reviewed_at', 'review_source',
        'binding', 'gguf_counter_source', 'basis', 'golden_cases'}
    if compatibility is not None:
        required.add('compatibility_assets')
    if (not isinstance(value, dict) or set(value) != required
        or value['schema_version'] != ('tensile-reviewed-tokenizer-equivalence/v2' if compatibility is not None
                                            else 'tensile-reviewed-tokenizer-equivalence/v1')
        or value['purpose'] != 'precall-context-budget'
        or not isinstance(value['reviewer'], dict) or set(value['reviewer']) != {'id', 'role'}
        or not isinstance(value['reviewer']['id'], str) or not value['reviewer']['id'].strip()
        or value['reviewer']['role'] != 'independent-tokenizer-auditor'
        or not isinstance(value['review_source'], str) or not value['review_source'].strip()):
        raise ValueError('reviewed tokenizer mapping requires named independent reviewer/source/purpose')
    try:
        stamp = datetime.fromisoformat(value['reviewed_at'])
        if stamp.tzinfo is None:
            raise ValueError('timezone required')
    except (ValueError, TypeError) as exc:
        raise ValueError('reviewed tokenizer mapping requires explicit review time') from exc
    actual_special = {'add_bos_token': getattr(tokenizer, 'add_bos_token', None),
        'add_eos_token': getattr(tokenizer, 'add_eos_token', None),
        'special_tokens_map_sha256': content_digest(getattr(tokenizer, 'special_tokens_map', {}))}
    binding = {'model': model, 'model_sha256': MODEL_DIGESTS[model],
        'upstream_source': spec['upstream_source'], 'upstream_revision': spec['upstream_revision'],
        'tokenizer_files': spec['files'], 'libraries': spec['libraries'],
        'provider_implementation_sha256': spec['implementation_sha256'],
        'format': 'hf-rendered-raw-generate-v1', 'enable_thinking': False,
        'add_special_tokens': False, 'special_token_behavior': actual_special}
    if compatibility is not None:
        binding['compatibility_counter'] = compatibility
    if value['binding'] != binding:
        raise ValueError('reviewed GGUF/HF tokenizer mapping binding or special-token behavior drift')
    source = value['gguf_counter_source']
    if (not isinstance(source, dict) or set(source) != {'method', 'implementation', 'model_sha256'}
        or source['method'] != 'independent-gguf-tokenizer' or source['model_sha256'] != MODEL_DIGESTS[model]
        or not isinstance(source['implementation'], dict) or set(source['implementation']) != {'name', 'version', 'sha256'}
        or any(not isinstance(source['implementation'][key], str) or not source['implementation'][key].strip() for key in ('name', 'version'))
        or not isinstance(source['implementation'].get('sha256'), str) or len(source['implementation']['sha256']) != 64
        or any(c not in '0123456789abcdef' for c in source['implementation']['sha256'])):
        raise ValueError('reviewed mapping must identify independent GGUF counter evidence')
    basis = value['basis']
    if not isinstance(basis, list) or not basis:
        raise ValueError('reviewed tokenizer mapping requires inspectable audit basis')
    basis_snapshots = []
    for reference in basis:
        if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256', 'description'}
            or not isinstance(reference['description'], str) or not reference['description'].strip()
            or _sha(_ordinary_audit(reference['path'])) != reference['sha256']):
            raise ValueError('reviewed tokenizer mapping audit basis drift')
        import base64
        basis_snapshots.append({'path': reference['path'], 'sha256': reference['sha256'],
            'content_base64': base64.b64encode(_ordinary_audit(reference['path']).read_bytes()).decode()})
    cases = value['golden_cases']
    if not isinstance(cases, list) or not cases:
        raise ValueError('reviewed tokenizer mapping requires frozen GGUF golden cases')
    counter = LocalTokenCounter({model: tokenizer})
    ids = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {'id', 'messages', 'rendered_prompt_sha256', 'token_ids'}
            or not isinstance(case['id'], str) or not case['id'] or case['id'] in ids
            or not isinstance(case['messages'], list) or not case['messages']
            or any(not isinstance(item, dict) or set(item) != {'role', 'content'}
                or item['role'] not in ('system', 'user', 'assistant') or not isinstance(item['content'], str) for item in case['messages'])):
            raise ValueError('reviewed tokenizer mapping golden-case schema invalid')
        ids.add(case['id'])
        rendered = counter.render(model, case['messages'])
        if (hashlib.sha256(rendered['prompt'].encode()).hexdigest() != case['rendered_prompt_sha256']
            or rendered['token_ids'] != case['token_ids']):
            raise ValueError('reviewed GGUF/HF golden tokenization case mismatch')
    return {'sha256': descriptor['sha256'], 'reviewer': value['reviewer'],
        'reviewed_at': value['reviewed_at'], 'review_source': value['review_source'],
        'golden_case_count': len(cases), 'reviewed_artifact': value, 'basis_snapshots': basis_snapshots}
