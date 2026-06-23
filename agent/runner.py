"""Shared execution kernel for the iterative agent.

This module is the single entry point used by both the local Streamlit UI and
the CLI. It loads configuration, builds the minimal video metadata required by
``IterativeAgent``, wires up the LLM / inference / sampling / clip-building
dependencies, and runs one or more videos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml


def load_config(config_path: str | Path = "agent/config.yaml") -> dict[str, Any]:
    """Load and return the YAML configuration at ``config_path``."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def create_llm_client(config: dict[str, Any]):
    """Create the Meta-Agent LLM client from ``config``.

    Delegates to ``agent.llm.AgentLLMFactory``.
    """
    from agent.llm import AgentLLMFactory

    return AgentLLMFactory.create(config)


def create_inference_client(config: dict[str, Any]):
    """Create the fine-tuned model inference client from ``config``.

    Delegates to ``agent.inference.create_inference_client``.
    """
    from agent.inference import create_inference_client as _create_inference_client

    return _create_inference_client(config)


def create_sampler(config: dict[str, Any], cache_dir: str | Path | None = None):
    """Create a ``UniformVideoSampler``.

    Defaults ``cache_dir`` to ``data/08_runtime/agent_frames`` if not provided.
    """
    from agent.sampling import UniformVideoSampler

    if cache_dir is None:
        cache_dir = "data/08_runtime/agent_frames"
    return UniformVideoSampler(cache_dir=str(cache_dir))


def create_clip_builder(
    config: dict[str, Any], output_dir: str | Path | None = None
):
    """Create a ``FfmpegVideoClipBuilder``.

    Defaults ``output_dir`` to ``data/08_runtime/agent_clips`` if not provided.
    """
    from agent.sampling import FfmpegVideoClipBuilder

    if output_dir is None:
        output_dir = "data/08_runtime/agent_clips"
    return FfmpegVideoClipBuilder(output_dir=str(output_dir))


def build_video_meta(
    video_path: str | Path, video_id: str | None = None
) -> dict[str, Any]:
    """Build the ``video_meta`` dict expected by ``IterativeAgent``.

    ``duration_sec`` is obtained with ``ffprobe`` when available, otherwise via
    ``cv2``. If neither is available, a ``RuntimeError`` is raised.

    Returns:
        A dict with keys ``video_id``, ``video_path``, ``duration_sec``,
        ``duration`` (alias for ``duration_sec``), ``original_fps`` and
        ``total_frames``.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    resolved_id = video_id if video_id is not None else path.stem

    # Prefer ffprobe.
    try:
        from agent.sampling import _probe_video, _which_ffprobe

        _which_ffprobe()
        probe = _probe_video(str(path))
        duration = float(probe["duration"] or 0.0)
        fps = probe["fps"] or 0.0
        total_frames = int(probe["total_frames"] or 0)
        return {
            "video_id": resolved_id,
            "video_path": str(path),
            "duration_sec": duration,
            "duration": duration,
            "original_fps": fps if fps > 0 else None,
            "total_frames": total_frames if total_frames > 0 else None,
        }
    except Exception:
        pass

    # Fall back to cv2.
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Unable to read video metadata: ffprobe failed and cv2 is not installed."
        ) from exc

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cv2 unable to open video: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if fps <= 0 or total_frames <= 0:
        raise RuntimeError(
            f"Unable to determine video duration from cv2: fps={fps}, frames={total_frames}"
        )

    duration = total_frames / fps
    return {
        "video_id": resolved_id,
        "video_path": str(path),
        "duration_sec": duration,
        "duration": duration,
        "original_fps": float(fps),
        "total_frames": total_frames,
    }


def _runtime_dir(work_dir: str | Path | None, name: str) -> Path:
    """Return a runtime subdirectory path rooted at ``work_dir`` or cwd."""
    if work_dir is None:
        return Path("data/08_runtime") / name
    return Path(work_dir) / "data/08_runtime" / name


def run_one(
    video_path: str | Path,
    config_path: str | Path = "agent/config.yaml",
    video_id: str | None = None,
    event_callback: Callable[[dict], None] | None = None,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the agent on a single video and return the final result dict.

    Configuration is loaded from ``config_path`` inside this function. All
    exceptions are caught, emitted as a ``video_failed`` event (when a callback
    is provided), annotated with the failing ``stage``, and then re-raised.
    """
    from agent.iterative_agent import IterativeAgent

    path = Path(video_path)
    resolved_id = video_id if video_id is not None else path.stem

    stage = "metadata"
    try:
        config = load_config(config_path)
        video_meta = build_video_meta(path, video_id=resolved_id)

        stage = "llm_client"
        llm_client = create_llm_client(config)

        stage = "inference_client"
        inference_client = create_inference_client(config)

        stage = "sampler"
        sampler = create_sampler(
            config, cache_dir=_runtime_dir(work_dir, "agent_frames")
        )

        stage = "clip_builder"
        clip_builder = create_clip_builder(
            config, output_dir=_runtime_dir(work_dir, "agent_clips")
        )

        stage = "agent"
        agent = IterativeAgent(
            config=config,
            video_meta=video_meta,
            llm_client=llm_client,
            sampler=sampler,
            clip_builder=clip_builder,
            inference_client=inference_client,
            event_callback=event_callback,
        )
        return agent.run()
    except Exception as exc:
        exc._stage = stage  # type: ignore[attr-defined]
        if event_callback is not None:
            event_callback(
                {
                    "event_type": "video_failed",
                    "video_id": resolved_id,
                    "error": str(exc),
                    "stage": stage,
                }
            )
        raise


def run_batch(
    video_paths: list[str | Path],
    config_path: str | Path = "agent/config.yaml",
    event_callback: Callable[[dict], None] | None = None,
    work_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Run the agent sequentially on multiple videos.

    Configuration is loaded by each call to ``run_one`` from ``config_path``.
    A single video failure emits a ``video_failed`` event (via ``run_one``) and
    is recorded as
    ``{"video_id": ..., "video_path": ..., "ok": false, "error": ..., "stage": ...}``
    without interrupting the rest of the batch.
    """
    results: list[dict[str, Any]] = []
    for path in video_paths:
        path_obj = Path(path)
        resolved_id = path_obj.stem
        try:
            results.append(
                run_one(
                    path_obj,
                    config_path,
                    video_id=resolved_id,
                    event_callback=event_callback,
                    work_dir=work_dir,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "video_id": resolved_id,
                    "video_path": str(path_obj),
                    "ok": False,
                    "error": str(exc),
                    "stage": getattr(exc, "_stage", "run_one"),
                }
            )
    return results
