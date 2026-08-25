from pathlib import Path

import pytest

from pipeline.scripts.source_migrate_workspace import (
    WorkspaceMigrationError,
    inventory,
    migrate,
)


def _write_source(root: Path) -> None:
    (root / "source").mkdir(parents=True)
    (root / "derived").mkdir()
    (root / "training_releases/dev-v4.1").mkdir(parents=True)
    (root / "source/video.mp4").write_bytes(b"video")
    (root / "derived/training_candidates.json").write_text("[]\n", encoding="utf-8")
    (root / "training_releases/dev-v4.1/manifest.json").write_text(
        '{"release":"dev-v4.1"}\n',
        encoding="utf-8",
    )


def test_migration_physically_copies_and_verifies_managed_data(tmp_path: Path) -> None:
    source = tmp_path / "current"
    destination = tmp_path / "repo/workspace/data"
    _write_source(source)

    result = migrate(source, destination, copy=True)

    assert result["verified"] is True
    assert (destination / "source/video.mp4").read_bytes() == b"video"
    assert (destination / "releases/dev-v4.1/manifest.json").is_file()
    assert not any(path.is_symlink() for path in destination.rglob("*"))
    assert inventory(source, source_layout=True) == inventory(
        destination,
        source_layout=False,
    )
    assert migrate(source, destination, copy=False)["verified"] is True


def test_migration_refuses_overwrite_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "current"
    destination = tmp_path / "workspace/data"
    _write_source(source)
    destination.mkdir(parents=True)

    with pytest.raises(WorkspaceMigrationError, match="拒绝覆盖"):
        migrate(source, destination, copy=True)

    link = source / "derived/link"
    link.symlink_to(source / "source/video.mp4")
    with pytest.raises(WorkspaceMigrationError, match="不允许软链接"):
        inventory(source, source_layout=True)
