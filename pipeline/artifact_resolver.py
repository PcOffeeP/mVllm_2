"""Artifact ID resolver: LATEST pointer + short-hash prefix + full ID lookup."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pipeline import artifact_index

LATEST_FILENAME = "LATEST"
def _validate_artifact_id(artifact_id: str) -> None:
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise ValueError("产物 ID 必须是非空字符串")


def update_latest(collection_dir: Path | str, artifact_id: str) -> None:
    """Write the LATEST pointer atomically to a collection directory.

    Idempotent: writing the same value is a no-op. Rejects malformed IDs.
    """
    _validate_artifact_id(artifact_id)
    collection_dir = Path(collection_dir)
    path = collection_dir / LATEST_FILENAME
    content = f"{artifact_id}\n".encode("utf-8")
    collection_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{LATEST_FILENAME}.",
        dir=collection_dir,
        text=False,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read_latest(collection_dir: Path) -> str:
    path = collection_dir / LATEST_FILENAME
    if not path.exists():
        raise ValueError(
            f"集合目录 {collection_dir} 不存在 LATEST 指针；"
            "请先运行生成步骤生成产物，或在解析时显式传入产物 ID"
        )
    return path.read_text(encoding="utf-8").strip()


def _candidate_ids(collection_dir: Path) -> list[str]:
    return [entry["id"] for entry in artifact_index.read_index(collection_dir)]


def resolve_cli_artifact_path(
    collection_dir: Path | str,
    value: Path | str | None,
    *,
    artifact_subpath: str | None = None,
) -> Path:
    """Resolve a CLI argument to a concrete artifact path.

    Resolution layers:
      - value is None: read the LATEST pointer, optionally append
        artifact_subpath.
      - value is a path-like string (contains '/' or the platform path separator,
        starts with '~', or is an absolute path): return it with expanduser()
        applied (so '~' and '~user' are resolved).
      - value is a full artifact ID or short prefix: resolve via
        resolve_artifact and return <collection_dir>/<artifact_id>,
        optionally appending artifact_subpath.

    Fail-closed: raises ValueError on any ambiguity or missing artifact.
    """
    collection_dir = Path(collection_dir)
    if value is None:
        artifact_id = resolve_artifact(collection_dir, None)
        path = collection_dir / artifact_id
        return path / artifact_subpath if artifact_subpath else path

    text = str(value).strip()
    if not text:
        raise ValueError("产物选择器不能为空")

    candidate = Path(value)
    if (
        "/" in text
        or os.sep in text
        or text.startswith("~")
        or candidate.is_absolute()
    ):
        return candidate.expanduser()

    artifact_id = resolve_artifact(collection_dir, text)
    path = collection_dir / artifact_id
    return path / artifact_subpath if artifact_subpath else path


def resolve_artifact(
    collection_dir: Path | str,
    selector: str | None,
) -> str:
    """Resolve a selector to a full artifact ID.

    Resolution layers:
      - selector is None: read the LATEST pointer.
      - selector is a full artifact ID (exact match): return it if it exists.
      - selector is a prefix: return the unique matching ID; raise if 0 or 2+.

    Fail-closed: raises ValueError on any ambiguity or missing artifact.
    """
    collection_dir = Path(collection_dir)
    if selector is None:
        latest_id = _read_latest(collection_dir)
        candidates = _candidate_ids(collection_dir)
        if latest_id not in candidates:
            raise ValueError(
                f"LATEST 指针 '{latest_id}' 已失效，不在当前 index 候选集中；"
                "请重新运行生成步骤生成产物，或在解析时显式传入产物 ID"
            )
        return latest_id

    selector = selector.strip()
    if not selector:
        raise ValueError("产物选择器不能为空")

    candidates = _candidate_ids(collection_dir)
    if selector in candidates:
        return selector

    def _matches(aid: str) -> bool:
        if aid.startswith(selector):
            return True
        hash_part = aid.split("-")[-1] if "-" in aid else aid
        return hash_part.startswith(selector)

    matches = [aid for aid in candidates if _matches(aid)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"产物选择器 '{selector}' 存在多义匹配，候选: {', '.join(matches)}"
        )
    raise ValueError(
        f"未找到匹配产物: {selector}（集合目录: {collection_dir}）"
    )
