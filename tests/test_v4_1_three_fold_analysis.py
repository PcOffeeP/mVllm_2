from finetune.analyze_v4_1_three_fold import analyze


def test_absolute_metrics_do_not_gate_integrity():
    values = [{"fold": i, "release_id": "r", "contract_version": "c", "prompt_sha256": "p", "recipe_sha256": "x", "validation_sources": [f"s{i}"], "runtime_failures": 0, "evaluation_count": 1, "evaluation_expected_count": 1, "artifact_integrity": True, "metrics": {"fracture_recall": i / 10}} for i in range(3)]
    integrity, aggregate = analyze(values)
    assert integrity["overall"]
    assert aggregate["metrics"]["fracture_recall"]["mode"] == "record_only"
