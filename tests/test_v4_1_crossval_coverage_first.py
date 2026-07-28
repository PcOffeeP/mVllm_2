import pytest

from finetune.build_v4_1_crossval_coverage_first import build_fold, freeze_source_folds


def sample():
    states = ("未断裂", "临界未断裂", "发生断裂", "已断裂", "无法判断")
    return [
        {
            "candidate_id": f"c{i}",
            "source_video": f"s{i // 2}",
            "effective_frame_signature": f"sig{i}",
            "labels": {"clip_state": states[i % len(states)]},
        }
        for i in range(18)
    ]


def test_source_folds_cover_once_and_are_disjoint():
    folds = freeze_source_folds(sample())
    assert set.union(*folds.values()) == {f"s{i}" for i in range(9)}
    assert not (folds[0] & folds[1] or folds[0] & folds[2] or folds[1] & folds[2])


def test_fold_sampling_is_reproducible_and_isolated():
    a = build_fold(sample(), 1, 3407, rows=30)
    b = build_fold(sample(), 1, 3407, rows=30)
    assert a["sampling_manifest"] == b["sampling_manifest"]
    assert {x["source_video"] for x in a["train"]}.isdisjoint({x["source_video"] for x in a["validation"]})


def test_existing_fold0_is_preserved_and_remaining_sources_cover_once():
    fixed = {"s0", "s3", "s8"}
    folds = freeze_source_folds(sample(), fold0_validation_sources=fixed)
    assert folds[0] == fixed
    assert set.union(*folds.values()) == {f"s{i}" for i in range(9)}
    assert not (folds[0] & folds[1] or folds[0] & folds[2] or folds[1] & folds[2])


def test_capacity_redistribution_keeps_caps_and_unique_coverage():
    built = build_fold(
        sample(),
        1,
        3407,
        rows=24,
        fold0_validation_sources={"s0", "s1", "s2"},
    )
    manifest = built["sampling_manifest"]
    assert len(built["multiset"]) == 24
    assert {x["candidate_id"] for x in built["train"]}.issubset(
        {x["candidate_id"] for x in built["multiset"]}
    )
    assert manifest["max_source_count"] <= manifest["source_count_cap"]
    assert manifest["max_signature_count"] <= manifest["signature_count_cap"]


def test_legacy_non_contract_state_is_rejected():
    candidates = sample()
    candidates[0]["labels"]["clip_state"] = "断裂中"
    with pytest.raises(ValueError, match="unsupported clip_state"):
        build_fold(candidates, 1, 3407, rows=24)
