"""Hand-calculated examples; all records and hashes here are synthetic.

Scoring contract under test is version ``five-label-score/3``: human
"无法判断" is a legal, comparable class on all 11 leaf fields (3 single-choice
plus 8 multi-item leaves), with per-class precision/recall, an explicit
human-vs-model uncertainty-rate comparison, and a multi-item-only
``over_uncertain_rate``. Requests that failed, timed out, were never processed
or whose extraction failed are still never treated as "无法判断".

Fragment-label rule change: the single values 断裂模式/断裂位置 no longer contain
"无". Accuracy, per-class precision/recall and the confusion matrix of exactly
those two fields are stratified by 断裂状态 (只有「发生断裂」「已断裂」进入分母),
while ``uncertain_rate`` keeps using every attempted clip.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from script.five_label_eval.score import (FIELDS, SINGLES, VERSION, InputError, combinations,
                                          extract, main, report, score, truth_cell)

MULTI_FIELDS = tuple(f for f in FIELDS if f not in SINGLES)
MULTI_LABELS = ("是", "否", "无法判断")


def labels():
    return {"断裂状态": "发生断裂", "断裂模式": "韧性断裂", "断裂位置": "标距内",
            "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
            "断裂现象": {"伸长": "是", "颈缩": "否", "开裂": "否", "界面分离": "否", "断后脱夹": "否"}}


def fixture(n=1):
    samples = [{"manifest_sha256": "a" * 64, "candidate_id": f"c{i}", "clip_sha256": f"{i+1:064x}",
                "source_id": f"s{i}", "source_type": "real", "review_id": f"r{i}"} for i in range(n)]
    reviews = [{**s, "review_status": "confirmed", "labels": labels()} for s in samples]
    preds = [{"candidate_id": s["candidate_id"], "clip_sha256": s["clip_sha256"], "run_id": "run",
              "model_id": "model", "prompt_id": "prompt", "input_id": f"input{i}", "request_id": f"request{i}",
              "status": "success", "raw_output": json.dumps(labels(), ensure_ascii=False)} for i, s in enumerate(samples)]
    return {"manifest_version": "synthetic/1", "samples": samples}, reviews, preds


def prediction_with(field, value):
    """Model output equal to ``labels()`` except for one leaf field."""
    obj = labels()
    if "." in field:
        group, item = field.split(".")
        obj[group][item] = value
    else:
        obj[field] = value
    return json.dumps(obj, ensure_ascii=False)


def halves(metric):
    return (metric["numerator"], metric["denominator"])


def layered_fixture(humans, models):
    """One clip per (human, model) pair; both are overrides of ``labels()``."""
    m, r, p = fixture(len(humans))
    for i, (human, model) in enumerate(zip(humans, models)):
        human_labels = labels()
        human_labels.update(human)
        r[i]["labels"] = human_labels
        output = labels()
        output.update(model)
        p[i]["raw_output"] = json.dumps(output, ensure_ascii=False)
    return m, r, p


def field_blocks(rendered):
    """Split ``report()`` into ``{(basis, field): text}`` blocks."""
    blocks, basis, current = {}, None, None
    for line in rendered.splitlines():
        if line.startswith("## "):
            basis, current = line[3:].strip(), None
        elif line.startswith("### "):
            current = (basis, line[4:].strip())
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {key: "\n".join(lines) for key, lines in blocks.items()}


class ScoreTests(unittest.TestCase):
    def test_confirmed_supplementary_denominators_exclude_only_ineligible_rows(self):
        # Ten invented clips: TP, FN, missing, explicit-uncertain, FP, TN,
        # request failure, human uncertain leaf, human blank, unprocessed.
        m, r, p = fixture(10)
        for i in (4, 5, 6):
            r[i]["labels"]["断裂现象"]["伸长"] = "否"
        r[4]["labels"]["断裂状态"] = "已断裂"
        r[7]["labels"]["断裂现象"]["伸长"] = "无法判断"
        r[7]["labels"]["断裂状态"] = ""
        r[8]["labels"]["断裂现象"]["伸长"] = ""
        r[8]["labels"]["断裂状态"] = "illegal-label"
        for i, value in enumerate(("是", "否", None, "无法判断", "是", "否", "是", "是", "是", "是")):
            output = labels()
            if value is None:
                del output["断裂现象"]["伸长"]
                del output["断裂状态"]
            else:
                output["断裂现象"]["伸长"] = value
            if i == 3:
                output["断裂状态"] = "无法判断"
            p[i]["raw_output"] = json.dumps(output)
        p[6]["status"] = "request_failed"
        p[9]["status"] = "unprocessed"
        result = score(m, r, p)
        group = result["groups"]["real"]["full_clip"]
        phenomenon = group["fields"]["断裂现象.伸长"]
        self.assertEqual((phenomenon["TP"], phenomenon["FN"], phenomenon["FP"], phenomenon["TN"]), (1, 1, 1, 1))
        # Legacy 是/否 detectors keep their own denominators.
        for key, pair in (("precision", (1, 2)), ("false_positive_rate_explicit_only", (1, 2)), ("recall", (1, 4))):
            self.assertEqual(halves(phenomenon[key]), pair)
        self.assertEqual(phenomenon["failures_or_uncertain_by_truth"],
                         {"是:missing": 1, "是:explicit_uncertain": 1, "否:request_failed": 1})
        # Human 无法判断 is now valid: only the blank leaf stays unlabeled.
        self.assertEqual(phenomenon["truth_counts"], {"valid": 9, "unlabeled": 1})
        self.assertEqual(phenomenon["prediction_counts"]["unprocessed"], 1)
        # Accuracy counts the human-uncertain clip as attempted and wrong (2/8).
        self.assertEqual(halves(phenomenon["accuracy"]), (2, 8))
        # Per-class recall/precision over attempted and truth-valid rows only.
        self.assertEqual(halves(phenomenon["classes"]["是"]["recall"]), (1, 4))
        self.assertEqual(halves(phenomenon["classes"]["是"]["precision"]), (1, 3))
        self.assertEqual(halves(phenomenon["classes"]["否"]["recall"]), (1, 3))
        self.assertEqual(halves(phenomenon["classes"]["否"]["precision"]), (1, 2))
        self.assertEqual(halves(phenomenon["classes"]["无法判断"]["recall"]), (0, 1))
        self.assertEqual(halves(phenomenon["classes"]["无法判断"]["precision"]), (0, 1))
        self.assertEqual(halves(phenomenon["over_uncertain_rate"]), (1, 7))
        self.assertEqual(halves(phenomenon["uncertain_rate"]["human"]), (1, 8))
        self.assertEqual(halves(phenomenon["uncertain_rate"]["model"]), (1, 8))
        state_precision = group["fields"]["断裂状态"]["classes"]["发生断裂"]["precision"]
        self.assertEqual(halves(state_precision), (3, 4))
        joint = group["all_five_correct_supplement"]
        self.assertEqual(halves(joint), (2, 7))
        self.assertEqual(result["supplementary_formula_status"], "user_confirmed_supplementary_statistics")
        rendered = report(result)
        self.assertIn("用户已确认的补充统计", rendered)
        self.assertNotIn("尚待正式确认", rendered)

        # Single-choice 无法判断 仍是合法可比较类别，不是 unknown truth status。
        # 断裂状态 不分层，精确率照常计分；模式/位置只计断裂状态 ∈ {发生断裂, 已断裂}
        # 的片段，因此这里的人工片段被排除在分层之外（分母 0），而不是被判成不可比较。
        m, r, p = fixture()
        uncertain = labels()
        for field in ("断裂状态", "断裂模式", "断裂位置"):
            uncertain[field] = "无法判断"
        r[0]["labels"] = uncertain
        p[0]["raw_output"] = json.dumps(uncertain)
        group = score(m, r, p)["groups"]["real"]["full_clip"]
        self.assertEqual(group["all_five_correct_supplement"]["value"], 1)
        state = group["fields"]["断裂状态"]
        self.assertEqual(halves(state["classes"]["无法判断"]["precision"]), (1, 1))
        self.assertEqual(state["failures_or_uncertain_by_truth"], {})
        self.assertEqual(state["truth_counts"], {"valid": 1})
        self.assertNotIn("layered", state)
        for field in ("断裂模式", "断裂位置"):
            metrics = group["fields"][field]
            # 无法判断 仍是 valid 真值（不是 unlabeled/invalid），只是该片段不进分层。
            self.assertEqual(metrics["truth_counts"], {"valid": 1})
            self.assertEqual(halves(metrics["accuracy"]), (0, 0))
            self.assertIsNone(metrics["accuracy"]["value"])
            self.assertEqual(halves(metrics["classes"]["无法判断"]["recall"]), (0, 0))
            self.assertIsNone(metrics["classes"]["无法判断"]["recall"]["value"])
            self.assertEqual(halves(metrics["classes"]["无法判断"]["precision"]), (0, 0))
            self.assertIsNone(metrics["classes"]["无法判断"]["precision"]["value"])
            self.assertEqual(metrics["failures_or_uncertain_by_truth"], {})
            self.assertEqual(metrics["layered"]["denominator"], 0)
            self.assertEqual(metrics["layered"]["excluded_clips"], 1)
            self.assertEqual(metrics["layered"]["excluded_distribution"]["无法判断"], {"无法判断": 1})

    def test_hand_calculated_multilabel_failures_uncertainty_and_sources(self):
        # 8 real: 4 attempted positives (TP,FN,failed,uncertain), 3 negatives
        # (FP,TN,timeout), 1 unprocessed positive. One virtual TP is isolated.
        m, r, p = fixture(9)
        m["samples"][8]["source_type"] = r[8]["source_type"] = "virtual"
        for i in (4, 5, 6):
            r[i]["labels"]["断裂现象"]["伸长"] = "否"
        outputs = ["是", "否", None, "无法判断", "是", "否", None, None, "是"]
        for i, val in enumerate(outputs):
            if val is not None:
                obj = labels()
                obj["断裂现象"]["伸长"] = val
                p[i]["raw_output"] = json.dumps(obj)
        p[2]["status"] = "request_failed"
        p[6]["status"] = "timeout"
        del p[7]
        result = score(m, r, p)
        real = result["groups"]["real"]["full_clip"]
        f = real["fields"]["断裂现象.伸长"]
        self.assertEqual((f["TP"], f["FN"], f["FP"], f["TN"]), (1, 1, 1, 1))
        self.assertEqual((f["recall"]["numerator"], f["recall"]["denominator"]), (1, 4))
        self.assertEqual(f["precision"]["value"], .5)
        self.assertEqual(f["false_positive_rate_explicit_only"]["value"], .5)
        self.assertEqual(f["accuracy"]["value"], 2/7)
        self.assertEqual(f["failures_or_uncertain_by_truth"], {"是:request_failed": 1, "是:explicit_uncertain": 1, "否:timeout": 1})
        self.assertEqual(f["truth_value_counts"], {"是": 5, "否": 3})
        self.assertEqual(f["truth_source_counts"], {"是": 5, "否": 3})
        self.assertEqual(real["sources"], 8)
        self.assertEqual(result["groups"]["virtual"]["full_clip"]["fields"]["断裂现象.伸长"]["recall"]["value"], 1)
        self.assertEqual(real["all_five_correct_supplement"]["numerator"], 2)
        self.assertEqual(real["all_five_correct_supplement"]["denominator"], 7)
        # No human 无法判断 leaf here: recall denominator for that class is 0,
        # but the model's single 无法判断 answer is a measurable false alarm.
        self.assertEqual(halves(f["classes"]["是"]["recall"]), (1, 4))
        self.assertEqual(halves(f["classes"]["是"]["precision"]), (1, 2))
        self.assertEqual(halves(f["classes"]["否"]["recall"]), (1, 3))
        self.assertEqual(halves(f["classes"]["否"]["precision"]), (1, 2))
        self.assertEqual(halves(f["classes"]["无法判断"]["recall"]), (0, 0))
        self.assertIsNone(f["classes"]["无法判断"]["recall"]["value"])
        self.assertEqual(halves(f["classes"]["无法判断"]["precision"]), (0, 1))
        self.assertEqual(halves(f["over_uncertain_rate"]), (1, 7))
        self.assertEqual(halves(f["uncertain_rate"]["human"]), (0, 7))
        self.assertEqual(halves(f["uncertain_rate"]["model"]), (1, 7))

    def test_unknown_blank_missing_and_single_uncertain_are_separate(self):
        m, r, p = fixture(4)
        r[0]["labels"]["断裂现象"]["伸长"] = "无法判断"
        r[1]["labels"]["断裂现象"]["伸长"] = ""
        r[2]["labels"]["断裂状态"] = "无法判断"
        obj = labels()
        obj["断裂状态"] = "无法判断"
        p[2]["raw_output"] = json.dumps(obj)
        obj = labels()
        del obj["断裂现象"]["伸长"]
        p[3]["raw_output"] = json.dumps(obj)
        a = score(m, r, p)["groups"]["real"]["full_clip"]
        f = a["fields"]["断裂现象.伸长"]
        self.assertEqual(f["truth_counts"], {"valid": 3, "unlabeled": 1})
        self.assertEqual(f["recall"]["value"], .5)
        self.assertEqual(f["FN"], 0)
        self.assertEqual(f["failures_or_uncertain_by_truth"], {"是:missing": 1})
        self.assertEqual(halves(f["classes"]["无法判断"]["recall"]), (0, 1))
        self.assertEqual(halves(f["classes"]["无法判断"]["precision"]), (0, 0))
        self.assertIsNone(f["classes"]["无法判断"]["precision"]["value"])
        self.assertEqual(halves(f["over_uncertain_rate"]), (0, 2))
        self.assertEqual(f["over_uncertain_rate"]["value"], 0.0)
        self.assertEqual(halves(f["uncertain_rate"]["human"]), (1, 3))
        self.assertEqual(halves(f["uncertain_rate"]["model"]), (0, 3))
        self.assertEqual(a["fields"]["断裂状态"]["classes"]["无法判断"]["recall"]["value"], 1)
        # A single-choice 无法判断 matched by the model is a comparable class, not
        # an explicit-uncertain failure.
        self.assertEqual(a["fields"]["断裂状态"]["failures_or_uncertain_by_truth"], {})
        self.assertEqual((a["fields"]["断裂状态"]["accuracy"]["numerator"],
                          a["fields"]["断裂状态"]["accuracy"]["denominator"]), (4, 4))
        # The human-uncertain leaf is truth-valid, so its clip now enters the
        # all-five denominator even though that leaf was answered wrongly.
        self.assertEqual(halves(a["all_five_correct_supplement"]), (1, 3))

    def test_explicit_uncertain_failure_requires_certain_human_truth(self):
        # One prediction value 无法判断: an ordinary correct class on a single-choice
        # field, an explicit_uncertain failure on a multi-item field only when the
        # human truth is a definite 是/否.
        m, r, p = fixture(1)
        r[0]["labels"]["断裂状态"] = "无法判断"
        obj = labels()
        obj["断裂状态"] = "无法判断"
        obj["断裂现象"]["伸长"] = "无法判断"
        p[0]["raw_output"] = json.dumps(obj)
        a = score(m, r, p)["groups"]["real"]["full_clip"]
        state, elongation = a["fields"]["断裂状态"], a["fields"]["断裂现象.伸长"]
        self.assertEqual((state["accuracy"]["numerator"], state["accuracy"]["denominator"]), (1, 1))
        self.assertEqual(state["failures_or_uncertain_by_truth"], {})
        self.assertEqual((elongation["accuracy"]["numerator"],
                          elongation["accuracy"]["denominator"]), (0, 1))
        self.assertEqual(elongation["failures_or_uncertain_by_truth"], {"是:explicit_uncertain": 1})

        # Same prediction value with a human 无法判断 leaf is a correct answer and
        # must not appear in the failure/uncertain counter.
        m, r, p = fixture(1)
        r[0]["labels"]["断裂现象"]["伸长"] = "无法判断"
        p[0]["raw_output"] = prediction_with("断裂现象.伸长", "无法判断")
        a = score(m, r, p)["groups"]["real"]["full_clip"]
        elongation = a["fields"]["断裂现象.伸长"]
        self.assertEqual(elongation["failures_or_uncertain_by_truth"], {})
        self.assertEqual(halves(elongation["accuracy"]), (1, 1))
        self.assertEqual(halves(elongation["classes"]["无法判断"]["recall"]), (1, 1))
        self.assertEqual(halves(elongation["classes"]["无法判断"]["precision"]), (1, 1))
        self.assertEqual(halves(elongation["uncertain_rate"]["human"]), (1, 1))
        self.assertEqual(halves(elongation["uncertain_rate"]["model"]), (1, 1))

    def test_all_labels_use_unified_uncertain_term_and_truth_cell_contract(self):
        for field in SINGLES:
            with self.subTest(field=field):
                self.assertIn("无法判断", SINGLES[field])
                self.assertNotIn("无法确定", SINGLES[field])
        for field in FIELDS:
            with self.subTest(field=field):
                self.assertEqual(truth_cell(field, "无法判断"), {"status": "valid", "value": "无法判断"})
                self.assertEqual(truth_cell(field, "")["status"], "unlabeled")
                self.assertEqual(truth_cell(field, None)["status"], "unlabeled")
                self.assertEqual(truth_cell(field, "无法确定")["status"], "invalid")
        for field in MULTI_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(truth_cell(field, "无")["status"], "invalid")
                self.assertEqual(truth_cell(field, "也许")["status"], "invalid")
        m, r, p = fixture()
        result = score(m, r, p)
        for basis in ("full_clip", "actual_input"):
            for field, metrics in result["groups"]["real"][basis]["fields"].items():
                self.assertNotIn("unknown", metrics["truth_counts"])

    def test_multi_leaf_uncertain_is_comparable_class_with_own_rates(self):
        # Seven invented clips for 断裂现象.伸长 as (human, model):
        # (是,是) (是,否) (否,无法判断) (无法判断,无法判断) (无法判断,是)
        # ("",是) (是,invalid value 不确定)
        m, r, p = fixture(7)
        humans = ["是", "是", "否", "无法判断", "无法判断", "", "是"]
        models = ["是", "否", "无法判断", "无法判断", "是", "是", "不确定"]
        for i, (human, model) in enumerate(zip(humans, models)):
            r[i]["labels"]["断裂现象"]["伸长"] = human
            p[i]["raw_output"] = prediction_with("断裂现象.伸长", model)
        group = score(m, r, p)["groups"]["real"]["full_clip"]
        metrics = group["fields"]["断裂现象.伸长"]

        self.assertEqual(metrics["truth_counts"], {"valid": 6, "unlabeled": 1})
        self.assertEqual(halves(metrics["accuracy"]), (2, 6))
        self.assertEqual((metrics["TP"], metrics["FN"], metrics["FP"], metrics["TN"]), (1, 1, 0, 0))
        self.assertEqual(halves(metrics["classes"]["是"]["recall"]), (1, 3))
        self.assertEqual(halves(metrics["classes"]["是"]["precision"]), (1, 2))
        self.assertEqual(halves(metrics["classes"]["否"]["recall"]), (0, 1))
        self.assertEqual(halves(metrics["classes"]["否"]["precision"]), (0, 1))
        self.assertEqual(halves(metrics["classes"]["无法判断"]["recall"]), (1, 2))
        self.assertEqual(halves(metrics["classes"]["无法判断"]["precision"]), (1, 2))
        self.assertEqual(halves(metrics["over_uncertain_rate"]), (1, 4))
        self.assertEqual(metrics["over_uncertain_rate"]["value"], 0.25)
        self.assertEqual(halves(metrics["uncertain_rate"]["human"]), (2, 6))
        self.assertEqual(halves(metrics["uncertain_rate"]["model"]), (2, 6))
        # Failures keep their own vocabulary: an invalid model value stays a
        # failure, a correct 无法判断/无法判断 pair does not.
        self.assertEqual(metrics["failures_or_uncertain_by_truth"],
                         {"否:explicit_uncertain": 1, "是:invalid": 1})
        self.assertNotIn("over_uncertain_rate", group["fields"]["断裂状态"])

    def test_class_metrics_and_over_uncertain_are_published_per_field(self):
        m, r, p = fixture()
        full = score(m, r, p)["groups"]["real"]["full_clip"]
        for field in FIELDS:
            with self.subTest(field=field):
                self.assertIn("classes", full["fields"][field])
                self.assertIn("human", full["fields"][field]["uncertain_rate"])
                self.assertIn("model", full["fields"][field]["uncertain_rate"])
                self.assertEqual(set(full["fields"][field]["uncertain_rate"]["human"]),
                                 {"numerator", "denominator", "value", "reason"})
        for field in SINGLES:
            with self.subTest(field=field):
                self.assertEqual(set(full["fields"][field]["classes"]), set(SINGLES[field]))
                self.assertNotIn("over_uncertain_rate", full["fields"][field])
        for field in MULTI_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(set(full["fields"][field]["classes"]), set(MULTI_LABELS))
                self.assertIn("over_uncertain_rate", full["fields"][field])
        # One clip, everything answered: every untouched label has 0/0 evidence.
        unmatched = full["fields"]["断裂状态"]["classes"]
        self.assertEqual(halves(unmatched["未断裂"]["recall"]), (0, 0))
        self.assertIsNone(unmatched["未断裂"]["recall"]["value"])
        self.assertIsNone(unmatched["未断裂"]["precision"]["value"])
        self.assertIsNone(unmatched["无法判断"]["recall"]["value"])
        elongation = full["fields"]["断裂现象.伸长"]
        self.assertIsNone(elongation["classes"]["否"]["recall"]["value"])
        self.assertIsNone(elongation["classes"]["无法判断"]["precision"]["value"])
        # A 0 numerator over a non-empty denominator is 0.0, not "no evidence".
        self.assertEqual(elongation["over_uncertain_rate"]["value"], 0.0)
        self.assertEqual(halves(elongation["over_uncertain_rate"]), (0, 1))
        self.assertEqual(elongation["uncertain_rate"]["human"]["value"], 0.0)
        self.assertEqual(elongation["uncertain_rate"]["model"]["value"], 0.0)
        self.assertIsNone(elongation["uncertain_rate"]["human"]["reason"])

    def test_uncertain_rate_is_none_when_nothing_was_attempted(self):
        m, r, p = fixture()
        p[0]["status"] = "unprocessed"
        result = score(m, r, p)
        real = result["groups"]["real"]["full_clip"]
        for field in FIELDS:
            with self.subTest(field=field):
                self.assertEqual(halves(real["fields"][field]["uncertain_rate"]["human"]), (0, 0))
                self.assertIsNone(real["fields"][field]["uncertain_rate"]["human"]["value"])
                self.assertIsNone(real["fields"][field]["uncertain_rate"]["model"]["value"])
                self.assertIsNotNone(real["fields"][field]["uncertain_rate"]["human"]["reason"])
                self.assertIsNone(real["fields"][field]["accuracy"]["value"])
        virtual = result["groups"]["virtual"]["full_clip"]
        for field in FIELDS:
            with self.subTest(field=field):
                self.assertIsNone(virtual["fields"][field]["uncertain_rate"]["human"]["value"])
                self.assertEqual(halves(virtual["fields"][field]["classes"]["无法判断"]["recall"]), (0, 0))
                self.assertIsNone(virtual["fields"][field]["classes"]["无法判断"]["recall"]["value"])
        for field in MULTI_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(halves(virtual["fields"][field]["over_uncertain_rate"]), (0, 0))
                self.assertIsNone(virtual["fields"][field]["over_uncertain_rate"]["value"])

    def test_all_five_supplement_counts_clip_whose_multi_leaf_truth_is_uncertain(self):
        m, r, p = fixture()
        r[0]["labels"]["断裂现象"]["伸长"] = "无法判断"
        p[0]["raw_output"] = prediction_with("断裂现象.伸长", "无法判断")
        group = score(m, r, p)["groups"]["real"]["full_clip"]
        joint = group["all_five_correct_supplement"]
        self.assertEqual(halves(joint), (1, 1))
        elongation = group["fields"]["断裂现象.伸长"]
        self.assertEqual(halves(elongation["accuracy"]), (1, 1))
        self.assertEqual(elongation["failures_or_uncertain_by_truth"], {})
        self.assertEqual(halves(elongation["classes"]["无法判断"]["recall"]), (1, 1))
        # The uncertain human leaf leaves no 是/否 rows, so the over-uncertain
        # guard has nothing to measure on this field.
        self.assertEqual(halves(elongation["over_uncertain_rate"]), (0, 0))
        self.assertIsNone(elongation["over_uncertain_rate"]["value"])
        self.assertEqual(halves(group["fields"]["异常情况.未夹紧"]["over_uncertain_rate"]), (0, 1))

    def test_version_and_report_expose_new_contract(self):
        m, r, p = fixture(5)
        humans = ["无法判断", "是", "是", "否", "否"]
        models = ["无法判断", "无法判断", "是", "否", "是"]
        for i, (human, model) in enumerate(zip(humans, models)):
            r[i]["labels"]["断裂现象"]["伸长"] = human
            p[i]["raw_output"] = prediction_with("断裂现象.伸长", model)
        result = score(m, r, p)
        self.assertEqual(VERSION, "five-label-score/3")
        self.assertEqual(result["scoring_version"], "five-label-score/3")
        rendered = report(result)
        self.assertIn("five-label-score/3", rendered.splitlines()[0])
        # Walk the rendered sections so each field's block is checked on its own.
        blocks, basis, current = {}, None, None
        for line in rendered.splitlines():
            if line.startswith("## "):
                basis, current = line[3:].strip(), None
            elif line.startswith("### "):
                current = (basis, line[4:].strip())
                blocks[current] = []
            elif current is not None:
                blocks[current].append(line)
        text = {key: "\n".join(lines) for key, lines in blocks.items()}
        for field in FIELDS:
            with self.subTest(field=field):
                self.assertIn(("real / full_clip", field), text)
        elongation = text[("real / full_clip", "断裂现象.伸长")]
        self.assertIn("1/5", elongation)  # 人工无法判断率 1/5
        self.assertIn("2/5", elongation)  # 模型无法判断率 2/5
        self.assertIn("1/4", elongation)  # over_uncertain_rate 1/4
        self.assertIn("over_uncertain_rate", elongation)
        self.assertIn("uncertain_rate", elongation)
        self.assertIn("无法判断", elongation)
        state = text[("real / full_clip", "断裂状态")]
        self.assertIn("uncertain_rate", state)
        self.assertIn("无法判断", state)
        self.assertNotIn("over_uncertain_rate", state)

    def test_extraction_duplicates_partial_empty_lists_fence_and_conflicts(self):
        raw = json.dumps(labels(), ensure_ascii=False)
        duplicate = raw.replace('"断裂状态": "发生断裂"', '"断裂状态": "发生断裂", "断裂状态": "已断裂"')
        x = extract(duplicate)
        self.assertEqual(x["fields"]["断裂状态"]["status"], "invalid")
        self.assertEqual(x["fields"]["断裂位置"]["value"], "标距内")
        self.assertFalse(x["strict_format_valid"])
        obj = labels()
        obj["异常情况"] = []
        x = extract(json.dumps(obj))
        self.assertEqual(x["fields"]["异常情况.未夹紧"]["status"], "invalid")
        self.assertTrue(extract(raw)["strict_format_valid"])
        self.assertFalse(extract('```json\n' + raw + '\n```')["strict_format_valid"])
        self.assertEqual(extract(raw + raw)["fields"]["断裂位置"]["status"], "extraction_failed")
        self.assertEqual(extract('not json')["fields"]["断裂位置"]["status"], "extraction_failed")
        obj = labels()
        obj["断裂状态"] = "未断裂"
        obj["异常情况"]["爆炸性断裂"] = "是"
        x = extract(json.dumps(obj))
        self.assertTrue(x["strict_format_valid"])
        # 未断裂 + 具体模式/位置已不再是冲突，只剩「未断裂 与 爆炸性断裂」一条。
        self.assertEqual(len(x["conflicts"]), 1, x["conflicts"])
        self.assertIn("爆炸性断裂", x["conflicts"][0])
        m, r, p = fixture()
        r[0]["labels"] = obj
        p[0]["raw_output"] = json.dumps(obj)
        scored = score(m, r, p)["groups"]["real"]["full_clip"]
        self.assertEqual(scored["prediction_combination_conflicts"], 1)
        self.assertEqual(scored["all_five_correct_supplement"]["value"], 1)

    def test_excessive_model_output_nesting_does_not_abort_batch(self):
        # Exercise both exact JSON and the fallback for surrounding prose.
        pathological = [
            '[' * 1100 + '0' + ']' * 1100,
            'answer: {"unexpected":' + '[' * 1100 + '0' + ']' * 1100 + '}',
        ]
        for raw in pathological:
            with self.subTest(nesting=len(raw)):
                m, r, p = fixture(2)
                p[0]["raw_output"] = raw
                result = score(m, r, p)
                first, second = result["samples"]
                self.assertEqual(first["prediction"]["raw_output"], raw)
                self.assertTrue(all(cell["status"] == "extraction_failed"
                                    for cell in first["extraction"]["fields"].values()))
                self.assertFalse(first["extraction"]["strict_format_valid"])
                self.assertIn("model_output_nesting_exceeds_recursion_limit",
                              first["extraction"]["issues"])
                self.assertTrue(second["extraction"]["strict_format_valid"])
                metric = result["groups"]["real"]["full_clip"]["fields"]["断裂状态"]
                self.assertEqual((metric["accuracy"]["numerator"], metric["accuracy"]["denominator"]), (1, 2))
                self.assertEqual(metric["failures_or_uncertain_by_truth"], {"发生断裂:extraction_failed": 1})
                self.assertEqual(halves(metric["uncertain_rate"]["model"]), (0, 2))

        # Recursion may also arise during conversion after decoding succeeds.
        # Inject it explicitly so this case is independent of Python stack depth.
        with patch("script.five_label_eval.score.materialize", side_effect=RecursionError):
            self.assertEqual(extract('{}')["fields"]["断裂状态"]["status"], "extraction_failed")
        with patch("script.five_label_eval.score.materialize", side_effect=TypeError("unexpected bug")):
            with self.assertRaisesRegex(TypeError, "unexpected bug"):
                extract('{}')

    def test_no_value_is_rejected_and_unfractured_clips_stay_out_of_stratified_metrics(self):
        # 「无」不再是断裂模式/断裂位置的合法单值，也不再是可比较类别；
        # 未断裂片段的这两个字段判对也不进分层统计（accuracy 分母为 0）。
        m, r, p = fixture()
        obj = labels()
        obj.update({"断裂状态": "未断裂", "断裂模式": "无法判断", "断裂位置": "无法判断"})
        r[0]["labels"] = obj
        p[0]["raw_output"] = json.dumps(obj)
        a = score(m, r, p)["groups"]["real"]["full_clip"]

        self.assertNotIn("无", SINGLES["断裂模式"])
        self.assertNotIn("无", SINGLES["断裂位置"])
        self.assertNotIn("无", a["fields"]["断裂模式"]["classes"])
        self.assertNotIn("无", a["fields"]["断裂位置"]["classes"])
        self.assertEqual(truth_cell("断裂模式", "无")["status"], "invalid")
        self.assertEqual(truth_cell("断裂位置", "无")["status"], "invalid")
        # 唯一的片段是未断裂：模式/位置的分层分母为空。
        self.assertEqual(halves(a["fields"]["断裂模式"]["accuracy"]), (0, 0))
        self.assertIsNone(a["fields"]["断裂模式"]["accuracy"]["value"])
        mode_layered = a["fields"]["断裂模式"].get("layered")
        self.assertIsNotNone(mode_layered, "断裂模式 指标必须带 layered 分层说明")
        self.assertEqual(mode_layered["denominator"], 0)
        # 断裂状态不受分层影响，仍是全量已尝试片段。
        self.assertEqual(a["fields"]["断裂状态"]["accuracy"]["value"], 1)
        # 多选字段仍按原口径报「没有正/负例证据」。
        self.assertIsNone(a["fields"]["异常情况.爆炸性断裂"]["recall"]["value"])
        self.assertIsNone(a["fields"]["断裂现象.伸长"]["false_positive_rate_explicit_only"]["value"])
        self.assertEqual(halves(a["fields"]["异常情况.爆炸性断裂"]["classes"]["是"]["recall"]), (0, 0))
        self.assertIsNone(a["fields"]["异常情况.爆炸性断裂"]["classes"]["是"]["recall"]["value"])

    def test_layered_metrics_drop_unfractured_clip_from_accuracy_and_class_denominators(self):
        # c0 发生断裂 / c1 已断裂 进分层；c2 未断裂，模式判错也不影响分层指标。
        m, r, p = layered_fixture(
            [{"断裂状态": "发生断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内"},
             {"断裂状态": "已断裂", "断裂模式": "脆性断裂", "断裂位置": "夹持根部"},
             {"断裂状态": "未断裂", "断裂模式": "韧性断裂", "断裂位置": "标距内"}],
            [{"断裂状态": "发生断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内"},
             {"断裂状态": "已断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内"},
             {"断裂状态": "未断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内"}])

        group = score(m, r, p)["groups"]["real"]["full_clip"]
        mode, location = group["fields"]["断裂模式"], group["fields"]["断裂位置"]

        # 未断裂片段（模式判错）不得拉低准确率：2/3 → 2/2。
        self.assertEqual(halves(mode["accuracy"]), (2, 2))
        self.assertEqual(set(mode["classes"]), set(SINGLES["断裂模式"]))
        self.assertEqual(halves(mode["classes"]["脆性断裂"]["recall"]), (2, 2))
        # 人工「韧性断裂」只出现在未断裂片段上：召回与精确率分母均为 0。
        self.assertEqual(halves(mode["classes"]["韧性断裂"]["recall"]), (0, 0))
        self.assertEqual(halves(mode["classes"]["韧性断裂"]["precision"]), (0, 0))
        self.assertEqual(mode["confusion"],
                         [{"truth": "脆性断裂", "prediction": "脆性断裂", "count": 2}])
        # 断裂位置同样分层：c1 的位置判错仍计入（两个片段都在分层内）。
        self.assertEqual(halves(location["accuracy"]), (1, 2))
        self.assertEqual(halves(location["classes"]["夹持根部"]["recall"]), (0, 1))
        # 其余 9 个字段不变：断裂状态仍按全部已尝试片段计分。
        self.assertEqual(halves(group["fields"]["断裂状态"]["accuracy"]), (3, 3))
        self.assertNotIn("layered", group["fields"]["断裂状态"])
        self.assertNotIn("layered", group["fields"]["断裂现象.伸长"])

    def test_layered_counts_only_fractured_clips_and_reports_excluded_distribution(self):
        m, r, p = layered_fixture(
            [{"断裂状态": "发生断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内"},
             {"断裂状态": "已断裂", "断裂模式": "半脆半韧断裂", "断裂位置": "标距外非根部"},
             {"断裂状态": "未断裂", "断裂模式": "韧性断裂", "断裂位置": "夹持根部"}],
            [{}, {}, {}])

        group = score(m, r, p)["groups"]["real"]["full_clip"]
        layered = group["fields"]["断裂模式"].get("layered")
        self.assertIsNotNone(layered, "断裂模式 指标必须带 layered 分层说明")

        self.assertEqual(layered["fracture_states"], ["发生断裂", "已断裂"])
        # 分母只数断裂状态为发生断裂/已断裂的片段。
        self.assertEqual(layered["denominator"], 2)
        self.assertEqual(layered["excluded_clips"], 1)
        # 排除片段按人工该字段取值进单列分布，不计算比例。
        self.assertEqual(layered["excluded_distribution"]["未断裂"], {"韧性断裂": 1})
        self.assertEqual(group["fields"]["断裂位置"]["layered"]["excluded_distribution"]["未断裂"],
                         {"夹持根部": 1})

    def test_uncertain_rate_keeps_every_attempted_clip_after_layering(self):
        # c2 未断裂且模型答「无法判断」：它不进模式准确率分母，但仍是无法判断率的分母。
        m, r, p = layered_fixture(
            [{"断裂状态": "发生断裂", "断裂模式": "脆性断裂"},
             {"断裂状态": "已断裂", "断裂模式": "脆性断裂"},
             {"断裂状态": "未断裂", "断裂模式": "韧性断裂"}],
            [{"断裂状态": "发生断裂", "断裂模式": "脆性断裂"},
             {"断裂状态": "已断裂", "断裂模式": "脆性断裂"},
             {"断裂状态": "未断裂", "断裂模式": "无法判断"}])

        mode = score(m, r, p)["groups"]["real"]["full_clip"]["fields"]["断裂模式"]

        self.assertEqual(halves(mode["accuracy"]), (2, 2))
        # 分母仍是全部 3 个已尝试片段，不因分层缩成 2。
        self.assertEqual(halves(mode["uncertain_rate"]["model"]), (1, 3))
        self.assertEqual(halves(mode["uncertain_rate"]["human"]), (0, 3))

    def test_report_prints_layered_distribution_as_reference_without_ratio(self):
        m, r, p = layered_fixture(
            [{"断裂状态": "发生断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内"},
             {"断裂状态": "未断裂", "断裂模式": "韧性断裂", "断裂位置": "夹持根部"}],
            [{}, {}])

        text = field_blocks(report(score(m, r, p)))

        for field in ("断裂模式", "断裂位置"):
            block = text[("real / full_clip", field)]
            self.assertIn("不计比例", block, f"{field} 段落必须显式说明分层分布不计比例")
            # 分布行要能看出被排除的断裂状态与人工取值，避免被当成分数。
            self.assertIn("未断裂", block, f"{field} 段落应打印被排除的断裂状态")
        self.assertIn("韧性断裂", text[("real / full_clip", "断裂模式")])
        self.assertNotIn("不计比例", text[("real / full_clip", "断裂状态")])

    def test_combinations_allow_concrete_mode_and_location_when_unfractured(self):
        # 新规则：未断裂或未夹紧不再要求「无」/「无法判断」，按可见证据作答即可。
        unfractured = {"断裂状态": "未断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内",
                       "异常情况.未夹紧": "否"}
        self.assertEqual(combinations(unfractured), [])
        unclamped = {"断裂状态": "无法判断", "断裂模式": "韧性断裂", "断裂位置": "夹持根部",
                     "异常情况.未夹紧": "是"}
        self.assertEqual(combinations(unclamped), [])
        # 保留的互斥仍然生效：未断裂 + 爆炸性断裂=是 / 未断裂 + 断后脱夹=是。
        explosive = combinations({"断裂状态": "未断裂", "断裂模式": "无法判断", "断裂位置": "无法判断",
                                  "异常情况.爆炸性断裂": "是"})
        self.assertEqual(len(explosive), 1, explosive)
        self.assertIn("爆炸性断裂", explosive[0])
        release = combinations({"断裂状态": "未断裂", "断裂现象.断后脱夹": "是"})
        self.assertEqual(len(release), 1, release)
        self.assertIn("断后脱夹", release[0])

    def test_locked_reviews_drafts_and_unreviewed_placeholders(self):
        m, r, p = fixture(2)
        r.append({**copy.deepcopy(r[0]), "review_id": "new", "labels": {}})
        r[1]["review_status"] = "draft"
        result = score(m, r, p)
        self.assertEqual(result["samples"][0]["truth"]["断裂状态"]["value"], "发生断裂")
        self.assertEqual(result["samples"][1]["truth"]["断裂状态"]["status"], "unlabeled")
        m["samples"][1]["review_id"] = None
        r[1].update(review_status="unreviewed", review_id=None, labels={})
        self.assertEqual(score(m, r, p)["samples"][1]["review_status"], "unreviewed")

    def test_identity_ambiguities_rejected(self):
        def bad(mutate):
            m, r, p = fixture()
            mutate(m, r, p)
            with self.assertRaises(InputError):
                score(m, r, p)
        bad(lambda m, r, p: m["samples"].append({**m["samples"][0], "clip_sha256": "b" * 64}))
        bad(lambda m, r, p: r.append(copy.deepcopy(r[0])))
        bad(lambda m, r, p: p.append(copy.deepcopy(p[0])))
        bad(lambda m, r, p: p[0].update(clip_sha256="b" * 64))
        bad(lambda m, r, p: r[0].update(manifest_sha256="b" * 64))
        bad(lambda m, r, p: m["samples"][0].pop("review_id"))
        bad(lambda m, r, p: m["samples"][0].update(review_id="missing"))
        bad(lambda m, r, p: p[0].pop("input_id"))
        m, r, p = fixture(2)
        p[1]["model_id"] = "other"
        with self.assertRaises(InputError):
            score(m, r, p)

    def test_actual_input_review_is_independent_and_exactly_bound(self):
        m, r, p = fixture()
        p[0]["input_review_id"] = "ir1"
        fields = {"断裂状态": {"evidence": "insufficient", "label": "无法判断"},
                  "断裂现象": {"伸长": {"evidence": "insufficient", "label": "无法判断"},
                               "颈缩": {"evidence": "sufficient", "label": "是"}}}
        ir = {**{k: v for k, v in p[0].items() if k not in ("raw_output", "status")},
              "review_status": "confirmed", "fields": fields}
        result = score(m, r, p, [ir])
        real = result["groups"]["real"]
        self.assertEqual(real["full_clip"]["all_five_correct_supplement"]["value"], 1)
        self.assertEqual(real["actual_input"]["fields"]["断裂状态"]["accuracy"]["value"], 0)
        self.assertEqual(real["actual_input"]["fields"]["断裂现象.颈缩"]["recall"]["value"], 0)
        self.assertIsNone(real["actual_input"]["fields"]["断裂现象.伸长"]["recall"]["value"])
        # A human 无法判断 input truth is a comparable class here too.
        self.assertEqual(halves(real["actual_input"]["fields"]["断裂状态"]["classes"]["无法判断"]["recall"]), (0, 1))
        self.assertEqual(halves(real["actual_input"]["fields"]["断裂现象.伸长"]["classes"]["无法判断"]["recall"]), (0, 1))
        self.assertEqual(halves(real["actual_input"]["fields"]["断裂现象.伸长"]["over_uncertain_rate"]), (0, 0))
        self.assertEqual(real["actual_input"]["evidence_by_field"]["断裂状态"]["insufficient"]["clips"], 1)
        self.assertEqual(real["actual_input"]["evidence_by_field"]["断裂位置"]["unreviewed"]["clips"], 1)
        ir["input_id"] = "wrong"
        with self.assertRaises(InputError):
            score(m, r, p, [ir])
        ir["input_id"] = p[0]["input_id"]
        ir["fields"]["断裂状态"]["label"] = "发生断裂"
        with self.assertRaises(InputError):
            score(m, r, p, [ir])

    def test_cli_real_jsonl_duplicate_keys_and_preserved_raw(self):
        m, r, p = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
            (root / "reviews.jsonl").write_text(json.dumps(r[0]) + "\n", encoding="utf-8")
            (root / "predictions.jsonl").write_text(json.dumps(p[0]) + "\n", encoding="utf-8")
            args = ["--manifest", str(root / "manifest.json"), "--reviews", str(root / "reviews.jsonl"),
                    "--predictions", str(root / "predictions.jsonl"), "--output", str(root / "out")]
            self.assertEqual(main(args), 0)
            result = json.loads((root / "out/results.json").read_text())
            self.assertEqual(result["samples"][0]["prediction"]["raw_output"], p[0]["raw_output"])
            self.assertIn("input_files", result)
            self.assertEqual(result["scoring_version"], "five-label-score/3")
            fields = result["groups"]["real"]["full_clip"]["fields"]
            self.assertEqual(halves(fields["断裂现象.伸长"]["over_uncertain_rate"]), (0, 1))
            self.assertEqual(halves(fields["断裂现象.伸长"]["uncertain_rate"]["human"]), (0, 1))
            self.assertEqual(set(fields["断裂现象.伸长"]["classes"]), set(MULTI_LABELS))
            self.assertTrue((root / "out/report.md").exists())
            self.assertIn("five-label-score/3", (root / "out/report.md").read_text())
            self.assertEqual(main(args), 2)  # Never overwrite outputs.
            (root / "manifest.json").write_text('{"manifest_version":"a","manifest_version":"b"}')
            self.assertEqual(main(args[:-1] + [str(root / "other")]), 2)


if __name__ == "__main__":
    unittest.main()
