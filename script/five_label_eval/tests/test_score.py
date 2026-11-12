"""Hand-calculated examples; all records and hashes here are synthetic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from script.five_label_eval.score import FIELDS, InputError, extract, main, report, score


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


class ScoreTests(unittest.TestCase):
    def test_confirmed_supplementary_denominators_exclude_only_ineligible_rows(self):
        # Ten invented clips: TP, FN, missing, uncertain, FP, TN, request
        # failure, human unknown, human blank, and unprocessed, respectively.
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
                output["断裂状态"] = "无法确定"
            p[i]["raw_output"] = json.dumps(output)
        p[6]["status"] = "request_failed"
        p[9]["status"] = "unprocessed"
        result = score(m, r, p)
        group = result["groups"]["real"]["full_clip"]
        phenomenon = group["fields"]["断裂现象.伸长"]
        self.assertEqual((phenomenon["TP"], phenomenon["FN"], phenomenon["FP"], phenomenon["TN"]), (1, 1, 1, 1))
        for key, pair in (("precision", (1, 2)), ("false_positive_rate_explicit_only", (1, 2)), ("recall", (1, 4))):
            metric = phenomenon[key]
            self.assertEqual((metric["numerator"], metric["denominator"]), pair)
        self.assertEqual(phenomenon["failures_or_uncertain_by_truth"],
                         {"是:missing": 1, "是:explicit_uncertain": 1, "否:request_failed": 1})
        self.assertEqual(phenomenon["truth_counts"], {"valid": 8, "unknown": 1, "unlabeled": 1})
        self.assertEqual(phenomenon["prediction_counts"]["unprocessed"], 1)
        state_precision = group["fields"]["断裂状态"]["classes"]["发生断裂"]["precision"]
        self.assertEqual((state_precision["numerator"], state_precision["denominator"]), (3, 4))
        joint = group["all_five_correct_supplement"]
        self.assertEqual((joint["numerator"], joint["denominator"]), (2, 7))
        self.assertEqual(result["supplementary_formula_status"], "user_confirmed_supplementary_statistics")
        rendered = report(result)
        self.assertIn("用户已确认的补充统计", rendered)
        self.assertNotIn("尚待正式确认", rendered)

        # Single-choice uncertainty is an ordinary comparable class, including
        # its precision and the all-five supplement; it is not multi-item unknown.
        m, r, p = fixture()
        uncertain = labels()
        for field in ("断裂状态", "断裂模式", "断裂位置"):
            uncertain[field] = "无法确定"
        r[0]["labels"] = uncertain
        p[0]["raw_output"] = json.dumps(uncertain)
        group = score(m, r, p)["groups"]["real"]["full_clip"]
        self.assertEqual(group["all_five_correct_supplement"]["value"], 1)
        for field in ("断裂状态", "断裂模式", "断裂位置"):
            precision = group["fields"][field]["classes"]["无法确定"]["precision"]
            self.assertEqual((precision["numerator"], precision["denominator"]), (1, 1))

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

    def test_unknown_blank_missing_and_single_uncertain_are_separate(self):
        m, r, p = fixture(4)
        r[0]["labels"]["断裂现象"]["伸长"] = "无法判断"
        r[1]["labels"]["断裂现象"]["伸长"] = ""
        r[2]["labels"]["断裂状态"] = "无法确定"
        obj = labels()
        obj["断裂状态"] = "无法确定"
        p[2]["raw_output"] = json.dumps(obj)
        obj = labels()
        del obj["断裂现象"]["伸长"]
        p[3]["raw_output"] = json.dumps(obj)
        a = score(m, r, p)["groups"]["real"]["full_clip"]
        f = a["fields"]["断裂现象.伸长"]
        self.assertEqual(f["truth_counts"], {"unknown": 1, "unlabeled": 1, "valid": 2})
        self.assertEqual(f["recall"]["value"], .5)
        self.assertEqual(f["FN"], 0)
        self.assertEqual(f["failures_or_uncertain_by_truth"], {"是:missing": 1})
        self.assertEqual(a["fields"]["断裂状态"]["classes"]["无法确定"]["recall"]["value"], 1)
        self.assertEqual(a["all_five_correct_supplement"]["denominator"], 2)

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
        self.assertEqual(len(x["conflicts"]), 3)
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

        # Recursion may also arise during conversion after decoding succeeds.
        # Inject it explicitly so this case is independent of Python stack depth.
        with patch("script.five_label_eval.score.materialize", side_effect=RecursionError):
            self.assertEqual(extract('{}')["fields"]["断裂状态"]["status"], "extraction_failed")
        with patch("script.five_label_eval.score.materialize", side_effect=TypeError("unexpected bug")):
            with self.assertRaisesRegex(TypeError, "unexpected bug"):
                extract('{}')

    def test_fixed_none_valid_and_no_positive_negative_evidence(self):
        m, r, p = fixture()
        obj = labels()
        obj.update({"断裂状态": "未断裂", "断裂模式": "无", "断裂位置": "无"})
        r[0]["labels"] = obj
        p[0]["raw_output"] = json.dumps(obj)
        a = score(m, r, p)["groups"]["real"]["full_clip"]
        self.assertEqual(a["fields"]["断裂模式"]["classes"]["无"]["recall"]["value"], 1)
        self.assertIsNone(a["fields"]["异常情况.爆炸性断裂"]["recall"]["value"])
        self.assertIsNone(a["fields"]["断裂现象.伸长"]["false_positive_rate_explicit_only"]["value"])

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
        fields = {"断裂状态": {"evidence": "insufficient", "label": "无法确定"},
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
            self.assertTrue((root / "out/report.md").exists())
            self.assertEqual(main(args), 2)  # Never overwrite outputs.
            (root / "manifest.json").write_text('{"manifest_version":"a","manifest_version":"b"}')
            self.assertEqual(main(args[:-1] + [str(root / "other")]), 2)


if __name__ == "__main__":
    unittest.main()
