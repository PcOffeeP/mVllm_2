import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts" / "archive"
sys.path.insert(0, str(SCRIPTS_DIR))

import build_v3_review_reference as cli


def test_parser_defaults_to_dry_run_false():
    args = cli.build_parser().parse_args([])
    assert args.dry_run is False
    assert args.train_review_decisions.name == "subvideo_train_review_decisions_final.json"
    assert args.test_review_decisions.name == "subvideo_test_review_decisions.json"


def test_parser_accepts_dry_run():
    assert cli.build_parser().parse_args(["--dry-run"]).dry_run is True
