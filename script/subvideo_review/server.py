"""Loopback-only, standard-library human-review service and JSONL exporter."""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
# 单值字段的取值必须与 script/five_label_eval/score.py 的 SINGLES 逐项一致（含顺序），
# 否则工作台会写入评分器不认的标签；这里保持字面量列表，便于静态核对。
# 只收新术语「无法判断」：历史记录里的旧词「无法确定」不做兼容改写，也不是合法取值——
# 那些旧词来自改造前的 CSV/清单，服务端如实保留已存记录（不改写不迁移不重算摘要：
# review_subject_sha256、revision_sha256 与存储文件字节均保持不变），旧词到统一术语的
# 显示层映射由前端负责；不得静默改写已存记录。
OPTIONS = {
    "断裂状态": ["未断裂", "发生断裂", "已断裂", "无法判断"],
    "断裂模式": ["脆性断裂", "韧性断裂", "半脆半韧断裂", "无法判断"],
    "断裂位置": ["标距内", "标距外非根部", "夹持根部", "无法判断"],
    "异常情况": {k: ["是", "否", "无法判断"] for k in ("未夹紧", "视频异常", "爆炸性断裂")},
    "断裂现象": {k: ["是", "否", "无法判断"] for k in ("伸长", "颈缩", "开裂", "界面分离", "断后脱夹")},
}
STATUSES = {"draft", "confirmed", "returned", "question"}
STORE_SCHEMA = "tensile-subvideo-human-review/2"


class ReviewError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_labels(labels, *, complete=False):
    if not isinstance(labels, dict) or set(labels) - set(OPTIONS):
        raise ReviewError("标签必须是五类标签对象，不能包含其他字段")
    missing = []
    for name, choices in OPTIONS.items():
        value = labels.get(name)
        if isinstance(choices, dict):
            if value is None:
                value = {}
            if not isinstance(value, dict) or set(value) - set(choices):
                raise ReviewError(f"{name} 必须逐项填写")
            for item, allowed in choices.items():
                choice = value.get(item)
                if choice in (None, ""):
                    missing.append(f"{name}.{item}")
                elif choice not in allowed:
                    raise ReviewError(f"{name}.{item} 取值无效")
        elif value in (None, ""):
            missing.append(name)
        elif value not in choices:
            raise ReviewError(f"{name} 取值无效")
    if complete and missing:
        raise ReviewError("确认须完成全部 11 项；未完成请保存草稿或疑问。缺少：" + "、".join(missing))
    anomaly = labels.get("异常情况") or {}
    if labels.get("断裂状态") == "未断裂" and anomaly.get("爆炸性断裂") == "是":
        raise ReviewError("未断裂与爆炸性断裂互斥")
    if complete and labels.get("断裂状态") == "未断裂" and (labels.get("断裂现象") or {}).get("断后脱夹") == "是":
        raise ReviewError("未断裂与断后脱夹互斥；请人工核对，或保存草稿/疑问；不会自动修改标签")
    return missing


@contextlib.contextmanager
def confined_file(root, relative):
    """Walk from a trusted directory fd, refusing all symlink components."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ("..", ".") for p in parts):
        raise ReviewError("媒体路径越界", 403)
    descriptors = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            descriptors.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        descriptors.append(fd)
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ReviewError("媒体必须是普通文件", 403)
        with os.fdopen(os.dup(fd), "rb") as stream:
            yield stream
    except FileNotFoundError as error:
        raise ReviewError("候选媒体不存在；请核对 --project-root 与清单对应的当前媒体目录", 404) from error
    except OSError as error:
        raise ReviewError("媒体路径不可用或包含符号链接", 403) from error
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


class ReviewApp:
    def __init__(self, project_root, *, manifest=None, records=None, max_media_bytes=512 * 1024 * 1024):
        self.root = Path(project_root).resolve(strict=True)
        self.file_signatures = {}
        self.manifest_path = Path(manifest) if manifest else self.root / "data/sub_video/manifest.json"
        if not self.manifest_path.is_absolute():
            self.manifest_path = self.root / self.manifest_path
        self.manifest_path = self.manifest_path.resolve(strict=True)
        raw = self.capture_file(self.manifest_path)
        self.manifest_sha256 = digest(raw)
        self.manifest = json.loads(raw)
        self.media_root = self.manifest_path.parent
        self.records_path = Path(records) if records else self.root / "data/subvideo-review/reviews.json"
        if not self.records_path.is_absolute():
            self.records_path = self.root / self.records_path
        self.records_path = self.records_path.resolve()
        protected = [self.manifest_path, self.root / "data/annotation-table-full.csv", self.root / "data/roi/manifest.json"]
        if (self.records_path in protected or self.records_path.is_relative_to(self.media_root)
                or (self.records_path.is_relative_to(self.root / "data")
                    and not self.records_path.is_relative_to(self.root / "data/subvideo-review"))):
            raise ReviewError("审核记录必须独立于源标注、ROI 和生成目录")
        self.max_media_bytes = max_media_bytes
        self.token = secrets.token_urlsafe(32)
        self.mutex = threading.Lock()
        self.label_rules_path = self.root / "docs/label.md"
        self.label_rules_sha256 = digest(self.capture_file(self.label_rules_path)) if self.label_rules_path.is_file() else None
        sources = self.manifest.get("sources", [])
        if not isinstance(sources, list):
            raise ReviewError("来源清单无效")
        self.sources = {}
        for source in sources:
            if not isinstance(source, dict):
                raise ReviewError("来源清单无效")
            source_id = source.get("video_id", source.get("source_id"))
            if not isinstance(source_id, str) or not source_id or source_id in self.sources:
                raise ReviewError("来源 ID 缺失或重复")
            self.sources[source_id] = source
        self.audit_issues = {}
        self.audit_current = False
        self.audit_status = "missing"
        self.audit_message = "未找到标签组合核验记录；不能据此判断没有待复核问题。"
        self.audit_path = self.media_root / "audit.json"
        test_file = self.root / "data/splits/three-fold/test.json"
        if not test_file.exists():
            raise ReviewError("缺少固定 test 成员清单；无法保证媒体访问边界")
        split_bytes = self.capture_file(test_file)
        self.split_snapshots = {test_file: digest(split_bytes)}
        test_value = json.loads(split_bytes)
        self.test_ids = set(test_value["video_ids"] if isinstance(test_value, dict) else test_value)
        self.development_ids = set()
        self.fold_members = {}
        for fold in range(3):
            self.fold_members[str(fold)] = {}
            for partition in ("train", "val"):
                split_file = test_file.parent / f"fold_{fold}_{partition}.json"
                if not split_file.exists():
                    raise ReviewError("缺少开发 fold 成员清单；无法确认来源归属")
                split_bytes = self.capture_file(split_file)
                self.split_snapshots[split_file] = digest(split_bytes)
                split_value = json.loads(split_bytes)
                members = set(split_value["video_ids"] if isinstance(split_value, dict) else split_value)
                self.fold_members[str(fold)][partition] = members
                self.development_ids.update(members)
        if self.development_ids & self.test_ids:
            raise ReviewError("固定划分存在开发与 test 成员冲突", 403)
        self.split_identity_sha256 = digest(canonical({
            str(path.relative_to(self.root)): sha for path, sha in self.split_snapshots.items()
        }))
        self.generation_identity_sha256 = digest(canonical(self.manifest.get("identity", {})))
        self.candidates = {}
        seen_candidates = set()
        for item in self.manifest.get("candidates", []):
            if not isinstance(item, dict):
                raise ReviewError("候选清单条目无效")
            candidate_id = item.get("candidate_id")
            source_id = item.get("source_video_id", item.get("source_id"))
            if not isinstance(candidate_id, str) or not candidate_id or candidate_id in seen_candidates:
                raise ReviewError("候选 ID 缺失或重复")
            seen_candidates.add(candidate_id)
            source = self.sources.get(source_id, {})
            self.allowed_source(source_id)
            scope, folds = self.split_for(source_id)
            self.check_split(item, scope, folds)
            self.check_related_sources(item, scope)
            if item.get("status") not in (None, "cropped"):
                continue
            for field in ("source_sha256", "roi_sha256"):
                if item.get(field) and source.get(field) and item[field] != source[field]:
                    raise ReviewError(f"候选与来源的 {field} 不一致：{candidate_id}", 409)
            clip_sha = item.get("output", {}).get("sha256", item.get("clip_sha256"))
            if not isinstance(clip_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", clip_sha):
                raise ReviewError(f"候选缺少有效片段摘要：{candidate_id}")
            relative = item.get("output_path")
            if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts or Path(relative).suffix.lower() not in (".mp4", ".webm", ".ogg"):
                raise ReviewError(f"候选媒体路径无效：{candidate_id}", 403)
            source_type = item.get("source_type", source.get("source_type", "real"))
            if "source_type" in source and source_type != source["source_type"]:
                raise ReviewError("候选与来源的来源类型不一致", 409)
            if source_type not in ("real", "virtual") or not source_id:
                raise ReviewError("来源 ID 或来源类型无效")
            current = {
                "candidate_id": candidate_id, "source_id": source_id, "source_type": source_type,
                "clip_sha256": clip_sha, "manifest_sha256": self.manifest_sha256,
                "generation_batch_id": self.manifest.get("generation_batch_id", self.manifest.get("batch_id")),
                "generation_rule": self.manifest.get("identity", {}),
                "generation_schema": self.manifest.get("schema"),
                "parent_candidate": item.get("parent_candidate", item.get("parent_candidate_id")),
                "source_sha256": item.get("source_sha256", source.get("source_sha256")),
                "roi_sha256": item.get("roi_sha256", source.get("roi_sha256")),
                "source_relationships": {key: source[key] for key in ("related_source_ids", "real_source_ids", "parent_source_id") if key in source},
                "candidate_record_sha256": digest(canonical(item)),
                "source_record_sha256": digest(canonical(source)),
                "generation_identity_sha256": self.generation_identity_sha256,
                "split_identity_sha256": self.split_identity_sha256,
                "label_rules_sha256": self.label_rules_sha256,
                "source_reference": source.get("source_annotation", {}),
                "candidate_reference": item.get("candidate_labels") or {},
                "review_focus": item.get("review_focus") or [],
                "audit_issues": self.audit_issues.get(candidate_id, []),
                "source_preview_available": self.source_preview_available(source_id),
                "scope": scope, "folds": folds,
                "window": {key: item[key] for key in ("window_role", "window_variant", "duration", "start_frame", "end_frame", "start_time", "end_time", "source_start_pts", "source_end_pts", "source_frame_range", "source_anchor_frames", "folds") if key in item},
                "frame_mapping": item.get("output", {}).get("frame_mapping", {}),
                "output_path": relative,
            }
            current["review_subject_sha256"] = digest(canonical({key: current[key] for key in (
                "candidate_id", "source_id", "source_type", "clip_sha256", "candidate_record_sha256",
                "source_sha256", "roi_sha256", "source_relationships", "source_reference", "scope", "folds",
                "generation_batch_id", "generation_schema", "label_rules_sha256",
                "source_record_sha256", "generation_identity_sha256", "split_identity_sha256",
            )}))
            self.candidates[candidate_id] = current
        self.audit_sha256 = None
        self.load_audit()
        # Stat signatures avoid hashing the 34 MB manifest repeatedly during one UI action.
        # ctime also detects an in-place change followed by resetting mtime.
        for path in (self.label_rules_path, self.audit_path):
            self.file_signatures.setdefault(path, None)

    def load_audit(self):
        if not self.audit_path.is_file():
            return
        try:
            raw = self.capture_file(self.audit_path)
            self.audit_sha256 = digest(raw)
            audit = json.loads(raw)
            if not isinstance(audit, dict):
                raise ValueError("核验记录须为对象")
            if audit.get("manifest_sha256") != self.manifest_sha256:
                self.audit_status = "mismatch"
                self.audit_message = "核验记录的清单 SHA256 与当前清单不一致；问题提示未映射，不能据此判断没有待复核问题。"
                return
            entries = audit.get("candidates")
            if not isinstance(entries, list):
                raise ValueError("核验候选列表缺失或格式错误")
            issues_by_id = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("核验候选条目无效")
                candidate_id = entry.get("candidate_id")
                if not isinstance(candidate_id, str) or candidate_id not in self.candidates or candidate_id in issues_by_id:
                    raise ValueError("核验候选 ID 未知或重复")
                candidate = self.candidates[candidate_id]
                if entry.get("source_video_id", candidate["source_id"]) != candidate["source_id"] or entry.get("scope", candidate["scope"]) != candidate["scope"]:
                    raise ValueError("核验候选的来源或划分不一致")
                issues = entry.get("issues")
                if not isinstance(issues, list) or not all(isinstance(issue, str) and issue.strip() for issue in issues):
                    raise ValueError("核验问题须为非空文字列表")
                issues_by_id[candidate_id] = issues
            attention_count = sum(bool(issues) for issues in issues_by_id.values())
            if "candidates_needing_attention" in audit and (type(audit["candidates_needing_attention"]) is not int or audit["candidates_needing_attention"] != attention_count):
                raise ValueError("核验待复核候选计数不一致")
            if "checked_candidates" in audit and audit["checked_candidates"] != len(self.candidates):
                raise ValueError("核验覆盖候选计数不一致")
            if "checked_sources" in audit and audit["checked_sources"] != len(self.sources):
                raise ValueError("核验覆盖来源计数不一致")
            if "issue_counts" in audit:
                counts = {}
                for issues in issues_by_id.values():
                    for issue in issues:
                        counts[issue] = counts.get(issue, 0) + 1
                if audit["issue_counts"] != counts:
                    raise ValueError("核验问题计数不一致")
            self.audit_issues = issues_by_id
            self.audit_current = True
            self.audit_status = "current"
            self.audit_message = f"已匹配当前清单：{attention_count} 个候选有标签组合待复核提示。技术核验不替代人工审核。"
            for candidate in self.candidates.values():
                candidate["audit_issues"] = self.audit_issues.get(candidate["candidate_id"], [])
        except (OSError, ValueError, TypeError, AttributeError) as error:
            self.audit_status = "invalid"
            self.audit_message = f"核验记录不可用（{error}）；问题提示未映射，不能据此判断没有待复核问题。"

    @staticmethod
    def file_signature(path):
        try:
            value = path.stat()
            return tuple(getattr(value, key) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
        except FileNotFoundError:
            return None

    def capture_file(self, path):
        before = self.file_signature(path)
        raw = path.read_bytes()
        if before != self.file_signature(path):
            raise ReviewError(f"读取期间文件发生变化，请重启并重新核对：{path.name}", 409)
        self.file_signatures[path] = before
        return raw

    def unchanged_file(self, path, expected):
        signature = self.file_signature(path)
        if signature == self.file_signatures[path]:
            return True
        actual = digest(path.read_bytes()) if signature is not None else None
        if actual != expected:
            return False
        self.file_signatures[path] = signature
        return True

    def split_for(self, source_id):
        if source_id in self.test_ids:
            return "test", {str(fold): "test" for fold in range(3)}
        if source_id not in self.development_ids:
            raise ReviewError("来源开发或 test 归属不明", 403)
        folds = {}
        for fold, members in self.fold_members.items():
            found = [part for part in ("train", "val") if source_id in members[part]]
            if len(found) != 1:
                raise ReviewError("来源在某一折的训练／验证归属不明或冲突", 403)
            folds[fold] = found[0]
        return "development", folds

    @staticmethod
    def check_split(value, scope, folds):
        split = value.get("split") or {}
        if any(declared is not None and declared != scope for declared in (value.get("scope"), split.get("partition"))):
            raise ReviewError("来源或候选的划分与成员清单不一致", 403)
        if any(declared is not None and declared != folds for declared in (value.get("folds"), split.get("folds"))):
            raise ReviewError("来源或候选的折归属与成员清单不一致", 403)

    def check_related_sources(self, value, expected_scope):
        related = []
        for key in ("related_source_ids", "real_source_ids"):
            if key in value:
                if not isinstance(value[key], list) or not all(isinstance(s, str) for s in value[key]):
                    raise ReviewError("关联来源必须为 ID 列表")
                related.extend(value[key])
        if value.get("parent_source_id"):
            related.append(value["parent_source_id"])
        for source_id in related:
            scope, folds = self.split_for(source_id)
            _, expected_folds = self.split_for(value.get("source_video_id", value.get("video_id", value.get("source_id"))))
            if scope != expected_scope or folds != expected_folds:
                raise ReviewError("关联来源与候选划分或折归属不同；拒绝媒体访问", 403)

    def allowed_source(self, source_id):
        if source_id not in self.sources:
            raise ReviewError("来源不存在或归属不明；拒绝媒体访问", 403)
        source = self.sources[source_id]
        scope, folds = self.split_for(source_id)
        self.check_split(source, scope, folds)
        self.check_related_sources(source, scope)
        return source

    def source_preview_available(self, source_id):
        try:
            source = self.allowed_source(source_id)
        except ReviewError:
            return False
        expected = source.get("source_sha256")
        return source.get("status") != "held" and source.get("source_path") == f"data/videos/{source_id}.mp4" and isinstance(expected, str) and bool(re.fullmatch(r"[0-9a-f]{64}", expected))

    def assert_manifest(self):
        try:
            if not self.unchanged_file(self.manifest_path, self.manifest_sha256):
                raise ReviewError("生成清单在服务启动后已变化；请先记录未保存输入并重启。已保存且身份未变的审核记录会保留", 409)
            if any(not self.unchanged_file(path, sha) for path, sha in self.split_snapshots.items()):
                raise ReviewError("数据划分在服务启动后已变化；请重启并重新核对", 409)
            if not self.unchanged_file(self.label_rules_path, self.label_rules_sha256):
                raise ReviewError("标签规则在服务启动后已变化；请重启并重新核对", 409)
            if not self.unchanged_file(self.audit_path, self.audit_sha256):
                raise ReviewError("核验记录在服务启动后已变化；问题提示需重新匹配，请重启并重新核对", 409)
        except OSError as error:
            raise ReviewError("生成清单或划分文件不可读；请重新核对", 409) from error

    def candidate(self, candidate_id):
        self.assert_manifest()
        if candidate_id not in self.candidates:
            raise ReviewError("未知候选", 404)
        return self.candidates[candidate_id]

    def read_store(self):
        if not self.records_path.exists():
            return []
        try:
            value = json.loads(self.records_path.read_text(encoding="utf-8"))
            if value.get("schema") != STORE_SCHEMA or not isinstance(value.get("revisions"), list):
                raise ValueError("schema mismatch")
            revisions = value["revisions"]
            ids = set()
            for row in revisions:
                recorded = row.get("revision_sha256")
                if not recorded or recorded != digest(canonical({k:v for k,v in row.items() if k != "revision_sha256"})) or row.get("review_id") in ids:
                    raise ValueError("revision integrity mismatch")
                ids.add(row["review_id"])
            return revisions
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ReviewError("审核记录格式或修订完整性异常；拒绝覆盖", 409) from error

    @staticmethod
    def matches(row, candidate):
        return all(row.get(k) == candidate[k] for k in ("candidate_id", "clip_sha256", "review_subject_sha256", "source_id", "source_type"))

    def review(self, candidate_id, revisions=None):
        candidate = self.candidate(candidate_id)
        rows = self.read_store() if revisions is None else revisions
        return self._review(candidate, rows)

    def _review(self, candidate, rows):
        history = [r for r in rows if self.matches(r, candidate)]
        isolated = [r for r in rows if r.get("candidate_id") == candidate["candidate_id"] and not self.matches(r, candidate)]
        return {"latest": history[-1] if history else None, "history": history, "isolated_history": isolated}

    def bootstrap(self):
        self.assert_manifest()
        rows = self.read_store()
        candidates = []
        for candidate_id, candidate in self.candidates.items():
            review = self._review(candidate, rows)
            display = copy.deepcopy(candidate["candidate_reference"])
            mapped = False
            for name in ("断裂模式", "断裂位置"):
                if display.get(name) == '无':
                    display[name] = "无法判断"
                    mapped = True
            candidates.append({**candidate, "candidate_reference_display": display,
                               "prefill_note": "初值为旧规则固定组合值『无』，已按新规则映射为无法判断" if mapped else None, "review_status": review["latest"]["review_status"] if review["latest"] else "unreviewed", "review_id": review["latest"]["review_id"] if review["latest"] else None, "isolated_revision_count": len(review["isolated_history"])})
        return {"manifest_sha256": self.manifest_sha256, "token": self.token, "options": OPTIONS, "candidates": candidates,
                "audit_current": self.audit_current, "audit_status": self.audit_status,
                "audit_message": self.audit_message,
                "audit_issue_candidate_count": sum(bool(issues) for issues in self.audit_issues.values()),
                "pending_sources": [{"source_id": sid, "status": s.get("status"), "reason": s.get("reason"), "source_reference": s.get("source_annotation", {}), "source_preview_available": self.source_preview_available(sid)} for sid, s in self.sources.items() if s.get("status") in ("pending", "held")],
                "project_root": str(self.root), "records_path": str(self.records_path)}

    @contextlib.contextmanager
    def verified_media(self, root, relative, expected_sha256):
        with confined_file(root, relative) as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_size > self.max_media_bytes:
                raise ReviewError("候选媒体超过大小上限", 413)
            sha = hashlib.sha256()
            while block := stream.read(1024 * 1024):
                sha.update(block)
            if sha.hexdigest() != expected_sha256:
                raise ReviewError("片段 SHA256 与生成清单不符；禁止播放及保存审核", 409)
            after = os.fstat(stream.fileno())
            if any(getattr(after, k) != getattr(stat, k) for k in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
                raise ReviewError("校验期间媒体发生变化", 409)
            stream.seek(0)
            yield stream, stat.st_size

    @contextlib.contextmanager
    def media(self, candidate_id):
        candidate = self.candidate(candidate_id)
        self.allowed_source(candidate["source_id"])
        with self.verified_media(self.media_root, candidate["output_path"], candidate["clip_sha256"]) as (stream, size):
            yield stream, size, candidate

    @contextlib.contextmanager
    def source_media(self, source_id):
        self.assert_manifest()
        source = self.allowed_source(source_id)
        if source.get("status") == "held":
            raise ReviewError("暂留来源不开放原视频入口", 403)
        relative = source.get("source_path")
        expected = source.get("source_sha256")
        if relative != f"data/videos/{source_id}.mp4" or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ReviewError("来源缺少可验证的原视频路径或摘要", 403)
        with self.verified_media(self.root, relative, expected) as (stream, size):
            yield stream, size, {"output_path": relative}

    def save(self, payload):
        if not isinstance(payload, dict):
            raise ReviewError("请求须为 JSON 对象")
        candidate = self.candidate(payload.get("candidate_id"))
        for field in ("manifest_sha256", "clip_sha256"):
            if payload.get(field) != candidate[field]:
                raise ReviewError("审核对象身份不符；请重新载入", 409)
        status = payload.get("review_status")
        if status not in STATUSES:
            raise ReviewError("审核状态无效")
        labels = payload.get("labels", {})
        validate_labels(labels, complete=status == "confirmed")
        note, reason = payload.get("note", ""), payload.get("reason", "")
        if not isinstance(note, str) or not isinstance(reason, str) or len(note) > 10000 or len(reason) > 10000:
            raise ReviewError("备注或原因须为不超过 10000 字的文本")
        if status in ("returned", "question") and not reason.strip():
            raise ReviewError("退回或疑问须填写原因")
        with self.media(candidate["candidate_id"]):
            pass
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.mutex, open(str(self.records_path) + ".lock", "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assert_manifest()
            rows = self.read_store()
            previous = self.review(candidate["candidate_id"], rows)["latest"]
            previous_id = previous["review_id"] if previous else None
            if "expected_review_id" not in payload or payload["expected_review_id"] != previous_id:
                raise ReviewError("该候选已有其他修订，请重新载入后再保存", 409)
            prior_confirmed = any(r["review_status"] == "confirmed" for r in rows if self.matches(r, candidate))
            if status != "draft" and prior_confirmed and not reason.strip():
                raise ReviewError("修订已确认结果须填写原因；草稿可先保存")
            row = {k: copy.deepcopy(candidate[k]) for k in ("candidate_id", "source_id", "source_type", "clip_sha256", "manifest_sha256", "candidate_record_sha256", "source_record_sha256", "generation_identity_sha256", "split_identity_sha256", "review_subject_sha256", "label_rules_sha256", "scope", "folds", "generation_batch_id", "generation_rule", "generation_schema", "parent_candidate", "source_sha256", "roi_sha256", "source_relationships")}
            row.update(review_id=str(uuid.uuid4()), previous_review_id=previous_id,
                       created_at=dt.datetime.now(dt.timezone.utc).isoformat(), review_status=status,
                       labels=copy.deepcopy(labels), note=note, reason=reason,
                       decision_origin="human_local_review", history_review_ids=[r["review_id"] for r in rows if self.matches(r, candidate)])
            row["revision_sha256"] = digest(canonical(row))
            rows.append(row)
            raw = canonical({"schema": STORE_SCHEMA, "revisions": rows}) + b"\n"
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.records_path.parent, prefix=".reviews-", delete=False) as file:
                    temporary = file.name
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.records_path)
                temporary = None
                directory = os.open(self.records_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if temporary:
                    os.unlink(temporary)
        return row

    def export(self, *, all_revisions=False):
        self.assert_manifest()
        rows = self.read_store()
        if all_revisions:
            return "".join(json.dumps({**row, "review_store_schema": STORE_SCHEMA}, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        result = []
        for candidate_id, candidate in self.candidates.items():
            review = self._review(candidate, rows)
            latest = review["latest"]
            if latest:
                row = copy.deepcopy(latest)
            else:
                row = {k: copy.deepcopy(v) for k,v in candidate.items() if k not in ("source_reference", "candidate_reference", "output_path")}
                row.update(review_id=None, review_status="unreviewed", labels={}, history_review_ids=[])
            row["isolated_history_review_ids"] = [r["review_id"] for r in review["isolated_history"]]
            row["review_store_schema"] = STORE_SCHEMA
            row["review_store_path"] = str(self.records_path)
            result.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return "\n".join(result) + ("\n" if result else "")


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def valid_host(self):
            host = self.headers.get("Host", "")
            expected = f"127.0.0.1:{self.server.server_port}"
            if host not in (expected, f"localhost:{self.server.server_port}"):
                raise ReviewError("仅接受本机服务地址", 403)
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                raise ReviewError("拒绝跨来源请求", 403)

        def respond(self, status, body, content_type="application/json; charset=utf-8", extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; frame-ancestors 'none'")
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                self.valid_host()
                url = urlsplit(self.path)
                query = parse_qs(url.query)
                candidate_id = query.get("candidate_id", [None])[0]
                if url.path in ("/", "/index.html", "/app.js", "/style.css"):
                    name = "index.html" if url.path in ("/", "/index.html") else url.path[1:]
                    mime = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[name]
                    self.respond(200, (HERE / "static" / name).read_bytes(), mime)
                elif url.path == "/api/bootstrap":
                    self.respond(200, canonical(app.bootstrap()))
                elif url.path == "/api/reviews":
                    self.respond(200, canonical(app.review(candidate_id)))
                elif url.path == "/api/export":
                    self.respond(200, app.export(all_revisions=query.get("all_revisions", [""])[0] == "1"), "application/x-ndjson; charset=utf-8", {"Content-Disposition": 'attachment; filename="%s"' % ("subvideo-reviews-history.jsonl" if query.get("all_revisions", [""])[0] == "1" else "subvideo-reviews.jsonl")})
                elif url.path == "/media":
                    self.send_media(candidate_id)
                elif url.path == "/source-media":
                    self.send_media(query.get("source_id", [None])[0], source=True)
                else:
                    raise ReviewError("未知路径", 404)
            except ReviewError as error:
                self.respond(error.status, canonical({"error": str(error)}))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (OSError, ValueError, TypeError) as error:
                self.respond(500, canonical({"error": "本地文件或记录不可用：" + str(error)}))

        def send_media(self, candidate_id, *, source=False):
            with (app.source_media(candidate_id) if source else app.media(candidate_id)) as (stream, size, candidate):
                start, end, status = 0, size - 1, 200
                value = self.headers.get("Range")
                if value:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
                    if not match or not any(match.groups()):
                        raise ReviewError("不支持该 Range", 416)
                    left, right = match.groups()
                    if left:
                        start = int(left)
                        end = min(int(right), size - 1) if right else size - 1
                    else:
                        start = max(0, size - int(right))
                    if start > end or start >= size:
                        raise ReviewError("Range 超出媒体", 416)
                    status = 206
                self.send_response(status)
                suffix = Path(candidate["output_path"]).suffix.lower()
                self.send_header("Content-Type", {".mp4": "video/mp4", ".webm": "video/webm", ".ogg": "video/ogg"}[suffix])
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

        def do_POST(self):
            try:
                self.valid_host()
                if self.path != "/api/reviews":
                    raise ReviewError("未知路径", 404)
                if self.headers.get("X-Review-Token") != app.token:
                    raise ReviewError("本地会话令牌无效，请重新载入", 403)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 64 * 1024:
                    raise ReviewError("请求大小无效", 413)
                payload = json.loads(self.rfile.read(length))
                row = app.save(payload)
                self.respond(201, canonical(row))
            except ReviewError as error:
                self.respond(error.status, canonical({"error": str(error)}))
            except (ValueError, TypeError):
                self.respond(400, canonical({"error": "JSON 请求格式无效"}))
            except OSError as error:
                self.respond(500, canonical({"error": "保存失败，未确认写入：" + str(error)}))

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True, help="带候选媒体、标注和划分的项目工作区")
    parser.add_argument("--manifest", type=Path, help="默认 data/sub_video/manifest.json")
    parser.add_argument("--records", type=Path, help="默认 data/subvideo-review/reviews.json；独立追加历史")
    parser.add_argument("--max-media-mib", type=int, default=512)
    sub = parser.add_subparsers(dest="command", required=True)
    serving = sub.add_parser("serve")
    serving.add_argument("--port", type=int, default=8765)
    exporting = sub.add_parser("export", help="向 stdout 输出当前候选最新决定 JSONL；不是发布")
    exporting.add_argument("--all-revisions", action="store_true", help="导出记录库内全部不可变修订，含旧身份，用于复现已冻结的 review_id")
    args = parser.parse_args(argv)
    if args.max_media_mib <= 0:
        parser.error("--max-media-mib 必须为正数")
    app = ReviewApp(args.project_root, manifest=args.manifest, records=args.records, max_media_bytes=args.max_media_mib * 1024 * 1024)
    if args.command == "export":
        print(app.export(all_revisions=args.all_revisions), end="")
    else:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(app))
        print(f"人工审核工作台：http://127.0.0.1:{server.server_port}", flush=True)
        print(f"只读候选清单：{app.manifest_path}\n独立审核历史：{app.records_path}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
