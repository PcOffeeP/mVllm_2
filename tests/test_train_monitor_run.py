import json
from pathlib import Path

from finetune.train_monitor_run import latest_trainer_state


def _write_state(path: Path, step: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"global_step": step}), encoding="utf-8")


def test_latest_trainer_state_prefers_final_state(tmp_path: Path):
    _write_state(tmp_path / "checkpoint-100" / "trainer_state.json", 100)
    final_path = tmp_path / "trainer_state.json"
    _write_state(final_path, 120)

    state, source = latest_trainer_state(tmp_path)

    assert state["global_step"] == 120
    assert source == final_path


def test_latest_trainer_state_uses_newest_valid_checkpoint(tmp_path: Path):
    _write_state(tmp_path / "checkpoint-50" / "trainer_state.json", 50)
    _write_state(tmp_path / "checkpoint-100" / "trainer_state.json", 100)
    corrupt = tmp_path / "checkpoint-150" / "trainer_state.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{", encoding="utf-8")

    state, source = latest_trainer_state(tmp_path)

    assert state["global_step"] == 100
    assert source == tmp_path / "checkpoint-100" / "trainer_state.json"


def test_latest_trainer_state_handles_missing_run_dir(tmp_path: Path):
    state, source = latest_trainer_state(tmp_path / "missing")

    assert state == {}
    assert source is None
