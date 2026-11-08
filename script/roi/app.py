"""ROI viewer and optional crop editor. Labels are read-only source annotations."""
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

from core import RoiError, geometry, normalize_drag_box
from roi import parser, workspace

STATUS_LABELS={"needs_decision":"待选框", "needs_review":"待调整", "ready":"待生成",
    "needs_output_review":"ROI可查看", "success":"ROI可用", "failed":"需处理", "needs_verification":"待核实"}


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
    st.caption("直接查看已有裁剪结果；有问题再调整。标签采用现有标注，无需逐项选择或点击通过。")
    try: manifest=work.refresh()
    except (RoiError,OSError,subprocess.SubprocessError) as exc:
        st.error(str(exc)); return
    st.write({"视频总数":manifest["total"],**{STATUS_LABELS.get(k,k):v for k,v in manifest["summary"].items()}})
    if not manifest["videos"]:
        st.info("目录中没有支持的视频文件。"); return
    mapping={row["video_id"]:row for row in manifest["videos"]}
    selected=st.selectbox("视频",list(mapping),format_func=lambda k:f"{k} · {STATUS_LABELS.get(mapping[k]['status'],mapping[k]['status'])}")
    row=mapping[selected]; source=row.get("source",{}); key=selected+"-"+source.get("sha256","")[:12]
    st.info(row.get("reason") or STATUS_LABELS.get(row["status"],row["status"]))
    output=row.get("output")
    if output:
        st.subheader("ROI 结果")
        st.video(output["path"])
        if output.get("origin")=="preserved_legacy":
            st.caption("沿用旧裁剪视频，保留原始文件内容。此状态表示ROI可用，不表示已完成人工复核。")
        else: st.caption("按保存的范围生成，可直接查看；有问题再调整。")
        timing_note=output.get("validation",{}).get("nominal_frame_rate",{})
        if timing_note.get("status")=="metadata_disagreement":
            st.caption("帧率元数据存在差异；来源、帧数、总时长和平均帧率核对通过，旧结果保持原样。未逐帧比较时间戳。")
        if output.get("geometry",{}).get("geometry_status")=="uncertain":
            st.caption("旧视频已按来源和输出摘要核对；已有记录不足以准确还原边界，原文件保持不变。")
        with st.expander("裁剪参数和处理记录"):
            st.json({"geometry":output.get("geometry"),"origin":output.get("origin"),
                     "validation":output.get("validation"),"sha256":output.get("sha256")})
    with st.expander("已有标注（只读）"):
        st.json(row.get("labels",{}))
    if not source:
        st.warning("此条目尚无可访问的源视频信息。"); return
    if row.get("source_missing") or not Path(source["path"]).is_file():
        st.warning("源视频缺失或不可访问，已保留历史记录。请恢复原文件后刷新。"); return
    media=source["media"]
    with st.expander("原视频和媒体信息",expanded=not bool(output)):
        st.video(source["path"])
        st.json(media)
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
