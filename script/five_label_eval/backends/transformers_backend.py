"""Thin local Hugging Face Transformers inference backend.

Lazy-imports ``torch``, ``transformers``, and ``PIL`` so CPU-only and offline
environments (including pytest) work with zero GPU or weight dependencies.

Supported first-round Tier 1 model families:
- ``minicpm-v-4.5`` (``MiniCPM-V-4.5`` / ``MiniCPM-V-4_5``): official-style
  ``0.1 s`` quantized ``temporal_ids`` + ``max_slice_nums=1``.
- ``qwen3-vl`` (``Qwen3-VL-8B-Instruct``)
- ``internvl3`` (``InternVL3-8B``)
- ``internvl3.5`` (``InternVL3.5-8B``)

Strict single-JSON output contract: raw model text is returned verbatim with NO
``<answer>`` unwrapping and NO fence stripping.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import hashlib
import io
import json
import math
from pathlib import Path
import random
import re
import signal
import sys
import threading
import time
from typing import Any, Callable, Sequence

from ..score import InputError
from . import InferenceRequest, InferenceResult, normalize_result

SUPPORTED_MODEL_FAMILIES = ("minicpm-v-4.5", "qwen3-vl", "internvl3", "internvl3.5")
MINICPM_TEMPORAL_GRID_SECONDS = 0.1
MINICPM_DEFAULT_MAX_SLICE_NUMS = 1
SHA256_RE = re.compile(r"[a-f0-9]{64}")
TRUSTED_REQUIRED_CONFIG_FILES = (
    "config.json",
    "processor_config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "generation_config.json",
    "chat_template.json",
)


class _InferenceTimeoutError(Exception):
    """Raised by POSIX SIGALRM when a single local inference call exceeds timeout."""


class _TimeoutGuardUnavailableError(RuntimeError):
    """Raised fail-closed when POSIX SIGALRM / main-thread timeout guard is unavailable."""


def detect_model_family(
    model_id: str,
    model_family: str | None = None,
    model_path: str | Path | None = None,
) -> str:
    """Resolve and validate the Tier 1 model family (fail-closed on unknown families)."""
    if model_family is not None:
        normalized = model_family.strip().lower()
        if normalized in SUPPORTED_MODEL_FAMILIES:
            return normalized
        raise InputError(
            f"unsupported model_family {model_family!r}; supported: {list(SUPPORTED_MODEL_FAMILIES)}"
        )

    probe = f"{model_id} {model_path or ''}".lower()
    if "minicpm" in probe and ("4.5" in probe or "4_5" in probe or "45" in probe):
        return "minicpm-v-4.5"
    if "qwen3-vl" in probe or "qwen3_vl" in probe:
        return "qwen3-vl"
    if "internvl3.5" in probe or "internvl3_5" in probe or "internvl-3.5" in probe:
        return "internvl3.5"
    if "internvl3" in probe or "internvl-3" in probe:
        return "internvl3"
    raise InputError(
        f"cannot infer supported Tier 1 model family from model_id={model_id!r}; "
        f"pass --model-family from {list(SUPPORTED_MODEL_FAMILIES)}"
    )


def compute_minicpm_temporal_ids(
    frame_pts_seconds: Sequence[float] | None,
    *,
    frame_indices: Sequence[int] | None = None,
    fps: float | None = None,
    grid_seconds: float = MINICPM_TEMPORAL_GRID_SECONDS,
) -> list[list[int]]:
    """Compute official-style ``0.1 s`` quantized per-frame ``temporal_ids`` for MiniCPM-V-4.5.

    Prefers measured per-frame ``pts_seconds``; falls back to ``frame_index / fps``
    when ``frame_pts_seconds`` is absent and both ``frame_indices`` and positive
    ``fps`` are available. Returns one single-frame group ``[quantized_id]`` per
    frame so each of the 8 frames keeps its distinct temporal position.
    """
    if isinstance(grid_seconds, bool) or not isinstance(grid_seconds, (int, float)) or grid_seconds <= 0:
        raise InputError(f"grid_seconds must be positive, got {grid_seconds!r}")

    timestamps: list[float] = []
    if frame_pts_seconds:
        for value in frame_pts_seconds:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise InputError(f"invalid frame pts_seconds value: {value!r}")
            timestamps.append(float(value))
    elif frame_indices and fps is not None and not isinstance(fps, bool) and isinstance(fps, (int, float)) and fps > 0:
        for index in frame_indices:
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise InputError(f"invalid clip_frame_index for temporal_ids fallback: {index!r}")
            timestamps.append(float(index) / float(fps))
    else:
        raise InputError(
            "MiniCPM-V-4.5 requires frame pts_seconds (or clip_frame_indices + positive fps) "
            "to compute 0.1 s quantized temporal_ids"
        )

    quantized = [max(0, int(round(ts / grid_seconds))) for ts in timestamps]
    return [[tid] for tid in quantized]


def verify_trusted_snapshot_sha256(
    model_path: Path,
    trusted_files_sha256: dict[str, str],
) -> dict[str, str]:
    """Fail-closed SHA-256 check covering all local ``.py`` and core config files before ``trust_remote_code``."""
    if not isinstance(trusted_files_sha256, dict) or not trusted_files_sha256:
        raise InputError("trusted_files_sha256 must be a non-empty {relative_path: sha256} mapping")
    root = model_path.resolve()
    if (root / "adapter_config.json").exists():
        raise InputError(
            "PEFT adapter_config.json is refused under fail-closed local trust_remote_code verification "
            "(auto-redirecting to an unverified base_model_name_or_path is not permitted)"
        )
    normalized_map: dict[str, str] = {}
    for rel_path, expected in trusted_files_sha256.items():
        if not isinstance(rel_path, str) or not rel_path.strip():
            raise InputError(f"invalid relative path in trusted_files_sha256: {rel_path!r}")
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise InputError(f"trusted sha256 for {rel_path!r} must be 64-char lowercase hex")
        target = (root / rel_path).resolve()
        try:
            rel_norm = target.relative_to(root).as_posix()
        except ValueError as exc:
            raise InputError(f"trusted path {rel_path!r} escapes model directory {root}") from exc
        if not target.is_file():
            raise InputError(f"trusted snapshot file missing: {target}")
        normalized_map[rel_norm] = expected

    # Every Python module and present core config file in the local snapshot must be pinned.
    required_files: set[str] = set()
    for py_file in sorted(root.rglob("*.py")):
        if py_file.is_file():
            required_files.add(py_file.relative_to(root).as_posix())
    for cfg_name in TRUSTED_REQUIRED_CONFIG_FILES:
        cfg_file = root / cfg_name
        if cfg_file.is_file():
            required_files.add(cfg_name)

    uncovered = sorted(required_files - set(normalized_map))
    if uncovered:
        raise InputError(
            f"trusted_files_sha256 must cover all local .py and core config files before trust_remote_code; "
            f"uncovered: {uncovered}"
        )

    verified: dict[str, str] = {}
    for rel_norm, expected in sorted(normalized_map.items()):
        target = root / rel_norm
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise InputError(
                f"trusted snapshot SHA-256 mismatch for {rel_norm}: expected {expected}, got {actual}"
            )
        verified[rel_norm] = actual

    # Reject external repo references in auto_map (e.g. "org/repo--module.Class") across
    # model, processor, and tokenizer configs (both dict and legacy list forms) so
    # trust_remote_code=True can only execute verified local .py files inside model_path.
    for cfg_name in ("config.json", "processor_config.json", "preprocessor_config.json", "tokenizer_config.json"):
        cfg_file = root / cfg_name
        if not cfg_file.is_file():
            continue
        try:
            cfg_obj = json.loads(cfg_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InputError(f"failed to parse trusted config {cfg_name}: {exc}") from exc
        auto_map = cfg_obj.get("auto_map") if isinstance(cfg_obj, dict) else None
        if isinstance(auto_map, dict):
            for key, value in auto_map.items():
                refs = value if isinstance(value, list) else [value]
                for ref in refs:
                    if isinstance(ref, str) and "--" in ref:
                        raise InputError(
                            f"external auto_map reference {ref!r} in {cfg_name}[{key!r}] "
                            "is refused under fail-closed local trust_remote_code verification"
                        )
        elif isinstance(auto_map, list):
            for idx, ref in enumerate(auto_map):
                if isinstance(ref, str) and "--" in ref:
                    raise InputError(
                        f"external auto_map reference {ref!r} in {cfg_name}[{idx}] "
                        "is refused under fail-closed local trust_remote_code verification"
                    )
    return verified


def _resize_image_to_max_pixels(image: Any, max_pixels: int | None) -> Any:
    """Proportionally downscale (never upscale) a PIL-like image to <= max_pixels."""
    if max_pixels is None:
        return image
    size = getattr(image, "size", None)
    resize_fn = getattr(image, "resize", None)
    if (
        not isinstance(size, tuple)
        or len(size) != 2
        or not callable(resize_fn)
        or not all(isinstance(v, int) and v > 0 for v in size)
    ):
        return image
    width, height = size
    if width * height <= max_pixels:
        return image
    scale = math.sqrt(max_pixels / float(width * height))
    new_w = max(1, int(width * scale))
    new_h = max(1, int(height * scale))
    while new_w * new_h > max_pixels and (new_w > 1 or new_h > 1):
        if new_w >= new_h and new_w > 1:
            new_w -= 1
        elif new_h > 1:
            new_h -= 1
    return resize_fn((new_w, new_h))


def _move_inputs_to_model_device(inputs: Any, model: Any) -> Any:
    """Move processor batch tensors onto the model's execution device before generate()."""
    device = getattr(model, "device", None)
    if device is None:
        return inputs
    to_fn = getattr(inputs, "to", None)
    if callable(to_fn):
        return to_fn(device)
    if isinstance(inputs, Mapping):
        moved = {}
        for key, value in inputs.items():
            val_to = getattr(value, "to", None)
            moved[key] = val_to(device) if callable(val_to) else value
        return moved
    return inputs


def _apply_seed(seed: int | None) -> None:
    """Apply deterministic seed to Python RNG and (if already loaded) PyTorch."""
    if seed is None:
        return
    random.seed(seed)
    torch_mod = sys.modules.get("torch")
    if torch_mod is not None:
        torch_mod.manual_seed(seed)
        if hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
            torch_mod.cuda.manual_seed_all(seed)


@contextmanager
def _sigalrm_timeout(timeout_seconds: float, *, enabled: bool = True):
    """Fail-closed POSIX SIGALRM + setitimer guard matching ``inference-entry.md`` §7."""
    if not enabled:
        yield
        return
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        raise _TimeoutGuardUnavailableError(
            "POSIX SIGALRM / setitimer is unavailable; refusing to ignore timeout budget"
        )
    if threading.current_thread() is not threading.main_thread():
        raise _TimeoutGuardUnavailableError(
            "SIGALRM timeout requires main thread; refusing to ignore timeout budget"
        )

    def _handle_timeout(_signum, _frame):
        raise _InferenceTimeoutError(f"local transformers inference exceeded {timeout_seconds}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _default_image_loader(path: Path) -> Any:
    """Lazy-import PIL only when opening real PNG frames."""
    from PIL import Image

    with Image.open(path) as img:
        return img.convert("RGB")


def _default_bytes_image_loader(raw: bytes) -> Any:
    """Lazy-import PIL only when decoding verified PNG bytes in memory (TOCTOU-safe)."""
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        return img.convert("RGB")


def _default_model_loader(
    model_path: Path,
    model_family: str,
    max_pixels: int | None,
) -> tuple[Any, Any, Any]:
    """Lazy-import torch & transformers only when loading real local weights."""
    import torch
    from transformers import AutoModel, AutoModelForCausalLM, AutoProcessor, AutoTokenizer

    dtype = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else "auto"
    common_kwargs: dict[str, Any] = {
        "local_files_only": True,
        "trust_remote_code": True,
        "device_map": "auto",
        "low_cpu_mem_usage": True,
        "torch_dtype": dtype,
    }
    processor_kwargs: dict[str, Any] = {"local_files_only": True, "trust_remote_code": True}
    if max_pixels is not None and model_family == "qwen3-vl":
        processor_kwargs["max_pixels"] = max_pixels

    if model_family == "minicpm-v-4.5":
        model = AutoModel.from_pretrained(str(model_path), **common_kwargs).eval()
        tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=True)
        processor = AutoProcessor.from_pretrained(str(model_path), **processor_kwargs)
        return model, processor, tokenizer

    if model_family == "qwen3-vl":
        from transformers import AutoModelForImageTextToText

        model = AutoModelForImageTextToText.from_pretrained(str(model_path), **common_kwargs).eval()
        processor = AutoProcessor.from_pretrained(str(model_path), **processor_kwargs)
        tokenizer = getattr(processor, "tokenizer", None)
        return model, processor, tokenizer

    # InternVL3 / InternVL3.5
    try:
        model = AutoModel.from_pretrained(str(model_path), **common_kwargs).eval()
    except Exception:
        model = AutoModelForCausalLM.from_pretrained(str(model_path), **common_kwargs).eval()
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=True)
    if hasattr(model, "chat"):
        # Native OpenGVLab InternVL checkpoints define an image feature extractor in
        # preprocessor_config.json rather than a registered AutoProcessor (which would
        # silently fall back to AutoTokenizer and reject images=...).
        from transformers import AutoImageProcessor

        processor = AutoImageProcessor.from_pretrained(
            str(model_path), local_files_only=True, trust_remote_code=True
        )
    else:
        processor = AutoProcessor.from_pretrained(str(model_path), **processor_kwargs)
    return model, processor, tokenizer


class TransformersBackend:
    """Thin local HF Transformers backend with offline injectable model/processor hooks."""

    backend_name = "transformers"

    def __init__(
        self,
        *,
        model_id: str,
        model_path: str | Path | None = None,
        model_family: str | None = None,
        timeout_seconds: float = 600.0,
        temperature: float = 0.0,
        max_tokens: int = 512,
        seed: int | None = None,
        max_pixels: int | None = None,
        max_slice_nums: int | None = None,
        sampling_policy: dict[str, Any] | None = None,
        trusted_files_sha256: dict[str, str] | None = None,
        model: Any = None,
        processor: Any = None,
        tokenizer: Any = None,
        model_loader: Callable[[Path, str, int | None], tuple[Any, Any, Any]] | None = None,
        image_loader: Callable[[Path], Any] | None = None,
        use_sigalrm: bool = True,
    ) -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            raise InputError("transformers backend requires a non-empty model_id")
        if model_id.strip() == "fake":
            raise InputError("transformers backend refuses --model-id fake")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise InputError(f"timeout_seconds must be positive, got {timeout_seconds!r}")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise InputError(f"max_tokens must be a positive integer, got {max_tokens!r}")
        if max_pixels is not None and (isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0):
            raise InputError(f"max_pixels must be a positive integer when set, got {max_pixels!r}")
        if max_slice_nums is not None and (
            isinstance(max_slice_nums, bool) or not isinstance(max_slice_nums, int) or max_slice_nums <= 0
        ):
            raise InputError(f"max_slice_nums must be a positive integer when set, got {max_slice_nums!r}")

        self.model_id = model_id
        self.model_path = Path(model_path) if model_path is not None else None
        self.model_family = detect_model_family(model_id, model_family=model_family, model_path=self.model_path)
        self.timeout_seconds = float(timeout_seconds)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.seed = seed
        self.max_pixels = max_pixels
        self.sampling_policy = dict(sampling_policy) if isinstance(sampling_policy, dict) else None
        self.use_sigalrm = bool(use_sigalrm)

        if self.model_family == "minicpm-v-4.5":
            self.temporal_ids_policy = "quantized_0.1s"
            self.temporal_grid_seconds: float | None = MINICPM_TEMPORAL_GRID_SECONDS
            self.max_slice_nums: int | None = (
                MINICPM_DEFAULT_MAX_SLICE_NUMS if max_slice_nums is None else int(max_slice_nums)
            )
        else:
            self.temporal_ids_policy = "not_applicable"
            self.temporal_grid_seconds = None
            self.max_slice_nums = max_slice_nums

        self._trusted_files_sha256 = dict(trusted_files_sha256) if trusted_files_sha256 is not None else None
        self.verified_snapshot_sha256: dict[str, str] | None = None
        self._model = model
        self._processor = processor
        self._tokenizer = tokenizer
        self._model_loader = model_loader or _default_model_loader
        self._image_loader = image_loader or _default_image_loader
        self.cold_load_seconds: float | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if self.model_path is None:
            raise InputError("transformers backend requires --model-path when no model hook is injected")
        if not self.model_path.is_dir():
            raise InputError(f"transformers model_path does not exist or is not a directory: {self.model_path}")
        if self._trusted_files_sha256 is None:
            raise InputError(
                "transformers backend requires --trusted-sha256-file (trusted_files_sha256) "
                "before loading local model files with trust_remote_code=True"
            )
        self.verified_snapshot_sha256 = verify_trusted_snapshot_sha256(
            self.model_path, self._trusted_files_sha256
        )
        started = time.monotonic()
        loaded = self._model_loader(self.model_path, self.model_family, self.max_pixels)
        if not isinstance(loaded, tuple) or len(loaded) != 3:
            raise InputError("model_loader must return a 3-tuple of (model, processor, tokenizer)")
        self._model, self._processor, self._tokenizer = loaded
        self.cold_load_seconds = time.monotonic() - started

    def run_identity(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "model_path": str(self.model_path) if self.model_path is not None else None,
            "max_pixels": self.max_pixels,
            "sampling_policy": self.sampling_policy,
            "temporal_ids_policy": self.temporal_ids_policy,
            "temporal_ids_grid_seconds": self.temporal_grid_seconds,
            "max_slice_nums": self.max_slice_nums,
            "verified_snapshot_sha256": self.verified_snapshot_sha256,
            "cold_load_seconds": self.cold_load_seconds,
            "timeout_seconds": self.timeout_seconds,
            "decode_config": {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "seed": self.seed,
            },
            "output_unwrapping": "none",
        }

    def _run_minicpm(self, images: list[Any], request: InferenceRequest) -> tuple[str, dict[str, Any]]:
        frame_indices = [
            f.get("clip_frame_index")
            for f in (request.record.get("frames") or [])
            if isinstance(f, dict) and isinstance(f.get("clip_frame_index"), int)
        ]
        fps = (request.record.get("media") or {}).get("fps") if isinstance(request.record.get("media"), dict) else None
        temporal_ids = compute_minicpm_temporal_ids(
            request.frame_pts_seconds,
            frame_indices=frame_indices or None,
            fps=fps,
            grid_seconds=self.temporal_grid_seconds or MINICPM_TEMPORAL_GRID_SECONDS,
        )
        decode = request.decode_config or {}
        temperature = float(decode.get("temperature", self.temperature))
        max_tokens = int(decode.get("max_tokens", self.max_tokens))
        seed = decode.get("seed", self.seed)
        _apply_seed(seed)
        do_sample = temperature > 0.0
        meta = {
            "temporal_ids": temporal_ids,
            "max_slice_nums": self.max_slice_nums,
            "use_image_id": False,
        }

        if self.max_pixels is not None:
            images = [_resize_image_to_max_pixels(img, self.max_pixels) for img in images]

        if hasattr(self._model, "chat"):
            msgs = [{"role": "user", "content": [*images, request.prompt_text]}]
            chat_kwargs: dict[str, Any] = {
                "msgs": msgs,
                "tokenizer": self._tokenizer,
                "temporal_ids": temporal_ids,
                "max_slice_nums": self.max_slice_nums,
                "use_image_id": False,
                "do_sample": do_sample,
                "max_new_tokens": max_tokens,
            }
            if do_sample:
                chat_kwargs["temperature"] = temperature
            raw_text = self._model.chat(**chat_kwargs)
            return raw_text, meta

        if self._processor is None:
            raise RuntimeError("MiniCPM-V-4.5 requires model.chat or a processor")
        inputs = self._processor(
            text=request.prompt_text,
            images=images,
            temporal_ids=temporal_ids,
            max_slice_nums=self.max_slice_nums,
            use_image_id=False,
            return_tensors="pt",
        )
        inputs = _move_inputs_to_model_device(inputs, self._model)
        gen_kwargs: dict[str, Any] = {"max_new_tokens": max_tokens, "do_sample": do_sample}
        if do_sample:
            gen_kwargs["temperature"] = temperature
        output_ids = self._model.generate(**inputs, **gen_kwargs)
        text = self._decode_generated(output_ids, inputs)
        return text, meta

    def _run_generic_vlm(self, images: list[Any], request: InferenceRequest) -> tuple[str, dict[str, Any]]:
        decode = request.decode_config or {}
        temperature = float(decode.get("temperature", self.temperature))
        max_tokens = int(decode.get("max_tokens", self.max_tokens))
        seed = decode.get("seed", self.seed)
        _apply_seed(seed)
        do_sample = temperature > 0.0
        meta: dict[str, Any] = {"model_family": self.model_family, "max_pixels": self.max_pixels}

        if self._processor is None:
            raise RuntimeError(f"{self.model_family} requires a processor")

        if self.model_family in ("internvl3", "internvl3.5") and hasattr(self._model, "chat"):
            proc_kwargs: dict[str, Any] = {"images": images, "return_tensors": "pt"}
            if self.max_pixels is not None:
                proc_kwargs["max_pixels"] = self.max_pixels
            visual = self._processor(**proc_kwargs)
            if not isinstance(visual, Mapping) or "pixel_values" not in visual:
                raise RuntimeError(
                    f"{self.model_family} native chat requires processor output containing 'pixel_values'"
                )
            pixel_values = visual["pixel_values"]
            device = getattr(self._model, "device", None)
            dtype = getattr(self._model, "dtype", None)
            pv_to = getattr(pixel_values, "to", None)
            if callable(pv_to) and (device is not None or dtype is not None):
                to_kwargs = {}
                if device is not None:
                    to_kwargs["device"] = device
                if dtype is not None:
                    to_kwargs["dtype"] = dtype
                pixel_values = pv_to(**to_kwargs)
            num_patches_list = visual.get("num_patches_list")
            if num_patches_list is None:
                num_patches_list = [1] * len(images)
            frame_prefix = "\n".join(f"Frame{i + 1}: <image>" for i in range(len(images)))
            question = f"{frame_prefix}\n{request.prompt_text}"
            generation_config: dict[str, Any] = {
                "max_new_tokens": max_tokens,
                "do_sample": do_sample,
            }
            if do_sample:
                generation_config["temperature"] = temperature
            raw_text = self._model.chat(
                self._tokenizer,
                pixel_values,
                question,
                generation_config,
                num_patches_list=list(num_patches_list),
            )
            return raw_text, meta

        messages = [
            {
                "role": "user",
                "content": (
                    [{"type": "image"} for _ in images]
                    + [{"type": "text", "text": request.prompt_text}]
                ),
            }
        ]
        if hasattr(self._processor, "apply_chat_template"):
            prompt_for_processor = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        else:
            prompt_for_processor = request.prompt_text

        proc_kwargs = {
            "text": prompt_for_processor,
            "images": images,
            "return_tensors": "pt",
        }
        if self.max_pixels is not None:
            proc_kwargs["max_pixels"] = self.max_pixels
        inputs = self._processor(**proc_kwargs)
        inputs = _move_inputs_to_model_device(inputs, self._model)
        gen_kwargs = {"max_new_tokens": max_tokens, "do_sample": do_sample}
        if do_sample:
            gen_kwargs["temperature"] = temperature
        output_ids = self._model.generate(**inputs, **gen_kwargs)
        return self._decode_generated(output_ids, inputs), meta

    def _decode_generated(self, output_ids: Any, inputs: Any) -> str:
        decoder = self._processor if hasattr(self._processor, "batch_decode") else self._tokenizer
        if decoder is None or not hasattr(decoder, "batch_decode"):
            return output_ids if isinstance(output_ids, str) else str(output_ids)
        trimmed = output_ids
        # HF processor outputs BatchFeature (a Mapping, not a plain dict).
        if isinstance(inputs, Mapping) and "input_ids" in inputs:
            try:
                prompt_len = len(inputs["input_ids"][0])
                trimmed = [seq[prompt_len:] for seq in output_ids]
            except (TypeError, IndexError):
                trimmed = output_ids
        decoded = decoder.batch_decode(trimmed, skip_special_tokens=True)
        return decoded[0] if isinstance(decoded, list) and decoded else ""

    def infer_one(self, request: InferenceRequest) -> InferenceResult:
        # Model loading errors (e.g. missing path, trusted SHA-256 mismatch) fail closed
        # before per-sample execution rather than being swallowed as per-sample failures.
        self._ensure_loaded()
        started = time.monotonic()
        timeout = float(request.timeout_seconds if request.timeout_seconds is not None else self.timeout_seconds)
        try:
            if request.frame_bytes is not None and self._image_loader is _default_image_loader:
                images = [_default_bytes_image_loader(raw) for raw in request.frame_bytes]
            else:
                images = [self._image_loader(path) for path in request.frame_paths]
        except OSError as exc:
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=f"failed to load L3 frame image: {exc}",
            )

        try:
            with _sigalrm_timeout(timeout, enabled=self.use_sigalrm):
                if self.model_family == "minicpm-v-4.5":
                    raw_text, meta = self._run_minicpm(images, request)
                else:
                    raw_text, meta = self._run_generic_vlm(images, request)
        except _InferenceTimeoutError as exc:
            return InferenceResult(
                status="timeout",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=str(exc),
            )
        except _TimeoutGuardUnavailableError:
            raise
        except Exception as exc:
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=f"{type(exc).__name__}: {exc}",
            )

        return normalize_result(
            InferenceResult(
                status="success",
                raw_output=raw_text,
                latency_seconds=time.monotonic() - started,
                extra_meta=meta,
            )
        )

    def close(self) -> None:
        return None
