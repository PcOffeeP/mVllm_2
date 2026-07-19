import json
from pathlib import Path

import pytest

from finetune.prepare_full_training_dataset import (
    FULL_DATASET_NAME,
    FullDatasetError,
    build_full_dataset,
    write_full_dataset,
)


def _write_release(root: Path, *, conflict: bool = False) -> Path:
    release = root / "release"
    manifest = {
        "release_id": "v-test",
        "status": "training_ready",
        "immutable": True,
        "quality": {"error_count": 0},
    }
    manifest_path = release / "manifest" / "release_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rows = {
        "train/fold_0.json": [
            {"messages": [{"role": "assistant", "content": "a"}], "videos": ["a.mp4"]},
            {"messages": [{"role": "assistant", "content": "b"}], "videos": ["b.mp4"]},
        ],
        "train/fold_1.json": [
            {"messages": [{"role": "assistant", "content": "a"}], "videos": ["a.mp4"]}
        ],
        "train/fold_2.json": [
            {"messages": [{"role": "assistant", "content": "a"}], "videos": ["a.mp4"]}
        ],
        "validation/fold_0.json": [
            {
                "messages": [
                    {"role": "assistant", "content": "changed" if conflict else "a"}
                ],
                "videos": ["a.mp4"],
            }
        ],
        "validation/fold_1.json": [
            {"messages": [{"role": "assistant", "content": "c"}], "videos": ["c.mp4"]}
        ],
        "validation/fold_2.json": [
            {"messages": [{"role": "assistant", "content": "d"}], "videos": ["d.mp4"]}
        ],
    }
    for relative, payload in rows.items():
        path = release / "datasets" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return release


def test_build_full_dataset_deduplicates_and_records_provenance(tmp_path: Path):
    release = _write_release(tmp_path)

    rows, provenance = build_full_dataset(release)

    assert [row["videos"] for row in rows] == [
        ["a.mp4"],
        ["b.mp4"],
        ["c.mp4"],
        ["d.mp4"],
    ]
    assert provenance["release_id"] == "v-test"
    assert provenance["source_row_count"] == 7
    assert provenance["unique_row_count"] == 4
    assert provenance["duplicate_occurrence_count"] == 3
    assert provenance["occurrence_histogram"] == {"1": 3, "4": 1}
    assert len(provenance["sources"]) == 6


def test_build_full_dataset_rejects_conflicting_duplicate(tmp_path: Path):
    release = _write_release(tmp_path, conflict=True)

    with pytest.raises(FullDatasetError, match="conflicting payload"):
        build_full_dataset(release)


def test_write_refuses_release_and_existing_outputs(tmp_path: Path):
    release = _write_release(tmp_path)
    with pytest.raises(FullDatasetError, match="outside the immutable release"):
        write_full_dataset(release, release / "derived")

    output = tmp_path / "derived"
    dataset_path, dataset_info_path, provenance_path = write_full_dataset(
        release, output
    )
    assert dataset_path.is_file()
    dataset_info = json.loads(dataset_info_path.read_text(encoding="utf-8"))
    assert dataset_info[FULL_DATASET_NAME]["file_name"] == dataset_path.name
    assert dataset_info[FULL_DATASET_NAME]["columns"] == {
        "messages": "messages",
        "videos": "videos",
    }
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["output"]["dataset"]["sha256"]
    assert provenance["output"]["dataset_info"]["sha256"]
    assert provenance["output"]["dataset_info"]["dataset_name"] == FULL_DATASET_NAME

    with pytest.raises(FullDatasetError, match="refusing to overwrite"):
        write_full_dataset(release, output)
