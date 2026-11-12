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

from script.subvideo_review.server import OPTIONS, ReviewApp, ReviewError, handler_for


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
            "schema": "synthetic/1", "generation_batch_id": "synthetic-batch",
            "identity": {"guard_seconds": 0.5, "scope": "development"},
            "sources": [{"video_id": "source_a", "source_type": "real", "source_annotation": {"断裂状态": "已断裂"}}, {"video_id": "source_b", "source_type": "virtual"}, {"video_id": "pending_source", "status": "pending", "reason": "synthetic_pending"}],
            "candidates": [{"candidate_id": name, "source_video_id": f"source_{name}", "output_path": f"videos/{name}.mp4", "output": {"sha256": hashlib.sha256(self.media).hexdigest()}, "scope": "development", "start_frame": 2, "end_frame": 5} for name in ("a", "b")],
        }
        self.write_manifest()
        self.app = ReviewApp(self.root)

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def labels(self):
        labels = {name: ({item: "无法判断" for item in options} if isinstance(options, dict) else "无法确定") for name, options in OPTIONS.items()}
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

    def test_fixed_combinations_and_invalid_fields(self):
        labels = self.labels()
        labels["断裂状态"] = "未断裂"
        with self.assertRaises(ReviewError):
            self.app.save(self.payload("confirmed", labels=labels))
        labels["断裂模式"] = labels["断裂位置"] = "无"
        labels["异常情况"]["爆炸性断裂"] = "是"
        with self.assertRaises(ReviewError):
            self.app.save(self.payload("confirmed", labels=labels))
        labels["异常情况"]["爆炸性断裂"] = "否"
        self.assertEqual(self.app.save(self.payload("confirmed", labels=labels))["labels"], labels)
        with self.assertRaises(ReviewError):
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
        labels["断裂模式"] = labels["断裂位置"] = "无"
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

    def test_source_preview_is_development_only_and_hash_verified(self):
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
        for request in (Request(base + "/api/bootstrap", headers={"Host": "evil.example"}), Request(base + "/api/bootstrap", headers={"Origin": "http://evil.example"}), Request(base + "/api/reviews", data=b"{}", method="POST")):
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            urlopen(base + "/media?candidate_id=../fixed_test")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
