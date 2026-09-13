"""Frozen business gates: unequal denominators, boundaries and privacy contract."""
import pytest

from finetune.holdout_metrics import (
    FOUR_STATES, THRESHOLDS, PUBLIC_GATE_KEYS, restricted_metrics,
    validate_thresholds, public_gates, gate_outcome,
)
from finetune.eval_run import _formal_config, FORMAL_GENERATION


def rows():
    # State denominators 3/7/6/5, successes 2/1/2/1: macros must not pool rows.
    records = []
    for state, total, hits in zip(FOUR_STATES, (3, 7, 6, 5), (2, 1, 2, 1), strict=True):
        for i in range(total):
            records.append({'target': {'clip_state': state},
                'prediction': {'clip_state': state} if i < hits else None,
                'strict_valid': i < hits, 'runtime_error': None,
                'scores': {'joint_correct': i < hits}})
    return records


def test_original_stage_d_denominators_and_round_after_macro():
    metrics = restricted_metrics(rows())
    assert metrics == {
        'four_state_macro_recall': 0.335714,
        'fracture_three_state_macro_recall': 0.225397,
        'joint_correct_rate': 0.285714, 'runtime_failure_count': 0,
        'strict_valid_rate': 0.285714, '已断裂_recall': 0.2, '未断裂_recall': 0.666667,
    }


@pytest.mark.parametrize('state', FOUR_STATES)
def test_missing_class_rejected_instead_of_zero_or_dropping_denominator(state):
    with pytest.raises(ValueError, match='all four'):
        restricted_metrics([r for r in rows() if r['target']['clip_state'] != state])


def test_empty_and_runtime_failure():
    with pytest.raises(ValueError, match='empty'):
        restricted_metrics([])
    records = rows(); records[0]['runtime_error'] = 'synthetic error'
    assert restricted_metrics(records)['runtime_failure_count'] == 1


@pytest.mark.parametrize('name', THRESHOLDS)
def test_each_gate_at_boundary_and_wrong_side(name):
    metrics = dict(THRESHOLDS)
    assert gate_outcome(public_gates(metrics, THRESHOLDS)) == 'passed'
    metrics[name] = 1 if name == 'runtime_failure_count' else metrics[name] - 0.000001
    gates = public_gates(metrics, THRESHOLDS)
    assert gates['gate_' + name] == 0
    assert sum(v == 0 for v in gates.values()) == 1
    assert gate_outcome(gates) == 'failed'


@pytest.mark.parametrize('name', THRESHOLDS)
def test_thresholds_cannot_be_omitted_or_relaxed(name):
    values = dict(THRESHOLDS); del values[name]
    with pytest.raises(ValueError): validate_thresholds(values)
    values = dict(THRESHOLDS); values[name] += 0.000001
    with pytest.raises(ValueError): validate_thresholds(values)


@pytest.mark.parametrize('bad', [None, True, float('nan'), float('inf'), -1, '0'])
def test_threshold_values_reject_bad_types_and_nonfinite(bad):
    values = dict(THRESHOLDS); values['runtime_failure_count'] = bad
    with pytest.raises(ValueError): validate_thresholds(values)


def config(scope, thresholds):
    return {'scope': scope, 'split': 'holdout' if scope == 'full' else 'validation',
        'artifact_kind': 'adapter', 'scorer': 'strict-v4.1', 'sample_selection': 'all',
        'quantization_bit': None, 'generation': FORMAL_GENERATION,
        'thresholds': thresholds, 'aggregation': 'pooled'}


def test_full_requires_frozen_policy_and_validation_is_unchanged():
    value = config('full', dict(THRESHOLDS))
    assert _formal_config(value) == value
    with pytest.raises(ValueError, match='seven'):
        _formal_config(config('full', {'joint_correct_rate': 1.0}))
    legacy_validation = config('cross_validation', {'joint_correct_rate': 0.1})
    assert _formal_config(legacy_validation) == legacy_validation
    with pytest.raises(ValueError, match='supported rates'):
        _formal_config(config('cross_validation', dict(THRESHOLDS)))


def test_public_gate_evidence_accepts_only_complete_binary_values():
    gates = public_gates(dict(THRESHOLDS), THRESHOLDS)
    assert set(gates) == PUBLIC_GATE_KEYS
    for bad in [0.9, True, float('nan'), float('inf'), None, '1']:
        value = dict(gates); value['gate_joint_correct_rate'] = bad
        with pytest.raises(ValueError, match='binary'): gate_outcome(value)
    with pytest.raises(ValueError): gate_outcome({'gate_joint_correct_rate': 1.0})
    with pytest.raises(ValueError): gate_outcome({**gates, 'joint_correct_rate': 0.3921})
