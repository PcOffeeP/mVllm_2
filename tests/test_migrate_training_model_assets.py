from pathlib import Path

from scripts.migrate_training_model_assets import _move_and_link


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
