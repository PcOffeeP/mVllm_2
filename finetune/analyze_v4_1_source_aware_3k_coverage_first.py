#!/usr/bin/env python3
"""Gate both seeds of the Stage B coverage-first revision."""

from finetune.v4_1_source_aware_3k_coverage_first import configure_runner

configure_runner()

from finetune.analyze_v4_1_source_aware_3k import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
