#!/usr/bin/env python3
"""Run the Stage B coverage-first train, merge, and strict evaluation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.v4_1_source_aware_3k_coverage_first import configure_runner


if __name__ == "__main__":
    raise SystemExit(configure_runner().main())
