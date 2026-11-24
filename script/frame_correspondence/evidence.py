"""Core DEC-005 per-run frame-correspondence evidence builder and renderer."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .extractor import (
    FrameExtractor,
    MetadataOnlyExtractor,
    build_extractor,
    resolve_l3_image,
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


def _is_git_repo_dir(path: Path) -> bool:
    """Detect normal Git repos (.git dir), worktrees (.git file), and bare Git repos."""
    if (path / ".git").exists():
        return True
    if (path / "HEAD").is_file() and (path / "objects").is_dir() and (path / "refs").is_dir():
        return True
    return False


def ensure_output_outside_git_repo(output_dir: Path | str) -> Path:
    """Reject output directories inside any Git repository, worktree, or bare repo per DEC-005."""
    resolved = Path(output_dir).expanduser().resolve()
    for ancestor in (resolved, *resolved.parents):
        if _is_git_repo_dir(ancestor):
            raise EvidenceError(
                f"output directory {resolved} is inside Git repository {ancestor}; "
                "DEC-005 forbids writing frame-correspondence evidence outputs into Git"
            )
    return resolved


def validate_output_path(path: Path, output_root: Path, *, allow_existing_symlink: bool = False) -> Path:
    """Ensure a target directory or file stays inside output_root and outside any Git repo."""
    resolved_root = ensure_output_outside_git_repo(output_root)
    if not allow_existing_symlink:
        cur = path
        while cur != output_root and cur != resolved_root and cur != cur.parent:
            if cur.is_symlink():
                raise EvidenceError(
                    f"refusing to traverse or write through symlink {cur}; "
                    f"output paths must stay inside {resolved_root}"
                )
            cur = cur.parent
    resolved_target = path.resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise EvidenceError(
            f"resolved output path {resolved_target} escapes output root {resolved_root}"
        )
    ensure_output_outside_git_repo(resolved_target)
    return resolved_target


def _atomic_write_text(path: Path, text: str, *, output_root: Path) -> None:
    """Write UTF-8 text via a fresh temp file + os.replace so hard-linked inodes are never truncated."""
    validate_output_path(path, output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_output_path(path.parent, output_root)
    tmp_dir = Path(tempfile.mkdtemp(dir=path.parent, prefix=".tmp_write_"))
    tmp_file = tmp_dir / path.name
    try:
        tmp_file.write_text(text, encoding="utf-8")
        os.replace(tmp_file, path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _safe_slug(value: str, fallback: str) -> str:
    cleaned = SAFE_SLUG_RE.sub("_", value.strip()).strip("._-")
    if not cleaned or cleaned in (".", ".."):
        return fallback
    return cleaned[:80]


def _run_slug_for_record(record: dict[str, Any]) -> str:
    """Collision-free run slug always incorporating raw (run_id, input_id) hash."""
    run_id = record_run_id(record)
    input_id = str(record.get("input_id") or "")
    identity_payload = json.dumps(
        {"run_id": run_id, "input_id": input_id},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    short_hash = hashlib.sha256(identity_payload).hexdigest()[:12]
    if run_id:
        base = _safe_slug(run_id, "run")
        return f"{base}__{short_hash}"
    return f"input__{short_hash}"


def _clip_slug_for_id(candidate_id: str, fallback: str) -> str:
    base = _safe_slug(candidate_id, fallback)
    if base != candidate_id:
        suffix = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:8]
        return f"{base}__{suffix}"
    return base


def _check_existing_manifest_identity(
    manifest_path: Path,
    *,
    run_id: str | None,
    input_id: str,
    candidate_id: str,
) -> None:
    """Refuse silent overwrite if an existing manifest belongs to a different binding."""
    if not manifest_path.exists():
        return
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(
            f"refusing to overwrite unreadable existing evidence manifest at {manifest_path}: {exc}"
        ) from exc
    if not isinstance(existing, dict):
        raise EvidenceError(f"refusing to overwrite non-object manifest at {manifest_path}")
    existing_rr = existing.get("run_record") if isinstance(existing.get("run_record"), dict) else {}
    existing_ci = existing.get("clip_identity") if isinstance(existing.get("clip_identity"), dict) else {}
    existing_identity = (
        existing_rr.get("run_id"),
        existing_rr.get("input_id"),
        existing_ci.get("candidate_id"),
    )
    current_identity = (run_id, input_id, candidate_id)
    if existing_identity != current_identity:
        raise EvidenceError(
            f"refusing to overwrite existing evidence manifest at {manifest_path}: "
            f"existing binding {existing_identity!r} != current binding {current_identity!r}"
        )


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
    if not subvideo_manifest or candidate_entry is None:
        return None, []
    tiers: list[str] = []
    limitations: list[str] = []

    manifest_ver = subvideo_manifest.get("verification") or {}
    cand_output = candidate_entry.get("output") if isinstance(candidate_entry.get("output"), dict) else {}
    cand_out_ver = cand_output.get("verification") if isinstance(cand_output.get("verification"), dict) else {}
    cand_ver = candidate_entry.get("verification") if isinstance(candidate_entry.get("verification"), dict) else {}

    for raw_tier in (
        manifest_ver.get("mode"),
        subvideo_manifest.get("verification_mode"),
        cand_ver.get("mode"),
        cand_out_ver.get("mode"),
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
    subvideo_binding: dict[str, Any] | None = None,
    candidate_entry: dict[str, Any] | None = None,
    extra_limitations: list[str] | None = None,
) -> dict[str, Any]:
    record_tiers: list[str] = []
    for source in (record, record.get("batch_audit"), record.get("run_metadata")):
        if not isinstance(source, dict):
            continue
        for key in ("audit_tier", "verification_mode"):
            tier = _normalize_audit_tier(source.get(key))
            if tier:
                record_tiers.append(tier)

    limitations: list[str] = []
    limitations.extend(_extract_record_limitations(record))
    if extra_limitations:
        limitations.extend(extra_limitations)

    all_tiers = list(record_tiers)
    binding = subvideo_binding or {}
    if binding.get("provided"):
        if binding.get("binding_verified") is True:
            manifest_tier, manifest_limitations = _extract_manifest_tier_and_limitations(
                subvideo_manifest, candidate_entry
            )
            if manifest_tier:
                all_tiers.append(manifest_tier)
            limitations.extend(manifest_limitations)
        else:
            if not binding.get("candidate_found"):
                limitations.append("subvideo_manifest_candidate_not_found_tier_not_inherited")
            if binding.get("record_manifest_sha256_match") is False:
                limitations.append("subvideo_manifest_sha256_mismatch_tier_not_inherited")
            elif binding.get("record_manifest_sha256_match") is None:
                limitations.append("subvideo_manifest_record_sha256_missing_tier_not_inherited")

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
    verified_candidate_entry: dict[str, Any] | None,
) -> str | None:
    if (
        isinstance(verified_candidate_entry, dict)
        and isinstance(verified_candidate_entry.get("source_video_id"), str)
    ):
        return verified_candidate_entry["source_video_id"]
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
    subvideo_binding: dict[str, Any] = {"provided": False, "binding_verified": False}
    if subvideo_manifest is not None:
        candidate_entry = subvideo_manifest["candidates_by_id"].get(cid)
        record_manifest_sha = record.get("manifest_sha256")
        manifest_sha_match = (
            record_manifest_sha == subvideo_manifest["sha256"]
            if isinstance(record_manifest_sha, str) and record_manifest_sha.strip()
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
        # Strict manifest binding: requires BOTH candidate hit AND explicit manifest_sha256 match.
        binding_verified = (candidate_entry is not None) and (manifest_sha_match is True)
        subvideo_binding = {
            "provided": True,
            "manifest_path": subvideo_manifest["path"],
            "manifest_sha256": subvideo_manifest["sha256"],
            "record_manifest_sha256_match": manifest_sha_match,
            "candidate_found": candidate_entry is not None,
            "binding_verified": binding_verified,
        }

    verified_candidate_entry = candidate_entry if subvideo_binding.get("binding_verified") else None
    source_video_id = _derive_source_video_id(record, verified_candidate_entry)
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

    return verified_candidate_entry, subvideo_binding, roi_binding


def _relative_posix(path: Path | None, base_dir: Path) -> str | None:
    if path is None:
        return None
    return path.resolve().relative_to(base_dir.resolve()).as_posix()


def _cached_sha256(path: Path, cache: dict[Path, str | None]) -> str | None:
    key = path.resolve()
    if key not in cache:
        cache[key] = sha256_file(key)
    return cache[key]


def build_evidence_manifest(
    record: dict[str, Any],
    *,
    target_dir: Path,
    output_root: Path | None = None,
    extractor: FrameExtractor,
    mode: str = "extract_images",
    subvideo_manifest: dict[str, Any] | None = None,
    roi_manifest: dict[str, Any] | None = None,
    media_root: Path | None = None,
    l3_frames_dir: Path | None = None,
    input_records_dir: Path | None = None,
    allow_run_only_l3_fallback: bool = True,
    allow_unscoped_l3_fallback: bool = True,
    digest_cache: dict[Path, str | None] | None = None,
) -> dict[str, Any]:
    """Resolve four-layer correspondence for one run/clip and optionally extract PNGs."""
    boundary_root = ensure_output_outside_git_repo(output_root if output_root is not None else target_dir)
    validate_output_path(target_dir, boundary_root)

    cid = str(record["candidate_id"])
    run_id = record_run_id(record)
    input_id = str(record["input_id"])
    run_slug = _run_slug_for_record(record)

    verified_candidate_entry, subvideo_binding, roi_binding = _bind_manifests(
        record,
        subvideo_manifest=subvideo_manifest,
        roi_manifest=roi_manifest,
    )
    source_video_id = _derive_source_video_id(record, verified_candidate_entry)

    lineage_media = record["lineage_media"]
    resolved_video_paths: dict[str, Path | None] = {
        layer: resolve_layer_media_path(
            (lineage_media.get(layer) or {}).get("path"),
            layer=layer,
            media_root=media_root,
        )
        for layer in ("l0", "l1", "l2")
    }

    # Verify disk SHA-256 once per resolved video path before any decoding in extract_images mode.
    cache = digest_cache if digest_cache is not None else {}
    observed_digests: dict[str, str | None] = {}
    digest_matches: dict[str, bool | None] = {}
    extra_limitations: list[str] = []
    for layer_key in ("l0", "l1", "l2"):
        recorded_sha = (lineage_media.get(layer_key) or {}).get("sha256")
        resolved_path = resolved_video_paths[layer_key]
        if mode != "metadata_only" and resolved_path is not None and resolved_path.is_file():
            obs = _cached_sha256(resolved_path, cache)
            observed_digests[layer_key] = obs
            match = (obs == recorded_sha) if (obs is not None and isinstance(recorded_sha, str)) else False
            digest_matches[layer_key] = match
            if not match:
                extra_limitations.append(f"{layer_key}_disk_sha256_mismatch")
        else:
            observed_digests[layer_key] = None
            digest_matches[layer_key] = None

    proof_boundaries = _build_proof_boundaries(
        record,
        subvideo_manifest=subvideo_manifest,
        subvideo_binding=subvideo_binding,
        candidate_entry=verified_candidate_entry,
        extra_limitations=extra_limitations,
    )

    frames_dir = target_dir / "frames"
    validate_output_path(frames_dir, boundary_root)
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
        expected_l3_sha = frame.get("image_sha256") or frame.get("sha256")

        mapping_raw = frame["frame_index_mapping"]
        mapping_with_direction = {
            node_name: {
                **dict(mapping_raw[node_name]),
                "direction": MAPPING_DIRECTIONS[node_name],
            }
            for node_name in ("clip_to_model_input", "clip_to_roi", "roi_to_original")
        }

        layers_out: dict[str, dict[str, Any]] = {}

        # --- L3: actual model input frame (run/input-bound, never substituted by L2) ---
        l3_resolution = resolve_l3_image(
            image_name,
            candidate_id=cid,
            run_id=run_id,
            input_id=input_id,
            run_slug=run_slug,
            expected_sha256=expected_l3_sha,
            allow_run_only_fallback=allow_run_only_l3_fallback,
            allow_unscoped_shared_fallback=allow_unscoped_l3_fallback,
            l3_frames_dir=l3_frames_dir,
            input_records_dir=input_records_dir,
            media_root=media_root,
        )
        l3_target_path = frames_dir / f"order_{order:03d}_L3_model_input.png"
        if mode == "metadata_only":
            l3_res = FrameExtractionResult(status="metadata_only", backend="metadata_only")
            l3_sha = l3_resolution.observed_sha256
        elif l3_resolution.path is None or not l3_resolution.path.is_file():
            l3_res = FrameExtractionResult(
                status="skipped",
                backend=None,
                skip_reason=l3_resolution.skip_reason or "l3_image_not_found_no_l2_substitution",
            )
            l3_sha = None
        else:
            validate_output_path(l3_target_path, boundary_root)
            l3_res = extractor.copy_l3_image(l3_resolution.path, l3_target_path)
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
            "recorded_sha256": expected_l3_sha if isinstance(expected_l3_sha, str) else None,
            "observed_sha256": l3_sha,
            "binding_basis": l3_resolution.binding_basis,
            "source_image": image_name,
            "source_image_path": str(l3_resolution.path) if l3_resolution.path else None,
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
            recorded_sha = media_entry.get("sha256")
            declared_sha = media_entry.get("declared_sha256")
            observed_sha = observed_digests[layer_key]
            digest_match = digest_matches[layer_key]
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
                    "media_sha256": recorded_sha,
                    "recorded_sha256": recorded_sha,
                    "observed_sha256": observed_sha,
                    "digest_match_on_disk": digest_match,
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
            elif digest_match is False:
                res = FrameExtractionResult(
                    status="skipped",
                    backend=None,
                    skip_reason=(
                        f"{layer_tag.lower()}_disk_sha256_mismatch: "
                        f"observed={observed_sha} != recorded={recorded_sha}"
                    ),
                )
            else:
                validate_output_path(target_png, boundary_root)
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
                "media_sha256": recorded_sha,
                "recorded_sha256": recorded_sha,
                "observed_sha256": observed_sha,
                "digest_match_on_disk": digest_match,
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
            "recorded_sha256": entry.get("sha256"),
            "observed_sha256": observed_digests[layer_key],
            "digest_match_on_disk": digest_matches[layer_key],
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
            "binding_run_key": run_id or input_id,
            "request_id": record.get("request_id"),
            "model_id": record.get("model_id"),
            "prompt_id": record.get("prompt_id"),
            "input_id": input_id,
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
            "| 层级 | 角色 | Recorded SHA-256 | Observed SHA-256（盘面） | Declared SHA-256 | FPS | 总帧数 | 文件路径 |",
            "| --- | --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )

    for key, tag in (("l3", "L3"), ("l2", "L2"), ("l1", "L1"), ("l0", "L0")):
        entry = md[key]
        if key == "l3":
            lines.append(
                f"| `{tag}` | `{entry['role']}` | 逐帧 PNG（无单文件容器） | 见下表 | — | — | {entry['frame_count']} | 见下表 |"
            )
        else:
            lines.append(
                f"| `{tag}` | `{entry['role']}` | {_fmt_cell(entry['recorded_sha256'])} | "
                f"{_fmt_cell(entry['observed_sha256'])} | {_fmt_cell(entry['declared_sha256'])} | "
                f"{_fmt_cell(entry['fps'])} | {_fmt_cell(entry['total_frames'])} | "
                f"{_fmt_cell(entry['resolved_path'] or entry['recorded_path'])} |"
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


def count_candidate_runs(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count distinct (run_id, input_id) identities per candidate_id across a record set."""
    by_candidate: dict[str, set[tuple[str | None, str]]] = {}
    for rec in records:
        cid = str(rec["candidate_id"])
        by_candidate.setdefault(cid, set()).add((record_run_id(rec), str(rec["input_id"])))
    return {cid: len(identities) for cid, identities in by_candidate.items()}


def count_candidate_run_input_ids(records: list[dict[str, Any]]) -> dict[tuple[str, str | None], int]:
    """Count distinct input_id values per (candidate_id, run_id) across a record set."""
    by_pair: dict[tuple[str, str | None], set[str]] = {}
    for rec in records:
        key = (str(rec["candidate_id"]), record_run_id(rec))
        by_pair.setdefault(key, set()).add(str(rec["input_id"]))
    return {key: len(input_ids) for key, input_ids in by_pair.items()}


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
    candidate_run_counts: dict[str, int] | None = None,
    candidate_run_input_counts: dict[tuple[str, str | None], int] | None = None,
) -> dict[str, Any]:
    """Extract per-run/clip evidence_manifest.json + index.md into output_dir outside Git.

    Performs full pre-flight validation of every record's target paths, duplicate identities,
    existing manifest bindings, and optional manifest digests BEFORE creating directories or
    writing any files so a later error never corrupts prior outputs.
    """
    out_root = ensure_output_outside_git_repo(output_dir)
    validate_output_path(out_root, out_root, allow_existing_symlink=True)

    active_extractor: FrameExtractor
    if extractor is not None:
        active_extractor = extractor
    elif mode == "metadata_only":
        active_extractor = MetadataOnlyExtractor()
    else:
        active_extractor = build_extractor(mode, backend=backend)

    run_counts = candidate_run_counts if candidate_run_counts is not None else count_candidate_runs(records)
    run_input_counts = (
        candidate_run_input_counts
        if candidate_run_input_counts is not None
        else count_candidate_run_input_ids(records)
    )

    # --- Phase 1: Pure pre-flight validation (zero writes, zero mkdir, zero extraction) ---
    used_dirs: dict[Path, tuple[str | None, str, str]] = {}
    planned: list[tuple[dict[str, Any], Path, Path, Path]] = []

    for index, rec in enumerate(records):
        cid = str(rec["candidate_id"])
        run_id = record_run_id(rec)
        input_id = str(rec["input_id"])
        identity = (run_id, input_id, cid)

        clip_slug = _clip_slug_for_id(cid, f"clip_{index:03d}")
        run_slug = _run_slug_for_record(rec)
        raw_target_dir = out_root / run_slug / clip_slug
        target_dir = validate_output_path(raw_target_dir, out_root)

        if target_dir in used_dirs and used_dirs[target_dir] != identity:
            alt_raw = out_root / f"{run_slug}_{index:03d}" / clip_slug
            target_dir = validate_output_path(alt_raw, out_root)
        elif target_dir in used_dirs:
            raise EvidenceError(
                f"duplicate record identity {identity!r} in input batch maps to the same output directory {target_dir}"
            )
        used_dirs[target_dir] = identity

        manifest_path = target_dir / "evidence_manifest.json"
        index_path = target_dir / "index.md"
        validate_output_path(target_dir / "frames", out_root)
        validate_output_path(manifest_path, out_root)
        validate_output_path(index_path, out_root)
        _check_existing_manifest_identity(
            manifest_path,
            run_id=run_id,
            input_id=input_id,
            candidate_id=cid,
        )
        # Validate manifest digest conflicts before touching disk.
        _bind_manifests(
            rec,
            subvideo_manifest=subvideo_manifest,
            roi_manifest=roi_manifest,
        )
        planned.append((rec, target_dir, manifest_path, index_path))

    run_index_path = out_root / "run_index.json"
    validate_output_path(run_index_path, out_root)

    # --- Phase 2: Execution and atomic writes ---
    out_root.mkdir(parents=True, exist_ok=True)
    digest_cache: dict[Path, str | None] = {}
    entries: list[dict[str, Any]] = []

    for rec, target_dir, manifest_path, index_path in planned:
        cid = str(rec["candidate_id"])
        run_id = record_run_id(rec)

        target_dir.mkdir(parents=True, exist_ok=True)
        validate_output_path(target_dir, out_root)

        manifest = build_evidence_manifest(
            rec,
            target_dir=target_dir,
            output_root=out_root,
            extractor=active_extractor,
            mode=mode,
            subvideo_manifest=subvideo_manifest,
            roi_manifest=roi_manifest,
            media_root=media_root,
            l3_frames_dir=l3_frames_dir,
            input_records_dir=input_records_dir,
            allow_run_only_l3_fallback=(run_input_counts.get((cid, run_id), 1) <= 1),
            allow_unscoped_l3_fallback=(run_counts.get(cid, 1) <= 1),
            digest_cache=digest_cache,
        )

        _atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            output_root=out_root,
        )
        _atomic_write_text(
            index_path,
            render_index_markdown(manifest),
            output_root=out_root,
        )

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
    _atomic_write_text(
        run_index_path,
        json.dumps(run_index, ensure_ascii=False, indent=2) + "\n",
        output_root=out_root,
    )
    return run_index
