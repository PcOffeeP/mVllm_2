import json
from pathlib import Path

from finetune.archive.prepare_v4_1_full_development_deployment import main


def test_component_has_only_allowed_capability(tmp_path: Path):
    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "config.json").write_text("{}")
    adapter = tmp_path / "adapter.json"
    adapter.write_text("{}")
    output = tmp_path / "component.json"
    assert main(["--merged-model", str(merged), "--output", str(output), "--base-model-identity", "minicpm-v-4.5", "--adapter-manifest", str(adapter)]) == 0
    value = json.loads(output.read_text())
    assert value["capability"] == "full_development_model"
    assert "production_passed" not in value
