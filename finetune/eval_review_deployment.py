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
    required = {'schema_version', 'purpose', 'reviewer', 'reviewed_at', 'review_source',
        'binding', 'gguf_counter_source', 'basis', 'golden_cases'}
    if (not isinstance(value, dict) or set(value) != required
        or value['schema_version'] != 'tensile-reviewed-tokenizer-equivalence/v1'
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
