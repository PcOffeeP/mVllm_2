"""Only synthetic bytes in temporary directories; never accesses project media."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

urlopen = build_opener(ProxyHandler({})).open

from script.subvideo_review.server import (OPTIONS, ReviewApp, ReviewError, canonical, digest,
                                           handler_for)

# review_subject_sha256 的输入键元组（顺序与实现一致；分层展示字段不得进入）。
REVIEW_SUBJECT_KEYS = ("candidate_id", "source_id", "source_type", "clip_sha256", "candidate_record_sha256",
                       "source_sha256", "roi_sha256", "source_relationships", "source_reference", "scope",
                       "folds", "generation_batch_id", "generation_schema", "label_rules_sha256",
                       "source_record_sha256", "generation_identity_sha256", "split_identity_sha256")
LEGACY_NONE_CANDIDATE_LABELS = {"断裂状态": "未断裂", "断裂模式": "无", "断裂位置": "无"}
PREFILL_NOTE = "初值为旧规则固定组合值『无』，已按新规则映射为无法判断"


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / "data/sub_video/manifest.json"
        self.manifest_path.parent.mkdir(parents=True)
        split = self.root / "data/splits/three-fold/test.json"
        split.parent.mkdir(parents=True)
        split.write_text('{"video_ids":["fixed_test"]}')
        for fold in range(3):
            for part in ("train", "val"):
                (split.parent / f"fold_{fold}_{part}.json").write_text(json.dumps({"video_ids": ["source_a", "source_b", "pending_source"] if part == "train" else []}))
        self.media = b"synthetic fixture only, not a real video"
        (self.manifest_path.parent / "videos").mkdir()
        for name in ("a", "b"):
            (self.manifest_path.parent / f"videos/{name}.mp4").write_bytes(self.media)
        self.manifest = {
            "schema": "tensile-unified-sub-video/1", "generation_batch_id": "synthetic-batch",
            "complete": True, "published": False, "plan_only": False,
            "identity": {"guard_seconds": 0.5, "scope": "development"},
            "sources": [{"video_id": "source_a", "source_type": "real", "source_annotation": {"断裂状态": "已断裂"}}, {"video_id": "source_b", "source_type": "virtual"}, {"video_id": "pending_source", "status": "pending", "reason": "synthetic_pending"}],
            "candidates": [{"candidate_id": name, "source_video_id": f"source_{name}", "output_path": f"videos/{name}.mp4", "output": {"sha256": hashlib.sha256(self.media).hexdigest()}, "scope": "development", "status": "cropped", "labels_status": "unreviewed", "manual_review": "required", "final_labels": None, "review": {"status": "未审核", "decision": None, "change_notes": ""}, "candidate_labels": {"断裂状态": "已断裂"}, "review_focus": ["断裂位置"], "window_role": "pre_event", "start_frame": 2, "end_frame": 5} for name in ("a", "b")],
        }
        self.write_manifest()
        self.app = ReviewApp(self.root)

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def write_audit(self, rows=None, **values):
        audit = {
            "schema": "tensile-unified-sub-video-audit/1",
            "manifest_sha256": hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
            "candidates": rows if rows is not None else [
                {"candidate_id": "a", "source_video_id": "source_a", "scope": "development", "issues": ["synthetic conflict"]},
                {"candidate_id": "b", "source_video_id": "source_b", "scope": "development", "issues": []},
            ],
        }
        audit.update(values)
        (self.manifest_path.parent / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    def set_fold_members(self, fold, train, val):
        directory = self.root / "data/splits/three-fold"
        for part, members in (("train", train), ("val", val)):
            (directory / f"fold_{fold}_{part}.json").write_text(json.dumps({"video_ids": members}), encoding="utf-8")

    def labels(self):
        labels = {name: ({item: "无法判断" for item in options} if isinstance(options, dict) else "无法判断") for name, options in OPTIONS.items()}
        return labels

    def payload(self, status="draft", **values):
        payload = {"candidate_id": "a", "manifest_sha256": self.app.manifest_sha256,
                   "clip_sha256": hashlib.sha256(self.media).hexdigest(),
                   "review_status": status, "labels": {}, "expected_review_id": None}
        payload.update(values)
        return payload

    def serve(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def test_bootstrap_empty_labels_source_types_pending_and_no_media_read(self):
        for file in (self.manifest_path.parent / "videos").iterdir():
            file.unlink()
        bootstrap = self.app.bootstrap()
        self.assertEqual([c["review_status"] for c in bootstrap["candidates"]], ["unreviewed"] * 2)
        self.assertTrue(all("labels" not in c for c in bootstrap["candidates"]))
        self.assertEqual([c["source_type"] for c in bootstrap["candidates"]], ["real", "virtual"])
        self.assertEqual(bootstrap["pending_sources"][0]["reason"], "synthetic_pending")

    def test_roundtrip_all_states_and_immutable_history(self):
        previous = None
        for status in ("draft", "question", "returned", "confirmed", "draft"):
            row = self.app.save(self.payload(status, labels=self.labels() if status == "confirmed" else {}, reason="synthetic reason", expected_review_id=previous))
            self.assertEqual(row["previous_review_id"], previous)
            previous = row["review_id"]
        restarted = ReviewApp(self.root)
        review = restarted.review("a")
        self.assertEqual(len(review["history"]), 5)
        self.assertEqual(review["latest"]["review_status"], "draft")
        self.assertEqual(review["history"][3]["review_status"], "confirmed")
        rows = [json.loads(line) for line in restarted.export().splitlines()]
        self.assertEqual(rows[0]["history_review_ids"], [r["review_id"] for r in review["history"][:-1]])
        self.assertEqual(rows[1]["review_status"], "unreviewed")
        self.assertIsNone(rows[1]["review_id"])
        self.assertEqual(len(restarted.export(all_revisions=True).splitlines()), 5)

    def test_confirmation_requires_eleven_explicit_answers(self):
        with self.assertRaisesRegex(ReviewError, "11"):
            self.app.save(self.payload("confirmed"))
        labels = self.labels()
        labels["断裂现象"]["伸长"] = ""
        with self.assertRaises(ReviewError):
            self.app.save(self.payload("confirmed", labels=labels))
        labels["断裂现象"]["伸长"] = "无法判断"
        row = self.app.save(self.payload("confirmed", labels=labels))
        self.assertEqual(row["labels"]["断裂现象"]["伸长"], "无法判断")

    def test_superseded_uncertain_term_is_rejected_for_single_fields(self):
        # 「无法确定」已统一为「无法判断」；工作台只接受新术语，旧词在保存时即被拒绝。
        for field in ("断裂状态", "断裂模式", "断裂位置"):
            labels = self.labels()
            labels[field] = "无法确定"
            with self.subTest(field=field):
                with self.assertRaisesRegex(ReviewError, f"{field} 取值无效"):
                    self.app.save(self.payload("confirmed", labels=labels))
        self.assertFalse(self.app.records_path.exists())

    def test_unfractured_state_keeps_concrete_mode_and_location(self):
        # 新规则：未断裂时按可见证据填具体值，不再强制「无」。
        labels = self.labels()
        labels["断裂状态"] = "未断裂"
        labels["断裂模式"] = "脆性断裂"
        labels["断裂位置"] = "标距内"

        row = self.app.save(self.payload("confirmed", labels=labels))

        self.assertEqual(row["labels"]["断裂模式"], "脆性断裂")
        self.assertEqual(row["labels"]["断裂位置"], "标距内")
        saved = ReviewApp(self.root).review("a")["latest"]
        self.assertEqual(saved["labels"]["断裂模式"], "脆性断裂")
        self.assertEqual(saved["labels"]["断裂位置"], "标距内")

    def test_unfractured_state_accepts_uncertain_mode_and_location(self):
        labels = self.labels()
        labels["断裂状态"] = "未断裂"

        row = self.app.save(self.payload("confirmed", labels=labels))

        self.assertEqual(row["review_status"], "confirmed")
        self.assertEqual(row["labels"]["断裂模式"], "无法判断")
        self.assertEqual(row["labels"]["断裂位置"], "无法判断")

    def test_unclamped_accepts_concrete_mode_and_location(self):
        # 未夹紧也不再要求「无」：按可见证据作答即可保存。
        labels = self.labels()
        labels["异常情况"]["未夹紧"] = "是"
        labels["断裂模式"] = "韧性断裂"
        labels["断裂位置"] = "夹持根部"

        row = self.app.save(self.payload("confirmed", labels=labels))

        self.assertEqual(row["labels"]["异常情况"]["未夹紧"], "是")
        self.assertEqual(row["labels"]["断裂模式"], "韧性断裂")
        self.assertEqual(row["labels"]["断裂位置"], "夹持根部")

    def test_legacy_none_value_is_rejected_for_mode_and_location(self):
        # 「无」已从两个下拉的取值清单移除；旧词作为非法枚举值被拒，文案点名字段。
        for field, candidate_id in (("断裂模式", "a"), ("断裂位置", "b")):
            labels = self.labels()
            labels[field] = "无"
            payload = {**self.payload("confirmed", labels=labels), "candidate_id": candidate_id}
            with self.subTest(field=field):
                with self.assertRaisesRegex(ReviewError, f"{field} 取值无效"):
                    self.app.save(payload)
        self.assertFalse(self.app.records_path.exists())

    def test_options_drop_none_but_keep_the_other_values_in_order(self):
        self.assertEqual(OPTIONS["断裂模式"], ["脆性断裂", "韧性断裂", "半脆半韧断裂", "无法判断"])
        self.assertEqual(OPTIONS["断裂位置"], ["标距内", "标距外非根部", "夹持根部", "无法判断"])

    def test_unfractured_state_still_conflicts_with_explosive_and_unknown_fields(self):
        labels = self.labels()
        labels["断裂状态"] = "未断裂"
        labels["异常情况"]["爆炸性断裂"] = "是"

        with self.assertRaisesRegex(ReviewError, "未断裂与爆炸性断裂互斥"):
            self.app.save(self.payload("confirmed", labels=labels))
        labels["异常情况"]["爆炸性断裂"] = "否"
        self.assertEqual(self.app.save(self.payload("confirmed", labels=labels))["labels"], labels)
        with self.assertRaisesRegex(ReviewError, "不能包含其他字段"):
            self.app.save(self.payload(labels={"unknown": "否"}))

    def test_reasons_required_and_blank_preserved(self):
        for status in ("question", "returned"):
            with self.assertRaises(ReviewError):
                self.app.save(self.payload(status))
        row = self.app.save(self.payload(labels={"断裂状态": "", "异常情况": {"未夹紧": ""}}))
        self.assertEqual(row["labels"]["异常情况"]["未夹紧"], "")

    def test_unfractured_post_fracture_release_cannot_confirm_but_can_save_pending(self):
        labels = self.labels()
        labels["断裂状态"] = "未断裂"
        labels["断裂现象"]["断后脱夹"] = "是"
        draft = self.app.save(self.payload("draft", labels=labels))
        question = self.app.save(self.payload("question", labels=labels, reason="synthetic conflict for human review", expected_review_id=draft["review_id"]))
        self.assertEqual(draft["labels"], labels)
        self.assertEqual(question["labels"], labels)
        with self.assertRaisesRegex(ReviewError, "未断裂与断后脱夹互斥"):
            self.app.save(self.payload("confirmed", labels=labels, expected_review_id=question["review_id"]))
        self.assertEqual(len(self.app.review("a")["history"]), 2)
        self.assertEqual(self.app.review("a")["latest"]["review_status"], "question")
        labels["断裂现象"]["断后脱夹"] = "无法判断"
        confirmed = self.app.save(self.payload("confirmed", labels=labels, expected_review_id=question["review_id"]))
        self.assertEqual(confirmed["labels"]["断裂现象"]["断后脱夹"], "无法判断")

    def test_first_confirmation_no_reason_but_revisions_need_reason(self):
        first = self.app.save(self.payload("confirmed", labels=self.labels()))
        with self.assertRaisesRegex(ReviewError, "修订已确认"):
            self.app.save(self.payload("confirmed", labels=self.labels(), expected_review_id=first["review_id"]))
        draft = self.app.save(self.payload("draft", expected_review_id=first["review_id"]))
        with self.assertRaisesRegex(ReviewError, "修订已确认"):
            self.app.save(self.payload("confirmed", labels=self.labels(), expected_review_id=draft["review_id"]))
        self.app.save(self.payload("confirmed", labels=self.labels(), expected_review_id=draft["review_id"], reason="synthetic correction"))

    def test_unknown_or_test_related_sources_rejected(self):
        self.manifest["candidates"][0]["source_video_id"] = "unknown"
        self.write_manifest()
        with self.assertRaisesRegex(ReviewError, "归属不明"):
            ReviewApp(self.root)
        self.manifest["candidates"][0]["source_video_id"] = "source_a"
        self.manifest["sources"][0]["related_source_ids"] = ["fixed_test"]
        self.write_manifest()
        with self.assertRaisesRegex(ReviewError, "关联来源"):
            ReviewApp(self.root)

    def test_source_preview_requires_known_source_and_verified_hash(self):
        source_file = self.root / "data/videos/pending_source.mp4"
        source_file.parent.mkdir(parents=True)
        source_file.write_bytes(self.media)
        self.manifest["sources"][2].update(source_path="data/videos/pending_source.mp4", source_sha256=hashlib.sha256(self.media).hexdigest())
        self.write_manifest()
        app = ReviewApp(self.root)
        with app.source_media("pending_source") as (stream, size, _):
            self.assertEqual(stream.read(), self.media)
            self.assertEqual(size, len(self.media))
        with self.assertRaises(ReviewError):
            with app.source_media("fixed_test"):
                self.fail("test source was opened")
        source_file.write_bytes(b"changed synthetic media")
        with self.assertRaisesRegex(ReviewError, "SHA256"):
            with app.source_media("pending_source"):
                pass

    def test_conflicting_source_split_refuses_preview_and_candidate_load(self):
        self.manifest["sources"][2].update(
            source_path="data/videos/pending_source.mp4",
            source_sha256=hashlib.sha256(self.media).hexdigest(),
            split={"partition": "test"},
        )
        self.write_manifest()
        app = ReviewApp(self.root)
        self.assertFalse(app.bootstrap()["pending_sources"][0]["source_preview_available"])
        with self.assertRaisesRegex(ReviewError, "划分.*不一致"):
            with app.source_media("pending_source"):
                self.fail("conflicting test source must not open")
        self.manifest["sources"][0]["split"] = {"partition": "test"}
        self.write_manifest()
        with self.assertRaisesRegex(ReviewError, "划分.*不一致"):
            ReviewApp(self.root)

    def test_optimistic_conflict_and_identity_check(self):
        self.app.save(self.payload())
        with self.assertRaisesRegex(ReviewError, "其他修订"):
            self.app.save(self.payload())
        with self.assertRaisesRegex(ReviewError, "身份"):
            self.app.save(self.payload(clip_sha256="0" * 64))

    def test_two_service_instances_cannot_lose_a_revision(self):
        second = ReviewApp(self.root)
        def save(app):
            try:
                return app.save(self.payload())["review_id"]
            except ReviewError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [self.app, second]))
        self.assertEqual(results.count(409), 1)
        self.assertEqual(len(self.app.review("a")["history"]), 1)

    def test_changed_media_rejected_without_new_revision(self):
        (self.manifest_path.parent / "videos/a.mp4").write_bytes(b"changed")
        with self.assertRaisesRegex(ReviewError, "SHA256"):
            self.app.save(self.payload())
        self.assertFalse(self.app.records_path.exists())

    def test_manifest_append_keeps_unchanged_review_but_changed_candidate_is_isolated(self):
        old = self.app.save(self.payload("confirmed", labels=self.labels()))
        self.manifest["candidates"].append({**self.manifest["candidates"][1], "candidate_id": "new"})
        self.write_manifest()
        with self.assertRaisesRegex(ReviewError, "已变化"):
            self.app.bootstrap()
        new_app = ReviewApp(self.root)
        review = new_app.review("a")
        self.assertEqual(review["latest"]["review_id"], old["review_id"])
        self.assertEqual(review["isolated_history"], [])
        self.manifest["candidates"][0]["start_frame"] = 3
        self.write_manifest()
        new_app = ReviewApp(self.root)
        review = new_app.review("a")
        self.assertIsNone(review["latest"])
        self.assertEqual(review["isolated_history"][0]["review_id"], old["review_id"])
        self.assertEqual(json.loads(new_app.export(all_revisions=True))["review_id"], old["review_id"])
        self.assertEqual(json.loads(new_app.export().splitlines()[0])["isolated_history_review_ids"], [old["review_id"]])

    def test_tampered_store_refuses_overwrite(self):
        self.app.save(self.payload())
        data = json.loads(self.app.records_path.read_text())
        data["revisions"][0]["labels"] = {"断裂状态": "已断裂"}
        self.app.records_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ReviewError, "完整性"):
            self.app.export()

    def test_older_store_schema_is_not_silently_overwritten(self):
        self.app.records_path.parent.mkdir(parents=True)
        old = '{"schema":"tensile-subvideo-human-review/1","revisions":[]}'
        self.app.records_path.write_text(old, encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "格式或修订完整性"):
            self.app.save(self.payload())
        self.assertEqual(self.app.records_path.read_text(encoding="utf-8"), old)

    def test_test_candidates_are_accessible_only_with_matching_fixed_split(self):
        self.manifest["sources"].append({"video_id": "fixed_test", "scope": "test", "folds": {str(f): "test" for f in range(3)}})
        self.manifest["candidates"][0].update(source_video_id="fixed_test", scope="test", folds={str(f): "test" for f in range(3)})
        self.write_manifest()
        app = ReviewApp(self.root)
        self.assertEqual(app.candidate("a")["scope"], "test")
        with app.media("a") as (stream, _, _):
            self.assertEqual(stream.read(), self.media)
        row = app.save({**self.payload("confirmed", labels=self.labels()), "manifest_sha256": app.manifest_sha256})
        self.assertEqual(row["scope"], "test")
        self.assertEqual(row["folds"], {str(f): "test" for f in range(3)})
        for change in ({"scope": "development"}, {"folds": {"0": "train", "1": "test", "2": "test"}}):
            original = copy.deepcopy(self.manifest["candidates"][0])
            self.manifest["candidates"][0].update(change)
            self.write_manifest()
            with self.assertRaisesRegex(ReviewError, "划分|折归属"):
                ReviewApp(self.root)
            self.manifest["candidates"][0] = original

    def test_changed_source_reference_isolates_review(self):
        old = self.app.save(self.payload("confirmed", labels=self.labels()))
        self.manifest["sources"][0]["source_annotation"]["断裂状态"] = "无法确定"
        self.write_manifest()
        review = ReviewApp(self.root).review("a")
        self.assertIsNone(review["latest"])
        self.assertEqual(review["isolated_history"][0]["review_id"], old["review_id"])

    def test_conflicting_scope_or_source_media_identity_cannot_be_hidden(self):
        self.manifest["sources"][0].update(scope="development", split={"partition": "test"})
        self.write_manifest()
        with self.assertRaisesRegex(ReviewError, "划分.*不一致"):
            ReviewApp(self.root)
        self.manifest["sources"][0].pop("split")
        for field in ("source_sha256", "roi_sha256"):
            self.manifest["sources"][0][field] = "1" * 64
            self.manifest["candidates"][0][field] = "2" * 64
            self.write_manifest()
            with self.assertRaisesRegex(ReviewError, field):
                ReviewApp(self.root)
            self.manifest["sources"][0].pop(field)
            self.manifest["candidates"][0].pop(field)

    def test_split_change_blocks_old_session_before_review_is_saved(self):
        split = self.root / "data/splits/three-fold/fold_0_train.json"
        split.write_text('{"video_ids": []}', encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "数据划分.*变化"):
            self.app.save(self.payload())
        self.assertFalse(self.app.records_path.exists())

    def test_changed_label_rules_isolate_existing_review(self):
        rules = self.root / "docs/label.md"
        rules.parent.mkdir(parents=True)
        rules.write_text("synthetic label rules v1", encoding="utf-8")
        app = ReviewApp(self.root)
        old = app.save(self.payload("confirmed", labels=self.labels()))
        rules.write_text("synthetic label rules v2", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "标签规则.*变化"):
            app.bootstrap()
        review = ReviewApp(self.root).review("a")
        self.assertIsNone(review["latest"])
        self.assertEqual(review["isolated_history"][0]["review_id"], old["review_id"])

    def test_only_matching_audit_and_finished_candidates_are_shown(self):
        self.manifest["candidates"].append({"candidate_id": "unfinished", "source_video_id": "source_a", "scope": "development", "status": "planned"})
        self.write_manifest()
        audit = {"manifest_sha256": hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
                 "candidates": [{"candidate_id": "a", "issues": ["synthetic conflict"]}]}
        (self.manifest_path.parent / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
        app = ReviewApp(self.root)
        self.assertTrue(app.bootstrap()["audit_current"])
        self.assertEqual(app.candidate("a")["audit_issues"], ["synthetic conflict"])
        self.assertNotIn("unfinished", app.candidates)
        self.manifest["generation_batch_id"] = "changed"
        self.write_manifest()
        newer = ReviewApp(self.root)
        self.assertFalse(newer.bootstrap()["audit_current"])
        self.assertEqual(newer.candidate("a")["audit_issues"], [])

    def test_unified_format_coverage_null_stays_unreviewed_and_blank(self):
        self.manifest["candidates"][1].update(
            candidate_labels=None, review_focus=None, window_role="coverage",
            event_kind="none_unlocated", source_labels={"断裂状态": "无法确定"},
        )
        self.write_manifest()
        app = ReviewApp(self.root)
        candidate = next(row for row in app.bootstrap()["candidates"] if row["candidate_id"] == "b")
        self.assertEqual(candidate["review_status"], "unreviewed")
        self.assertFalse(candidate.get("candidate_reference"))
        self.assertFalse(candidate.get("review_focus"))
        self.assertNotIn("labels", candidate)
        self.assertIsNone(app.review("b")["latest"])
        row = app.save({**self.payload(), "candidate_id": "b", "manifest_sha256": app.manifest_sha256})
        self.assertEqual(row["labels"], {})
        exported = {row["candidate_id"]: row for row in map(json.loads, app.export().splitlines())}
        self.assertEqual(exported["b"]["labels"], {})
        self.assertEqual(exported["a"]["review_status"], "unreviewed")

    def test_automatic_candidates_are_reference_only_and_no_input_is_overwritten(self):
        original_manifest = self.manifest_path.read_bytes()
        original_media = (self.manifest_path.parent / "videos/a.mp4").read_bytes()
        candidate = self.app.candidate("a")
        self.assertEqual(candidate["candidate_reference"], {"断裂状态": "已断裂"})
        self.assertEqual(candidate["source_reference"], {"断裂状态": "已断裂"})
        first = self.app.save(self.payload())
        self.assertEqual(first["labels"], {})
        self.assertEqual(self.app.review("a")["latest"]["labels"], {})
        self.assertEqual(self.manifest_path.read_bytes(), original_manifest)
        self.assertEqual((self.manifest_path.parent / "videos/a.mp4").read_bytes(), original_media)
        self.assertNotEqual(self.app.records_path.parent, self.manifest_path.parent)

    def test_bootstrap_maps_legacy_none_for_display_only_without_touching_digests(self):
        partial = copy.deepcopy(self.manifest["candidates"][0])
        partial.update(candidate_id="partial", candidate_labels={"断裂状态": "无法判断", "断裂位置": "无"})
        self.manifest["candidates"][0]["candidate_labels"] = copy.deepcopy(LEGACY_NONE_CANDIDATE_LABELS)
        self.manifest["candidates"].append(partial)
        self.write_manifest()
        manifest_item = copy.deepcopy(self.manifest["candidates"][0])

        app = ReviewApp(self.root)
        rows = {row["candidate_id"]: row for row in app.bootstrap()["candidates"]}

        # candidate_reference 保持原值（仍含「无」），候选对象不被就地改写。
        self.assertEqual(app.candidates["a"]["candidate_reference"], LEGACY_NONE_CANDIDATE_LABELS)
        self.assertEqual(rows["a"]["candidate_reference"], LEGACY_NONE_CANDIDATE_LABELS)
        # 展示副本只映射两个字段的「无」，其它键值原样。
        self.assertEqual(rows["a"].get("candidate_reference_display"),
                         {"断裂状态": "未断裂", "断裂模式": "无法判断", "断裂位置": "无法判断"},
                         "bootstrap 必须为每个候选提供仅供展示的 candidate_reference_display")
        self.assertEqual(rows["a"].get("prefill_note"), PREFILL_NOTE,
                         "发生过「无」映射时必须给出 prefill_note 提示原文")
        # 只部分相同的候选同样给出提示，未出现「无」的字段保持原值。
        self.assertEqual(rows["partial"].get("candidate_reference_display"),
                         {"断裂状态": "无法判断", "断裂位置": "无法判断"},
                         "映射按字段进行，不含「无」的键不得被改写")
        self.assertEqual(rows["partial"].get("prefill_note"), PREFILL_NOTE)
        # 没有「无」的候选不带提示，展示副本与引用完全一致。
        self.assertIsNone(rows["b"].get("prefill_note"), "未发生映射时 prefill_note 必须为 None")
        self.assertEqual(rows["b"].get("candidate_reference_display"), rows["b"]["candidate_reference"])
        # 摘要输入不变：candidate_record_sha256 仍是未改写清单条目的 canonical 摘要。
        self.assertEqual(rows["a"]["candidate_record_sha256"], digest(canonical(manifest_item)))
        # review_subject_sha256 可用原键元组重算，展示字段不在输入里。
        self.assertEqual(rows["a"]["review_subject_sha256"],
                         digest(canonical({key: rows["a"][key] for key in REVIEW_SUBJECT_KEYS})))
        self.assertNotIn("candidate_reference_display", REVIEW_SUBJECT_KEYS)
        self.assertNotIn("prefill_note", REVIEW_SUBJECT_KEYS)

    def test_three_distinct_folds_are_inherited_and_exported_without_reassignment(self):
        self.set_fold_members(0, ["source_b", "pending_source"], ["source_a"])
        self.set_fold_members(1, ["source_a", "pending_source"], ["source_b"])
        self.set_fold_members(2, ["source_a", "source_b"], ["pending_source"])
        self.manifest["sources"][0]["folds"] = {"0": "val", "1": "train", "2": "train"}
        self.manifest["candidates"][0]["folds"] = {"0": "val", "1": "train", "2": "train"}
        self.write_manifest()
        app = ReviewApp(self.root)
        self.assertEqual(app.candidate("a")["folds"], {"0": "val", "1": "train", "2": "train"})
        self.assertEqual(app.candidate("b")["folds"], {"0": "train", "1": "val", "2": "train"})
        row = app.save({**self.payload(), "manifest_sha256": app.manifest_sha256})
        self.assertEqual(row["folds"], {"0": "val", "1": "train", "2": "train"})
        self.assertEqual(json.loads(app.export().splitlines()[0])["folds"], row["folds"])

    def test_missing_conflicting_or_test_leaking_fold_members_are_rejected(self):
        for train, val in ((["source_b", "pending_source"], []),
                           (["source_a", "source_b", "pending_source"], ["source_a"]),
                           (["source_a", "source_b", "pending_source", "fixed_test"], [])):
            with self.subTest(train=train, val=val):
                self.set_fold_members(1, train, val)
                with self.assertRaises(ReviewError):
                    ReviewApp(self.root)
        self.assertFalse(self.app.records_path.exists())

    def test_same_scope_related_source_with_different_fold_is_rejected(self):
        self.set_fold_members(0, ["source_a", "pending_source"], ["source_b"])
        for owner in (self.manifest["sources"][0], self.manifest["candidates"][0]):
            with self.subTest(owner="source" if "video_id" in owner else "candidate"):
                owner["related_source_ids"] = ["source_b"]
                self.write_manifest()
                with self.assertRaises(ReviewError):
                    ReviewApp(self.root)
                del owner["related_source_ids"]

    def test_changed_audit_requires_restart_before_any_stale_issues_can_be_used(self):
        self.write_audit(candidates_needing_attention=1)
        app = ReviewApp(self.root)
        before_subject = app.candidate("a")["review_subject_sha256"]
        bootstrap = app.bootstrap()
        self.assertEqual(bootstrap["audit_status"], "current")
        self.assertEqual(bootstrap["audit_issue_candidate_count"], 1)
        self.assertEqual(app.candidate("a")["audit_issues"], ["synthetic conflict"])
        self.assertIsNone(app.review("a")["latest"])
        self.write_audit(manifest_sha256="0" * 64)
        with self.assertRaisesRegex(ReviewError, "核验.*变化") as error:
            app.bootstrap()
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(ReviewError):
            app.save(self.payload())
        restarted = ReviewApp(self.root)
        bootstrap = restarted.bootstrap()
        self.assertFalse(bootstrap["audit_current"])
        self.assertEqual(bootstrap["audit_status"], "mismatch")
        self.assertTrue(bootstrap["audit_message"])
        self.assertEqual(restarted.candidate("a")["audit_issues"], [])
        self.assertEqual(restarted.candidate("a")["review_subject_sha256"], before_subject)
        self.assertFalse(app.records_path.exists())

    def test_missing_or_malformed_audit_is_explicit_and_never_supplies_issues(self):
        self.assertEqual(self.app.bootstrap()["audit_status"], "missing")
        (self.manifest_path.parent / "audit.json").write_text("{broken synthetic JSON", encoding="utf-8")
        app = ReviewApp(self.root)
        bootstrap = app.bootstrap()
        self.assertEqual(bootstrap["audit_status"], "invalid")
        self.assertFalse(bootstrap["audit_current"])
        self.assertEqual(app.candidate("a")["audit_issues"], [])
        self.assertEqual(len(bootstrap["candidates"]), 2)

    def test_matching_hash_cannot_legitimize_invalid_audit_rows(self):
        good = {"candidate_id": "a", "source_video_id": "source_a", "scope": "development", "issues": ["synthetic conflict"]}
        cases = [
            {"candidates": [good, good]},
            {"candidates": [good, {"candidate_id": "unknown", "issues": []}]},
            {"candidates": [good, {"candidate_id": "b", "issues": [1]}]},
            {"candidates": [{**good, "source_video_id": "source_b"}]},
            {"candidates": [{**good, "scope": "test"}]},
            {"candidates": [good], "candidates_needing_attention": 2},
            {"candidates": None},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.write_audit(**changes)
                app = ReviewApp(self.root)
                bootstrap = app.bootstrap()
                self.assertEqual(bootstrap["audit_status"], "invalid")
                self.assertFalse(bootstrap["audit_current"])
                self.assertEqual(app.candidate("a")["audit_issues"], [])
                self.assertEqual(app.candidate("b")["audit_issues"], [])

    def test_audit_correction_preserves_current_manual_revision(self):
        self.write_audit(candidates_needing_attention=1)
        app = ReviewApp(self.root)
        saved = app.save(self.payload("confirmed", labels=self.labels()))
        self.write_audit(rows=[], candidates_needing_attention=0)
        restarted = ReviewApp(self.root)
        self.assertEqual(restarted.bootstrap()["audit_issue_candidate_count"], 0)
        self.assertEqual(restarted.review("a")["latest"]["review_id"], saved["review_id"])
        self.assertEqual(restarted.review("a")["isolated_history"], [])

    def test_changed_generation_rules_isolate_same_named_clip_without_losing_history(self):
        saved = self.app.save(self.payload("confirmed", labels=self.labels()))
        self.manifest["identity"]["guard_seconds"] = 0.75
        self.write_manifest()
        restarted = ReviewApp(self.root)
        review = restarted.review("a")
        self.assertIsNone(review["latest"])
        self.assertEqual([r["review_id"] for r in review["isolated_history"]], [saved["review_id"]])
        fresh = restarted.save({**self.payload(), "manifest_sha256": restarted.manifest_sha256})
        self.assertIsNone(fresh["previous_review_id"])
        self.assertEqual(len(restarted.export(all_revisions=True).splitlines()), 2)

    def test_changed_source_record_isolates_same_named_clip(self):
        saved = self.app.save(self.payload("confirmed", labels=self.labels()))
        self.manifest["sources"][0]["source_path"] = "data/videos/replaced_source.mp4"
        self.write_manifest()
        review = ReviewApp(self.root).review("a")
        self.assertIsNone(review["latest"])
        self.assertEqual(review["isolated_history"][0]["review_id"], saved["review_id"])

    def test_changed_split_identity_isolates_review_even_if_candidate_membership_is_unchanged(self):
        saved = self.app.save(self.payload("confirmed", labels=self.labels()))
        old_folds = copy.deepcopy(self.app.candidate("a")["folds"])
        self.set_fold_members(1, ["source_a", "pending_source"], ["source_b"])
        restarted = ReviewApp(self.root)
        self.assertEqual(restarted.candidate("a")["folds"], old_folds)
        review = restarted.review("a")
        self.assertIsNone(review["latest"])
        self.assertEqual(review["isolated_history"][0]["review_id"], saved["review_id"])

    def test_records_cannot_replace_generation_or_source_annotation(self):
        annotation = self.root / "data/annotation-table-full.csv"
        annotation.write_text("synthetic sentinel", encoding="utf-8")
        original = self.manifest_path.read_bytes()
        for path in (self.manifest_path, self.manifest_path.parent / "reviews.json", annotation):
            with self.subTest(path=path):
                with self.assertRaises(ReviewError):
                    ReviewApp(self.root, records=path)
        self.assertEqual(annotation.read_text(encoding="utf-8"), "synthetic sentinel")
        self.assertEqual(self.manifest_path.read_bytes(), original)

    def test_media_endpoint_hash_failure_never_returns_changed_bytes(self):
        base = self.serve()
        (self.manifest_path.parent / "videos/a.mp4").write_bytes(b"changed synthetic fixture")
        with self.assertRaises(HTTPError) as error:
            urlopen(base + "/media?candidate_id=a")
        self.assertEqual(error.exception.code, 409)
        self.assertIn("SHA256", json.load(error.exception)["error"])
        self.assertFalse(self.app.records_path.exists())

    def test_traversal_symlink_and_size_rejected(self):
        self.manifest["candidates"][0]["output_path"] = "../outside.mp4"
        self.write_manifest()
        with self.assertRaises(ReviewError):
            ReviewApp(self.root)
        self.manifest["candidates"][0]["output_path"] = "videos/a.mp4"
        self.write_manifest()
        self.app = ReviewApp(self.root, max_media_bytes=1)
        with self.assertRaisesRegex(ReviewError, "大小"):
            self.app.save(self.payload())
        file = self.manifest_path.parent / "videos/a.mp4"
        file.unlink()
        outside = self.root / "outside.mp4"
        outside.write_bytes(self.media)
        file.symlink_to(outside)
        with self.assertRaisesRegex(ReviewError, "符号链接"):
            self.app.save(self.payload())

    def test_http_bootstrap_range_save_export_security(self):
        base = self.serve()
        with urlopen(base + "/api/bootstrap") as response:
            bootstrap = json.load(response)
        with urlopen(Request(base + "/media?candidate_id=a", headers={"Range": "bytes=2-6"})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), self.media[2:7])
        request = Request(base + "/api/reviews", data=json.dumps(self.payload()).encode(), headers={"X-Review-Token": bootstrap["token"]}, method="POST")
        with urlopen(request) as response:
            self.assertEqual(response.status, 201)
        with urlopen(base + "/api/export?all_revisions=1") as response:
            self.assertEqual(json.load(response)["review_status"], "draft")
            # 文件名是用户唯一能判断导出范围的依据：只改 all_revisions 查询参数而沿用同一文件名，会让人把全量修订当成最新修订。
            self.assertEqual(response.headers["Content-Disposition"], 'attachment; filename="subvideo-reviews-history.jsonl"')
        with urlopen(base + "/api/export") as response:
            self.assertEqual(response.status, 200)
            # 不带参数时仍应是「最新修订」的文件名，避免为区分全量导出而把默认输出一起改掉。
            self.assertEqual(response.headers["Content-Disposition"], 'attachment; filename="subvideo-reviews.jsonl"')
        for request in (Request(base + "/api/bootstrap", headers={"Host": "evil.example"}), Request(base + "/api/bootstrap", headers={"Origin": "http://evil.example"}), Request(base + "/api/reviews", data=b"{}", method="POST")):
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            urlopen(base + "/media?candidate_id=../fixed_test")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
