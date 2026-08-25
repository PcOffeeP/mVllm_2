from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import artifact_index, artifact_resolver


def _make_entry(artifact_id: str, step: str = "source") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def test_resolve_latest_reads_pointer(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    artifact_resolver.update_latest(collection_dir, artifact_id)

    resolved = artifact_resolver.resolve_artifact(collection_dir, None)
    assert resolved == artifact_id


def test_resolve_latest_missing_gives_clear_error(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )

    with pytest.raises(ValueError, match="LATEST") as exc_info:
        artifact_resolver.resolve_artifact(collection_dir, None)
    message = str(exc_info.value).lower()
    assert "latest" in message
    assert "生成" in message or "显式" in message


def test_resolve_full_id_exact(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))

    resolved = artifact_resolver.resolve_artifact(collection_dir, artifact_id)
    assert resolved == artifact_id


def test_resolve_full_id_not_exists_gives_error(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )

    with pytest.raises(ValueError, match="未找到"):
        artifact_resolver.resolve_artifact(
            collection_dir, "source-ffffffffffff"
        )


def test_resolve_short_prefix_unique_match(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )
    artifact_index.append_entry(
        collection_dir, _make_entry("source-fedcba654321")
    )

    resolved = artifact_resolver.resolve_artifact(collection_dir, "abc")
    assert resolved == "source-abcdef123456"

    resolved = artifact_resolver.resolve_artifact(
        collection_dir, "source-abc"
    )
    assert resolved == "source-abcdef123456"


def test_resolve_short_prefix_ambiguous_lists_candidates(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abc123456789")
    )

    with pytest.raises(ValueError) as exc_info:
        artifact_resolver.resolve_artifact(collection_dir, "abc")
    message = str(exc_info.value)
    assert "多义" in message or "候选" in message
    assert "source-abcdef123456" in message
    assert "source-abc123456789" in message


def test_resolve_short_prefix_no_match_gives_error(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )

    with pytest.raises(ValueError, match="未找到"):
        artifact_resolver.resolve_artifact(collection_dir, "zzz")


def test_update_latest_atomic_and_idempotent(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"

    artifact_resolver.update_latest(collection_dir, artifact_id)
    latest_path = Path(collection_dir) / artifact_resolver.LATEST_FILENAME
    assert latest_path.read_text(encoding="utf-8").strip() == artifact_id

    artifact_resolver.update_latest(collection_dir, artifact_id)
    assert latest_path.read_text(encoding="utf-8").strip() == artifact_id


def test_update_latest_rejects_empty_id(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"

    with pytest.raises(ValueError):
        artifact_resolver.update_latest(collection_dir, "")

    with pytest.raises(ValueError):
        artifact_resolver.update_latest(collection_dir, "   ")


def test_resolve_reads_from_index_not_only_latest_file(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))

    resolved = artifact_resolver.resolve_artifact(collection_dir, "abc")
    assert resolved == artifact_id


def test_resolve_cli_path_none_reads_latest(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    artifact_resolver.update_latest(collection_dir, artifact_id)

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, None
    )
    assert resolved == collection_dir / artifact_id


def test_resolve_cli_path_none_with_subpath(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    artifact_resolver.update_latest(collection_dir, artifact_id)

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, None, artifact_subpath="video_meta.json"
    )
    assert resolved == collection_dir / artifact_id / "video_meta.json"


def test_resolve_cli_path_full_id(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, artifact_id
    )
    assert resolved == collection_dir / artifact_id


def test_resolve_cli_path_full_id_with_subpath(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, artifact_id, artifact_subpath="video_meta.json"
    )
    assert resolved == collection_dir / artifact_id / "video_meta.json"


def test_resolve_cli_path_prefix(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, "abc"
    )
    assert resolved == collection_dir / artifact_id


def test_resolve_cli_path_uses_filesystem_path(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    explicit = tmp_path / "custom" / "video_meta.json"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("{}")

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, str(explicit)
    )
    assert resolved == explicit


def test_resolve_cli_path_expands_tilde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    explicit = home / "evil"
    explicit.write_text("{}")

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, "~/evil"
    )
    assert resolved == explicit
    assert resolved.is_absolute()


def test_resolve_cli_path_filesystem_path_ignores_subpath(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    explicit = tmp_path / "custom" / "video_meta.json"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("{}")

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, str(explicit), artifact_subpath="ignored.json"
    )
    assert resolved == explicit


def test_resolve_cli_path_missing_latest_is_clear(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )

    with pytest.raises(ValueError, match="LATEST|最新"):
        artifact_resolver.resolve_cli_artifact_path(collection_dir, None)


def test_resolve_latest_rejects_stale_pointer(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("source-abcdef123456")
    )
    artifact_resolver.update_latest(
        collection_dir, "source-missingdeadbeef"
    )

    with pytest.raises(ValueError, match="LATEST.*失效|重新生成|显式") as exc_info:
        artifact_resolver.resolve_artifact(collection_dir, None)
    message = str(exc_info.value).lower()
    assert "latest" in message
    assert "重新生成" in message or "显式" in message


def test_resolve_cli_bare_name_does_not_sniff_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_id = "source-abcdef123456"
    artifact_index.append_entry(collection_dir, _make_entry(artifact_id))
    # Create a bare-name file in the current working directory that the old
    # ``candidate.exists()`` sniff would have returned as a filesystem path.
    monkeypatch.chdir(tmp_path)
    bare_file = tmp_path / artifact_id
    bare_file.write_text("not an artifact")

    resolved = artifact_resolver.resolve_cli_artifact_path(
        collection_dir, artifact_id
    )
    assert resolved == collection_dir / artifact_id
    assert resolved != bare_file


def test_resolve_short_prefix_hash_segment_only(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("candidate-media-abcdef123456")
    )
    artifact_index.append_entry(
        collection_dir, _make_entry("candidate-plan-fedcba654321")
    )

    # Hash suffix prefix works.
    resolved = artifact_resolver.resolve_artifact(collection_dir, "abcdef")
    assert resolved == "candidate-media-abcdef123456"

    # Full-ID prefix works.
    resolved = artifact_resolver.resolve_artifact(
        collection_dir, "candidate-media"
    )
    assert resolved == "candidate-media-abcdef123456"

    # Mid-word like "media" must not match either ID.
    with pytest.raises(ValueError, match="未找到"):
        artifact_resolver.resolve_artifact(collection_dir, "media")


def test_resolve_cli_path_mid_word_prefix_fails_closed(tmp_path: Path) -> None:
    collection_dir = tmp_path / "source_snapshots"
    artifact_index.append_entry(
        collection_dir, _make_entry("candidate-media-abcdef123456")
    )

    with pytest.raises(ValueError, match="未找到"):
        artifact_resolver.resolve_cli_artifact_path(
            collection_dir, "media"
        )

