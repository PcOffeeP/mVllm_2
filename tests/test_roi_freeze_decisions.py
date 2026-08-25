import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import roi_freeze_decisions as cli


def test_parser_defaults():
    args = cli.build_parser().parse_args([])
    assert args.decisions.name == "roi_decisions.json"
    assert args.check_only is False


def test_parser_accepts_check_only():
    assert cli.build_parser().parse_args(["--check-only"]).check_only is True
