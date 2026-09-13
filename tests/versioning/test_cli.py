"""B10 统一 CLI 的命令结构、缺参和错误边界。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from versioning.cli import main


def test_top_level_help_lists_all_domains(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in (
        "data",
        "prompt",
        "train",
        "eval",
        "model",
        "backup",
        "migration",
    ):
        assert command in output


@pytest.mark.parametrize(
    "argv",
    [
        ["data", "release"],
        ["data", "release_validate"],
        ["prompt", "create"],
        ["train", "create", "train-v4.1-r1"],
        ["eval", "create", "eval-v4.1-r1"],
        ["model", "register", "model-v4.1-r1"],
    ],
)
def test_incomplete_commands_stop_with_usage_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    message = capsys.readouterr().err
    assert "缺少必填参数" in message or "实际执行器" in message


def test_unknown_data_stage_is_fail_closed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "latest"]) == 1
    assert "未知 stage" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["train", "fold-start", "train-v4.1-r1"],
        ["eval", "fold-start", "eval-v4.1-r1"],
        ["eval", "summary", "eval-v4.1-r1"],
    ],
)
def test_non_create_usage_errors_do_not_initialize_store(
    tmp_path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    assert main([*argv, "--root", str(root)]) == 2
    message = capsys.readouterr().err
    assert "缺少必填参数" in message or "实际执行器" in message
    assert not (root / "workspace" / "mlflow").exists()


def _write_migration_mapping(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prompt_item = {
        "source_legacy_id": "legacy-prompt",
        "candidate_target_identity": "prompt-v4.1-r1",
        "target_path": "records/prompts/prompt-v4.1-r1.yaml",
        "status": "user_confirmed",
    }
    data_items = [
        {
            "source_legacy_id": "legacy-data",
            "candidate_target_identity": "data-v4.1-r1",
            "target_path": "data/releases/data-v4.1-r1/release.yaml",
            "target_status": "active",
            "status": "user_confirmed",
        }
    ]
    path.write_text(
        yaml.safe_dump(
            {
                "mapping_schema": "tensile-migration/object-mapping/v1",
                "prompt_mapping": {"items": [prompt_item]},
                "data_mapping": {"items": data_items},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return prompt_item, data_items


@pytest.mark.parametrize(
    "action,required_option",
    [
        ("prompt-precheck", "--mapping"),
        ("prompt-migrate", "--mapping"),
        ("data-precheck", "--mapping"),
        ("data-migrate", "--mapping"),
        ("history-build", "--entries"),
        ("history-write", "--entries"),
    ],
)
def test_migration_cli_requires_explicit_input_file(
    action: str,
    required_option: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["migration", action, "--root", str(tmp_path)]) == 2
    assert required_option in capsys.readouterr().err


@pytest.mark.parametrize(
    "action",
    [
        "prompt-precheck",
        "prompt-migrate",
        "data-precheck",
        "data-migrate",
        "history-build",
        "history-write",
    ],
)
def test_migration_cli_requires_explicit_root_before_loading_inputs(
    action: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    option = "--entries" if action.startswith("history-") else "--mapping"
    input_path = tmp_path / "unused.yaml"

    assert main(["migration", action, option, str(input_path)]) == 2
    assert "--root" in capsys.readouterr().err


@pytest.mark.parametrize(
    "action",
    [
        "prompt-precheck",
        "prompt-migrate",
        "data-precheck",
        "data-migrate",
        "history-build",
        "history-write",
    ],
)
@pytest.mark.parametrize("empty_root", ["", "   "])
def test_migration_cli_rejects_empty_explicit_root_before_loading_inputs(
    action: str,
    empty_root: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    option = "--entries" if action.startswith("history-") else "--mapping"
    input_path = tmp_path / "unused.yaml"

    assert (
        main(
            [
                "migration",
                action,
                "--root",
                empty_root,
                option,
                str(input_path),
            ]
        )
        == 2
    )
    assert "--root 不得为空" in capsys.readouterr().err


@pytest.mark.parametrize(
    "action,api_name,expected_result",
    [
        ("prompt-precheck", "precheck_prompt_migration", {"status": "ready"}),
        ("prompt-migrate", "migrate_prompt", "prompt-v4.1-r1"),
        ("data-precheck", "precheck_data_migration", {"status": "ready"}),
        (
            "data-migrate",
            "migrate_data",
            (Path("migration_receipts/data-v4.1-r1.receipt.yaml"),),
        ),
    ],
)
def test_migration_cli_dispatches_explicit_object_mapping_section(
    action: str,
    api_name: str,
    expected_result: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from versioning import migration as migration_api

    mapping_path = tmp_path / "object-mapping.yaml"
    prompt_item, data_items = _write_migration_mapping(mapping_path)
    calls: list[tuple[Path, Any]] = []

    def fake_api(root: Path, value: Any) -> Any:
        calls.append((root, value))
        return expected_result

    monkeypatch.setattr(migration_api, api_name, fake_api)

    assert (
        main(
            [
                "migration",
                action,
                "--root",
                str(tmp_path),
                "--mapping",
                str(mapping_path),
            ]
        )
        == 0
    )
    expected_input = prompt_item if action.startswith("prompt-") else data_items
    assert calls == [(tmp_path, expected_input)]
    assert json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    "action,api_name,expected_result",
    [
        ("history-build", "build_history_summary", {"entries": []}),
        ("history-write", "write_history_summary", Path("history-summary.yaml")),
    ],
)
def test_migration_cli_dispatches_declared_history_entries_without_scanning(
    action: str,
    api_name: str,
    expected_result: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from versioning import migration as migration_api

    entries = [
        {
            "kind": "prepare_only_run",
            "source_legacy_id": "declared-run",
            "status": "user_confirmed",
        }
    ]
    entries_path = tmp_path / "history-entries.yaml"
    entries_path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    calls: list[tuple[Path, Any]] = []

    def fake_api(root: Path, value: Any) -> Any:
        calls.append((root, value))
        return expected_result

    monkeypatch.setattr(migration_api, api_name, fake_api)

    assert (
        main(
            [
                "migration",
                action,
                "--root",
                str(tmp_path),
                "--entries",
                str(entries_path),
            ]
        )
        == 0
    )
    assert calls == [(tmp_path, entries)]
    assert json.loads(capsys.readouterr().out)


def test_migration_cli_rejects_wrong_mapping_schema_before_domain_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from versioning import migration as migration_api

    mapping_path = tmp_path / "object-mapping.yaml"
    mapping_path.write_text(
        yaml.safe_dump(
            {
                "mapping_schema": "tensile-migration/object-mapping/v0",
                "prompt_mapping": {"items": [{}]},
            }
        ),
        encoding="utf-8",
    )

    def unexpected_call(root: Path, value: Any) -> Any:
        raise AssertionError("invalid mapping must not reach migration domain")

    monkeypatch.setattr(
        migration_api, "precheck_prompt_migration", unexpected_call
    )

    assert (
        main(
            [
                "migration",
                "prompt-precheck",
                "--root",
                str(tmp_path),
                "--mapping",
                str(mapping_path),
            ]
        )
        == 1
    )
    assert "mapping_schema" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["prompt-precheck", "data-precheck"])
def test_migration_cli_blocked_precheck_reports_reasons_and_exits_nonzero(
    action: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mapping_path = tmp_path / "object-mapping.yaml"
    _write_migration_mapping(mapping_path)
    raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    section_name = "prompt_mapping" if action.startswith("prompt-") else "data_mapping"
    raw[section_name]["items"][0]["candidate_target_identity"] = "LATEST"
    mapping_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert (
        main(
            [
                "migration",
                action,
                "--root",
                str(tmp_path),
                "--mapping",
                str(mapping_path),
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert any("禁止 LATEST" in reason for reason in report["reasons"])


@pytest.mark.parametrize(
    "action,document",
    [
        (
            "prompt-precheck",
            "mapping_schema: tensile-migration/object-mapping/v1\n"
            "mapping_schema: tensile-migration/object-mapping/v1\n"
            "prompt_mapping:\n"
            "  items: []\n",
        ),
        (
            "prompt-precheck",
            "mapping_schema: tensile-migration/object-mapping/v1\n"
            "prompt_mapping:\n"
            "  items: []\n"
            "  items: []\n",
        ),
        (
            "prompt-precheck",
            "mapping_schema: tensile-migration/object-mapping/v1\n"
            "prompt_mapping:\n"
            "  items:\n"
            "    - source_legacy_id: legacy-prompt\n"
            "      candidate_target_identity: LATEST\n"
            "      candidate_target_identity: prompt-v4.1-r1\n"
            "      target_path: records/prompts/prompt-v4.1-r1.yaml\n"
            "      status: pending_user_check\n"
            "      status: user_confirmed\n",
        ),
        (
            "data-precheck",
            "mapping_schema: tensile-migration/object-mapping/v1\n"
            "data_mapping:\n"
            "  items:\n"
            "    - source_legacy_id: legacy-data\n"
            "      candidate_target_identity: LATEST\n"
            "      candidate_target_identity: data-v4.1-r1\n"
            "      target_path: data/releases/data-v4.1-r1/release.yaml\n"
            "      target_status: active\n"
            "      status: pending_user_check\n"
            "      status: user_confirmed\n",
        ),
        (
            "history-build",
            "- kind: prepare_only_run\n"
            "  source_legacy_id: declared-run\n"
            "  status: pending_user_check\n"
            "  status: user_confirmed\n",
        ),
    ],
)
def test_migration_cli_rejects_duplicate_yaml_keys(
    action: str,
    document: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    option = "--entries" if action.startswith("history-") else "--mapping"
    input_path = tmp_path / "ambiguous.yaml"
    input_path.write_text(document, encoding="utf-8")

    assert (
        main(
            [
                "migration",
                action,
                "--root",
                str(tmp_path),
                option,
                str(input_path),
            ]
        )
        == 1
    )
    assert "重复键" in capsys.readouterr().err


def test_migration_cli_builds_then_publishes_history_summary_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = [
        {
            "kind": "prepare_only_run",
            "source_legacy_id": "declared-run",
            "status": "user_confirmed",
        }
    ]
    entries_path = tmp_path / "history-entries.yaml"
    entries_path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    target = (
        tmp_path
        / "docs"
        / "results"
        / "version-control-migration"
        / "history-summary.yaml"
    )
    command = [
        "migration",
        "history-build",
        "--root",
        str(tmp_path),
        "--entries",
        str(entries_path),
    ]

    assert main(command) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["entries"][0]["original_id"] == "declared-run"
    assert not target.exists()

    command[1] = "history-write"
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out) == str(target)
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == built

    assert main(command) == 1
    assert "拒绝覆盖" in capsys.readouterr().err


def test_train_prepare_routes_all_explicit_inputs(tmp_path, monkeypatch, capsys):
    from finetune import train_prepare_run
    seen = {}
    config = tmp_path / "folds.yaml"
    config.write_text(yaml.safe_dump({f"fold{i}": {"seed": i} for i in range(3)}))
    environment = tmp_path / "environment.yaml"
    environment.write_text("python: fixture\n")
    def prepare(**kwargs):
        seen.update(kwargs)
        return tmp_path / "input"
    monkeypatch.setattr(train_prepare_run, "prepare_versioned_run", prepare)
    assert main(["train", "prepare", "train-v4.1-r1", "--root", str(tmp_path),
        "--data-version", "data-v4.1-r2", "--prompt-version", "prompt-v4.1-r1",
        "--config", str(config), "--environment", str(environment),
        "--git-commit", "commit", "--media-root", str(tmp_path / "media")]) == 0
    assert seen["fold_configs"]["fold2"]["seed"] == 2
    assert seen["media_root"] == tmp_path / "media"
    assert seen["data_version"] == "data-v4.1-r2"


def test_train_run_and_validate_route_to_frozen_inputs(tmp_path, monkeypatch):
    from finetune import train_prepare_run
    calls = []
    monkeypatch.setattr(train_prepare_run, "execute_versioned_run", lambda **kw: calls.append(("run", kw)))
    monkeypatch.setattr(train_prepare_run, "verify_versioned_run", lambda **kw: calls.append(("validate", kw)))
    for action in ("run", "validate"):
        assert main(["train", action, "train-v4.1-r1", "--root", str(tmp_path)]) == 0
    assert [item[0] for item in calls] == ["run", "validate"]
    assert all(kw["train_version"] == "train-v4.1-r1" for _, kw in calls)


def test_backup_transfer_requires_host_source_and_digest(tmp_path, capsys):
    assert main(["backup", "transfer", "--root", str(tmp_path),
                 "--backup-root", str(tmp_path / "received")]) == 2
    message = capsys.readouterr().err
    assert "缺少必填参数" in message or "实际执行器" in message


def test_backup_transfer_cli_routes_explicit_arguments(tmp_path, monkeypatch, capsys):
    from versioning import cli
    calls = []
    monkeypatch.setattr(cli, "transfer_backup", lambda **kwargs: calls.append(kwargs) or {"objects": []})
    assert main(["backup", "transfer", "--root", str(tmp_path),
        "--backup-root", str(tmp_path / "received"), "--ssh-host", "fixture-host",
        "--source-backup-root", "/remote/snapshot", "--catalog-sha256", "a" * 64]) == 0
    assert calls == [{"ssh_host": "fixture-host", "source_backup_root": Path("/remote/snapshot"),
                     "backup_root": tmp_path / "received", "catalog_sha256": "a" * 64}]
    assert json.loads(capsys.readouterr().out) == {"objects": []}


@pytest.mark.parametrize('domain,actions', [
    ('train', ('create', 'fold-start', 'fold-end', 'summary', 'complete')),
    ('eval', ('create', 'fold-start', 'fold-end', 'aggregate', 'summary', 'complete', 'manifest')),
])
def test_manual_execution_commands_refused_before_store(tmp_path, capsys, domain, actions):
    for action in actions:
        assert main([domain, action, f'{domain}-v4.1-r1', '--root', str(tmp_path)]) == 2
        assert '实际执行器' in capsys.readouterr().err
        assert not (tmp_path / 'workspace/mlflow').exists()


def test_train_run_routes_explicit_fold_and_other_actions_reject_it(tmp_path, monkeypatch):
    from finetune import train_prepare_run
    calls = []
    monkeypatch.setattr(train_prepare_run, "execute_versioned_run", lambda **kw: calls.append(kw))
    assert main(["train", "run", "train-v4.1-r1", "--root", str(tmp_path), "--fold", "1"]) == 0
    assert calls[0]["fold"] == 1
    for action in ("prepare", "validate", "export"):
        assert main(["train", action, "train-v4.1-r1", "--root", str(tmp_path), "--fold", "1"]) == 2
    assert len(calls) == 1
