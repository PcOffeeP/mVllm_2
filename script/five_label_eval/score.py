"""Five-label scorer. Reads only explicit JSON/JSONL files; never opens media."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

VERSION = "five-label-score/3"
SINGLES = {
    "断裂状态": ("未断裂", "发生断裂", "已断裂", "无法判断"),
    "断裂模式": ("脆性断裂", "韧性断裂", "半脆半韧断裂", "无法判断"),
    "断裂位置": ("标距内", "标距外非根部", "夹持根部", "无法判断"),
}
MULTIS = {"异常情况": ("未夹紧", "视频异常", "爆炸性断裂"),
          "断裂现象": ("伸长", "颈缩", "开裂", "界面分离", "断后脱夹")}
FIELDS = tuple(SINGLES) + tuple(f"{group}.{item}" for group, items in MULTIS.items() for item in items)
REQUEST_KEYS = ("run_id", "model_id", "prompt_id", "input_id", "request_id")
IDENTITY = ("manifest_sha256", "candidate_id", "clip_sha256", "source_id", "source_type")
STATUS = ("success", "request_failed", "timeout", "unprocessed")
EVIDENCE = ("sufficient", "insufficient", "unknown")


from .errors import InputError


class Pairs(list):
    pass


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=Pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def materialize(value, path="", duplicates=None):
    duplicates = [] if duplicates is None else duplicates
    if isinstance(value, Pairs):
        counts = Counter(k for k, _ in value)
        result = {}
        for key, child in value:
            loc = f"{path}.{key}" if path else key
            if counts[key] > 1:
                if loc not in duplicates:
                    duplicates.append(loc)
                continue  # Never select first/last duplicate value.
            result[key] = materialize(child, loc, duplicates)
        return result
    if isinstance(value, list):
        return [materialize(v, f"{path}[{i}]", duplicates) for i, v in enumerate(value)]
    return value


def decode_file(raw, location):
    try:
        duplicates = []
        obj = materialize(parse_json(raw), duplicates=duplicates)
        if duplicates:
            raise InputError(f"{location}: duplicate keys: {duplicates}")
        return obj
    except (ValueError, TypeError) as exc:
        raise InputError(f"{location}: {exc}") from exc


def read_json(path):
    return decode_file(Path(path).read_text(encoding="utf-8"), str(path))


def read_jsonl(path):
    if path is None:
        return []
    rows = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        obj = decode_file(raw, f"{path}:{number}")
        if not isinstance(obj, dict):
            raise InputError(f"{path}:{number}: expected object")
        rows.append({**obj, "_ref": f"{path}:{number}"})
    return rows


def require_text(row, key, where):
    if not isinstance(row.get(key), str) or not row[key].strip():
        raise InputError(f"{where}: missing/invalid {key}")


def validate_identity(row, where):
    for key in IDENTITY:
        require_text(row, key, where)
    for key in ("manifest_sha256", "clip_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", row[key]):
            raise InputError(f"{where}: {key} must be lowercase SHA256")
    if row["source_type"] not in ("real", "virtual"):
        raise InputError(f"{where}: invalid source_type")


def flatten(labels):
    if not isinstance(labels, dict):
        return {f: None for f in FIELDS}
    out = {f: labels.get(f) for f in SINGLES}
    for group, items in MULTIS.items():
        obj = labels.get(group)
        for item in items:
            out[f"{group}.{item}"] = obj.get(item) if isinstance(obj, dict) else None
    return out


def allowed(field):
    return SINGLES[field] if field in SINGLES else ("是", "否", "无法判断")


def truth_cell(field, value):
    if value is None or value == "":
        return {"status": "unlabeled", "value": value}
    if not isinstance(value, str) or value not in allowed(field):
        return {"status": "invalid", "value": value}
    return {"status": "valid", "value": value}


def human_truth(labels):
    result = {f: truth_cell(f, v) for f, v in flatten(labels).items()}
    if labels is None:
        return result
    if not isinstance(labels, dict):
        return {f: {"status": "invalid", "value": labels} for f in FIELDS}
    for group, items in MULTIS.items():
        if group in labels and not isinstance(labels[group], dict):
            for item in items:
                result[f"{group}.{item}"] = {"status": "invalid", "value": labels[group]}
    return result


def combinations(flat):
    conflicts = []
    state = flat.get("断裂状态")
    if state == "未断裂":
        for field in ("异常情况.爆炸性断裂", "断裂现象.断后脱夹"):
            if flat.get(field) == "是":
                conflicts.append(f"{field}: 与未断裂冲突")
    return conflicts


def extract(raw):
    """Keep excessive model-output nesting from interrupting other samples."""
    try:
        return _extract(raw)
    except RecursionError:
        return {"fields": {f: {"status": "extraction_failed", "value": None} for f in FIELDS},
                "strict_format_valid": False, "issues": ["model_output_nesting_exceeds_recursion_limit"],
                "conflicts": []}


def _extract(raw):
    """Parse exactly one object, optionally fenced or surrounded by prose."""
    issues, duplicates = [], []
    if not isinstance(raw, str):
        return {"fields": {f: {"status": "extraction_failed", "value": None} for f in FIELDS},
                "strict_format_valid": False, "issues": ["raw_output is not string"], "conflicts": []}
    stripped = raw.strip()
    exact = True
    try:
        parsed = parse_json(stripped)
    except ValueError:
        exact = False
        decoder = json.JSONDecoder(object_pairs_hook=Pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        candidates = []
        for i, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                obj, end = decoder.raw_decode(stripped, i)
                if isinstance(obj, Pairs):
                    candidates.append((i, end, obj))
            except ValueError:
                pass
        # Nested objects belong to their enclosing object, not separate candidates.
        outer = [c for c in candidates if not any(a < c[0] < b for a, b, _ in candidates)]
        if len(outer) != 1:
            return {"fields": {f: {"status": "extraction_failed", "value": None} for f in FIELDS},
                    "strict_format_valid": False, "issues": ["not exactly one extractable JSON object"], "conflicts": []}
        parsed = outer[0][2]
        issues.append("surrounding_text_or_fence")
    obj = materialize(parsed, duplicates=duplicates)
    if not isinstance(obj, dict):
        return {"fields": {f: {"status": "extraction_failed", "value": None} for f in FIELDS},
                "strict_format_valid": False, "issues": ["top level is not object"], "conflicts": []}
    expected = set(SINGLES) | set(MULTIS)
    if set(obj) != expected:
        issues.append("top_level_keys_mismatch")
    for group, items in MULTIS.items():
        if not isinstance(obj.get(group), dict) or set(obj[group]) != set(items):
            issues.append(f"{group}: expected explicit per-item object")
    issues.extend(f"duplicate_key:{p}" for p in duplicates)
    flat = flatten(obj)
    fields = {}
    for field in FIELDS:
        parent = field.split(".")[0]
        if any(field == p or field.startswith(p + ".") for p in duplicates):
            status = "invalid"
        elif "." in field and parent in obj and not isinstance(obj[parent], dict):
            status = "invalid"  # [] never means all negative.
        elif field in SINGLES and field not in obj:
            status = "missing"
        elif "." in field and (parent not in obj or field.split(".")[1] not in obj.get(parent, {})):
            status = "missing"
        elif not isinstance(flat[field], str) or flat[field] not in allowed(field):
            status = "invalid"
        else:
            status = "valid"
        fields[field] = {"status": status, "value": flat[field]}
    strict = exact and not issues and all(x["status"] == "valid" for x in fields.values())
    return {"fields": fields, "strict_format_valid": strict, "issues": issues,
            "conflicts": combinations({f: x["value"] for f, x in fields.items() if x["status"] == "valid"})}


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "reason": None if denominator else "证据不足／无法计算"}


def request_identity(row):
    return tuple(row.get(k) for k in ("candidate_id", "clip_sha256") + REQUEST_KEYS)


def prepare(manifest, reviews, predictions, input_reviews=(), *, exclusions=None, enforce_exclusions=True):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("samples"), list):
        raise InputError("manifest must contain samples array")
    require_text(manifest, "manifest_version", "manifest")
    samples = {}
    source_types = {}
    for sample in manifest["samples"]:
        if not isinstance(sample, dict):
            raise InputError("manifest sample must be object")
        validate_identity(sample, "manifest sample")
        cid = sample["candidate_id"]
        if cid in samples:
            raise InputError(f"duplicate candidate_id {cid} (including same name/different digest)")
        if "review_id" not in sample or (sample["review_id"] is not None and
                                           (not isinstance(sample["review_id"], str) or not sample["review_id"].strip())):
            raise InputError(f"{cid}: review_id must explicitly be null or nonempty ID")
        sid = sample["source_id"]
        if sid in source_types and source_types[sid] != sample["source_type"]:
            raise InputError(f"source_type conflict: {sid}")
        source_types[sid] = sample["source_type"]
        samples[cid] = sample
    if enforce_exclusions:
        from .exclusions import load_dev_exclusions
        active_exclusions = exclusions if exclusions is not None else load_dev_exclusions()
        active_exclusions.assert_no_excluded(list(samples.values()), context="score manifest")
    review_index = {}
    for review in reviews:
        validate_identity(review, "review")
        if review.get("review_status") == "unreviewed" and review.get("review_id") is None:
            if review.get("labels") not in (None, {}):
                raise InputError("unreviewed placeholder cannot contain labels")
            cid = review["candidate_id"]
            if cid in samples and any(review[k] != samples[cid][k] for k in IDENTITY):
                raise InputError(f"unreviewed review identity mismatch: {cid}")
            key = (cid, None)
            if key in review_index:
                raise InputError(f"duplicate unreviewed placeholder: {cid}")
            review_index[key] = review
            continue
        require_text(review, "review_id", "review")
        if review.get("review_status") not in ("confirmed", "draft", "returned", "question"):
            raise InputError("invalid review_status")
        key = (review["candidate_id"], review["review_id"])
        if key in review_index:
            raise InputError(f"duplicate review revision {key}")
        review_index[key] = review
    pred_index = {}
    run_identity = None
    for pred in predictions:
        for key in ("candidate_id", "clip_sha256") + REQUEST_KEYS:
            require_text(pred, key, "prediction")
        if pred.get("input_review_id") is not None and (not isinstance(pred["input_review_id"], str) or not pred["input_review_id"].strip()):
            raise InputError("prediction input_review_id must be null or nonempty string")
        if pred.get("status") not in STATUS:
            raise InputError(f"invalid prediction status: {pred.get('status')}")
        if "raw_output" not in pred or (pred["raw_output"] is not None and not isinstance(pred["raw_output"], str)):
            raise InputError("prediction must preserve raw_output as string or null")
        current_run = tuple(pred[k] for k in ("run_id", "model_id", "prompt_id"))
        if run_identity is not None and run_identity != current_run:
            raise InputError("one scoring batch must have one run_id/model_id/prompt_id")
        run_identity = current_run
        cid = pred["candidate_id"]
        if cid not in samples or pred["clip_sha256"] != samples[cid]["clip_sha256"]:
            raise InputError(f"prediction candidate/digest mismatch: {cid}")
        if cid in pred_index:
            raise InputError(f"multiple predictions for {cid}; explicitly select one request per batch")
        pred_index[cid] = pred
    input_index = {}
    for review in input_reviews:
        for key in ("candidate_id", "clip_sha256") + REQUEST_KEYS + ("input_review_id",):
            require_text(review, key, "input review")
        key = (request_identity(review), review["input_review_id"])
        if key in input_index:
            raise InputError(f"duplicate input review revision {key}")
        if review.get("review_status") not in ("confirmed", "draft", "returned", "question"):
            raise InputError("invalid input review_status")
        pred = pred_index.get(review["candidate_id"])
        if pred is None or request_identity(pred) != request_identity(review):
            raise InputError(f"input review is not bound to exact prediction request: {key}")
        input_index[key] = review
    rows = []
    for cid, sample in samples.items():
        rid = sample["review_id"]
        review = review_index.get((cid, rid)) if rid is not None else None
        if rid is not None and review is None:
            raise InputError(f"locked review not found: {cid}/{rid}")
        if review is not None:
            for key in IDENTITY:
                if review[key] != sample[key]:
                    raise InputError(f"locked review identity mismatch: {cid}/{key}")
        confirmed = review is not None and review["review_status"] == "confirmed"
        truth = human_truth(review.get("labels") if confirmed else None)
        pred = pred_index.get(cid)
        status = pred["status"] if pred else "unprocessed"
        extraction = extract(pred["raw_output"]) if status == "success" else {
            "fields": {f: {"status": status, "value": None} for f in FIELDS},
            "strict_format_valid": False, "issues": [], "conflicts": []}
        input_rid = pred.get("input_review_id") if pred else None
        ir = input_index.get((request_identity(pred), input_rid)) if pred and input_rid is not None else None
        if input_rid is not None and ir is None:
            raise InputError(f"locked input review not found: {cid}/{input_rid}")
        input_truth, evidence = {}, {}
        input_confirmed = ir is not None and ir["review_status"] == "confirmed"
        if input_confirmed:
            if not isinstance(ir.get("fields"), dict):
                raise InputError(f"{cid}: confirmed input review requires fields object")
            for group in MULTIS:
                if group in ir["fields"] and not isinstance(ir["fields"][group], dict):
                    raise InputError(f"{cid}: input review {group} must be per-item object")
        cells = flatten(ir.get("fields") if input_confirmed else None)
        for field, cell in cells.items():
            if not input_confirmed or cell is None:
                evidence[field], input_truth[field] = "unreviewed", truth_cell(field, None)
                continue
            if not isinstance(cell, dict) or cell.get("evidence") not in EVIDENCE or "label" not in cell:
                raise InputError(f"{cid}: invalid input review cell {field}")
            evidence[field] = cell["evidence"]
            input_truth[field] = truth_cell(field, cell["label"])
            if cell["evidence"] in ("insufficient", "unknown") and cell["label"] not in (None, "", "无法确定", "无法判断"):
                raise InputError(f"{cid}: insufficient/unknown evidence cannot assert certain label: {field}")
        rows.append({"sample": sample, "review_status": review["review_status"] if review else "unreviewed",
                     "truth": truth, "truth_conflicts": combinations({f: c["value"] for f, c in truth.items() if c["status"] == "valid"}),
                     "prediction_status": status, "prediction": pred, "extraction": extraction,
                     "input_review_status": ir["review_status"] if ir else "unreviewed", "input_truth": input_truth,
                     "input_evidence": evidence})
    return rows


def field_metrics(rows, field, truth_key):
    truth_counts, truth_values, pred_counts, failures, confusion = Counter(), Counter(), Counter(), Counter(), Counter()
    prediction_by_truth = {}
    source_sets = {}
    correct = attempted = tp = fn = fp = tn = 0
    positives = negatives = 0
    layered = field in ("断裂模式", "断裂位置")
    excluded = {}
    all_attempted = human_uncertain = model_uncertain = 0
    for row in rows:
        human = row[truth_key][field]
        pred = row["extraction"]["fields"][field]
        truth_counts[human["status"]] += 1
        bucket = human["value"] if human["status"] == "valid" else human["status"]
        truth_values[str(bucket)] += 1
        source_sets.setdefault(str(bucket), set()).add(row["sample"]["source_id"])
        pstatus = pred["status"]
        pred_counts[pstatus] += 1
        prediction_by_truth.setdefault(str(bucket), Counter())[str(pred["value"]) if pstatus == "valid" else f"<{pstatus}>"] += 1
        if pstatus == "valid" and pred["value"] in ("无法确定", "无法判断"):
            pred_counts["explicit_uncertain"] += 1
        eligible = row["prediction_status"] != "unprocessed" and human["status"] == "valid"
        state = row[truth_key]["断裂状态"]
        in_layer = eligible and state["status"] == "valid" and state["value"] in ("发生断裂", "已断裂")
        if layered and not in_layer:
            state_key = str(state["value"]) if state["status"] == "valid" else f"<{state['status']}>"
            value_key = str(human["value"]) if human["status"] == "valid" else f"<{human['status']}>"
            excluded.setdefault(state_key, Counter())[value_key] += 1
        if not eligible:
            continue
        h, p = human["value"], pred["value"]
        all_attempted += 1
        human_uncertain += h == "无法判断"
        model_uncertain += pstatus == "valid" and p == "无法判断"
        if pstatus != "valid" or (p == "无法判断" and field not in SINGLES and h != "无法判断"):
            failures[f"{h}:{pstatus if pstatus != 'valid' else 'explicit_uncertain'}"] += 1
        if layered and not in_layer:
            continue
        attempted += 1
        correct += pstatus == "valid" and h == p
        category = p if pstatus == "valid" else f"<{pstatus}>"
        confusion[(h, category)] += 1
        if field not in SINGLES:
            positives += h == "是"
            negatives += h == "否"
            if pstatus == "valid" and p in ("是", "否"):
                tp += h == "是" and p == "是"
                fn += h == "是" and p == "否"
                fp += h == "否" and p == "是"
                tn += h == "否" and p == "否"
    result = {"truth_counts": dict(truth_counts), "truth_value_counts": dict(truth_values),
              "prediction_by_truth": {k: dict(v) for k, v in prediction_by_truth.items()}, "prediction_counts": dict(pred_counts),
              "truth_source_counts": {k: len(v) for k, v in source_sets.items()},
              "accuracy": ratio(correct, attempted), "failures_or_uncertain_by_truth": dict(failures),
              "classes": {label: {"recall": ratio(confusion[(label, label)],
                                                  sum(n for (h, _), n in confusion.items() if h == label)),
                                   "precision": ratio(confusion[(label, label)],
                                                      sum(n for (_, p), n in confusion.items() if p == label))}
                          for label in allowed(field)},
              "uncertain_rate": {"human": ratio(human_uncertain, all_attempted),
                                 "model": ratio(model_uncertain, all_attempted)},
              "confusion": [{"truth": h, "prediction": p, "count": n} for (h, p), n in sorted(confusion.items())]}
    if layered:
        result["layered"] = {"fracture_states": ["发生断裂", "已断裂"], "denominator": attempted,
                             "excluded_clips": sum(sum(counts.values()) for counts in excluded.values()),
                             "excluded_distribution": {key: dict(counts) for key, counts in excluded.items()}}
    if field not in SINGLES:
        certain = [n for (h, _), n in confusion.items() if h in ("是", "否")]
        uncertain = [n for (h, p), n in confusion.items() if h in ("是", "否") and p == "无法判断"]
        result.update({"TP": tp, "FN": fn, "FP": fp, "TN": tn,
                       "positive_attempted": positives, "negative_attempted": negatives,
                       "recall": ratio(tp, positives), "precision": ratio(tp, tp + fp),
                       "false_positive_rate_explicit_only": ratio(fp, fp + tn),
                       "over_uncertain_rate": ratio(sum(uncertain), sum(certain))})
    return result


def aggregate(rows, truth_key):
    eligible = [r for r in rows if r["prediction_status"] != "unprocessed"
                and all(c["status"] == "valid" for c in r[truth_key].values())]
    # 派生变更（随 truth_cell 口径「无法判断 一律 valid」）：人工为「无法判断」的多选叶项
    # 不再使片段失去资格，含多选人工无法判断的片段自 five-label-score/2 起进入本比率分母。
    # 计算逻辑本身未改：分母仍是「11 个叶字段真值全 valid 且请求已尝试」。
    joint = sum(all(r["extraction"]["fields"][f]["status"] == "valid" and
                        r["extraction"]["fields"][f]["value"] == r[truth_key][f]["value"] for f in FIELDS) for r in eligible)
    attempted = sum(r["prediction_status"] != "unprocessed" for r in rows)
    return {"clips": len(rows), "sources": len({r["sample"]["source_id"] for r in rows}),
            "request_status_counts": dict(Counter(r["prediction_status"] for r in rows)),
            "review_status_counts": dict(Counter(r["review_status" if truth_key == "truth" else "input_review_status"] for r in rows)),
            "strict_format_valid": ratio(sum(r["extraction"]["strict_format_valid"] for r in rows), attempted),
            "prediction_combination_conflicts": sum(bool(r["extraction"]["conflicts"]) for r in rows),
            "human_combination_conflicts": sum(bool(combinations({f: c["value"] for f, c in r[truth_key].items() if c["status"] == "valid"})) for r in rows),
            "all_five_correct_supplement": ratio(joint, len(eligible)),
            "fields": {f: field_metrics(rows, f, truth_key) for f in FIELDS}}


def _score_impl(manifest, reviews, predictions, input_reviews=(), *, exclusions=None, enforce_exclusions=True):
    rows = prepare(manifest, reviews, predictions, input_reviews,
                   exclusions=exclusions, enforce_exclusions=enforce_exclusions)
    groups = {}
    for source_type in ("real", "virtual"):
        selected = [r for r in rows if r["sample"]["source_type"] == source_type]
        full, actual = aggregate(selected, "truth"), aggregate(selected, "input_truth")
        actual["evidence_by_field"] = {}
        for field in FIELDS:
            actual["evidence_by_field"][field] = {
                e: {"clips": len(subset), "sources": len({r["sample"]["source_id"] for r in subset}),
                    "metrics": field_metrics(subset, field, "input_truth")}
                for e in EVIDENCE + ("unreviewed",)
                for subset in ([r for r in selected if r["input_evidence"][field] == e],)}
        groups[source_type] = {"full_clip": full, "actual_input": actual,
                               "by_source": {sid: {"full_clip": aggregate(subset, "truth"),
                                                   "actual_input": aggregate(subset, "input_truth")}
                                             for sid in sorted({r["sample"]["source_id"] for r in selected})
                                             for subset in ([r for r in selected if r["sample"]["source_id"] == sid],)}}
    return {"scoring_version": VERSION, "supplementary_formula_status": "user_confirmed_supplementary_statistics", "manifest_version": manifest["manifest_version"],
            "groups": groups, "samples": rows,
            "limits": ["No media opened; human reviews are supplied inputs, not independently verified.",
                       "Full-clip and actual-input truth remain separate. No weighted overall score, thresholds, promotion or release."]}


def score(manifest, reviews, predictions, input_reviews=()):
    return _score_impl(manifest, reviews, predictions, input_reviews)


def display_ratio(metric):
    value = "证据不足／无法计算" if metric["value"] is None else f"{metric['value']:.4f}"
    return f"{metric['numerator']}/{metric['denominator']} = {value}"


def report(result):
    lines = [f"# 五类标签评分（{VERSION}）", "", "完整片段与实际输入分别计分；真实与虚拟分别报告。无加权总分、阈值或晋级。", "精确率、显式负例误报率、五类全对是用户已确认的补充统计，不设通过阈值或自动晋级。", ""]
    for kind, data in result["groups"].items():
        for basis in ("full_clip", "actual_input"):
            group = data[basis]
            lines.extend([f"## {kind} / {basis}", "", f"片段 {group['clips']}；来源 {group['sources']}；请求状态 {json.dumps(group['request_status_counts'], ensure_ascii=False)}；审核状态 {json.dumps(group['review_status_counts'], ensure_ascii=False)}。",
                          f"格式严格合法：{display_ratio(group['strict_format_valid'])}；预测组合冲突 {group['prediction_combination_conflicts']}；人工组合冲突 {group['human_combination_conflicts']}。",
                          f"五类全对（补充）：{display_ratio(group['all_five_correct_supplement'])}。", ""])
            for field, metrics in group["fields"].items():
                lines.extend([f"### {field}", "", f"准确率 {display_ratio(metrics['accuracy'])}；真值状态计数 {json.dumps(metrics['truth_counts'], ensure_ascii=False)}；真值取值计数 {json.dumps(metrics['truth_value_counts'], ensure_ascii=False)}；来源数 {json.dumps(metrics['truth_source_counts'], ensure_ascii=False)}。",
                              f"预测字段状态 {json.dumps(metrics['prediction_counts'], ensure_ascii=False)}；失败／不确定按真值 {json.dumps(metrics['failures_or_uncertain_by_truth'], ensure_ascii=False)}。"])
                if "layered" in metrics:
                    layer = metrics["layered"]
                    lines.append(f"分层：断裂状态 {json.dumps(layer['fracture_states'], ensure_ascii=False)}；分母 {layer['denominator']}；排除 {layer['excluded_clips']}。断裂状态下不计比例（仅参考分布）：{json.dumps(layer['excluded_distribution'], ensure_ascii=False)}。")
                if "classes" in metrics:
                    for label, values in metrics["classes"].items():
                        lines.append(f"- {label}：精确率（precision）{display_ratio(values['precision'])}；召回 {display_ratio(values['recall'])}")
                lines.append(f"无法判断率（uncertain_rate）：人工 {display_ratio(metrics['uncertain_rate']['human'])}；模型 {display_ratio(metrics['uncertain_rate']['model'])}。")
                if "over_uncertain_rate" in metrics:
                    lines.append(f"过度不确定率（over_uncertain_rate）：预测无法判断而人工为是或否 {display_ratio(metrics['over_uncertain_rate'])}。")
                if "TP" in metrics:
                    lines.append(f"TP={metrics['TP']} FN={metrics['FN']} FP={metrics['FP']} TN={metrics['TN']}；识别比例 {display_ratio(metrics['recall'])}；精确率 {display_ratio(metrics['precision'])}；仅显式可判断负例误报率 {display_ratio(metrics['false_positive_rate_explicit_only'])}。")
                lines.append(f"混淆：`{json.dumps(metrics['confusion'], ensure_ascii=False)}`")
                if basis == "actual_input":
                    for e, info in group["evidence_by_field"][field].items():
                        lines.append(f"- 输入证据 {e}：片段 {info['clips']}、来源 {info['sources']}；独立输入答案准确率 {display_ratio(info['metrics']['accuracy'])}")
                lines.append("")
        lines.extend([f"## {kind} / 逐来源", ""])
        for sid, source in data["by_source"].items():
            lines.append(f"### {sid}")
            for basis, summary in source.items():
                lines.append(f"- {basis}：片段 {summary['clips']}；请求 {json.dumps(summary['request_status_counts'], ensure_ascii=False)}；五类全对 {display_ratio(summary['all_five_correct_supplement'])}")
                for field, metrics in summary["fields"].items():
                    lines.append(f"  - {field}：准确率 {display_ratio(metrics['accuracy'])}" + (f"；识别比例 {display_ratio(metrics['recall'])}" if "recall" in metrics else ""))
            lines.append("")
    lines.extend(["## 逐片段追溯", "", "结构化结果的 samples 保留每项真值、提取状态、实际输入证据及原回答；以下列出身份和引用。", ""])
    for row in result["samples"]:
        pred = row["prediction"] or {}
        lines.append(f"### {row['sample']['candidate_id']} / {row['sample']['source_type']} / {row['sample']['source_id']}")
        lines.extend(["", f"片段摘要 {row['sample']['clip_sha256']}；{row['prediction_status']}；raw 引用 {pred.get('_ref', '无记录')}；请求 {pred.get('request_id', '无')}；冲突 {json.dumps(row['extraction']['conflicts'], ensure_ascii=False)}；格式问题 {json.dumps(row['extraction']['issues'], ensure_ascii=False)}。", ""])
        for field in FIELDS:
            human, actual, extracted = row['truth'][field], row['input_truth'][field], row['extraction']['fields'][field]
            def outcome(cell):
                if cell['status'] != 'valid':
                    return '不比较:' + cell['status']
                if row['prediction_status'] == 'unprocessed':
                    return '未处理'
                return '正确' if extracted['status'] == 'valid' and extracted['value'] == cell['value'] else '未正确'
            lines.append(f"- {field}：片段真值 {json.dumps(human, ensure_ascii=False)}；预测 {json.dumps(extracted, ensure_ascii=False)} → {outcome(human)}；输入证据 {row['input_evidence'][field]}／真值 {json.dumps(actual, ensure_ascii=False)} → {outcome(actual)}")
        lines.append("")
    lines.extend(["", "限制：只读取显式本地 JSON/JSONL，未打开媒体、运行模型或验证人审内容。"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--input-reviews")
    parser.add_argument("--output", required=True, help="New output directory; refuses existing directory")
    parser.add_argument("--exclusions", help="DEC-007 dev-exclusions JSON; defaults to data/splits/dev-exclusions.json")
    parser.add_argument("--allow-excluded", action="store_true", help="Disable DEC-007 exclusion guard (forensic use only)")
    args = parser.parse_args(argv)
    try:
        from .exclusions import load_dev_exclusions
        exclusions = None if args.allow_excluded else load_dev_exclusions(args.exclusions)
        paths = {k: Path(v) for k, v in vars(args).items()
                 if k not in ("output", "exclusions", "allow_excluded") and v is not None}
        result = _score_impl(read_json(args.manifest), read_jsonl(args.reviews), read_jsonl(args.predictions),
                             read_jsonl(args.input_reviews), exclusions=exclusions, enforce_exclusions=not args.allow_excluded)
        result["input_files"] = {k: {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for k, p in paths.items()}
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=False)
        (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "report.md").write_text(report(result), encoding="utf-8")
        print(f"Wrote {output}/results.json and report.md ({len(result['samples'])} manifest samples)")
        return 0
    except (InputError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
