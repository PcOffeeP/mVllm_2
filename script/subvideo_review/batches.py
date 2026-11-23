"""折归属指来源在 fold_k 的 train/val，而非候选的全局角色。
例如 video_0001_fracture_01 在折 0 为 val，在折 1、2 为 train。
"""
import json
from pathlib import Path

from .errors import ReviewError

SCHEMA = "subvideo-review-batches/v1"


def load_definitions(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as error:
        raise ReviewError(f"batches JSON 无效：{error}") from error
    if not isinstance(config, dict) or config.get("schema") != SCHEMA:
        raise ReviewError("批次 schema 不符")
    rows = config.get("batches")
    if not isinstance(rows, list):
        raise ReviewError("batches 必须为列表")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ReviewError("batches 条目必须是对象")
        bid = row.get("batch_id")
        if not isinstance(bid, str) or not bid or bid in seen:
            raise ReviewError(f"batch_id 无效或重复：{bid}")
        seen.add(bid)
        for key, kind in (("name", str), ("description", str), ("provenance", dict)):
            if not isinstance(row.get(key), kind):
                raise ReviewError(f"{bid} {key} 无效")
        if row.get("status") not in ("ready", "undefined"):
            raise ReviewError(f"{bid} status 无效：{row.get('status')}")
        sel = row.get("selection")
        if not isinstance(sel, dict):
            raise ReviewError(f"{bid} 缺少有效 selection")
        if sel.get("type") == "explicit_ids":
            ids = sel.get("ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ReviewError(f"{bid} explicit_ids 必须为字符串列表")
            if len(ids) != len(set(ids)):
                raise ReviewError(f"{bid} explicit_ids 重复")
        elif sel.get("type") == "rule":
            if sel.get("scope") not in ("development", "test"):
                raise ReviewError(f"{bid} selection.scope 无效")
            if sel.get("fold_match", "any") != "any":
                raise ReviewError(f"{bid} fold_match 不支持：{sel['fold_match']}")
            roles = sel.get("fold_roles", [])
            if not isinstance(roles, list) or any(r not in ("train", "val", "test") for r in roles):
                raise ReviewError(f"{bid} fold_roles 无效：{roles}")
        else:
            raise ReviewError(f"{bid} selection.type 未知：{sel.get('type')}")
        if row["status"] == "undefined" and (sel["type"] != "rule" or len(sel.get("fold_roles", [])) != 1):
            raise ReviewError(f"{bid} undefined 需要 rule 与单值 fold_roles")
    return rows


def select(batch, candidates):
    sel = batch["selection"]
    missing = []
    if sel["type"] == "explicit_ids":
        wanted = set(sel["ids"])
        ids = [cid for cid in candidates if cid in wanted]
        missing = [cid for cid in sel["ids"] if cid not in candidates]
    else:
        scoped = [(cid, c) for cid, c in candidates.items() if c["scope"] == sel["scope"]]
        roles = sel.get("fold_roles")
        if batch["status"] == "undefined":
            counts = {k: sum(c["folds"].get(k) in roles for _, c in scoped) for k in ("0", "1", "2")}
            return {"candidate_ids": [], "candidate_count": None, "missing_ids": [], "fold_pool_counts": counts}
        ids = [cid for cid, c in scoped if roles is None or any(r in roles for r in c["folds"].values())]
    return {"candidate_ids": ids, "candidate_count": len(ids), "missing_ids": missing, "fold_pool_counts": None}
