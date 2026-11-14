"""Write tiny invented JSON fixtures; does not open, generate or process media."""
import argparse
import json
from pathlib import Path


def write_example(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    labels = {"断裂状态": "发生断裂", "断裂模式": "韧性断裂", "断裂位置": "标距内",
              "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
              "断裂现象": {"伸长": "是", "颈缩": "否", "开裂": "否", "界面分离": "否", "断后脱夹": "否"}}
    samples = [{"manifest_sha256": "a" * 64, "candidate_id": f"invented-{i}", "clip_sha256": f"{i+1:064x}",
                "source_id": f"invented-source-{i}", "source_type": "virtual" if i == 4 else "real", "review_id": f"review-{i}"}
               for i in range(5)]
    reviews = [{**s, "review_status": "confirmed", "labels": labels} for s in samples]
    predictions = [{"candidate_id": s["candidate_id"], "clip_sha256": s["clip_sha256"], "run_id": "synthetic-run",
                    "model_id": "invented-no-model", "prompt_id": "invented-no-prompt", "input_id": f"invented-input-{i}",
                    "request_id": f"invented-request-{i}", "status": "request_failed" if i == 1 else "success",
                    "raw_output": None if i == 1 else json.dumps(labels, ensure_ascii=False)}
                   for i, s in enumerate(samples) if i != 3]
    predictions[2]["input_review_id"] = "input-review-2"
    actual = {k: predictions[2][k] for k in ("candidate_id", "clip_sha256", "run_id", "model_id", "prompt_id", "input_id", "request_id", "input_review_id")}
    actual.update(review_status="confirmed", fields={"断裂状态": {"evidence": "insufficient", "label": "无法判断"},
                                                    "断裂现象": {"伸长": {"evidence": "insufficient", "label": "无法判断"}}})
    (root / "manifest.json").write_text(json.dumps({"manifest_version": "invented/1", "samples": samples}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, rows in (("reviews", reviews), ("predictions", predictions), ("input_reviews", [actual])):
        (root / f"{name}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New directory")
    write_example(parser.parse_args().output)
