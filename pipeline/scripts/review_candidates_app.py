#!/usr/bin/env python3
"""Streamlit UI for queue-bound v4.1 candidate review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from pipeline.current_data import data_context_from_arg
from pipeline.v4_1_labels import (
    CLIP_STATES,
    canonicalize_v4_1_labels,
)
from pipeline.v3_labels import FRACTURE_MECHANISMS, SPECIAL_CASES
from pipeline.v4_labels import FRACTURE_SITES
from pipeline.v4_1_review_workflow import (
    V4_1ReviewWorkflowError,
    freeze_completed_batch,
    historical_context,
    load_draft,
    load_reference_records,
    load_review_queue,
    new_decision,
    save_draft,
)
from pipeline.v4_1_review_routing import (
    ReviewRoutingError,
    load_manual_candidate_ids,
)

STATUS_FILTERS = {
    "未审核": None,
    "全部": "all",
    "已批准": "approved",
    "已修正": "corrected",
    "已丢弃": "dropped",
    "需重新生成": "needs_regenerate",
}
STATUS_EMOJI = {
    None: "○",
    "approved": "✓",
    "corrected": "✎",
    "dropped": "×",
    "needs_regenerate": "↻",
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw:
        raw = raw[raw.index("--") + 1 :]
    parser = argparse.ArgumentParser(description="v4.1 候选媒体人工复检 UI")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--review-reference", type=Path)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--routing-manifest", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reviewer-id")
    args = parser.parse_args(raw)
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    args.project_root = args.project_root or context.root
    args._data_context = context
    return args


def _default_paths(
    output_root: Path, queue_id: str, selected_ids_sha256: str
) -> tuple[Path, Path]:
    root = output_root / queue_id
    workspace = root / f"workspace-{selected_ids_sha256[:12]}"
    return workspace / "draft.json", root


def _option_index(options: list[Any], value: Any) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _decision_status(
    candidate_id: str, decisions: dict[str, dict[str, Any]]
) -> str | None:
    decision = decisions.get(candidate_id)
    return str(decision["review_status"]) if decision else None


def review_counts(
    candidate_ids: list[str], decisions: dict[str, dict[str, Any]]
) -> dict[str, int]:
    counts = {
        "total": len(candidate_ids),
        "reviewed": 0,
        "remaining": 0,
        "approved": 0,
        "corrected": 0,
        "dropped": 0,
        "needs_regenerate": 0,
    }
    for candidate_id in candidate_ids:
        status = _decision_status(candidate_id, decisions)
        if status is None:
            counts["remaining"] += 1
        else:
            counts["reviewed"] += 1
            if status in counts:
                counts[status] += 1
    return counts


def filter_candidate_ids(
    candidates: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    status_filter: str,
    source_filter: str | None,
    search: str,
) -> list[str]:
    wanted_status = STATUS_FILTERS[status_filter]
    query = search.strip().lower()
    result: list[str] = []
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        source_video = str(candidate["source_video"])
        status = _decision_status(candidate_id, decisions)
        if wanted_status != "all" and status != wanted_status:
            continue
        if source_filter is not None and source_video != source_filter:
            continue
        if query and query not in candidate_id.lower() and query not in source_video.lower():
            continue
        result.append(candidate_id)
    return result


def next_unreviewed_id(
    candidate_ids: list[str],
    decisions: dict[str, dict[str, Any]],
    *,
    after_id: str | None = None,
) -> str | None:
    if not candidate_ids:
        return None
    start = 0
    if after_id in candidate_ids:
        start = candidate_ids.index(after_id) + 1
    ordered = candidate_ids[start:] + candidate_ids[:start]
    return next(
        (
            candidate_id
            for candidate_id in ordered
            if candidate_id not in decisions
        ),
        None,
    )


def _candidate_label(
    candidate: dict[str, Any], decisions: dict[str, dict[str, Any]]
) -> str:
    candidate_id = str(candidate["candidate_id"])
    status = _decision_status(candidate_id, decisions)
    return (
        f"{STATUS_EMOJI[status]} {candidate['source_video']} · "
        f"{candidate.get('window_role', 'clip')} · "
        f"{float(candidate['start_time']):.2f}–{float(candidate['end_time']):.2f}s"
    )


def render_review_media(candidate: dict[str, Any]) -> None:
    """Show the model-observed frames first and keep video as optional context."""
    st.subheader(str(candidate["source_video"]))
    st.caption(
        f"{float(candidate['start_time']):.3f}s–"
        f"{float(candidate['end_time']):.3f}s · "
        f"{candidate.get('window_role', 'clip')}"
    )
    frames = [item["path"] for item in candidate["_resolved_frames"]]
    timestamps = list(candidate["_actual_sampled_timestamps"])
    st.markdown("#### 模型采样帧")
    st.caption("请优先依据这些按时间顺序排列的画面审查。")
    if frames:
        frame_columns = st.columns(min(2, len(frames)))
        for index, frame_path in enumerate(frames):
            timestamp = timestamps[index] if index < len(timestamps) else None
            caption = f"第 {index + 1} 帧"
            if timestamp is not None:
                caption += f" · {float(timestamp):.3f}s"
            frame_columns[index % len(frame_columns)].image(
                frame_path,
                caption=caption,
                use_container_width=True,
            )
    with st.expander("辅助查看：连续视频", expanded=False):
        st.caption("仅在采样帧存在时序歧义时展开查看。")
        st.video(candidate["_resolved_video_path"])
    with st.expander("实际帧映射", expanded=False):
        st.dataframe(
            candidate["actual_frame_mapping"],
            use_container_width=True,
            hide_index=True,
        )


@st.cache_data(show_spinner="正在验证复检队列和媒体…")
def _cached_review_queue(
    queue_path: str,
    project_root: str,
    candidate_ids: tuple[str, ...],
    limit: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return load_review_queue(
        Path(queue_path),
        project_root=Path(project_root),
        candidate_ids=candidate_ids,
        limit=limit,
    )


@st.cache_data(show_spinner=False)
def _cached_reference_records(path: str | None) -> dict[str, dict[str, Any]]:
    return load_reference_records(Path(path) if path is not None else None)


def main() -> None:
    st.set_page_config(page_title="v4.1 人工复检", layout="wide")
    args = _parse_args()
    try:
        if args.routing_manifest is not None and args.candidate_id:
            raise V4_1ReviewWorkflowError(
                "--routing-manifest 与 --candidate-id 不能同时使用"
            )
        candidate_ids = list(args.candidate_id)
        if args.routing_manifest is not None:
            candidate_ids = load_manual_candidate_ids(
                args.routing_manifest,
                queue_path=args.queue,
            )
        identity, candidates = _cached_review_queue(
            str(args.queue.resolve()),
            str(args.project_root.resolve()),
            tuple(candidate_ids),
            args.limit,
        )
        references = _cached_reference_records(
            str(args.review_reference.resolve()) if args.review_reference else None
        )
        review_root = args._data_context.metadata_collection(
            "review_decisions"
        )
        default_draft, default_output_root = _default_paths(
            review_root,
            identity["queue_id"],
            identity["selected_candidate_ids_sha256"],
        )
        draft_path = args._data_context.require_managed_output(
            args.draft or default_draft,
            review_root,
            label="review draft output",
        )
        output_root = args._data_context.require_managed_output(
            args.output_root or default_output_root,
            review_root,
            label="review decisions output",
        )
        decisions = load_draft(draft_path, identity)
    except (ReviewRoutingError, V4_1ReviewWorkflowError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    candidate_index = {item["candidate_id"]: item for item in candidates}
    candidate_ids = identity["selected_candidate_ids"]
    counts = review_counts(candidate_ids, decisions)
    completed_batch: Path | None = None
    freeze_error: str | None = None
    if counts["remaining"] == 0:
        try:
            completed_batch = freeze_completed_batch(
                output_root, identity, decisions
            )
        except (V4_1ReviewWorkflowError, ValueError, FileExistsError) as exc:
            freeze_error = str(exc)

    st.title("v4.1 人工复检")
    metric_columns = st.columns(6)
    for column, label, value in zip(
        metric_columns,
        ("总数", "已完成", "待审核", "批准", "修正", "需重生成"),
        (
            counts["total"],
            counts["reviewed"],
            counts["remaining"],
            counts["approved"],
            counts["corrected"],
            counts["needs_regenerate"],
        ),
        strict=True,
    ):
        column.metric(label, value)
    if completed_batch is not None:
        st.success("全部候选已审核完成，结果已安全保存。")
    elif freeze_error is not None:
        st.warning(f"全部决定已保存，但最终汇总暂未完成：{freeze_error}")

    with st.sidebar:
        st.subheader("筛选")
        status_filter = st.selectbox(
            "审核状态",
            list(STATUS_FILTERS),
            index=0,
            key="v4_status_filter",
        )
        source_options = [
            None,
            *sorted({str(item["source_video"]) for item in candidates}),
        ]
        source_filter = st.selectbox(
            "源视频",
            source_options,
            format_func=lambda value: "全部源视频" if value is None else value,
            key="v4_source_filter",
        )
        search = st.text_input(
            "搜索候选或源视频",
            key="v4_candidate_search",
        )
        with st.expander("技术信息（一般无需查看）", expanded=False):
            st.caption(f"V4 队列：{identity['queue_id']}")
            if identity.get("review_scope") is not None:
                st.caption(f"审查隔离域：{identity['review_scope']}")
            st.caption(f"草稿：{draft_path}")
            st.caption(f"结果目录：{output_root}")

    filtered_ids = filter_candidate_ids(
        candidates,
        decisions,
        status_filter=status_filter,
        source_filter=source_filter,
        search=search,
    )
    if not filtered_ids:
        st.info("当前筛选没有候选。请切换审核状态、源视频或清空搜索条件。")
        return

    if "v4_review_candidate_id" not in st.session_state:
        st.session_state.v4_review_candidate_id = (
            next_unreviewed_id(candidate_ids, decisions) or candidate_ids[0]
        )
    if st.session_state.v4_review_candidate_id not in filtered_ids:
        st.session_state.v4_review_candidate_id = filtered_ids[0]

    list_col, media_col, form_col = st.columns([0.8, 1.35, 1])
    with list_col:
        st.subheader(f"候选列表 · {len(filtered_ids)}")
        selected_id = st.selectbox(
            "选择候选",
            filtered_ids,
            index=_option_index(
                filtered_ids, st.session_state.v4_review_candidate_id
            ),
            format_func=lambda item: _candidate_label(
                candidate_index[item], decisions
            ),
            label_visibility="collapsed",
        )
        st.session_state.v4_review_candidate_id = selected_id
        current_index = filtered_ids.index(selected_id)
        previous_col, next_col = st.columns(2)
        if previous_col.button(
            "上一条",
            disabled=current_index == 0,
            use_container_width=True,
        ):
            st.session_state.v4_review_candidate_id = filtered_ids[
                current_index - 1
            ]
            st.rerun()
        if next_col.button(
            "下一条",
            disabled=current_index >= len(filtered_ids) - 1,
            use_container_width=True,
        ):
            st.session_state.v4_review_candidate_id = filtered_ids[
                current_index + 1
            ]
            st.rerun()
        st.caption(f"{current_index + 1} / {len(filtered_ids)}")

    candidate = candidate_index[selected_id]
    existing = decisions.get(selected_id)
    independent_review = (
        identity.get("labels_are_truth") is False
        and candidate.get("labels_are_truth") is False
    )
    historical_labels, historical_ids, historical_records = historical_context(
        candidate, references
    )

    with media_col:
        render_review_media(candidate)

    with form_col:
        st.subheader("标签确认")
        proposed = candidate["candidate_v4_labels"]
        site_labels = {
            "inside_gauge": "标距内",
            "outside_gauge_non_root": "标距外（非齐根）",
            "grip_root": "夹具根部齐根",
            None: "位置未知",
        }
        suggestion_prefix = (
            "历史标签提示（不是真值）："
            if independent_review
            else "系统建议："
        )
        st.caption(
            suggestion_prefix + f"{proposed['clip_state']} · "
            f"{proposed['fracture_mechanism'] or '机制未知'} · "
            f"{site_labels[proposed['fracture_site']]}"
        )
        if independent_review:
            st.warning("请仅依据当前采样帧独立选择四个字段，不能直接批准历史标签提示。")
        with st.expander(
            f"历史参考 · {len(historical_records)} 条",
            expanded=False,
        ):
            if historical_labels is not None:
                st.caption("历史记录存在一致的 v4 标签建议。")
                st.json(historical_labels, expanded=False)
            elif historical_records:
                st.caption("历史记录存在，但没有一致的 v4 标签建议。")
            else:
                st.caption("当前候选没有可用的历史参考。")
            if historical_ids:
                st.caption("参考 ID")
                st.code("\n".join(historical_ids))
        if existing:
            st.info(f"当前已保存：{existing['review_status']}")

        if existing and existing.get("effective_labels") is not None:
            base_labels = existing["effective_labels"]
        elif independent_review:
            base_labels = None
        else:
            base_labels = candidate["candidate_v4_labels"]
        with st.form(f"v4-review-{selected_id}"):
            clip_states = (
                [None, *sorted(CLIP_STATES)]
                if independent_review
                else sorted(CLIP_STATES)
            )
            mechanisms = [None, *sorted(FRACTURE_MECHANISMS)]
            fracture_sites = [
                None,
                "inside_gauge",
                "outside_gauge_non_root",
                "grip_root",
            ]
            special_cases = [None, *sorted(SPECIAL_CASES)]
            clip_state = st.selectbox(
                "clip_state",
                clip_states,
                index=_option_index(
                    clip_states,
                    base_labels["clip_state"] if base_labels is not None else None,
                ),
                format_func=lambda value: "请选择状态" if value is None else value,
            )
            fracture_mechanism = st.selectbox(
                "fracture_mechanism",
                mechanisms,
                index=_option_index(
                    mechanisms,
                    (
                        base_labels["fracture_mechanism"]
                        if base_labels is not None
                        else None
                    ),
                ),
            )
            fracture_site = st.selectbox(
                "断裂位置",
                fracture_sites,
                index=_option_index(
                    fracture_sites,
                    base_labels["fracture_site"] if base_labels is not None else None,
                ),
                format_func=lambda value: site_labels[value],
            )
            special_case = st.selectbox(
                "special_case",
                special_cases,
                index=_option_index(
                    special_cases,
                    base_labels["special_case"] if base_labels is not None else None,
                ),
            )
            independently_checked = st.checkbox(
                "我已基于模型采样帧独立核对四个字段",
                value=not independent_review,
                disabled=not independent_review,
            )
            notes = st.text_area(
                "备注（丢弃或重新生成时必填）",
                value=str((existing or {}).get("reviewer_notes") or ""),
            )
            button_columns = st.columns(3)
            approve = button_columns[0].form_submit_button(
                "批准",
                type="primary",
                use_container_width=True,
            )
            drop = button_columns[1].form_submit_button(
                "丢弃",
                use_container_width=True,
            )
            regenerate = button_columns[2].form_submit_button(
                "需重生成",
                use_container_width=True,
            )

        if approve or drop or regenerate:
            try:
                if approve:
                    if clip_state is None:
                        raise V4_1ReviewWorkflowError("必须明确选择 clip_state")
                    if independent_review and not independently_checked:
                        raise V4_1ReviewWorkflowError(
                            "必须确认已基于采样帧独立核对四个字段"
                        )
                    edited = canonicalize_v4_1_labels(
                        {
                            "clip_state": clip_state,
                            "fracture_mechanism": fracture_mechanism,
                            "fracture_site": fracture_site,
                            "special_case": special_case,
                        }
                    )
                    proposed = candidate["candidate_v4_labels"]
                    status = "approved" if edited == proposed else "corrected"
                    corrected = None if status == "approved" else edited
                else:
                    status = "dropped" if drop else "needs_regenerate"
                    corrected = None
                decisions[selected_id] = new_decision(
                    candidate,
                    status=status,
                    corrected_labels=corrected,
                    historical_suggested_labels=historical_labels,
                    historical_reference_ids=historical_ids,
                    reviewer_notes=notes,
                    reviewer_id=args.reviewer_id,
                )
                save_draft(draft_path, identity, decisions)
            except (V4_1ReviewWorkflowError, ValueError) as exc:
                st.error(str(exc))
                st.stop()
            next_candidate = next_unreviewed_id(
                candidate_ids,
                decisions,
                after_id=selected_id,
            )
            if next_candidate is not None:
                st.session_state.v4_review_candidate_id = next_candidate
            st.rerun()


if __name__ == "__main__":
    main()
