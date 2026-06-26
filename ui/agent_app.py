#!/usr/bin/env python3
"""Streamlit local workbench for the TensileAgent iterative runner.

Deep-engineering three-column dark console UI.

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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from agent import runner

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS: set[str] = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_DARK_CSS = """
<style>
    /* Global dark theme */
    .stApp, .stApp > header, .stApp > div {
        background-color: #0e1117 !important;
        color: #e0e0e0 !important;
    }
    /* Panels */
    .css-1d391kg, .css-12oz5g7, .block-container, .st-emotion-cache-1y4p8pa,
    .st-emotion-cache-1wqrhv4, div[data-testid="stSidebar"] {
        background-color: #0e1117 !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #0e1117 !important;
        border-right: 1px solid #2e3138;
    }
    div.stButton > button {
        background-color: #1a1d24 !important;
        border: 1px solid #2e3138 !important;
        color: #e0e0e0 !important;
        border-radius: 4px !important;
        font-size: 0.85rem !important;
    }
    div.stButton > button:hover {
        border-color: #3b82f6 !important;
    }
    div.stTextInput > div > div > input {
        background-color: #1a1d24 !important;
        border: 1px solid #2e3138 !important;
        color: #e0e0e0 !important;
        border-radius: 4px !important;
        font-size: 0.85rem !important;
    }
    div.stTextInput > div > div > input:focus {
        border-color: #3b82f6 !important;
    }
    /* Radio buttons */
    div.stRadio > div {
        background-color: transparent !important;
    }
    div.stRadio label {
        color: #e0e0e0 !important;
        font-size: 0.85rem !important;
    }
    /* Metrics */
    div[data-testid="stMetricValue"] {
        font-size: 1.1rem !important;
        color: #e0e0e0 !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        color: #888 !important;
    }
    /* Expander */
    div.streamlit-expanderHeader {
        background-color: #1a1d24 !important;
        border: 1px solid #2e3138 !important;
        border-radius: 4px !important;
        font-size: 0.85rem !important;
        color: #e0e0e0 !important;
    }
    div.streamlit-expanderContent {
        background-color: #1a1d24 !important;
        border: 1px solid #2e3138 !important;
        border-top: none !important;
        border-radius: 0 0 4px 4px !important;
    }
    /* JSON viewer */
    .stJson {
        background-color: #1a1d24 !important;
        border: 1px solid #2e3138 !important;
        border-radius: 4px !important;
        font-size: 0.8rem !important;
    }
    /* Code blocks */
    code, pre {
        font-size: 0.8rem !important;
        border-radius: 4px !important;
    }
    /* Dataframe */
    div[data-testid="stDataFrame"] {
        font-size: 0.8rem !important;
    }
    div[data-testid="stDataFrame"] table {
        font-size: 0.8rem !important;
    }
    /* File uploader */
    section[data-testid="stFileUploader"] {
        background-color: #1a1d24 !important;
        border: 1px dashed #2e3138 !important;
        border-radius: 4px !important;
        padding: 0.5rem !important;
    }
    section[data-testid="stFileUploader"]:hover {
        border-color: #3b82f6 !important;
    }
    /* Progress bar */
    div.stProgress > div > div > div > div {
        background-color: #3b82f6 !important;
    }
    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        vertical-align: middle;
    }
    .status-pending { background-color: #2e3138; color: #888; }
    .status-running { background-color: #1e3a5f; color: #3b82f6; }
    .status-completed { background-color: #0f2e1a; color: #22c55e; }
    .status-failed { background-color: #2e1114; color: #ef4444; }
    /* Round badge */
    .round-badge {
        display: inline-block;
        background-color: #1a1d24;
        border: 1px solid #3b82f6;
        color: #3b82f6;
        border-radius: 4px;
        padding: 0.05rem 0.4rem;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 0.3rem;
    }
    /* Event log */
    .event-log {
        background-color: #000000;
        color: #22c55e;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.75rem;
        padding: 0.4rem;
        border-radius: 4px;
        border: 1px solid #2e3138;
        line-height: 1.4;
        white-space: pre-wrap;
        word-break: break-all;
    }
    /* Result card */
    .result-card {
        padding: 0.6rem;
        border-radius: 4px;
        border: 1px solid #2e3138;
        background-color: #1a1d24;
        margin-bottom: 0.4rem;
    }
    .result-fracture { border-left: 3px solid #22c55e; }
    .result-no_fracture { border-left: 3px solid #3b82f6; }
    .result-unrecognized { border-left: 3px solid #eab308; }
    .result-failed { border-left: 3px solid #ef4444; }
    /* Task list items */
    .task-item {
        padding: 0.3rem 0.5rem;
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.8rem;
        margin-bottom: 0.15rem;
        border: 1px solid transparent;
    }
    .task-item:hover {
        background-color: #1a1d24;
        border-color: #2e3138;
    }
    .task-item.active {
        background-color: #1e3a5f;
        border-color: #3b82f6;
    }
    /* Section title */
    .section-title {
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #888;
        margin: 0.8rem 0 0.3rem 0;
    }
    /* Info text */
    .info-text {
        font-size: 0.8rem;
        color: #888;
    }
    /* Scrollable containers */
    .scrollable-panel {
        overflow-y: auto;
        max-height: calc(100vh - 80px);
    }
    /* Terminal output */
    .terminal-output {
        background-color: #000000;
        color: #e0e0e0;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.75rem;
        padding: 0.4rem;
        border-radius: 4px;
        border: 1px solid #2e3138;
        max-height: 400px;
        overflow-y: auto;
        line-height: 1.5;
    }
    /* Collapsible JSON */
    .collapsible-json summary {
        cursor: pointer;
        font-size: 0.8rem;
        color: #3b82f6;
    }
    /* Export buttons row */
    .export-row {
        display: flex;
        gap: 0.4rem;
        margin-top: 0.5rem;
    }
    .export-row button {
        flex: 1;
    }
    hr {
        border-color: #2e3138 !important;
        margin: 0.4rem 0 !important;
    }
</style>
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TaskItem:
    """Represents a single video analysis task."""

    video_id: str
    video_path: str
    status: str = STATUS_PENDING
    config_path: str = "agent/config.yaml"
    work_dir: str = "."
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Helper functions (importable without streamlit)
# ---------------------------------------------------------------------------


def _is_video_file(path: str | Path) -> bool:
    """Return True if ``path`` has a known video extension."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _find_video_files(directory: str | Path) -> list[Path]:
    """Return sorted video files under ``directory`` (non-recursive)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for child in directory.iterdir():
        if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
            files.append(child)
    return sorted(set(files))


def _result_to_row(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize a runner result into a flat table row."""
    inner = (result.get("result") or {}) if isinstance(result, dict) else {}
    error = result.get("error", {}) or {}
    ok = result.get("ok", True)

    row = {
        "video_id": inner.get("video_id", ""),
        "status": inner.get("status", ""),
        "has_fracture": inner.get("status") == "fracture",
        "time_range": inner.get("time_range"),
        "fracture_type": inner.get("fracture_type", ""),
        "location": inner.get("location", ""),
        "confidence": inner.get("confidence", 0.0),
        "unrecognized_reason": inner.get("unrecognized_reason", ""),
        "rounds": result.get("rounds", 0),
        "ok": ok,
        "error_code": error.get("code", "") if isinstance(error, dict) else "",
        "error_message": error.get("message", "") if isinstance(error, dict) else str(error),
    }
    return row


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
        prev = event.get("previous_state", "")
        new = event.get("state", "")
        return f"状态更新: {prev} → {new}"
    if event_type == "video_finished":
        return "视频分析完成"
    if event_type == "video_failed":
        return f"视频分析失败 ({event.get('stage')})"
    return event_type


def _export_jsonl(results: list[Any]) -> bytes:
    """Serialize ``results`` as JSON lines."""
    buffer = io.StringIO()
    for item in results:
        if hasattr(item, "model_dump"):
            buffer.write(json.dumps(item.model_dump(), ensure_ascii=False) + "\n")
        elif isinstance(item, dict):
            buffer.write(json.dumps(item, ensure_ascii=False) + "\n")
        else:
            buffer.write(json.dumps(item, ensure_ascii=False) + "\n")
    return buffer.getvalue().encode("utf-8")


def _export_csv(results: list[dict[str, Any]]) -> bytes:
    """Serialize ``results`` as CSV."""
    buffer = io.StringIO()
    fieldnames = [
        "video_id",
        "status",
        "has_fracture",
        "time_range",
        "fracture_type",
        "location",
        "confidence",
        "unrecognized_reason",
        "rounds",
        "ok",
        "error_code",
        "error_message",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in results:
        writer.writerow(_result_to_row(item))
    return buffer.getvalue().encode("utf-8")


def _export_json(results: list[Any]) -> bytes:
    """Serialize ``results`` as a pretty-printed JSON string."""
    serializable = []
    for item in results:
        if hasattr(item, "model_dump"):
            serializable.append(item.model_dump())
        elif isinstance(item, dict):
            serializable.append(item)
        else:
            serializable.append(item)
    return json.dumps(serializable, ensure_ascii=False, indent=2).encode("utf-8")


# ---------------------------------------------------------------------------
# HTML builders (importable without streamlit)
# ---------------------------------------------------------------------------


def _status_badge_html(status: str) -> str:
    """Return HTML for a status badge."""
    cls = f"status-{status}" if status in ("pending", "running", "completed", "failed") else "status-pending"
    return f'<span class="status-badge {cls}">{status}</span>'


def _round_badge_html(round_num: int) -> str:
    """Return HTML for a round badge."""
    return f'<span class="round-badge">第 {round_num} 轮</span>'


def _event_log_html(text: str) -> str:
    """Wrap text in terminal-style event log HTML."""
    return f'<div class="event-log">{text}</div>'


def _result_card_html(
    status: str,
    summary_line: str,
    detail_lines: list[str] | None = None,
) -> str:
    """Return HTML for a result card."""
    cls = f"result-{status}" if status in ("fracture", "no_fracture", "unrecognized", "failed") else ""
    lines_html = ""
    if detail_lines:
        lines_html = "<br>" + "<br>".join(detail_lines)
    return (
        f'<div class="result-card {cls}">'
        f'<strong style="font-size:0.85rem;">{summary_line}</strong>'
        f'{lines_html}'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Streamlit-only functions
# ---------------------------------------------------------------------------


def _init_session_state() -> None:
    """Initialize all session state keys."""
    if st is None:
        return
    if "tasks" not in st.session_state:
        st.session_state.tasks = {}
    if "active_task_id" not in st.session_state:
        st.session_state.active_task_id = None
    if "view" not in st.session_state:
        st.session_state.view = "workbench"
    if "queue" not in st.session_state:
        st.session_state.queue = []


def _set_mock_mode(enabled: bool) -> None:
    """Toggle the mock inference environment variable."""
    if enabled:
        os.environ["INFERENCE_MOCK"] = "1"
    else:
        os.environ.pop("INFERENCE_MOCK", None)


def _resolve_upload_path(upload_name: str, work_dir: str) -> str:
    """Resolve upload path, adding timestamp suffix on conflict."""
    save_dir = Path(work_dir) / "uploads"
    save_dir.mkdir(parents=True, exist_ok=True)
    dest = save_dir / upload_name
    if dest.exists():
        ts = datetime.now().strftime("_%Y%m%d_%H%M%S")
        stem = dest.stem
        suffix = dest.suffix
        dest = save_dir / f"{stem}{ts}{suffix}"
    return str(dest)


def _add_task_from_path(video_path: str, config_path: str, work_dir: str) -> str | None:
    """Create a TaskItem from a video path. Returns task key or None on error."""
    p = Path(video_path)
    if not p.exists():
        if st is not None:
            st.warning(f"路径不存在: {video_path}")
        return None
    if not _is_video_file(video_path):
        if st is not None:
            st.warning(f"不支持的文件格式: {video_path}")
        return None
    task_key = str(p.resolve())
    if task_key in st.session_state.tasks:
        if st is not None:
            st.warning(f"任务已存在: {video_path}")
        return None
    st.session_state.tasks[task_key] = TaskItem(
        video_id=p.stem,
        video_path=str(p.resolve()),
        status=STATUS_PENDING,
        config_path=config_path,
        work_dir=work_dir,
    )
    st.session_state.queue.append(task_key)
    return task_key


def _add_task_from_upload(
    uploaded_file: Any, config_path: str, work_dir: str
) -> str | None:
    """Create a TaskItem from an uploaded file. Returns task key or None."""
    dest_path = _resolve_upload_path(uploaded_file.name, work_dir)
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    p = Path(dest_path)
    task_key = str(p.resolve())
    if task_key in st.session_state.tasks:
        return None
    st.session_state.tasks[task_key] = TaskItem(
        video_id=p.stem,
        video_path=str(p.resolve()),
        status=STATUS_PENDING,
        config_path=config_path,
        work_dir=work_dir,
    )
    st.session_state.queue.append(task_key)
    return task_key


def _add_batch_tasks(directory: str, config_path: str, work_dir: str) -> int:
    """Add all videos in a directory to the queue. Returns count added."""
    video_paths = _find_video_files(directory)
    added = 0
    for vp in video_paths:
        task_key = str(vp.resolve())
        if task_key not in st.session_state.tasks:
            st.session_state.tasks[task_key] = TaskItem(
                video_id=vp.stem,
                video_path=str(vp.resolve()),
                status=STATUS_PENDING,
                config_path=config_path,
                work_dir=work_dir,
            )
            st.session_state.queue.append(task_key)
            added += 1
    return added


# ---------------------------------------------------------------------------
# Left column — Navigation & settings
# ---------------------------------------------------------------------------


def _render_left_column() -> None:
    """Render the left navigation column."""
    if st is None:
        return

    st.markdown(
        '<div style="padding:0.5rem 0;">'
        '<span style="font-size:1.1rem;font-weight:700;color:#e0e0e0;">🧪 TensileAgent</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    # View switcher
    view_map = {
        "🔬 工作台": "workbench",
        "📋 历史": "history",
        "⚙️ 配置": "config",
    }
    selected_label = st.radio(
        "导航",
        options=list(view_map.keys()),
        index=0,
        label_visibility="collapsed",
        key="nav_radio",
        on_change=lambda: setattr(
            st.session_state,
            "view",
            view_map[st.session_state.nav_radio],
        ),
    )
    # Sync from session state
    current_label = [k for k, v in view_map.items() if v == st.session_state.view]
    if current_label and st.session_state.get("nav_radio") != current_label[0]:
        st.session_state.nav_radio = current_label[0]

    st.markdown('<div class="section-title">设置</div>', unsafe_allow_html=True)

    mock_mode = st.checkbox("Mock 推理模式", value=False, key="mock_checkbox")
    _set_mock_mode(mock_mode)

    work_dir = st.text_input("工作目录", value=".", key="work_dir_input")
    config_path = st.text_input("配置路径", value="agent/config.yaml", key="config_path_input")

    # Recent tasks list
    st.markdown('<div class="section-title">近期任务</div>', unsafe_allow_html=True)
    tasks = st.session_state.tasks
    if not tasks:
        st.markdown('<span class="info-text">暂无任务</span>', unsafe_allow_html=True)
    else:
        # Show last 10 tasks (most recent first)
        recent_keys = list(tasks.keys())[-10:]
        active_key = st.session_state.active_task_id
        for tk in reversed(recent_keys):
            task = tasks[tk]
            cls = "task-item active" if tk == active_key else "task-item"
            status_badge = _status_badge_html(task.status)
            display_name = task.video_id[:20] + "…" if len(task.video_id) > 20 else task.video_id
            html = (
                f'<div class="{cls}" onclick="alert(\'streamlit click\')">'
                f'{status_badge} <span style="font-size:0.8rem;">{display_name}</span>'
                f"</div>"
            )
            st.markdown(html, unsafe_allow_html=True)
            # Use button as proxy for clickability
            if st.button(task.video_id, key=f"task_sel_{tk}", help="选择此任务"):
                st.session_state.active_task_id = tk


# ---------------------------------------------------------------------------
# Workbench view (center)
# ---------------------------------------------------------------------------


def _render_workbench() -> None:
    """Render the workbench view in the center column."""
    if st is None:
        return

    st.markdown(
        '<span style="font-size:1rem;font-weight:600;">🔬 工作台</span>',
        unsafe_allow_html=True,
    )

    # --- Input section ---
    st.markdown('<div class="section-title">单视频输入</div>', unsafe_allow_html=True)
    col_a, col_b = st.columns([1, 1])
    with col_a:
        uploaded = st.file_uploader(
            "上传视频",
            type=list(VIDEO_EXTENSIONS),
            label_visibility="collapsed",
            key="wb_uploader",
        )
    with col_b:
        text_path = st.text_input(
            "路径输入",
            placeholder="/path/to/video.mp4",
            label_visibility="collapsed",
            key="wb_text_path",
        )

    config_path = st.session_state.get("config_path_input", "agent/config.yaml")
    work_dir = st.session_state.get("work_dir_input", ".")

    if uploaded is not None:
        _add_task_from_upload(uploaded, config_path, work_dir)
        st.rerun()

    if text_path:
        _add_task_from_path(text_path, config_path, work_dir)
        # Clear the input after adding
        st.session_state.wb_text_path = ""

    # --- Batch input ---
    st.markdown('<div class="section-title">批量输入</div>', unsafe_allow_html=True)
    batch_dir = st.text_input(
        "视频目录",
        placeholder="/path/to/videos/",
        label_visibility="collapsed",
        key="wb_batch_dir",
    )
    if batch_dir:
        p = Path(batch_dir)
        if not p.exists():
            st.warning(f"目录不存在: {batch_dir}")
        elif not p.is_dir():
            st.warning(f"路径不是目录: {batch_dir}")
        else:
            found = _find_video_files(batch_dir)
            st.markdown(
                f'<span class="info-text">发现 {len(found)} 个视频文件</span>',
                unsafe_allow_html=True,
            )
            if found and st.button("添加到队列", key="add_batch_btn"):
                added = _add_batch_tasks(batch_dir, config_path, work_dir)
                if added > 0:
                    st.success(f"已添加 {added} 个任务到队列")
                    st.rerun()

    # --- Queue ---
    st.markdown('<div class="section-title">待分析队列</div>', unsafe_allow_html=True)
    queue = st.session_state.queue
    if not queue:
        st.markdown('<span class="info-text">队列为空</span>', unsafe_allow_html=True)
    else:
        for i, task_key in enumerate(queue):
            task = st.session_state.tasks.get(task_key)
            if task:
                cols = st.columns([3, 1])
                cols[0].markdown(
                    f'<span style="font-size:0.8rem;">{i+1}. {task.video_id}</span>',
                    unsafe_allow_html=True,
                )
                if cols[1].button("移除", key=f"remove_q_{task_key}"):
                    if task_key in st.session_state.queue:
                        st.session_state.queue.remove(task_key)
                    st.rerun()
        if st.button("清空队列", key="clear_queue_btn"):
            st.session_state.queue = []
            st.rerun()

    # --- Run button ---
    st.markdown("<hr>", unsafe_allow_html=True)
    run_disabled = len(queue) == 0
    if st.button(
        "▶ 运行队列" if not run_disabled else "▶ 运行队列 (队列为空)",
        disabled=run_disabled,
        use_container_width=True,
        key="run_queue_btn",
    ):
        # Switch active task to first in queue
        if queue:
            st.session_state.active_task_id = queue[0]
        st.session_state.run_triggered = True
        st.rerun()


# ---------------------------------------------------------------------------
# History view (center)
# ---------------------------------------------------------------------------


def _render_history() -> None:
    """Render the history view in the center column."""
    if st is None:
        return

    st.markdown(
        '<span style="font-size:1rem;font-weight:600;">📋 历史</span>',
        unsafe_allow_html=True,
    )

    tasks = st.session_state.tasks
    if not tasks:
        st.markdown('<span class="info-text">暂无历史记录</span>', unsafe_allow_html=True)
        return

    # Search & filter
    col1, col2 = st.columns([2, 1])
    with col1:
        search_query = st.text_input(
            "搜索",
            placeholder="按 video_id 过滤…",
            label_visibility="collapsed",
            key="history_search",
        )
    with col2:
        status_filter = st.selectbox(
            "状态",
            options=["全部", STATUS_COMPLETED, STATUS_FAILED],
            label_visibility="collapsed",
            key="history_status_filter",
        )

    # Filter tasks
    filtered_keys = []
    for tk, task in tasks.items():
        if search_query and search_query.lower() not in task.video_id.lower():
            continue
        if status_filter == STATUS_COMPLETED and task.status != STATUS_COMPLETED:
            continue
        if status_filter == STATUS_FAILED and task.status != STATUS_FAILED:
            continue
        filtered_keys.append(tk)

    if not filtered_keys:
        st.markdown('<span class="info-text">无匹配任务</span>', unsafe_allow_html=True)
        return

    for tk in reversed(filtered_keys):
        task = tasks[tk]
        with st.expander(f"{task.video_id} — {_status_badge_html(task.status)}", unsafe_allow_html=True):
            # Show events
            if task.events:
                st.markdown(
                    '<div style="font-size:0.8rem;font-weight:600;margin-bottom:0.3rem;">事件日志</div>',
                    unsafe_allow_html=True,
                )
                event_lines = []
                for evt in task.events[-30:]:
                    summary = _format_event_summary(evt)
                    event_lines.append(f"[{evt.get('event_type', '?')}] {summary}")
                st.markdown(
                    _event_log_html("\n".join(event_lines)),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<span class="info-text">无事件记录</span>', unsafe_allow_html=True)

            # Show result
            if task.result is not None:
                st.markdown(
                    '<div style="font-size:0.8rem;font-weight:600;margin-top:0.5rem;margin-bottom:0.3rem;">结果</div>',
                    unsafe_allow_html=True,
                )
                _render_result_card(task.result)
                # Export buttons for this task
                _render_export_buttons([task.result], prefix=f"hist_{tk}")
            elif task.error:
                st.error(f"错误: {task.error}")


# ---------------------------------------------------------------------------
# Config view (center)
# ---------------------------------------------------------------------------


def _render_config() -> None:
    """Render the config view in the center column."""
    if st is None:
        return

    st.markdown(
        '<span style="font-size:1rem;font-weight:600;">⚙️ 配置</span>',
        unsafe_allow_html=True,
    )

    try:
        cfg = runner.load_config("agent/config.yaml")
    except Exception as e:
        st.error(f"无法加载配置: {e}")
        return

    agent_cfg = cfg.get("agent", {})
    backend_cfg = cfg.get("backend", {})

    st.markdown('<div class="section-title">Agent 参数</div>', unsafe_allow_html=True)
    rows = [
        ("最大轮次", agent_cfg.get("max_rounds", "—")),
        ("容差 (秒)", agent_cfg.get("tolerance_seconds", "—")),
        ("置信度阈值", agent_cfg.get("confidence_threshold", "—")),
        ("低置信度最大轮次", agent_cfg.get("max_low_conf_rounds", "—")),
        ("温度", agent_cfg.get("temperature", "—")),
        ("后端模式", agent_cfg.get("backend", "—")),
    ]
    for label, value in rows:
        cols = st.columns([2, 3])
        cols[0].markdown(
            f'<span style="font-size:0.85rem;color:#888;">{label}</span>',
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f'<span style="font-size:0.85rem;">{value}</span>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">LLM 远程端点</div>', unsafe_allow_html=True)
    remote = agent_cfg.get("remote", {})
    api_key = remote.get("api_key")
    api_key_display = "✅ 已配置" if api_key else "❌ 未配置"
    rows = [
        ("Provider", remote.get("provider", "—")),
        ("模型", remote.get("model", "—")),
        ("Base URL", remote.get("base_url", "—")),
        ("API Key", api_key_display),
    ]
    for label, value in rows:
        cols = st.columns([2, 3])
        cols[0].markdown(
            f'<span style="font-size:0.85rem;color:#888;">{label}</span>',
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f'<span style="font-size:0.85rem;">{value}</span>',
            unsafe_allow_html=True,
        )

    if agent_cfg.get("backend") == "local":
        st.markdown('<div class="section-title">LLM 本地端点</div>', unsafe_allow_html=True)
        local = agent_cfg.get("local", {})
        rows = [
            ("Provider", local.get("provider", "—")),
            ("模型", local.get("model", "—")),
            ("Base URL", local.get("base_url", "—")),
        ]
        for label, value in rows:
            cols = st.columns([2, 3])
            cols[0].markdown(
                f'<span style="font-size:0.85rem;color:#888;">{label}</span>',
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f'<span style="font-size:0.85rem;">{value}</span>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="section-title">微调模型后端</div>', unsafe_allow_html=True)
    rows = [
        ("名称", backend_cfg.get("name", "—")),
        ("基础模型", backend_cfg.get("base_model", "—")),
        ("Adapter 基目录", backend_cfg.get("adapter_base_dir", "—")),
        ("Adapter 模式", backend_cfg.get("adapter_pattern", "—")),
    ]
    for label, value in rows:
        cols = st.columns([2, 3])
        cols[0].markdown(
            f'<span style="font-size:0.85rem;color:#888;">{label}</span>',
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f'<span style="font-size:0.85rem;">{value}</span>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Right column — Status panel
# ---------------------------------------------------------------------------


def _render_status_panel() -> None:
    """Render the right column status panel for the active task."""
    if st is None:
        return

    st.markdown(
        '<span style="font-size:1rem;font-weight:600;">📊 状态面板</span>',
        unsafe_allow_html=True,
    )

    active_id = st.session_state.active_task_id
    if active_id is None or active_id not in st.session_state.tasks:
        # No active task, show placeholder
        st.markdown(
            '<div style="text-align:center;padding:2rem 0;">'
            '<span class="info-text">选择左侧任务查看详情</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    task = st.session_state.tasks[active_id]

    # Task info card
    st.markdown(
        f'<div style="background:#1a1d24;border:1px solid #2e3138;border-radius:4px;padding:0.5rem;margin-bottom:0.5rem;">'
        f'<div style="font-size:0.85rem;font-weight:600;">{task.video_id}</div>'
        f'<div style="font-size:0.75rem;color:#888;">{task.video_path}</div>'
        f'<div style="margin-top:0.3rem;">{_status_badge_html(task.status)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # Events timeline (last 30)
    if task.events:
        st.markdown(
            '<div style="font-size:0.8rem;font-weight:600;margin-bottom:0.3rem;">事件流</div>',
            unsafe_allow_html=True,
        )
        event_lines = []
        for evt in task.events[-30:]:
            et = evt.get("event_type", "?")
            summary = _format_event_summary(evt)
            event_lines.append(f"[{et}] {summary}")
        st.markdown(
            _event_log_html("\n".join(event_lines)),
            unsafe_allow_html=True,
        )

    # Result
    if task.result is not None:
        st.markdown(
            '<div style="font-size:0.8rem;font-weight:600;margin-top:0.5rem;margin-bottom:0.3rem;">结果</div>',
            unsafe_allow_html=True,
        )
        _render_result_card(task.result)
        _render_export_buttons([task.result], prefix="right")
    elif task.error:
        st.markdown(
            f'<div class="result-card result-failed">'
            f'<strong style="color:#ef4444;">❌ 失败</strong><br>'
            f'<span style="font-size:0.8rem;">{task.error}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_result_card(result: dict[str, Any]) -> None:
    """Render a result card in the UI."""
    if st is None:
        return
    inner = result.get("result", {}) if isinstance(result, dict) else {}
    if not isinstance(inner, dict):
        inner = {}
    status = inner.get("status", "")
    ok = result.get("ok", True)

    if not ok:
        error = result.get("error", {})
        if isinstance(error, dict):
            stage = error.get("stage", "unknown")
            code = error.get("code", "")
            msg = error.get("message", "")
        else:
            stage = "unknown"
            code = "error"
            msg = str(error)
        st.markdown(
            f'<div class="result-card result-failed">'
            f'<strong style="color:#ef4444;">🔴 失败</strong><br>'
            f'<span style="font-size:0.8rem;">阶段: {stage}</span><br>'
            f'<span style="font-size:0.8rem;">代码: {code}</span><br>'
            f'<span style="font-size:0.8rem;">信息: {msg}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        # Collapsible JSON for full result
        with st.expander("完整 result (JSON)"):
            st.json(result)
        return

    if status == "fracture":
        time_range = inner.get("time_range", [])
        time_str = f"{time_range[0]:.2f}s–{time_range[1]:.2f}s" if len(time_range) == 2 else "—"
        fracture_type = inner.get("fracture_type", "—")
        location = inner.get("location", "—")
        confidence = inner.get("confidence", 0.0)
        rounds = result.get("rounds", 0)
        st.markdown(
            f'<div class="result-card result-fracture">'
            f'<span style="color:#22c55e;font-size:1rem;">🟢 断裂</span><br>'
            f'<span style="font-size:0.8rem;">时间区间: {time_str}</span><br>'
            f'<span style="font-size:0.8rem;">类型: {fracture_type}</span><br>'
            f'<span style="font-size:0.8rem;">位置: {location}</span><br>'
            f'<span style="font-size:0.8rem;">置信度: {confidence:.3f}</span><br>'
            f'<span style="font-size:0.8rem;">轮次: {rounds}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
    elif status == "no_fracture":
        confidence = inner.get("confidence", 0.0)
        rounds = result.get("rounds", 0)
        st.markdown(
            f'<div class="result-card result-no_fracture">'
            f'<span style="color:#3b82f6;font-size:1rem;">🔵 未断裂</span><br>'
            f'<span style="font-size:0.8rem;">置信度: {confidence:.3f}</span><br>'
            f'<span style="font-size:0.8rem;">轮次: {rounds}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
    elif status == "unrecognized":
        reason = inner.get("unrecognized_reason", "—")
        rounds = result.get("rounds", 0)
        st.markdown(
            f'<div class="result-card result-unrecognized">'
            f'<span style="color:#eab308;font-size:1rem;">🟡 未识别</span><br>'
            f'<span style="font-size:0.8rem;">原因: {reason}</span><br>'
            f'<span style="font-size:0.8rem;">轮次: {rounds}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="result-card">'
            f'<span style="font-size:0.85rem;">未知状态: {status}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

    # Collapsible JSON for full result
    with st.expander("完整 result (JSON)"):
        # Expose only FinalOutput-level fields, not internal diagnostics
        fo_fields = {
            "video_id", "status", "time_range", "fracture_type",
            "location", "confidence", "unrecognized_reason",
        }
        safe = {k: v for k, v in inner.items() if k in fo_fields} if isinstance(inner, dict) else inner
        st.json({"result": safe})


def _render_export_buttons(results: list[dict[str, Any]], prefix: str = "export") -> None:
    """Render export download buttons for a list of results."""
    if st is None:
        return
    if not results:
        return
    cols = st.columns(3)
    cols[0].download_button(
        label="JSONL",
        data=_export_jsonl(results),
        file_name="results.jsonl",
        mime="application/jsonl",
        key=f"{prefix}_jsonl",
    )
    cols[1].download_button(
        label="CSV",
        data=_export_csv(results),
        file_name="results.csv",
        mime="text/csv",
        key=f"{prefix}_csv",
    )
    cols[2].download_button(
        label="JSON",
        data=_export_json(results),
        file_name="results.json",
        mime="application/json",
        key=f"{prefix}_json",
    )


# ---------------------------------------------------------------------------
# Run logic (right column only)
# ---------------------------------------------------------------------------


def _run_single_task(task_key: str, right_placeholder: Any) -> None:
    """Run a single task, rendering progress into ``right_placeholder``."""
    if st is None:
        return
    task = st.session_state.tasks.get(task_key)
    if task is None:
        return

    task.status = STATUS_RUNNING

    def event_callback(event: dict[str, Any]) -> None:
        task.events.append(event)
        # Re-render status panel
        with right_placeholder.container():
            _render_status_panel()

    st.session_state.active_task_id = task_key

    result = runner.run_one(
        task.video_path,
        task.config_path,
        event_callback=event_callback,
        work_dir=task.work_dir,
    )

    if result.get("ok"):
        task.status = STATUS_COMPLETED
        task.result = result
    else:
        task.status = STATUS_FAILED
        task.result = result
        error = result.get("error", {})
        if isinstance(error, dict):
            task.error = error.get("message", str(error))
        else:
            task.error = str(error)

    with right_placeholder.container():
        _render_status_panel()
        if task.status == STATUS_COMPLETED:
            st.success(f"✅ {task.video_id} 完成")
        else:
            st.error(f"❌ {task.video_id} 失败")


def _process_queue() -> None:
    """Process all tasks in the queue."""
    if st is None:
        return

    queue = st.session_state.queue[:]  # copy
    if not queue:
        return

    st.session_state.queue = []

    right_placeholder = st.empty()

    if len(queue) == 1:
        # Single task
        _run_single_task(queue[0], right_placeholder)
    else:
        # Batch — show progress in right column
        total = len(queue)
        completed = 0
        progress_bar = right_placeholder.progress(0.0)
        status_text = right_placeholder.empty()

        for task_key in queue:
            task = st.session_state.tasks.get(task_key)
            if task is None:
                continue
            task.status = STATUS_RUNNING
            st.session_state.active_task_id = task_key

            def make_callback(tk: str) -> Any:
                def cb(event: dict) -> None:
                    t = st.session_state.tasks.get(tk)
                    if t is not None:
                        t.events.append(event)
                    with right_placeholder.container():
                        progress_bar.progress(completed / total)
                        status_text.text(f"处理中 {completed + 1}/{total}: {tk}")
                        _render_status_panel()
                return cb

            result = runner.run_one(
                task.video_path,
                task.config_path,
                event_callback=make_callback(task_key),
                work_dir=task.work_dir,
            )

            if result.get("ok"):
                task.status = STATUS_COMPLETED
                task.result = result
            else:
                task.status = STATUS_FAILED
                task.result = result
                error = result.get("error", {})
                if isinstance(error, dict):
                    task.error = error.get("message", str(error))
                else:
                    task.error = str(error)

            completed += 1
            with right_placeholder.container():
                progress_bar.progress(completed / total)
                status_text.text(f"已完成 {completed}/{total}")
                _render_status_panel()

        with right_placeholder.container():
            progress_bar.progress(1.0)
            status_text.text(f"批量完成: {completed}/{total}")
            _render_status_panel()
            st.success(f"🎉 完成 {completed}/{total} 个任务")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


def main() -> None:
    """Build and run the Streamlit workbench."""
    if st is None:
        print(
            "Streamlit is not installed. Install it with: pip install streamlit",
            file=sys.stderr,
        )
        sys.exit(1)

    st.set_page_config(page_title="TensileAgent Workbench", layout="wide")

    # Apply dark theme CSS
    st.markdown(_DARK_CSS, unsafe_allow_html=True)

    _init_session_state()

    # Handle run trigger (from workbench run button)
    if st.session_state.get("run_triggered"):
        st.session_state.run_triggered = False
        _process_queue()
        st.rerun()

    # Three-column layout
    left_col, center_col, right_col = st.columns([1.2, 2.5, 1.8])

    with left_col:
        _render_left_column()

    with center_col:
        view = st.session_state.view
        if view == "workbench":
            _render_workbench()
        elif view == "history":
            _render_history()
        elif view == "config":
            _render_config()

    with right_col:
        _render_status_panel()


if __name__ == "__main__":
    main()
