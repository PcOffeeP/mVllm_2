#!/usr/bin/env python3
"""Run the single pre-registered coverage-first fallback seed3413."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.v4_1_coverage_first_fallback_seed3413 import configure_runner


if __name__ == "__main__":
    raise SystemExit(configure_runner().main())
