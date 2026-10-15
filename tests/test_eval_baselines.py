from __future__ import annotations

from copy import deepcopy
import json

import pytest

from finetune.eval_baselines import (
    build_majority_baseline,
    compare_paired_records,
    majority_baseline_records,
)


def labels(state="未断裂", mechanism=None, site=None):
    return {"clip_state": state, "fracture_mechanism": mechanism,
            "fracture_site": site, "special_case": None}


def record(identity, target=None, prediction=None, *, error=None):
    target = labels() if target is None else target
    return {"candidate_id": identity, "video_path": f"/frozen/{identity}.mp4",
            "source_video": "source-1", "source_group": "specimen-1", "target": target,
            "raw_output": json.dumps(prediction, ensure_ascii=False) if prediction is not None else "",
            "runtime_error": error}


def config():
    return {"media_sampling": {"max_frames": 8, "method": "uniform"},
            "prompt": {"version": "prompt-v4.1-r1", "system_prompt": "frozen"},
            "decode": {"temperature": 0, "max_new_tokens": 256},
            "scorer": "semantic-v4.1"}


def compare(base, trained, **kwargs):
    return compare_paired_records(base, trained, base_config=config(), trained_config=config(), **kwargs)


def test_majority_uses_development_joint_mode_and_freezes_provenance():
    stable = labels()
    fracture = labels("发生断裂", "韧性断裂", "inside_gauge")
    rows = [record("train-1", stable), record("train-2", stable), record("train-3", fracture)]
    before = deepcopy(rows)
    frozen = build_majority_baseline(rows, development_data_id="data-v4.1-r2", fit_split="train")
    assert frozen["prediction"] == stable
    assert frozen["method"] == "joint_label_mode"
    assert frozen["fit_split"] == "train"
    assert frozen["fit_sample_count"] == 3
    assert frozen["fit_sample_ids"] == ["train-1", "train-2", "train-3"]
    assert frozen["generalization_claim"] == "not_established_by_baseline"
    assert rows == before
    assert frozen == build_majority_baseline(list(reversed(rows)), development_data_id="data-v4.1-r2", fit_split="train")


def test_majority_tie_break_is_frozen_and_does_not_read_evaluation_targets():
    rows = [{"target": labels()}, {"target": labels("发生断裂", "脆性断裂", "grip_root")}]
    frozen = build_majority_baseline(rows, development_data_id="data-v4.1-r2", fit_split="validation")
    assert frozen["tie_break"] == "canonical_json_lexical_order"
    assert frozen == build_majority_baseline(rows[::-1], development_data_id="data-v4.1-r2", fit_split="validation")
    evaluation = [record("one", labels()), record("two", labels("已断裂"))]
    before = deepcopy(evaluation)
    predictions = majority_baseline_records(frozen, evaluation)
    assert all(row["prediction"] == frozen["prediction"] for row in predictions)
    assert all(row["baseline_kind"] == "synthetic_majority" for row in predictions)
    assert all(row["baseline_fit_overlap"] is None for row in predictions)
    assert predictions[1]["target"] == evaluation[1]["target"]
    assert evaluation == before


@pytest.mark.parametrize("split", ["test", "holdout", "", None])
def test_majority_refuses_non_development_fit_split(split):
    with pytest.raises(ValueError, match="development"):
        build_majority_baseline([{"target": labels()}], development_data_id="data-v4.1-r1", fit_split=split)


def test_majority_rejects_hidden_test_truth_and_incomplete_target():
    with pytest.raises(ValueError, match="split"):
        build_majority_baseline([{"target": labels(), "split": "test"}], development_data_id="data-v4.1-r1", fit_split="train")
    with pytest.raises(ValueError):
        build_majority_baseline([{"target": {"clip_state": "未断裂"}}], development_data_id="data-v4.1-r1", fit_split="train")
    with pytest.raises(ValueError):
        build_majority_baseline([{"target": labels()}], development_data_id="LATEST", fit_split="train")


def test_majority_refuses_mutated_frozen_parameters_and_reports_overlap():
    rows = [record("same", labels())]
    frozen = build_majority_baseline(rows, development_data_id="data-v4.1-r1", fit_split="validation")
    assert majority_baseline_records(frozen, rows)[0]["baseline_fit_overlap"] is True
    frozen["prediction"]["clip_state"] = "已断裂"
    with pytest.raises(ValueError, match="drift"):
        majority_baseline_records(frozen, rows)


def test_majority_removes_previous_response_and_blind_review_evidence():
    frozen = build_majority_baseline([{"target": labels()}], development_data_id="data-v4.1-r1", fit_split="train")
    evaluation = record("failed", labels(), error="OOM")
    evaluation.update({"semantics": {"fake": True}, "blind_review": {"fake": True},
                       "scores": {"joint_correct": False}, "generated_token_count": 512,
                       "sampled_timestamps": [1.0], "hit_token_limit": True})
    synthetic = majority_baseline_records(frozen, [evaluation])[0]
    assert "runtime_error" not in synthetic
    assert "semantics" not in synthetic
    assert "blind_review" not in synthetic
    assert "generated_token_count" not in synthetic
    assert "sampled_timestamps" not in synthetic


def test_paired_changes_keep_failure_denominator_and_pair_by_identity():
    stable = labels()
    base = [record("regression", stable, stable), record("improvement", stable, error="timeout"),
            record("both-wrong", stable)]
    trained = [record("both-wrong", stable), record("improvement", stable, stable),
               record("regression", stable, error="OOM")]
    before = deepcopy((base, trained))
    result = compare(base, trained)
    assert result["sample_count"] == 3
    assert len(result["samples"]) == 3
    assert result["paired"]["joint"] == {"improved": 1, "regressed": 1, "unchanged_correct": 0,
                                           "unchanged_incorrect": 1, "net_correct_delta": 0,
                                           "net_correct_rate_delta": 0.0}
    assert result["base"]["metrics"]["joint_correct_rate"] == 1 / 3
    assert result["trained"]["metrics"]["joint_correct_rate"] == 1 / 3
    assert sum(row["base_runtime_failure"] for row in result["samples"]) == 1
    assert sum(row["trained_runtime_failure"] for row in result["samples"]) == 1
    assert (base, trained) == before


def test_relative_improvement_is_reported_separately_from_absolute_gate():
    gates = {"status": "failed", "gates": {"joint_correct_rate": False}}
    result = compare([record("one")], [record("one", prediction=labels())], absolute_gate_result=gates)
    assert result["paired"]["joint"]["improved"] == 1
    assert result["absolute_gate_result"] == gates
    assert result["relative_improvement_is_gate"] is False
    assert "passed" not in result
    result["absolute_gate_result"]["status"] = "changed"
    assert gates["status"] == "failed"


def test_paired_missing_null_is_not_filled_and_caller_scores_are_ignored():
    base = record("one", prediction={"clip_state": "未断裂"})
    base["scores"] = {"joint_correct": True}
    result = compare([base], [record("one", prediction=labels())])
    assert result["base"]["metrics"]["clip_state_correct_rate"] == 1.0
    assert result["base"]["metrics"]["fracture_mechanism_correct_rate"] == 0.0
    assert result["paired"]["joint"]["improved"] == 1


def test_unfinished_semantic_review_does_not_become_observed_regression():
    base = record("one", prediction=labels())
    trained = record("one")
    trained["raw_output"] = "opaque answer awaiting blind review"
    result = compare([base], [trained])
    assert result["sample_count"] == 1
    assert result["measurement_complete"] is False
    assert result["paired"] is None
    assert result["provisional_paired"]["joint"]["regressed"] == 1
    assert result["samples"][0]["outcomes"]["joint"] == "measurement_incomplete"
    assert result["metric_delta"]["joint_correct_rate"] is None
    assert result["trained"]["metrics"]["joint_correct_rate"] is None


@pytest.mark.parametrize("key", ["media_sampling", "prompt", "decode", "scorer"])
def test_paired_rejects_different_frozen_comparison_conditions(key):
    trained_config = config()
    trained_config[key] = "different"
    with pytest.raises(ValueError):
        compare_paired_records([record("one")], [record("one")], base_config=config(), trained_config=trained_config)


def test_paired_refuses_claiming_a_scorer_other_than_the_actual_scorer():
    conditions = {**config(), "scorer": "strict-v4.1"}
    with pytest.raises(ValueError, match="actual"):
        compare_paired_records([record("one")], [record("one")], base_config=conditions, trained_config=conditions)


@pytest.mark.parametrize("key", ["media_sampling", "prompt", "decode"])
def test_paired_refuses_non_configuration_values_on_both_sides(key):
    conditions = {**config(), key: True}
    with pytest.raises(ValueError, match="mappings"):
        compare_paired_records([record("one")], [record("one")], base_config=conditions, trained_config=conditions)


@pytest.mark.parametrize("key,value", [
    ("video_path", "/other.mp4"), ("media_sha256", "changed"),
    ("source_group", "other-specimen"), ("target", labels("已断裂")),
    ("sampled_timestamps", [2.0]), ("sample_id", "other-id"),
])
def test_paired_rejects_sample_evidence_drift(key, value):
    base = record("one")
    trained = deepcopy(base)
    if key == "sampled_timestamps":
        base[key] = [1.0]
    trained[key] = value
    with pytest.raises(ValueError, match="mismatch"):
        compare([base], [trained])


def test_paired_rejects_prediction_based_filtering_duplicate_and_missing_raw():
    base = [record("success", prediction=labels()), record("failure", error="OOM")]
    with pytest.raises(ValueError, match="complete fixed list"):
        compare(base, base[:1])
    with pytest.raises(ValueError, match="duplicate"):
        compare([base[0], base[0]], base)
    missing_raw = deepcopy(base)
    del missing_raw[1]["raw_output"]
    with pytest.raises(ValueError, match="raw output"):
        compare(base, missing_raw)


def test_failure_before_frame_sampling_stays_in_comparison():
    base = record("one", prediction=labels())
    base["sampled_timestamps"] = [0.1, 0.5]
    trained = record("one", error="video decode failed")
    trained["sampled_timestamps"] = []
    result = compare([base], [trained])
    assert result["sample_count"] == 1
    assert result["paired"]["joint"]["regressed"] == 1


def test_paired_accepts_sample_id_media_digest_without_paths():
    row = record("one", prediction=labels())
    row["sample_id"] = row.pop("candidate_id")
    row["media_sha256"] = "a" * 64
    del row["video_path"]
    assert compare([row], [row])["paired"]["joint"]["unchanged_correct"] == 1
