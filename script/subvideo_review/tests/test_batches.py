"""批次选择（B0／B1／B2／B3）契约测试（红阶段）。

三层断言，全部只读：

1. `script/subvideo_review/batches.py` 的纯函数：用合成 candidates 字典驱动 `load_definitions()`
   / `select()`，钉死配置校验错误类别、explicit_ids 求交与缺失上报、规则批次的 scope／
   fold_roles（任一折命中即命中）语义、undefined 批次只产出 fold_pool_counts。
2. `GET /api/batches`：只读、无需令牌、配置缺失时仍 200 且 batches 为空；并守卫
   `/api/bootstrap` 的键集合与 `app.export()` 字节不因该功能改变（批次配置不得进入身份摘要）。
3. 真实清单漂移守卫：读仓库内 `data/sub_video/manifest.json` + `data/splits/three-fold/`
   七份成员文件实算，与 `data/subvideo-review/batches.json` 的定义对齐；B0 的 id 从
   `docs/TODO.md` 第 6 节解析，不硬编码后再断言同一份硬编码。

合成项目只写临时目录，不访问真实媒体、不写真实审核记录、不绑定 8765。
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import build_opener, ProxyHandler

urlopen = build_opener(ProxyHandler({})).open

from script.subvideo_review.server import ReviewApp, handler_for  # noqa: E402  (需在 sys.path 就绪后导入)

SCHEMA = "subvideo-review-batches/v1"
PROVENANCE = {"source": "docs/TODO.md", "section": "6. SUBVIDEO-HUMAN-REVIEW", "note": "合成数据"}
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_MANIFEST_PATH = REPO_ROOT / "data/sub_video/manifest.json"
REAL_SPLIT_DIR = REPO_ROOT / "data/splits/three-fold"
REAL_BATCHES_PATH = REPO_ROOT / "data/subvideo-review/batches.json"
REAL_AUDIT_PATH = REPO_ROOT / "data/sub_video/audit.json"
REAL_TODO_PATH = REPO_ROOT / "docs/TODO.md"
REAL_B2_DRAFT_PATH = REPO_ROOT / "docs/subvideo-eval-subset-draft.md"

# `/api/bootstrap` 改动前（本功能之前）的键集合；本功能不得新增批次相关字段。
BOOTSTRAP_KEYS = {"manifest_sha256", "token", "options", "candidates", "audit_current", "audit_status",
                  "audit_message", "audit_issue_candidate_count", "pending_sources", "project_root",
                  "records_path"}


def load_batches_module():
    """实现阶段应提供 `script/subvideo_review/batches.py`；缺失时按「本用例失败」报告。"""
    return importlib.import_module("script.subvideo_review.batches")


def batch_list(loaded):
    """`load_definitions()` 可返回批次列表或含 batches 的完整定义；两种都接受。"""
    if isinstance(loaded, dict):
        return loaded["batches"]
    return loaded


def definition(batch_id, *, status="ready", selection=None, name=None, description="合成用途"):
    return {"batch_id": batch_id, "name": name or f"批次 {batch_id}", "description": description,
            "status": status,
            "selection": {"type": "rule", "scope": "test"} if selection is None else selection,
            "provenance": dict(PROVENANCE)}


def definitions(*batches):
    return {"schema": SCHEMA, "batches": list(batches)}


def explicit_batch(batch_id="B0", ids=("cand_a",)):
    return definition(batch_id, selection={"type": "explicit_ids", "ids": list(ids)})


def rule_batch(batch_id="B1", **selection):
    return definition(batch_id, selection={"type": "rule", **selection})


def synthetic_candidates():
    """合成 candidates：candidate_id → 记录（键序即候选顺序）。"""
    return {
        "dev_fold0_val": {"candidate_id": "dev_fold0_val", "scope": "development",
                          "folds": {"0": "val", "1": "train", "2": "train"}},
        "dev_all_train": {"candidate_id": "dev_all_train", "scope": "development",
                          "folds": {"0": "train", "1": "train", "2": "train"}},
        "test_a": {"candidate_id": "test_a", "scope": "test", "folds": {"0": "test", "1": "test", "2": "test"}},
        "test_b": {"candidate_id": "test_b", "scope": "test", "folds": {"0": "test", "1": "test", "2": "test"}},
    }


class DefinitionLoadingTests(unittest.TestCase):
    """`load_definitions(path)` 的校验与顺序保留。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, payload):
        path = self.root / "batches.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def assert_config_error(self, payload, *fragments):
        path = self.write(payload)
        module = load_batches_module()

        with self.assertRaises(ValueError) as caught:
            module.load_definitions(path)

        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message,
                          f"配置错误消息应点名字段「{fragment}」以便分辨错误类别，实际消息为「{message}」")

    def test_load_definitions_keeps_declared_order_and_fields(self):
        module = load_batches_module()
        path = self.write(definitions(definition("B3", name="训练集"),
                                      definition("B1", name="固定测试集")))

        batches = batch_list(module.load_definitions(path))

        self.assertEqual([row["batch_id"] for row in batches], ["B3", "B1"],
                         "load_definitions() 必须保留配置文件里的批次顺序")
        self.assertEqual(batches[1]["name"], "固定测试集")
        self.assertEqual(batches[1]["provenance"], PROVENANCE)

    def test_load_definitions_rejects_unknown_schema(self):
        self.assert_config_error({"schema": "subvideo-review-batches/v2",
                                  "batches": [definition("B1")]}, "schema")

    def test_load_definitions_rejects_duplicate_batch_id(self):
        self.assert_config_error(definitions(definition("B1"), definition("B1")), "B1", "重复")

    def test_load_definitions_rejects_unknown_status(self):
        self.assert_config_error(definitions(definition("B1", status="draft-wip")), "status", "draft-wip")

    def test_load_definitions_rejects_unknown_selection_type(self):
        self.assert_config_error(definitions(definition("B1", selection={"type": "regex", "pattern": ".*"})),
                                 "type", "regex")

    def test_load_definitions_rejects_ready_batch_without_selection(self):
        broken = definition("B1")
        broken.pop("selection")
        self.assert_config_error(definitions(broken), "B1", "selection")

    def test_load_definitions_rejects_non_string_explicit_id(self):
        self.assert_config_error(definitions(explicit_batch("B0", ids=["cand_a", 17])),
                                 "explicit_ids", "B0")

    def test_load_definitions_rejects_duplicate_explicit_id(self):
        self.assert_config_error(definitions(explicit_batch("B0", ids=["cand_a", "cand_a"])),
                                 "explicit_ids", "重复")

    def test_load_definitions_rejects_unsupported_fold_match(self):
        self.assert_config_error(
            definitions(rule_batch("B3", scope="development", fold_roles=["train"], fold_match="all")),
            "fold_match", "all")

    def test_load_definitions_rejects_unknown_fold_role(self):
        self.assert_config_error(definitions(rule_batch("B3", scope="development", fold_roles=["validation"])),
                                 "fold_roles", "validation")


class SelectionTests(unittest.TestCase):
    """`select(batch, candidates)` 的候选选择语义（合成数据，纯函数）。"""

    def setUp(self):
        self.module = load_batches_module()
        self.candidates = synthetic_candidates()

    def test_rule_scope_test_selects_only_test_candidates(self):
        result = self.module.select(rule_batch("B1", scope="test"), self.candidates)

        self.assertEqual(result["candidate_ids"], ["test_a", "test_b"])
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["missing_ids"], [])
        self.assertIsNone(result["fold_pool_counts"], "ready 批次不应产出 fold_pool_counts")

    def test_rule_fold_roles_val_matches_a_candidate_val_in_any_fold(self):
        result = self.module.select(rule_batch("B2", scope="development", fold_roles=["val"]), self.candidates)

        self.assertEqual(result["candidate_ids"], ["dev_fold0_val"],
                         "fold_roles 为「任一折命中」，只有 fold0 是 val 的候选命中，三折全 train 的候选不命中")

    def test_rule_fold_roles_train_matches_cross_fold_candidates(self):
        result = self.module.select(rule_batch("B3", scope="development", fold_roles=["train"],
                                               fold_match="any"), self.candidates)

        self.assertEqual(result["candidate_ids"], ["dev_fold0_val", "dev_all_train"],
                         "同一候选可同时在 val 池与 train 池：fold0=val 但 fold1/fold2=train 仍应命中 train 规则")

    def test_explicit_ids_intersect_candidates_and_report_missing(self):
        result = self.module.select(explicit_batch("B0", ids=["dev_fold0_val", "unknown_id", "test_a"]),
                                    self.candidates)

        self.assertEqual(result["candidate_ids"], ["dev_fold0_val", "test_a"])
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["missing_ids"], ["unknown_id"],
                         "不存在的 explicit id 必须被上报，不得静默丢弃")

    def test_explicit_ids_follow_candidate_order(self):
        result = self.module.select(explicit_batch("B0", ids=["test_b", "test_a"]), self.candidates)

        self.assertEqual(result["candidate_ids"], ["test_a", "test_b"],
                         "candidate_ids 取候选顺序（与候选清单一致），不取配置里的书写顺序")

    def test_undefined_batch_reports_fold_pools_without_candidates(self):
        result = self.module.select(definition("B2", status="undefined",
                                               selection={"type": "rule", "scope": "development",
                                                          "fold_roles": ["val"], "sample_per_fold": 1}),
                                    self.candidates)

        self.assertEqual(result["candidate_ids"], [], "undefined 批次不可选，不得给出候选 id")
        self.assertIsNone(result["candidate_count"], "undefined 批次的候选数必须是 null，不是 0")
        self.assertEqual(result["fold_pool_counts"], {"0": 1, "1": 0, "2": 0},
                         "undefined 批次只给出逐折池大小：该折 role 命中 fold_roles 单值的开发集候选数")


class SyntheticProject(unittest.TestCase):
    """合成项目：2 个 test 来源 + 4 个开发来源，每个来源一个候选（共 6 个）。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / "data/sub_video/manifest.json"
        self.manifest_path.parent.mkdir(parents=True)
        media_dir = self.manifest_path.parent / "videos"
        media_dir.mkdir()
        split_dir = self.root / "data/splits/three-fold"
        split_dir.mkdir(parents=True)
        (split_dir / "test.json").write_text(json.dumps({"video_ids": ["fixed_a", "fixed_b"]}), encoding="utf-8")
        members = {
            (0, "train"): ["dev_2", "dev_3"], (0, "val"): ["dev_1", "dev_4"],
            (1, "train"): ["dev_1", "dev_3"], (1, "val"): ["dev_2", "dev_4"],
            (2, "train"): ["dev_1", "dev_2"], (2, "val"): ["dev_3", "dev_4"],
        }
        for (fold, partition), ids in members.items():
            (split_dir / f"fold_{fold}_{partition}.json").write_text(json.dumps({"video_ids": ids}),
                                                                    encoding="utf-8")
        sources, candidates = [], []
        for source_id in ("fixed_a", "fixed_b", "dev_1", "dev_2", "dev_3", "dev_4"):
            content = f"synthetic media for {source_id}".encode()
            (media_dir / f"{source_id}.mp4").write_bytes(content)
            sources.append({"video_id": source_id, "source_type": "real"})
            candidates.append({"candidate_id": f"cand_{source_id}", "source_video_id": source_id,
                               "output_path": f"videos/{source_id}.mp4",
                               "output": {"sha256": hashlib.sha256(content).hexdigest()},
                               "status": "cropped", "candidate_labels": {"断裂状态": "已断裂"}})
        self.manifest = {"schema": "tensile-unified-sub-video/1", "generation_batch_id": "synthetic-batches",
                         "identity": {"guard_seconds": 0.5}, "sources": sources, "candidates": candidates}
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.review_dir = self.root / "data/subvideo-review"
        self.batches_path = self.review_dir / "batches.json"
        self.records_path = self.review_dir / "reviews.json"
        self.app = ReviewApp(self.root)

    def synthetic_config(self):
        return definitions(
            explicit_batch("B0", ids=["cand_dev_1", "missing_candidate"]),
            rule_batch("B1", scope="test"),
            definition("B2", status="undefined", selection={"type": "rule", "scope": "development",
                                                            "fold_roles": ["val"], "sample_per_fold": 1}),
            rule_batch("B3", scope="development", fold_roles=["train"], fold_match="any"),
        )

    def write_config(self):
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.batches_path.write_text(json.dumps(self.synthetic_config(), ensure_ascii=False), encoding="utf-8")
        return self.batches_path

    def configured_app(self):
        """先写配置再建应用：无论实现是启动时读取还是请求时读取，两者都必须通过。"""
        self.write_config()
        return ReviewApp(self.root)

    def serve(self, app):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def get_json(self, app, path):
        with urlopen(self.serve(app) + path) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)


def batch_by_id(payload, batch_id):
    for row in payload["batches"]:
        if row.get("batch_id") == batch_id:
            return row
    raise AssertionError(f"响应里应有批次 {batch_id}，实际为 {[row.get('batch_id') for row in payload['batches']]}")


class BatchEndpointTests(SyntheticProject):
    """`GET /api/batches`：只读、无需令牌、缺配置不报错。"""

    def test_api_batches_without_config_returns_200_and_empty_list(self):
        payload = self.get_json(self.app, "/api/batches")

        self.assertEqual(payload["schema"], SCHEMA)
        self.assertEqual(payload["batches"], [], "批次配置缺失时不得报错，应返回空批次列表")
        self.assertEqual(payload["candidate_total"], 6)

    def test_api_batches_reports_ready_batch_candidates(self):
        payload = self.get_json(self.configured_app(), "/api/batches")

        b1 = batch_by_id(payload, "B1")
        self.assertTrue(b1["selectable"], "ready 批次必须可选")
        self.assertEqual(b1["status"], "ready")
        self.assertEqual(b1["candidate_count"], 2)
        self.assertEqual(b1["candidate_ids"], ["cand_fixed_a", "cand_fixed_b"])
        self.assertEqual(b1["missing_ids"], [])
        self.assertIsNone(b1["fold_pool_counts"])
        self.assertEqual(b1["provenance"], PROVENANCE, "接口必须原样带出批次来源说明")

    def test_api_batches_reports_undefined_batch_with_fold_pools_only(self):
        payload = self.get_json(self.configured_app(), "/api/batches")

        b2 = batch_by_id(payload, "B2")
        self.assertFalse(b2["selectable"], "undefined 批次不可选")
        self.assertIsNone(b2["candidate_count"])
        self.assertEqual(b2["candidate_ids"], [])
        self.assertEqual(b2["fold_pool_counts"], {"0": 2, "1": 2, "2": 2},
                         "undefined 批次必须给出每折池大小（每折 role 为 val 的开发集候选数）")

    def test_api_batches_reports_missing_explicit_ids(self):
        payload = self.get_json(self.configured_app(), "/api/batches")

        b0 = batch_by_id(payload, "B0")
        self.assertEqual(b0["candidate_ids"], ["cand_dev_1"])
        self.assertEqual(b0["missing_ids"], ["missing_candidate"],
                         "配置里不存在的显式 id 必须在接口响应里被报告")

    def test_api_batches_is_read_only_and_needs_no_token(self):
        app = self.configured_app()
        base = self.serve(app)
        before = sorted(path.name for path in self.review_dir.iterdir())
        config_bytes = self.batches_path.read_bytes()

        for _ in range(2):
            with urlopen(base + "/api/batches") as response:  # 不带 X-Review-Token
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response)["schema"], SCHEMA)

        self.assertEqual(sorted(path.name for path in self.review_dir.iterdir()), before,
                         "只读接口不得在记录目录留下任何文件")
        self.assertEqual(self.batches_path.read_bytes(), config_bytes, "只读接口不得改写批次配置")
        self.assertFalse(self.records_path.exists(), "只读接口不得创建审核记录")

    def test_api_batches_reports_dec007_counts_and_supports_hide_excluded(self):
        excl_path = self.root / "data/splits/dev-exclusions.json"
        excl_path.write_text(json.dumps({
            "schema": "tensile-dev-exclusions/1",
            "decision_id": "DEC-007",
            "excluded_dev_sources": [{
                "source_id": "dev_2",
                "reason": "near_duplicate_of_test_source",
                "matched_test_source_id": "fixed_a",
                "excluded_subvideo_ids": ["cand_dev_2"],
            }],
        }), encoding="utf-8")
        app = self.configured_app()

        full = self.get_json(app, "/api/batches")
        self.assertFalse(full["hide_excluded"])
        self.assertEqual(full["raw_candidate_total"], 6)
        self.assertEqual(full["candidate_total"], 6)
        self.assertEqual(full["excluded_candidate_total"], 1)
        b3 = batch_by_id(full, "B3")
        self.assertEqual(b3["candidate_count"], 3)
        self.assertEqual(b3["raw_candidate_count"], 3)
        self.assertEqual(b3["clean_candidate_count"], 2)
        self.assertEqual(b3["excluded_candidate_count"], 1)
        self.assertEqual(b3["clean_unreviewed_count"], 2)
        self.assertEqual(b3["excluded_unreviewed_count"], 1)
        self.assertEqual(b3["excluded_candidate_ids"], ["cand_dev_2"])
        self.assertEqual(b3["excluded_sources"], ["dev_2"])
        self.assertIn("cand_dev_2", b3["candidate_ids"])

        hidden = self.get_json(app, "/api/batches?hide_excluded=1")
        self.assertTrue(hidden["hide_excluded"])
        self.assertEqual(hidden["candidate_total"], 5)
        self.assertEqual(hidden["raw_candidate_total"], 6)
        b3_hidden = batch_by_id(hidden, "B3")
        self.assertEqual(b3_hidden["candidate_count"], 2)
        self.assertEqual(b3_hidden["raw_candidate_count"], 3)
        self.assertEqual(b3_hidden["clean_unreviewed_count"], 2)
        self.assertEqual(b3_hidden["excluded_unreviewed_count"], 1)
        self.assertNotIn("cand_dev_2", b3_hidden["candidate_ids"])
        self.assertFalse(self.records_path.exists(), "只读批次接口不得创建审核记录")


class ExistingContractGuardTests(SyntheticProject):
    """本功能不得改变既有 bootstrap 契约与审核身份摘要。"""

    def test_bootstrap_key_set_is_unchanged_by_the_batch_feature(self):
        self.assertEqual(set(self.app.bootstrap()), BOOTSTRAP_KEYS,
                         "未选批次时 bootstrap 响应必须与改动前完全一致（键集合不多不少）")
        configured = self.configured_app()
        self.assertEqual(set(configured.bootstrap()), BOOTSTRAP_KEYS,
                         "存在批次配置时 bootstrap 也不得新增批次相关字段")

    def test_export_bytes_are_identical_with_and_without_batches_config(self):
        before = self.app.export()
        self.assertTrue(before)
        configured = self.configured_app()

        self.assertEqual(configured.export(), before,
                         "批次配置不得进入导出内容：有／无 batches.json 时 export() 必须逐字节相同")

    def test_review_subject_sha256_is_identical_with_and_without_batches_config(self):
        before = {cid: candidate["review_subject_sha256"] for cid, candidate in self.app.candidates.items()}
        configured = self.configured_app()
        after = {cid: candidate["review_subject_sha256"] for cid, candidate in configured.candidates.items()}

        self.assertEqual(after, before, "批次配置不得改变已有审核记录的身份摘要")
        self.assertEqual(len(before), 6)

    def test_dec007_exclusions_preserve_bootstrap_keys_export_and_identity_hashes(self):
        before_export = self.app.export()
        before_subjects = {cid: c["review_subject_sha256"] for cid, c in self.app.candidates.items()}
        before_split_id = self.app.split_identity_sha256
        (self.root / "data/splits/dev-exclusions.json").write_text(json.dumps({
            "schema": "tensile-dev-exclusions/1",
            "decision_id": "DEC-007",
            "excluded_dev_sources": [{
                "source_id": "dev_1",
                "reason": "near_duplicate_of_test_source",
                "excluded_subvideo_ids": ["cand_dev_1"],
            }],
        }), encoding="utf-8")
        reloaded = ReviewApp(self.root)
        self.assertEqual(set(reloaded.bootstrap()), BOOTSTRAP_KEYS)
        self.assertEqual(reloaded.export(), before_export)
        self.assertEqual({cid: c["review_subject_sha256"] for cid, c in reloaded.candidates.items()}, before_subjects)
        self.assertEqual(reloaded.split_identity_sha256, before_split_id)


def split_ids(name):
    value = json.loads((REAL_SPLIT_DIR / name).read_text(encoding="utf-8"))
    return set(value["video_ids"] if isinstance(value, dict) else value)


def real_candidates():
    """按 server.py 的候选过滤口径（status 缺失／None／"cropped"）构造真实候选映射。"""
    manifest = json.loads(REAL_MANIFEST_PATH.read_text(encoding="utf-8"))
    test_ids = split_ids("test.json")
    members = {(str(fold), partition): split_ids(f"fold_{fold}_{partition}.json")
               for fold in range(3) for partition in ("train", "val")}
    development_ids = set().union(*members.values())
    candidates = {}
    for item in manifest["candidates"]:
        if item.get("status") not in (None, "cropped"):
            continue
        source_id = item.get("source_video_id", item.get("source_id"))
        if source_id in test_ids:
            scope, folds = "test", {str(fold): "test" for fold in range(3)}
        elif source_id in development_ids:
            scope = "development"
            folds = {str(fold): ("train" if source_id in members[(str(fold), "train")] else "val")
                     for fold in range(3)}
        else:
            continue
        candidates[item["candidate_id"]] = {"candidate_id": item["candidate_id"], "scope": scope, "folds": folds}
    return candidates


def real_definitions():
    module = load_batches_module()
    return {row["batch_id"]: row for row in batch_list(module.load_definitions(REAL_BATCHES_PATH))}


def b0_ids_from_todo(path=REAL_TODO_PATH):
    """从 docs/TODO.md 第 6 节「下一步」解析 B0 的候选名（不硬编码任何 id）。"""
    text = Path(path).read_text(encoding="utf-8")
    start = text.index("## 6. SUBVIDEO-HUMAN-REVIEW")
    section = text[start:text.index("\n## ", start)]
    next_step = section.index("### 下一步")
    step_end = section.index("### 完成标准", next_step)
    ids = []
    for line in section[next_step:step_end].splitlines():
        match = re.match(r"\s*-\s*`video_\d+`：(.+)$", line)
        if match:
            ids.extend(re.findall(r"`([^`]+)`", match.group(1)))
    return ids


def b2_ids_by_fold_from_draft(path=REAL_B2_DRAFT_PATH):
    """从 docs/subvideo-eval-subset-draft.md §4.3 按折解析 B2 的 180 条候选名（不硬编码任何 id）。"""
    text = Path(path).read_text(encoding="utf-8")
    start = text.index("### 4.3 B2 180 条按折分组清单")
    end = text.index("\n## 5.", start)
    by_fold = {}
    current_fold = None
    for line in text[start:end].splitlines():
        fold_match = re.match(r"^####\s+Fold\s+([012])\s+val", line)
        if fold_match:
            current_fold = fold_match.group(1)
            by_fold[current_fold] = []
            continue
        match = re.match(r"\s*-\s*`video_\d+`：(.+)$", line)
        if match and current_fold is not None:
            by_fold[current_fold].extend(re.findall(r"`([^`]+)`", match.group(1)))
    return by_fold


def b2_ids_from_draft(path=REAL_B2_DRAFT_PATH):
    by_fold = b2_ids_by_fold_from_draft(path)
    return [cid for f in ("0", "1", "2") for cid in by_fold.get(f, [])]


class RealDataGuardTests(unittest.TestCase):
    """真实清单漂移守卫：清单或划分变更时本组测试应当变红。"""

    def setUp(self):
        self.module = load_batches_module()
        self.candidates = real_candidates()
        self.batches = real_definitions()

    def select(self, batch_id):
        return self.module.select(self.batches[batch_id], self.candidates)

    def test_real_batch_definitions_cover_b0_to_b3(self):
        self.assertEqual(set(self.batches), {"B0", "B1", "B2", "B3"})
        for batch_id in ("B0", "B1", "B2", "B3"):
            self.assertEqual(self.batches[batch_id]["status"], "ready", f"{batch_id} 应已定义完成")

    def test_real_batch_b1_selects_the_314_test_candidates(self):
        result = self.select("B1")

        self.assertEqual(result["candidate_count"], 314)
        self.assertEqual(len(result["candidate_ids"]), 314)
        self.assertEqual(result["missing_ids"], [])
        scopes = {self.candidates[candidate_id]["scope"] for candidate_id in result["candidate_ids"]}
        self.assertEqual(scopes, {"test"})

    def test_real_batch_b3_selects_the_1319_development_candidates(self):
        result = self.select("B3")

        self.assertEqual(result["candidate_count"], 1319)
        scopes = {self.candidates[candidate_id]["scope"] for candidate_id in result["candidate_ids"]}
        self.assertEqual(scopes, {"development"})

    def test_real_batches_b1_and_b3_partition_all_1633_candidates(self):
        b1 = set(self.select("B1")["candidate_ids"])
        b3 = set(self.select("B3")["candidate_ids"])

        self.assertEqual(len(self.candidates), 1633)
        self.assertEqual(b1 & b3, set(), "test 与开发集候选不得重叠")
        self.assertEqual(b1 | b3, set(self.candidates), "B1 与 B3 必须覆盖全部候选")

    def test_real_val_fold_pools_remain_432_440_447(self):
        probe = definition("B2_POOL", status="undefined",
                           selection={"type": "rule", "scope": "development", "fold_roles": ["val"]})
        result = self.module.select(probe, self.candidates)

        self.assertEqual(result["candidate_ids"], [])
        self.assertIsNone(result["candidate_count"])
        self.assertEqual(result["fold_pool_counts"], {"0": 432, "1": 440, "2": 447})

    def test_real_batch_b2_selects_180_val_candidates_matching_draft_and_guards(self):
        documented_by_fold = b2_ids_by_fold_from_draft()
        documented = [cid for f in ("0", "1", "2") for cid in documented_by_fold.get(f, [])]
        b2_def = self.batches["B2"]
        b2 = self.select("B2")
        b0_ids = set(self.select("B0")["candidate_ids"])
        prior_confirmed = b0_ids | {"video_0050_coverage_02"}

        self.assertEqual(b2_def["selection"]["type"], "explicit_ids")
        self.assertEqual(set(documented_by_fold), {"0", "1", "2"})
        for f in ("0", "1", "2"):
            self.assertEqual(len(documented_by_fold[f]), 60, f"草稿中 fold {f} 必须恰好列出 60 条")
            for cid in documented_by_fold[f]:
                self.assertEqual(self.candidates[cid]["folds"][f], "val",
                                 f"草稿 fold {f} 下的 {cid} 实际不属于 fold {f} val")
        self.assertEqual(len(documented), 180)
        self.assertEqual(len(set(documented)), 180, "subvideo-eval-subset-draft.md 中的 B2 候选名不应重复")
        self.assertEqual(b2["candidate_count"], 180)
        self.assertEqual(b2["missing_ids"], [], "B2 的 180 条必须全部存在于当前清单")
        self.assertEqual(set(b2["candidate_ids"]), set(documented),
                         "batches.json 的 B2 必须与 docs/subvideo-eval-subset-draft.md 登记的 180 条一致")
        scopes = {self.candidates[cid]["scope"] for cid in b2["candidate_ids"]}
        self.assertEqual(scopes, {"development"}, "B2 只取开发集，不取 test")
        self.assertEqual(set(b2["candidate_ids"]) & prior_confirmed, set(),
                         "B2 不得与 B0（32 条）及试审（video_0050_coverage_02）重复")

        fold_counts = {f: sum(self.candidates[cid]["folds"][f] == "val" for cid in b2["candidate_ids"])
                       for f in ("0", "1", "2")}
        self.assertEqual(fold_counts, {"0": 60, "1": 60, "2": 60}, "B2 每折 val 必须恰好 60 条")

        manifest = json.loads(REAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        sources_by_cid = {c["candidate_id"]: c["source_video_id"] for c in manifest["candidates"]}
        widths = {c["candidate_id"]: c["output"]["media"]["width"] for c in manifest["candidates"]}

        # 必须 100% 覆盖全部 87 个仍有未审候选的开发来源
        unreviewed_dev_sources = {
            sources_by_cid[cid] for cid, c in self.candidates.items()
            if c["scope"] == "development" and cid not in prior_confirmed
        }
        b2_sources = {sources_by_cid[cid] for cid in b2["candidate_ids"]}
        self.assertEqual(len(unreviewed_dev_sources), 87)
        self.assertEqual(b2_sources, unreviewed_dev_sources, "B2 必须覆盖全部 87 个未审开发源")

        # 全量覆盖开发集中全部 37 条未审待关注候选（开发集共 40 条待关注，其中 3 条已在 B0 确认）
        audit = json.loads(REAL_AUDIT_PATH.read_text(encoding="utf-8"))
        dev_attention = {
            e["candidate_id"] for e in audit["candidates"]
            if e.get("issues") and self.candidates[e["candidate_id"]]["scope"] == "development"
        }
        unreviewed_dev_attention = dev_attention - b0_ids
        self.assertEqual(len(unreviewed_dev_attention), 37)
        self.assertTrue(unreviewed_dev_attention.issubset(set(b2["candidate_ids"])),
                        "B2 必须完整纳入全部 37 条未审开发集待关注候选")

        # 每折均覆盖全部三个画幅档（w_le_200 / w_200_400 / w_gt_400）
        for f in ("0", "1", "2"):
            f_ids = [cid for cid in b2["candidate_ids"] if self.candidates[cid]["folds"][f] == "val"]
            tiers = {"w_le_200" if widths[cid] <= 200 else "w_200_400" if widths[cid] < 400 else "w_gt_400"
                     for cid in f_ids}
            self.assertEqual(tiers, {"w_le_200", "w_200_400", "w_gt_400"}, f"fold {f} 须覆盖全部三个画幅档")

    def test_real_batch_b0_ids_exist_in_manifest_and_are_development(self):
        documented = b0_ids_from_todo()
        b0 = self.select("B0")

        self.assertEqual(len(documented), 32)
        self.assertEqual(len(set(documented)), 32, "docs/TODO.md 第 6 节的 B0 候选名不应重复")
        self.assertEqual(set(b0["candidate_ids"]), set(documented),
                         "batches.json 的 B0 必须与 docs/TODO.md 登记的 32 条一致")
        self.assertEqual(b0["missing_ids"], [], "B0 的 32 条必须全部存在于当前清单")
        scopes = {self.candidates[candidate_id]["scope"] for candidate_id in documented}
        self.assertEqual(scopes, {"development"}, "B0 只取开发集，不取 test")

    def test_real_candidate_video_0001_fracture_01_is_val_and_train_in_different_folds(self):
        candidate_id = "video_0001_fracture_01"
        self.assertIn(candidate_id, self.candidates)
        folds = self.candidates[candidate_id]["folds"]

        self.assertEqual(folds, {"0": "val", "1": "train", "2": "train"},
                         "该候选同一实例在三折分别是 val 与 train，是 B2／B3 跨池命中的具体证据")
        self.assertIn(candidate_id, self.select("B3")["candidate_ids"], "fold1／fold2 为 train，应命中 B3")
        self.assertEqual(folds["0"], "val", "fold0 为 val，因此同时计入 B2 的 fold0 池")

    def test_real_dec007_exclusions_b3_counts_and_frozen_subset_integrity(self):
        app = ReviewApp(REPO_ROOT)
        bootstrap = app.bootstrap()
        excluded_rows = [row for row in bootstrap["candidates"] if row["dec007_excluded"]]
        self.assertEqual(len(bootstrap["candidates"]), 1633)
        self.assertEqual(len(excluded_rows), 20, "DEC-007 应标记 video_0006 (19) + video_0079 (1) 共 20 条子视频")
        self.assertEqual({row["source_id"] for row in excluded_rows}, {"video_0006", "video_0079"})
        for row in excluded_rows:
            self.assertEqual(row["dec007_reason"], "near_duplicate_of_test_source")
            self.assertIn(row["dec007_matched_test_source_id"], ("video_0010", "video_0032"))

        hidden_bootstrap = app.bootstrap(hide_excluded=True)
        self.assertEqual(len(hidden_bootstrap["candidates"]), 1613)
        self.assertFalse(any(row["dec007_excluded"] for row in hidden_bootstrap["candidates"]))

        catalog = app.batch_catalog()
        b3 = batch_by_id(catalog, "B3")
        self.assertEqual(b3["raw_candidate_count"], 1319)
        self.assertEqual(b3["candidate_count"], 1319)
        self.assertEqual(b3["clean_candidate_count"], 1299)
        self.assertEqual(b3["excluded_candidate_count"], 20)
        self.assertEqual(b3["clean_unreviewed_count"], 1089)
        self.assertEqual(b3["excluded_unreviewed_count"], 17)
        self.assertEqual(b3["excluded_unreviewed_sources"], ["video_0006"])
        self.assertEqual(b3["clean_confirmed_count"], 210)
        self.assertEqual(b3["excluded_confirmed_count"], 3)

        hidden_catalog = app.batch_catalog(hide_excluded=True)
        b3_hidden = batch_by_id(hidden_catalog, "B3")
        self.assertEqual(b3_hidden["candidate_count"], 1299)
        self.assertEqual(b3_hidden["raw_candidate_count"], 1319)
        self.assertEqual(b3_hidden["clean_unreviewed_count"], 1089)
        self.assertEqual(b3_hidden["excluded_unreviewed_count"], 17)
        self.assertEqual(set(b3_hidden["candidate_ids"]) & set(b3["excluded_candidate_ids"]), set())

        # Verify V1_PINNED_INPUTS & frozen eval subsets remain 100% intact.
        from script.five_label_eval.freeze_subsets import verify_frozen_subsets
        verified = verify_frozen_subsets(REPO_ROOT / "data/eval-subsets")
        self.assertEqual(len(verified), 2)


if __name__ == "__main__":
    unittest.main()
