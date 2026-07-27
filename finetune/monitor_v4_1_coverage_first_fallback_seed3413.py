#!/usr/bin/env python3
"""Monitor the single pre-registered coverage-first fallback seed3413."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.v4_1_coverage_first_fallback_seed3413 import configure_runner

configure_runner()

from finetune.monitor_v4_1_source_aware_3k import main


if __name__ == "__main__":
    raise SystemExit(main())
