"""Actual A/B frozen source records retain meaning without acquiring new admission."""
from __future__ import annotations

import hashlib
import json
import subprocess
import types
from pathlib import Path

import pytest

from finetune import eval_run as runtime
from test_eval_development_wiring import _config
from test_eval_run import _formal_eval_fixture, _fake_formal_runtime


def _ab_runtime():
    source = subprocess.check_output(["git", "show", "30e96f97:finetune/eval_run.py"], cwd=runtime.ROOT)
    module = types.ModuleType("ab_frozen_eval_run")
    module.__file__ = str(runtime.ROOT / "finetune/eval_run.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    old_sha = module._sha256
    frozen_digest = hashlib.sha256(source).hexdigest()
    module._sha256 = lambda path: frozen_digest if Path(path) == runtime.ROOT / "finetune/eval_run.py" else old_sha(path)
    return module, frozen_digest


@pytest.mark.parametrize("scorer", ["strict-v4.1", "semantic-v4.1"])
def test_actual_ab_runtime_record_can_revalidate_export_but_not_gain_new_admission(tmp_path, monkeypatch, scorer):
    from versioning.registry import open_registry_store, _run_eval_gate, finalize_model_evaluation, PromotionGateRejected
    from versioning.mlflow_eval import open_eval_store, get_eval_run
    root, media, model, config = _formal_eval_fixture(tmp_path)
    if scorer == "semantic-v4.1":
        config = _config(config)
    legacy, frozen_digest = _ab_runtime()
    calls = _fake_formal_runtime(monkeypatch)
    legacy.load_model = runtime.load_model
    legacy.run_model_on_video_detailed = runtime.run_model_on_video_detailed
    kwargs = dict(root=root, eval_version="eval-v4.1-r1", model_version=model.model_id,
        model_version_number=model.version, data_version="data-v4.1-r2", config=config,
        git_commit="synthetic", media_root=media)
    legacy.prepare_versioned_evaluation(**kwargs)
    legacy.execute_versioned_evaluation(root=root, eval_version=kwargs["eval_version"])
    assert len(calls) == 3
    frozen = runtime.verify_versioned_evaluation(root=root, eval_version=kwargs["eval_version"])
    assert frozen["implementation_sha256"]["finetune/eval_run.py"] == frozen_digest
    runtime.prepare_versioned_evaluation(**kwargs)
    document = json.loads(runtime.export_versioned_evaluation(root=root, eval_version=kwargs["eval_version"]).read_bytes())
    assert document.get("scoring_protocol", "strict-v4.1") == scorer
    assert get_eval_run(open_eval_store(root / "workspace/mlflow"), kwargs["eval_version"]).purpose == "legacy"
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    if scorer == "semantic-v4.1":
        with pytest.raises(PromotionGateRejected, match="development semantic"):
            _run_eval_gate(registry, kwargs["eval_version"], require_passed=False)
    else:
        with pytest.raises(PromotionGateRejected, match="new admission"):
            finalize_model_evaluation(registry, model.model_id, eval_id=kwargs["eval_version"])
    # Only this audited adapter's exact current bytes are trusted.
    old_sha = runtime._sha256
    monkeypatch.setattr(runtime, "_sha256", lambda path: "f" * 64 if Path(path) == runtime.ROOT / "finetune/eval_run.py" else old_sha(path))
    with pytest.raises(ValueError, match="drift|implementation"):
        runtime.verify_versioned_evaluation(root=root, eval_version=kwargs["eval_version"])
    with pytest.raises(ValueError, match="implementation"):
        runtime.export_versioned_evaluation(root=root, eval_version=kwargs["eval_version"])
