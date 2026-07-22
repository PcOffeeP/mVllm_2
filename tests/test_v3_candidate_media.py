import json
import subprocess
from pathlib import Path

import pytest

from pipeline.preprocessing import FrameMapping, ProcessorInfo, VideoPreprocessor
from pipeline.roi_media import VideoProbe, probe_video
from pipeline.v3_candidate_media import (
    CandidateMediaError,
    _validate_clip_probe,
    build_crop_command,
    materialize_media_plan,
    validate_actual_sampling_gate,
)


class FakePreprocessor(VideoPreprocessor):
    def __init__(self, mappings: list[FrameMapping], fingerprint: str = "fake:v1") -> None:
        self.mappings = mappings
        self._fingerprint = fingerprint

    def get_info(self) -> ProcessorInfo:
        return ProcessorInfo("fake", "v1", 8, "test")

    def healthcheck(self) -> bool:
        return True

    def sample(self, video_path: str, start_time: float, end_time: float) -> list[FrameMapping]:
        return self.mappings

    def fingerprint(self) -> str:
        return self._fingerprint


def _candidate(state: str = "发生断裂") -> dict:
    return {
        "candidate_id": "video_0001_v3_transition_f000030-000090",
        "source_video": "video_0001",
        "scope": "development",
        "source_video_path": "source.mp4",
        "planned_video_path": "planned.mp4",
        "planned_frame_dir": "planned_frames",
        "media_status": "planned_not_materialized",
        "start_time": 1.0,
        "end_time": 3.0,
        "start_frame": 30,
        "end_frame": 90,
        "duration": 2.0,
        "target_duration_seconds": 2.0,
        "duration_policy": "standard",
        "window_role": "transition",
        "window_variant": None,
        "event_position_ratio": 0.5,
        "review_disposition": "manual_required",
        "reference_match": {"kind": "none", "reference_ids": []},
        "candidate_v3_labels": {
            "clip_state": state,
            "fracture_mechanism": "韧性断裂" if state != "未断裂" else None,
            "root_break": False if state != "未断裂" else None,
            "location": "inside_gauge" if state != "未断裂" else None,
            "special_case": None,
        },
        "source_type": "韧性断裂",
        "source_location": "inside_gauge",
        "roi_provenance": {"roi_media_id": "roi-media-test", "output_sha256": "x"},
    }


def _source_record() -> dict:
    return {
        "video_id": "video_0001",
        "event_time": 2.0,
        "event_time_reliable": True,
        "has_fracture_canonical": True,
        "fps": 30.0,
    }


@pytest.mark.parametrize(
    ("state", "timestamps", "expected", "reason"),
    [
        ("发生断裂", [1.1, 2.0, 2.8], True, "passed"),
        ("发生断裂", [1.1, 1.9], False, "transition_missing_post_event_sample"),
        ("未断裂", [0.5, 1.5], True, "passed"),
        ("未断裂", [1.0, 1.5001], False, "pre_event_sample_crosses_guard"),
        ("已断裂", [2.5, 2.8], True, "passed"),
        ("已断裂", [2.49, 2.8], False, "post_event_sample_crosses_guard"),
    ],
)
def test_actual_sampling_gate(state, timestamps, expected, reason):
    candidate = _candidate(state)
    mapping = [
        {
            "input_index": index,
            "clip_frame": index * 10,
            "timestamp": timestamp,
        }
        for index, timestamp in enumerate(timestamps)
    ]
    assert validate_actual_sampling_gate(candidate, mapping, _source_record()) == (
        expected,
        reason,
    )


def test_crop_command_uses_half_open_source_frame_interval(tmp_path: Path):
    command = build_crop_command(
        tmp_path / "source.mp4", tmp_path / "out.mp4", _candidate(), "30/1"
    )
    assert "-ss" not in command
    assert "trim=start_frame=30:end_frame=90,setpts=N*1/(30*TB)" in command


def test_clip_duration_allows_two_frame_vfr_container_variance():
    candidate = _candidate()
    candidate.update({"start_frame": 0, "end_frame": 91, "duration": 3.0023})
    source = VideoProbe(96, 128, "92/3", "30/1", 92, 3.0)
    clip = VideoProbe(96, 128, "91/3", "30/1", 91, 2.966667)
    _validate_clip_probe(source, clip, candidate)


def _make_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x128:rate=30:duration=4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def _media_plan(tmp_path: Path) -> dict:
    source_path = tmp_path / "source.mp4"
    _make_video(source_path)
    identity = {
        "schema_version": "test",
        "processor_fingerprint": "fake:v1",
        "candidate_count": 1,
    }
    return {
        "media_id": "candidate-media-test",
        "identity": identity,
        "candidate_plan_id": "candidate-plan-test",
        "candidates": [_candidate()],
        "sources": {
            "video_0001": {
                "path": source_path,
                "record": _source_record(),
            }
        },
        "full_scope": True,
        "project_root": str(tmp_path),
    }


def test_materialization_is_frame_exact_atomic_and_resumable(tmp_path: Path):
    plan = _media_plan(tmp_path)
    processor = FakePreprocessor(
        [
            FrameMapping(0, 0, 0.0),
            FrameMapping(1, 30, 1.0),
            FrameMapping(2, 59, 1.9667),
        ]
    )
    destination = materialize_media_plan(
        plan,
        model_path="unused",
        video_output_root=tmp_path / "videos",
        frame_output_root=tmp_path / "frames",
        result_root=tmp_path / "results",
        preprocessor=processor,
    )
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {
        "planned": 1,
        "passed": 1,
        "excluded": 0,
        "development_passed": 1,
        "test_audit_passed": 0,
        "development_manual_review": 1,
    }
    clip = tmp_path / "videos/candidate-plan-test/videos/video_0001_v3_transition_f000030-000090.mp4"
    assert probe_video(clip).frame_count == 60
    frame_dir = tmp_path / "frames/candidate-plan-test/video_0001_v3_transition_f000030-000090"
    assert len(list(frame_dir.glob("frame_*.jpg"))) == 3
    assert materialize_media_plan(
        plan,
        model_path="unused",
        video_output_root=tmp_path / "videos",
        frame_output_root=tmp_path / "frames",
        result_root=tmp_path / "results",
        preprocessor=processor,
    ) == destination
    next(frame_dir.glob("frame_*.jpg")).write_bytes(b"drift")
    with pytest.raises(CandidateMediaError, match="媒体或 receipt 漂移"):
        materialize_media_plan(
            plan,
            model_path="unused",
            video_output_root=tmp_path / "videos",
            frame_output_root=tmp_path / "frames",
            result_root=tmp_path / "results",
            preprocessor=processor,
        )


def test_gate_exclusion_does_not_publish_media(tmp_path: Path):
    plan = _media_plan(tmp_path)
    processor = FakePreprocessor(
        [FrameMapping(0, 0, 0.0), FrameMapping(1, 20, 0.6667)]
    )
    destination = materialize_media_plan(
        plan,
        model_path="unused",
        video_output_root=tmp_path / "videos",
        frame_output_root=tmp_path / "frames",
        result_root=tmp_path / "results",
        preprocessor=processor,
    )
    report = json.loads((destination / "generation_report.json").read_text(encoding="utf-8"))
    assert report["passed_count"] == 0
    assert report["excluded_count"] == 1
    assert report["exclusion_reason_counts"] == {
        "transition_missing_post_event_sample": 1
    }
    assert not list((tmp_path / "videos").rglob("*.mp4"))
    assert not list((tmp_path / "frames").rglob("*.jpg"))


def test_processor_identity_mismatch_fails_closed(tmp_path: Path):
    plan = _media_plan(tmp_path)
    with pytest.raises(CandidateMediaError, match="processor fingerprint"):
        materialize_media_plan(
            plan,
            model_path="unused",
            video_output_root=tmp_path / "videos",
            frame_output_root=tmp_path / "frames",
            result_root=tmp_path / "results",
            preprocessor=FakePreprocessor([], fingerprint="fake:other"),
        )
