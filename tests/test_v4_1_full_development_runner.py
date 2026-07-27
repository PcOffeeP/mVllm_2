from pathlib import Path

from finetune.v4_1_manifest_runtime import atomic_json, monitor, sha256_file


def test_full_training_has_fixed_step_contract(tmp_path: Path):
    marker = tmp_path / "dataset"
    marker.write_text("x")
    manifest = tmp_path / "manifest.json"
    atomic_json(manifest, {"immutable": True, "run_id": "full", "repo_root": str(tmp_path), "state_path": str(tmp_path / "state.json"), "log_root": str(tmp_path), "expected_global_step": 1125, "input_sha256": {"dataset": sha256_file(marker)}}, immutable=True)
    assert monitor(manifest)["expected_global_step"] == 1125
