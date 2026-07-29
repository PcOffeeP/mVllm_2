#!/usr/bin/env python3
"""Run, resume, or promote an isolated V4.1 data rebuild."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.current_data import (  # noqa: E402
    current_data_context,
    data_context_for_root,
)
from pipeline.data_rebuild import (  # noqa: E402
    DataRebuildError,
    append_jsonl,
    build_promotion_manifest,
    initialize_state,
    has_completed_stage_record,
    load_json_object,
    promote,
    rebuild_paths,
    tree_inventory,
    update_state,
)
from pipeline.roi_manifest import (  # noqa: E402
    build_roi_manifest_bundle,
    write_roi_manifest_bundle,
)
from pipeline.roi_media import (  # noqa: E402
    load_generation_plan,
    materialize_plan,
    require_tools as require_roi_tools,
)
from pipeline.source_bootstrap import (  # noqa: E402
    DEFAULT_EXPECTED_COUNT,
    SourceBootstrapError,
    build_source_snapshot,
    current_source_fingerprint,
    materialize_source_snapshot,
    sha256_file,
)
from pipeline.v3_candidate_plan import (  # noqa: E402
    build_candidate_plan,
    load_plan_inputs,
    materialize_candidate_plan,
)
from pipeline.v4_1_review_workflow import (  # noqa: E402
    build_v4_1_review_queue,
    save_v4_1_review_queue,
)
from pipeline.v4_1_training_release import (  # noqa: E402
    build_v4_1_training_release,
)

DEFAULT_REVIEW_REFERENCE_ID = "review-ref-7cd2e73a1cd1"
DEFAULT_MODEL = PROJECT_ROOT / "models/minicpmv4_5"


def _record_stage(
    run_root: Path,
    state: dict[str, Any],
    next_state: str,
    *,
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance a fresh run or revalidate a completed stage during resume."""
    record = {
        "schema_version": "tensile-v4.1-stage-completion/v1",
        "stage": next_state,
        "resulting_state": next_state,
        "git_commit": state.get("git_commit"),
        "runtime_identity": state.get("runtime_identity"),
        "inputs": {
            "source_identity": state.get("source_identity"),
        },
        "outputs": dict(artifacts or {}),
    }
    append_jsonl(
        Path(run_root) / "control/commands.jsonl",
        {**record, "record_status": "intent"},
    )
    updated = update_state(
        run_root,
        state,
        next_state,
        artifacts=artifacts,
        allow_completed=True,
    )
    append_jsonl(
        Path(run_root) / "control/commands.jsonl",
        {
            **record,
            "record_status": "completed",
            "resulting_state": updated["state"],
        },
    )
    return updated


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DataRebuildError("无法读取 Git commit identity")
    return result.stdout.strip()


def _tool_version(command: str) -> str:
    result = subprocess.run(
        [command, "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise DataRebuildError(f"无法读取 {command} 版本")
    return result.stdout.splitlines()[0].strip()


def _project_path(value: Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def _runtime_identity(args: argparse.Namespace) -> dict[str, Any]:
    dependency_files = [
        path
        for path in (
            PROJECT_ROOT / "pyproject.toml",
            PROJECT_ROOT / "uv.lock",
        )
        if path.is_file()
    ]
    dependency_hashes = {
        path.name: sha256_file(path) for path in dependency_files
    }
    return {
        "command": {
            "source_data_root": str(_project_path(args.source_data_root)),
            "run_root": str(_project_path(args.run_root)),
            "roi_mode": args.roi_mode,
            "review_mode": args.review_mode,
            "review_reference_id": args.review_reference_id,
            "model": str(_project_path(args.model)),
            "workers": args.workers,
            "expected_count": args.expected_count,
        },
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "dependency_hashes": dependency_hashes,
        "dependency_summary_sha256": hashlib.sha256(
            json.dumps(
                dependency_hashes,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "ffmpeg_version": _tool_version("ffmpeg"),
        "ffprobe_version": _tool_version("ffprobe"),
    }


def _copy_file(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != sha256_file(source):
            raise DataRebuildError(f"staging 文件已存在且内容不同: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != sha256_file(source):
            raise DataRebuildError(f"复制后 hash 不一致: {source}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_tree(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    expected = tree_inventory(source)["tree_sha256"]
    if destination.exists():
        if tree_inventory(destination)["tree_sha256"] != expected:
            raise DataRebuildError(f"staging 目录已存在且内容不同: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(source, temporary, symlinks=False)
    try:
        if tree_inventory(temporary)["tree_sha256"] != expected:
            raise DataRebuildError(f"复制后 tree hash 不一致: {source}")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _space_guard(run_root: Path, required_bytes: int) -> None:
    run_root.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(run_root.parent).free
    minimum = int(required_bytes * 1.2)
    if free < minimum:
        raise DataRebuildError(
            f"staging 空间不足: free={free}, required_with_margin={minimum}"
        )


def _artifact_bytes(path: Path) -> int | None:
    path = Path(path)
    if not path.exists():
        return None
    if path.is_dir():
        return int(tree_inventory(path)["total_bytes"])
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise DataRebuildError(f"空间估算输入不是物理制品: {path}")
    return path.stat().st_size


def _estimate_candidate_media_bytes(
    plan: dict[str, Any],
    inputs: dict[str, Any],
    roi_media: Path,
) -> int:
    """Conservatively estimate CRF video, eight JPEG frames, metadata and temp."""
    candidates = (
        list(plan["development_candidates"])
        + list(plan["test_candidate_audit"])
    )
    per_candidate: list[int] = []
    for candidate in candidates:
        video_id = str(candidate["source_video"])
        record = inputs["records"][video_id]
        source_video = roi_media / "videos" / f"{video_id}.mp4"
        source_duration = float(record["duration"])
        if not source_video.is_file() or source_duration <= 0:
            raise DataRebuildError(
                f"无法估算 candidate media: {source_video}"
            )
        encoded_video = int(
            source_video.stat().st_size
            * float(candidate["duration"])
            / source_duration
        )
        raw_frame_upper_bound = (
            int(record["width"])
            * int(record["height"])
            * 3
            * 8
        )
        metadata_allowance = 64 * 1024
        per_candidate.append(
            encoded_video + raw_frame_upper_bound + metadata_allowance
        )
    final_bytes = sum(per_candidate)
    temporary_peak = max(per_candidate, default=0)
    return final_bytes + temporary_peak


def _candidate_space_requirement(
    existing_parts: tuple[int | None, ...],
    clean_estimate: int,
) -> int:
    existing_total = (
        sum(int(value) for value in existing_parts)
        if all(value is not None for value in existing_parts)
        else 0
    )
    return max(clean_estimate, existing_total)


def _find_frozen_decisions(root: Path) -> Path | None:
    candidates = sorted(Path(root).glob("*/decisions.json"))
    if not candidates:
        return None
    if len(candidates) != 1:
        raise DataRebuildError(f"冻结 review decisions 不唯一: {root}")
    return candidates[0]


def _check_current_chain(current: Any) -> dict[str, Any]:
    expected_inputs = {
        "decisions_sha256": sha256_file(
            current.metadata / "roi_decisions.json"
        ),
        "video_metadata_sha256": sha256_file(
            current.metadata / "video_meta.json"
        ),
        "test_manifest_sha256": sha256_file(current.splits / "test.json"),
    }
    matches: list[tuple[Path, dict[str, Any]]] = []
    for manifest_path in sorted(
        (current.metadata / "v3/roi_manifests").glob("*/manifest.json")
    ):
        manifest = load_json_object(manifest_path, "current ROI manifest")
        inputs = manifest.get("inputs")
        if isinstance(inputs, dict) and all(
            inputs.get(key) == value
            for key, value in expected_inputs.items()
        ):
            matches.append((manifest_path.parent, manifest))
    if len(matches) != 1:
        raise DataRebuildError(
            f"当前 ROI manifest 身份匹配数必须为 1，实际为 {len(matches)}"
        )
    existing_roi, existing_manifest = matches[0]
    roi_id = str(existing_manifest["roi_manifest_id"])
    roi_plan = load_generation_plan(
        existing_roi,
        current.metadata / "video_meta.json",
        current.root,
    )
    roi_media = current.roi_videos / str(roi_plan["media_id"])
    candidate_inputs = load_plan_inputs(
        roi_media,
        current.metadata
        / "v3/review_reference"
        / DEFAULT_REVIEW_REFERENCE_ID,
        PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v3.json",
        data_root=current.root,
    )
    candidate_plan = build_candidate_plan(candidate_inputs)
    return {
        "roi_manifest_id": roi_id,
        "roi_media_id": roi_plan["media_id"],
        "candidate_plan_id": candidate_plan["plan_id"],
        "development_candidate_count": len(
            candidate_plan["development_candidates"]
        ),
    }


def _source_stage(
    current: Any,
    rebuild: Any,
    run_root: Path,
    *,
    expected_count: int,
    roi_mode: str,
    review_mode: str,
    runtime_identity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    bundle = build_source_snapshot(
        current,
        rebuild,
        expected_count=expected_count,
    )
    fingerprint = current_source_fingerprint(
        current,
        expected_count=expected_count,
    )
    source_bytes = sum(
        int(item["size_bytes"]) for item in fingerprint["videos"]
    )
    _space_guard(run_root, source_bytes)
    state = initialize_state(
        PROJECT_ROOT,
        run_root,
        roi_mode=roi_mode,
        review_mode=review_mode,
        source_identity={
            "source_snapshot_id": bundle["snapshot_id"],
            "identity_sha256": bundle["identity_sha256"],
            "fingerprint": fingerprint,
        },
        git_commit=_git_commit(),
        runtime_identity=runtime_identity,
    )
    state = _record_stage(
        run_root,
        state,
        "source_validated",
        artifacts={
            "source_snapshot_id": bundle["snapshot_id"],
            "source_validation": bundle["validation"],
        },
    )
    snapshot = (
        rebuild.metadata
        / "source_snapshots"
        / str(bundle["snapshot_id"])
    )
    snapshot = materialize_source_snapshot(bundle)
    state = _record_stage(
        run_root,
        state,
        "source_snapshotted",
        artifacts={
            "source_snapshot_id": bundle["snapshot_id"],
            "source_snapshot": str(snapshot),
            "source_snapshot_tree_sha256": tree_inventory(snapshot)[
                "tree_sha256"
            ],
        },
    )
    return state, bundle, snapshot


def _run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    current = current_data_context(PROJECT_ROOT)
    rebuild, run_root = rebuild_paths(PROJECT_ROOT, args.run_root)
    existing_state_path = run_root / "control/rebuild.json"
    if existing_state_path.exists():
        existing_state = load_json_object(
            existing_state_path,
            "rebuild state",
        )
        existing_name = str(existing_state.get("state"))
        if existing_name == "ready_to_promote" and has_completed_stage_record(
            run_root,
            existing_name,
        ):
            return existing_state
        if existing_name == "promoted":
            if has_completed_stage_record(run_root, "promoted"):
                return existing_state
            raise DataRebuildError(
                "promoted state 缺少完成 provenance；请重跑 promote 恢复"
            )
    state, source_bundle, snapshot = _source_stage(
        current,
        rebuild,
        run_root,
        expected_count=args.expected_count,
        roi_mode=args.roi_mode,
        review_mode=args.review_mode,
        runtime_identity=_runtime_identity(args),
    )
    video_meta = snapshot / "video_meta.json"
    test_split = snapshot / "splits/test.json"

    staged_decisions = rebuild.metadata / "roi_decisions.json"
    if args.roi_mode == "reuse":
        _copy_file(current.metadata / "roi_decisions.json", staged_decisions)
    elif not staged_decisions.exists():
        return _record_stage(
            run_root,
            state,
            "waiting_for_roi_review",
            artifacts={
                "roi_review_command": (
                    "streamlit run pipeline/scripts/roi_annotation_app.py -- "
                    f"--data-root {rebuild.root} --metadata {video_meta} "
                    f"--output {staged_decisions}"
                )
            },
        )

    roi_bundle = build_roi_manifest_bundle(
        decisions_path=staged_decisions,
        video_metadata_path=video_meta,
        test_manifest_path=test_split,
        project_root=rebuild.root,
    )
    roi_manifest, _ = write_roi_manifest_bundle(
        rebuild.metadata / "v3/roi_manifests",
        roi_bundle,
    )
    state = _record_stage(
        run_root,
        state,
        "roi_validated",
        artifacts={
            "roi_manifest": str(roi_manifest),
            "roi_manifest_tree_sha256": tree_inventory(roi_manifest)[
                "tree_sha256"
            ],
        },
    )
    roi_plan = load_generation_plan(
        roi_manifest,
        video_meta,
        rebuild.root,
    )
    source_bytes = sum(
        int(item["size_bytes"]) for item in source_bundle["inventory"]["videos"]
    )
    existing_roi_bytes = _artifact_bytes(
        current.roi_videos / str(roi_plan["media_id"])
    )
    reference_source = (
        current.metadata
        / "v3/review_reference"
        / args.review_reference_id
    )
    reference_bytes = _artifact_bytes(reference_source)
    if reference_bytes is None:
        raise DataRebuildError(f"review reference 不存在: {reference_source}")
    _space_guard(
        run_root,
        (existing_roi_bytes or source_bytes) + reference_bytes,
    )
    require_roi_tools()
    roi_media = materialize_plan(
        roi_plan,
        rebuild.roi_videos,
        workers=args.workers,
    )
    state = _record_stage(
        run_root,
        state,
        "roi_media_ready",
        artifacts={
            "roi_media": str(roi_media),
            "roi_media_tree_sha256": tree_inventory(roi_media)["tree_sha256"],
        },
    )

    reference = (
        rebuild.metadata
        / "v3/review_reference"
        / args.review_reference_id
    )
    _copy_tree(reference_source, reference)
    inputs = load_plan_inputs(
        roi_media,
        reference,
        PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v3.json",
        data_root=rebuild.root,
    )
    plan = build_candidate_plan(inputs)
    plan_dir = materialize_candidate_plan(
        plan,
        rebuild.metadata / "v3/candidate_plans",
    )

    from pipeline.preprocessing import MiniCPMVideoPreprocessor
    from pipeline.v3_candidate_media import (
        load_media_plan,
        materialize_media_plan,
    )

    processor = MiniCPMVideoPreprocessor(
        model_path_or_name=str(args.model),
        max_frames=8,
    )
    media_plan = load_media_plan(
        plan_dir,
        roi_media,
        rebuild.root,
        processor_fingerprint=processor.fingerprint(),
    )
    existing_candidate_parts = (
        _artifact_bytes(current.subvideos / plan["plan_id"]),
        _artifact_bytes(current.frames / plan["plan_id"]),
        _artifact_bytes(
            current.metadata
            / "v3/candidate_media_results"
            / str(media_plan["media_id"])
        ),
    )
    candidate_required_bytes = _candidate_space_requirement(
        existing_candidate_parts,
        _estimate_candidate_media_bytes(plan, inputs, roi_media),
    )
    _space_guard(
        run_root,
        candidate_required_bytes,
    )
    media_result = materialize_media_plan(
        media_plan,
        model_path=str(args.model),
        video_output_root=rebuild.subvideos,
        frame_output_root=rebuild.frames,
        result_root=rebuild.metadata / "v3/candidate_media_results",
        preprocessor=processor,
    )
    state = _record_stage(
        run_root,
        state,
        "candidate_media_ready",
        artifacts={
            "candidate_plan": str(plan_dir),
            "candidate_plan_tree_sha256": tree_inventory(plan_dir)[
                "tree_sha256"
            ],
            "candidate_media": str(media_result),
            "candidate_media_tree_sha256": tree_inventory(media_result)[
                "tree_sha256"
            ],
        },
    )

    queue = build_v4_1_review_queue(
        materialized_path=media_result / "development_materialized.json",
        manifest_path=media_result / "manifest.json",
        project_root=rebuild.root,
        contract_path=PROJECT_ROOT
        / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    queue_path = (
        rebuild.metadata
        / "v4_1/review_queues"
        / str(queue["queue_id"])
        / "review_queue.json"
    )
    save_v4_1_review_queue(queue_path, queue)
    staged_review_root = (
        rebuild.metadata
        / "v4_1/review_decisions"
        / str(queue["queue_id"])
    )
    if args.review_mode == "reuse":
        current_review_root = (
            current.metadata
            / "v4_1/review_decisions"
            / str(queue["queue_id"])
        )
        existing = _find_frozen_decisions(current_review_root)
        if existing is None:
            raise DataRebuildError(
                "review reuse 身份不匹配；当前数据根没有同 queue_id 冻结决定"
            )
        _copy_tree(existing.parent, staged_review_root / existing.parent.name)
    decisions = _find_frozen_decisions(staged_review_root)
    if decisions is None:
        state = _record_stage(
            run_root,
            state,
            "waiting_for_candidate_review",
            artifacts={
                "review_queue": str(queue_path),
                "review_command": (
                    "streamlit run pipeline/scripts/review_v4_candidates_app.py -- "
                    f"--data-root {rebuild.root} --queue {queue_path}"
                ),
            },
        )
        return state
    _space_guard(
        run_root,
        int(tree_inventory(media_result)["total_bytes"]),
    )
    state = _record_stage(
        run_root,
        state,
        "review_validated",
        artifacts={
            "review_queue": str(queue_path),
            "review_decisions": str(decisions),
            "review_queue_sha256": sha256_file(queue_path),
            "review_decisions_tree_sha256": tree_inventory(decisions.parent)[
                "tree_sha256"
            ],
        },
    )

    release_dir, manifest = build_v4_1_training_release(
        project_root=rebuild.root,
        materialized_path=media_result / "development_materialized.json",
        media_manifest_path=media_result / "manifest.json",
        queue_path=queue_path,
        decisions_path=decisions,
        contract_path=PROJECT_ROOT
        / "pipeline/contracts/tensile_vlm_v4_1.json",
        splits_dir=snapshot / "splits",
        releases_dir=rebuild.training_releases,
        source_snapshot_id=str(source_bundle["snapshot_id"]),
    )
    state = _record_stage(
        run_root,
        state,
        "release_validated",
        artifacts={
            "release": str(release_dir),
            "release_id": manifest["release_id"],
            "release_tree_sha256": tree_inventory(release_dir)["tree_sha256"],
        },
    )

    plan_id = plan["plan_id"]
    entries = [
        (
            "source_snapshot",
            snapshot,
            current.metadata / "source_snapshots" / snapshot.name,
        ),
        (
            "roi_manifest",
            roi_manifest,
            current.metadata / "v3/roi_manifests" / roi_manifest.name,
        ),
        (
            "roi_media",
            roi_media,
            current.roi_videos / roi_media.name,
        ),
        (
            "candidate_plan",
            plan_dir,
            current.metadata / "v3/candidate_plans" / plan_dir.name,
        ),
        (
            "candidate_videos",
            rebuild.subvideos / plan_id,
            current.subvideos / plan_id,
        ),
        (
            "candidate_frames",
            rebuild.frames / plan_id,
            current.frames / plan_id,
        ),
        (
            "candidate_media",
            media_result,
            current.metadata
            / "v3/candidate_media_results"
            / media_result.name,
        ),
        (
            "review_queue",
            queue_path.parent,
            current.metadata
            / "v4_1/review_queues"
            / queue_path.parent.name,
        ),
        (
            "review_decisions",
            decisions.parent,
            current.metadata
            / "v4_1/review_decisions"
            / queue_path.parent.name
            / decisions.parent.name,
        ),
        (
            "release",
            release_dir,
            current.training_releases / release_dir.name,
        ),
    ]
    build_promotion_manifest(
        PROJECT_ROOT,
        run_root,
        entries,
        release_name="release",
        source_fingerprint=state["source_identity"]["fingerprint"],
        git_commit=_git_commit(),
    )
    return _record_stage(run_root, state, "ready_to_promote")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    run = subparsers.add_parser("run")
    run.add_argument("--source-data-root", type=Path, default=PROJECT_ROOT / "workspace/data")
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--roi-mode", choices=("reuse", "review"), required=True)
    run.add_argument("--review-mode", choices=("reuse", "review"), required=True)
    run.add_argument("--review-reference-id", default=DEFAULT_REVIEW_REFERENCE_ID)
    run.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    run.add_argument("--workers", type=int, default=2)
    run.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    run.add_argument("--check-only", action="store_true")

    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--run-root", type=Path, required=True)
    promote_parser.add_argument(
        "--expected-count",
        type=int,
        default=DEFAULT_EXPECTED_COUNT,
    )
    return parser


def main() -> int:
    raw = sys.argv[1:]
    if raw and raw[0].startswith("-") and raw[0] != "--help":
        raw.insert(0, "run")
    args = build_parser().parse_args(raw)
    try:
        if args.command == "promote":
            current = current_data_context(PROJECT_ROOT)
            result = promote(
                PROJECT_ROOT,
                args.run_root,
                expected_git_commit=_git_commit,
                current_source_fingerprint=lambda: current_source_fingerprint(
                    current, expected_count=args.expected_count
                ),
            )
        elif args.command == "run":
            current = current_data_context(PROJECT_ROOT)
            args.model = _project_path(args.model)
            if _project_path(args.source_data_root) != current.root:
                raise DataRebuildError(
                    "source-data-root 必须是当前 workspace/data"
                )
            if args.check_only:
                rebuild = data_context_for_root(
                    PROJECT_ROOT,
                    Path(args.run_root) / "data",
                )
                bundle = build_source_snapshot(
                    current,
                    rebuild,
                    expected_count=args.expected_count,
                )
                result = {
                    "status": "source_validated",
                    "check_only": True,
                    "source_snapshot_id": bundle["snapshot_id"],
                    "current_chain": _check_current_chain(current),
                }
            else:
                result = _run_pipeline(args)
        else:
            build_parser().print_help()
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (
        DataRebuildError,
        SourceBootstrapError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
