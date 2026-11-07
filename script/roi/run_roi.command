#!/bin/zsh
cd "$(dirname "$0")/../.." || exit 1
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python script/roi/roi.py
fi
exec python3 script/roi/roi.py
