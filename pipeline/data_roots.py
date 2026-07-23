"""Version-bound external data roots for frozen V2 and active V4.1 flows."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

MARKER_NAME = ".tensile-data-root.json"
REQUIRED_DIRECTORIES = ("source", "derived", "training_releases")


class DataRootError(ValueError):
    """Raised when a data root does not match its declared contract."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataRootError(f"无法读取数据根配置: {path}") from exc
    if not isinstance(value, dict):
        raise DataRootError(f"数据根配置必须是 JSON object: {path}")
    return value


def load_config(path: Path) -> dict[str, Any]:
    config = _read_object(Path(path))
    if config.get("schema_version") != 1:
        raise DataRootError("数据根配置 schema_version 必须为 1")
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise DataRootError("数据根配置缺少 profiles")

    directories: set[str] = set()
    for contract_version, profile in profiles.items():
        if not isinstance(contract_version, str) or not isinstance(profile, dict):
            raise DataRootError("profiles 中的契约和配置必须有效")
        directory = profile.get("directory")
        if (
            not isinstance(directory, str)
            or not directory
            or Path(directory).name != directory
        ):
            raise DataRootError(f"{contract_version}: directory 必须是单层目录名")
        if directory in directories:
            raise DataRootError("不同契约不能共用同一个数据目录")
        directories.add(directory)
        if profile.get("lifecycle") not in {"active", "frozen"}:
            raise DataRootError(f"{contract_version}: lifecycle 必须是 active 或 frozen")
        if not isinstance(profile.get("git_ref"), str) or not profile["git_ref"]:
            raise DataRootError(f"{contract_version}: 缺少 git_ref")
        links = profile.get("workspace_links")
        if not isinstance(links, dict) or not links:
            raise DataRootError(f"{contract_version}: 缺少 workspace_links")
        for link_name, target_name in links.items():
            for label, value in (("link", link_name), ("target", target_name)):
                if (
                    not isinstance(value, str)
                    or not value
                    or Path(value).is_absolute()
                    or ".." in Path(value).parts
                ):
                    raise DataRootError(
                        f"{contract_version}: workspace {label} 必须是安全相对路径"
                    )
    return config


def resolve_data_home(
    config: Mapping[str, Any],
    *,
    project_root: Path,
    override: Path | None = None,
) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env_name = config.get("data_home_env")
    if isinstance(env_name, str) and os.environ.get(env_name):
        return Path(os.environ[env_name]).expanduser().resolve()
    default = config.get("default_data_home")
    if not isinstance(default, str) or not default:
        raise DataRootError("数据根配置缺少 default_data_home")
    return (Path(project_root).resolve() / default).resolve()


def profile_for(config: Mapping[str, Any], contract_version: str) -> dict[str, Any]:
    profiles = config.get("profiles")
    profile = profiles.get(contract_version) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise DataRootError(f"未配置的数据契约: {contract_version}")
    return profile


def version_root(
    config: Mapping[str, Any],
    contract_version: str,
    *,
    data_home: Path,
) -> Path:
    profile = profile_for(config, contract_version)
    return Path(data_home).resolve() / profile["directory"]


def initialize_root(
    config: Mapping[str, Any],
    contract_version: str,
    *,
    data_home: Path,
) -> Path:
    profile = profile_for(config, contract_version)
    root = version_root(
        config,
        contract_version,
        data_home=data_home,
    )
    root.mkdir(parents=True, exist_ok=True)
    marker_path = root / MARKER_NAME
    if marker_path.exists():
        validate_root(
            config,
            contract_version,
            data_home=data_home,
        )
    else:
        marker = {
            "schema_version": 1,
            "contract_version": contract_version,
            "git_ref": profile["git_ref"],
            "lifecycle": profile["lifecycle"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        marker_path.write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    for name in REQUIRED_DIRECTORIES:
        (root / name).mkdir(exist_ok=True)
    return root


def workspace_root(
    config: Mapping[str, Any],
    contract_version: str,
    *,
    data_home: Path,
) -> Path:
    return version_root(
        config,
        contract_version,
        data_home=data_home,
    ) / ".compat" / "workspace"


def resolve_workspace_artifact(value: str | Path, workspace: Path) -> Path:
    """Map frozen ``data/...`` paths into one version's workspace.

    Historical manifests may contain an absolute path from the machine where
    they were created.  Only the suffix beginning with ``data`` is portable;
    all other absolute paths remain unchanged.
    """
    path = Path(value)
    workspace = Path(workspace).absolute()
    if not path.is_absolute():
        return workspace / path
    try:
        path.absolute().relative_to(workspace)
        return path
    except ValueError:
        pass
    data_indexes = [index for index, part in enumerate(path.parts) if part == "data"]
    if not data_indexes:
        return path
    suffix = Path(*path.parts[data_indexes[-1] :])
    return workspace / suffix


def workspace_relative_path(path: Path, workspace: Path) -> str:
    try:
        return str(Path(path).absolute().relative_to(Path(workspace).absolute()))
    except ValueError as exc:
        raise DataRootError(f"路径不属于版本 workspace: {path}") from exc


def workspace_portable_path(path: Path, workspace: Path) -> str:
    """Return the frozen ``data/...`` identity for a semantic target."""
    path = Path(path).absolute()
    workspace = Path(workspace).absolute()
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        pass
    resolved = path.resolve()
    for link in workspace.rglob("*"):
        if not link.is_symlink():
            continue
        target = link.resolve()
        try:
            suffix = resolved.relative_to(target)
        except ValueError:
            continue
        return str(link.relative_to(workspace) / suffix)
    raise DataRootError(f"路径不属于版本 workspace: {path}")


def initialize_workspace(
    config: Mapping[str, Any],
    contract_version: str,
    *,
    data_home: Path,
) -> Path:
    profile = profile_for(config, contract_version)
    root = version_root(config, contract_version, data_home=data_home)
    validate_root(config, contract_version, data_home=data_home)
    workspace = workspace_root(
        config,
        contract_version,
        data_home=data_home,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    for link_name, target_name in profile["workspace_links"].items():
        target = root / target_name
        if not target.exists():
            raise DataRootError(
                f"{contract_version}: workspace 目标不存在: {target}"
            )
        link = workspace / link_name
        link.parent.mkdir(parents=True, exist_ok=True)
        desired = Path(os.path.relpath(target, start=link.parent))
        if link.is_symlink():
            if link.readlink() != desired:
                link.unlink()
                link.symlink_to(desired, target_is_directory=target.is_dir())
        elif link.exists():
            raise DataRootError(
                f"{contract_version}: workspace 路径不是符号链接: {link}"
            )
        else:
            link.symlink_to(desired, target_is_directory=target.is_dir())
    validate_workspace(config, contract_version, data_home=data_home)
    return workspace


def validate_workspace(
    config: Mapping[str, Any],
    contract_version: str,
    *,
    data_home: Path,
) -> dict[str, Any]:
    profile = profile_for(config, contract_version)
    root = version_root(config, contract_version, data_home=data_home)
    workspace = workspace_root(
        config,
        contract_version,
        data_home=data_home,
    )
    for link_name, target_name in profile["workspace_links"].items():
        target = (root / target_name).resolve()
        link = workspace / link_name
        if not link.is_symlink() or link.resolve() != target:
            raise DataRootError(
                f"{contract_version}: workspace 链接无效: {link}"
            )
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise DataRootError(
                f"{contract_version}: workspace 目标越界: {target}"
            ) from exc
    return {
        "contract_version": contract_version,
        "workspace": str(workspace),
        "link_count": len(profile["workspace_links"]),
    }


def validate_root(
    config: Mapping[str, Any],
    contract_version: str,
    *,
    data_home: Path,
) -> dict[str, Any]:
    profile = profile_for(config, contract_version)
    root = version_root(config, contract_version, data_home=data_home)
    marker_path = root / MARKER_NAME
    marker = _read_object(marker_path)
    expected = {
        "schema_version": 1,
        "contract_version": contract_version,
        "git_ref": profile["git_ref"],
        "lifecycle": profile["lifecycle"],
    }
    for field, value in expected.items():
        if marker.get(field) != value:
            raise DataRootError(
                f"{marker_path}: {field}={marker.get(field)!r}，预期 {value!r}"
            )
    missing = [name for name in REQUIRED_DIRECTORIES if not (root / name).is_dir()]
    if missing:
        raise DataRootError(f"{root}: 缺少目录 {', '.join(missing)}")
    return {
        "contract_version": contract_version,
        "root": str(root),
        "git_ref": profile["git_ref"],
        "lifecycle": profile["lifecycle"],
    }
