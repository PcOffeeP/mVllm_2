from finetune.build_v4_1_crossval_coverage_first import build_fold, freeze_source_folds


def sample():
    return [{"candidate_id": f"c{i}", "source_video": f"s{i // 2}", "labels": {"clip_state": "发生断裂" if i % 2 else "未断裂"}} for i in range(18)]


def test_source_folds_cover_once_and_are_disjoint():
    folds = freeze_source_folds(sample())
    assert set.union(*folds.values()) == {f"s{i}" for i in range(9)}
    assert not (folds[0] & folds[1] or folds[0] & folds[2] or folds[1] & folds[2])


def test_fold_sampling_is_reproducible_and_isolated():
    a = build_fold(sample(), 1, 3407, rows=30)
    b = build_fold(sample(), 1, 3407, rows=30)
    assert a["sampling_manifest"] == b["sampling_manifest"]
    assert {x["source_video"] for x in a["train"]}.isdisjoint({x["source_video"] for x in a["validation"]})
