from finetune.v4_1_coverage_first_fallback_seed3413 import RUN_ID, SAMPLING_ID


def test_fallback_identity_is_single_and_pre_registered():
    assert RUN_ID.endswith("fallback_seed3413")
    assert SAMPLING_ID.endswith("fallback-seed3413")
