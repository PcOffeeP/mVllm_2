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
    TransformersBackend,
    compute_minicpm_temporal_ids,
    detect_model_family,
    verify_trusted_snapshot_sha256,
)
from script.five_label_eval.frames import RECORD_SCHEMA
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
        "input_id": "input@sha256:" + "1" * 64,
        "frame_count_convention": "decoded",
        "sampling": {
            "sampling_rule": "evenly_spaced_inclusive",
            "target_frame_count": 8,
            "short_clip_policy": "fail_closed",
            "resize": None,
        },
        "media": {"width": 320, "height": 240, "fps": 30.0, "total_frames": 240, "sha256": clip_sha},
        "frames": frame_entries,
    }
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
