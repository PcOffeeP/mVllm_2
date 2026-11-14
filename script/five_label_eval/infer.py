"""Plan one request per input record with a deterministic fake backend.

It never contacts a model; a fixed category order makes each answer shape appear once.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

from . import paths
from .frames import RECORD_SCHEMA, read_records
from .prompt_id import load_prompt
from .score import InputError, decode_file, read_json, require_text

CATEGORY_ORDER = ("complete", "missing_fields", "invalid_literal", "conflict", "fenced",
                  "request_failed", "timeout")
NON_ANSWERS = ("request_failed", "timeout")
LEGAL = {"断裂状态": "发生断裂", "断裂模式": "韧性断裂", "断裂位置": "标距内",
         "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
         "断裂现象": {"伸长": "否", "颈缩": "否", "开裂": "否", "界面分离": "否", "断后脱夹": "否"}}


def fake_raw_output(category: str) -> str | None:
    """Return the raw model text for one category; ``None`` means no answer arrived."""
    if category in NON_ANSWERS:
        return None
    labels = copy.deepcopy(LEGAL)
    if category == "missing_fields":
        del labels["断裂位置"], labels["断裂现象"]["开裂"]
    elif category == "invalid_literal":
        # 词表外取值：「无法判断」已是 score.SINGLES 的合法单值，这里要造非法字面量。
        labels["断裂状态"] = "部分断裂"
    elif category == "conflict":
        labels["断裂状态"], labels["断裂模式"], labels["断裂位置"] = "未断裂", "韧性断裂", "无"
    elif category not in ("complete", "fenced"):
        raise ValueError(f"unknown fake category: {category}")
    text = json.dumps(labels, ensure_ascii=False)
    return f"```json\n{text}\n```" if category == "fenced" else text


def plan_predictions(records, manifest, run_id, prompt_id, model_id="fake") -> list[dict]:
    require_text({"run_id": run_id}, "run_id", "run")
    require_text({"prompt_id": prompt_id}, "prompt_id", "run")
    rows = manifest.get("samples") if isinstance(manifest, dict) else None
    if not isinstance(rows, list):
        raise InputError("manifest must contain samples array")
    samples = {row["candidate_id"]: row for row in rows if isinstance(row, dict) and "candidate_id" in row}
    predictions = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise InputError("input record must be object")
        for key in ("candidate_id", "clip_sha256", "input_id", "manifest_sha256", "record_schema"):
            require_text(record, key, "input record")
        cid = record["candidate_id"]
        sample = samples.get(cid)
        if sample is None:
            raise InputError(f"input record candidate absent from manifest: {cid}")
        for key, want in (("clip_sha256", sample.get("clip_sha256")), ("record_schema", RECORD_SCHEMA),
                          ("manifest_sha256", sample.get("manifest_sha256"))):
            if record[key] != want:
                raise InputError(f"{cid}: record {key} {record[key]!r} != expected {want!r}")
        category = CATEGORY_ORDER[index % len(CATEGORY_ORDER)]
        predictions.append({"candidate_id": cid, "clip_sha256": record["clip_sha256"], "run_id": run_id,
                            "model_id": model_id, "prompt_id": prompt_id, "input_id": record["input_id"],
                            "request_id": f"{run_id}/{cid}", "raw_output": fake_raw_output(category),
                            "status": category if category in NON_ANSWERS else "success",
                            "input_review_id": None, "fake_category": category})
    return predictions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Scoring manifest to bind requests to")
    parser.add_argument("--candidate-ids", help="JSON array of candidate IDs selecting record order")
    parser.add_argument("--profile", help="Path profile; only needed to default --input-config")
    parser.add_argument("--model-id", default="fake")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prompt-file", required=True, help="Prompt text; only its ID is used here")
    parser.add_argument("--input-config", help="frames records JSONL; defaults to profile output_dir/records.jsonl")
    parser.add_argument("--output", required=True, help="New predictions JSONL; never overwrites")
    parser.add_argument("--backend", default="fake", choices=("fake", "transformers"))
    args = parser.parse_args(argv)
    try:
        if args.backend == "transformers":
            raise NotImplementedError("transformers backend is not implemented in this slice")
        if args.model_id != "fake":
            raise InputError("fake backend only accepts --model-id fake")
        profiles = paths.load_profile(args.profile) if args.profile else None
        if not args.input_config and profiles is None:
            raise InputError("provide --input-config or --profile")
        input_config = Path(args.input_config) if args.input_config else profiles["output_dir"] / "records.jsonl"
        prompt_identity = load_prompt(args.prompt_file)[1]
        records = read_records(input_config)
        if args.candidate_ids:
            selected = decode_file(Path(args.candidate_ids).read_text(encoding="utf-8"), args.candidate_ids)
            if not isinstance(selected, list) or not selected:
                raise InputError("candidate IDs must be a nonempty JSON array")
            by_id = {record.get("candidate_id"): record for record in records}
            duplicated = sorted(cid for cid in set(selected) if selected.count(cid) > 1)
            missing = [cid for cid in selected if cid not in by_id]
            if duplicated or missing:
                raise InputError(f"duplicate candidate_id in candidate_ids: {duplicated}" if duplicated
                                 else f"candidate_id not found in input records: {missing}")
            records = [by_id[cid] for cid in selected]
        predictions = plan_predictions(records, read_json(args.manifest), args.run_id,
                                       prompt_identity, model_id=args.model_id)
        with Path(args.output).open("x", encoding="utf-8") as stream:
            for row in predictions:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {len(predictions)} predictions to {args.output}; backend={args.backend}; "
              f"prompt_id={prompt_identity}")
        return 0
    except (InputError, OSError, UnicodeError, NotImplementedError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
