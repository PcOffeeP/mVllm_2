"""Local interactive ROI worklist. Launched by roi.py."""
from __future__ import annotations
import io
import subprocess
import sys
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw
try:
    from streamlit_cropper import st_cropper
except ImportError:
    st_cropper=None

from core import (EVIDENCE_ITEMS, REVIEW_VALUES, RoiError, geometry,
                  normalize_drag_box, now)
from roi import parser, workspace

STATUS_LABELS={"needs_decision":"待选框", "needs_review":"待源画面审核", "ready":"可生成",
    "needs_output_review":"待输出审核", "success":"已完成", "failed":"失败", "needs_verification":"待核实"}
REVIEW_LABELS={"unchecked":"未检查","judgable":"可判断","insufficient":"证据不足","not_applicable":"不适用"}
CAUSE_LABELS={"unknown":"原因待核实","source":"源视频本身不足","processing":"裁剪或编码损失"}


def intervals(text: str) -> list:
    result=[]
    for chunk in text.replace("，",",").split(","):
        chunk=chunk.strip()
        if not chunk: continue
        values=[float(v.strip()) for v in chunk.split(":")]
        if len(values)==1: values*=2
        if len(values)!=2: raise RoiError("检查位置请用 0:2, 5:8 或单个秒数")
        result.append(values)
    return result


def review_form(prefix, existing=None):
    existing=existing or {}
    st.caption("逐项记录证据是否保留；可判断包含可确认未出现。不适用须填写标签规则依据。")
    items={}
    for key,label in EVIDENCE_ITEMS.items():
        prior=existing.get("items",{}).get(key,{})
        a,b,c=st.columns([2,2,4])
        value=prior.get("result","unchecked")
        if value not in REVIEW_VALUES: value="unchecked"
        result=a.selectbox(label,REVIEW_VALUES,index=REVIEW_VALUES.index(value),
            format_func=REVIEW_LABELS.get,key=f"{prefix}-{key}-result")
        cause=prior.get("cause","unknown")
        if cause not in CAUSE_LABELS: cause="unknown"
        if result=="insufficient":
            cause=b.selectbox("不足原因",list(CAUSE_LABELS),index=list(CAUSE_LABELS).index(cause),
                format_func=CAUSE_LABELS.get,key=f"{prefix}-{key}-cause")
        note=c.text_input("原因／依据",value=prior.get("note",""),key=f"{prefix}-{key}-note")
        items[key]={"result":result,"cause":cause,"note":note}
    previous=", ".join(f"{a}:{b}" for a,b in existing.get("checked_intervals",[]))
    text=st.text_input("实际检查的秒数或区间（如 0:2, 10:15, 20）",value=previous,key=prefix+"-interval")
    confirmed=st.checkbox("我已实际检查上述位置及相关过程，记录准确，未留下未解决的裁剪证据损失",key=prefix+"-confirmed")
    return {"items":items,"checked_intervals_text":text,"confirmed":confirmed}


def finalize_review(review):
    result=dict(review); result["checked_intervals"]=intervals(result.pop("checked_intervals_text"))
    result["recorded_at"]=now(); return result


@st.cache_data(show_spinner=False)
def frame(path: str, sha: str, time: float):
    result=subprocess.run(["ffmpeg","-v","error","-noautorotate","-ss",str(time),"-i",path,
        "-frames:v","1","-f","image2pipe","-vcodec","png","-"],capture_output=True)
    if result.returncode or not result.stdout: raise RoiError("该位置无法提取预览帧")
    return result.stdout


def main():
    args=parser().parse_args(sys.argv[1:]); work=workspace(args)
    st.set_page_config(page_title="视频 ROI",layout="wide")
    st.title("视频 ROI 裁剪")
    st.caption("选择范围 → 检查源画面 → 生成或复用 → 检查实际输出。源视频和标签保持原样。")
    st.text(f"输入：{work.videos_dir}\n输出：{work.output_dir}")
    try:
        manifest=work.refresh()
    except (RoiError,OSError,subprocess.SubprocessError) as exc:
        st.error(str(exc)); return
    st.write({"视频总数":manifest["total"],**{STATUS_LABELS.get(k,k):v for k,v in manifest["summary"].items()}})
    if not manifest["videos"]:
        st.info("目录中没有支持的视频文件。"); return
    mapping={row["video_id"]:row for row in manifest["videos"]}
    selected=st.selectbox("工作列表",list(mapping),format_func=lambda k:f"{k} · {STATUS_LABELS.get(mapping[k]['status'],mapping[k]['status'])}")
    row=mapping[selected]; key=selected+"-"+row.get("source",{}).get("sha256", "")[:12]; st.info(row.get("reason") or STATUS_LABELS.get(row["status"],row["status"]))
    if "source" not in row: return
    source=row["source"]; media=source["media"]
    if row.get("source_missing") or not Path(source["path"]).is_file():
        st.warning("源视频缺失或不可访问，已保留此条目的历史记录。请恢复原文件后刷新。"); return
    if media["rotation"] != 0:
        st.warning("视频有旋转标记。为避免显示方向与裁剪坐标不一致，当前保持待核实，保留源文件。"); return
    with st.expander("源视频属性和辅助标签"):
        st.json({"media":media,"labels":row.get("labels",{}),"sha256":source["sha256"]})
    if media.get("frame_count_basis") == "decoded":
        st.caption(f"实际解码帧数：{media['frame_count']}；文件头记录：{media.get('metadata_frame_count', '未知')}。")
    else:
        st.caption(f"文件头帧数：{media.get('metadata_frame_count', media.get('frame_count'))}（尚未实际计帧，生成或复用时核对）。")
    st.video(source["path"])
    # Slider and adjacent-frame controls are navigation, never proof of viewing.
    time=st.number_input("预览位置（秒，可按单帧步长调整）",min_value=0.,max_value=max(0.,media["duration"]-.001),
        value=0.,step=float(1/float(__import__('fractions').Fraction(media["nominal_frame_rate"]))),key=key+"-time")
    try:
        raw=frame(source["path"],source["sha256"],time)
    except RoiError:
        st.warning("该时间点没有可提取的画面，下面显示起始帧供选框。此回退不代表已检查所选位置，请调整预览时间或播放视频核对。")
        try: raw=frame(source["path"],source["sha256"],0.)
        except RoiError as exc: st.error(str(exc)); return
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    existing=row.get("draft") or row.get("decision",{})
    mode=st.radio("画面范围",["fixed_roi","no_crop"],index=1 if existing.get("mode")=="no_crop" else 0,
        format_func=lambda x:"固定 3:4 框" if x=="fixed_roi" else "全画面补边",key=key+"-mode")
    if mode=="fixed_roi":
        if st_cropper is None:
            st.error("缺少 streamlit-cropper，请按 README 安装依赖。"); return
        st.caption("在下图拖动 3:4 框；最终偶数像素范围显示在下方，可继续精确输入。")
        box=st_cropper(image,realtime_update=True,box_color="#2679D1",aspect_ratio=(3,4),return_type="box",key=key+"-cropper")
        try: normalized=normalize_drag_box(box,media["width"],media["height"])
        except RoiError as exc: st.error(str(exc)); return
        # Existing geometry is preserved until explicitly replaced with dragged box.
        if st.button("采用当前拖框",key=key+"-apply"):
            st.session_state[key+"-box"]=normalized
        chosen=st.session_state.get(key+"-box",existing.get("pixel_box") or normalized)
        cols=st.columns(4)
        box={field:int(col.number_input(field,value=int(chosen[field]),min_value=0 if field in {"x","y"} else 2,
            key=f"{key}-{field}-{chosen[field]}")) for field,col in zip(("x","y","width","height"),cols)}
    else: box=None
    decision={"mode":mode,"source_resolution":[media["width"],media["height"]],"pixel_box":box}
    try: geo=geometry(decision)
    except RoiError as exc: st.error(str(exc)); return
    if box:
        outlined=image.copy(); draw=ImageDraw.Draw(outlined)
        draw.rectangle((box["x"],box["y"],box["x"]+box["width"]-1,box["y"]+box["height"]-1),outline="#2679D1",width=max(2,image.width//200))
        st.image(outlined,caption="最终生效范围（蓝框）",width=min(800,image.width))
    else: st.image(image,caption="保留全部画面",width=min(800,image.width))
    st.json({k:v for k,v in geo.items() if k!="filter"})
    with st.expander("源画面证据审核",expanded=row["status"] in {"needs_decision","needs_review"}):
        review=review_form(key+"-source",existing.get("source_review"))
        pending_reason=st.text_input("待处理原因／下次继续的位置",value=existing.get("pending_reason",""),key=key+"-pending-reason")
        if st.button("保存选框和审核进度",key=key+"-draft"):
            try:
                work.save_draft(row,{**decision,"source_review":finalize_review(review),"pending_reason":pending_reason})
                st.rerun()
            except (RoiError,OSError,ValueError) as exc: st.error(str(exc))
        if st.button("保存范围与源画面审核",key=key+"-save"):
            try:
                decision["source_review"]=finalize_review(review)
                work.save_decision(row,decision); st.rerun()
            except (RoiError,OSError,ValueError) as exc: st.error(str(exc))
    saved_geometry = {k: existing.get(k) for k in ("mode", "pixel_box", "source_resolution")}
    current_geometry = {k: decision.get(k) for k in ("mode", "pixel_box", "source_resolution")}
    unsaved = saved_geometry != current_geometry
    if unsaved:
        st.caption("当前画面范围尚未保存，请完成源画面审核并保存后生成。")
    if (row["status"]=="ready" or (row["status"]=="failed" and row.get("generation_error"))) and st.button("生成／重试／核对可复用视频",key=key+"-generate",disabled=unsaved):
        with st.spinner("正在处理并核对媒体属性，请等待"):
            try: work.generate(selected); st.rerun()
            except (RoiError,OSError,subprocess.SubprocessError) as exc: st.error(str(exc))
    if row.get("output"):
        st.subheader("实际输出")
        st.video(row["output"]["path"])
        st.caption("请与源视频对照，检查实际输出的相关过程和细节。")
        output_existing=row.get("output_review_draft") or row.get("output_review") or {}
        output_review=review_form(key+"-output-"+row["output"]["sha256"][:12],output_existing)
        output_pending=st.text_input("输出待处理原因／下次继续的位置",value=output_existing.get("pending_reason",""),key=key+"-output-pending")
        if st.button("保存输出审核进度",key=key+"-output-draft"):
            try:
                work.save_output_draft(selected,{**finalize_review(output_review),"pending_reason":output_pending})
                st.rerun()
            except (RoiError,OSError,ValueError) as exc: st.error(str(exc))
        if st.button("确认实际输出审核",key=key+"-approve-output"):
            try: work.save_output_review(selected,finalize_review(output_review)); st.rerun()
            except (RoiError,OSError,ValueError) as exc: st.error(str(exc))


if __name__=="__main__": main()
