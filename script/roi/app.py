"""ROI viewer, optional crop editor, and separate ROI label-review records."""
from __future__ import annotations
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw
try:
    from streamlit_cropper import st_cropper
except ImportError:
    st_cropper=None

from core import RoiError, geometry, normalize_drag_box
from label_fields import LABEL_FIELDS, LABEL_GROUPS, field_value, option_label, options_for
from roi import parser, workspace

STATUS_LABELS={"needs_decision":"待选框", "needs_review":"待调整", "ready":"待生成",
    "needs_output_review":"ROI可查看", "success":"ROI可用", "failed":"需处理", "needs_verification":"待核实"}


@st.cache_data(show_spinner=False)
def frame(path: str, sha: str, time: float):
    result=subprocess.run(["ffmpeg","-v","error","-noautorotate","-ss",str(time),"-i",path,
        "-frames:v","1","-f","image2pipe","-vcodec","png","-"],capture_output=True)
    if result.returncode or not result.stdout: raise RoiError("该位置无法提取预览帧")
    return result.stdout


def render_label_review(labels: dict, review_key: str) -> dict[str, str]:
    """Render the current label-review values as an editable review draft."""
    st.subheader("已有标签")
    st.caption("预填自原标注或已保存的 ROI 审查记录。编辑后需主动保存；保存不会更新原始标注 CSV。")
    draft: dict[str, str] = {}
    for group in LABEL_GROUPS:
        st.markdown(f"##### {group.title}")
        if group.title == "关键帧与时间":
            values={field.column:field_value(labels,field.column) for field in group.fields}
            draft.update(values)
            summary=(f"前帧：{values['断裂帧_前'] or '未标注'}　·　"
                     f"后帧：{values['断裂帧_后'] or '未标注'}　·　"
                     f"发生时间：{values['断裂时间点'] or '未标注'} 秒")
            bounds=[values[column] for column in ("断裂时间范围_下界","断裂时间范围_上界")]
            if any(bounds):
                summary+=f"　·　范围：{bounds[0] or '未标注'}–{bounds[1] or '未标注'} 秒"
            st.caption(summary)
            continue
        fields = list(group.fields)
        for start in range(0, len(fields), 3):
            for column, field in zip(st.columns(3), fields[start:start + 3]):
                current = field_value(labels, field.column)
                widget_key = f"{review_key}-label-{field.column}"
                with column:
                    if field.kind == "select":
                        choices = options_for(field, current)
                        draft[field.column] = st.selectbox(
                            field.label, choices, index=choices.index(current),
                            format_func=lambda value, item=field: option_label(item, value),
                            key=widget_key,
                        )
                    elif field.kind == "textarea":
                        draft[field.column] = st.text_input(field.label, value=current, key=widget_key)
                    else:
                        draft[field.column] = st.text_input(
                            field.label, value=current, key=widget_key,
                            disabled=field.readonly or group.title == "关键帧与时间",
                        )
    return draft


def main():
    args=parser().parse_args(sys.argv[1:]); work=workspace(args)
    st.set_page_config(page_title="视频 ROI",layout="wide")
    st.markdown("""<style>
    .block-container { padding-top: 0.45rem; padding-bottom: 0.75rem; }
    .stApp h1 { font-size: 1.85rem; line-height: 1.25; margin-bottom: 0; }
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] { gap: 0.25rem; }
    video[data-testid="stVideo"] {
      height: min(31vh, 278px) !important;
      max-height: 278px !important;
      width: 100% !important;
      object-fit: contain !important;
      background: #111;
    }
    div[data-testid="stMarkdownContainer"] h5 { font-size: 1rem; line-height: 1; margin: 0.05rem 0 0; }
    div[data-testid="stWidgetLabel"] { margin-bottom: -0.35rem; }
    div[data-testid="stWidgetLabel"] p { font-size: 0.84rem; line-height: 1.1; }
    div[data-baseweb="select"] > div { min-height: 2rem; }
    div[data-baseweb="select"] span { line-height: 1.9rem; }
    @media (max-width: 1000px) {
      div[data-testid="stColumn"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        flex: 1 1 45% !important;
        min-width: 45% !important;
      }
      video[data-testid="stVideo"] { height: 250px !important; max-height: 250px !important; }
    }
    </style>""", unsafe_allow_html=True)
    st.title("视频 ROI 裁剪")
    try: manifest=work.refresh()
    except (RoiError,OSError,subprocess.SubprocessError) as exc:
        st.error(str(exc)); return
    summary=" · ".join(f"{STATUS_LABELS.get(name,name)} {count}" for name,count in manifest["summary"].items())
    st.caption(f"直接查看已有裁剪结果；有问题再调整。ROI 画面和标签同屏展示 · 视频总数 {manifest['total']} · {summary}")
    if not manifest["videos"]:
        st.info("目录中没有支持的视频文件。"); return
    mapping={row["video_id"]:row for row in manifest["videos"]}
    selected=st.selectbox("视频",list(mapping),format_func=lambda k:f"{k} · {STATUS_LABELS.get(mapping[k]['status'],mapping[k]['status'])}")
    row=mapping[selected]; source=row.get("source",{}); key=selected+"-"+source.get("sha256","")[:12]
    if row.get("status")!="success" and row.get("reason"):
        if row.get("status")=="failed": st.error(row["reason"])
        else: st.warning(row["reason"])
    output=row.get("output")
    try:
        label_review=work.label_review_state(row)
    except (RoiError,OSError,ValueError) as exc:
        label_review={"status":"unavailable","values":row.get("labels",{}),"changes":{},"revision":None,"revision_id":None,"history_count":0}
        st.warning(f"无法读取已保存的 ROI 标签审查记录：{exc}")
    saved_values=label_review.get("values") or row.get("labels",{})
    label_signature=hashlib.sha256(json.dumps(row.get("labels",{}),ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:12]
    review_key=f"{key}-{(output or {}).get('sha256','')[:12]}-{label_signature}"
    revision_key=review_key+"-loaded-revision"
    if revision_key not in st.session_state:
        st.session_state[revision_key]=label_review.get("revision_id")
    loaded_revision=st.session_state[revision_key]
    record_changed=loaded_revision != label_review.get("revision_id")
    draft_store_key=review_key+"-draft-values"
    if draft_store_key not in st.session_state:
        st.session_state[draft_store_key]={
            field.column:field_value(saved_values,field.column) for field in LABEL_FIELDS
        }
    form_values=st.session_state[draft_store_key]
    video_column, labels_column = st.columns((1.18,1),gap="large")
    with video_column:
        if output:
            st.subheader("ROI 结果")
            st.video(output["path"])
            if output.get("origin")=="preserved_legacy":
                st.caption("沿用旧裁剪视频，保留原始文件内容。此状态表示 ROI 可用，不表示已完成人工复核。")
            else: st.caption("按保存的范围生成，可直接查看；有问题再调整。")
            timing_note=output.get("validation",{}).get("nominal_frame_rate",{})
            if timing_note.get("status")=="metadata_disagreement":
                st.warning("帧率元数据存在差异；来源、帧数、总时长和平均帧率核对通过。未逐帧比较时间戳。")
            if output.get("geometry",{}).get("geometry_status")=="uncertain":
                st.warning("旧视频已按来源和输出摘要核对；已有记录不足以准确还原边界，原文件保持不变。")
        elif source and Path(source.get("path","")).is_file():
            st.subheader("原视频（尚未生成 ROI）")
            st.video(source["path"])
            st.caption("尚无 ROI 结果；可在下方设置画面范围。")
        else:
            st.subheader("ROI 结果")
            st.warning("没有可播放的 ROI 或源视频。")
    with labels_column:
        label_draft=render_label_review(form_values,review_key)
        st.session_state[draft_store_key]=dict(label_draft)
        changed_fields=[field.column for field in LABEL_FIELDS
                        if label_draft.get(field.column,"") != field_value(saved_values,field.column)]
        if record_changed:
            st.error("该视频的 ROI 标签审查记录已在其他页面变更。请刷新页面后再编辑或保存，避免覆盖他人的修改。")
        elif label_review.get("status")=="stale":
            st.warning("原标注或 ROI 身份已变化。请核对当前标签后重新保存为新的 ROI 审查记录。")
        elif changed_fields:
            st.caption(f"有 {len(changed_fields)} 项标签修改尚未保存。")
        elif label_review.get("status")=="saved":
            st.caption("当前标签与已保存的 ROI 审查记录一致。")
        if st.button("保存标签修改到 ROI 审查记录",key=key+"-save-labels",
                     type="primary",disabled=not changed_fields or record_changed):
            try:
                saved=work.save_label_review(row,label_draft,expected_revision=loaded_revision)
                st.session_state[revision_key]=saved.get("revision_id")
                st.session_state[draft_store_key]=dict(saved.get("values") or label_draft)
                st.success("标签已保存到 ROI 审查记录；原始标注 CSV 未修改。")
                st.rerun()
            except (RoiError,OSError,ValueError) as exc:
                st.error(f"未能保存 ROI 标签审查记录：{exc}")
    # The per-video key prevents edits from leaking across video switches.
    st.session_state[review_key+"-label-draft"]=label_draft
    if not source:
        st.warning("此条目尚无可访问的源视频信息。"); return
    if row.get("source_missing") or not Path(source["path"]).is_file():
        st.warning("源视频缺失或不可访问，已保留历史记录。请恢复原文件后刷新。"); return
    media=source["media"]
    if media["rotation"]!=0:
        st.warning("视频有旋转标记，需要先核实画面方向和坐标。"); return
    if output and not st.checkbox("需要调整裁剪范围",key=key+"-edit"):
        return
    st.subheader("调整画面范围" if output else "设置画面范围")
    existing=row.get("draft") or row.get("decision") or row.get("reference_decision") or {}
    effective=(output or {}).get("geometry",{}).get("effective_pixel_box")
    time=st.number_input("预览位置（秒）",min_value=0.,max_value=max(0.,media["duration"]-.001),value=0.,
        step=float(1/float(__import__('fractions').Fraction(media["nominal_frame_rate"]))),key=key+"-time")
    try: raw=frame(source["path"],source["sha256"],time)
    except RoiError:
        st.warning("此位置没有可提取帧，下面显示起始帧。请调整时间或播放原视频查看。");
        try: raw=frame(source["path"],source["sha256"],0.)
        except RoiError as exc: st.error(str(exc)); return
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    mode=st.radio("画面范围",["fixed_roi","no_crop"],index=1 if existing.get("mode")=="no_crop" else 0,
        format_func=lambda x:"固定 3:4 框" if x=="fixed_roi" else "全画面补边",key=key+"-mode")
    if mode=="fixed_roi":
        if st_cropper is None:
            st.error("缺少 streamlit-cropper，请按 README 安装依赖。"); return
        chosen_box=st_cropper(image,realtime_update=True,box_color="#2679D1",aspect_ratio=(3,4),return_type="box",key=key+"-cropper")
        try: normalized=normalize_drag_box(chosen_box,media["width"],media["height"])
        except RoiError as exc: st.error(str(exc)); return
        if st.button("采用当前拖框",key=key+"-apply"): st.session_state[key+"-box"]=normalized
        chosen=st.session_state.get(key+"-box",effective or existing.get("pixel_box") or normalized)
        cols=st.columns(4)
        box={field:int(col.number_input(field,value=int(chosen[field]),min_value=0 if field in {"x","y"} else 2,
            key=f"{key}-{field}-{chosen[field]}")) for field,col in zip(("x","y","width","height"),cols)}
    else: box=None
    decision={"mode":mode,"source_resolution":[media["width"],media["height"]],"pixel_box":box}
    try: geo=geometry(decision)
    except RoiError as exc: st.error(str(exc)); return
    if box:
        outlined=image.copy(); ImageDraw.Draw(outlined).rectangle((box["x"],box["y"],box["x"]+box["width"]-1,box["y"]+box["height"]-1),outline="#2679D1",width=max(2,image.width//200))
        st.image(outlined,caption="新范围（仅保存并生成后生效）",width=min(800,image.width))
    else: st.image(image,caption="保留全部画面",width=min(800,image.width))
    st.json({k:v for k,v in geo.items() if k!="filter"})
    pending=st.text_input("备注／下次继续的位置",value=existing.get("pending_reason",""),key=key+"-pending")
    if st.button("保存选框进度",key=key+"-draft"):
        try: work.save_draft(row,{**decision,"pending_reason":pending}); st.rerun()
        except (RoiError,OSError,ValueError) as exc: st.error(str(exc))
    if st.button("保存范围并生成 ROI",key=key+"-generate"):
        with st.spinner("正在生成并核对媒体，请稍候"):
            try: work.save_decision(row,{**decision,"pending_reason":pending}); work.generate(selected); st.rerun()
            except (RoiError,OSError,ValueError,subprocess.SubprocessError) as exc: st.error(str(exc))


if __name__=="__main__": main()
