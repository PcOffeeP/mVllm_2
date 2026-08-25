from contextlib import contextmanager

from pipeline.scripts import review_v4_candidates_app as app


class _Column:
    def __init__(self, calls):
        self.calls = calls

    def image(self, path, *, caption, use_container_width):
        self.calls.append(("image", path, caption, use_container_width))


class _FakeStreamlit:
    def __init__(self):
        self.calls = []

    def subheader(self, text):
        self.calls.append(("subheader", text))

    def caption(self, text):
        self.calls.append(("caption", text))

    def markdown(self, text):
        self.calls.append(("markdown", text))

    def columns(self, count):
        self.calls.append(("columns", count))
        return [_Column(self.calls) for _ in range(count)]

    @contextmanager
    def expander(self, label, *, expanded):
        self.calls.append(("expander", label, expanded))
        yield

    def video(self, path):
        self.calls.append(("video", path))

    def dataframe(self, value, *, use_container_width, hide_index):
        self.calls.append(("dataframe", value, use_container_width, hide_index))


def test_review_media_prioritizes_timestamped_frames_and_collapses_video(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setattr(app, "st", fake)
    candidate = {
        "source_video": "video_0001",
        "start_time": 1.0,
        "end_time": 3.0,
        "window_role": "transition",
        "_resolved_frames": [{"path": "frame-1.jpg"}, {"path": "frame-2.jpg"}],
        "_actual_sampled_timestamps": [0.0, 2.0],
        "_resolved_video_path": "clip.mp4",
        "actual_frame_mapping": [{"timestamp": 0.0}, {"timestamp": 2.0}],
    }

    app.render_review_media(candidate)

    image_indexes = [
        index for index, call in enumerate(fake.calls) if call[0] == "image"
    ]
    video_index = next(
        index for index, call in enumerate(fake.calls) if call[0] == "video"
    )
    assert image_indexes and max(image_indexes) < video_index
    assert ("image", "frame-1.jpg", "第 1 帧 · 0.000s", True) in fake.calls
    assert ("image", "frame-2.jpg", "第 2 帧 · 2.000s", True) in fake.calls
    assert ("expander", "辅助查看：连续视频", False) in fake.calls
