"""Offline unit tests for dual-backend inference adapters (http & transformers) and infer CLI.

All tests run 100% offline with zero GPU, zero model weights, and zero external network calls:
- ``HttpBackend`` uses ``httpx.MockTransport`` plus a local loopback ``ThreadingHTTPServer``
  to verify end-to-end wall-clock timeout cancellation on slow headers and slow chunked bodies.
- ``TransformersBackend`` uses injectable fake model/processor/tokenizer hooks and verifies
  that ``torch`` / ``transformers`` are never imported eagerly.
"""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

import httpx
import pytest

from script.five_label_eval import infer
from script.five_label_eval.backends import InferenceRequest, sanitize_base_url
from script.five_label_eval.backends.http_backend import HttpBackend
from script.five_label_eval.backends.transformers_backend import (
    InternVLNativeImageProcessor,
    TransformersBackend,
    compute_minicpm_temporal_ids,
    detect_model_family,
    internvl_dynamic_preprocess,
    verify_trusted_snapshot_sha256,
)
from script.five_label_eval.frames import RECORD_SCHEMA, compute_record_input_id
from script.five_label_eval.score import InputError, extract

LEGAL_JSON = json.dumps(
    {
        "断裂状态": "发生断裂",
        "断裂模式": "韧性断裂",
        "断裂位置": "标距内",
        "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
        "断裂现象": {"伸长": "是", "颈缩": "是", "开裂": "否", "界面分离": "否", "断后脱夹": "否"},
    },
    ensure_ascii=False,
)

# Minimal valid 1x1 PNG bytes (distinct per frame via trailing comment bytes).
PNG_HEADER = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_eight_frames(frames_dir: Path, cid: str = "c00") -> tuple[list[Path], list[dict]]:
    clip_dir = frames_dir / cid
    clip_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    frame_entries: list[dict] = []
    indices = [0, 34, 68, 102, 137, 171, 205, 239]
    for order, clip_idx in enumerate(indices):
        name = f"frame_{order + 1:03d}.png"
        path = clip_dir / name
        payload = PNG_HEADER + f"frame-{order}-{clip_idx}".encode("ascii")
        path.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        frame_paths.append(path)
        frame_entries.append({
            "display_order": order,
            "decode_order": order,
            "clip_frame_index": clip_idx,
            "roi_frame_index": 973 + clip_idx,
            "original_source_frame_index": 973 + clip_idx,
            "is_anchor": False,
            "anchor_ref": None,
            "media_role": "clip",
            "image": name,
            "pts_seconds": round(clip_idx / 30.0, 4),
            "width": 320,
            "height": 240,
            "sha256": sha,
            "frame_index_mapping": {
                "clip_to_roi": {"kind": "manifest_replay", "offset": 973, "reason": None},
                "clip_to_model_input": {
                    "kind": "ffmpeg_select_nth_decoded_frame",
                    "offset": None,
                    "reason": "test",
                    "sampling_rule": "evenly_spaced_inclusive",
                    "target_frame_count": 8,
                    "short_clip_policy": "fail_closed",
                    "resize": None,
                },
                "roi_to_original": {
                    "kind": "explicit_pairs",
                    "offset": 0,
                    "method": "manifest_anchors",
                    "reason": None,
                },
            },
        })
    return frame_paths, frame_entries


def _build_record_and_manifest(tmp_path: Path, cid: str = "c00") -> tuple[dict, dict, Path]:
    frames_dir = tmp_path / "frames"
    _, frame_entries = _write_eight_frames(frames_dir, cid)
    clip_sha = "a" * 64
    manifest_sha = "b" * 64
    record = {
        "record_schema": RECORD_SCHEMA,
        "candidate_id": cid,
        "clip_sha256": clip_sha,
        "manifest_sha256": manifest_sha,
        "input_id": "",
        "frame_count_convention": "decoded",
        "sampling": {
            "sampling_rule": "evenly_spaced_inclusive",
            "target_frame_count": 8,
            "short_clip_policy": "fail_closed",
            "resize": None,
        },
        "media": {"width": 320, "height": 240, "fps": 30.0, "total_frames": 240, "sha256": clip_sha},
        "verification": {
            "method": "manifest_anchors",
            "verdict_id": "v1",
            "evidence_sha256": "e" * 64,
            "conditions": {"explicit_pairs": [True, True, True]},
        },
        "lineage_media": {
            "l0": {"total_frames": 2000, "total_frames_source": "decoded", "sha256": "0" * 64, "declared_sha256": "0" * 64},
            "l1": {"total_frames": 2000, "total_frames_source": "decoded", "sha256": "1" * 64, "declared_sha256": "1" * 64},
            "l2": {"total_frames": 240, "total_frames_source": "decoded", "sha256": clip_sha, "declared_sha256": clip_sha},
        },
        "frames": frame_entries,
    }
    record["input_id"] = compute_record_input_id(record)
    manifest = {
        "manifest_version": "test/1",
        "samples": [{
            "manifest_sha256": manifest_sha,
            "candidate_id": cid,
            "clip_sha256": clip_sha,
            "source_id": "video_0001",
            "source_type": "real",
            "review_id": None,
        }],
    }
    return record, manifest, frames_dir


def _make_request(tmp_path: Path, prompt_text: str = "  verbatim prompt\n", timeout: float = 5.0) -> InferenceRequest:
    record, _, frames_dir = _build_record_and_manifest(tmp_path)
    frame_paths = tuple(frames_dir / "c00" / f["image"] for f in record["frames"])
    frame_pts = tuple(f["pts_seconds"] for f in record["frames"])
    return InferenceRequest(
        candidate_id="c00",
        record=record,
        frame_paths=frame_paths,
        frame_pts_seconds=frame_pts,
        prompt_text=prompt_text,
        timeout_seconds=timeout,
    )


# --------------------------------------------------------------------------------------
# URL sanitization & shared contract helpers
# --------------------------------------------------------------------------------------
def test_sanitize_base_url_strips_credentials_query_and_fragment():
    assert sanitize_base_url("https://user:s3cr3t@127.0.0.1:8000/v1/?api_key=xyz#frag") == "https://127.0.0.1:8000/v1"
    assert sanitize_base_url("http://localhost:9000") == "http://localhost:9000"


# --------------------------------------------------------------------------------------
# HttpBackend offline unit tests (MockTransport + real loopback timeout server)
# --------------------------------------------------------------------------------------
def test_http_backend_sends_ordered_8_frames_verbatim_prompt_and_no_leakage(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_VLM_API_KEY", "secret-token-value")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": LEGAL_JSON}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    req = _make_request(tmp_path, prompt_text="  请严格输出 JSON\n")
    backend = HttpBackend(
        endpoint="http://user:pass@127.0.0.1:8000/v1?token=leak",
        model_id="Qwen3-VL-8B-Instruct@sha256:deadbeef",
        api_model_name="Qwen/Qwen3-VL-8B-Instruct",
        api_key_env="TEST_VLM_API_KEY",
        max_pixels=65536,
        sampling_policy=req.record["sampling"],
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.infer_one(req)
        identity = backend.run_identity()
    finally:
        backend.close()

    assert result.status == "success"
    assert result.raw_output == LEGAL_JSON
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["auth"] == "Bearer secret-token-value"

    content = captured["body"]["messages"][0]["content"]
    assert len(content) == 9  # 8 images + 1 verbatim text
    expected_urls = [
        f"data:image/png;base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"
        for p in req.frame_paths
    ]
    assert [item["image_url"]["url"] for item in content[:8]] == expected_urls
    assert content[8] == {"type": "text", "text": "  请严格输出 JSON\n"}
    assert captured["body"]["mm_processor_kwargs"] == {"max_pixels": 65536}

    # Zero leakage of candidate_id or filesystem paths in payload.
    serialized_payload = json.dumps(captured["body"], ensure_ascii=False)
    assert "c00" not in serialized_payload
    assert str(tmp_path) not in serialized_payload

    # Run identity metadata sanitized (no secret key, no credentials in URL).
    assert identity["backend"] == "http"
    assert identity["model_id"] == "Qwen3-VL-8B-Instruct@sha256:deadbeef"
    assert identity["base_url"] == "http://127.0.0.1:8000/v1"
    assert identity["max_pixels"] == 65536
    assert identity["sampling_policy"]["target_frame_count"] == 8
    assert identity["output_unwrapping"] == "none"
    serialized_identity = json.dumps(identity, ensure_ascii=False)
    assert "secret-token-value" not in serialized_identity
    assert "pass" not in serialized_identity


def test_http_backend_preserves_answer_tags_verbatim_without_unwrapping(tmp_path):
    wrapped = f"<answer>{LEGAL_JSON}</answer>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": wrapped,
                        "reasoning_content": "step-by-step reasoning",
                    }
                }]
            },
        )

    backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="GLM-4.1V-9B-Thinking@sha256:abc",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.infer_one(_make_request(tmp_path))
    finally:
        backend.close()

    assert result.status == "success"
    assert result.raw_output == wrapped
    assert result.reasoning_content == "step-by-step reasoning"
    # Scorer must see the surrounding <answer> wrapper and mark strict_format_valid=False.
    extraction = extract(result.raw_output)
    assert extraction["strict_format_valid"] is False
    assert "surrounding_text_or_fence" in extraction["issues"]


@pytest.mark.parametrize("response_factory", [
    pytest.param(lambda _r: httpx.Response(500, text="internal error"), id="http-500"),
    pytest.param(lambda _r: httpx.Response(400, text="bad request"), id="http-400"),
    pytest.param(lambda _r: httpx.Response(200, text="not-json"), id="invalid-json"),
    pytest.param(lambda _r: httpx.Response(200, json={"choices": []}), id="empty-choices"),
    pytest.param(lambda _r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}), id="empty-content"),
    pytest.param(lambda _r: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}), id="null-content"),
])
def test_http_backend_maps_http_and_json_errors_to_request_failed(tmp_path, response_factory):
    backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@sha256:abc",
        transport=httpx.MockTransport(response_factory),
    )
    try:
        result = backend.infer_one(_make_request(tmp_path))
    finally:
        backend.close()

    assert result.status == "request_failed"
    assert result.raw_output is None
    assert result.error_detail


def test_http_backend_rejects_fake_model_id_and_missing_api_key_env(monkeypatch):
    with pytest.raises(InputError):
        HttpBackend(endpoint="http://127.0.0.1:8000", model_id="fake")
    monkeypatch.delenv("UNSET_VLM_KEY", raising=False)
    with pytest.raises(InputError):
        HttpBackend(
            endpoint="http://127.0.0.1:8000",
            model_id="Qwen3-VL-8B-Instruct@sha256:abc",
            api_key_env="UNSET_VLM_KEY",
        )


def _start_loopback_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_http_backend_loopback_slow_headers_and_slow_body_hit_wall_clock_timeout(tmp_path):
    aborted_paths: list[str] = []

    class SlowHandler(BaseHTTPRequestHandler):
        def log_message(self, _fmt, *_args):
            return None

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            if self.path.startswith("/trickle-headers"):
                # Trickle response headers faster than per-read timeout so only a true
                # end-to-end wall-clock deadline can cancel the request on time.
                try:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                    self.wfile.flush()
                    for idx in range(40):
                        self.wfile.write(f"X-Pad-{idx}: 1\r\n".encode("ascii"))
                        self.wfile.flush()
                        time.sleep(0.04)
                    self.wfile.write(b"Content-Length: 2\r\n\r\n{}")
                    self.wfile.flush()
                except OSError:
                    aborted_paths.append(self.path)
                    return
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    for _ in range(40):
                        self.wfile.write(b"1\r\n \r\n")
                        self.wfile.flush()
                        time.sleep(0.04)
                    self.wfile.write(b"0\r\n\r\n")
                except OSError:
                    aborted_paths.append(self.path)
                    return

    server, base_url = _start_loopback_server(SlowHandler)
    try:
        req = _make_request(tmp_path, timeout=0.25)
        for path in ("/trickle-headers/v1/chat/completions", "/slow-body/v1/chat/completions"):
            backend = HttpBackend(
                endpoint=base_url + path,
                model_id="Qwen3-VL-8B-Instruct@sha256:abc",
                timeout_seconds=0.25,
            )
            try:
                started = time.monotonic()
                result = backend.infer_one(req)
                elapsed = time.monotonic() - started
            finally:
                backend.close()
            assert result.status == "timeout"
            assert result.raw_output is None
            assert elapsed < 0.8, f"wall-clock timeout took too long ({elapsed:.3f}s) for {path}"
        # Allow server handler threads a brief moment to observe BrokenPipeError / ConnectionResetError.
        time.sleep(0.15)
        assert len(aborted_paths) == 2, f"expected peer disconnect on both timeouts, got {aborted_paths}"
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------------------
# TransformersBackend offline unit tests (injectable hooks, zero torch/transformers import)
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("model_id,expected", [
    ("openbmb/MiniCPM-V-4_5@sha256:1234", "minicpm-v-4.5"),
    ("MiniCPM-V-4.5-local", "minicpm-v-4.5"),
    ("Qwen/Qwen3-VL-8B-Instruct@sha256:1234", "qwen3-vl"),
    ("OpenGVLab/InternVL3-8B@sha256:1234", "internvl3"),
    ("OpenGVLab/InternVL3.5-8B@sha256:1234", "internvl3.5"),
])
def test_detect_model_family_supports_tier1_models(model_id, expected):
    assert detect_model_family(model_id) == expected


def test_detect_model_family_fails_closed_for_unknown_model():
    with pytest.raises(InputError):
        detect_model_family("unknown/some-vlm-7b")


def test_compute_minicpm_temporal_ids_quantizes_to_0_1s_grid():
    pts = [0.0, 0.25, 0.54, 1.0, 2.34, 3.66, 4.99, 5.0]
    assert compute_minicpm_temporal_ids(pts) == [[0], [2], [5], [10], [23], [37], [50], [50]]

    # Fallback to clip_frame_indices / fps when pts_seconds omitted
    assert compute_minicpm_temporal_ids(None, frame_indices=[0, 15, 30], fps=30.0) == [[0], [5], [10]]

    # Fail-closed when neither is available
    with pytest.raises(InputError):
        compute_minicpm_temporal_ids(None)


def test_transformers_backend_minicpm_passes_quantized_temporal_ids_and_max_slice_1(tmp_path):
    called: dict = {}

    class FakeMiniCPMModel:
        def chat(self, **kwargs):
            called.update(kwargs)
            return LEGAL_JSON

    req = _make_request(tmp_path, prompt_text="  MiniCPM prompt\n")
    backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:deadbeef",
        max_pixels=65536,
        sampling_policy=req.record["sampling"],
        model=FakeMiniCPMModel(),
        tokenizer=object(),
        image_loader=lambda p: f"IMG:{p.name}",
    )

    result = backend.infer_one(req)
    identity = backend.run_identity()

    assert result.status == "success"
    assert result.raw_output == LEGAL_JSON
    assert called["max_slice_nums"] == 1
    assert called["use_image_id"] is False
    expected_tids = compute_minicpm_temporal_ids(req.frame_pts_seconds)
    assert called["temporal_ids"] == expected_tids
    assert len(called["temporal_ids"]) == 8
    content = called["msgs"][0]["content"]
    assert content[:8] == [f"IMG:frame_{i:03d}.png" for i in range(1, 9)]
    assert content[8] == "  MiniCPM prompt\n"

    assert identity["backend"] == "transformers"
    assert identity["model_family"] == "minicpm-v-4.5"
    assert identity["temporal_ids_policy"] == "quantized_0.1s"
    assert identity["temporal_ids_grid_seconds"] == 0.1
    assert identity["max_slice_nums"] == 1
    assert identity["max_pixels"] == 65536
    assert identity["output_unwrapping"] == "none"
    # Verify lazy import: torch & transformers are never imported in offline hook tests.
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


@pytest.mark.parametrize("model_id,family", [
    ("Qwen/Qwen3-VL-8B-Instruct@sha256:1111", "qwen3-vl"),
    ("OpenGVLab/InternVL3-8B@sha256:2222", "internvl3"),
    ("OpenGVLab/InternVL3.5-8B@sha256:3333", "internvl3.5"),
])
def test_transformers_backend_supports_qwen3_and_internvl_families_without_unwrapping(tmp_path, model_id, family):
    captured: dict = {}
    wrapped_output = f"<answer>{LEGAL_JSON}</answer>"

    class FakeProcessor:
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            captured["messages"] = messages
            return "<prompt>"

        def __call__(self, **kwargs):
            captured["proc_kwargs"] = kwargs
            return {"input_ids": [[1, 2, 3]]}

        def batch_decode(self, sequences, skip_special_tokens=True):
            return [wrapped_output]

    class FakeModel:
        def generate(self, **kwargs):
            captured["gen_kwargs"] = kwargs
            return [[1, 2, 3, 99]]

    backend = TransformersBackend(
        model_id=model_id,
        max_pixels=262144,
        model=FakeModel(),
        processor=FakeProcessor(),
        image_loader=lambda p: f"IMG:{p.name}",
    )
    result = backend.infer_one(_make_request(tmp_path))
    identity = backend.run_identity()

    assert result.status == "success"
    # Strict contract: NO <answer> unwrapping!
    assert result.raw_output == wrapped_output
    assert captured["proc_kwargs"]["max_pixels"] == 262144
    assert len(captured["proc_kwargs"]["images"]) == 8
    assert identity["model_family"] == family
    assert identity["max_pixels"] == 262144
    assert identity["temporal_ids_policy"] == "not_applicable"
    assert identity["max_slice_nums"] is None


def test_transformers_backend_trusted_snapshot_sha256_fails_closed(tmp_path):
    model_dir = tmp_path / "minicpmv4_5"
    model_dir.mkdir()
    cfg = model_dir / "config.json"
    cfg.write_bytes(b'{"version": "4.5"}')
    py_mod = model_dir / "modeling_minicpmv.py"
    py_mod.write_bytes(b"def init():\n    return True\n")
    good_cfg = hashlib.sha256(cfg.read_bytes()).hexdigest()
    good_py = hashlib.sha256(py_mod.read_bytes()).hexdigest()

    # Must cover both config.json and every .py file before trust_remote_code=True.
    with pytest.raises(InputError, match="uncovered"):
        verify_trusted_snapshot_sha256(model_dir, {"config.json": good_cfg})

    assert verify_trusted_snapshot_sha256(
        model_dir, {"config.json": good_cfg, "modeling_minicpmv.py": good_py}
    ) == {"config.json": good_cfg, "modeling_minicpmv.py": good_py}

    loader_called = False

    def fake_loader(*_args):
        nonlocal loader_called
        loader_called = True
        return object(), None, None

    # Omitting trusted_files_sha256 entirely must fail closed before loading.
    backend_no_manifest = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:deadbeef",
        model_path=model_dir,
        model_loader=fake_loader,
    )
    with pytest.raises(InputError, match="trusted_files_sha256"):
        backend_no_manifest.infer_one(_make_request(tmp_path))
    assert loader_called is False

    # Hash mismatch must fail closed before loading.
    backend_bad_hash = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:deadbeef",
        model_path=model_dir,
        trusted_files_sha256={"config.json": "0" * 64, "modeling_minicpmv.py": good_py},
        model_loader=fake_loader,
    )
    with pytest.raises(InputError, match="SHA-256 mismatch"):
        backend_bad_hash.infer_one(_make_request(tmp_path))
    assert loader_called is False


def test_transformers_backend_trims_prompt_tokens_from_batch_feature_mapping(tmp_path):
    """HF BatchFeature is a Mapping (not a plain dict); prompt tokens must be trimmed."""
    from collections.abc import Mapping

    class FakeBatchFeature(Mapping):
        def __init__(self, data):
            self._data = data

        def __getitem__(self, key):
            return self._data[key]

        def __iter__(self):
            return iter(self._data)

        def __len__(self):
            return len(self._data)

    decoded_seqs: list = []

    class FakeProcessor:
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            return "PROMPT"

        def __call__(self, **kwargs):
            return FakeBatchFeature({"input_ids": [[10, 20, 30]]})

        def batch_decode(self, sequences, skip_special_tokens=True):
            decoded_seqs.extend(sequences)
            # Only return pure JSON when prompt tokens [10, 20, 30] were trimmed!
            return [LEGAL_JSON if sequences == [[99, 100]] else f"PROMPT{LEGAL_JSON}"]

    class FakeModel:
        def generate(self, **kwargs):
            return [[10, 20, 30, 99, 100]]

    backend = TransformersBackend(
        model_id="Qwen/Qwen3-VL-8B-Instruct@sha256:1111",
        model=FakeModel(),
        processor=FakeProcessor(),
        image_loader=lambda p: p.name,
    )
    result = backend.infer_one(_make_request(tmp_path))

    assert decoded_seqs == [[99, 100]]
    assert result.status == "success"
    assert result.raw_output == LEGAL_JSON


def test_transformers_backend_internvl_native_chat_uses_pixel_values_signature(tmp_path):
    """Native OpenGVLab InternVL3/3.5 chat() expects (tokenizer, pixel_values, question, generation_config, num_patches_list)."""
    called: dict = {}

    class FakeInternVLProcessor:
        def __call__(self, **kwargs):
            called["proc_kwargs"] = kwargs
            return {"pixel_values": "TENSOR_PV", "num_patches_list": [1] * len(kwargs["images"])}

    class FakeInternVLNativeModel:
        def chat(self, tokenizer, pixel_values, question, generation_config, num_patches_list=None):
            called["args"] = (tokenizer, pixel_values, question, generation_config, num_patches_list)
            return LEGAL_JSON

    tok = object()
    backend = TransformersBackend(
        model_id="OpenGVLab/InternVL3.5-8B@sha256:3333",
        max_pixels=262144,
        model=FakeInternVLNativeModel(),
        processor=FakeInternVLProcessor(),
        tokenizer=tok,
        image_loader=lambda p: p.name,
    )
    result = backend.infer_one(_make_request(tmp_path, prompt_text="请判断五类标签"))

    assert result.status == "success"
    assert result.raw_output == LEGAL_JSON
    assert called["args"][0] is tok
    assert called["args"][1] == "TENSOR_PV"
    assert called["args"][2].count("<image>") == 8
    assert called["args"][2].endswith("请判断五类标签")
    assert called["args"][4] == [1] * 8


def test_transformers_backend_sigalrm_timeout_and_oom_error_handling(tmp_path):
    class SlowModel:
        def chat(self, **_kwargs):
            time.sleep(0.5)
            return LEGAL_JSON

    slow_backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:deadbeef",
        timeout_seconds=0.1,
        model=SlowModel(),
        image_loader=lambda p: p.name,
    )
    timeout_res = slow_backend.infer_one(_make_request(tmp_path, timeout=0.1))
    assert timeout_res.status == "timeout"
    assert timeout_res.raw_output is None

    class OomModel:
        def chat(self, **_kwargs):
            raise RuntimeError("CUDA out of memory")

    oom_backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:deadbeef",
        model=OomModel(),
        image_loader=lambda p: p.name,
    )
    oom_res = oom_backend.infer_one(_make_request(tmp_path))
    assert oom_res.status == "request_failed"
    assert oom_res.raw_output is None
    assert "CUDA out of memory" in (oom_res.error_detail or "")


# --------------------------------------------------------------------------------------
# infer.py end-to-end CLI with local loopback mock HTTP server
# --------------------------------------------------------------------------------------
def test_infer_cli_http_backend_end_to_end_with_loopback_server(tmp_path):
    record, manifest, frames_dir = _build_record_and_manifest(tmp_path)
    records_path = frames_dir / "records.jsonl"
    records_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("只输出一个 JSON 对象\n", encoding="utf-8")
    output_path = tmp_path / "predictions.jsonl"
    meta_path = tmp_path / "run_meta.json"

    class MockOpenAIHandler(BaseHTTPRequestHandler):
        def log_message(self, _fmt, *_args):
            return None

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            body = json.dumps({"choices": [{"message": {"content": LEGAL_JSON}}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server, base_url = _start_loopback_server(MockOpenAIHandler)
    try:
        rc = infer.main([
            "--backend", "http",
            "--endpoint", base_url,
            "--model-id", "Qwen3-VL-8B-Instruct@sha256:1234",
            "--api-model-name", "Qwen/Qwen3-VL-8B-Instruct",
            "--run-id", "run-http-1",
            "--manifest", str(manifest_path),
            "--input-config", str(records_path),
            "--frames-dir", str(frames_dir),
            "--prompt-file", str(prompt_path),
            "--max-pixels", "65536",
            "--output", str(output_path),
            "--meta-output", str(meta_path),
        ])
    finally:
        server.shutdown()
        server.server_close()

    assert rc == 0
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "success"
    assert row["raw_output"] == LEGAL_JSON
    assert row["model_id"] == "Qwen3-VL-8B-Instruct@sha256:1234"
    # Strict output contract: no sidecar parsed label fields in predictions.jsonl.
    assert not ({"labels", "fields", "parsed"} & set(row))

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["backend_identity"]["backend"] == "http"
    assert meta["backend_identity"]["max_pixels"] == 65536
    assert meta["sampling_policy"]["target_frame_count"] == 8
    assert meta["status_counts"] == {"success": 1, "request_failed": 0, "timeout": 0}


def test_run_inference_guards_8_frame_contract_path_traversal_png_and_meta_output(tmp_path):
    class SpyBackend:
        backend_name = "http"

        def __init__(self):
            self.calls = 0

        def run_identity(self):
            return {"backend": "http"}

        def infer_one(self, request):
            self.calls += 1
            raise AssertionError("backend must not be called when pre-flight validation fails")

        def close(self):
            return None

    # 1. Reject 3-frame record under real backend
    rec3, manifest, frames_dir = _build_record_and_manifest(tmp_path / "case_3f")
    rec3["frames"] = rec3["frames"][:3]
    rec3["sampling"]["target_frame_count"] = 3
    with pytest.raises(InputError, match="8-frame"):
        infer.run_inference(
            [rec3], manifest, backend=SpyBackend(), run_id="r1",
            prompt_id="prompt@sha256:" + "a" * 64, prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1", frames_dir=frames_dir,
        )

    # 2. Reject path traversal in frame image name
    rec_trav, manifest, frames_dir = _build_record_and_manifest(tmp_path / "case_trav")
    rec_trav["frames"][0]["image"] = "../escape.png"
    with pytest.raises(InputError, match="safe path component"):
        infer.run_inference(
            [rec_trav], manifest, backend=SpyBackend(), run_id="r1",
            prompt_id="prompt@sha256:" + "a" * 64, prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1", frames_dir=frames_dir,
        )

    # 3. Reject symlink frame pointing outside candidate dir
    rec_sym, manifest, frames_dir = _build_record_and_manifest(tmp_path / "case_sym")
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG_HEADER + b"outside")
    target = frames_dir / "c00" / rec_sym["frames"][0]["image"]
    target.unlink()
    target.symlink_to(outside)
    rec_sym["frames"][0]["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    with pytest.raises(InputError, match="symlink"):
        infer.run_inference(
            [rec_sym], manifest, backend=SpyBackend(), run_id="r1",
            prompt_id="prompt@sha256:" + "a" * 64, prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1", frames_dir=frames_dir,
        )

    # 4. Reject non-PNG bytes even when sha256 matches
    rec_nonpng, manifest, frames_dir = _build_record_and_manifest(tmp_path / "case_nonpng")
    target = frames_dir / "c00" / rec_nonpng["frames"][0]["image"]
    target.write_bytes(b"NOT A PNG SECRET")
    rec_nonpng["frames"][0]["sha256"] = hashlib.sha256(b"NOT A PNG SECRET").hexdigest()
    with pytest.raises(InputError, match="valid PNG"):
        infer.run_inference(
            [rec_nonpng], manifest, backend=SpyBackend(), run_id="r1",
            prompt_id="prompt@sha256:" + "a" * 64, prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1", frames_dir=frames_dir,
        )

    # 5. Reserve meta_output_path before making any backend request
    rec_meta, manifest, frames_dir = _build_record_and_manifest(tmp_path / "case_meta")
    existing_meta = tmp_path / "existing.meta.json"
    existing_meta.write_text("{}", encoding="utf-8")
    spy = SpyBackend()
    with pytest.raises(FileExistsError):
        infer.run_inference(
            [rec_meta], manifest, backend=spy, run_id="r1",
            prompt_id="prompt@sha256:" + "a" * 64, prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1", frames_dir=frames_dir,
            output_path=tmp_path / "new_preds.jsonl",
            meta_output_path=existing_meta,
        )
    assert spy.calls == 0


def test_infer_fake_cli_works_without_httpx_installed(tmp_path, monkeypatch):
    """Fake backend CLI must not import httpx at module import time."""
    record, manifest, frames_dir = _build_record_and_manifest(tmp_path)
    records_path = frames_dir / "records.jsonl"
    records_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("只输出一个 JSON 对象\n", encoding="utf-8")
    output_path = tmp_path / "fake_predictions.jsonl"

    monkeypatch.setitem(sys.modules, "httpx", None)
    rc = infer.main([
        "--backend", "fake",
        "--model-id", "fake",
        "--run-id", "run-fake-no-httpx",
        "--manifest", str(manifest_path),
        "--input-config", str(records_path),
        "--prompt-file", str(prompt_path),
        "--output", str(output_path),
    ])
    assert rc == 0
    assert output_path.is_file()


def test_r2_regression_device_placement_minicpm_max_pixels_processor_config_and_toctou(tmp_path):
    """Regression tests for Round-2 Codex review findings."""
    # 1. Qwen3-VL moves BatchFeature inputs onto model.device before generate().
    moved_devices: list = []

    class FakeDeviceBatch(dict):
        def to(self, device):
            moved_devices.append(device)
            return self

    class FakeCudaProcessor:
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            return "P"

        def __call__(self, **kwargs):
            return FakeDeviceBatch({"input_ids": [[1, 2]]})

        def batch_decode(self, sequences, skip_special_tokens=True):
            return [LEGAL_JSON]

    class FakeCudaModel:
        device = "cuda:0"

        def generate(self, **kwargs):
            return [[1, 2, 9]]

    qwen = TransformersBackend(
        model_id="Qwen/Qwen3-VL-8B-Instruct@sha256:1",
        model=FakeCudaModel(),
        processor=FakeCudaProcessor(),
        image_loader=lambda p: p.name,
    )
    assert qwen.infer_one(_make_request(tmp_path / "r2_cuda")).status == "success"
    assert moved_devices == ["cuda:0"]

    # 2. MiniCPM enforces max_pixels downscale before model.chat().
    seen_sizes: list[tuple[int, int]] = []

    class FakePILImage:
        def __init__(self, size):
            self.size = size

        def resize(self, new_size):
            return FakePILImage(new_size)

    class FakeMiniCPM:
        def chat(self, **kwargs):
            for item in kwargs["msgs"][0]["content"][:8]:
                seen_sizes.append(item.size)
            return LEGAL_JSON

    mcpm = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        max_pixels=10000,
        model=FakeMiniCPM(),
        image_loader=lambda _p: FakePILImage((400, 400)),
    )
    assert mcpm.infer_one(_make_request(tmp_path / "r2_mcpm")).status == "success"
    assert all(w * h <= 10000 for w, h in seen_sizes)

    # 3. Trusted snapshot verification covers processor_config.json and rejects external auto_map.
    mdir = tmp_path / "r2_snap"
    mdir.mkdir()
    (mdir / "config.json").write_bytes(b'{"version": "4.5"}')
    (mdir / "processor_config.json").write_bytes(b'{"auto_map": {"AutoProcessor": "evil/repo--proc.P"}}')
    cfg_sha = hashlib.sha256((mdir / "config.json").read_bytes()).hexdigest()
    proc_sha = hashlib.sha256((mdir / "processor_config.json").read_bytes()).hexdigest()
    with pytest.raises(InputError, match="processor_config.json"):
        verify_trusted_snapshot_sha256(mdir, {"config.json": cfg_sha})
    with pytest.raises(InputError, match="external auto_map"):
        verify_trusted_snapshot_sha256(mdir, {"config.json": cfg_sha, "processor_config.json": proc_sha})

    # 4. TOCTOU protection with O(1) frame-byte retention: mutating candidate 2's PNG during
    #    candidate 1's request causes candidate 2 to fail closed on sha256 mismatch before sending.
    rec1, m1, frames_dir = _build_record_and_manifest(tmp_path / "r2_toctou", cid="c00")
    _, entries2 = _write_eight_frames(frames_dir, cid="c01")
    rec2 = {**rec1, "candidate_id": "c01", "frames": entries2}
    rec2["input_id"] = compute_record_input_id(rec2)
    manifest = {"manifest_version": "test/1", "samples": [m1["samples"][0], {**m1["samples"][0], "candidate_id": "c01"}]}
    sent_count = 0

    def toctou_handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_count
        sent_count += 1
        if sent_count == 1:
            # Tamper with c01's PNG on disk while c00 is in flight.
            (frames_dir / "c01" / entries2[0]["image"]).write_bytes(PNG_HEADER + b"TAMPERED")
        return httpx.Response(200, json={"choices": [{"message": {"content": LEGAL_JSON}}]})

    http_backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@sha256:1",
        transport=httpx.MockTransport(toctou_handler),
    )
    try:
        with pytest.raises(InputError, match="sha256 mismatch"):
            infer.run_inference(
                [rec1, rec2], manifest, backend=http_backend, run_id="r-toctou",
                prompt_id="prompt@sha256:" + "a" * 64, prompt_text="p",
                model_id="Qwen3-VL-8B-Instruct@sha256:1", frames_dir=frames_dir,
            )
    finally:
        http_backend.close()
    assert sent_count == 1


def test_r3_regression_tokenizer_auto_map_internvl_default_loader_seed_and_meta_checkpoint(tmp_path, monkeypatch):
    """Regression tests for unresolved PR #24 bot findings (4689838553, 4689785933, 4689785953, 4689715685)."""
    import types
    from script.five_label_eval.backends.transformers_backend import _default_model_loader

    # 1. Reject external auto_map in tokenizer_config.json (both dict and legacy list forms).
    for form_name, tok_cfg in (
        ("dict", {"auto_map": {"AutoTokenizer": ["evil/repo--tok.Tok", None]}}),
        ("list", {"auto_map": ["evil/repo--tok.Tok"]}),
    ):
        mdir = tmp_path / f"tok_ext_{form_name}"
        mdir.mkdir()
        (mdir / "config.json").write_bytes(b'{"version": "4.5"}')
        (mdir / "tokenizer_config.json").write_bytes(json.dumps(tok_cfg).encode("utf-8"))
        manifest_sha = {
            "config.json": hashlib.sha256((mdir / "config.json").read_bytes()).hexdigest(),
            "tokenizer_config.json": hashlib.sha256((mdir / "tokenizer_config.json").read_bytes()).hexdigest(),
        }
        with pytest.raises(InputError, match="tokenizer_config.json"):
            verify_trusted_snapshot_sha256(mdir, manifest_sha)

    # 2. Default loader uses InternVLNativeImageProcessor (not AutoProcessor or CLIP AutoImageProcessor)
    #    for native InternVL with model.chat().
    from PIL import Image

    loader_calls: list[str] = []

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def is_bf16_supported():
            return False

    fake_torch = types.SimpleNamespace(
        bfloat16="bf16",
        cuda=FakeCuda(),
        manual_seed=lambda s: loader_calls.append(f"torch.manual_seed({s})"),
    )

    class FakeNativeInternVL:
        def eval(self):
            return self

        def chat(self, tokenizer, pixel_values, question, generation_config, num_patches_list=None):
            loader_calls.append(f"chat_patches={num_patches_list}")
            return LEGAL_JSON

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            return FakeNativeInternVL()

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            return "TOK"

    class FakeAutoImageProcessor:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            raise AssertionError("native InternVL must not use CLIP AutoImageProcessor")

    class FakeAutoProcessor:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            raise AssertionError("native InternVL must use InternVLNativeImageProcessor, not AutoProcessor")

    fake_transformers = types.SimpleNamespace(
        AutoModel=FakeAutoModel,
        AutoModelForCausalLM=FakeAutoModel,
        AutoTokenizer=FakeAutoTokenizer,
        AutoProcessor=FakeAutoProcessor,
        AutoImageProcessor=FakeAutoImageProcessor,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    internvl_dir = tmp_path / "internvl3_snap"
    internvl_dir.mkdir()
    (internvl_dir / "config.json").write_text(json.dumps({"force_image_size": 32}), encoding="utf-8")
    (internvl_dir / "preprocessor_config.json").write_text(
        json.dumps({"feature_extractor_type": "CLIPFeatureExtractor", "do_center_crop": True}),
        encoding="utf-8",
    )

    model, proc, tok = _default_model_loader(internvl_dir, "internvl3", None)
    assert isinstance(proc, InternVLNativeImageProcessor)
    assert proc.image_size == 32
    backend = TransformersBackend(
        model_id="OpenGVLab/InternVL3-8B@sha256:1",
        temperature=0.2,
        seed=42,
        model=model,
        processor=proc,
        tokenizer=tok,
        image_loader=lambda _p: Image.new("RGB", (64, 32), color=(10, 20, 30)),
    )
    res = backend.infer_one(_make_request(tmp_path / "r3_internvl"))
    assert res.status == "success"
    assert res.raw_output == LEGAL_JSON
    assert "torch.manual_seed(42)" in loader_calls
    assert f"chat_patches={[3] * 8}" in loader_calls

    # 3. Interruption mid-batch checkpoints run_meta (never 0 bytes) alongside flushed predictions.
    rec1, m1, frames_dir = _build_record_and_manifest(tmp_path / "r3_interrupt", cid="c00")
    _, entries2 = _write_eight_frames(frames_dir, cid="c01")
    rec2 = {**rec1, "candidate_id": "c01", "frames": entries2}
    rec2["input_id"] = compute_record_input_id(rec2)
    manifest = {"manifest_version": "test/1", "samples": [m1["samples"][0], {**m1["samples"][0], "candidate_id": "c01"}]}

    class InterruptOnSecondBackend:
        backend_name = "http"

        def __init__(self):
            self.n = 0

        def run_identity(self):
            return {"backend": "http", "model_id": "Qwen3-VL-8B-Instruct@1"}

        def infer_one(self, request):
            from script.five_label_eval.backends import InferenceResult

            self.n += 1
            if self.n == 2:
                raise KeyboardInterrupt("simulated ctrl-c")
            return InferenceResult(status="success", raw_output=LEGAL_JSON, latency_seconds=0.1)

        def close(self):
            return None

    preds_path = tmp_path / "interrupted_preds.jsonl"
    meta_path = tmp_path / "interrupted_meta.json"
    with pytest.raises(KeyboardInterrupt):
        infer.run_inference(
            [rec1, rec2],
            manifest,
            backend=InterruptOnSecondBackend(),
            run_id="r-int",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
            output_path=preds_path,
            meta_output_path=meta_path,
        )

    pred_lines = [l for l in preds_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(pred_lines) == 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["run_status"] == "interrupted"
    assert meta["total_requests"] == 1
    assert meta["backend_identity"]["backend"] == "http"
    assert len(meta["requests"]) == 1


def test_r4_regression_peft_rejection_error_secret_redaction_and_atomic_meta(tmp_path, monkeypatch):
    """Regression tests for PEFT adapter rejection, HTTP error secret redaction, and atomic metadata replace."""
    # 1. PEFT adapter_config.json rejected fail-closed.
    peft_dir = tmp_path / "peft_snap"
    peft_dir.mkdir()
    (peft_dir / "config.json").write_bytes(b'{}')
    (peft_dir / "adapter_config.json").write_bytes(b'{"base_model_name_or_path": "/other/model"}')
    cfg_sha = hashlib.sha256(b"{}").hexdigest()
    with pytest.raises(InputError, match="adapter_config.json"):
        verify_trusted_snapshot_sha256(peft_dir, {"config.json": cfg_sha})

    # 2. HTTP 401 echoing Authorization header must never leak secret into error_detail.
    monkeypatch.setenv("TEST_SECRET_KEY", "super-secret-bearer-token")
    backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@1",
        api_key_env="TEST_SECRET_KEY",
        transport=httpx.MockTransport(
            lambda _req: httpx.Response(401, text="Unauthorized: Bearer super-secret-bearer-token")
        ),
    )
    try:
        res = backend.infer_one(_make_request(tmp_path / "r4_secret"))
    finally:
        backend.close()
    assert res.status == "request_failed"
    assert res.raw_output is None
    assert "super-secret-bearer-token" not in (res.error_detail or "")
    assert "HTTP 401" in (res.error_detail or "")

    # 3. Atomic metadata checkpoint preserves last valid checkpoint if a subsequent replace fails.
    rec1, m1, frames_dir = _build_record_and_manifest(tmp_path / "r4_atomic", cid="c00")
    _, entries2 = _write_eight_frames(frames_dir, cid="c01")
    rec2 = {**rec1, "candidate_id": "c01", "frames": entries2}
    rec2["input_id"] = compute_record_input_id(rec2)
    manifest = {"manifest_version": "test/1", "samples": [m1["samples"][0], {**m1["samples"][0], "candidate_id": "c01"}]}
    preds_path = tmp_path / "atomic_preds.jsonl"
    meta_path = tmp_path / "atomic_meta.json"

    import os as _os

    real_replace = _os.replace
    replace_calls = 0

    def flaky_replace(src, dst):
        nonlocal replace_calls
        replace_calls += 1
        # Succeed for initial "running" and after req #1; fail on req #2 checkpoint.
        if replace_calls >= 3:
            raise OSError("simulated disk full during atomic replace")
        return real_replace(src, dst)

    class TwoSuccessBackend:
        backend_name = "http"

        def run_identity(self):
            return {"backend": "http"}

        def infer_one(self, request):
            from script.five_label_eval.backends import InferenceResult

            return InferenceResult(status="success", raw_output=LEGAL_JSON, latency_seconds=0.05)

        def close(self):
            return None

    monkeypatch.setattr(infer.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="disk full"):
        infer.run_inference(
            [rec1, rec2],
            manifest,
            backend=TwoSuccessBackend(),
            run_id="r-atomic",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
            output_path=preds_path,
            meta_output_path=meta_path,
        )
    # Previous valid checkpoint (after req #1) survived intact!
    surviving = json.loads(meta_path.read_text(encoding="utf-8"))
    assert surviving["total_requests"] == 1
    assert surviving["backend_identity"]["backend"] == "http"


def test_r5_regression_internvl_native_full_frame_preservation_and_max_pixels(tmp_path, monkeypatch):
    """Regression tests for PR #24 P2 findings: full-frame InternVL preprocessing and max_pixels enforcement."""
    import numpy as np
    from PIL import Image

    # Build a 2:1 non-square image with distinct edge markers that CLIP center-crop would discard:
    # left 80px = pure red (255, 0, 0), center 480px = black (0, 0, 0), right 80px = pure blue (0, 0, 255).
    edge_arr = np.zeros((320, 640, 3), dtype=np.uint8)
    edge_arr[:, :80, 0] = 255
    edge_arr[:, 560:, 2] = 255
    edge_img = Image.fromarray(edge_arr, mode="RGB")

    # 1. Dynamic tiling preserves both left (red) and right (blue) edges + full-frame thumbnail.
    #    For 640x320 with image_size=64 and max_num=12, area > 0.5*64*64*8 selects (4, 2) = 8 tiles + 1 thumbnail = 9.
    proc = InternVLNativeImageProcessor(image_size=64, max_num=12, use_thumbnail=True)
    out_tiled = proc(images=[edge_img], return_tensors="np")
    pv_tiled = out_tiled["pixel_values"]
    assert out_tiled["num_patches_list"] == [9]
    assert pv_tiled.shape == (9, 3, 64, 64)
    # Tile 0 (top-left of 4x2 grid): left edge has high R, low B.
    assert pv_tiled[0, 0, :, :4].mean() > pv_tiled[0, 2, :, :4].mean() + 2.0
    # Tile 3 (top-right of 4x2 grid): right edge has high B, low R.
    assert pv_tiled[3, 2, :, -4:].mean() > pv_tiled[3, 0, :, -4:].mean() + 2.0
    # Tile -1 (full-frame thumbnail): preserves BOTH left red edge and right blue edge.
    assert pv_tiled[-1, 0, :, :4].mean() > pv_tiled[-1, 2, :, :4].mean() + 2.0
    assert pv_tiled[-1, 2, :, -4:].mean() > pv_tiled[-1, 0, :, -4:].mean() + 2.0

    # 2. Single-tile square resize (max_num=1) also preserves both edges with no center crop.
    tiles_sq = internvl_dynamic_preprocess(edge_img, min_num=1, max_num=1, image_size=64, use_thumbnail=True)
    assert len(tiles_sq) == 1
    sq_arr = np.asarray(tiles_sq[0])
    assert sq_arr[:, :4, 0].mean() > 200 and sq_arr[:, :4, 2].mean() < 20
    assert sq_arr[:, -4:, 2].mean() > 200 and sq_arr[:, -4:, 0].mean() < 20

    # 3. max_pixels enforces BOTH source-image downscaling and tiled patch budget,
    #    producing measurably different visual tensors across pixel budgets.
    y_grid, x_grid = np.mgrid[0:400, 0:800]
    pattern = np.stack(
        [
            ((x_grid // 4 + y_grid // 4) % 2 * 255).astype(np.uint8),
            ((x_grid * 255) // 799).astype(np.uint8),
            ((y_grid * 255) // 399).astype(np.uint8),
        ],
        axis=-1,
    )
    pattern_img = Image.fromarray(pattern, mode="RGB")

    captured_runs: dict[int, tuple[np.ndarray, list[int]]] = {}

    # Budget smaller than a single 64x64 tile (4096 px) must fail closed rather than silently emitting 4096 px.
    class RejectInternVL:
        def chat(self, *_a, **_kw):
            raise AssertionError("chat must not run when max_pixels < single tile area")

    too_small_backend = TransformersBackend(
        model_id="OpenGVLab/InternVL3-8B@sha256:1",
        max_pixels=1024,
        model=RejectInternVL(),
        processor=InternVLNativeImageProcessor(image_size=64, max_num=12, use_thumbnail=True),
        tokenizer=object(),
        image_loader=lambda _p, img=pattern_img: img.copy(),
    )
    with pytest.raises(InputError, match="smaller than a single"):
        too_small_backend.infer_one(_make_request(tmp_path / "r5_budget_1024"))

    for budget in (4096, 12288):
        class CaptureInternVL:
            def chat(self, tokenizer, pixel_values, question, generation_config, num_patches_list=None):
                captured_runs[budget] = (np.asarray(pixel_values), list(num_patches_list or []))
                return LEGAL_JSON

        backend = TransformersBackend(
            model_id="OpenGVLab/InternVL3-8B@sha256:1",
            max_pixels=budget,
            model=CaptureInternVL(),
            processor=InternVLNativeImageProcessor(image_size=64, max_num=12, use_thumbnail=True),
            tokenizer=object(),
            image_loader=lambda _p, img=pattern_img: img.copy(),
        )
        res = backend.infer_one(_make_request(tmp_path / f"r5_budget_{budget}"))
        assert res.status == "success"

    pv_4096, patches_4096 = captured_runs[4096]
    pv_12288, patches_12288 = captured_runs[12288]

    assert patches_4096 == [1] * 8 and pv_4096.shape == (8, 3, 64, 64)
    assert patches_12288 == [3] * 8 and pv_12288.shape == (24, 3, 64, 64)

    # 4. Injected custom processor also receives images pre-downscaled to <= max_pixels.
    seen_input_sizes: list[tuple[int, int]] = []

    class SpyInternVLProcessor:
        def __call__(self, **kwargs):
            for im in kwargs["images"]:
                seen_input_sizes.append(im.size)
            return {"pixel_values": "PV", "num_patches_list": [1] * len(kwargs["images"])}

    class SpyInternVLModel:
        def chat(self, tokenizer, pixel_values, question, generation_config, num_patches_list=None):
            return LEGAL_JSON

    spy_backend = TransformersBackend(
        model_id="OpenGVLab/InternVL3.5-8B@sha256:2",
        max_pixels=10000,
        model=SpyInternVLModel(),
        processor=SpyInternVLProcessor(),
        tokenizer=object(),
        image_loader=lambda _p: Image.new("RGB", (400, 200)),
    )
    assert spy_backend.infer_one(_make_request(tmp_path / "r5_spy")).status == "success"
    assert len(seen_input_sizes) == 8
    assert all(w * h <= 10000 for w, h in seen_input_sizes)

    # 5. Hardening checks: unpaired UTF-8 surrogate, illegal API key chars, configuration_files redirect.
    from script.five_label_eval.backends import InferenceResult, normalize_result

    bad_utf8 = normalize_result(InferenceResult(status="success", raw_output="bad\ud800surrogate", latency_seconds=0.1))
    assert bad_utf8.status == "request_failed"
    assert bad_utf8.raw_output is None

    monkeypatch.setenv("BAD_KEY_NL", "secret\nheader")
    with pytest.raises(InputError, match="illegal whitespace or control"):
        HttpBackend(endpoint="http://127.0.0.1:8000", model_id="Qwen3-VL-8B-Instruct@1", api_key_env="BAD_KEY_NL")

    cfg_dir = tmp_path / "cfg_redir"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_bytes(b'{"configuration_files": ["other.json"]}')
    with pytest.raises(InputError, match="configuration_files"):
        verify_trusted_snapshot_sha256(
            cfg_dir, {"config.json": hashlib.sha256((cfg_dir / "config.json").read_bytes()).hexdigest()}
        )


def test_r6_regression_video_preprocessor_hf_internvl_mkstemp_and_surrogate_meta(tmp_path, monkeypatch):
    """Regression tests for R6 Codex blocking findings (video_preprocessor_config, HF InternVL, mkstemp, extra_meta surrogates)."""
    import os as _os
    import types
    from script.five_label_eval.backends.transformers_backend import _default_model_loader

    # 1. video_preprocessor_config.json must be pinned AND nested auto_map in processor_config.json rejected.
    qwen_dir = tmp_path / "qwen_video_snap"
    qwen_dir.mkdir()
    (qwen_dir / "config.json").write_bytes(b'{"model_type": "qwen3_vl"}')
    (qwen_dir / "video_preprocessor_config.json").write_bytes(
        b'{"auto_map": {"AutoVideoProcessor": "evil/repo--vid.Proc"}}'
    )
    cfg_sha = hashlib.sha256((qwen_dir / "config.json").read_bytes()).hexdigest()
    vid_sha = hashlib.sha256((qwen_dir / "video_preprocessor_config.json").read_bytes()).hexdigest()
    with pytest.raises(InputError, match="video_preprocessor_config.json"):
        verify_trusted_snapshot_sha256(qwen_dir, {"config.json": cfg_sha})
    with pytest.raises(InputError, match="external auto_map"):
        verify_trusted_snapshot_sha256(
            qwen_dir, {"config.json": cfg_sha, "video_preprocessor_config.json": vid_sha}
        )

    nested_dir = tmp_path / "qwen_nested_proc"
    nested_dir.mkdir()
    (nested_dir / "config.json").write_bytes(b'{"model_type": "qwen3_vl"}')
    (nested_dir / "processor_config.json").write_bytes(
        b'{"video_processor": {"auto_map": {"AutoVideoProcessor": "evil/repo--vid.Proc"}}}'
    )
    with pytest.raises(InputError, match="external auto_map"):
        verify_trusted_snapshot_sha256(
            nested_dir,
            {
                "config.json": hashlib.sha256((nested_dir / "config.json").read_bytes()).hexdigest(),
                "processor_config.json": hashlib.sha256((nested_dir / "processor_config.json").read_bytes()).hexdigest(),
            },
        )

    # 2. HF-format InternVL checkpoint (model_type == "internvl") loads AutoModelForImageTextToText with generate(),
    #    never getting stuck on base InternVLModel without generate/chat.
    hf_calls: list[str] = []

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def is_bf16_supported():
            return False

    class BaseInternVLNoGenerate:
        def eval(self):
            return self

    class HFInternVLForCondGen:
        def eval(self):
            return self

        def generate(self, **kwargs):
            return [[1, 2, 99]]

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            hf_calls.append("AutoModel")
            return BaseInternVLNoGenerate()

    class FakeAutoModelForImageTextToText:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            hf_calls.append("AutoModelForImageTextToText")
            return HFInternVLForCondGen()

    class FakeHFProcessor:
        tokenizer = "HF_TOK"

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            return "P"

        def __call__(self, **kwargs):
            return {"input_ids": [[1, 2]]}

        def batch_decode(self, sequences, skip_special_tokens=True):
            return [LEGAL_JSON]

    class FakeAutoProcessor:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            hf_calls.append("AutoProcessor")
            return FakeHFProcessor()

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            return "TOK"

    fake_torch = types.SimpleNamespace(bfloat16="bf16", cuda=FakeCuda())
    fake_transformers = types.SimpleNamespace(
        AutoModel=FakeAutoModel,
        AutoModelForCausalLM=FakeAutoModel,
        AutoModelForImageTextToText=FakeAutoModelForImageTextToText,
        AutoProcessor=FakeAutoProcessor,
        AutoTokenizer=FakeAutoTokenizer,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    hf_dir = tmp_path / "internvl35_hf"
    hf_dir.mkdir()
    (hf_dir / "config.json").write_text(
        json.dumps({"model_type": "internvl", "architectures": ["InternVLForConditionalGeneration"]}),
        encoding="utf-8",
    )
    model, proc, tok = _default_model_loader(hf_dir, "internvl3.5", 262144)
    assert hasattr(model, "generate")
    assert hf_calls == ["AutoModelForImageTextToText", "AutoProcessor"]
    assert tok == "HF_TOK"

    # 3. Checkpoint temp file uses unpredictable mkstemp (never clobbers a pre-existing predictable symlink/file),
    #    AND unpaired surrogate in HTTP finish_reason does not abort the batch before candidate 2 runs.
    rec1, m1, frames_dir = _build_record_and_manifest(tmp_path / "r6_batch", cid="c00")
    _, entries2 = _write_eight_frames(frames_dir, cid="c01")
    rec2 = {**rec1, "candidate_id": "c01", "frames": entries2}
    rec2["input_id"] = compute_record_input_id(rec2)
    manifest = {"manifest_version": "test/1", "samples": [m1["samples"][0], {**m1["samples"][0], "candidate_id": "c01"}]}

    preds_path = tmp_path / "r6_preds.jsonl"
    meta_path = tmp_path / "r6_meta.json"
    victim = tmp_path / "victim.txt"
    victim.write_text("DO NOT CLOBBER", encoding="utf-8")
    predictable_tmp = meta_path.with_name(f".{meta_path.name}.tmp.{_os.getpid()}")
    predictable_tmp.symlink_to(victim)

    call_n = 0

    def surrogate_finish_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            # Valid content + JSON-escaped lone surrogate in finish_reason.
            raw_body = (
                '{"choices":[{"message":{"content":'
                + json.dumps(LEGAL_JSON)
                + '},"finish_reason":"stop\\ud800bad"}]}'
            ).encode("utf-8")
            return httpx.Response(200, content=raw_body, headers={"Content-Type": "application/json"})
        return httpx.Response(200, json={"choices": [{"message": {"content": LEGAL_JSON}, "finish_reason": "stop"}]})

    http_backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@1",
        transport=httpx.MockTransport(surrogate_finish_handler),
    )
    try:
        preds, run_meta = infer.run_inference(
            [rec1, rec2],
            manifest,
            backend=http_backend,
            run_id="r6-surrogate",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
            output_path=preds_path,
            meta_output_path=meta_path,
        )
    finally:
        http_backend.close()

    assert len(preds) == 2
    assert [p["status"] for p in preds] == ["success", "success"]
    assert run_meta["run_status"] == "completed"
    assert victim.read_text(encoding="utf-8") == "DO NOT CLOBBER"
    saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved_meta["total_requests"] == 2
    assert saved_meta["requests"][0]["extra_meta"]["finish_reason"] == "stop?bad"


def test_r7_regression_swapped_frames_input_id_slow_dns_recursion_and_url_redaction(tmp_path, monkeypatch):
    """Regression tests for R7 Codex blocking findings: frame-order input_id binding, slow DNS timeout, deep JSON RecursionError, and endpoint redaction."""
    import socket

    # 1. Swapping two frames' (image, sha256) pairs while keeping old input_id must fail closed before inference.
    rec_swap, manifest, frames_dir = _build_record_and_manifest(tmp_path / "r7_swap", cid="c00")
    rec_swap["frames"][0]["image"], rec_swap["frames"][1]["image"] = (
        rec_swap["frames"][1]["image"],
        rec_swap["frames"][0]["image"],
    )
    rec_swap["frames"][0]["sha256"], rec_swap["frames"][1]["sha256"] = (
        rec_swap["frames"][1]["sha256"],
        rec_swap["frames"][0]["sha256"],
    )

    class FailIfCalledBackend:
        backend_name = "http"

        def run_identity(self):
            return {"backend": "http"}

        def infer_one(self, request):
            raise AssertionError("backend must not run when swapped frames violate input_id")

        def close(self):
            return None

    with pytest.raises(InputError, match="input_id"):
        infer.run_inference(
            [rec_swap],
            manifest,
            backend=FailIfCalledBackend(),
            run_id="r7-swap",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
        )

    # 2. Blocking getaddrinfo() DNS lookup returns timeout within wall-clock budget.
    def slow_getaddrinfo(*_args, **_kwargs):
        time.sleep(2.0)
        raise socket.gaierror("slow dns")

    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    dns_backend = HttpBackend(
        endpoint="http://slow-dns.example.invalid:8000/v1",
        model_id="Qwen3-VL-8B-Instruct@1",
        timeout_seconds=0.2,
    )
    try:
        started = time.monotonic()
        dns_res = dns_backend.infer_one(_make_request(tmp_path / "r7_dns", timeout=0.2))
        elapsed = time.monotonic() - started
    finally:
        dns_backend.close()
    assert dns_res.status == "timeout"
    assert dns_res.raw_output is None
    assert elapsed < 0.7, f"slow DNS timeout exceeded wall-clock budget: {elapsed:.3f}s"

    # 3. Deeply nested JSON triggering RecursionError maps to request_failed without aborting candidate 2.
    rec1, m1, frames_dir = _build_record_and_manifest(tmp_path / "r7_rec", cid="c00")
    _, entries2 = _write_eight_frames(frames_dir, cid="c01")
    rec2 = {**rec1, "candidate_id": "c01", "frames": entries2}
    rec2["input_id"] = compute_record_input_id(rec2)
    manifest2 = {"manifest_version": "test/1", "samples": [m1["samples"][0], {**m1["samples"][0], "candidate_id": "c01"}]}
    deep_payload = ("[" * 2000 + "]" * 2000).encode("ascii")
    idx = 0

    def deep_json_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal idx
        idx += 1
        if idx == 1:
            return httpx.Response(200, content=deep_payload, headers={"Content-Type": "application/json"})
        return httpx.Response(200, json={"choices": [{"message": {"content": LEGAL_JSON}}]})

    deep_backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@1",
        transport=httpx.MockTransport(deep_json_handler),
    )
    try:
        preds, _ = infer.run_inference(
            [rec1, rec2],
            manifest2,
            backend=deep_backend,
            run_id="r7-rec",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
        )
    finally:
        deep_backend.close()
    assert [p["status"] for p in preds] == ["request_failed", "success"]
    assert preds[0]["raw_output"] is None
    assert preds[1]["raw_output"] == LEGAL_JSON

    # 4. Uppercase HTTPS:// scheme is accepted; invalid scheme with credentials/query never leaks secrets.
    upper_backend = HttpBackend(
        endpoint="HTTPS://127.0.0.1:8000/v1",
        model_id="Qwen3-VL-8B-Instruct@1",
    )
    assert upper_backend.completions_url == "https://127.0.0.1:8000/v1/chat/completions"
    upper_backend.close()

    with pytest.raises(InputError) as exc_info:
        HttpBackend(
            endpoint="FTP://admin:topsecret@127.0.0.1:8000/v1?api_key=leakme",
            model_id="Qwen3-VL-8B-Instruct@1",
        )
    err_msg = str(exc_info.value)
    assert "topsecret" not in err_msg
    assert "leakme" not in err_msg


def test_r8_regression_malformed_url_redaction_deep_usage_and_pts_input_id(tmp_path):
    """Regression tests for R8 Codex blocking findings: malformed URL ValueError redaction, deep nested usage, and PTS in input_id."""
    # 1. Malformed URL with userinfo + fullwidth slash (triggers urlsplit ValueError) must not leak credentials.
    with pytest.raises(InputError) as exc_info:
        HttpBackend(
            endpoint="http://alice:super_secret_pw@127.0.0.1\uff0f8000/v1",
            model_id="Qwen3-VL-8B-Instruct@1",
        )
    assert "super_secret_pw" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None

    # 2. HTTP 200 with 600-level nested usage dict must not overflow _sanitize_utf8_obj or abort candidate 2.
    rec1, m1, frames_dir = _build_record_and_manifest(tmp_path / "r8_usage", cid="c00")
    _, entries2 = _write_eight_frames(frames_dir, cid="c01")
    rec2 = {**rec1, "candidate_id": "c01", "frames": entries2}
    rec2["input_id"] = compute_record_input_id(rec2)
    manifest2 = {"manifest_version": "test/1", "samples": [m1["samples"][0], {**m1["samples"][0], "candidate_id": "c01"}]}

    deep_usage_json = (
        '{"choices":[{"message":{"content":'
        + json.dumps(LEGAL_JSON)
        + '}}],"usage":{"prompt_tokens":10,"nested":'
        + '{"a":' * 400
        + "1"
        + "}" * 400
        + "}}"
    ).encode("utf-8")
    call_idx = 0

    def deep_usage_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return httpx.Response(200, content=deep_usage_json, headers={"Content-Type": "application/json"})
        return httpx.Response(200, json={"choices": [{"message": {"content": LEGAL_JSON}}]})

    backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@1",
        transport=httpx.MockTransport(deep_usage_handler),
    )
    try:
        preds, meta = infer.run_inference(
            [rec1, rec2],
            manifest2,
            backend=backend,
            run_id="r8-usage",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
        )
    finally:
        backend.close()
    assert [p["status"] for p in preds] == ["success", "success"]
    assert meta["requests"][0]["extra_meta"]["usage"] == {"prompt_tokens": 10}

    # 3. Mutating pts_seconds while keeping old input_id must fail closed before inference.
    rec_pts, m_pts, frames_dir_pts = _build_record_and_manifest(tmp_path / "r8_pts", cid="c00")
    for f in rec_pts["frames"]:
        f["pts_seconds"] = round(f["pts_seconds"] + 1.0, 4)

    class FailBackend:
        backend_name = "transformers"

        def run_identity(self):
            return {"backend": "transformers"}

        def infer_one(self, request):
            raise AssertionError("backend must not run when pts_seconds changed without updating input_id")

        def close(self):
            return None

    with pytest.raises(InputError, match="input_id"):
        infer.run_inference(
            [rec_pts],
            m_pts,
            backend=FailBackend(),
            run_id="r8-pts",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="openbmb/MiniCPM-V-4_5@sha256:1",
            frames_dir=frames_dir_pts,
        )


def test_r9_regression_trusted_snapshot_private_staging_closes_toctou(tmp_path):
    """Trusted snapshot .py/config files are copied into a private 0o700 staging dir before SHA-256 check and model load."""
    snap_a = tmp_path / "snap_a"
    snap_a.mkdir()
    (snap_a / "config.json").write_bytes(b'{"version": "4.5"}')
    (snap_a / "modeling_test.py").write_bytes(b"SAFE = True\n")
    (snap_a / "weights.safetensors").write_bytes(b"WEIGHTS")
    link = tmp_path / "model_link"
    link.symlink_to(snap_a)

    trusted = {
        "config.json": hashlib.sha256((snap_a / "config.json").read_bytes()).hexdigest(),
        "modeling_test.py": hashlib.sha256((snap_a / "modeling_test.py").read_bytes()).hexdigest(),
    }
    loaded_paths: list[Path] = []

    class FakeModel:
        def chat(self, **_kwargs):
            return LEGAL_JSON

    def spy_loader(staged_path: Path, _family: str, _max_pixels: int | None):
        loaded_paths.append(staged_path)
        # Staged dir must NOT be the original symlink or source dir; .py/config must be real copied files.
        assert staged_path != link and staged_path != snap_a
        assert (staged_path.stat().st_mode & 0o777) == 0o700
        assert not (staged_path / "modeling_test.py").is_symlink()
        assert not (staged_path / "config.json").is_symlink()
        assert (staged_path / "weights.safetensors").is_symlink()
        # Mutating source dir after staging cannot alter the verified staged .py file.
        (snap_a / "modeling_test.py").write_bytes(b"PWNED = True\n")
        assert (staged_path / "modeling_test.py").read_bytes() == b"SAFE = True\n"
        return FakeModel(), None, object()

    backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        model_path=link,
        trusted_files_sha256=trusted,
        model_loader=spy_loader,
        image_loader=lambda p: p.name,
    )
    try:
        res = backend.infer_one(_make_request(tmp_path / "r9_stage"))
        assert res.status == "success"
        assert len(loaded_paths) == 1
        staged_dir = loaded_paths[0]
        assert staged_dir.is_dir()
    finally:
        backend.close()
    assert not staged_dir.exists()


def test_r10_regression_chat_template_hf_blobs_plaintext_auth_missing_lineage_and_dns_exit(tmp_path, monkeypatch):
    """Regression tests for R10 Codex blocking findings + cloud thread PRRT_kwDOTJFipM67uP-T."""
    import subprocess

    # 1. chat_template.jinja must be pinned in trusted_files_sha256 (missing or modified rejected).
    tmpl_dir = tmp_path / "qwen_tmpl"
    tmpl_dir.mkdir()
    (tmpl_dir / "config.json").write_bytes(b'{"model_type": "qwen3_vl"}')
    (tmpl_dir / "chat_template.jinja").write_bytes(b"{{ messages }}")
    cfg_sha = hashlib.sha256((tmpl_dir / "config.json").read_bytes()).hexdigest()
    tmpl_sha = hashlib.sha256((tmpl_dir / "chat_template.jinja").read_bytes()).hexdigest()
    with pytest.raises(InputError, match="chat_template.jinja"):
        verify_trusted_snapshot_sha256(tmpl_dir, {"config.json": cfg_sha})
    assert verify_trusted_snapshot_sha256(
        tmpl_dir, {"config.json": cfg_sha, "chat_template.jinja": tmpl_sha}
    ) == {"config.json": cfg_sha, "chat_template.jinja": tmpl_sha}

    # 2. Standard HuggingFace cache layout (snapshots/<rev> -> ../../blobs/<hash>) stages cleanly.
    repo_cache = tmp_path / "models--OpenGVLab--InternVL3-8B"
    blobs_dir = repo_cache / "blobs"
    snap_rev = repo_cache / "snapshots" / "abc123"
    blobs_dir.mkdir(parents=True)
    snap_rev.mkdir(parents=True)
    blob_cfg = blobs_dir / "blob_cfg"
    blob_py = blobs_dir / "blob_py"
    blob_cfg.write_bytes(b'{"version": "3"}')
    blob_py.write_bytes(b"OK = True\n")
    (snap_rev / "config.json").symlink_to(blob_cfg)
    (snap_rev / "modeling_internvl.py").symlink_to(blob_py)
    trusted_hf = {
        "config.json": hashlib.sha256(blob_cfg.read_bytes()).hexdigest(),
        "modeling_internvl.py": hashlib.sha256(blob_py.read_bytes()).hexdigest(),
    }

    class FakeModel:
        def chat(self, **_kwargs):
            return LEGAL_JSON

    hf_backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        model_path=snap_rev,
        trusted_files_sha256=trusted_hf,
        model_loader=lambda p, _f, _m: (FakeModel(), None, object()),
        image_loader=lambda p: p.name,
    )
    try:
        assert hf_backend.infer_one(_make_request(tmp_path / "r10_hf_blobs")).status == "success"
    finally:
        hf_backend.close()

    # 3. Reject plaintext http:// with credentials to non-loopback hosts (both api_key_env and URL userinfo).
    monkeypatch.setenv("REMOTE_API_KEY", "secret-val")
    with pytest.raises(InputError, match="plaintext http://"):
        HttpBackend(
            endpoint="http://remote-gpu.example.com:8000/v1",
            model_id="Qwen3-VL-8B-Instruct@1",
            api_key_env="REMOTE_API_KEY",
        )
    with pytest.raises(InputError, match="plaintext http://"):
        HttpBackend(
            endpoint="http://user:pass@remote-gpu.example.com:8000/v1",
            model_id="Qwen3-VL-8B-Instruct@1",
        )
    # https:// to non-loopback host with credentials is allowed.
    ok_https = HttpBackend(
        endpoint="https://remote-gpu.example.com:8000/v1",
        model_id="Qwen3-VL-8B-Instruct@1",
        api_key_env="REMOTE_API_KEY",
    )
    ok_https.close()

    # 4. Missing lineage_media must be rejected when verify_record_lineage=True (default).
    rec_nolin, m_nolin, frames_dir_nolin = _build_record_and_manifest(tmp_path / "r10_nolin", cid="c00")
    rec_nolin.pop("lineage_media")
    rec_nolin["input_id"] = compute_record_input_id(rec_nolin)

    class NeverBackend:
        backend_name = "http"

        def run_identity(self):
            return {"backend": "http"}

        def infer_one(self, request):
            raise AssertionError("should fail closed on missing lineage_media")

        def close(self):
            return None

    with pytest.raises(InputError, match="lineage check failed"):
        infer.run_inference(
            [rec_nolin],
            m_nolin,
            backend=NeverBackend(),
            run_id="r10-nolin",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir_nolin,
        )

    # 5. Subprocess CLI exits within timeout budget even when socket.getaddrinfo blocks for 5s.
    script = (
        "import socket, time\n"
        "from pathlib import Path\n"
        "from script.five_label_eval.backends.http_backend import HttpBackend\n"
        "from script.five_label_eval.backends import InferenceRequest\n"
        "socket.getaddrinfo = lambda *a, **k: (time.sleep(5.0), (_ for _ in ()).throw(socket.gaierror('slow')))[1]\n"
        "b = HttpBackend(endpoint='http://slow-exit.example.invalid:8000/v1', model_id='Qwen3-VL-8B-Instruct@1', timeout_seconds=0.15)\n"
        "req = InferenceRequest(candidate_id='c00', record={}, frame_paths=(), frame_pts_seconds=(), prompt_text='p', timeout_seconds=0.15, frame_bytes=())\n"
        "res = b.infer_one(req)\n"
        "assert res.status == 'timeout', res\n"
    )
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=3.0)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 1.5, f"subprocess hung on DNS thread exit ({elapsed:.2f}s)"


def test_r11_regression_auto_map_local_module_allowlist_and_hf_internvl_max_pixels(tmp_path):
    """Regression tests for R11 Codex blocking findings: strict local auto_map allowlist and HF InternVL max_pixels."""
    from PIL import Image

    # 1. Reject absolute-path or missing-module auto_map references even without '--'.
    abs_dir = tmp_path / "abs_automap"
    abs_dir.mkdir()
    (abs_dir / "config.json").write_bytes(b'{"auto_map": {"AutoConfig": "/tmp/evil.Config"}}')
    with pytest.raises(InputError, match="non-local auto_map"):
        verify_trusted_snapshot_sha256(
            abs_dir, {"config.json": hashlib.sha256((abs_dir / "config.json").read_bytes()).hexdigest()}
        )

    miss_dir = tmp_path / "miss_automap"
    miss_dir.mkdir()
    (miss_dir / "config.json").write_bytes(b'{"auto_map": {"AutoConfig": "missing_mod.Config"}}')
    with pytest.raises(InputError, match="unverified or missing local module"):
        verify_trusted_snapshot_sha256(
            miss_dir, {"config.json": hashlib.sha256((miss_dir / "config.json").read_bytes()).hexdigest()}
        )

    ok_dir = tmp_path / "ok_automap"
    ok_dir.mkdir()
    (ok_dir / "config.json").write_bytes(b'{"auto_map": {"AutoConfig": "configuration_local.LocalConfig"}}')
    (ok_dir / "configuration_local.py").write_bytes(b"class LocalConfig: pass\n")
    assert verify_trusted_snapshot_sha256(
        ok_dir,
        {
            "config.json": hashlib.sha256((ok_dir / "config.json").read_bytes()).hexdigest(),
            "configuration_local.py": hashlib.sha256((ok_dir / "configuration_local.py").read_bytes()).hexdigest(),
        },
    )

    # 2. HF-format InternVL (generate()-based, no .chat()) downscales images to <= max_pixels before processor.
    seen_sizes: list[tuple[int, int]] = []

    class FakeHFInternVLProc:
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            return "P"

        def __call__(self, **kwargs):
            for im in kwargs["images"]:
                seen_sizes.append(im.size)
            return {"input_ids": [[1, 2]]}

        def batch_decode(self, sequences, skip_special_tokens=True):
            return [LEGAL_JSON]

    class FakeHFInternVLModel:
        def generate(self, **kwargs):
            return [[1, 2, 99]]

    hf_backend = TransformersBackend(
        model_id="OpenGVLab/InternVL3.5-8B-HF@sha256:1",
        max_pixels=10000,
        model=FakeHFInternVLModel(),
        processor=FakeHFInternVLProc(),
        image_loader=lambda _p: Image.new("RGB", (400, 200)),
    )
    assert hf_backend.infer_one(_make_request(tmp_path / "r11_hf_px")).status == "success"
    assert hf_backend.run_identity()["max_pixels_scope"] == "pre_processor_source_resize"
    assert len(seen_sizes) == 8
    assert all(w * h <= 10000 for w, h in seen_sizes)


def test_r12_regression_payload_timeout_tokenizer_json_pin_and_sampling_indices(tmp_path):
    """Regression tests for R12 blocking findings: payload-build deadline, full *.json pinning, and sampling-rule index validation."""
    # 1. If build_payload() exhausts timeout budget, infer_one returns timeout without ever hitting network.
    network_called = False

    def should_not_receive(_request: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200, json={"choices": [{"message": {"content": LEGAL_JSON}}]})

    slow_payload_backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@1",
        timeout_seconds=0.05,
        transport=httpx.MockTransport(should_not_receive),
    )
    orig_build = slow_payload_backend.build_payload

    def delayed_build(req):
        time.sleep(0.08)
        return orig_build(req)

    slow_payload_backend.build_payload = delayed_build  # type: ignore[method-assign]
    try:
        res = slow_payload_backend.infer_one(_make_request(tmp_path / "r12_payload", timeout=0.05))
    finally:
        slow_payload_backend.close()
    assert res.status == "timeout"
    assert network_called is False

    # 2. All *.json files (including tokenizer.json) must be pinned and copied (not symlinked) in staging.
    tok_dir = tmp_path / "tok_json_snap"
    tok_dir.mkdir()
    (tok_dir / "config.json").write_bytes(b'{"version": "4.5"}')
    (tok_dir / "tokenizer.json").write_bytes(b'{"version": "1.0"}')
    cfg_sha = hashlib.sha256((tok_dir / "config.json").read_bytes()).hexdigest()
    tok_sha = hashlib.sha256((tok_dir / "tokenizer.json").read_bytes()).hexdigest()
    with pytest.raises(InputError, match="tokenizer.json"):
        verify_trusted_snapshot_sha256(tok_dir, {"config.json": cfg_sha})
    assert verify_trusted_snapshot_sha256(tok_dir, {"config.json": cfg_sha, "tokenizer.json": tok_sha}) == {
        "config.json": cfg_sha,
        "tokenizer.json": tok_sha,
    }

    # 3. Repeated or non-uniform clip_frame_index sequence violating evenly_spaced_inclusive fails closed.
    rec_bad, m_bad, frames_dir_bad = _build_record_and_manifest(tmp_path / "r12_indices", cid="c00")
    for f in rec_bad["frames"]:
        f["clip_frame_index"] = 0
        f["roi_frame_index"] = 973
        f["original_source_frame_index"] = 973
    rec_bad["input_id"] = compute_record_input_id(rec_bad)

    class FailBackend:
        backend_name = "http"

        def run_identity(self):
            return {"backend": "http"}

        def infer_one(self, request):
            raise AssertionError("should reject non-uniform clip_frame_index before backend")

        def close(self):
            return None

    with pytest.raises(InputError, match="evenly_spaced_inclusive"):
        infer.run_inference(
            [rec_bad],
            m_bad,
            backend=FailBackend(),
            run_id="r12-indices",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir_bad,
        )

    # 4. Malformed URL missing '//' (https:user:pass@host/v1) must never echo password in error.
    with pytest.raises(InputError) as no_slash_exc:
        HttpBackend(endpoint="https:alice:my_secret_pw@127.0.0.1/v1", model_id="Qwen3-VL-8B-Instruct@1")
    assert "my_secret_pw" not in str(no_slash_exc.value)
    assert "alice" not in str(no_slash_exc.value)

    # 5. Short 7-frame L2 clip with padded/repeated 8 frames must fail closed before backend.
    rec_short, m_short, frames_dir_short = _build_record_and_manifest(tmp_path / "r12_short7", cid="c00")
    rec_short["media"]["total_frames"] = 7
    rec_short["lineage_media"]["l2"]["total_frames"] = 7
    for idx_i, f in enumerate(rec_short["frames"]):
        ci = min(idx_i, 6)
        f["clip_frame_index"] = ci
        f["roi_frame_index"] = 973 + ci
        f["original_source_frame_index"] = 973 + ci
    rec_short["input_id"] = compute_record_input_id(rec_short)
    with pytest.raises(InputError, match="total_frames"):
        infer.run_inference(
            [rec_short],
            m_short,
            backend=FailBackend(),
            run_id="r12-short7",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir_short,
        )


def test_r13_regression_finite_temperature_timeout_and_decode_deadline(tmp_path):
    """Regression tests for non-finite temperature/timeout rejection and local frame-decoding deadline."""
    for bad_val in (float("nan"), float("inf"), float("-inf"), -0.1):
        with pytest.raises(InputError, match="temperature"):
            HttpBackend(endpoint="http://127.0.0.1:8000", model_id="Qwen3-VL-8B-Instruct@1", temperature=bad_val)
        with pytest.raises(InputError, match="temperature"):
            TransformersBackend(model_id="Qwen/Qwen3-VL-8B-Instruct@1", temperature=bad_val)
    for bad_timeout in (float("nan"), float("inf"), 0.0, -1.0):
        with pytest.raises(InputError, match="timeout_seconds"):
            HttpBackend(endpoint="http://127.0.0.1:8000", model_id="Qwen3-VL-8B-Instruct@1", timeout_seconds=bad_timeout)
        with pytest.raises(InputError, match="timeout_seconds"):
            TransformersBackend(model_id="Qwen/Qwen3-VL-8B-Instruct@1", timeout_seconds=bad_timeout)

    # Slow frame decoding must count toward local TransformersBackend timeout budget.
    class FastModel:
        def chat(self, **_kwargs):
            return LEGAL_JSON

    def slow_loader(_path):
        time.sleep(0.04)
        return "IMG"

    backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        timeout_seconds=0.05,
        model=FastModel(),
        tokenizer=object(),
        image_loader=slow_loader,
    )
    res = backend.infer_one(_make_request(tmp_path / "r13_slow_decode", timeout=0.05))
    assert res.status == "timeout"
    assert res.raw_output is None


def test_r14_regression_qwen3_vl_min_transformers_version_and_dangling_config_symlink(tmp_path, monkeypatch):
    """Regression tests for Qwen3-VL transformers>=4.57.0 version gate and dangling config symlink rejection."""
    import types
    from script.five_label_eval.backends.transformers_backend import _default_model_loader

    # 1. Qwen3-VL local loader rejects transformers==4.56.1 (< 4.57.0) fail-closed.
    class FakeCuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def is_bf16_supported():
            return False

    fake_torch = types.SimpleNamespace(bfloat16="bf16", cuda=FakeCuda())
    fake_old_tf = types.SimpleNamespace(
        __version__="4.56.1",
        AutoModel=object,
        AutoModelForCausalLM=object,
        AutoProcessor=object,
        AutoTokenizer=object,
        AutoModelForImageTextToText=object,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_old_tf)
    with pytest.raises(InputError, match="4.57.0"):
        _default_model_loader(tmp_path, "qwen3-vl", 262144)

    # 2. Dangling config symlink in snapshot directory is rejected fail-closed during staging & verification.
    snap = tmp_path / "dangling_snap"
    snap.mkdir()
    (snap / "config.json").write_bytes(b"{}")
    (snap / "processor_config.json").symlink_to(tmp_path / "does_not_exist.json")
    cfg_sha = hashlib.sha256(b"{}").hexdigest()
    with pytest.raises(InputError, match="symlink"):
        verify_trusted_snapshot_sha256(snap, {"config.json": cfg_sha})
    backend = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        model_path=snap,
        trusted_files_sha256={"config.json": cfg_sha},
        model_loader=lambda *_a: (object(), None, None),
    )
    with pytest.raises(InputError, match="dangling symlink"):
        backend.infer_one(_make_request(tmp_path / "r14_dangling"))


def test_r15_regression_jsonl_line_separators_and_duplicate_manifest_candidate(tmp_path):
    """Regression tests for U+2028/U+2029 JSONL round-trip with score.read_jsonl and duplicate manifest candidate_id."""
    from script.five_label_eval.score import read_jsonl

    # 1. Model output containing literal U+2028 / U+2029 survives predictions.jsonl -> score.read_jsonl() intact.
    rec, manifest, frames_dir = _build_record_and_manifest(tmp_path / "r15_sep", cid="c00")
    raw_with_sep = LEGAL_JSON + "\u2028\u2029"
    preds_path = tmp_path / "r15_preds.jsonl"

    http_backend = HttpBackend(
        endpoint="http://127.0.0.1:8000",
        model_id="Qwen3-VL-8B-Instruct@1",
        transport=httpx.MockTransport(
            lambda _req: httpx.Response(200, json={"choices": [{"message": {"content": raw_with_sep}}]})
        ),
    )
    try:
        infer.run_inference(
            [rec],
            manifest,
            backend=http_backend,
            run_id="r15-sep",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
            output_path=preds_path,
        )
    finally:
        http_backend.close()

    parsed_rows = read_jsonl(preds_path)
    assert len(parsed_rows) == 1
    assert parsed_rows[0]["raw_output"] == raw_with_sep

    # 2. Duplicate candidate_id in manifest["samples"] fails closed before creating output or calling backend.
    dup_manifest = {
        "manifest_version": "test/1",
        "samples": [
            {**manifest["samples"][0], "clip_sha256": "0" * 64},
            manifest["samples"][0],
        ],
    }
    out_should_not_exist = tmp_path / "r15_dup_preds.jsonl"

    class FailBackend:
        backend_name = "http"

        def run_identity(self):
            return {"backend": "http"}

        def infer_one(self, request):
            raise AssertionError("backend must not run on duplicate manifest candidate_id")

        def close(self):
            return None

    with pytest.raises(InputError, match="duplicate candidate_id in manifest"):
        infer.run_inference(
            [rec],
            dup_manifest,
            backend=FailBackend(),
            run_id="r15-dup",
            prompt_id="prompt@sha256:" + "a" * 64,
            prompt_text="p",
            model_id="Qwen3-VL-8B-Instruct@1",
            frames_dir=frames_dir,
            output_path=out_should_not_exist,
        )
    assert not out_should_not_exist.exists()

    # 3. Uppercase config filename (PROCESSOR_CONFIG.JSON) must also be pinned and auto_map-scanned.
    upper_dir = tmp_path / "r15_upper_cfg"
    upper_dir.mkdir()
    (upper_dir / "config.json").write_bytes(b"{}")
    (upper_dir / "PROCESSOR_CONFIG.JSON").write_bytes(b'{"auto_map": {"AutoProcessor": "evil/repo--p.P"}}')
    cfg_sha = hashlib.sha256(b"{}").hexdigest()
    up_sha = hashlib.sha256((upper_dir / "PROCESSOR_CONFIG.JSON").read_bytes()).hexdigest()
    with pytest.raises(InputError, match="PROCESSOR_CONFIG.JSON"):
        verify_trusted_snapshot_sha256(upper_dir, {"config.json": cfg_sha})
    with pytest.raises(InputError, match="external auto_map"):
        verify_trusted_snapshot_sha256(upper_dir, {"config.json": cfg_sha, "PROCESSOR_CONFIG.JSON": up_sha})
