from finetune.archive.build_v4_1_full_development import build_full_development


def test_full_development_covers_every_candidate_once_before_repeats():
    candidates = [{"candidate_id": f"c{i}", "source_video": f"s{i}", "labels": {"clip_state": str(i % 2)}} for i in range(10)]
    result = build_full_development(candidates, rows=30)
    assert result["manifest"]["unique_coverage_rate"] == 1.0
    assert result["manifest"]["unique_coverage_count"] == 10
    assert result["manifest"]["repeat_count"] == 20
