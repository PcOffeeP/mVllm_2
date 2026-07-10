#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子视频人工审查 UI（Streamlit）。

用途：
    为训练级或测试级子视频 metadata 提供本地人工审查界面，输出统一的审查决策
    JSON 文件，供下游 apply_review_decisions.py 使用。

运行方式：
    streamlit run pipeline/scripts/review_subvideos_app.py -- \
        --metadata data/07_metadata/subvideos_meta.json

    测试级：
    streamlit run pipeline/scripts/review_subvideos_app.py -- \
        --metadata data/07_metadata/test_subvideos_meta.json

输出路径：
    - 输入为 subvideos_meta.json 时，输出
      data/07_metadata/subvideo_train_review_decisions.json
    - 输入为 test_subvideos_meta.json 时，输出
      data/07_metadata/subvideo_test_review_decisions.json

输出格式：
    {
      "decisions": [
        {
          "subvideo_id": "<子视频 ID>",
          "status": "approved" | "dropped" | "needs_regenerate",
          "reviewed_at": "<ISO 8601 UTC 时间>",
          "reviewer_notes": "<人工备注/原因>",
          "corrected_labels": { ... },
          "original_labels": { ... },
          "source_metadata_file": "<输入 metadata 路径>",
          "generated_at": "<ISO 8601 UTC 时间>"
        }
      ]
    }

注意：
    - 当输入 metadata 不存在时，界面会显示友好提示，不会崩溃。
    - 不假设子视频 mp4 或采样帧图片一定存在，缺失时仅显示占位提示。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]

STATUS_APPROVED = "approved"
STATUS_DROPPED = "dropped"
STATUS_NEEDS_REGENERATE = "needs_regenerate"
STATUS_OPTIONS = [STATUS_APPROVED, STATUS_DROPPED, STATUS_NEEDS_REGENERATE]
STATUS_LABELS = {
    None: "未审查",
    STATUS_APPROVED: "approved",
    STATUS_DROPPED: "dropped",
    STATUS_NEEDS_REGENERATE: "needs_regenerate",
}
STATUS_EMOJI = {
    None: "❓",
    STATUS_APPROVED: "✅",
    STATUS_DROPPED: "🗑️",
    STATUS_NEEDS_REGENERATE: "🔄",
}

RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"
RISK_OPTIONS = [RISK_HIGH, RISK_MEDIUM, RISK_LOW]
RISK_LABELS = {
    RISK_HIGH: "高",
    RISK_MEDIUM: "中",
    RISK_LOW: "低",
}
RISK_EMOJI = {
    RISK_HIGH: "🔴",
    RISK_MEDIUM: "🟡",
    RISK_LOW: "🟢",
}


def _parse_args() -> argparse.Namespace:
    """解析命令行参数，兼容 streamlit run 与直接 python 运行。"""
    raw = sys.argv[1:]
    if "--" in raw:
        raw = raw[raw.index("--") + 1 :]

    parser = argparse.ArgumentParser(
        description="子视频人工审查 UI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：streamlit run review_subvideos_app.py -- --metadata data/07_metadata/subvideos_meta.json",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="子视频 metadata JSON 路径（训练级或测试级均可）。",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，用于解析相对路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="审查决策输出路径（默认根据输入文件名推导）。",
    )
    return parser.parse_args(raw)


def _resolve_path(rel: str | None, project_root: Path) -> Path | None:
    """将 metadata 中的相对路径解析为绝对路径。"""
    if not rel:
        return None
    path = Path(rel)
    if path.is_absolute():
        return path
    if rel.startswith("data/"):
        return project_root / rel
    return project_root / "data" / rel


def _load_subvideos(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取子视频 metadata，支持顶层 dict（含 subvideos 字段）或 list。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        st.error(f"无法解析 metadata JSON {path}: {exc}")
        st.stop()
    if isinstance(raw, dict):
        return raw.get("subvideos", []), raw
    return raw, {}


def _derive_output_path(input_path: Path, output_override: Path | None) -> Path:
    """根据输入 metadata 文件名推导输出审查决策文件名。"""
    if output_override is not None:
        return output_override
    stem = input_path.stem
    parent = input_path.parent
    if stem == "subvideos_meta":
        return parent / "subvideo_train_review_decisions.json"
    if stem == "test_subvideos_meta":
        return parent / "subvideo_test_review_decisions.json"
    return parent / f"{stem}.review_decisions.json"


def _snapshot_labels(sub: dict[str, Any]) -> dict[str, Any]:
    """提取当前 metadata 中的自动生成标签快照。"""
    has_fracture = sub.get("has_fracture_canonical", sub.get("has_fracture"))
    return {
        "has_fracture": has_fracture,
        "type": sub.get("type"),
        "location": sub.get("location_canonical", sub.get("location")),
        "fracture_between": sub.get("fracture_between"),
    }


def _load_existing_decisions(output_path: Path) -> dict[str, dict[str, Any]]:
    """若输出文件已存在，读取为 subvideo_id -> decision 的映射。"""
    if not output_path.exists():
        return {}
    try:
        raw = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        st.error(f"无法解析已有决策文件 {output_path}: {exc}")
        st.stop()

    decisions: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        data = raw.get("decisions", raw)
        if isinstance(data, list):
            for rec in data:
                if isinstance(rec, dict) and "subvideo_id" in rec:
                    decisions[rec["subvideo_id"]] = rec
        elif isinstance(data, dict):
            for sid, rec in data.items():
                if isinstance(rec, dict):
                    decisions[sid] = rec
    elif isinstance(raw, list):
        for rec in raw:
            if isinstance(rec, dict) and "subvideo_id" in rec:
                decisions[rec["subvideo_id"]] = rec
    return decisions


def _init_decisions(
    subvideos: list[dict[str, Any]], output_path: Path
) -> dict[str, dict[str, Any]]:
    """初始化 session_state 中的 decisions，确保所有子视频都有记录。"""
    if "decisions" in st.session_state:
        return st.session_state["decisions"]

    decisions = _load_existing_decisions(output_path)
    for sub in subvideos:
        if not isinstance(sub, dict):
            st.error(f"子视频记录必须为 dict，得到 {type(sub).__name__}")
            st.stop()
        sid = sub.get("subvideo_id")
        if not isinstance(sid, str) or not sid:
            st.error("子视频记录缺少有效的 subvideo_id")
            st.stop()
        if sid not in decisions:
            decisions[sid] = {
                "subvideo_id": sid,
                "status": None,
                "reviewed_at": None,
                "reviewer_notes": "",
                "corrected_labels": None,
                "original_labels": _snapshot_labels(sub),
            }
        else:
            # 保证 original_labels 字段存在，防止后续阶段 metadata 字段调整。
            if "original_labels" not in decisions[sid]:
                decisions[sid]["original_labels"] = _snapshot_labels(sub)

    st.session_state["decisions"] = decisions
    return decisions


def _save_decisions(
    output_path: Path, metadata_path: Path, decisions: dict[str, dict[str, Any]]
) -> None:
    """将已审查的决策写入 JSON 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed = [dict(rec) for rec in decisions.values() if rec.get("status") is not None]
    generated_at = datetime.now(timezone.utc).isoformat()
    source_metadata_file = str(metadata_path)
    for rec in reviewed:
        rec["source_metadata_file"] = source_metadata_file
        rec["generated_at"] = generated_at
    payload = {"decisions": reviewed}
    try:
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    except OSError as exc:
        st.error(f"无法写入决策文件 {output_path}: {exc}")


def _status_counts(decisions: dict[str, dict[str, Any]]) -> dict[str, int]:
    """统计当前各类状态数量。"""
    counts = {"total": len(decisions), "approved": 0, "dropped": 0, "needs_regenerate": 0, "unreviewed": 0}
    for rec in decisions.values():
        status = rec.get("status")
        if status == STATUS_APPROVED:
            counts["approved"] += 1
        elif status == STATUS_DROPPED:
            counts["dropped"] += 1
        elif status == STATUS_NEEDS_REGENERATE:
            counts["needs_regenerate"] += 1
        else:
            counts["unreviewed"] += 1
    return counts


def compute_subvideo_risk(sub: dict[str, Any]) -> tuple[str, list[str]]:
    """基于子视频 metadata 计算审查风险等级及原因。

    风险等级：
    - high（高）：需要优先审查，可能存在标签错误或视频异常。
    - medium（中）：存在边界或特殊情况，建议人工确认。
    - low（低）：正常情况。

    判定规则（按优先级短路）：
    高：
      1. is_abnormal 为 True（源视频存在 video_anomaly_kind，子视频可能不可靠）。
      2. type 为 "视频异常"。
      3. crop_type 以 "full_anomaly" 开头。
      4. has_fracture_canonical 为 None（断裂状态未明确）。
      5. has_fracture 与 has_fracture_canonical 不一致。
      6. 全时长子视频 (crop_type 以 "full" 开头) 的源类型与 canonical 标签明显冲突：
         - 源类型为断裂类型但 has_fracture_canonical 为 False；
         - 源类型为 "未断裂" 但 has_fracture_canonical 为 True；
         - 源类型为 "视频异常" 但 has_fracture_canonical 不为 None。
    中：
      1. type 为 "未夹紧" 且 has_fracture_canonical 为 True。
      2. 非异常正样本 (has_fracture_canonical 为 True) 缺少 fracture_between。
      3. fracture_between 接近采样帧边界：
         - 区间起始于 0（接近起始边界）；
         - 区间结束于最后一个采样帧索引（接近结束边界）。
    低：
      其他正常情况。

    返回：
        (risk_level, reasons)，其中 risk_level 为 RISK_HIGH / RISK_MEDIUM / RISK_LOW，
        reasons 为触发该等级的所有原因列表。
    """
    reasons: list[str] = []

    has_fracture = sub.get("has_fracture")
    has_fracture_canonical = sub.get("has_fracture_canonical")
    sub_type = sub.get("type")
    source_type = sub.get("source_type")
    is_abnormal = bool(sub.get("is_abnormal", False))
    crop_type = sub.get("crop_type", "")
    fracture_between = sub.get("fracture_between")

    # 高风险：异常或不确定
    if is_abnormal:
        reasons.append("源视频被标记为异常 (is_abnormal=True)")
    if sub_type == "视频异常":
        reasons.append('子视频 type 为 "视频异常"')
    if isinstance(crop_type, str) and crop_type.startswith("full_anomaly"):
        reasons.append('crop_type 为异常视频全时长')
    if has_fracture_canonical is None:
        reasons.append("has_fracture_canonical 为 None，断裂状态不明确")
    if (
        has_fracture is not None
        and has_fracture_canonical is not None
        and has_fracture != has_fracture_canonical
    ):
        reasons.append(
            f"自动生成 has_fracture({has_fracture}) 与 canonical 标签({has_fracture_canonical}) 不一致"
        )

    # 高风险：全时长子视频源类型与 canonical 标签冲突
    if isinstance(crop_type, str) and crop_type.startswith("full"):
        fracture_source_types = {
            "韧性断裂",
            "脆性断裂",
            "界面脱粘",
            "齐根断裂",
            "爆炸性断裂",
            "半脆半韧断裂",
            "界面脱粘、齐根断裂",
        }
        if source_type in fracture_source_types and has_fracture_canonical is False:
            reasons.append(
                f"源视频类型为断裂({source_type})，但全时长子视频 canonical 为 False"
            )
        elif source_type == "未断裂" and has_fracture_canonical is True:
            reasons.append("源视频类型为未断裂，但全时长子视频 canonical 为 True")
        elif source_type == "视频异常" and has_fracture_canonical is not None:
            reasons.append("源视频类型为视频异常，但全时长子视频 canonical 已确定")

    if reasons:
        return RISK_HIGH, reasons

    # 中风险：特殊类型或边界情况
    if sub_type == "未夹紧" and has_fracture_canonical is True:
        reasons.append("未夹紧类型子视频被标记为断裂")
    if (
        has_fracture_canonical is True
        and fracture_between is None
        and sub_type != "视频异常"
    ):
        reasons.append("正样本子视频缺少 fracture_between")
    if isinstance(fracture_between, (list, tuple)) and len(fracture_between) == 2:
        mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
        n = len(mapping)
        if n >= 2:
            if fracture_between[0] == 0:
                reasons.append(
                    f"fracture_between {list(fracture_between)} 接近采样帧起始边界"
                )
            if fracture_between[1] >= n - 1:
                reasons.append(
                    f"fracture_between {list(fracture_between)} 接近采样帧结束边界"
                )

    if reasons:
        return RISK_MEDIUM, reasons

    return RISK_LOW, ["标签与类型一致，未见明显异常"]


def _format_option(sub: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> str:
    """生成左侧列表中显示的子视频选项文本。"""
    sid = sub["subvideo_id"]
    status = decisions[sid].get("status")
    emoji = STATUS_EMOJI.get(status, "❓")
    label = STATUS_LABELS.get(status, "未审查")
    source = sub.get("source_video", "N/A")
    crop = sub.get("crop_type", "N/A")
    risk, _ = compute_subvideo_risk(sub)
    risk_emoji = RISK_EMOJI.get(risk, "⚪")
    risk_label = RISK_LABELS.get(risk, "未知")
    return f"{emoji} {risk_emoji} [{risk_label}] {sid}  |  {source}  |  {crop}  [{label}]"


def _resolve_video_path(sub: dict[str, Any], project_root: Path) -> Path | None:
    """解析子视频 mp4 绝对路径。"""
    video_path = _resolve_path(sub.get("video_path"), project_root)
    if video_path is not None:
        return video_path
    return project_root / "data" / "03_subvideos" / f"{sub['subvideo_id']}.mp4"


def _resolve_frame_paths(sub: dict[str, Any], project_root: Path) -> list[Path]:
    """解析所有存在的采样帧图片路径。"""
    existing: list[Path] = []
    for fp in sub.get("frame_paths") or []:
        p = _resolve_path(fp, project_root)
        if p is not None and p.exists():
            existing.append(p)
    return existing


def _parse_fracture_between(text: str) -> list[int] | None:
    """将 fracture_between 文本解析为 [i, i+1] 或 None。"""
    text = text.strip()
    if not text or text.lower() in ("null", "none"):
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"fracture_between 不是合法 JSON: {exc}") from exc
    if not (isinstance(value, list) and len(value) == 2 and all(isinstance(x, int) for x in value)):
        raise ValueError("fracture_between 必须是包含两个整数的列表，如 [2, 3]")
    return [int(value[0]), int(value[1])]


def _normalize_str(value: str) -> str | None:
    """将空字符串规范化为 None。"""
    value = value.strip()
    return None if value == "" else value


def main() -> None:
    args = _parse_args()
    metadata_path = args.metadata.resolve()
    project_root = args.project_root.resolve()
    output_path = _derive_output_path(metadata_path, args.output).resolve()

    st.set_page_config(page_title="子视频人工审查", layout="wide")
    st.title("子视频人工审查 UI")
    st.caption(f"metadata: `{metadata_path}`  |  输出: `{output_path}`")

    if not metadata_path.exists():
        st.error(f"输入 metadata 不存在: {metadata_path}")
        st.info("请确认路径正确后重新启动。")
        st.stop()

    subvideos, _ = _load_subvideos(metadata_path)
    if not subvideos:
        st.warning("输入 metadata 中未找到任何子视频记录。")
        st.stop()

    decisions = _init_decisions(subvideos, output_path)
    counts = _status_counts(decisions)

    # 实时统计
    st.divider()
    cols = st.columns(5)
    cols[0].metric("总数", counts["total"])
    cols[1].metric("未审查", counts["unreviewed"])
    cols[2].metric("approved", counts["approved"])
    cols[3].metric("dropped", counts["dropped"])
    cols[4].metric("needs_regenerate", counts["needs_regenerate"])
    st.divider()

    left_col, mid_col, right_col = st.columns([1.2, 2.2, 1.6])

    # ---------------------------- 左侧：列表 + 筛选 ----------------------------
    with left_col:
        st.subheader("子视频列表")
        status_filter = st.multiselect(
            "审查状态筛选",
            options=["未审查", STATUS_APPROVED, STATUS_DROPPED, STATUS_NEEDS_REGENERATE],
            default=["未审查", STATUS_APPROVED, STATUS_DROPPED, STATUS_NEEDS_REGENERATE],
        )
        risk_filter = st.multiselect(
            "风险等级筛选",
            options=RISK_OPTIONS,
            default=RISK_OPTIONS,
            format_func=lambda x: f"{RISK_EMOJI.get(x, '⚪')} {RISK_LABELS.get(x, x)}",
        )
        search = st.text_input("搜索 subvideo_id / source_video", value="")
        search_lower = search.strip().lower()

        filtered: list[dict[str, Any]] = []
        for sub in subvideos:
            sid = sub["subvideo_id"]
            status = decisions[sid].get("status")
            label = STATUS_LABELS.get(status, "未审查")
            if label not in status_filter:
                continue
            risk, _ = compute_subvideo_risk(sub)
            if risk not in risk_filter:
                continue
            if search_lower and (
                search_lower not in sid.lower()
                and search_lower not in str(sub.get("source_video", "")).lower()
            ):
                continue
            filtered.append(sub)

        if not filtered:
            st.info("没有符合当前筛选条件的子视频。")
            selected_sub = None
        else:
            sub_by_id = {sub["subvideo_id"]: sub for sub in filtered}
            selected_id = st.selectbox(
                "选择子视频",
                options=list(sub_by_id.keys()),
                format_func=lambda sid: _format_option(sub_by_id[sid], decisions),
                index=0,
                key="selected_subvideo",
            )
            selected_sub = sub_by_id[selected_id]

    # ---------------------------- 中间：展示 ----------------------------
    if selected_sub is None:
        with mid_col:
            st.info("请在左侧选择子视频以开始审查。")
        with right_col:
            pass
        return

    sid = selected_sub["subvideo_id"]
    decision = decisions[sid]
    current_status = decision.get("status")

    with mid_col:
        st.subheader(sid)
        video_path = _resolve_video_path(selected_sub, project_root)
        if video_path is not None and video_path.exists():
            st.video(str(video_path))
        else:
            st.info("子视频 mp4 文件不存在，无法播放。")

        st.write("**采样帧展示**")
        frame_paths = _resolve_frame_paths(selected_sub, project_root)
        if frame_paths:
            mapping = selected_sub.get("actual_frame_mapping") or selected_sub.get("sampled_frames") or []
            captions: list[str] = []
            for idx, _ in enumerate(frame_paths):
                if idx < len(mapping) and "original_frame" in mapping[idx]:
                    captions.append(f"frame {idx} (orig {mapping[idx]['original_frame']})")
                else:
                    captions.append(f"frame {idx}")
            st.image([str(p) for p in frame_paths], caption=captions, use_container_width=True)
        else:
            st.info("采样帧图片不存在，显示占位。")

        mapping = selected_sub.get("actual_frame_mapping") or selected_sub.get("sampled_frames")
        if mapping:
            with st.expander("帧映射详情"):
                st.json(mapping)

    # ---------------------------- 右侧：信息 + 编辑 ----------------------------
    with right_col:
        st.subheader("子视频信息")
        st.write(f"**subvideo_id:** `{sid}`")
        st.write(f"**source_video:** {selected_sub.get('source_video', 'N/A')}")
        st.write(f"**crop_type:** {selected_sub.get('crop_type', 'N/A')}")
        st.write(f"**split / fold:** {selected_sub.get('split', 'N/A')} / {selected_sub.get('fold', 'N/A')}")
        start_value = selected_sub.get("start_time")
        end_value = selected_sub.get("end_time")
        start_time = float(start_value) if start_value is not None else 0.0
        end_time = float(end_value) if end_value is not None else 0.0
        st.write(f"**时间区间:** {start_time:.3f}s – {end_time:.3f}s")
        st.write(
            f"**帧范围:** {selected_sub.get('start_frame', 'N/A')} – {selected_sub.get('end_frame', 'N/A')}"
        )
        st.write(f"**当前状态:** {STATUS_LABELS.get(current_status, '未审查')} {STATUS_EMOJI.get(current_status, '❓')}")

        risk, risk_reasons = compute_subvideo_risk(selected_sub)
        risk_color = {
            RISK_HIGH: "#ff4d4f",
            RISK_MEDIUM: "#faad14",
            RISK_LOW: "#52c41a",
        }.get(risk, "#8c8c8c")
        st.markdown(
            f"**风险等级:** <span style='background-color:{risk_color}; "
            f"color:white; padding:2px 8px; border-radius:4px;'>"
            f"{RISK_EMOJI.get(risk, '⚪')} {RISK_LABELS.get(risk, '未知')}</span>",
            unsafe_allow_html=True,
        )
        with st.expander("风险判定原因"):
            for reason in risk_reasons:
                st.write(f"- {reason}")

        if selected_sub.get("selection_reason"):
            st.write(f"**selection_reason:** {selected_sub['selection_reason']}")

        st.write("**自动生成标签（original_labels）**")
        st.json(decision["original_labels"])

        st.divider()

        # 编辑表单
        base_labels = decision["corrected_labels"] if decision["corrected_labels"] is not None else decision["original_labels"]
        with st.form(key=f"review_form_{sid}"):
            if current_status == STATUS_APPROVED:
                st.write("**标签编辑**")
            else:
                st.info("当前状态非 approved；编辑结果仅在点击「审查通过」时保存为 corrected_labels。")
            has_options = [True, False, None]
            has_default = base_labels.get("has_fracture")
            try:
                has_index = has_options.index(has_default)
            except ValueError:
                has_index = 2
            edited_has_fracture = st.selectbox(
                "has_fracture",
                options=has_options,
                index=has_index,
                format_func=lambda x: "True" if x is True else ("False" if x is False else "None"),
                key=f"has_fracture_{sid}",
            )
            edited_type = st.text_input(
                "type",
                value=str(base_labels.get("type") or ""),
                key=f"type_{sid}",
            )
            edited_location = st.text_input(
                "location",
                value=str(base_labels.get("location") or ""),
                key=f"location_{sid}",
            )
            fb_default = base_labels.get("fracture_between")
            fb_text = st.text_input(
                "fracture_between（JSON，如 [2,3] 或留空）",
                value=json.dumps(fb_default) if fb_default is not None else "",
                key=f"fracture_between_{sid}",
            )

            notes = st.text_area(
                "reviewer_notes / 丢弃或重新生成原因",
                value=decision.get("reviewer_notes", ""),
                key=f"notes_{sid}",
            )

            btn_cols = st.columns(3)
            with btn_cols[0]:
                approve = st.form_submit_button("审查通过", type="primary")
            with btn_cols[1]:
                drop = st.form_submit_button("丢弃")
            with btn_cols[2]:
                regen = st.form_submit_button("需要重新生成")

        if approve or drop or regen:
            new_status: str | None = None
            if approve:
                new_status = STATUS_APPROVED
                try:
                    fb = _parse_fracture_between(fb_text)
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                corrected_labels = {
                    "has_fracture": edited_has_fracture,
                    "type": _normalize_str(edited_type),
                    "location": _normalize_str(edited_location),
                    "fracture_between": fb,
                }
                decision["corrected_labels"] = corrected_labels
            elif drop:
                new_status = STATUS_DROPPED
                decision["corrected_labels"] = None
            elif regen:
                new_status = STATUS_NEEDS_REGENERATE
                decision["corrected_labels"] = None

            if new_status in (STATUS_DROPPED, STATUS_NEEDS_REGENERATE) and not notes.strip():
                st.warning(f"{new_status} 建议填写原因，便于后续追溯。")

            decision["status"] = new_status
            decision["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            decision["reviewer_notes"] = notes

            _save_decisions(output_path, metadata_path, decisions)
            st.success(f"已保存为 {new_status}，并写入 {output_path}")
            st.rerun()

        # 显式保存按钮
        st.divider()
        if st.button("立即保存到文件", key=f"save_button_{sid}"):
            _save_decisions(output_path, metadata_path, decisions)
            st.success(f"已保存到 {output_path}")

        # 导出当前决策摘要
        with st.expander("查看当前子视频决策"):
            st.json(decision)


if __name__ == "__main__":
    main()
