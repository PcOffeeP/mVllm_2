from pathlib import Path

from finetune.v4_1_manifest_runtime import atomic_json, monitor, sha256_file


def test_monitor_warmup_schedule(tmp_path: Path):
    frozen = tmp_path / "frozen"
    frozen.write_text("x")
    manifest = tmp_path / "run_manifest.json"
    atomic_json(manifest, {"immutable": True, "run_id": "r", "repo_root": str(tmp_path), "state_path": str(tmp_path / "state.json"), "log_root": str(tmp_path), "expected_global_step": 1125, "evaluation_expected_count": 425, "input_sha256": {"frozen": sha256_file(frozen)}}, immutable=True)
    atomic_json(tmp_path / "state.json", {"phase": "train", "status": "running", "global_step": 49})
    result = monitor(manifest)
    assert result["eta_reliable"] is False
    assert result["suggested_check_after_seconds"] == 900
