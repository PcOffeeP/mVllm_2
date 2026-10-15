"""Frozen V4.1 semantic evaluation primitives; no model, truth or network access.

Blind-review seals are content/order audit records, not proof of process isolation.
The calling workflow must independently enforce and verify technical isolation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import random
import re
from typing import Any

PROTOCOL = "semantic-v4.1"
FIELDS = ("clip_state", "fracture_mechanism", "fracture_site", "special_case")
FOUR_STATES = ("未断裂", "临界未断裂", "发生断裂", "已断裂")
ENUMS = {
    "clip_state": (*FOUR_STATES, "无法判断"),
    "fracture_mechanism": ("韧性断裂", "脆性断裂", "界面脱粘", "爆炸性断裂", "半脆半韧断裂", None),
    "fracture_site": ("inside_gauge", "outside_gauge_non_root", "grip_root", None),
    "special_case": ("未夹紧", "视频异常", None),
}
BRANCHES = ("strict", "rule", "blind", "unreadable")
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 3407


def content_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def implementation_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def default_rules() -> dict:
    """Conservative rules: explicit JSON fields only, optional Markdown JSON fence.

    No natural-language guessing, aliases, inferred nulls or relation repairs.
    Changing this payload or module changes the frozen rules identity.
    """
    return {"protocol": PROTOCOL, "version": 1,
            "extractor": "explicit-json-fields-or-fence", "aliases": {},
            "ambiguity": "omit-conflicting-duplicate-field",
            "implementation_sha256": implementation_digest()}


def rules_digest(rules: Mapping | None = None) -> str:
    value = dict(default_rules() if rules is None else rules)
    if value != default_rules():
        raise ValueError("unsupported or drifted semantic rules; freeze a supported implementation")
    return content_digest(value)


def _legal(field: str, value: Any) -> bool:
    return value is None and None in ENUMS[field] or isinstance(value, str) and value in ENUMS[field]


def _validate_target(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or set(value) != set(FIELDS):
        raise ValueError("target must explicitly contain exactly four fields")
    if any(not _legal(field, value[field]) for field in FIELDS):
        raise ValueError("target contains invalid V4.1 field")
    state = value["clip_state"]
    if state == "未断裂" and any(value[field] is not None for field in FIELDS[1:]):
        raise ValueError("未断裂 requires explicit null summary and special fields")
    if state == "临界未断裂" and (value["fracture_mechanism"] not in (None, "韧性断裂") or value["special_case"] is not None):
        raise ValueError("invalid 临界未断裂 fields")
    if value["special_case"] is not None and (state != "无法判断" or any(value[field] is not None for field in FIELDS[1:3])):
        raise ValueError("special_case requires 无法判断 and null summary")
    return dict(value)


def _object_pairs(raw: str) -> list | None:
    try:
        value = json.loads(raw, object_pairs_hook=lambda pairs: pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError):
        return None
    if not isinstance(value, list) or not value or not all(isinstance(p, tuple) and len(p) == 2 for p in value):
        return None
    return value


def _explicit_fields(pairs: list) -> dict:
    grouped = defaultdict(list)
    for name, value in pairs:
        if name in FIELDS:
            grouped[name].append(value)
    # Duplicates are ambiguous even when an invalid alternative accompanies a valid one.
    return {name: values[0] for name, values in grouped.items()
            if all(value == values[0] for value in values) and _legal(name, values[0])}


def extract_semantics(raw_output: str | None, *, runtime_error=None, rules=None,
                      blind_review: Mapping | None = None) -> dict:
    """Extract only expressed answers; never receives labels, video or model identity.

    A successful partial rule extraction owns the entire response and does not
    proceed to blind review. Runtime failure is retained even if it left text.
    """
    if raw_output is not None and not isinstance(raw_output, str):
        raise ValueError("raw_output must be text or None")
    raw = raw_output or ""
    digest = rules_digest(rules)
    result = {"branch": "unreadable", "fields": {}, "field_sources": {},
              "strict_valid": False, "review_complete": True,
              "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
              "rules_sha256": digest, "runtime_error": runtime_error}
    if not runtime_error:
        pairs = _object_pairs(raw.strip())
        if pairs is not None:
            try:
                if len({name for name, _ in pairs}) != len(pairs):
                    raise ValueError("duplicate keys")
                fields = _validate_target(dict(pairs))
            except (ValueError, TypeError):
                fields = _explicit_fields(pairs)
                if fields:
                    result.update(branch="rule", fields=fields)
            else:
                result.update(branch="strict", fields=fields, strict_valid=True)
        else:
            fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw, re.S)
            if fenced:
                pairs = _object_pairs(fenced.group(1).strip())
                if pairs is not None and (fields := _explicit_fields(pairs)):
                    result.update(branch="rule", fields=fields)
        if result["branch"] == "unreadable" and blind_review is not None:
            imported = import_blind_review(raw, blind_review)
            result.update(branch="blind", fields=imported["fields"],
                          review_complete=imported["complete"], blind_audit=imported)
    elif blind_review is not None:
        raise ValueError("runtime failures cannot acquire blind-review answers")
    if blind_review is not None and result["branch"] in ("strict", "rule"):
        raise ValueError("strict/rule answers cannot enter a later blind branch")
    if result["branch"] == "unreadable" and raw.strip() and not runtime_error:
        result["review_complete"] = False
    result["field_sources"] = ({field: result["branch"] for field in result["fields"]}
                               if result["branch"] != "blind" else result["blind_audit"]["field_sources"])
    result["missing_fields"] = [field for field in FIELDS if field not in result["fields"]]
    return result


def freeze_blind_policy(policy: Mapping) -> dict:
    """Validate a pre-run participant/manual/prompt/retry policy and content seal it.

    Supports a frozen unanimous per-field initial aggregation (two by default).
    More participants require explicit pre-registration, never ad-hoc majority vote.
    """
    required = {"participants", "arbiter", "manual_sha256", "rules_sha256", "aggregation", "retry_policy"}
    if set(policy) != required or policy["aggregation"] != "unanimous-per-field":
        raise ValueError("blind policy requires exact frozen participants/manual/aggregation/retry schema")
    participants = policy["participants"]
    if not isinstance(participants, list) or len(participants) < 2:
        raise ValueError("at least two independent initial participants required")
    actors = [*participants, policy["arbiter"]]
    for actor in actors:
        if not isinstance(actor, Mapping) or set(actor) != {"id", "model", "model_sha256", "prompt_sha256"}:
            raise ValueError("actor requires exact model and prompt identities")
        if any(not isinstance(actor[key], str) or not actor[key] for key in actor):
            raise ValueError("actor identity must be nonempty text")
        if any(not re.fullmatch(r"[0-9a-f]{64}", actor[key]) for key in ("model_sha256", "prompt_sha256")):
            raise ValueError("actor requires full model/prompt content digests")
    if len({actor["id"] for actor in actors}) != len(actors):
        raise ValueError("independent contexts require distinct actor identities")
    for key in ("manual_sha256", "rules_sha256"):
        if not isinstance(policy[key], str) or not re.fullmatch(r"[0-9a-f]{64}", policy[key]):
            raise ValueError("policy requires full manual/rules digests")
    if policy["retry_policy"] != {"runtime_failure_retries": 1, "answer_selection": "forbidden"}:
        raise ValueError("only one runtime-failure retry, no answer selection")
    copied = json.loads(json.dumps(policy))
    return {"policy": copied, "sha256": content_digest(copied)}


def seal_judgment(*, actor_id: str, raw_sha256: str, policy_sha256: str,
                  fields: Mapping, sequence: int, status="completed", elapsed_seconds=0.0,
                  cost=0.0, phase="independent") -> dict:
    """Content seal for offline import; sequence is a caller's frozen audit order."""
    if any(field not in FIELDS or not _legal(field, value) for field, value in fields.items()):
        raise ValueError("judgment contains invalid expressed field")
    if status not in ("completed", "infrastructure_failure") or type(sequence) is not int or sequence < 0:
        raise ValueError("invalid judgment completion/order")
    if phase not in ("independent", "arbitration", "human"):
        raise ValueError("invalid judgment phase")
    if status != "completed" and fields:
        raise ValueError("incomplete review cannot contain adopted answers")
    if any(type(value) not in (int, float) or not 0 <= value < float("inf") for value in (elapsed_seconds, cost)):
        raise ValueError("invalid review cost/latency")
    value = dict(actor_id=actor_id, raw_sha256=raw_sha256, policy_sha256=policy_sha256,
                 fields=dict(fields), sequence=sequence, status=status, phase=phase,
                 elapsed_seconds=elapsed_seconds, cost=cost)
    return {**value, "sha256": content_digest(value)}


def build_blind_package(raw_outputs: Mapping[str, str], *, manual: str, policy: Mapping) -> tuple[dict, dict]:
    """Return anonymous raw-only package and a SEPARATE restricted identity map.

    This function neither writes nor distributes the package. Anonymization applies
    to metadata only: raw is never rewritten. Technical isolation remains external.
    """
    frozen = freeze_blind_policy(policy)
    if hashlib.sha256(manual.encode()).hexdigest() != policy["manual_sha256"]:
        raise ValueError("blind manual drift")
    samples, restricted = [], {}
    for index, (identity, raw) in enumerate(raw_outputs.items()):
        if not isinstance(raw, str):
            raise ValueError("blind raw must be text")
        anonymous_id = f"answer-{index:08d}"
        samples.append({"anonymous_id": anonymous_id, "raw_output": raw, "requested_fields": list(FIELDS)})
        restricted[anonymous_id] = identity
    package = {"manual": manual, "policy_sha256": frozen["sha256"], "samples": samples}
    return {**package, "sha256": content_digest(package)}, restricted


def import_blind_review(raw_output: str, evidence: Mapping) -> dict:
    """Import pre-sealed independent results; never ask a judge or read any truth.

    The required scope declaration is auditable metadata, not verified isolation.
    Independent judgment sequence must precede disagreement disclosure/arbitration.
    """
    if set(evidence) - {"policy", "initial", "arbiter_independent", "arbitration", "human", "disclosed_at", "sealed_at", "access_scope"}:
        raise ValueError("unexpected blind evidence fields (truth/video/model forbidden)")
    if evidence.get("access_scope") != "anonymous-raw-and-manual-only":
        raise ValueError("blind scope declaration required")
    frozen = freeze_blind_policy(evidence["policy"])
    raw_digest = hashlib.sha256(raw_output.encode()).hexdigest()
    if evidence["policy"]["rules_sha256"] != rules_digest():
        raise ValueError("blind review rules drift")
    sealed_at = evidence.get("sealed_at")
    if type(sealed_at) is not int or sealed_at < 0:
        raise ValueError("judge answers must be sealed before score")

    def checked(value, actor, phase):
        if not isinstance(value, Mapping):
            raise ValueError("missing sealed judgment")
        payload = {key: item for key, item in value.items() if key != "sha256"}
        if value.get("sha256") != content_digest(payload):
            raise ValueError("judgment content drift")
        rebuilt = seal_judgment(**payload)
        if rebuilt != value or value["actor_id"] != actor or value["phase"] != phase:
            raise ValueError("unexpected actor or judgment phase")
        if value["raw_sha256"] != raw_digest or value["policy_sha256"] != frozen["sha256"] or value["sequence"] >= sealed_at:
            raise ValueError("judgment raw/policy/order mismatch")
        return value

    initial = evidence.get("initial", [])
    participants = evidence["policy"]["participants"]
    if len(initial) != len(participants):
        raise ValueError("frozen participant count mismatch")
    initial = [checked(value, actor["id"], "independent") for value, actor in zip(initial, participants)]
    fields, sources, agreements, disagreements = {}, {}, [], []
    infrastructure_failure = any(value["status"] != "completed" for value in initial)
    for field in FIELDS:
        answers = [value["fields"] for value in initial]
        if all(field in value for value in answers) and all(value[field] == answers[0][field] for value in answers):
            fields[field] = answers[0][field]
            sources[field] = "blind:agreement"
            agreements.append(field)
        elif not infrastructure_failure and all(field not in value for value in answers):
            # All participants explicitly completed without an expressed field.
            continue
        else:
            disagreements.append(field)
    all_judgments = list(initial)
    arbiter = evidence.get("arbiter_independent")
    arbitration = evidence.get("arbitration")
    human = evidence.get("human")
    arbitrated, changed, human_fields = [], [], []
    if arbiter is not None or arbitration is not None:
        if not disagreements or arbiter is None or arbitration is None:
            raise ValueError("only disagreement fields may be arbitrated, after independent seal")
        actor_id = evidence["policy"]["arbiter"]["id"]
        independent = checked(arbiter, actor_id, "independent")
        decision = checked(arbitration, actor_id, "arbitration")
        disclosed = evidence.get("disclosed_at")
        if type(disclosed) is not int or not max(value["sequence"] for value in [*initial, independent]) < disclosed < decision["sequence"]:
            raise ValueError("arbiter must seal independent answer before disclosure")
        if set(decision["fields"]) - set(disagreements):
            raise ValueError("cannot revote already agreed fields")
        infrastructure_failure |= independent["status"] != "completed" or decision["status"] != "completed"
        fields.update(decision["fields"])
        for field in decision["fields"]:
            sources[field] = "blind:arbitration"
            arbitrated.append(field)
            if field not in independent["fields"] or independent["fields"][field] != decision["fields"][field]:
                changed.append(field)
        all_judgments.extend([independent, decision])
    unresolved = set(FIELDS) - set(fields)
    if human is not None:
        decision = checked(human, "human", "human")
        if set(decision["fields"]) - unresolved:
            raise ValueError("human may only resolve unresolved fields")
        if decision["sequence"] <= max(value["sequence"] for value in all_judgments):
            raise ValueError("human review must follow independent review")
        fields.update(decision["fields"])
        human_fields = list(decision["fields"])
        sources.update({field: "blind:human" for field in human_fields})
        infrastructure_failure |= decision["status"] != "completed"
        all_judgments.append(decision)
    unresolved_disagreements = set(disagreements) - set(fields)
    complete = not infrastructure_failure and not unresolved_disagreements
    # Completed disagreement with no adopted answer is explicitly unreadable once
    # a completed arbitration/human decision has recorded that fact.
    if not infrastructure_failure and unresolved_disagreements and (arbitration is not None or human is not None):
        complete = True
    return {"fields": fields, "field_sources": sources, "complete": complete,
            "agreements": agreements, "disagreements": disagreements,
            "arbitrated_fields": arbitrated, "human_fields": human_fields,
            "changed_fields": changed, "judgments": all_judgments,
            "policy_sha256": frozen["sha256"], "evidence_sha256": content_digest(evidence),
            "elapsed_seconds": sum(value["elapsed_seconds"] for value in all_judgments),
            "cost": sum(value["cost"] for value in all_judgments),
            "technical_isolation_verified": False,
            "risk": "correlated judge errors; agreement is not correctness"}


def _prf(rows: list, field: str, classes: Sequence) -> dict:
    result = {}
    for label in classes:
        support = sum(row["target"][field] == label for row in rows)
        predicted = sum(row["semantics"]["fields"].get(field, object()) == label for row in rows)
        tp = sum(row["target"][field] == label and row["semantics"]["fields"].get(field, object()) == label for row in rows)
        precision = tp / predicted if predicted else (0.0 if support else None)
        recall = tp / support if support else None
        f1 = 2 * tp / (support + predicted) if support else None
        result[label] = {"precision": precision, "recall": recall, "f1": f1,
                         "support": support, "predicted": predicted, "true_positive": tp,
                         "false_positive": predicted - tp, "false_negative": support - tp}
    return result


def _mean_complete(values) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values and all(value is not None for value in values) else None


def _normalize_records(records: Sequence[Mapping]) -> list:
    rows, ids = [], set()
    for index, record in enumerate(records):
        target = _validate_target(record["target"])
        identity = record.get("sample_id", record.get("candidate_id", record.get("video_id", f"row-{index}")))
        if identity in ids:
            raise ValueError("duplicate fixed sample identity")
        ids.add(identity)
        semantic = record.get("semantics")
        if semantic is None:
            semantic = extract_semantics(record.get("raw_output"), runtime_error=record.get("runtime_error"),
                                         blind_review=record.get("blind_review"))
        if semantic.get("branch") not in BRANCHES or set(semantic.get("fields", {})) - set(FIELDS):
            raise ValueError("invalid semantic record")
        if any(not _legal(field, value) for field, value in semantic["fields"].items()):
            raise ValueError("semantic record has invalid fields")
        # Recompute deterministic branches rather than trusting supplied answers.
        if semantic.get("rules_sha256") != rules_digest():
            raise ValueError("semantic rules drift")
        if "raw_output" not in record:
            raise ValueError("semantic scoring requires frozen raw_output, including failed rows")
        if "raw_output" in record:
            expected = extract_semantics(record.get("raw_output"), runtime_error=record.get("runtime_error"),
                                         blind_review=record.get("blind_review"))
            if semantic != expected:
                raise ValueError("semantic evidence does not match frozen raw extraction")
        rows.append({**record, "target": target, "semantics": semantic})
    return rows


def _summarize(rows: list) -> dict:
    total = len(rows)
    metrics = {f"{field}_correct_rate": sum(field in row["semantics"]["fields"] and row["semantics"]["fields"][field] == row["target"][field] for row in rows) / total if total else None for field in FIELDS}
    metrics["joint_correct_rate"] = sum(all(field in row["semantics"]["fields"] and row["semantics"]["fields"][field] == row["target"][field] for field in FIELDS) for row in rows) / total if total else None
    metrics["strict_valid_rate"] = sum(row["semantics"]["strict_valid"] for row in rows) / total if total else None
    state_stats = _prf(rows, "clip_state", ENUMS["clip_state"])
    metrics["four_state_macro_recall"] = _mean_complete(state_stats[state]["recall"] for state in FOUR_STATES)
    for state in FOUR_STATES:
        metrics[f"{state}_recall"] = state_stats[state]["recall"]
    support = {"total": total, "clip_state": state_stats}
    diagnostics = {"branches": {}, "field_readable_rate": {}, "null_false_fill": {}}
    for branch in BRANCHES:
        count = sum(row["semantics"]["branch"] == branch for row in rows)
        diagnostics["branches"][branch] = {"count": count, "rate": count / total if total else None}
    for field in FIELDS:
        diagnostics["field_readable_rate"][field] = sum(field in row["semantics"]["fields"] for row in rows) / total if total else None
    for field in FIELDS[1:3]:
        applicable = [row for row in rows if row["target"][field] is not None]
        classes = [label for label in ENUMS[field] if label is not None]
        stats = _prf(applicable, field, classes)
        support[field] = {"applicable_total": len(applicable), "classes": stats}
        metrics[f"{field}_macro_f1"] = _mean_complete(stats[label]["f1"] for label in classes)
        null_rows = [row for row in rows if row["target"][field] is None]
        false_fill = sum(field in row["semantics"]["fields"] and row["semantics"]["fields"][field] is not None for row in null_rows)
        diagnostics["null_false_fill"][field] = {"support": len(null_rows), "count": false_fill, "rate": false_fill / len(null_rows) if null_rows else None}
    specials = _prf(rows, "special_case", [label for label in ENUMS["special_case"] if label is not None])
    support["special_case"] = specials
    for label, stats in specials.items():
        for metric in ("precision", "recall"):
            metrics[f"{label}_{metric}"] = stats[metric]
    diagnostics["runtime_failure_count"] = sum(bool(row.get("runtime_error")) for row in rows)
    diagnostics["review_incomplete_count"] = sum(not row["semantics"].get("review_complete", True) for row in rows)
    confusion = defaultdict(Counter)
    for row in rows:
        predicted = row["semantics"]["fields"].get("clip_state", "<missing>")
        confusion[row["target"]["clip_state"]][predicted] += 1
    diagnostics["clip_state_confusion"] = {key: dict(counts) for key, counts in confusion.items()}
    audits = [row["semantics"]["blind_audit"] for row in rows if "blind_audit" in row["semantics"]]
    blind_total = len(audits)
    blind_fields = blind_total * len(FIELDS)
    # One sealed judgment can be reused by several samples with identical raw.
    # Adoption/consistency remain sample-level, whereas actual compute work must
    # count each performed sealed judgment only once.
    unique_judgments = {judgment["sha256"]: judgment
                        for audit in audits for judgment in audit["judgments"]}
    diagnostics["blind_review"] = {
        "sample_count": blind_total,
        "agreement_rate": sum(len(audit["agreements"]) for audit in audits) / blind_fields if blind_fields else None,
        "disagreement_rate": sum(len(audit["disagreements"]) for audit in audits) / blind_fields if blind_fields else None,
        "arbitration_rate": sum(bool(audit["arbitrated_fields"]) for audit in audits) / blind_total if blind_total else None,
        "human_review_rate": sum(bool(audit["human_fields"]) for audit in audits) / blind_total if blind_total else None,
        "rate_definitions": {"agreement_rate": "expressed agreed fields / (4 * blind samples)",
                             "disagreement_rate": "disputed fields / (4 * blind samples)",
                             "arbitration_rate": "samples with adopted arbitrated fields / blind samples",
                             "human_review_rate": "samples with adopted human fields / blind samples"},
        **{key: sum(len(audit[key]) for audit in audits) for key in ("agreements", "disagreements", "arbitrated_fields", "human_fields", "changed_fields")},
        "unique_judgment_count": len(unique_judgments),
        "elapsed_seconds": sum(judgment["elapsed_seconds"] for judgment in unique_judgments.values()),
        "elapsed_seconds_definition": "sum of unique sealed judgment durations (compute work), not wall-clock latency",
        "cost": sum(judgment["cost"] for judgment in unique_judgments.values()),
        "cost_definition": "sum of cost for unique sealed judgments",
        "risk": "correlated judge errors; agreement is not correctness",
        "technical_isolation_verified": False,
    }
    return {"metrics": metrics, "support": support, "diagnostics": diagnostics}


def _quantile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def score_semantic_records(records: Sequence[Mapping], *, bootstrap=True) -> dict:
    """Score the supplied FIXED manifest rows, preserving every failure.

    The formal caller must compare row identities with its frozen manifest. A pure
    scorer cannot detect a sample deleted before invocation. No prediction filters
    or minimum-source/CI gates are applied here.
    """
    rows = _normalize_records(records)
    summary = _summarize(rows)
    if summary["diagnostics"]["review_incomplete_count"]:
        # Review infrastructure/unfinished judging is measurement pending, not
        # an observed visual mistake. Keep the full denominator and provisional
        # arithmetic for audit, but do not publish final visual rates or CIs.
        summary["diagnostics"]["provisional_metrics"] = dict(summary["metrics"])
        summary["metrics"] = {key: value if key == "strict_valid_rate" else None
                              for key, value in summary["metrics"].items()}
    groups = defaultdict(list)
    source_to_group = {}
    missing_group = False
    for row in rows:
        group = row.get("source_group", row.get("source_id"))
        if not isinstance(group, str) or not group:
            missing_group = True
            continue
        source = row.get("source_id")
        if source is not None:
            if source in source_to_group and source_to_group[source] != group:
                raise ValueError("source mapped to conflicting dependency groups")
            source_to_group[source] = group
        groups[group].append(row)
    summary["support"]["independent_group_count"] = len(groups) if not missing_group else None
    summary["support"]["group_sizes"] = {group: len(values) for group, values in sorted(groups.items())}
    summary["support"]["source_to_group"] = source_to_group
    summary["support"]["group_class_support"] = {group: {field: dict(Counter(row["target"][field] if row["target"][field] is not None else "<null>" for row in values)) for field in FIELDS} for group, values in sorted(groups.items())}
    summary["support"]["group_mapping_sha256"] = content_digest({group: [row.get("sample_id", row.get("candidate_id", row.get("video_id"))) for row in values] for group, values in sorted(groups.items())})
    summary["support"]["missing_group_mapping"] = missing_group
    strata = defaultdict(Counter)
    for row in rows:
        if "scenario" in row:
            strata[str(row["scenario"])][row["target"]["clip_state"]] += 1
    summary["support"]["scenario_support"] = {key: dict(value) for key, value in strata.items()}
    ci = {key: {"lower": None, "upper": None, "estimable": False,
                "reason": "bootstrap disabled" if not bootstrap else "missing dependency groups" if missing_group else "fewer than two groups"}
          for key in summary["metrics"]}
    if bootstrap and not missing_group and len(groups) >= 2:
        keys = list(groups)
        rng = random.Random(BOOTSTRAP_SEED)
        draws = {metric: [] for metric in summary["metrics"]}
        undefined = Counter()
        for _ in range(BOOTSTRAP_REPLICATES):
            sampled = [row for _ in keys for row in groups[rng.choice(keys)]]
            values = _summarize(sampled)["metrics"]
            for metric, value in values.items():
                if value is None:
                    undefined[metric] += 1
                else:
                    draws[metric].append(value)
        for metric, values in draws.items():
            # Do not discard missing-class draws to manufacture a conditional CI.
            if summary["metrics"][metric] is None or undefined[metric] or not values:
                ci[metric] = {"lower": None, "upper": None, "estimable": False,
                              "reason": "undefined metric in bootstrap replicates", "undefined_replicates": undefined[metric]}
            else:
                values.sort()
                ci[metric] = {"lower": _quantile(values, .025), "upper": _quantile(values, .975), "estimable": True, "undefined_replicates": 0}
    summary["confidence_intervals"] = {"method": "group-percentile-bootstrap", "replicates": BOOTSTRAP_REPLICATES,
                                       "seed": BOOTSTRAP_SEED, "confidence": .95, "metrics": ci}
    return summary


def development_gates(fold_records: Mapping, *, bootstrap=True) -> dict:
    """Every-fold state gates plus pooled sample metrics; no rounded comparisons."""
    if not isinstance(fold_records, Mapping) or not fold_records:
        raise ValueError("development gates require explicit fold records")
    normalized = {str(key): value for key, value in fold_records.items()}
    if len(normalized) != len(fold_records) or set(normalized) - {"0", "1", "2"}:
        raise ValueError("development fold identities must be 0/1/2 without duplicates")
    folds, gates, pooled_records, missing = {}, {}, [], []
    for fold, records in sorted(normalized.items()):
        summary = score_semantic_records(records, bootstrap=False)
        folds[fold] = summary
        pooled_records.extend(records)
        for metric, threshold in {"four_state_macro_recall": .65, **{f"{state}_recall": .50 for state in FOUR_STATES}}.items():
            value = summary["metrics"][metric]
            gates[f"fold_{fold}_{metric}"] = None if value is None else value >= threshold
            if value is None:
                missing.append(f"fold {fold}: {metric} support missing")
    pooled = score_semantic_records(pooled_records, bootstrap=bootstrap)
    for metric, threshold in {"joint_correct_rate": .50, "fracture_mechanism_macro_f1": .50, "fracture_site_macro_f1": .60}.items():
        value = pooled["metrics"][metric]
        gates[f"pooled_{metric}"] = None if value is None else value >= threshold
        if value is None:
            missing.append(f"pooled: {metric} support missing")
    if set(normalized) != {"0", "1", "2"}:
        missing.append("complete three-fold development evidence required")
    for label, stats in pooled["support"]["special_case"].items():
        if not stats["support"]:
            missing.append(f"pooled: special case {label} support missing")
    for fold, summary in folds.items():
        if summary["diagnostics"]["review_incomplete_count"]:
            missing.append(f"fold {fold}: blind review incomplete")
    # Missing classes cannot pass. No new arbitrary sample/source hard minimum.
    outcome = "insufficient_evidence" if missing else "passed" if all(gates.values()) else "failed"
    return {"protocol": PROTOCOL, "outcome": outcome, "gates": gates,
            "folds": folds, "pooled": pooled, "missing_evidence": missing}
