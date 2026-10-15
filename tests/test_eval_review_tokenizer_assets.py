"""Synthetic protection for separately frozen upstream chat templates."""
import hashlib
import json
from pathlib import Path

import pytest

from finetune import eval_review_deployment as deployment
from finetune.eval_review import MODEL_DIGESTS


def spec_for(root):
    return {
        'path': str(root), 'upstream_source': 'synthetic/upstream', 'upstream_revision': 'f' * 40,
        'files': {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'size_bytes': p.stat().st_size}
                  for p in root.iterdir()},
        'libraries': {name: {'version': 'synthetic', 'code_sha256': 'a' * 64}
                      for name in ('transformers', 'tokenizers')},
        'implementation_sha256': hashlib.sha256(Path(deployment.__file__).read_bytes()).hexdigest(),
        'ollama_template_sha256': 'b' * 64,
        'tokenizer_equivalence_audit': {'path': str(root.parent / 'not-a-real-audit.json'), 'sha256': 'c' * 64},
    }


def test_external_template_is_frozen_as_asset_and_byte_drift_rejected(tmp_path):
    root = tmp_path.resolve() / 'tokenizer'
    root.mkdir()
    (root / 'tokenizer_config.json').write_text(json.dumps({'chat_template': 'inline synthetic'}))
    template = root / 'chat_template.jinja'
    template.write_text('external synthetic template')
    spec = spec_for(root)
    sources = {model: {**spec, 'model_sha256': digest} for model, digest in MODEL_DIGESTS.items()}
    assert deployment.validate_tokenizer_sources(sources) == sources
    assert deployment._check_assets(spec) == spec['files']
    template.write_text('different external template')
    with pytest.raises(ValueError, match='drift'):
        deployment._check_assets(spec)


def test_external_template_symlink_cannot_replace_frozen_bytes(tmp_path):
    root = tmp_path.resolve() / 'tokenizer'
    root.mkdir()
    template = root / 'chat_template.jinja'
    template.write_text('synthetic')
    spec = spec_for(root)
    outside = root.parent / 'outside'
    outside.write_text('synthetic')
    template.unlink()
    template.symlink_to(outside)
    with pytest.raises(ValueError, match='symlink'):
        deployment._check_assets(spec)


def test_allowing_jinja_does_not_admit_arbitrary_python_assets(tmp_path):
    root = tmp_path.resolve() / 'tokenizer'
    root.mkdir()
    (root / 'arbitrary.py').write_text('not executed')
    spec = spec_for(root)
    sources = {model: {**spec, 'model_sha256': digest} for model, digest in MODEL_DIGESTS.items()}
    with pytest.raises(ValueError, match='approved local tokenizer assets'):
        deployment.validate_tokenizer_sources(sources)
