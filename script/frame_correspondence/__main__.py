"""Module entrypoint for `python -m script.frame_correspondence`."""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
