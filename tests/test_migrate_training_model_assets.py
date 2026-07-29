from pathlib import Path

from scripts.migrate_training_model_assets import _ensure_current_link, _move_and_link


def test_move_and_link_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "legacy/model"
    target = tmp_path / "workspace/run/adapter"
    source.mkdir(parents=True)
    (source / "adapter_model.safetensors").write_bytes(b"adapter")

    assert _move_and_link(source, target, apply=True) == "migrated"
    assert source.is_symlink()
    assert source.resolve() == target.resolve()

    assert _move_and_link(source, target, apply=False) == "already_migrated"
    assert _move_and_link(source, target, apply=True) == "already_migrated"


def test_current_link_is_idempotent(tmp_path: Path) -> None:
    release = tmp_path / "workspace/models/releases/model"
    current = tmp_path / "workspace/models/current"
    release.mkdir(parents=True)

    assert _ensure_current_link(current, release) == "created"
    assert current.is_symlink()
    assert _ensure_current_link(current, release) == "already_current"
