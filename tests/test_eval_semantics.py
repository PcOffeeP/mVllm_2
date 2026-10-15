"""Synthetic counterexamples; no released samples, models or sealed truth."""
import hashlib
import json
from copy import deepcopy

import pytest

from finetune.eval_semantics import (
    FIELDS, FOUR_STATES, content_digest, default_rules, rules_digest,
    extract_semantics, score_semantic_records, development_gates,
    freeze_blind_policy, seal_judgment, import_blind_review, build_blind_package,
)


def labels(state="发生断裂", mechanism="韧性断裂", site="inside_gauge", special=None):
    if state == "未断裂" or special is not None:
        mechanism = site = None
    return dict(zip(FIELDS, (state, mechanism, site, special)))


def row(identity, target, prediction=None, *, raw=None, group="source-a", error=None):
    return {"sample_id": str(identity), "target": target, "raw_output": raw if raw is not None else json.dumps(prediction, ensure_ascii=False) if prediction is not None else "", "source_group": group, "runtime_error": error}


def metrics(rows):
    return score_semantic_records(rows, bootstrap=False)["metrics"]


def policy():
    def actor(identity):
        return {"id": identity, "model": "local:" + identity,
                "model_sha256": "a" * 64, "prompt_sha256": "b" * 64}
    return {"participants": [actor("first"), actor("second")], "arbiter": actor("third"),
            "manual_sha256": hashlib.sha256(b"manual").hexdigest(),
            "rules_sha256": rules_digest(), "aggregation": "unanimous-per-field",
            "retry_policy": {"runtime_failure_retries": 1, "answer_selection": "forbidden"}}


def review(raw, first, second):
    frozen_policy = policy()
    digest = freeze_blind_policy(frozen_policy)["sha256"]
    raw_hash = hashlib.sha256(raw.encode()).hexdigest()
    def judgment(actor, fields, sequence, phase="independent", **kwargs):
        return seal_judgment(actor_id=actor, raw_sha256=raw_hash, policy_sha256=digest,
                             fields=fields, sequence=sequence, phase=phase, **kwargs)
    evidence = {"policy": frozen_policy, "initial": [judgment("first", first, 1), judgment("second", second, 2)],
                "sealed_at": 10, "access_scope": "anonymous-raw-and-manual-only"}
    return evidence, judgment


def complete_fold(prefix, bad_state=False):
    examples = [labels("未断裂"), labels("临界未断裂"), labels("发生断裂", "脆性断裂", "outside_gauge_non_root"),
                labels("已断裂", "界面脱粘", "grip_root"), labels("发生断裂", "爆炸性断裂"),
                labels("已断裂", "半脆半韧断裂"), labels("无法判断", special="未夹紧"), labels("无法判断", special="视频异常")]
    return [row(f"{prefix}-{index}", target, {**target, "clip_state": "已断裂"} if bad_state and target["clip_state"] == "发生断裂" else target,
                group=f"group-{index}") for index, target in enumerate(examples)]


def test_missing_is_not_explicit_null_and_joint_requires_all_fields():
    target = labels("未断裂")
    recovered = extract_semantics('{"clip_state":"未断裂"}')
    assert recovered["fields"] == {"clip_state": "未断裂"}
    assert recovered["missing_fields"] == list(FIELDS[1:])
    values = metrics([row("partial", target, raw='{"clip_state":"未断裂"}')])
    assert values["clip_state_correct_rate"] == 1
    assert values["fracture_mechanism_correct_rate"] == 0
    assert values["joint_correct_rate"] == 0


def test_runtime_empty_and_unreadable_preserve_all_sample_denominators():
    target = labels()
    rows = [row("ok", target, target), row("error", target, target, error="timeout"), row("empty", target), row("garbage", target, raw="uninterpretable")]
    summary = score_semantic_records(rows, bootstrap=False)
    assert summary["support"]["total"] == 4
    assert summary["metrics"]["joint_correct_rate"] is None
    assert summary["diagnostics"]["provisional_metrics"]["joint_correct_rate"] == .25
    assert summary["diagnostics"]["branches"]["unreadable"]["count"] == 3
    assert summary["diagnostics"]["review_incomplete_count"] == 1
    assert summary["diagnostics"]["runtime_failure_count"] == 1


def test_extraction_sources_mutually_exclusive_and_strict_rate_unrepaired():
    target = labels()
    raw = json.dumps(target)
    rows = [row("strict", target, raw=raw), row("rule", target, raw=f"```json\n{raw}\n```"), row("bad", target, raw="unknown")]
    summary = score_semantic_records(rows, bootstrap=False)
    assert summary["metrics"]["strict_valid_rate"] == 1 / 3
    assert summary["diagnostics"]["provisional_metrics"]["joint_correct_rate"] == 2 / 3
    assert sum(value["count"] for value in summary["diagnostics"]["branches"].values()) == 3
    with pytest.raises(ValueError, match="later blind"):
        extract_semantics(raw, blind_review={})


def test_contradictory_duplicate_is_not_strict_or_usable_field():
    result = extract_semantics('{"clip_state":"未断裂","clip_state":"已断裂","special_case":null}')
    assert result["strict_valid"] is False
    assert result["fields"] == {"special_case": None}


def test_invalid_relation_does_not_repair_other_fields_or_discard_partial():
    value = {**labels("未断裂"), "fracture_site": "grip_root"}
    result = extract_semantics(json.dumps(value))
    assert result["branch"] == "rule"
    assert result["fields"] == value


def test_gt_applicable_subset_does_not_follow_prediction_state():
    target = labels("发生断裂")
    summary = score_semantic_records([row("wrong-state", target, labels("未断裂"))], bootstrap=False)
    support = summary["support"]["fracture_mechanism"]
    assert support["applicable_total"] == 1
    assert support["classes"]["韧性断裂"]["f1"] == 0
    assert support["classes"]["韧性断裂"]["precision"] == 0


def test_null_false_fill_and_special_false_positive_use_full_relevant_samples():
    unbroken = labels("未断裂")
    special = labels("无法判断", special="未夹紧")
    rows = [row("sp", special, special), row("false-sp", unbroken, special), row("false-site", unbroken, labels())]
    summary = score_semantic_records(rows, bootstrap=False)
    assert summary["support"]["special_case"]["未夹紧"]["precision"] == .5
    assert summary["support"]["special_case"]["未夹紧"]["false_positive"] == 1
    assert summary["diagnostics"]["null_false_fill"]["fracture_site"] == {"support": 3, "count": 1, "rate": 1 / 3}


def test_four_state_macro_excludes_unknown_truth_and_counts_refusal_wrong():
    rows = [row(state, labels(state), labels(state)) for state in FOUR_STATES]
    rows.append(row("refusal", labels("发生断裂"), labels("无法判断")))
    rows.extend(row(f"unknown-{i}", labels("无法判断"), labels("未断裂")) for i in range(10))
    summary = score_semantic_records(rows, bootstrap=False)
    assert summary["metrics"]["four_state_macro_recall"] == .875
    assert summary["support"]["clip_state"]["无法判断"]["support"] == 10


def test_missing_classes_are_insufficient_not_zero_or_auto_pass():
    records = [row("one", labels("未断裂"), labels("未断裂"))]
    assert metrics(records)["four_state_macro_recall"] is None
    result = development_gates({0: records}, bootstrap=False)
    assert result["outcome"] == "insufficient_evidence"


def test_three_fold_development_and_per_fold_collapse():
    folds = {fold: complete_fold(str(fold)) for fold in range(3)}
    assert development_gates(folds, bootstrap=False)["outcome"] == "passed"
    folds[0] = complete_fold("0", bad_state=True)
    result = development_gates(folds, bootstrap=False)
    assert result["pooled"]["metrics"]["four_state_macro_recall"] >= .65
    assert result["gates"]["fold_0_发生断裂_recall"] is False
    assert result["outcome"] == "failed"


def test_thresholds_compare_unrounded_precision():
    # Deliberately place 49.99995% just below 50%; never use displayed rounding.
    import finetune.eval_semantics as module
    original = module.score_semantic_records
    def modified(records, *, bootstrap=True):
        summary = original(records, bootstrap=False)
        summary["metrics"]["joint_correct_rate"] = .4999995
        return summary
    from unittest.mock import patch
    with patch.object(module, "score_semantic_records", modified):
        result = development_gates({fold: complete_fold(str(fold)) for fold in range(3)}, bootstrap=False)
    assert result["outcome"] == "failed"


def test_rules_drift_rejected_and_ground_truth_cannot_fill_missing():
    changed = default_rules()
    changed["aliases"] = {"broken": "发生断裂"}
    with pytest.raises(ValueError, match="drifted"):
        extract_semantics("broken", rules=changed)
    with pytest.raises(TypeError):
        extract_semantics("broken", ground_truth=labels())
    with pytest.raises(TypeError):
        extract_semantics("broken", video="secret.mp4")


def test_semantic_content_tampering_and_duplicate_sample_rejected():
    sample = row("a", labels(), labels())
    sample["semantics"] = extract_semantics(sample["raw_output"])
    sample["semantics"]["fields"]["fracture_site"] = "grip_root"
    with pytest.raises(ValueError, match="does not match"):
        score_semantic_records([sample], bootstrap=False)
    other = row("duplicate", labels(), labels())
    with pytest.raises(ValueError, match="duplicate"):
        score_semantic_records([other, other], bootstrap=False)


def test_group_bootstrap_keeps_whole_groups_and_does_not_drop_missing_class_draws():
    rows = [row("a", labels("未断裂"), labels("未断裂"), group="one"), row("a2", labels("未断裂"), labels("未断裂"), group="one"), row("b", labels("已断裂"), labels("已断裂"), group="two")]
    first = score_semantic_records(rows)
    second = score_semantic_records(rows)
    assert first == second
    assert first["support"]["group_sizes"] == {"one": 2, "two": 1}
    cis = first["confidence_intervals"]
    assert cis["replicates"] == 2000 and cis["seed"] == 3407
    assert cis["metrics"]["joint_correct_rate"]["lower"] == 1
    assert not cis["metrics"]["已断裂_recall"]["estimable"]
    assert cis["metrics"]["已断裂_recall"]["undefined_replicates"] > 0


def test_missing_dependency_mapping_reports_no_ci_not_sample_bootstrap():
    sample = row("x", labels(), labels())
    del sample["source_group"]
    result = score_semantic_records([sample])
    assert result["support"]["missing_group_mapping"]
    assert result["confidence_intervals"]["metrics"]["joint_correct_rate"]["reason"] == "missing dependency groups"


def test_conflicting_higher_dependency_mapping_rejected():
    rows = [row("a", labels(), labels(), group="one"), row("b", labels(), labels(), group="two")]
    for sample in rows:
        sample["source_id"] = "same-source"
    with pytest.raises(ValueError, match="conflicting"):
        score_semantic_records(rows, bootstrap=False)


def test_anonymous_package_preserves_raw_and_separates_mapping():
    p = policy()
    package, mapping = build_blind_package({"private-model/fold/video.mp4": "original raw"}, manual="manual", policy=p)
    assert package["samples"] == [{"anonymous_id": "answer-00000000", "raw_output": "original raw", "requested_fields": list(FIELDS)}]
    assert "private-model" not in json.dumps(package)
    assert mapping["answer-00000000"] == "private-model/fold/video.mp4"


def test_blind_agreement_preserves_missing_null_and_provenance():
    raw = "model expressed an unbroken state"
    evidence, _ = review(raw, {"clip_state": "未断裂"}, {"clip_state": "未断裂"})
    sample = row("a", labels("未断裂"), raw=raw)
    sample["blind_review"] = evidence
    sample["semantics"] = extract_semantics(raw, blind_review=evidence)
    assert sample["semantics"]["branch"] == "blind"
    assert sample["semantics"]["fields"] == {"clip_state": "未断裂"}
    assert sample["semantics"]["review_complete"]
    assert metrics([sample])["joint_correct_rate"] == 0
    assert sample["semantics"]["blind_audit"]["technical_isolation_verified"] is False


def test_blind_disagreement_requires_independent_seal_before_arbitration():
    raw = "ambiguous answer"
    evidence, judge = review(raw, {"clip_state": "已断裂"}, {"clip_state": "发生断裂"})
    assert not import_blind_review(raw, evidence)["complete"]
    evidence.update(arbiter_independent=judge("third", {"clip_state": "已断裂"}, 3),
                    disclosed_at=4, arbitration=judge("third", {"clip_state": "发生断裂"}, 5, "arbitration"))
    result = import_blind_review(raw, evidence)
    assert result["complete"]
    assert result["fields"]["clip_state"] == "发生断裂"
    assert result["changed_fields"] == ["clip_state"]
    evidence["disclosed_at"] = 2
    with pytest.raises(ValueError, match="before disclosure"):
        import_blind_review(raw, evidence)


def test_blind_cannot_revote_agreement_or_import_truth_and_tamper():
    raw = "unbroken answer"
    evidence, judge = review(raw, {"clip_state": "未断裂", "fracture_site": None}, {"clip_state": "未断裂", "fracture_site": "grip_root"})
    evidence.update(arbiter_independent=judge("third", {}, 3), disclosed_at=4,
                    arbitration=judge("third", {"clip_state": "已断裂"}, 5, "arbitration"))
    with pytest.raises(ValueError, match="revote"):
        import_blind_review(raw, evidence)
    del evidence["arbitration"], evidence["arbiter_independent"]
    evidence["target"] = labels()
    with pytest.raises(ValueError, match="forbidden"):
        import_blind_review(raw, evidence)
    del evidence["target"]
    evidence["initial"][0]["fields"]["clip_state"] = "已断裂"
    with pytest.raises(ValueError, match="drift"):
        import_blind_review(raw, evidence)


def test_blind_infrastructure_failure_is_incomplete_and_runtime_failure_no_import():
    raw = "non-json"
    evidence, judge = review(raw, {}, {})
    evidence["initial"][1] = judge("second", {}, 2, status="infrastructure_failure")
    assert not import_blind_review(raw, evidence)["complete"]
    with pytest.raises(ValueError, match="runtime failures"):
        extract_semantics(raw, runtime_error="timeout", blind_review=evidence)


def test_frozen_participant_identity_and_retry_policy_enforced():
    p = policy()
    p["participants"][1]["id"] = "first"
    with pytest.raises(ValueError, match="distinct"):
        freeze_blind_policy(p)
    p = policy()
    p["retry_policy"]["runtime_failure_retries"] = 10
    with pytest.raises(ValueError, match="retry"):
        freeze_blind_policy(p)


def test_review_infrastructure_failure_does_not_publish_visual_errors_as_final():
    raw = "pending non-json answer"
    evidence, judge = review(raw, {}, {})
    evidence["initial"][1] = judge("second", {}, 2, status="infrastructure_failure")
    sample = row("pending", labels(), raw=raw)
    sample["blind_review"] = evidence
    sample["semantics"] = extract_semantics(raw, blind_review=evidence)
    result = score_semantic_records([sample], bootstrap=False)
    assert result["metrics"]["joint_correct_rate"] is None
    assert result["metrics"]["strict_valid_rate"] == 0
    assert result["support"]["total"] == 1
    assert result["diagnostics"]["review_incomplete_count"] == 1


def test_missing_frozen_raw_cannot_import_semantic_answers():
    result = extract_semantics(json.dumps(labels()))
    with pytest.raises(ValueError, match="frozen raw_output"):
        score_semantic_records([{"target": labels(), "semantics": result}], bootstrap=False)


def test_blind_evidence_without_precomputed_semantics_matches_explicit_extraction():
    raw = "The specimen remains unbroken throughout the answer."
    target = labels("未断裂")
    evidence, _ = review(raw, target, target)
    sample = {"target": target, "raw_output": raw, "blind_review": evidence}
    direct = score_semantic_records([sample], bootstrap=False)
    precomputed = {**sample, "semantics": extract_semantics(raw, blind_review=evidence)}
    assert direct == score_semantic_records([precomputed], bootstrap=False)
    assert direct["metrics"]["joint_correct_rate"] == 1
    assert direct["metrics"]["strict_valid_rate"] == 0
    assert direct["diagnostics"]["branches"]["blind"]["count"] == 1


def test_blind_incomplete_evidence_without_semantics_preserves_pending_measurement():
    raw = "answer pending independent review"
    evidence, judge = review(raw, {}, {})
    evidence["initial"][1] = judge("second", {}, 2, status="infrastructure_failure")
    result = score_semantic_records([{
        "target": labels(), "raw_output": raw, "blind_review": evidence,
    }], bootstrap=False)
    assert result["support"]["total"] == 1
    assert result["metrics"]["joint_correct_rate"] is None
    assert result["diagnostics"]["review_incomplete_count"] == 1


@pytest.mark.parametrize("reuse_judgments", [True, False])
def test_duplicate_raw_review_cost_counts_unique_judgments_not_sample_adoptions(reuse_judgments):
    raw = "The specimen remains unbroken throughout the answer."
    target = labels("未断裂")
    evidence, judge = review(raw, target, target)
    evidence["initial"] = [
        judge("first", target, 1, elapsed_seconds=2.0, cost=.1),
        judge("second", target, 2, elapsed_seconds=3.0, cost=.2),
    ]
    second = deepcopy(evidence)
    if not reuse_judgments:
        second["initial"] = [
            judge("first", target, 3, elapsed_seconds=2.0, cost=.1),
            judge("second", target, 4, elapsed_seconds=3.0, cost=.2),
        ]
    rows = [
        {**row("one", target, raw=raw), "blind_review": evidence},
        {**row("two", target, raw=raw), "blind_review": second},
    ]
    result = score_semantic_records(rows, bootstrap=False)
    audit = result["diagnostics"]["blind_review"]
    multiplier = 1 if reuse_judgments else 2
    assert audit["unique_judgment_count"] == 2 * multiplier
    assert audit["elapsed_seconds"] == 5.0 * multiplier
    assert audit["cost"] == pytest.approx(.3 * multiplier)
    assert "not wall-clock" in audit["elapsed_seconds_definition"]
    assert audit["sample_count"] == 2
    assert audit["agreements"] == 8
    assert audit["agreement_rate"] == 1
    assert result["diagnostics"]["branches"]["blind"]["count"] == 2
    assert result["metrics"]["joint_correct_rate"] == 1
