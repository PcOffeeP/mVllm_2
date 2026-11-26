"""Offline unit and end-to-end tests for Run B (`--no-image`) pure-text prior baseline mode."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from contextlib import redirect_stderr
from pathlib import Path
import sys
import threading

import httpx
import pytest

from script.five_label_eval import infer, manifest_convert, score
from script.five_label_eval.backends import (
    InferenceRequest,
    MODALITY_TEXT_ONLY,
    MODALITY_VISION_TEXT,
)
from script.five_label_eval.backends.fake_backend import FakeBackend, LEGAL
from script.five_label_eval.backends.http_backend import HttpBackend
from script.five_label_eval.backends.transformers_backend import TransformersBackend
from script.five_label_eval.exclusions import REPO_ROOT
from script.five_label_eval.frames import RECORD_SCHEMA, compute_record_input_id
from script.five_label_eval.score import InputError

LEGAL_JSON = json.dumps(LEGAL, ensure_ascii=False)

PNG_HEADER = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_record(
    frames_dir: Path | None,
    cid: str = "c00",
    *,
    clip_sha: str | None = None,
    manifest_sha: str = "b" * 64,
    write_pngs: bool = True,
) -> dict:
    clip_sha = clip_sha or hashlib.sha256(f"clip-{cid}".encode("utf-8")).hexdigest()
    indices = [0, 34, 68, 102, 137, 171, 205, 239]
    frame_entries: list[dict] = []
    if write_pngs and frames_dir is not None:
        clip_dir = frames_dir / cid
        clip_dir.mkdir(parents=True, exist_ok=True)
    else:
        clip_dir = None

    for order, clip_idx in enumerate(indices):
        name = f"frame_{order + 1:03d}.png"
        payload = PNG_HEADER + f"{cid}-frame-{order}-{clip_idx}".encode("ascii")
        if clip_dir is not None:
            (clip_dir / name).write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
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
    return record


def _build_batch(
    tmp_path: Path,
    count: int = 1,
    *,
    write_pngs: bool = True,
    with_reviews: bool = False,
) -> tuple[list[dict], dict, list[dict], Path]:
    frames_dir = tmp_path / "frames"
    manifest_sha = "b" * 64
    records: list[dict] = []
    samples: list[dict] = []
    reviews: list[dict] = []
    for idx in range(count):
        cid = f"video_0001_clip_{idx:02d}"
        source_id = f"video_{idx + 10:04d}"
        rec = _make_record(frames_dir, cid=cid, manifest_sha=manifest_sha, write_pngs=write_pngs)
        records.append(rec)
        review_id = f"rev-{idx:02d}" if with_reviews else None
        samples.append({
            "manifest_sha256": manifest_sha,
            "candidate_id": cid,
            "clip_sha256": rec["clip_sha256"],
            "source_id": source_id,
            "source_type": "real",
            "review_id": review_id,
        })
        if with_reviews:
            reviews.append({
                "manifest_sha256": manifest_sha,
                "candidate_id": cid,
                "clip_sha256": rec["clip_sha256"],
                "source_id": source_id,
                "source_type": "real",
                "review_id": review_id,
                "review_status": "confirmed",
                "labels": LEGAL,
            })
    manifest = {"manifest_version": "runb-test/1", "samples": samples}
    return records, manifest, reviews, frames_dir


def _start_loopback_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


# --------------------------------------------------------------------------------------
# 1. HttpBackend.build_payload text-only (`no_image=True`) vs Run A (`no_image=False`)
# --------------------------------------------------------------------------------------
def test_http_backend_build_payload_no_image_emits_zero_image_urls_and_preserves_decode(tmp_path):
    records, _, _, frames_dir = _build_batch(tmp_path, count=1, write_pngs=True)
    rec = records[0]
    frame_paths = tuple(frames_dir / rec["candidate_id"] / f["image"] for f in rec["frames"])
    frame_pts = tuple(f["pts_seconds"] for f in rec["frames"])
    prompt_text = "  请仅根据规则严格输出 JSON\n"

    req_runa = InferenceRequest(
        candidate_id=rec["candidate_id"],
        record=rec,
        frame_paths=frame_paths,
        frame_pts_seconds=frame_pts,
        prompt_text=prompt_text,
        decode_config={"temperature": 0.2, "max_tokens": 256, "top_p": 0.9, "seed": 42},
        no_image=False,
    )
    req_runb = InferenceRequest(
        candidate_id=rec["candidate_id"],
        record=rec,
        # Even if frame_paths points to missing files, no_image=True must never read disk or encode URLs.
        frame_paths=(tmp_path / "does_not_exist.png",),
        frame_pts_seconds=(),
        prompt_text=prompt_text,
        decode_config={"temperature": 0.2, "max_tokens": 256, "top_p": 0.9, "seed": 42},
        no_image=True,
    )

    backend_a = HttpBackend(
        endpoint="http://127.0.0.1:8000/v1",
        model_id="Qwen3-VL-8B-Instruct@sha256:1",
        temperature=0.2,
        max_tokens=256,
        top_p=0.9,
        seed=42,
        max_pixels=65536,
        sampling_policy=rec["sampling"],
        no_image=False,
    )
    backend_b = HttpBackend(
        endpoint="http://127.0.0.1:8000/v1",
        model_id="Qwen3-VL-8B-Instruct@sha256:1",
        temperature=0.2,
        max_tokens=256,
        top_p=0.9,
        seed=42,
        max_pixels=65536,
        sampling_policy=rec["sampling"],
        no_image=True,
    )
    try:
        payload_a = backend_a.build_payload(req_runa)
        payload_b_from_backend = backend_b.build_payload(req_runa)
        payload_b_from_request = backend_a.build_payload(req_runb)
        id_a = backend_a.run_identity()
        id_b = backend_b.run_identity()
    finally:
        backend_a.close()
        backend_b.close()

    # Run A regression untouched: 8 image_url blocks + 1 text block + mm_processor_kwargs
    content_a = payload_a["messages"][0]["content"]
    assert sum(1 for item in content_a if item["type"] == "image_url") == 8
    assert content_a[-1] == {"type": "text", "text": prompt_text}
    assert payload_a["mm_processor_kwargs"] == {"max_pixels": 65536}

    # Run B (both via backend flag and via request flag): ZERO image_url entries, identical prompt & decoding
    for payload_b in (payload_b_from_backend, payload_b_from_request):
        content_b = payload_b["messages"][0]["content"]
        assert [item for item in content_b if item["type"] == "image_url"] == []
        assert content_b == [{"type": "text", "text": prompt_text}]
        assert "data:image/" not in json.dumps(payload_b, ensure_ascii=False)
        assert "mm_processor_kwargs" not in payload_b
        assert payload_b["model"] == payload_a["model"]
        assert payload_b["temperature"] == payload_a["temperature"] == 0.2
        assert payload_b["max_tokens"] == payload_a["max_tokens"] == 256
        assert payload_b["top_p"] == payload_a["top_p"] == 0.9
        assert payload_b["seed"] == payload_a["seed"] == 42

    assert id_a["no_image"] is False
    assert id_a["modality"] == MODALITY_VISION_TEXT
    assert id_a["max_pixels"] == 65536
    assert id_b["no_image"] is True
    assert id_b["modality"] == MODALITY_TEXT_ONLY
    assert id_b["max_pixels"] is None
    assert id_b["decode_config"] == {"temperature": 0.2, "max_tokens": 256, "top_p": 0.9, "seed": 42}


@pytest.mark.parametrize("bad_top_p", [0.0, -0.5, 1.01, float("nan"), float("inf"), True])
def test_backends_reject_invalid_top_p(bad_top_p):
    with pytest.raises(InputError, match="top_p"):
        HttpBackend(endpoint="http://127.0.0.1:8000", model_id="Qwen3-VL-8B-Instruct@1", top_p=bad_top_p)
    with pytest.raises(InputError, match="top_p"):
        TransformersBackend(model_id="Qwen/Qwen3-VL-8B-Instruct@1", top_p=bad_top_p)


# --------------------------------------------------------------------------------------
# 2. TransformersBackend text-only paths (MiniCPM chat/generate, InternVL chat, Generic HF)
# --------------------------------------------------------------------------------------
def test_transformers_backend_minicpm_no_image_chat_and_generate(tmp_path):
    records, _, _, _ = _build_batch(tmp_path, count=1, write_pngs=False)
    rec = records[0]
    prompt_text = "  MiniCPM Run B text-only prompt\n"
    req = InferenceRequest(
        candidate_id=rec["candidate_id"],
        record=rec,
        frame_paths=(tmp_path / "never_opened.png",),
        frame_pts_seconds=(),
        prompt_text=prompt_text,
        decode_config={"temperature": 0.3, "max_tokens": 200, "top_p": 0.85, "seed": 7},
        no_image=True,
    )

    def fail_image_loader(_path):
        raise AssertionError("image_loader must never be called in no_image mode")

    # Path A: MiniCPM model.chat()
    chat_called: dict = {}

    class FakeMiniCPMChatModel:
        def chat(self, **kwargs):
            chat_called.update(kwargs)
            return LEGAL_JSON

    tok = object()
    backend_chat = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        temperature=0.3,
        max_tokens=200,
        top_p=0.85,
        seed=7,
        max_pixels=65536,
        no_image=True,
        model=FakeMiniCPMChatModel(),
        tokenizer=tok,
        image_loader=fail_image_loader,
    )
    res_chat = backend_chat.infer_one(req)
    id_chat = backend_chat.run_identity()

    assert res_chat.status == "success"
    assert res_chat.raw_output == LEGAL_JSON
    assert chat_called["msgs"] == [{"role": "user", "content": [prompt_text]}]
    assert chat_called["tokenizer"] is tok
    assert "temporal_ids" not in chat_called
    assert "max_slice_nums" not in chat_called
    assert chat_called["do_sample"] is True
    assert chat_called["temperature"] == 0.3
    assert chat_called["top_p"] == 0.85
    assert chat_called["max_new_tokens"] == 200
    assert res_chat.extra_meta["no_image"] is True
    assert res_chat.extra_meta["modality"] == MODALITY_TEXT_ONLY
    assert res_chat.extra_meta["temporal_ids"] is None

    assert id_chat["no_image"] is True
    assert id_chat["modality"] == MODALITY_TEXT_ONLY
    assert id_chat["temporal_ids_policy"] == "not_applicable"
    assert id_chat["temporal_ids_grid_seconds"] is None
    assert id_chat["max_slice_nums"] is None
    assert id_chat["max_pixels"] is None
    assert id_chat["max_pixels_scope"] == "not_applicable"
    assert id_chat["decode_config"] == {"temperature": 0.3, "max_tokens": 200, "top_p": 0.85, "seed": 7}

    # Path B: MiniCPM processor + model.generate()
    gen_captured: dict = {}

    class FakeMiniCPMProcessor:
        def __call__(self, **kwargs):
            gen_captured["proc_kwargs"] = kwargs
            return {"input_ids": [[1, 2, 3]]}

        def batch_decode(self, seqs, skip_special_tokens=True):
            return [LEGAL_JSON]

    class FakeMiniCPMGenerateModel:
        def generate(self, **kwargs):
            gen_captured["gen_kwargs"] = kwargs
            return [[1, 2, 3, 99]]

    backend_gen = TransformersBackend(
        model_id="openbmb/MiniCPM-V-4_5@sha256:1",
        no_image=True,
        model=FakeMiniCPMGenerateModel(),
        processor=FakeMiniCPMProcessor(),
        image_loader=fail_image_loader,
    )
    res_gen = backend_gen.infer_one(req)
    assert res_gen.status == "success"
    assert res_gen.raw_output == LEGAL_JSON
    assert gen_captured["proc_kwargs"] == {"text": prompt_text, "return_tensors": "pt"}
    assert "images" not in gen_captured["proc_kwargs"]
    assert "temporal_ids" not in gen_captured["proc_kwargs"]

    # Lazy import invariant preserved
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_transformers_backend_generic_vlm_and_native_internvl_no_image(tmp_path):
    records, _, _, _ = _build_batch(tmp_path, count=1, write_pngs=False)
    rec = records[0]
    prompt_text = "请输出五类标签 JSON"
    req = InferenceRequest(
        candidate_id=rec["candidate_id"],
        record=rec,
        frame_paths=(),
        frame_pts_seconds=(),
        prompt_text=prompt_text,
        no_image=True,
    )

    def fail_image_loader(_path):
        raise AssertionError("image_loader must not run when no_image=True")

    # 1. Generic HF VLM path (Qwen3-VL / HF InternVL3.5)
    for model_id in ("Qwen/Qwen3-VL-8B-Instruct@sha256:1", "OpenGVLab/InternVL3.5-8B-HF@sha256:2"):
        captured: dict = {}

        class FakeHFProcessor:
            def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
                captured["messages"] = messages
                return "<text-only-prompt>"

            def __call__(self, **kwargs):
                captured["proc_kwargs"] = kwargs
                return {"input_ids": [[10, 20]]}

            def batch_decode(self, seqs, skip_special_tokens=True):
                return [LEGAL_JSON]

        class FakeHFModel:
            def generate(self, **kwargs):
                captured["gen_kwargs"] = kwargs
                return [[10, 20, 77]]

        backend = TransformersBackend(
            model_id=model_id,
            max_pixels=262144,
            no_image=True,
            model=FakeHFModel(),
            processor=FakeHFProcessor(),
            image_loader=fail_image_loader,
        )
        res = backend.infer_one(req)
        assert res.status == "success"
        assert res.raw_output == LEGAL_JSON
        assert captured["messages"] == [{"role": "user", "content": [{"type": "text", "text": prompt_text}]}]
        assert captured["proc_kwargs"] == {"text": "<text-only-prompt>", "return_tensors": "pt"}
        assert "images" not in captured["proc_kwargs"]
        assert "max_pixels" not in captured["proc_kwargs"]
        assert res.extra_meta["no_image"] is True
        assert res.extra_meta["modality"] == MODALITY_TEXT_ONLY
        assert res.extra_meta["max_pixels"] is None

    # 2. Native InternVL model.chat() path (pixel_values=None, zero <image> tokens, works with processor=None)
    internvl_called: dict = {}

    class FakeNativeInternVL:
        def chat(self, tokenizer, pixel_values, question, generation_config, num_patches_list=None):
            internvl_called["args"] = (tokenizer, pixel_values, question, generation_config, num_patches_list)
            return LEGAL_JSON

    tok = object()
    native_backend = TransformersBackend(
        model_id="OpenGVLab/InternVL3-8B@sha256:3",
        max_pixels=262144,
        no_image=True,
        model=FakeNativeInternVL(),
        processor=None,
        tokenizer=tok,
        image_loader=fail_image_loader,
    )
    res_native = native_backend.infer_one(req)
    assert res_native.status == "success"
    assert res_native.raw_output == LEGAL_JSON
    assert internvl_called["args"][0] is tok
    assert internvl_called["args"][1] is None
    assert internvl_called["args"][2] == prompt_text
    assert "<image>" not in internvl_called["args"][2]
    assert internvl_called["args"][4] is None


# --------------------------------------------------------------------------------------
# 3. End-to-end run_inference(..., no_image=True) + FakeBackend + score verification
# --------------------------------------------------------------------------------------
def test_run_inference_no_image_with_fake_backend_and_score_end_to_end(tmp_path):
    records, manifest, reviews, _ = _build_batch(tmp_path, count=7, write_pngs=False, with_reviews=True)
    preds_path = tmp_path / "predictions.jsonl"
    meta_path = tmp_path / "predictions.jsonl.meta.json"
    prompt_id = "prompt@sha256:" + "a" * 64

    # Pass FakeBackend() without explicit no_image=True to ensure run_inference(no_image=True)
    # still enforces text-only request & consistent run_meta metadata.
    backend = FakeBackend()
    predictions, run_meta = infer.run_inference(
        records,
        manifest,
        backend=backend,
        run_id="runb-fake-e2e",
        prompt_id=prompt_id,
        prompt_text="仅凭文字先验回答\n",
        model_id="fake",
        frames_dir=None,
        decode_config={"temperature": 0.0, "max_tokens": 512, "top_p": 1.0, "seed": 123},
        output_path=preds_path,
        meta_output_path=meta_path,
        no_image=True,
    )

    assert len(predictions) == 7
    assert all(row["input_id"] == f"no_image:{rec['input_id']}" for row, rec in zip(predictions, records))

    saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved_meta == run_meta
    assert saved_meta["run_id"] == "runb-fake-e2e"
    assert saved_meta["model_id"] == "fake"
    assert saved_meta["prompt_id"] == prompt_id
    assert saved_meta["run_status"] == "completed"
    assert saved_meta["no_image"] is True
    assert saved_meta["modality"] == MODALITY_TEXT_ONLY
    assert saved_meta["decode_config"] == {"temperature": 0.0, "max_tokens": 512, "top_p": 1.0, "seed": 123}
    assert saved_meta["sampling_policy"] == {
        "sampling_rule": "evenly_spaced_inclusive",
        "target_frame_count": 8,
        "short_clip_policy": "fail_closed",
        "resize": None,
    }
    assert saved_meta["backend_identity"]["backend"] == "fake"
    assert saved_meta["backend_identity"]["no_image"] is True
    assert saved_meta["backend_identity"]["modality"] == MODALITY_TEXT_ONLY
    assert saved_meta["status_counts"] == {"success": 5, "request_failed": 1, "timeout": 1}
    assert all(
        rm["paired_record_input_id"] == rec["input_id"]
        and rm["input_id"] == f"no_image:{rec['input_id']}"
        and rm["extra_meta"]["no_image"] is True
        and rm["extra_meta"]["modality"] == MODALITY_TEXT_ONLY
        for rm, rec in zip(saved_meta["requests"], records)
    )

    # score.py scores Run B predictions.jsonl with zero changes (both API and CLI)
    parsed_preds = score.read_jsonl(preds_path)
    scored = score.score(manifest, reviews, parsed_preds)
    full_clip = scored["groups"]["real"]["full_clip"]
    assert full_clip["clips"] == 7
    assert full_clip["request_status_counts"] == {"success": 5, "request_failed": 1, "timeout": 1}
    assert full_clip["strict_format_valid"]["numerator"] == 2  # complete + conflict (both strict valid JSON)
    assert full_clip["strict_format_valid"]["denominator"] == 7

    manifest_file = tmp_path / "manifest.json"
    reviews_file = tmp_path / "reviews.jsonl"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    reviews_file.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in reviews) + "\n", encoding="utf-8"
    )
    score_out_dir = tmp_path / "score_out"
    rc_score = score.main([
        "--manifest", str(manifest_file),
        "--reviews", str(reviews_file),
        "--predictions", str(preds_path),
        "--output", str(score_out_dir),
    ])
    assert rc_score == 0
    assert (score_out_dir / "results.json").is_file()
    assert (score_out_dir / "report.md").is_file()


# --------------------------------------------------------------------------------------
# 4. CLI `--no-image` parsing, `run_meta.json` & `predictions.jsonl.meta.json`, HTTP & Fake
# --------------------------------------------------------------------------------------
def test_infer_cli_no_image_http_and_fake_write_paired_metadata(tmp_path):
    records, manifest, _, frames_dir = _build_batch(tmp_path, count=1, write_pngs=True)
    records_path = frames_dir / "records.jsonl"
    records_path.write_text(json.dumps(records[0], ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    prompt_path = tmp_path / "prompt.txt"
    prompt_text = "只输出一个 JSON 对象（Run B）\n"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    received_bodies: list[dict] = []

    class CaptureHandler(BaseHTTPRequestHandler):
        def log_message(self, _fmt, *_args):
            return None

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            received_bodies.append(json.loads(raw.decode("utf-8")))
            body = json.dumps({"choices": [{"message": {"content": LEGAL_JSON}}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server, base_url = _start_loopback_server(CaptureHandler)
    try:
        # 4a. HTTP --no-image with default <output>.meta.json (predictions.jsonl.meta.json)
        out_b1 = tmp_path / "runb_http" / "predictions.jsonl"
        out_b1.parent.mkdir()
        rc_b1 = infer.main([
            "--backend", "http",
            "--no-image",
            "--endpoint", base_url,
            "--model-id", "Qwen3-VL-8B-Instruct@sha256:runb",
            "--api-model-name", "Qwen/Qwen3-VL-8B-Instruct",
            "--run-id", "runb-http-default-meta",
            "--manifest", str(manifest_path),
            "--input-config", str(records_path),
            "--prompt-file", str(prompt_path),
            "--temperature", "0.0",
            "--max-tokens", "384",
            "--top-p", "0.95",
            "--seed", "42",
            "--max-pixels", "65536",
            "--output", str(out_b1),
        ])

        # 4b. HTTP --no-image with explicit --meta-output run_meta.json
        out_b2 = tmp_path / "runb_http_explicit" / "predictions.jsonl"
        out_b2.parent.mkdir()
        run_meta_path = out_b2.parent / "run_meta.json"
        rc_b2 = infer.main([
            "--backend", "http",
            "--no-image",
            "--endpoint", base_url,
            "--model-id", "Qwen3-VL-8B-Instruct@sha256:runb",
            "--run-id", "runb-http-explicit-meta",
            "--manifest", str(manifest_path),
            "--input-config", str(records_path),
            "--prompt-file", str(prompt_path),
            "--output", str(out_b2),
            "--meta-output", str(run_meta_path),
        ])

        # 4c. Default Run A (no `--no-image` flag) remains vision_text with 8 images
        out_a = tmp_path / "runa_http" / "predictions.jsonl"
        out_a.parent.mkdir()
        rc_a = infer.main([
            "--backend", "http",
            "--endpoint", base_url,
            "--model-id", "Qwen3-VL-8B-Instruct@sha256:runa",
            "--run-id", "runa-http-default",
            "--manifest", str(manifest_path),
            "--input-config", str(records_path),
            "--frames-dir", str(frames_dir),
            "--prompt-file", str(prompt_path),
            "--output", str(out_a),
        ])
    finally:
        server.shutdown()
        server.server_close()

    assert rc_b1 == 0 and rc_b2 == 0 and rc_a == 0
    assert len(received_bodies) == 3

    # Verify HTTP payloads: first two are text-only (0 image_url), third is Run A (8 image_url)
    for body_b in received_bodies[:2]:
        content_b = body_b["messages"][0]["content"]
        assert content_b == [{"type": "text", "text": prompt_text}]
        assert "mm_processor_kwargs" not in body_b
    assert received_bodies[0]["temperature"] == 0.0
    assert received_bodies[0]["max_tokens"] == 384
    assert received_bodies[0]["top_p"] == 0.95
    assert received_bodies[0]["seed"] == 42

    content_a = received_bodies[2]["messages"][0]["content"]
    assert sum(1 for item in content_a if item["type"] == "image_url") == 8
    assert content_a[-1] == {"type": "text", "text": prompt_text}

    # Verify predictions.jsonl.meta.json (default) & run_meta.json (explicit)
    default_meta_b1 = json.loads((out_b1.parent / "predictions.jsonl.meta.json").read_text(encoding="utf-8"))
    explicit_meta_b2 = json.loads(run_meta_path.read_text(encoding="utf-8"))
    default_meta_a = json.loads((out_a.parent / "predictions.jsonl.meta.json").read_text(encoding="utf-8"))

    for meta_b in (default_meta_b1, explicit_meta_b2):
        assert meta_b["no_image"] is True
        assert meta_b["modality"] == MODALITY_TEXT_ONLY
        assert meta_b["backend_identity"]["no_image"] is True
        assert meta_b["backend_identity"]["modality"] == MODALITY_TEXT_ONLY
        assert meta_b["sampling_policy"]["target_frame_count"] == 8
        assert meta_b["prompt_id"].startswith("prompt@sha256:")
    assert default_meta_b1["decode_config"] == {
        "temperature": 0.0,
        "max_tokens": 384,
        "top_p": 0.95,
        "seed": 42,
    }
    assert default_meta_a["no_image"] is False
    assert default_meta_a["modality"] == MODALITY_VISION_TEXT
    assert default_meta_a["backend_identity"]["no_image"] is False
    assert default_meta_a["backend_identity"]["modality"] == MODALITY_VISION_TEXT

    # 4d. Fake backend CLI with --no-image works without PNGs on disk and writes metadata
    no_png_records, no_png_manifest, _, _ = _build_batch(tmp_path / "nopng", count=2, write_pngs=False)
    np_records_path = tmp_path / "nopng_records.jsonl"
    np_records_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in no_png_records) + "\n", encoding="utf-8"
    )
    np_manifest_path = tmp_path / "nopng_manifest.json"
    np_manifest_path.write_text(json.dumps(no_png_manifest, ensure_ascii=False), encoding="utf-8")
    out_fake_b = tmp_path / "runb_fake" / "predictions.jsonl"
    out_fake_b.parent.mkdir()
    rc_fake_b = infer.main([
        "--backend", "fake",
        "--model-id", "fake",
        "--no-image",
        "--run-id", "runb-fake-cli",
        "--manifest", str(np_manifest_path),
        "--input-config", str(np_records_path),
        "--prompt-file", str(prompt_path),
        "--top-p", "0.9",
        "--seed", "99",
        "--output", str(out_fake_b),
    ])
    assert rc_fake_b == 0
    fake_meta = json.loads((out_fake_b.parent / "predictions.jsonl.meta.json").read_text(encoding="utf-8"))
    assert fake_meta["no_image"] is True
    assert fake_meta["modality"] == MODALITY_TEXT_ONLY
    assert fake_meta["decode_config"] == {"temperature": 0.0, "max_tokens": 512, "top_p": 0.9, "seed": 99}
    assert fake_meta["total_requests"] == 2


# --------------------------------------------------------------------------------------
# 5. Fail-closed pairing guards under `--no-image` (exclusions, frozen subset, policy, input_id)
# --------------------------------------------------------------------------------------
def test_no_image_enforces_paired_validation_guards_fail_closed(tmp_path):
    records, manifest, _, _ = _build_batch(tmp_path / "guards", count=1, write_pngs=False)
    prompt_id = "prompt@sha256:" + "a" * 64

    # 5a. DEC-007 excluded candidate rejected under no_image=True
    bad_excl_rec = _make_record(None, cid="video_0006_pre_06", write_pngs=False)
    bad_excl_manifest = {
        "manifest_version": "excl/1",
        "samples": [{
            "manifest_sha256": bad_excl_rec["manifest_sha256"],
            "candidate_id": "video_0006_pre_06",
            "clip_sha256": bad_excl_rec["clip_sha256"],
            "source_id": "video_0006",
            "source_type": "real",
            "review_id": None,
        }],
    }
    with pytest.raises(InputError, match="DEC-007"):
        infer.run_inference(
            [bad_excl_rec],
            bad_excl_manifest,
            backend=FakeBackend(no_image=True),
            run_id="r-excl",
            prompt_id=prompt_id,
            prompt_text="p",
            model_id="fake",
            no_image=True,
        )

    # 5b. Wrong sampling policy (3 frames instead of 8) rejected under no_image=True
    rec3 = json.loads(json.dumps(records[0]))
    rec3["frames"] = rec3["frames"][:3]
    rec3["sampling"]["target_frame_count"] = 3
    with pytest.raises(InputError, match="8-frame"):
        infer.run_inference(
            [rec3],
            manifest,
            backend=FakeBackend(no_image=True),
            run_id="r-3f",
            prompt_id=prompt_id,
            prompt_text="p",
            model_id="fake",
            no_image=True,
        )

    # 5c. Tampered input_id rejected under no_image=True
    rec_tampered = json.loads(json.dumps(records[0]))
    rec_tampered["input_id"] = "input@sha256:" + "f" * 64
    with pytest.raises(InputError, match="input_id"):
        infer.run_inference(
            [rec_tampered],
            manifest,
            backend=FakeBackend(no_image=True),
            run_id="r-tampered",
            prompt_id=prompt_id,
            prompt_text="p",
            model_id="fake",
            no_image=True,
        )

    # 5d. Contradictory backend(no_image=True) passed into run_inference(no_image=False) fails closed
    with pytest.raises(InputError, match="no_image"):
        infer.run_inference(
            records,
            manifest,
            backend=FakeBackend(no_image=True),
            run_id="r-contradict",
            prompt_id=prompt_id,
            prompt_text="p",
            model_id="fake",
            frames_dir=tmp_path / "guards" / "frames",
            no_image=False,
        )

    # 5e. Frozen eval-dev-v1 subset mismatch rejected via CLI even with --no-image
    dev_subset_path = REPO_ROOT / "data/eval-subsets/eval-dev-v1.json"
    full_manifest_out = tmp_path / "full-manifest.json"
    dev_manifest_out = tmp_path / "dev-manifest.json"
    assert manifest_convert.main([
        "--input", str(REPO_ROOT / "data/sub_video/manifest.json"),
        "--manifest-version", "full/1",
        "--output", str(full_manifest_out),
    ]) == 0
    assert manifest_convert.main([
        "--input", str(REPO_ROOT / "data/sub_video/manifest.json"),
        "--candidate-ids", str(dev_subset_path),
        "--manifest-version", "dev/1",
        "--output", str(dev_manifest_out),
    ]) == 0
    dev_manifest = json.loads(dev_manifest_out.read_text(encoding="utf-8"))
    dev_records_path = tmp_path / "dev_records.jsonl"
    with dev_records_path.open("w", encoding="utf-8") as stream:
        for sample in dev_manifest["samples"]:
            rec = _make_record(
                None,
                cid=sample["candidate_id"],
                clip_sha=sample["clip_sha256"],
                manifest_sha=sample["manifest_sha256"],
                write_pngs=False,
            )
            stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
    prompt_path = tmp_path / "p.txt"
    prompt_path.write_text("prompt\n", encoding="utf-8")

    bad_out = tmp_path / "bad_runb.jsonl"
    err = io.StringIO()
    with redirect_stderr(err):
        rc_bad = infer.main([
            "--backend", "fake",
            "--model-id", "fake",
            "--no-image",
            "--manifest", str(full_manifest_out),
            "--candidate-ids", str(dev_subset_path),
            "--input-config", str(dev_records_path),
            "--prompt-file", str(prompt_path),
            "--run-id", "runb-bad-subset",
            "--output", str(bad_out),
        ])
    assert rc_bad == 2
    assert "do not match frozen subset" in err.getvalue()
    assert not bad_out.exists()

    # Exact 210-clip frozen eval-dev-v1 subset succeeds cleanly under --no-image and scores cleanly!
    good_out = tmp_path / "good_runb.jsonl"
    rc_good = infer.main([
        "--backend", "fake",
        "--model-id", "fake",
        "--no-image",
        "--manifest", str(dev_manifest_out),
        "--candidate-ids", str(dev_subset_path),
        "--input-config", str(dev_records_path),
        "--prompt-file", str(prompt_path),
        "--run-id", "runb-dev-v1-fake",
        "--output", str(good_out),
    ])
    assert rc_good == 0
    good_meta = json.loads((tmp_path / "good_runb.jsonl.meta.json").read_text(encoding="utf-8"))
    assert good_meta["no_image"] is True
    assert good_meta["modality"] == MODALITY_TEXT_ONLY
    assert good_meta["eval_subset_id"] == "eval-dev-v1"
    assert good_meta["total_requests"] == 210
    good_rows = score.read_jsonl(good_out)
    scored = score.score(dev_manifest, [], good_rows)
    assert len(scored["samples"]) == 210
    assert scored["groups"]["real"]["full_clip"]["clips"] == 210


# --------------------------------------------------------------------------------------
# 6. Regression tests for PR #29 review advisories (decode merge, Run-A backend reuse, CLI validation)
# --------------------------------------------------------------------------------------
def test_no_image_advisory_regressions_decode_merge_backend_identity_and_fake_cli_nan(tmp_path):
    records, manifest, _, _ = _build_batch(tmp_path, count=1, write_pngs=False)
    prompt_id = "prompt@sha256:" + "a" * 64

    # 6a. Passing decode_config={"top_p": None} into run_inference with an HttpBackend(top_p=0.8, max_pixels=65536)
    #     must record the actual effective top_p=0.8 AND neutralize stale max_pixels in backend_identity when no_image=True.
    captured_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"choices": [{"message": {"content": LEGAL_JSON}}]})

    runa_constructed_backend = HttpBackend(
        endpoint="http://127.0.0.1:8000/v1",
        model_id="Qwen3-VL-8B-Instruct@sha256:1",
        temperature=0.2,
        max_tokens=256,
        top_p=0.8,
        seed=7,
        max_pixels=65536,
        no_image=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        preds, meta = infer.run_inference(
            records,
            manifest,
            backend=runa_constructed_backend,
            run_id="runb-merge-check",
            prompt_id=prompt_id,
            prompt_text="prompt",
            model_id="Qwen3-VL-8B-Instruct@sha256:1",
            decode_config={"temperature": None, "max_tokens": None, "top_p": None, "seed": None},
            no_image=True,
        )
    finally:
        runa_constructed_backend.close()

    assert len(preds) == 1 and preds[0]["status"] == "success"
    assert captured_payload["top_p"] == 0.8
    assert captured_payload["temperature"] == 0.2
    assert captured_payload["max_tokens"] == 256
    assert captured_payload["seed"] == 7
    assert "mm_processor_kwargs" not in captured_payload
    assert meta["decode_config"] == {"temperature": 0.2, "max_tokens": 256, "top_p": 0.8, "seed": 7}
    assert meta["backend_identity"]["no_image"] is True
    assert meta["backend_identity"]["modality"] == MODALITY_TEXT_ONLY
    assert meta["backend_identity"]["max_pixels"] is None

    # 6b. Default fake CLI path must reject --top-p nan fail-closed before writing any output/meta files.
    rec_path = tmp_path / "recs.jsonl"
    rec_path.write_text(json.dumps(records[0], ensure_ascii=False) + "\n", encoding="utf-8")
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("prompt\n", encoding="utf-8")
    bad_out = tmp_path / "nan_preds.jsonl"
    bad_meta = tmp_path / "nan_meta.json"
    err = io.StringIO()
    with redirect_stderr(err):
        rc = infer.main([
            "--backend", "fake",
            "--model-id", "fake",
            "--run-id", "run-nan",
            "--manifest", str(man_path),
            "--input-config", str(rec_path),
            "--prompt-file", str(prompt_path),
            "--top-p", "nan",
            "--output", str(bad_out),
            "--meta-output", str(bad_meta),
        ])
    assert rc == 2
    assert "top_p" in err.getvalue()
    assert not bad_out.exists()
    assert not bad_meta.exists()

    # 6c. Non-JSON-serializable extra key (e.g., custom NaN) in decode_config fails closed
    #     BEFORE creating output_path or meta_output_path (no orphan files left behind).
    orphan_out = tmp_path / "orphan_preds.jsonl"
    orphan_meta = tmp_path / "orphan_meta.json"
    with pytest.raises(InputError, match="JSON-serializable"):
        infer.run_inference(
            records,
            manifest,
            backend=FakeBackend(no_image=True),
            run_id="run-custom-nan",
            prompt_id=prompt_id,
            prompt_text="prompt",
            model_id="fake",
            decode_config={"custom": float("nan")},
            output_path=orphan_out,
            meta_output_path=orphan_meta,
            no_image=True,
        )
    assert not orphan_out.exists()
    assert not orphan_meta.exists()

    # 6d. Non-JSON-serializable backend run_identity fails closed BEFORE creating output files.
    class BadIdentityBackend:
        backend_name = "fake"

        def run_identity(self):
            return {"backend": "fake", "bad": float("nan")}

        def infer_one(self, request):
            raise AssertionError("backend must not run when initial metadata serialization fails")

        def close(self):
            return None

    with pytest.raises(ValueError):
        infer.run_inference(
            records,
            manifest,
            backend=BadIdentityBackend(),
            run_id="run-bad-id",
            prompt_id=prompt_id,
            prompt_text="prompt",
            model_id="fake",
            output_path=orphan_out,
            meta_output_path=orphan_meta,
            no_image=True,
        )
    assert not orphan_out.exists()
    assert not orphan_meta.exists()

