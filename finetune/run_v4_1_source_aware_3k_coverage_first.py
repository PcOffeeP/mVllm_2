#!/usr/bin/env python3
"""Run the Stage B coverage-first train, merge, and strict evaluation."""

from finetune.v4_1_source_aware_3k_coverage_first import configure_runner


if __name__ == "__main__":
    raise SystemExit(configure_runner().main())
