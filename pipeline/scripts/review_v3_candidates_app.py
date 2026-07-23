#!/usr/bin/env python3
"""Streamlit UI for queue-bound v3 candidate review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from pipeline.v3_labels import (
    CLIP_STATES,
    FRACTURE_MECHANISMS,
    LOCATIONS,
    SPECIAL_CASES,
    canonicalize_v3_labels,
)
from pipeline.v3_review_workflow import (
    V3ReviewWorkflowError,
    freeze_completed_batch,
    historical_context,
    load_draft,
    load_reference_records,
    load_review_queue,
    new_decision,
    save_draft,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw:
        raw = raw[raw.index("--") + 1 :]
    parser = argparse.ArgumentParser(description="v3 候选媒体人工复检 UI")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--review-reference", type=Path)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reviewer-id")
    return parser.parse_args(raw)


def _default_paths(
    project_root: Path, media_id: str, selected_ids_sha256: str
) -> tuple[Path, Path]:
    root = project_root / "data/07_metadata/v3/review_decisions" / media_id
    workspace = root / f"workspace-{selected_ids_sha256[:12]}"
    return workspace / "draft.json", root


def _option_index(options: list[Any], value: Any) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def main() -> None:
    st.set_page_config(page_title="v3 人工复检", layout="wide")
    args = _parse_args()
    try:
        identity, candidates = load_review_queue(
            args.queue,
            manifest_path=args.manifest,
            project_root=args.project_root,
            candidate_ids=args.candidate_id,
            limit=args.limit,
        )
        references = load_reference_records(args.review_reference)
        default_draft, default_output_root = _default_paths(
            args.project_root.resolve(),
            identity["media_id"],
            identity["selected_candidate_ids_sha256"],
        )
        draft_path = (args.draft or default_draft).resolve()
        output_root = (args.output_root or default_output_root).resolve()
        decisions = load_draft(draft_path, identity)
    except (V3ReviewWorkflowError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    st.title("v3 候选媒体人工复检")
    st.caption(
        f"media_id={identity['media_id']} · 选定 {len(candidates)}/"
        f"{identity['full_queue_count']} · 已完成 {len(decisions)}"
    )
    with st.expander("队列身份与隔离输出"):
        st.json(identity)
        st.write(f"草稿：`{draft_path}`")
        st.write(f"冻结目录：`{output_root}`")

    candidate_index = {item["candidate_id"]: item for item in candidates}
    candidate_ids = identity["selected_candidate_ids"]
    if "v3_review_candidate_id" not in st.session_state:
        st.session_state.v3_review_candidate_id = next(
            (item for item in candidate_ids if item not in decisions),
            candidate_ids[0],
        )
    selected_id = st.selectbox(
        "候选",
        candidate_ids,
        index=_option_index(
            candidate_ids, st.session_state.v3_review_candidate_id
        ),
        format_func=lambda item: (
            f"{'✅' if item in decisions else '❓'} {item} · "
            f"{candidate_index[item]['candidate_v3_labels']['clip_state']}"
        ),
    )
    st.session_state.v3_review_candidate_id = selected_id
    candidate = candidate_index[selected_id]
    existing = decisions.get(selected_id)
    historical_labels, historical_ids, historical_records = historical_context(
        candidate, references
    )

    media_col, form_col = st.columns([1.35, 1])
    with media_col:
        st.video(candidate["_resolved_video_path"])
        frames = [item["path"] for item in candidate["_resolved_frames"]]
        if frames:
            st.image(frames, caption=[Path(item).name for item in frames])
        with st.expander("实际帧映射"):
            st.json(candidate["actual_frame_mapping"])

    with form_col:
        st.subheader(candidate["candidate_id"])
        st.write(
            f"`{candidate['source_video']}` · {candidate['start_time']:.3f}s–"
            f"{candidate['end_time']:.3f}s · {candidate.get('window_role')}"
        )
        st.write("系统建议")
        st.json(candidate["candidate_v3_labels"])
        st.write("历史审查参考（只读，不自动批准）")
        if historical_records:
            st.json(historical_records)
        else:
            st.caption(f"未加载可用历史记录；候选引用 ID：{historical_ids or '无'}")
        if existing:
            st.write("已保存决定")
            st.json(existing)

        base_labels = (
            existing.get("effective_labels")
            if existing and existing.get("effective_labels") is not None
            else candidate["candidate_v3_labels"]
        )
        with st.form(f"v3-review-{selected_id}"):
            clip_states = sorted(CLIP_STATES)
            mechanisms = [None, *sorted(FRACTURE_MECHANISMS)]
            root_breaks = [None, False, True]
            locations = [None, *sorted(LOCATIONS)]
            special_cases = [None, *sorted(SPECIAL_CASES)]
            clip_state = st.selectbox(
                "clip_state",
                clip_states,
                index=_option_index(clip_states, base_labels["clip_state"]),
            )
            fracture_mechanism = st.selectbox(
                "fracture_mechanism",
                mechanisms,
                index=_option_index(
                    mechanisms, base_labels["fracture_mechanism"]
                ),
            )
            root_break = st.selectbox(
                "root_break",
                root_breaks,
                index=_option_index(root_breaks, base_labels["root_break"]),
            )
            location = st.selectbox(
                "location",
                locations,
                index=_option_index(locations, base_labels["location"]),
            )
            special_case = st.selectbox(
                "special_case",
                special_cases,
                index=_option_index(
                    special_cases, base_labels["special_case"]
                ),
            )
            notes = st.text_area(
                "reviewer_notes",
                value=str((existing or {}).get("reviewer_notes") or ""),
            )
            approve = st.form_submit_button("批准当前标签", type="primary")
            drop = st.form_submit_button("丢弃")
            regenerate = st.form_submit_button("需要重新生成")

        if approve or drop or regenerate:
            try:
                if approve:
                    edited = canonicalize_v3_labels(
                        {
                            "clip_state": clip_state,
                            "fracture_mechanism": fracture_mechanism,
                            "root_break": root_break,
                            "location": location,
                            "special_case": special_case,
                        }
                    )
                    proposed = candidate["candidate_v3_labels"]
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
            except (V3ReviewWorkflowError, ValueError) as exc:
                st.error(str(exc))
                st.stop()
            st.success(f"已原子保存草稿：{draft_path}")
            remaining = [item for item in candidate_ids if item not in decisions]
            if remaining:
                st.session_state.v3_review_candidate_id = remaining[0]
            st.rerun()

    st.divider()
    remaining_count = len(candidate_ids) - len(decisions)
    if st.button("冻结已完成的选定队列", disabled=remaining_count != 0):
        try:
            batch_dir = freeze_completed_batch(
                output_root, identity, decisions
            )
        except (V3ReviewWorkflowError, ValueError, FileExistsError) as exc:
            st.error(str(exc))
            st.stop()
        st.success(f"已冻结不可覆盖批次：{batch_dir}")
    if remaining_count:
        st.info(f"还有 {remaining_count} 条未形成终态决定，暂不能冻结。")


if __name__ == "__main__":
    main()
