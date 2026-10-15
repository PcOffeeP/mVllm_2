"""Public wiring preserves explicit model-call and controlled-session authority."""
from pathlib import Path

import pytest

from versioning.cli import main


def test_review_verification_and_execution_have_distinct_explicit_permissions(tmp_path, monkeypatch):
    from finetune import eval_holdout
    calls = []
    monkeypatch.setattr(eval_holdout, "verify_holdout_review_deployment",
        lambda **kwargs: calls.append(("verify", kwargs)) or {"verified": False})
    monkeypatch.setattr(eval_holdout, "run_holdout_review",
        lambda **kwargs: calls.append(("run", kwargs)) or {"synthetic": True})
    prefix = ["eval", "review_verify", "eval-v4.1-r1", "--root", str(tmp_path)]
    assert main(prefix) == 0
    assert calls[-1][1]["allow_local_metadata"] is False
    assert main(prefix + ["--allow-local-review-metadata"]) == 0
    assert calls[-1][1]["allow_local_metadata"] is True
    before = list(calls)
    assert main(prefix + ["--allow-real-model-calls"]) == 2
    assert calls == before
    assert main(["eval", "review_run", "eval-v4.1-r1", "--root", str(tmp_path)]) == 0
    assert calls[-1][1]["allow_real_model_calls"] is False


@pytest.mark.parametrize("flag", ["--allow-real-model-calls", "--allow-local-review-metadata"])
def test_performance_actions_never_implicitly_authorize_review_calls(tmp_path, monkeypatch, flag):
    from finetune import eval_performance
    monkeypatch.setattr(eval_performance, "execute_performance_evaluation", lambda **kwargs: pytest.fail("execution escaped purpose gate"))
    assert main(["eval", "performance_run", "eval-v4.1-r1", "--root", str(tmp_path),
        "--performance-evidence", str(tmp_path / "events.json"), flag]) == 2


def test_performance_import_and_controlled_serve_use_separate_explicit_entries(tmp_path, monkeypatch):
    from finetune import eval_performance
    from versioning import performance
    calls = []
    monkeypatch.setattr(eval_performance, "execute_performance_evaluation",
        lambda **kwargs: calls.append(("import", kwargs)) or {"synthetic": True})
    monkeypatch.setattr(performance, "run_performance_session",
        lambda **kwargs: calls.append(("serve", kwargs)) or {"synthetic": True})
    evidence = tmp_path / "events.json"
    common = ["eval-v4.1-r1", "--root", str(tmp_path), "--performance-evidence", str(evidence)]
    assert main(["eval", "performance_run", *common]) == 0
    assert [kind for kind, _ in calls] == ["import"]
    assert calls[-1][1]["evidence_path"] == Path(evidence)
    assert main(["eval", "performance_serve", *common]) == 2
    assert len(calls) == 1
    assert main(["eval", "performance_serve", *common, "--executor", "synthetic-owner",
        "--session-id", "synthetic-session", "--port", "40123"]) == 0
    assert calls[-1] == ("serve", {"root": tmp_path, "eval_version": "eval-v4.1-r1",
        "executor": "synthetic-owner", "session_id": "synthetic-session", "port": 40123,
        "evidence_path": evidence})
