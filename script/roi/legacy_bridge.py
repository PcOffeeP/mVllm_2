"""Current data connections for the original ROI annotation interface.

The old interface receives a display-only metadata/decision view.  Its original
whole-file JSON writer is deliberately not used: writes go through Workspace,
which updates one video and keeps current media and label-review identities.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Mapping

if __package__:
    from .core import RoiError, Workspace, geometry, source_matches
else:
    from core import RoiError, Workspace, geometry, source_matches


DISPLAY_ROI_POLICY = "1.2"


def _event_time(labels: Mapping, duration: float | None) -> float | None:
    value = labels.get("断裂时间点", labels.get("event_time"))
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0 or (duration is not None and result > duration):
        return None
    return result


class LegacyBridge:
    """Adapt the original GUI's inputs without changing its visual structure."""

    def __init__(self, work: Workspace, project_root: Path):
        self.work = work
        self.project_root = Path(project_root).resolve()
        self.metadata_path = work.labels or work.manifest_path
        self.output_path = work.decisions_path
        self.manifest: dict[str, Any] = {}
        self.videos: list[dict[str, Any]] = []
        self.decisions: dict[str, dict[str, Any]] = {}
        self._rows: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_argv(cls, argv: list[str] | None = None) -> "LegacyBridge":
        # Import lazily so this module remains usable in non-UI unit checks.
        from roi import parser, workspace

        args = parser().parse_args(argv)
        return cls(workspace(args), args.project_root)

    def refresh(self) -> dict[str, Any]:
        self.manifest = self.work.refresh()
        self._rows = {row["video_id"]: row for row in self.manifest["videos"]}
        self.videos = []
        self.decisions = {}
        for video_id, row in self._rows.items():
            source = row.get("source", {})
            media = source.get("media", {})
            labels = dict(row.get("labels", {}))
            # A failed/conflicting ID must not accidentally resolve to a file
            # that happens to share its stem and become editable in the old UI.
            path = source.get("path") or row.get("source_path")
            if not path:
                path = str(self.project_root / "__unavailable_source__" / f"{video_id}.mp4")
            self.videos.append({
                "video_id": video_id,
                "video_path": str(path),
                "type": labels.get("材料类型") or labels.get("类型") or labels.get("type") or "",
                "event_time": _event_time(labels, media.get("duration")),
                "location_canonical": labels.get("断裂位置", ""),
                "labels": labels,
                "bridge_status": row.get("status"),
                "bridge_error": row.get("reason") if row.get("status") in {"failed", "needs_verification"} else None,
                "roi_output_path": row.get("output", {}).get("path"),
            })
            view = self._decision_view(row)
            if view is not None:
                self.decisions[video_id] = view
        return {"videos": self.videos, "decisions": self.decisions,
                "manifest": self.manifest}

    @staticmethod
    def _decision_view(row: Mapping) -> dict[str, Any] | None:
        source = row.get("source")
        if not isinstance(source, Mapping):
            return None
        draft = row.get("draft")
        saved = row.get("decision")
        value = draft if isinstance(draft, Mapping) and source_matches(source, draft) else saved
        if not isinstance(value, Mapping) or not source_matches(source, value):
            return None
        view = copy.deepcopy(dict(value))
        ui = value.get("legacy_ui", {})
        if not isinstance(ui, Mapping):
            ui = {}
        # This is the old GUI's input view, never the on-disk current decision.
        # Keep actual earlier ROI review values when present; a newly recorded
        # range is not silently promoted to an approved visual review.
        view.update({key: copy.deepcopy(ui[key]) for key in (
            "review_status", "reviewer_notes", "visibility_checks", "reviewed_timestamps"
        ) if key in ui})
        view.setdefault("review_status", "needs_review")
        view.setdefault("reviewer_notes", value.get("pending_reason", ""))
        view.setdefault("visibility_checks", {})
        view.setdefault("reviewed_timestamps", [])
        view.setdefault("roi_policy_version", DISPLAY_ROI_POLICY)
        view["_bridge_display_only"] = True
        # Copied source paths/mtimes are not a content change.  The Workspace
        # already checked content identity; expose this current file's state.
        stat = source.get("stat", {})
        view["source_size_bytes"] = stat.get("size")
        view["source_mtime_ns"] = stat.get("mtime_ns")
        view["source_video_path"] = source.get("path")
        if not (isinstance(draft, Mapping) and source_matches(source, draft)):
            effective = row.get("output", {}).get("geometry", {}).get("effective_pixel_box")
            if value.get("mode") == "fixed_roi" and isinstance(effective, Mapping):
                view["pixel_box"] = dict(effective)
        return view

    def row(self, video_id: str) -> dict[str, Any]:
        if video_id not in self._rows:
            raise RoiError("视频不在当前工作列表，请刷新。")
        return self._rows[video_id]

    def save_current_decision(self, video_id: str, decision: Mapping | None = None,
                              **legacy_fields: Any) -> dict[str, Any]:
        """Save the viewed video's current box, never a legacy whole-file payload.

        The GUI must pass its freshly computed source hash.  Original ROI review
        controls are retained under ``legacy_ui`` as explicit user input, not
        converted into current source/output review approval.
        """
        if decision is not None and not isinstance(decision, Mapping):
            raise RoiError("裁剪决定必须是字段对象。")
        raw = {**dict(decision or {}), **legacy_fields}
        row = self.row(video_id)
        source = row.get("source")
        if not isinstance(source, Mapping) or row.get("source_missing"):
            raise RoiError("当前源视频不可用，不能保存裁剪决定。")
        if raw.get("source_video_id", video_id) != video_id:
            raise RoiError("裁剪决定的视频 ID 与当前选择不一致。")
        if raw.get("source_sha256") != source.get("sha256"):
            raise RoiError("裁剪决定的源摘要与当前视频不一致，请刷新。")
        width, height = source["media"]["width"], source["media"]["height"]
        supplied_resolution = raw.get("source_resolution", [raw.get("source_width", width), raw.get("source_height", height)])
        if not isinstance(supplied_resolution, (list, tuple)) or list(supplied_resolution) != [width, height]:
            raise RoiError("裁剪决定的源尺寸与当前视频不一致。")
        if raw.get("source_rotation", source["media"]["rotation"]) != source["media"]["rotation"]:
            raise RoiError("裁剪决定的源方向与当前视频不一致。")
        mode = raw.get("mode")
        box = raw.get("pixel_box_override", raw.get("pixel_box"))
        current = {"mode": mode, "pixel_box": copy.deepcopy(box) if mode == "fixed_roi" else None,
                   "source_resolution": [width, height],
                   "pending_reason": str(raw.get("reviewer_notes", raw.get("pending_reason", "")) or ""),
                   "legacy_ui": {key: copy.deepcopy(raw[key]) for key in (
                       "review_status", "reviewer_notes", "visibility_checks", "reviewed_timestamps",
                       "source_video_reference"
                   ) if key in raw}}
        geometry(current)
        self.work.save_decision(row, current)
        return self.refresh()

    def label_state(self, video_id: str) -> dict[str, Any]:
        state = self.work.label_review_state(self.row(video_id))
        # Original GUI integration uses a compact revision token.  Keep the
        # full historical record available separately, never confuse the two.
        return {**state, "review_record": state.get("revision"),
                "revision": state.get("revision_id")}

    def save_labels(self, video_id: str, values: Mapping, expected_revision: str | None,
                    *, viewed_row: Mapping | None = None) -> dict[str, Any]:
        row = viewed_row if viewed_row is not None else self.row(video_id)
        if row.get("video_id") != video_id:
            raise RoiError("标签记录的视频 ID 与当前选择不一致。")
        state = self.work.save_label_review(row, values, expected_revision=expected_revision)
        self.refresh()
        return {**state, "review_record": state.get("revision"),
                "revision": state.get("revision_id")}
