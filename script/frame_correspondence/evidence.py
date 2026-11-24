"""Core DEC-005 per-run frame-correspondence evidence builder and renderer."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .extractor import (
    FrameExtractor,
    MetadataOnlyExtractor,
    build_extractor,
    resolve_l3_image_path,
    resolve_layer_media_path,
    sha256_file,
)
from .loader import record_run_id
from .schema import (
    EVIDENCE_SCHEMA,
    MAPPING_DIRECTIONS,
    PROOF_DISCLAIMERS,
    PROOF_STRENGTH,
    RUN_INDEX_SCHEMA,
    EvidenceError,
    FrameExtractionResult,
)

SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
TIER_RANK = {"none": 0, "basic": 1, "full": 2}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_output_outside_git_repo(output_dir: Path | str) -> Path:
    """Reject output directories inside any Git repository/worktree per DEC-005."""
    resolved = Path(output_dir).expanduser().resolve()
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / ".git").exists():
            raise EvidenceError(
                f"output directory {resolved} is inside Git repository {ancestor}; "
                "DEC-005 forbids writing frame-correspondence evidence outputs into Git"
            )
    return resolved


def _safe_slug(value: str, fallback: str) -> str:
    cleaned = SAFE_SLUG_RE.sub("_", value.strip()).strip("._-")
    if not cleaned or cleaned in (".", ".."):
        return fallback
    return cleaned[:96]


def _run_slug_for_record(record: dict[str, Any], *, disambiguate: bool = False) -> str:
    run_id = record_run_id(record)
    input_id = str(record.get("input_id") or "")
    short_hash = hashlib.sha256(input_id.encode("utf-8")).hexdigest()[:12]
    if run_id:
        base = _safe_slug(run_id, f"run_{short_hash}")
        return f"{base}__{short_hash}" if disambiguate else base
    if input_id.startswith("input@sha256:") and len(input_id) >= len("input@sha256:") + 12:
        return f"input_{input_id.split(':', 1)[1][:12]}"
    return f"input_{short_hash}"


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _nominal_timestamp(frame_index: int | None, fps: Any) -> tuple[float | None, str]:
    rate = _positive_number(fps)
    if frame_index is None or rate is None:
        return None, "unavailable"
    return round(frame_index / rate, 6), "nominal_index_div_fps"


def _normalize_audit_tier(value: Any) -> str | None:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in TIER_RANK:
            return lowered
    return None


def _extract_record_limitations(record: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for source in (record, record.get("batch_audit"), record.get("run_metadata")):
        if not isinstance(source, dict):
            continue
        lims = source.get("limitations")
        if isinstance(lims, list):
            found.extend(str(item) for item in lims if isinstance(item, str) and item.strip())
        if source.get("no_frame_level_replay") is True:
            found.append("no_frame_level_replay")
    return found


def _extract_manifest_tier_and_limitations(
    subvideo_manifest: dict[str, Any] | None,
    candidate_entry: dict[str, Any] | None,
) -> tuple[str | None, list[str]]:
    if not subvideo_manifest:
        return None, []
    tiers: list[str] = []
    limitations: list[str] = []

    manifest_ver = subvideo_manifest.get("verification") or {}
    for raw_tier in (
        manifest_ver.get("mode"),
        subvideo_manifest.get("verification_mode"),
        (candidate_entry.get("verification") or {}).get("mode") if isinstance(candidate_entry, dict) else None,
        (candidate_entry.get("output") or {}).get("verification", {}).get("mode")
        if isinstance(candidate_entry, dict) and isinstance(candidate_entry.get("output"), dict)
        and isinstance(candidate_entry["output"].get("verification"), dict)
        else None,
    ):
        tier = _normalize_audit_tier(raw_tier)
        if tier:
            tiers.append(tier)

    if manifest_ver.get("frame_replay") == "skipped":
        limitations.append("no_frame_level_replay")

    gen_val = subvideo_manifest.get("generation_validation") or {}
    if isinstance(gen_val.get("limitations"), list):
        limitations.extend(str(x) for x in gen_val["limitations"] if isinstance(x, str) and x.strip())

    chosen_tier = min(tiers, key=lambda t: TIER_RANK[t]) if tiers else None
    return chosen_tier, limitations


def _build_proof_boundaries(
    record: dict[str, Any],
    *,
    subvideo_manifest: dict[str, Any] | None = None,
    candidate_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record_tiers: list[str] = []
    for source in (record, record.get("batch_audit"), record.get("run_metadata")):
        if not isinstance(source, dict):
            continue
        for key in ("audit_tier", "verification_mode"):
            tier = _normalize_audit_tier(source.get(key))
            if tier:
                record_tiers.append(tier)

    manifest_tier, manifest_limitations = _extract_manifest_tier_and_limitations(
        subvideo_manifest, candidate_entry
    )
    all_tiers = list(record_tiers)
    if manifest_tier:
        all_tiers.append(manifest_tier)

    limitations: list[str] = []
    limitations.extend(_extract_record_limitations(record))
    limitations.extend(manifest_limitations)

    if len(set(all_tiers)) > 1:
        limitations.append("audit_tier_conflict_conservatively_downgraded")

    audit_tier = min(all_tiers, key=lambda t: TIER_RANK[t]) if all_tiers else "unknown"
    verification_method = str((record.get("verification") or {}).get("method") or "unverified")

    if verification_method == "unverified":
        limitations.append("record_lineage_unverified")

    if audit_tier in ("basic", "none") or verification_method == "unverified" or "no_frame_level_replay" in limitations:
        no_frame_level_replay: bool | None = True
        limitations.append("no_frame_level_replay")
    elif audit_tier == "full":
        no_frame_level_replay = False
    else:
        no_frame_level_replay = None
        limitations.append("audit_tier_unspecified")

    dedup_limitations = sorted(dict.fromkeys(limitations))
    return {
        "proof_strength": PROOF_STRENGTH,
        "replaces_full_receipt": False,
        "equals_frame_level_replay_pass": False,
        "automated_pixel_comparison": False,
        "automated_similarity_judgment": False,
        "claims_verified_frame_correspondence": False,
        "audit_tier": audit_tier,
        "no_frame_level_replay": no_frame_level_replay,
        "active_limitations": dedup_limitations,
        "disclaimers": list(PROOF_DISCLAIMERS),
    }


def _derive_source_video_id(
    record: dict[str, Any],
    candidate_entry: dict[str, Any] | None,
) -> str | None:
    if isinstance(candidate_entry, dict) and isinstance(candidate_entry.get("source_video_id"), str):
        return candidate_entry["source_video_id"]
    if isinstance(record.get("source_video_id"), str) and record["source_video_id"].strip():
        return record["source_video_id"].strip()
    l0 = (record.get("lineage_media") or {}).get("l0")
    if isinstance(l0, dict) and isinstance(l0.get("path"), str) and l0["path"].strip():
        return Path(l0["path"]).stem
    return None


def _bind_manifests(
    record: dict[str, Any],
    *,
    subvideo_manifest: dict[str, Any] | None,
    roi_manifest: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    cid = str(record["candidate_id"])
    candidate_entry = None
    subvideo_binding: dict[str, Any] = {"provided": False}
    if subvideo_manifest is not None:
        candidate_entry = subvideo_manifest["candidates_by_id"].get(cid)
        record_manifest_sha = record.get("manifest_sha256")
        manifest_sha_match = (
            record_manifest_sha == subvideo_manifest["sha256"]
            if isinstance(record_manifest_sha, str)
            else None
        )
        if isinstance(candidate_entry, dict):
            output_block = candidate_entry.get("output")
            cand_sha = output_block.get("sha256") if isinstance(output_block, dict) else None
            if isinstance(cand_sha, str) and cand_sha != record.get("clip_sha256"):
                raise EvidenceError(
                    f"{cid}: subvideo manifest output.sha256 {cand_sha} != "
                    f"record.clip_sha256 {record.get('clip_sha256')}"
                )
        subvideo_binding = {
            "provided": True,
            "manifest_path": subvideo_manifest["path"],
            "manifest_sha256": subvideo_manifest["sha256"],
            "record_manifest_sha256_match": manifest_sha_match,
            "candidate_found": candidate_entry is not None,
        }

    source_video_id = _derive_source_video_id(record, candidate_entry)
    roi_binding: dict[str, Any] = {"provided": False}
    if roi_manifest is not None:
        roi_entry = roi_manifest["videos_by_id"].get(source_video_id) if source_video_id else None
        if isinstance(roi_entry, dict):
            roi_output = roi_entry.get("output")
            roi_sha = roi_output.get("sha256") if isinstance(roi_output, dict) else None
            l1_sha = ((record.get("lineage_media") or {}).get("l1") or {}).get("sha256")
            if isinstance(roi_sha, str) and isinstance(l1_sha, str) and roi_sha != l1_sha:
                raise EvidenceError(
                    f"{cid}: ROI manifest output.sha256 {roi_sha} != "
                    f"record.lineage_media.l1.sha256 {l1_sha}"
                )
        roi_binding = {
            "provided": True,
            "manifest_path": roi_manifest["path"],
            "manifest_sha256": roi_manifest["sha256"],
            "source_video_id": source_video_id,
            "video_found": roi_entry is not None,
            "status": roi_entry.get("status") if isinstance(roi_entry, dict) else None,
            "recipe_hash": roi_entry.get("recipe_hash") if isinstance(roi_entry, dict) else None,
        }

    return candidate_entry, subvideo_binding, roi_binding


def _relative_posix(path: Path | None, base_dir: Path) -> str | None:
    if path is None:
        return None
    return path.resolve().relative_to(base_dir.resolve()).as_posix()


def build_evidence_manifest(
    record: dict[str, Any],
    *,
    target_dir: Path,
    extractor: FrameExtractor,
    mode: str = "extract_images",
    subvideo_manifest: dict[str, Any] | None = None,
    roi_manifest: dict[str, Any] | None = None,
    media_root: Path | None = None,
    l3_frames_dir: Path | None = None,
    input_records_dir: Path | None = None,
) -> dict[str, Any]:
    """Resolve four-layer correspondence for one run/clip and optionally extract PNGs."""
    cid = str(record["candidate_id"])
    candidate_entry, subvideo_binding, roi_binding = _bind_manifests(
        record,
        subvideo_manifest=subvideo_manifest,
        roi_manifest=roi_manifest,
    )
    source_video_id = _derive_source_video_id(record, candidate_entry)
    proof_boundaries = _build_proof_boundaries(
        record,
        subvideo_manifest=subvideo_manifest,
        candidate_entry=candidate_entry,
    )

    lineage_media = record["lineage_media"]
    resolved_video_paths: dict[str, Path | None] = {
        layer: resolve_layer_media_path(
            (lineage_media.get(layer) or {}).get("path"),
            layer=layer,
            media_root=media_root,
        )
        for layer in ("l0", "l1", "l2")
    }

    frames_dir = target_dir / "frames"
    skipped_layers: list[dict[str, Any]] = []
    counts = {"extracted": 0, "copied": 0, "skipped": 0, "metadata_only": 0}
    l3_image_digests: dict[str, str | None] = {}
    resolved_frames: list[dict[str, Any]] = []

    for frame in record["frames"]:
        order = frame["display_order"]
        clip_idx = frame["clip_frame_index"]
        roi_idx = frame["roi_frame_index"]
        orig_idx = frame["original_source_frame_index"]
        record_pts = frame.get("pts_seconds")
        image_name = frame.get("image")

        mapping_raw = frame["frame_index_mapping"]
        mapping_with_direction = {
            node_name: {
                **dict(mapping_raw[node_name]),
                "direction": MAPPING_DIRECTIONS[node_name],
            }
            for node_name in ("clip_to_model_input", "clip_to_roi", "roi_to_original")
        }

        layers_out: dict[str, dict[str, Any]] = {}

        # --- L3: actual model input frame ---
        l3_source_path = resolve_l3_image_path(
            image_name,
            candidate_id=cid,
            l3_frames_dir=l3_frames_dir,
            input_records_dir=input_records_dir,
            media_root=media_root,
        )
        l3_target_path = frames_dir / f"order_{order:03d}_L3_model_input.png"
        if mode == "metadata_only":
            l3_res = FrameExtractionResult(status="metadata_only", backend="metadata_only")
            l3_sha = sha256_file(l3_source_path) if l3_source_path and l3_source_path.is_file() else None
        elif l3_source_path is None or not l3_source_path.is_file():
            l3_res = FrameExtractionResult(
                status="skipped",
                backend=None,
                skip_reason=f"l3_image_not_found_no_l2_substitution: {l3_source_path}",
            )
            l3_sha = None
        else:
            l3_res = extractor.copy_l3_image(l3_source_path, l3_target_path)
            l3_sha = l3_res.image_sha256

        counts[l3_res.status] += 1
        if l3_res.status == "skipped":
            skipped_layers.append(
                {
                    "display_order": order,
                    "layer": "L3",
                    "frame_index": order,
                    "reason": l3_res.skip_reason or "l3_image_skipped",
                }
            )
        if isinstance(image_name, str):
            l3_image_digests[image_name] = l3_sha
        layers_out["l3"] = {
            "layer": "L3",
            "role": "model_input",
            "frame_index": order,
            "source_clip_frame_index": clip_idx,
            "timestamp_seconds": record_pts,
            "timestamp_source": "record_pts_seconds" if record_pts is not None else "unavailable",
            "media_sha256": l3_sha,
            "source_image": image_name,
            "source_image_path": str(l3_source_path) if l3_source_path else None,
            "extracted_image": _relative_posix(l3_res.output_path, target_dir),
            "extracted_image_sha256": l3_res.image_sha256,
            "extraction_status": l3_res.status,
            "backend": l3_res.backend,
            "skip_reason": l3_res.skip_reason,
        }

        # --- L2 / L1 / L0 video layers ---
        layer_specs = (
            ("l2", "L2", "sub_video", clip_idx, "clip"),
            ("l1", "L1", "roi_video", roi_idx, "roi"),
            ("l0", "L0", "original_video", orig_idx, "orig"),
        )
        for layer_key, layer_tag, role, frame_idx, file_tag in layer_specs:
            media_entry = lineage_media[layer_key]
            resolved_path = resolved_video_paths[layer_key]
            media_sha = media_entry.get("sha256")
            declared_sha = media_entry.get("declared_sha256")
            fps = media_entry.get("fps")

            if frame_idx is None:
                if mode == "metadata_only":
                    status = "metadata_only"
                    skip_reason = f"{layer_tag.lower()}_frame_index_unverified"
                else:
                    status = "skipped"
                    skip_reason = f"{layer_tag.lower()}_frame_index_unavailable_unverified"
                    skipped_layers.append(
                        {
                            "display_order": order,
                            "layer": layer_tag,
                            "frame_index": None,
                            "reason": skip_reason,
                        }
                    )
                counts[status] += 1
                layers_out[layer_key] = {
                    "layer": layer_tag,
                    "role": role,
                    "frame_index": None,
                    "timestamp_seconds": None,
                    "timestamp_source": "unavailable",
                    "media_sha256": media_sha,
                    "declared_sha256": declared_sha,
                    "media_path": str(resolved_path) if resolved_path else media_entry.get("path"),
                    "extracted_image": None,
                    "extracted_image_sha256": None,
                    "extraction_status": status,
                    "backend": "metadata_only" if mode == "metadata_only" else None,
                    "skip_reason": skip_reason,
                }
                continue

            target_png = frames_dir / f"order_{order:03d}_{layer_tag}_{file_tag}_f{frame_idx:06d}.png"
            if mode == "metadata_only":
                res = FrameExtractionResult(status="metadata_only", backend="metadata_only")
            elif resolved_path is None or not resolved_path.is_file():
                res = FrameExtractionResult(
                    status="skipped",
                    backend=None,
                    skip_reason=f"{layer_tag.lower()}_media_file_missing: {resolved_path}",
                )
            else:
                res = extractor.extract_video_frame(resolved_path, frame_idx, target_png)

            counts[res.status] += 1
            if res.status == "skipped":
                skipped_layers.append(
                    {
                        "display_order": order,
                        "layer": layer_tag,
                        "frame_index": frame_idx,
                        "reason": res.skip_reason or f"{layer_tag.lower()}_extraction_skipped",
                    }
                )

            if res.pts_seconds is not None:
                ts_val, ts_src = res.pts_seconds, "decoded_pts_seconds"
            elif layer_key == "l2" and record_pts is not None:
                ts_val, ts_src = record_pts, "record_pts_seconds"
            else:
                ts_val, ts_src = _nominal_timestamp(frame_idx, fps)

            layers_out[layer_key] = {
                "layer": layer_tag,
                "role": role,
                "frame_index": frame_idx,
                "timestamp_seconds": ts_val,
                "timestamp_source": ts_src,
                "media_sha256": media_sha,
                "declared_sha256": declared_sha,
                "media_path": str(resolved_path) if resolved_path else media_entry.get("path"),
                "extracted_image": _relative_posix(res.output_path, target_dir),
                "extracted_image_sha256": res.image_sha256,
                "extraction_status": res.status,
                "backend": res.backend,
                "skip_reason": res.skip_reason,
            }

        resolved_frames.append(
            {
                "display_order": order,
                "decode_order": frame.get("decode_order"),
                "is_anchor": bool(frame.get("is_anchor", False)),
                "anchor_ref": frame.get("anchor_ref"),
                "mapping": mapping_with_direction,
                "layers": layers_out,
            }
        )

    run_id = record_run_id(record)
    media_digests: dict[str, Any] = {}
    for layer_key in ("l0", "l1", "l2"):
        entry = lineage_media[layer_key]
        resolved_path = resolved_video_paths[layer_key]
        media_digests[layer_key] = {
            "role": entry.get("role"),
            "recorded_path": entry.get("path"),
            "resolved_path": str(resolved_path) if resolved_path else None,
            "file_present": bool(resolved_path and resolved_path.is_file()),
            "sha256": entry.get("sha256"),
            "declared_sha256": entry.get("declared_sha256"),
            "fps": entry.get("fps"),
            "total_frames": entry.get("total_frames"),
            "total_frames_source": entry.get("total_frames_source"),
            "width": entry.get("width"),
            "height": entry.get("height"),
            "frame_count_notes": entry.get("frame_count_notes"),
        }
    media_digests["l3"] = {
        "role": "model_input_frames",
        "container_media": False,
        "frame_count": len(record["frames"]),
        "image_digests": l3_image_digests,
    }

    verification = record["verification"]
    manifest = {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": _utc_now(),
        "anchor_basis": "run_actual_model_input_frames",
        "proof_boundaries": proof_boundaries,
        "run_record": {
            "record_schema": record["record_schema"],
            "run_id": run_id,
            "binding_run_key": run_id or record["input_id"],
            "request_id": record.get("request_id"),
            "model_id": record.get("model_id"),
            "prompt_id": record.get("prompt_id"),
            "input_id": record["input_id"],
            "manifest_sha256": record.get("manifest_sha256"),
            "frame_count_convention": record.get("frame_count_convention", "decoded"),
            "frame_count": len(record["frames"]),
            "verification": {
                "verdict_id": verification.get("verdict_id"),
                "method": verification.get("method"),
                "evidence_sha256": verification.get("evidence_sha256"),
                "checked_at": verification.get("checked_at"),
                "failed_conditions": list(verification.get("failed_conditions") or []),
            },
        },
        "clip_identity": {
            "candidate_id": cid,
            "source_video_id": source_video_id,
            "clip_sha256": record["clip_sha256"],
            "manifest_sha256": record.get("manifest_sha256"),
            "subvideo_manifest_binding": subvideo_binding,
            "roi_manifest_binding": roi_binding,
        },
        "media_digests": media_digests,
        "mapping_directions": dict(MAPPING_DIRECTIONS),
        "extraction_summary": {
            "mode": mode,
            "extracted_count": counts["extracted"],
            "copied_count": counts["copied"],
            "skipped_count": counts["skipped"],
            "metadata_only_count": counts["metadata_only"],
            "skipped_layers": skipped_layers,
        },
        "frames": resolved_frames,
    }
    return manifest


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "`null`"
    return f"`{value}`"


def render_index_markdown(manifest: dict[str, Any]) -> str:
    """Render a human-readable DEC-005 inspection index.md from an evidence manifest."""
    pb = manifest["proof_boundaries"]
    rr = manifest["run_record"]
    ci = manifest["clip_identity"]
    md = manifest["media_digests"]
    es = manifest["extraction_summary"]

    lines: list[str] = [
        f"# 帧对应抽帧取证清单：`{ci['candidate_id']}`",
        "",
        "> **证明强度边界（DEC-005）**",
        f"> - `proof_strength`: `{pb['proof_strength']}`",
        f"> - `replaces_full_receipt`: `{str(pb['replaces_full_receipt']).lower()}`",
        f"> - `equals_frame_level_replay_pass`: `{str(pb['equals_frame_level_replay_pass']).lower()}`",
        f"> - `automated_pixel_comparison`: `{str(pb['automated_pixel_comparison']).lower()}` / `automated_similarity_judgment`: `{str(pb['automated_similarity_judgment']).lower()}`",
        f"> - `audit_tier`: `{pb['audit_tier']}` / `no_frame_level_replay`: `{pb['no_frame_level_replay']}`",
        f"> - `active_limitations`: `{', '.join(pb['active_limitations']) if pb['active_limitations'] else 'none'}`",
    ]
    for disclaimer in pb["disclaimers"]:
        lines.append(f"> - {disclaimer}")

    lines.extend(
        [
            "",
            "## 1. 取证绑定对象（按次取证）",
            "",
            "| 字段 | 值 |",
            "| --- | --- |",
            f"| `schema` | `{manifest['schema']}` |",
            f"| `anchor_basis` | `{manifest['anchor_basis']}`（严格锚定该次运行实际输入帧 `frames[]`） |",
            f"| `candidate_id` | `{ci['candidate_id']}` |",
            f"| `source_video_id` | {_fmt_cell(ci['source_video_id'])} |",
            f"| `run_id` | {_fmt_cell(rr['run_id'])} |",
            f"| `input_id` | `{rr['input_id']}` |",
            f"| `clip_sha256` | `{ci['clip_sha256']}` |",
            f"| `manifest_sha256` | {_fmt_cell(ci['manifest_sha256'])} |",
            f"| `verification.method` | `{rr['verification']['method']}` (`{rr['verification']['verdict_id']}`) |",
            f"| `extraction_mode` | `{es['mode']}`（extracted={es['extracted_count']}, copied={es['copied_count']}, skipped={es['skipped_count']}, metadata_only={es['metadata_only_count']}） |",
            "",
            "## 2. 四级媒体摘要与映射方向",
            "",
            "映射方向（按 `five-label-input-record/3` / `docs/eval/input-record.md` §10）：",
            "- `clip_to_model_input`: `L2->L3`（片段解码帧 → 模型输入帧）",
            "- `clip_to_roi`: `L2->L1`（片段帧号 + `source_start_frame` → ROI 帧号）",
            "- `roi_to_original`: `L1->L0`（ROI 帧号 → 原始源视频帧号，受记录级 `verification.method` 约束）",
            "",
            "| 层级 | 角色 | SHA-256（实测） | Declared SHA-256 | FPS | 总帧数 | 文件路径 |",
            "| --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )

    for key, tag in (("l3", "L3"), ("l2", "L2"), ("l1", "L1"), ("l0", "L0")):
        entry = md[key]
        if key == "l3":
            lines.append(
                f"| `{tag}` | `{entry['role']}` | 逐帧 PNG（无单文件容器） | — | — | {entry['frame_count']} | 见下表 |"
            )
        else:
            lines.append(
                f"| `{tag}` | `{entry['role']}` | {_fmt_cell(entry['sha256'])} | "
                f"{_fmt_cell(entry['declared_sha256'])} | {_fmt_cell(entry['fps'])} | "
                f"{_fmt_cell(entry['total_frames'])} | {_fmt_cell(entry['resolved_path'] or entry['recorded_path'])} |"
            )

    lines.extend(
        [
            "",
            "## 3. 逐帧四级对应表（人工查阅）",
            "",
            "| Order | L3 模型输入 | L2 子视频 | L1 ROI | L0 原视频 | 映射节点（`L2->L1` / `L1->L0`） |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )

    for frame in manifest["frames"]:
        order = frame["display_order"]
        cells: list[str] = []
        for layer_key in ("l3", "l2", "l1", "l0"):
            layer = frame["layers"][layer_key]
            idx_txt = "null" if layer["frame_index"] is None else str(layer["frame_index"])
            ts_txt = (
                "null"
                if layer["timestamp_seconds"] is None
                else f"{layer['timestamp_seconds']}s ({layer['timestamp_source']})"
            )
            img = layer["extracted_image"]
            if img:
                media_txt = f"[{Path(img).name}]({img})"
            elif layer["skip_reason"]:
                media_txt = f"{layer['extraction_status']}: `{layer['skip_reason']}`"
            else:
                media_txt = f"{layer['extraction_status']}"
            cells.append(f"f=`{idx_txt}` / t={ts_txt} / {media_txt}")

        c2r = frame["mapping"]["clip_to_roi"]
        r2o = frame["mapping"]["roi_to_original"]
        map_txt = (
            f"c2r: `{c2r.get('kind')}` (off={c2r.get('offset')}); "
            f"r2o: `{r2o.get('kind')}` / `{r2o.get('method')}` (off={r2o.get('offset')})"
        )
        lines.append(f"| {order} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {map_txt} |")

    if es["skipped_layers"]:
        lines.extend(
            [
                "",
                "## 4. 跳过明细（未伪造画面）",
                "",
                "| Order | 层级 | 帧号 | 跳过原因 |",
                "| ---: | --- | ---: | --- |",
            ]
        )
        for item in es["skipped_layers"]:
            lines.append(
                f"| {item['display_order']} | `{item['layer']}` | {_fmt_cell(item['frame_index'])} | `{item['reason']}` |"
            )

    lines.extend(
        [
            "",
            "**失效条件：** 当输入记录 `input_id`、各级媒体 SHA-256、映射方向契约或对应清单变更时，本人工取证快照即失效，须基于新运行记录重新抽取。",
            "",
        ]
    )
    return "\n".join(lines)


def extract_evidence_bundle(
    records: list[dict[str, Any]],
    *,
    output_dir: Path | str,
    mode: str = "extract_images",
    backend: str = "auto",
    extractor: FrameExtractor | None = None,
    subvideo_manifest: dict[str, Any] | None = None,
    roi_manifest: dict[str, Any] | None = None,
    media_root: Path | None = None,
    l3_frames_dir: Path | None = None,
    input_records_dir: Path | None = None,
) -> dict[str, Any]:
    """Extract per-run/clip evidence_manifest.json + index.md into output_dir outside Git."""
    out_root = ensure_output_outside_git_repo(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    active_extractor: FrameExtractor
    if extractor is not None:
        active_extractor = extractor
    elif mode == "metadata_only":
        active_extractor = MetadataOnlyExtractor()
    else:
        active_extractor = build_extractor(mode, backend=backend)

    # Disambiguate run slug if multiple records share the same (run_id, candidate_id).
    key_counts: dict[tuple[str, str], int] = {}
    for rec in records:
        pair = (_run_slug_for_record(rec, disambiguate=False), str(rec["candidate_id"]))
        key_counts[pair] = key_counts.get(pair, 0) + 1

    used_dirs: set[Path] = set()
    entries: list[dict[str, Any]] = []

    for index, rec in enumerate(records):
        cid = str(rec["candidate_id"])
        clip_slug = _safe_slug(cid, f"clip_{index:03d}")
        base_run_slug = _run_slug_for_record(rec, disambiguate=False)
        run_slug = _run_slug_for_record(rec, disambiguate=key_counts[(base_run_slug, cid)] > 1)
        target_dir = (out_root / run_slug / clip_slug).resolve()
        if not target_dir.is_relative_to(out_root):
            raise EvidenceError(f"resolved target directory {target_dir} escapes output root {out_root}")
        if target_dir in used_dirs:
            target_dir = (out_root / f"{run_slug}_{index:03d}" / clip_slug).resolve()
        used_dirs.add(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest = build_evidence_manifest(
            rec,
            target_dir=target_dir,
            extractor=active_extractor,
            mode=mode,
            subvideo_manifest=subvideo_manifest,
            roi_manifest=roi_manifest,
            media_root=media_root,
            l3_frames_dir=l3_frames_dir,
            input_records_dir=input_records_dir,
        )

        manifest_path = target_dir / "evidence_manifest.json"
        index_path = target_dir / "index.md"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        index_path.write_text(render_index_markdown(manifest), encoding="utf-8")

        entries.append(
            {
                "candidate_id": cid,
                "run_id": manifest["run_record"]["run_id"],
                "input_id": manifest["run_record"]["input_id"],
                "verification_method": manifest["run_record"]["verification"]["method"],
                "audit_tier": manifest["proof_boundaries"]["audit_tier"],
                "no_frame_level_replay": manifest["proof_boundaries"]["no_frame_level_replay"],
                "evidence_manifest": _relative_posix(manifest_path, out_root),
                "index_markdown": _relative_posix(index_path, out_root),
                "extraction_summary": manifest["extraction_summary"],
            }
        )

    run_index = {
        "schema": RUN_INDEX_SCHEMA,
        "generated_at": _utc_now(),
        "output_dir": str(out_root),
        "mode": mode,
        "proof_strength": PROOF_STRENGTH,
        "replaces_full_receipt": False,
        "records_processed": len(entries),
        "entries": entries,
    }
    (out_root / "run_index.json").write_text(
        json.dumps(run_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_index
