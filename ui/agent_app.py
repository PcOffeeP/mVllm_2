#!/usr/bin/env python3
"""Streamlit local workbench for the TensileAgent iterative runner.

Run with:
    streamlit run ui/agent_app.py

The module can be imported even when Streamlit is not installed; the UI is
only built when ``main()`` is executed directly.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from agent import runner


VIDEO_EXTENSIONS: set[str] = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def _is_video_file(path: str | Path) -> bool:
    """Return True if ``path`` has a known video extension."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _find_video_files(directory: str | Path) -> list[Path]:
    """Return sorted video files under ``directory`` (non-recursive)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for ext in VIDEO_EXTENSIONS:
        files.extend(directory.glob(f"*{ext}"))
        files.extend(directory.glob(f"*{ext.upper()}"))
    return sorted(set(files))


def _format_event_summary(event: dict[str, Any]) -> str:
    """Return a short human-readable summary for an event."""
    event_type = event.get("event_type", "unknown")
    if event_type == "video_started":
        return f"开始分析视频 `{event.get('video_id')}`"
    if event_type == "round_started":
        return f"第 {event.get('display_round', event.get('round', 0) + 1)} 轮开始"
    if event_type == "llm_tool_call":
        return f"LLM 调用工具 `{event.get('tool_name')}`"
    if event_type == "sample_and_infer_finished":
        return "模型推理完成"
    if event_type == "state_updated":
        return f"状态更新: {event.get('previous_state')} → {event.get('state')}"
    if event_type == "video_finished":
        return "视频分析完成"
    if event_type == "video_failed":
        return f"视频分析失败 ({event.get('stage')})"
    return event_type


def _render_event(event: dict[str, Any]) -> None:
    """Render a single event in the Streamlit UI."""
    if st is None:
        return
    event_type = event.get("event_type", "unknown")
    if event_type == "video_started":
        st.write(f"**video_id:** `{event.get('video_id')}`")
        st.write(f"**video_path:** `{event.get('video_path')}`")
        st.write(f"**duration_sec:** {event.get('duration_sec')}")
        st.write(f"**max_rounds:** {event.get('max_rounds')}")
    elif event_type == "round_started":
        st.write(f"**state:** `{event.get('state')}`")
        st.write(f"**candidate:** {event.get('candidate')}")
    elif event_type == "llm_tool_call":
        st.write(f"**tool_name:** `{event.get('tool_name')}`")
        st.write("**tool_args:**")
        st.json(event.get("tool_args", {}))
    elif event_type == "sample_and_infer_finished":
        st.write("**model_output:**")
        st.json(event.get("model_output", {}))
        st.write(f"**inferred_time_range:** {event.get('inferred_time_range')}")
        st.write(f"**boundary_status:** {event.get('boundary_status')}")
    elif event_type == "state_updated":
        st.write(f"**previous_state:** `{event.get('previous_state')}`")
        st.write(f"**state:** `{event.get('state')}`")
        st.write(f"**previous_candidate:** {event.get('previous_candidate')}")
        st.write(f"**candidate:** {event.get('candidate')}")
    elif event_type == "video_finished":
        st.write("**result:**")
        st.json(event.get("result", {}))
    elif event_type == "video_failed":
        st.error(f"**stage:** `{event.get('stage')}`")
        st.error(f"**error:** {event.get('error')}")
    else:
        st.json(event)


def _render_timeline(events: list[dict[str, Any]]) -> None:
    """Render a list of agent events grouped by round."""
    if st is None:
        return
    if not events:
        st.info("暂无事件")
        return

    rounds: dict[int, list[dict[str, Any]]] = {}
    non_round: list[dict[str, Any]] = []
    for event in events:
        round_idx = event.get("round")
        if round_idx is not None:
            rounds.setdefault(round_idx, []).append(event)
        else:
            non_round.append(event)

    for event in non_round:
        with st.expander(_format_event_summary(event)):
            _render_event(event)

    for round_idx in sorted(rounds):
        round_events = rounds[round_idx]
        display_round = round_events[0].get("display_round", round_idx + 1)
        with st.expander(f"第 {display_round} 轮"):
            for event in round_events:
                st.markdown(f"**{_format_event_summary(event)}**")
                _render_event(event)
                st.divider()


def _update_timeline_placeholder(
    placeholder: Any, event: dict[str, Any]
) -> None:
    """Update a live placeholder with the latest event."""
    if st is None or placeholder is None:
        return
    with placeholder.container():
        st.caption(f"最新事件: {_format_event_summary(event)}")
        _render_event(event)


def _set_mock_mode(enabled: bool) -> None:
    """Toggle the mock inference environment variable."""
    if enabled:
        os.environ["INFERENCE_MOCK"] = "1"
    else:
        os.environ.pop("INFERENCE_MOCK", None)


def _result_to_row(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize a runner result into a flat table row."""
    return {
        "video_id": result.get("video_id", ""),
        "has_fracture": result.get("has_fracture", False),
        "time_estimate": result.get("time_estimate"),
        "type": result.get("type", ""),
        "location": result.get("location", ""),
        "confidence": result.get("confidence", 0.0),
        "confidence_level": result.get("confidence_level", ""),
        "rounds": result.get("rounds", 0),
        "status": "failed" if result.get("status") == "failed" else "success",
        "error": result.get("error", ""),
    }


def _export_jsonl(results: list[dict[str, Any]]) -> bytes:
    """Serialize ``results`` as JSON lines."""
    buffer = io.StringIO()
    for item in results:
        buffer.write(json.dumps(item, ensure_ascii=False) + "\n")
    return buffer.getvalue().encode("utf-8")


def _export_csv(results: list[dict[str, Any]]) -> bytes:
    """Serialize ``results`` as CSV."""
    buffer = io.StringIO()
    fieldnames = [
        "video_id",
        "has_fracture",
        "time_estimate",
        "type",
        "location",
        "confidence",
        "confidence_level",
        "rounds",
        "status",
        "error",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in results:
        writer.writerow(_result_to_row(item))
    return buffer.getvalue().encode("utf-8")


def _export_json(results: list[dict[str, Any]]) -> bytes:
    """Serialize ``results`` as a pretty-printed JSON string."""
    return json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8")


def _run_single_video(
    video_path: str, config_path: str, work_dir: str, mock: bool
) -> None:
    """Run the agent on a single video and update session state."""
    if st is None:
        return
    _set_mock_mode(mock)
    timeline_placeholder = st.empty()
    st.session_state.events = []
    st.session_state.result = None

    def event_callback(event: dict[str, Any]) -> None:
        st.session_state.events.append(event)
        _update_timeline_placeholder(timeline_placeholder, event)

    with st.spinner("Agent 运行中..."):
        try:
            result = runner.run_one(
                video_path,
                config_path,
                event_callback=event_callback,
                work_dir=work_dir,
            )
            st.session_state.result = result
            st.success("运行完成")
        except Exception as exc:
            st.error(f"运行失败: {exc}")


def _run_batch(
    directory: str, config_path: str, work_dir: str, mock: bool
) -> None:
    """Run the agent on all videos in ``directory`` and update session state."""
    if st is None:
        return
    _set_mock_mode(mock)
    video_paths = _find_video_files(directory)
    if not video_paths:
        st.warning(f"目录中没有找到视频文件: {directory}")
        return

    st.session_state.events = []
    st.session_state.batch_results = []
    st.session_state.batch_total = len(video_paths)
    st.session_state.batch_completed = 0

    progress_bar = st.progress(0)
    status_text = st.empty()
    timeline_placeholder = st.empty()

    def event_callback(event: dict[str, Any]) -> None:
        st.session_state.events.append(event)
        if event.get("event_type") in ("video_finished", "video_failed"):
            st.session_state.batch_completed += 1
            progress_bar.progress(
                st.session_state.batch_completed / st.session_state.batch_total
            )
            status_text.text(
                f"已完成 {st.session_state.batch_completed}/{st.session_state.batch_total}"
            )
        _update_timeline_placeholder(timeline_placeholder, event)

    with st.spinner("批量 Agent 运行中..."):
        try:
            results = runner.run_batch(
                video_paths,
                config_path,
                event_callback=event_callback,
                work_dir=work_dir,
            )
            st.session_state.batch_results = results
            st.success(f"完成 {len(video_paths)} 个视频")
        except Exception as exc:
            st.error(f"批量运行失败: {exc}")


def _render_single_result(result: dict[str, Any]) -> None:
    """Render the final result summary for a single video."""
    if st is None:
        return
    has_fracture = result.get("has_fracture", False)
    cols = st.columns(4)
    cols[0].metric("video_id", result.get("video_id", ""))
    cols[1].metric("has_fracture", str(has_fracture))
    cols[2].metric("time_estimate", result.get("time_estimate"))
    cols[3].metric("confidence", result.get("confidence"))
    st.json(result)


def _render_batch_results(results: list[dict[str, Any]]) -> None:
    """Render the batch result table and selected video timeline."""
    if st is None:
        return
    rows = [_result_to_row(r) for r in results]
    st.dataframe(rows, use_container_width=True)

    video_ids = [r["video_id"] for r in rows]
    selected = st.selectbox("选择视频查看事件时间线", options=video_ids)
    st.session_state.selected_video_id = selected

    selected_events = [
        e for e in st.session_state.events if e.get("video_id") == selected
    ]
    _render_timeline(selected_events)


def main() -> None:
    """Build and run the Streamlit workbench."""
    if st is None:
        print(
            "Streamlit is not installed. Install it with: pip install streamlit",
            file=sys.stderr,
        )
        sys.exit(1)

    st.set_page_config(page_title="TensileAgent Workbench", layout="wide")

    for key, default in (
        ("events", []),
        ("result", None),
        ("batch_results", []),
        ("selected_video_id", None),
        ("batch_total", 0),
        ("batch_completed", 0),
    ):
        if key not in st.session_state:
            st.session_state[key] = default

    with st.sidebar:
        st.title("TensileAgent Workbench")
        mode = st.radio("模式", options=["单视频", "批量视频"])

        if mode == "单视频":
            video_path_input = st.text_input("视频路径", value="")
            uploaded = st.file_uploader(
                "或上传视频文件", type=list(VIDEO_EXTENSIONS)
            )
        else:
            video_dir_input = st.text_input("视频目录路径", value="")

        config_path = st.text_input("配置文件路径", value="agent/config.yaml")
        work_dir = st.text_input("工作目录", value="data/runtime")
        mock_mode = st.checkbox("Mock 推理模式")
        run_clicked = st.button("运行 Agent")

    st.header("TensileAgent 工作台")

    if mode == "单视频":
        video_path = video_path_input.strip()
        if uploaded is not None:
            save_dir = Path(work_dir) / "uploads"
            save_dir.mkdir(parents=True, exist_ok=True)
            video_path = str(save_dir / uploaded.name)
            with open(video_path, "wb") as f:
                f.write(uploaded.getvalue())

        if video_path and Path(video_path).exists() and _is_video_file(video_path):
            st.subheader("视频预览")
            st.video(video_path)

        if run_clicked:
            if not video_path:
                st.error("请输入视频路径")
            elif not Path(video_path).exists():
                st.error(f"视频文件不存在: {video_path}")
            elif not _is_video_file(video_path):
                st.error(f"不支持的文件格式: {video_path}")
            else:
                _run_single_video(video_path, config_path, work_dir, mock_mode)

        if st.session_state.result is not None:
            st.subheader("最终结果摘要")
            _render_single_result(st.session_state.result)

        if st.session_state.events:
            st.subheader("Agent 事件时间线")
            _render_timeline(st.session_state.events)
    else:
        video_dir = video_dir_input.strip()

        if run_clicked:
            if not video_dir:
                st.error("请输入视频目录路径")
            elif not Path(video_dir).is_dir():
                st.error(f"目录不存在: {video_dir}")
            else:
                _run_batch(video_dir, config_path, work_dir, mock_mode)

        if st.session_state.batch_results:
            st.subheader("批量结果")
            _render_batch_results(st.session_state.batch_results)

    results_to_export: list[dict[str, Any]] = []
    if st.session_state.result is not None:
        results_to_export = [st.session_state.result]
    elif st.session_state.batch_results:
        results_to_export = st.session_state.batch_results

    if results_to_export:
        st.subheader("结果导出")
        col1, col2, col3 = st.columns(3)
        col1.download_button(
            label="导出 JSONL",
            data=_export_jsonl(results_to_export),
            file_name="results.jsonl",
            mime="application/jsonl",
        )
        col2.download_button(
            label="导出 CSV",
            data=_export_csv(results_to_export),
            file_name="results.csv",
            mime="text/csv",
        )
        col3.download_button(
            label="导出 JSON",
            data=_export_json(results_to_export),
            file_name="results.json",
            mime="application/json",
        )


if __name__ == "__main__":
    main()
