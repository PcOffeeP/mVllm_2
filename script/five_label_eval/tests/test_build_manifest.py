"""Synthetic current-decision exports; no media or model access."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from script.five_label_eval.build_manifest import build_draft, main
from script.five_label_eval.score import IDENTITY, InputError, score


def export_rows():
    rows = []
    for i, status in enumerate(("confirmed", "unreviewed", "draft", "returned", "question")):
        rows.append({"manifest_sha256": "a" * 64, "candidate_id": f"chosen-{i}", "clip_sha256": f"{i+1:064x}",
                     "source_id": f"source-{i}", "source_type": "real" if i < 4 else "virtual",
                     "review_id": None if status == "unreviewed" else f"revision-{i}",
                     "review_status": status, "labels": {} if status == "unreviewed" else {"断裂状态": "已断裂"}})
    return rows


class BuildManifestTests(unittest.TestCase):
    def test_explicit_selection_preserves_identity_order_revision_and_all_states(self):
        rows = export_rows()
        original = copy.deepcopy(rows)
        ids = ["chosen-4", "chosen-3", "chosen-2", "chosen-1", "chosen-0"]
        draft = build_draft(rows, ids, "user-selected-version")
        self.assertEqual(rows, original)
        self.assertEqual(draft["manifest_version"], "user-selected-version")
        self.assertEqual(draft["draft_status"], "identity_snapshot_not_frozen")
        self.assertEqual([s["candidate_id"] for s in draft["samples"]], ids)
        self.assertEqual(len(draft["not_confirmed"]), 4)
        for sample, row in zip(draft["samples"], reversed(rows)):
            self.assertEqual({k: sample[k] for k in (*IDENTITY, "review_id", "review_status")},
                             {k: row[k] for k in (*IDENTITY, "review_id", "review_status")})
            self.assertNotIn("labels", sample)
        predictions = [{"candidate_id": row["candidate_id"], "clip_sha256": row["clip_sha256"], "run_id": "run",
                        "model_id": "synthetic-model", "prompt_id": "synthetic-prompt", "input_id": f"input-{i}",
                        "request_id": f"req-{i}", "status": "success", "raw_output": '{"断裂状态":"已断裂"}'}
                       for i, row in enumerate(rows)]
        result = score(draft, rows, predictions)
        state = result["groups"]["real"]["full_clip"]["fields"]["断裂状态"]
        self.assertEqual(state["accuracy"]["numerator"], 1)
        self.assertEqual(state["accuracy"]["denominator"], 1)
        self.assertEqual(state["truth_counts"], {"unlabeled": 3, "valid": 1})
        self.assertEqual([s["candidate_id"] for s in build_draft(rows, ["chosen-2"], "only-one")["samples"]], ["chosen-2"])

    def test_duplicate_missing_invalid_identity_and_history_fail(self):
        invalid_selections = ([], ["chosen-0", "chosen-0"], ["missing"], [None], [True], "chosen-0")
        for ids in invalid_selections:
            with self.subTest(ids=ids), self.assertRaises(InputError):
                build_draft(export_rows(), ids, "v")
        mutations = (
            lambda rows: rows.append(copy.deepcopy(rows[0])),
            lambda rows: rows.append({**rows[0], "review_id": "older-revision"}),
            lambda rows: rows.append({**rows[0], "clip_sha256": "b" * 64}),
            lambda rows: rows[0].pop("review_id"),
            lambda rows: rows[0].update(clip_sha256="invalid"),
            lambda rows: rows[0].update(source_type="unknown"),
            lambda rows: rows[0].update(review_id=None),
            lambda rows: rows[0].update(review_status="invalid"),
            lambda rows: rows[1].update(labels={"断裂状态": "已断裂"}),
        )
        for mutate in mutations:
            rows = export_rows()
            mutate(rows)
            with self.subTest(mutation=mutate), self.assertRaises(InputError):
                build_draft(rows, ["chosen-0", "chosen-1"], "v")
        for version in (None, "", "  "):
            with self.assertRaises(InputError):
                build_draft(export_rows(), ["chosen-0"], version)

    def test_cli_new_file_source_hashes_warnings_no_overwrite_and_repeated_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "current.jsonl"
            ids = root / "ids.json"
            output = root / "draft.json"
            export.write_text("".join(json.dumps(row) + "\n" for row in export_rows()), encoding="utf-8")
            ids.write_text('["chosen-1", "chosen-0"]', encoding="utf-8")
            before = export.read_bytes(), ids.read_bytes()
            args = ["--reviews", str(export), "--candidate-ids", str(ids), "--manifest-version", "cli/1", "--output", str(output)]
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(args), 0)
            self.assertIn("NOT CONFIRMED: chosen-1 / unreviewed", stdout.getvalue())
            result = json.loads(output.read_text())
            self.assertEqual(result["input_files"]["reviews"]["sha256"], hashlib.sha256(before[0]).hexdigest())
            self.assertEqual(result["input_files"]["candidate_ids"]["sha256"], hashlib.sha256(before[1]).hexdigest())
            saved = output.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual((export.read_bytes(), ids.read_bytes()), before)
            export.write_text('{"candidate_id":"a","candidate_id":"b"}\n', encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(args[:-1] + [str(root / "invalid.json")]), 2)
            self.assertFalse((root / "invalid.json").exists())


if __name__ == "__main__":
    unittest.main()
