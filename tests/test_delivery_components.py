import copy
from pathlib import Path

import scripts.validate_delivery_components as validator


def test_current_delivery_components_are_internally_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    report = validator.validate_components(root)
    assert report["passed"] is True


def test_model_component_cannot_claim_final_or_production(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[1]
    original_load = validator._load

    def load_with_false_claim(path: Path):
        value = original_load(path)
        if path.name == "model_component.json":
            value = copy.deepcopy(value)
            value["production_approved"] = True
        return value

    monkeypatch.setattr(validator, "_load", load_with_false_claim)
    report = validator.validate_components(root)
    assert "model capability boundary is invalid" in report["errors"]


def test_performance_thresholds_cannot_block_intermediate_delivery(
    monkeypatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    original_load = validator._load

    def load_with_blocking_performance(path: Path):
        value = original_load(path)
        if path.name == "model_component.json":
            value = copy.deepcopy(value)
            value["intermediate_delivery_policy"][
                "performance_thresholds_block_delivery"
            ] = True
        return value

    monkeypatch.setattr(validator, "_load", load_with_blocking_performance)
    report = validator.validate_components(root)
    assert "intermediate delivery performance policy is invalid" in report["errors"]


def test_model_component_must_bind_current_registry(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[1]
    original_load = validator._load

    def load_with_wrong_registry_binding(path: Path):
        value = original_load(path)
        if path.name == "model_component.json":
            value = copy.deepcopy(value)
            value["model_name"] = "v4.1-wrong-fold0-r1"
        return value

    monkeypatch.setattr(validator, "_load", load_with_wrong_registry_binding)
    report = validator.validate_components(root)
    assert "model component/registry binding mismatch" in report["errors"]
