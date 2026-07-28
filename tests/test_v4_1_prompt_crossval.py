from __future__ import annotations

import json
from pathlib import Path

from finetune import build_v4_1_prompt_crossval_dataset as crossval

ROOT = Path(__file__).resolve().parents[1]
PROMPT_REVISION = ROOT / "pipeline/prompt_registry/v4.1-concise-evidence-json-v2"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _row(video: str, state: str) -> dict[str, object]:
    target = {
        "clip_state": state,
        "fracture_mechanism": None if state == "未断裂" else "韧性断裂",
        "fracture_site": None if state == "未断裂" else "inside_gauge",
        "special_case": None,
    }
    return {
        "videos": [video],
        "messages": [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "<video>\nold user"},
            {
                "role": "assistant",
                "content": json.dumps(target, ensure_ascii=False),
            },
        ],
    }


def _release(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    candidates = []
    rows = []
    states = ("未断裂", "临界未断裂", "发生断裂")
    for index in range(9):
        video = f"source/videos/{index}.mp4"
        rows.append(_row(video, states[index % len(states)]))
        candidates.append(
            {
                "candidate_id": f"candidate-{index}",
                "video_path": video,
                "source_video": f"source-{index}",
                "effective_frame_signature": f"signature-{index}",
                "labels": {
                    "clip_state": states[index % len(states)],
                },
            }
        )
    _write_json(
        root / "manifest/release_manifest.json",
        {
            "release_id": "release-test",
            "immutable": True,
        },
    )
    _write_json(
        root / "metadata/training_candidates.json",
        {"candidates": candidates},
    )
    validation_indexes = {
        0: {0, 1, 2},
        1: {3, 4, 5},
        2: {6, 7, 8},
    }
    for fold in crossval.FOLDS:
        validation = validation_indexes[fold]
        _write_json(
            root / f"datasets/train/fold_{fold}.json",
            [row for index, row in enumerate(rows) if index not in validation],
        )
        _write_json(
            root / f"datasets/validation/fold_{fold}.json",
            [row for index, row in enumerate(rows) if index in validation],
        )
    return root


def test_builds_all_frozen_folds_without_source_leakage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(crossval, "ROWS_PER_FOLD", 12)
    output, summary = crossval.build_prompt_crossval_dataset(
        release_dir=_release(tmp_path),
        prompt_revision_dir=PROMPT_REVISION,
        output_root=tmp_path / "workspace/runs",
        experiment_id=crossval.DEFAULT_EXPERIMENT_ID,
        project_root=tmp_path,
    )

    assert summary["system_prompt_chars"] <= 500
    assert [item["source_overlap_count"] for item in summary["folds"]] == [0, 0, 0]
    assert [item["train_rows"] for item in summary["folds"]] == [12, 12, 12]
    assert [item["validation_rows"] for item in summary["folds"]] == [3, 3, 3]
    registry = json.loads((output / "dataset_info.json").read_text(encoding="utf-8"))
    assert len(registry) == 6
    for fold in crossval.FOLDS:
        train = json.loads(
            (output / f"datasets/train/fold_{fold}.json").read_text(encoding="utf-8")
        )
        assert len(train) == 12
        assert all(
            row["messages"][0]["content"].startswith("仅依据当前视频")
            and '禁止字符串 "null"' in row["messages"][0]["content"]
            for row in train
        )


def test_validate_only_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(crossval, "ROWS_PER_FOLD", 12)
    kwargs = {
        "release_dir": _release(tmp_path),
        "prompt_revision_dir": PROMPT_REVISION,
        "output_root": tmp_path / "workspace/runs",
        "experiment_id": crossval.DEFAULT_EXPERIMENT_ID,
        "project_root": tmp_path,
    }
    first_output, first = crossval.build_prompt_crossval_dataset(**kwargs)
    second_output, second = crossval.build_prompt_crossval_dataset(
        **kwargs,
        validate_only=True,
    )
    assert second_output == first_output
    assert second == first
