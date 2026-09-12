from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from pipeline.prompt_control import (
    PromptControlError,
    build_experiment_contract,
    build_model_messages,
    load_experiment_contract,
    load_prompt_revision,
    publish_prompt,
    validate_active_prompt,
    validate_model_bundle_prompt,
)
from pipeline.prompt_control.core import sha256_file

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "pipeline/prompt_control/active_prompt.yaml"
REVISION = ROOT / "pipeline/prompt_registry/v4.1-concise-evidence-json-v2"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _experiment(tmp_path: Path) -> Path:
    value = build_experiment_contract(
        prompt_revision_dir=REVISION,
        release_identity={
            "release_id": "release-test",
            "release_manifest_sha256": "a" * 64,
            "training_candidates_sha256": "b" * 64,
        },
        sampling_identity={
            "sampling_id": "sampling-test",
            "sampling_manifest_sha256": "c" * 64,
            "candidate_sequence_sha256": "d" * 64,
            "seed": 3411,
        },
        generation={
            "do_sample": False,
            "num_beams": 1,
            "temperature": 0.0,
            "max_new_tokens": 256,
        },
    )
    path = tmp_path / "experiment_contract.json"
    _write_json(path, value)
    return path


def test_active_prompt_and_committed_revision_are_valid() -> None:
    active = validate_active_prompt(ACTIVE)
    prompt, manifest = load_prompt_revision(REVISION)

    assert active == prompt
    assert manifest["revision_id"] == "v4.1-concise-evidence-json-v2"
    assert manifest["source_path"] == "pipeline/prompt_control/active_prompt.yaml"
    assert manifest["prompt_yaml_sha256"] == sha256_file(REVISION / "prompt.yaml")
    assert active["user_prompt"] == (
        "请根据这段拉伸试验视频，判断试样是否发生断裂，"
        "并给出相应的断裂模式和断裂位置。"
    )
    assert '禁止字符串 "null"' in active["system_prompt"]


def test_publish_is_idempotent_and_refuses_revision_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "active_prompt.yaml"
    source.write_text(ACTIVE.read_text(encoding="utf-8"), encoding="utf-8")
    registry = tmp_path / "registry"
    now = datetime(2026, 7, 28, tzinfo=timezone.utc)

    first, first_manifest = publish_prompt(
        source,
        registry_root=registry,
        now=now,
        code_commit="test-commit",
    )
    repeated, repeated_manifest = publish_prompt(
        source,
        registry_root=registry,
        now=now,
        code_commit="test-commit",
    )

    assert repeated == first
    assert repeated_manifest == first_manifest

    changed = yaml.safe_load(source.read_text(encoding="utf-8"))
    changed["system_prompt"] += " drift"
    source.write_text(
        yaml.safe_dump(changed, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(PromptControlError, match="拒绝覆盖"):
        publish_prompt(
            source,
            registry_root=registry,
            code_commit="test-commit",
        )


def test_experiment_contract_is_self_contained_and_fail_closed(
    tmp_path: Path,
) -> None:
    path = _experiment(tmp_path)
    experiment = load_experiment_contract(path)
    prompt = experiment["prompt"]

    assert prompt["system_prompt"]
    assert prompt["user_prompt"]
    assert prompt["output_fields"] == [
        "clip_state",
        "fracture_mechanism",
        "fracture_site",
        "special_case",
    ]
    assert build_model_messages(experiment)[1]["content"].startswith("<video>\n")

    bundle = {
        "schema_version": "tensile-vlm-v4.1-model-bundle/v1",
        "experiment_contract_sha256": experiment["experiment_contract_sha256"],
        "prompt_revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt["prompt_content_sha256"],
        "response_fields": prompt["output_fields"],
    }
    validate_model_bundle_prompt(bundle, experiment)

    drifted_bundle = {**bundle, "prompt_content_sha256": "0" * 64}
    with pytest.raises(PromptControlError, match="身份不匹配"):
        validate_model_bundle_prompt(drifted_bundle, experiment)

    drifted = copy.deepcopy(experiment)
    drifted["prompt"]["system_prompt"] += " drift"
    _write_json(path, drifted)
    with pytest.raises(PromptControlError, match="自哈希"):
        load_experiment_contract(path)


@pytest.mark.parametrize("arguments", [[], ["validate", "--source", "missing.yaml"], ["publish", "--source", "missing.yaml"], ["--legacy"]])
def test_retired_prompt_cli_stops_before_parsing(arguments, monkeypatch, capsys):
    from pipeline.prompt_control import __main__ as cli
    import sys
    monkeypatch.setattr(cli, "parse_args", lambda: pytest.fail("legacy parsing reached"))
    monkeypatch.setattr(cli, "publish_prompt", lambda *a, **kw: pytest.fail("legacy publication reached"))
    monkeypatch.setattr(sys, "argv", ["prompt_control", *arguments])
    assert cli.main() == 2
    assert "python -m versioning prompt" in capsys.readouterr().err


def test_retired_prompt_script_and_module_do_not_publish(tmp_path):
    import subprocess
    import sys
    for prefix in ([sys.executable, str(ROOT / "pipeline/prompt_control/__main__.py")],
                   [sys.executable, "-m", "pipeline.prompt_control"]):
        for args, expected in ((["publish", "--source", str(ACTIVE), "--registry-root", str(tmp_path / "registry")], 2),
                               (["--help"], 0), (["-h"], 0), (["--help", "--legacy"], 2)):
            result = subprocess.run(prefix + args, cwd=ROOT, text=True, capture_output=True)
            assert result.returncode == expected, result.stderr
            assert "python -m versioning prompt" in result.stdout + result.stderr
            assert not (tmp_path / "registry").exists()
