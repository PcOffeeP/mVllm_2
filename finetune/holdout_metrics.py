"""Frozen Stage D seven-gate policy, without reading data or model state.

Definitions are preserved from f04ca7cb:finetune/v4_1_stage_d_runtime.py.
Numeric metrics are private. Public metrics encode gate pass/fail only.
"""
from collections import Counter
from collections.abc import Mapping
import math

FOUR_STATES = ('未断裂', '临界未断裂', '发生断裂', '已断裂')
FRACTURE_STATES = FOUR_STATES[1:]
THRESHOLDS = {
    'four_state_macro_recall': 0.4006,
    'fracture_three_state_macro_recall': 0.3,
    'joint_correct_rate': 0.3921,
    'runtime_failure_count': 0,
    'strict_valid_rate': 1.0,
    '已断裂_recall': 0.15,
    '未断裂_recall': 0.7,
}
METRIC_DEFINITIONS = {
    'four_state_macro_recall': 'mean recall over all four states; round after averaging to six decimals',
    'fracture_three_state_macro_recall': 'mean recall over 临界未断裂/发生断裂/已断裂; round after averaging to six decimals',
    'joint_correct_rate': 'jointly correct / all records, rounded to six decimals',
    'runtime_failure_count': 'number of records with a runtime error; must equal zero',
    'strict_valid_rate': 'strictly valid / all records, rounded to six decimals',
    '已断裂_recall': 'correct 已断裂 predictions / 已断裂 targets, rounded to six decimals',
    '未断裂_recall': 'correct 未断裂 predictions / 未断裂 targets, rounded to six decimals',
}
PUBLIC_GATE_KEYS = frozenset('gate_' + name for name in THRESHOLDS)


def validate_thresholds(thresholds):
    if not isinstance(thresholds, Mapping) or set(thresholds) != set(THRESHOLDS):
        raise ValueError('holdout requires exactly the seven frozen thresholds')
    for name, frozen in THRESHOLDS.items():
        value = thresholds[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value != frozen:
            raise ValueError(f'holdout frozen threshold mismatch: {name}')


def restricted_metrics(records):
    """Reproduce the original Stage D denominators, missing-class and rounding rules."""
    if not records:
        raise ValueError('holdout records must not be empty')
    counts, correct = Counter(), Counter()
    for row in records:
        state = row['target']['clip_state']
        counts[state] += 1
        prediction = row.get('prediction')
        correct[state] += isinstance(prediction, Mapping) and prediction.get('clip_state') == state
    if any(not counts[state] for state in FOUR_STATES):
        raise ValueError('holdout must cover all four states')
    recalls = {state: correct[state] / counts[state] for state in FOUR_STATES}
    return {
        'four_state_macro_recall': round(sum(recalls.values()) / 4, 6),
        'fracture_three_state_macro_recall': round(sum(recalls[s] for s in FRACTURE_STATES) / 3, 6),
        'joint_correct_rate': round(sum(bool((r.get('scores') or {}).get('joint_correct')) for r in records) / len(records), 6),
        'runtime_failure_count': sum(bool(r.get('runtime_error')) for r in records),
        'strict_valid_rate': round(sum(r.get('strict_valid') is True for r in records) / len(records), 6),
        '已断裂_recall': round(recalls['已断裂'], 6),
        '未断裂_recall': round(recalls['未断裂'], 6),
    }


def public_gates(metrics, thresholds):
    validate_thresholds(thresholds)
    if not isinstance(metrics, Mapping) or set(metrics) != set(THRESHOLDS):
        raise ValueError('holdout private metrics must contain all seven values')
    result = {}
    for name, threshold in thresholds.items():
        value = metrics[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid holdout private metric')
        if name == 'runtime_failure_count':
            if value != int(value):
                raise ValueError('holdout runtime failure count must be integral')
            passed = value == threshold
        else:
            if value > 1:
                raise ValueError('holdout rate must be at most one')
            passed = value >= threshold
        result['gate_' + name] = float(passed)
    return result


def gate_outcome(gates):
    if (not isinstance(gates, Mapping) or set(gates) != PUBLIC_GATE_KEYS
        or any(type(v) not in (int, float) or v not in (0, 1) for v in gates.values())):
        raise ValueError('holdout public evidence requires seven binary gates')
    return 'passed' if all(gates.values()) else 'failed'
