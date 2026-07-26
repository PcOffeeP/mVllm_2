from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_review_routing import (
    EXISTING_DISPOSITION,
    HISTORICAL_DISPOSITION,
    MANUAL_DISPOSITION,
    MANUAL_SELECTION_SCHEMA_VERSION,
    ROUTING_POLICY_VERSION,
    ROUTING_SCHEMA_VERSION,
    ReviewRoutingError,
    load_manual_candidate_ids,
    route_review_candidates,
    semantic_window_role,
)


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": (
            "韧性断裂" if state in {"发生断裂", "已断裂"} else None
        ),
        "fracture_site": (
            "inside_gauge" if state in {"发生断裂", "已断裂"} else None
        ),
        "special_case": None,
    }


def _candidate(
    candidate_id: str = "video_0001_v41exp_transition_f000010-000020",
    *,
    source: str = "video_0001",
    role: str | None = "transition",
    state: str = "发生断裂",
) -> dict[str, object]:
    result = {
        "candidate_id": candidate_id,
        "source_video": source,
        "candidate_v4_labels": _labels(state),
    }
    if role is not None:
        result["window_role"] = role
    return result


def _previous(
    clip_id: str = "video_0001_v3_transition_f000010-000020",
    *,
    source: str = "video_0001",
    status: str = "approved",
    state: str = "发生断裂",
) -> dict[str, object]:
    return {
        "clip_id": clip_id,
        "source_video": source,
        "review_status": status,
        "effective_labels": _labels(state) if status in {"approved", "corrected"} else None,
    }


def test_semantic_window_role_normalizes_current_and_historical_ids() -> None:
    assert semantic_window_role(_candidate()) == "transition"
    assert (
        semantic_window_role("video_0001_v41exp_post_event_f000020-000030")
        == "post_event"
    )
    assert semantic_window_role("video_0001_v3_post_f000020-000030") == "post_event"
    assert semantic_window_role("unknown") is None


def test_current_human_decision_has_highest_priority() -> None:
    candidate = _candidate()
    current = {
        candidate["candidate_id"]: {
            "clip_id": candidate["candidate_id"],
            "effective_labels": _labels("已断裂"),
        }
    }
    routed = route_review_candidates(
        [candidate],
        [_previous(status="corrected", state="已断裂")],
        current,
    )

    assert routed[0]["disposition"] == EXISTING_DISPOSITION
    assert routed[0]["labels"] == _labels("已断裂")


def test_missing_history_routes_to_manual_review() -> None:
    routed = route_review_candidates([_candidate()], [])

    assert routed[0]["disposition"] == MANUAL_DISPOSITION
    assert routed[0]["reason"] == "no_previous_source_history"


@pytest.mark.parametrize("status", ["corrected", "dropped", "needs_regenerate"])
def test_any_non_approved_history_routes_the_whole_source_to_manual(
    status: str,
) -> None:
    previous = [
        _previous(),
        _previous(
            "video_0001_v3_post_f000030-000040",
            status=status,
            state="已断裂",
        ),
    ]

    routed = route_review_candidates([_candidate()], previous)

    assert routed[0]["disposition"] == MANUAL_DISPOSITION
    assert routed[0]["reason"] == "previous_source_has_non_approved_status"


def test_unknown_role_routes_to_manual_review() -> None:
    routed = route_review_candidates(
        [_candidate(candidate_id="clip-without-role", role=None)],
        [_previous()],
    )

    assert routed[0]["disposition"] == MANUAL_DISPOSITION
    assert routed[0]["reason"] == "unknown_semantic_window_role"


def test_non_unique_role_history_routes_to_manual_review() -> None:
    previous = [
        _previous(),
        _previous(
            "video_0001_v3_transition_f000030-000040",
            state="已断裂",
        ),
    ]

    routed = route_review_candidates([_candidate()], previous)

    assert routed[0]["disposition"] == MANUAL_DISPOSITION
    assert routed[0]["reason"] == "no_unique_role_consensus"


def test_hint_disagreement_routes_to_manual_review() -> None:
    routed = route_review_candidates(
        [_candidate(state="已断裂")],
        [_previous(state="发生断裂")],
    )

    assert routed[0]["disposition"] == MANUAL_DISPOSITION
    assert (
        routed[0]["reason"]
        == "historical_consensus_disagrees_with_current_hint"
    )


def test_approved_role_consensus_is_carried_forward() -> None:
    previous = [
        _previous(),
        _previous("video_0001_v3_transition_f000030-000040"),
        _previous(
            "video_0001_v3_post_f000050-000060",
            state="已断裂",
        ),
    ]

    routed = route_review_candidates([_candidate()], previous)

    assert routed[0]["disposition"] == HISTORICAL_DISPOSITION
    assert routed[0]["labels"] == _labels("发生断裂")
    assert len(routed[0]["historical_reference_ids"]) == 2


def test_manual_selection_loader_rejects_drift(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    queue.write_text("{}\n", encoding="utf-8")
    selection = {
        "schema_version": MANUAL_SELECTION_SCHEMA_VERSION,
        "routing_id": "history-review-route-test",
        "queue_id": "queue-test",
        "queue_sha256": sha256_file(queue),
        "candidate_count": 1,
        "candidate_ids_sha256": (
            "f50c13c2698d6bb9b37cd645878c43109cdb7087d0dccf820aa97e41f88c78aa"
        ),
        "candidate_ids": ["clip-1"],
    }
    selection_path = tmp_path / "manual_candidate_ids.json"
    selection_path.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "policy_version": ROUTING_POLICY_VERSION,
        "routing_id": "history-review-route-test",
        "source_queue": {
            "queue_id": "queue-test",
            "sha256": sha256_file(queue),
        },
        "artifacts": {
            "manual_candidate_ids.json": sha256_file(selection_path),
        },
    }
    manifest_path = tmp_path / "routing_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReviewRoutingError, match="摘要不一致"):
        load_manual_candidate_ids(manifest_path, queue_path=queue)
