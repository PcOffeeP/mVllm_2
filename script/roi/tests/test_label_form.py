"""Review the selected ROI next to the labels loaded from its annotation row."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from script.roi import core, label_fields


@pytest.fixture
def labelled_app(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    videos = tmp_path / "data/videos"
    videos.mkdir(parents=True)
    annotations = [
        {"id": "video_a", "video_path": "data/videos/video_a.mp4", "材料类型": "金属", "断裂状态": "发生断裂",
         "断裂模式": "韧性断裂", "断裂位置": "标距内", "异常_未夹紧": "否",
         "异常_视频异常": "无法判断", "异常_爆炸性断裂": "", "现象_伸长": "是",
         "现象_颈缩": "否", "现象_开裂": "无法判断", "现象_界面分离": "",
         "现象_断后脱夹": "旧表待确认", "断裂帧_前": "8", "断裂帧_后": "9",
         "断裂时间点": "0.9", "断裂时间范围_下界": "", "断裂时间范围_上界": "",
         "标注状态": "已标注·有断裂", "标注备注": "A 的原始备注"},
        {"id": "video_b", "video_path": "data/videos/video_b.mp4", "材料类型": "聚合物", "断裂状态": "未断裂",
         "断裂模式": "无", "断裂位置": "无", "异常_未夹紧": "无法判断",
         "异常_视频异常": "否", "异常_爆炸性断裂": "否", "现象_伸长": "",
         "现象_颈缩": "是", "现象_开裂": "否", "现象_界面分离": "无法判断",
         "现象_断后脱夹": "否", "断裂帧_前": "无", "断裂帧_后": "无",
         "断裂时间点": "无", "断裂时间范围_下界": "", "断裂时间范围_上界": "",
         "标注状态": "已标注·无断裂", "标注备注": "B 的原始备注"},
    ]
    labels = tmp_path / "data/annotation-table-full.csv"
    columns = ["id", "video_path", "材料类型", *(field.column for field in label_fields.LABEL_FIELDS)]
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(annotations)
    before = labels.read_bytes()
    for identifier in ("video_a", "video_b"):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=64x48:rate=10:duration=1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(videos / f"{identifier}.mp4")],
                       check=True, capture_output=True)
    work = core.Workspace(videos, tmp_path / "data/roi", labels=labels)
    for row in work.refresh()["videos"]:
        work.save_decision(row, {"mode": "no_crop"})
        work.generate(row["video_id"])
    app = Path(core.__file__).with_name("app.py")
    monkeypatch.syspath_prepend(str(app.parent))
    monkeypatch.setattr(sys, "argv", [str(app), "--project-root", str(tmp_path)])
    page = AppTest.from_file(str(app)).run(timeout=10)
    return page, annotations, labels, before


def select_widget(page, label):
    # The legacy ROI workbench uses its original "选择视频" label.
    labels = {label, "选择视频"} if label == "视频" else {label}
    return next(widget for widget in page.selectbox if widget.label in labels)


def assert_visual_labels(page, annotation):
    for field in label_fields.LABEL_FIELDS:
        if field.kind == "select":
            assert select_widget(page, field.label).value == annotation[field.column]


def test_existing_roi_and_all_prefilled_labels_are_available_without_opening_a_label_expander(labelled_app):
    page, annotations, labels, before = labelled_app
    assert not page.exception
    assert_visual_labels(page, annotations[0])
    # A rendered video is present on the default page, before crop editing.
    assert page.get("video")
    label_names = {field.label for field in label_fields.LABEL_FIELDS}
    for expander in page.expander:
        assert not any(widget.label in label_names for widget in expander.selectbox)
    assert not any("通过" in button.label or "确认审核" in button.label for button in page.button)
    # This page keeps the original frame/time observation together.  Editing
    # frames while retaining a read-only derived time would store contradictory
    # annotations; frame corrections remain in the dedicated annotation tool.
    for group in label_fields.LABEL_GROUPS:
        if group.title == "关键帧与时间":
            for field in group.fields:
                widget = next(widget for widget in page.text_input if widget.label == field.label)
                assert widget.value == annotations[0][field.column]
                assert widget.disabled
    assert labels.read_bytes() == before


def test_switching_video_loads_the_selected_annotation_without_leaking_other_values(labelled_app):
    page, annotations, labels, before = labelled_app
    assert_visual_labels(page, annotations[0])
    page = select_widget(page, "视频").set_value("video_b").run(timeout=10)
    assert not page.exception
    assert_visual_labels(page, annotations[1])
    page = select_widget(page, "视频").set_value("video_a").run(timeout=10)
    assert not page.exception
    assert_visual_labels(page, annotations[0])
    assert labels.read_bytes() == before


def test_label_edits_need_explicit_save_and_reload_from_roi_records_only(labelled_app):
    from streamlit.testing.v1 import AppTest

    page, _, labels, before = labelled_app
    page = select_widget(page, "断裂位置").set_value("夹持根部").run(timeout=10)
    record = labels.parent / "roi/label_reviews.json"
    assert not record.exists()
    assert labels.read_bytes() == before
    button = next(button for button in page.button if button.label == "保存标签审查记录")
    page = button.click().run(timeout=10)
    assert not page.exception
    assert record.is_file()
    app = Path(core.__file__).with_name("app.py")
    reloaded = AppTest.from_file(str(app)).run(timeout=10)
    assert not reloaded.exception
    assert select_widget(reloaded, "断裂位置").value == "夹持根部"
    assert select_widget(reloaded, "未夹紧").value == "否"
    assert labels.read_bytes() == before


def test_a_second_open_page_cannot_revert_newer_label_edits_without_refresh(labelled_app):
    from streamlit.testing.v1 import AppTest

    first, _, labels, before = labelled_app
    app = Path(core.__file__).with_name("app.py")
    second = AppTest.from_file(str(app)).run(timeout=10)
    first = select_widget(first, "断裂位置").set_value("夹持根部").run(timeout=10)
    first = next(button for button in first.button if button.label == "保存标签审查记录").click().run(timeout=10)
    assert not first.exception
    # The second page still has the pre-edit annotation in its widget state.
    second = select_widget(second, "颈缩").set_value("是").run(timeout=10)
    second = next(button for button in second.button if button.label == "保存标签审查记录").click().run(timeout=10)
    assert not second.exception
    current = AppTest.from_file(str(app)).run(timeout=10)
    assert select_widget(current, "断裂位置").value == "夹持根部"
    records = json.loads((labels.parent / "roi/label_reviews.json").read_text())
    assert len(records["videos"]["video_a"]["revisions"]) == 1
    assert labels.read_bytes() == before


def test_changed_source_annotation_is_not_displayed_as_the_previous_rows_prefill(labelled_app):
    page, _, labels, _ = labelled_app
    assert select_widget(page, "断裂状态").value == "发生断裂"
    labels.write_text(labels.read_text(encoding="utf-8").replace("发生断裂", "已断裂"), encoding="utf-8")
    page = page.run(timeout=10)
    assert not page.exception
    assert select_widget(page, "断裂状态").value == "已断裂"


def test_unsaved_edits_return_with_the_video_without_writing_source_or_roi_records(labelled_app):
    page, annotations, labels, before = labelled_app
    page = select_widget(page, "断裂位置").set_value("夹持根部").run(timeout=10)
    page = select_widget(page, "视频").set_value("video_b").run(timeout=10)
    assert_visual_labels(page, annotations[1])
    page = select_widget(page, "视频").set_value("video_a").run(timeout=10)
    assert not page.exception
    assert select_widget(page, "断裂位置").value == "夹持根部"
    assert select_widget(page, "断裂模式").value == "韧性断裂"
    assert not (labels.parent / "roi/label_reviews.json").exists()
    assert labels.read_bytes() == before


def test_changed_roi_output_does_not_reuse_the_previous_outputs_label_draft(labelled_app):
    page, annotations, labels, before = labelled_app
    page = select_widget(page, "断裂位置").set_value("夹持根部").run(timeout=10)
    page = next(button for button in page.button if button.label == "保存标签审查记录").click().run(timeout=10)
    assert not page.exception
    work = core.Workspace(labels.parent / "videos", labels.parent / "roi", labels=labels)
    row = next(row for row in work.refresh()["videos"] if row["video_id"] == "video_a")
    work.save_decision(row, {"mode": "fixed_roi", "pixel_box": {"x": 2, "y": 2, "width": 30, "height": 40}})
    work.generate("video_a")
    page = page.run(timeout=10)
    assert not page.exception
    assert_visual_labels(page, annotations[0])
    records = json.loads((labels.parent / "roi/label_reviews.json").read_text())
    assert len(records["videos"]["video_a"]["revisions"]) == 1
    assert labels.read_bytes() == before


def test_failed_video_shows_its_actual_id_conflict_reason_in_the_page(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    videos = tmp_path / "data/videos"
    videos.mkdir(parents=True)
    (videos / "duplicate.mp4").write_bytes(b"not decoded: duplicate ID detected first")
    (videos / "duplicate.mov").write_bytes(b"same ID in a different supported container")
    app = Path(core.__file__).with_name("app.py")
    monkeypatch.syspath_prepend(str(app.parent))
    monkeypatch.setattr(sys, "argv", [str(app), "--project-root", str(tmp_path)])
    page = AppTest.from_file(str(app)).run(timeout=10)
    assert not page.exception
    assert select_widget(page, "视频").value == "duplicate"
    # The user must see the actionable reason, rather than only a generic
    # "no source/ROI" message that hides the two conflicting paths.
    visible_feedback = [element.value for element in (*page.error, *page.warning, *page.info)]
    assert any("视频 ID 重复" in text for text in visible_feedback)


def test_legacy_workbench_search_and_status_filters_keep_the_selected_rows_labels(labelled_app):
    page, annotations, labels, before = labelled_app
    assert not page.exception
    assert any(widget.label == "选择视频" for widget in page.selectbox)
    search = next(widget for widget in page.text_input if widget.label == "搜索 video_id / 类型")
    page = search.set_value("VIDEO_B").run(timeout=10)
    assert not page.exception
    assert select_widget(page, "视频").value == "video_b"
    assert_visual_labels(page, annotations[1])
    page = next(widget for widget in page.text_input if widget.label == "搜索 video_id / 类型").set_value("聚合物").run(timeout=10)
    assert not page.exception
    assert select_widget(page, "视频").value == "video_b"
    assert_visual_labels(page, annotations[1])

    status_filter = next(widget for widget in page.multiselect if widget.label == "状态")
    page = status_filter.set_value(["unreviewed"]).run(timeout=10)
    assert not page.exception
    assert any("没有符合筛选条件的视频" in element.value for element in page.info)
    assert not any(widget.label == "选择视频" for widget in page.selectbox)

    page = next(widget for widget in page.multiselect if widget.label == "状态").set_value(
        ["unreviewed", "approved", "needs_review", "outdated_policy"]
    ).run(timeout=10)
    assert select_widget(page, "视频").value == "video_b"
    assert_visual_labels(page, annotations[1])
    assert labels.read_bytes() == before


def test_copied_original_ui_keeps_its_workbench_controls_and_saves_only_a_decision(labelled_app, monkeypatch):
    import streamlit_cropper

    page, annotations, labels, before = labelled_app
    work = core.Workspace(labels.parent / "videos", labels.parent / "roi", labels=labels)
    previous = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    original_output = Path(previous["output"]["path"])
    original_hash = core.sha256_file(original_output)
    source_hash = core.sha256_file(labels.parent / "videos/video_a.mp4")
    # AppTest cannot send native pointer drags to the external cropper iframe.
    # Supply the cropper's public result, then exercise the actual UI save and
    # real encoder path; source geometry and generated media remain observable.
    monkeypatch.setattr(streamlit_cropper, "st_cropper", lambda image, **kwargs: {
        "left": 2, "top": 2, "width": 30, "height": 40,
    })
    page = next(widget for widget in page.radio if widget.label == "模式").set_value("fixed_roi").run(timeout=10)
    assert not page.exception
    page = next(widget for widget in page.slider if widget.label == "抽帧时间（可拖动）").set_value(0.5).run(timeout=10)
    assert not page.exception
    assert {"原始视频播放", "当前帧 ROI 对照预览", "关键时刻 ROI 预览", "源视频信息"} <= {
        item.label for item in page.expander
    }
    assert next(widget for widget in page.selectbox if widget.label == "审核状态")
    assert {"上夹具清晰可见", "下夹具清晰可见", "完整试样清晰可见", "仍可判断标距内/外位置",
            "仍可判断是否齐根断裂", "我已检查关键时刻预览"} <= {widget.label for widget in page.checkbox}
    # The copied legacy tool keeps these controls visible; the current workflow
    # does not require checking them individually just to save a crop decision.
    page = next(button for button in page.button if button.label == "保存当前决定").click().run(timeout=10)
    assert not page.exception
    current = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    assert current["status"] == "ready"
    assert current["decision"]["mode"] == "fixed_roi"
    assert current["decision"]["pixel_box"] == {"x": 2, "y": 2, "width": 30, "height": 40}
    assert not work.inventory()["complete"]
    assert not current.get("output_review")
    assert core.sha256_file(original_output) == original_hash
    assert core.sha256_file(labels.parent / "videos/video_a.mp4") == source_hash
    assert_visual_labels(page, annotations[0])
    assert labels.read_bytes() == before


def test_reopening_legacy_drag_editor_starts_at_the_existing_effective_roi(labelled_app, monkeypatch):
    import streamlit_cropper
    from streamlit.testing.v1 import AppTest

    page, _, labels, before = labelled_app
    work = core.Workspace(labels.parent / "videos", labels.parent / "roi", labels=labels)
    row = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    box = {"x": 2, "y": 2, "width": 30, "height": 40}
    work.save_decision(row, {"mode": "fixed_roi", "pixel_box": box})
    work.generate("video_a")
    observed = []

    def existing_box(image, **kwargs):
        observed.append(kwargs.get("default_coords"))
        return {"left": box["x"], "top": box["y"], "width": box["width"], "height": box["height"]}

    monkeypatch.setattr(streamlit_cropper, "st_cropper", existing_box)
    # Reopening is a fresh page, rather than rerunning an already open radio
    # that legitimately still contains the user's unsaved selection.
    page = AppTest.from_file(str(Path(core.__file__).with_name("app.py"))).run(timeout=10)
    assert not page.exception
    assert next(widget for widget in page.radio if widget.label == "模式").value == "fixed_roi"
    assert observed[-1] == (2, 32, 2, 42)
    assert labels.read_bytes() == before


def test_saving_after_a_second_drag_uses_the_current_red_box_not_a_previously_applied_box(labelled_app, monkeypatch):
    import streamlit_cropper

    page, _, labels, before = labelled_app
    chosen = {"left": 2, "top": 2, "width": 30, "height": 40}
    monkeypatch.setattr(streamlit_cropper, "st_cropper", lambda image, **kwargs: dict(chosen))
    page = next(widget for widget in page.radio if widget.label == "模式").set_value("fixed_roi").run(timeout=10)
    assert not page.exception
    # Earlier versions exposed an Apply action. If retained, using it must not
    # freeze the crop and silently ignore a later visible red-box adjustment.
    apply = next((button for button in page.button if button.label == "采用当前拖框"), None)
    if apply is not None:
        page = apply.click().run(timeout=10)
        assert not page.exception
    chosen.update(left=10, top=4)
    page = page.run(timeout=10)
    assert not page.exception
    page = next(button for button in page.button if button.label == "保存当前决定").click().run(timeout=10)
    assert not page.exception
    work = core.Workspace(labels.parent / "videos", labels.parent / "roi", labels=labels)
    current = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    assert current["decision"]["pixel_box"] == {"x": 10, "y": 4, "width": 30, "height": 40}
    assert current["status"] == "ready"
    assert labels.read_bytes() == before


def test_saved_crop_draft_takes_precedence_over_the_old_generated_rois_box(labelled_app, monkeypatch):
    import streamlit_cropper
    from streamlit.testing.v1 import AppTest

    page, _, labels, before = labelled_app
    work = core.Workspace(labels.parent / "videos", labels.parent / "roi", labels=labels)
    original = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    work.save_decision(original, {"mode": "fixed_roi", "pixel_box": {"x": 2, "y": 2, "width": 30, "height": 40}})
    work.generate("video_a")
    generated = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    old_output = Path(generated["output"]["path"])
    old_hash = core.sha256_file(old_output)
    draft_box = {"x": 10, "y": 4, "width": 30, "height": 40}
    work.save_draft(generated, {"mode": "fixed_roi", "pixel_box": draft_box,
                                "pending_reason": "继续核对新位置"})
    observed = []

    def use_default_box(image, **kwargs):
        coordinates = kwargs.get("default_coords")
        observed.append(coordinates)
        left, right, top, bottom = coordinates
        return {"left": left, "top": top, "width": right - left, "height": bottom - top}

    monkeypatch.setattr(streamlit_cropper, "st_cropper", use_default_box)
    page = AppTest.from_file(str(Path(core.__file__).with_name("app.py"))).run(timeout=10)
    assert not page.exception
    assert observed[-1] == (10, 40, 4, 44)
    page = next(button for button in page.button if button.label == "保存当前决定").click().run(timeout=10)
    assert not page.exception
    current = next(row for row in work.inventory()["videos"] if row["video_id"] == "video_a")
    assert current["decision"]["pixel_box"] == draft_box
    assert current["decision"]["pending_reason"] == "继续核对新位置"
    assert core.sha256_file(old_output) == old_hash
    assert labels.read_bytes() == before
