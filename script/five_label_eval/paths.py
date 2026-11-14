"""Resolve the evaluator's nine media/prompt/output paths from a named profile.

Values carry no absolute home directory: ``~`` is expanded by :func:`resolve_path` and a
relative value is joined onto the repository root. Existence is never checked here;
failing consumers report missing files themselves.

``gpu-train`` carries ``TODO_MIGRATION_FILL:<key>`` placeholders on purpose: those paths are
still chosen during migration, so they never resolve inside the repository; :func:`is_placeholder`
reports them instead of letting a consumer create a directory in the worktree.
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_KEYS = ("source_videos", "roi_videos", "sub_video_dir", "sub_video_manifest", "sub_video_videos",
                "review_store", "prompts_dir", "output_dir", "score_output_dir")
CONFIG_RELATIVE = "config/eval_paths.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
TODO_MARKER, PLACEHOLDER_ROOT = "TODO_MIGRATION_FILL:", Path("/nonexistent")


class EvalPathError(ValueError):
    """Path profile is missing, malformed or names an unknown profile."""


def is_placeholder(profile, key=None) -> bool:
    """True when the key (any key when omitted) never resolved to a usable path."""
    return any(TODO_MARKER in str(profile[k])
               for k in (PROFILE_KEYS if key is None else (key,)))


def resolve_path(value: str, base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (REPO_ROOT if base is None else Path(base)) / path


def load_profile(name: str, config_path=None) -> dict[str, Path]:
    config_file = Path(config_path) if config_path is not None else REPO_ROOT / CONFIG_RELATIVE
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvalPathError(f"cannot read path config {config_file}: {exc}") from exc
    except ValueError as exc:
        raise EvalPathError(f"invalid JSON in path config {config_file}: {exc}") from exc
    profiles = config.get("profiles") if isinstance(config, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise EvalPathError(f"{config_file}: missing profiles object")
    if name not in profiles:
        raise EvalPathError(f"unknown profile {name!r}; available profiles: {sorted(profiles)}")
    profile = profiles[name]
    if not isinstance(profile, dict):
        raise EvalPathError(f"{config_file}: profile {name!r} must be an object")
    missing = [key for key in PROFILE_KEYS
               if not isinstance(profile.get(key), str) or not profile[key].strip()]
    if missing:
        raise EvalPathError(f"{config_file}: profile {name!r} missing or non-string keys: {missing}")
    return {key: (PLACEHOLDER_ROOT / profile[key].strip() if profile[key].strip().startswith(TODO_MARKER)
                  else resolve_path(profile[key])) for key in PROFILE_KEYS}
