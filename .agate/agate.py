#!/usr/bin/env python3
"""Agate's single command. Run it from the project root: `python3 .agate/agate.py <command>`.

This file is only a launcher: everything lives in `.agate/core/` (base-owned, replaced by `agate.py update`).
`python3 .agate/agate.py --help` lists the commands.
"""
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent / "core"
sys.path.insert(0, str(CORE / "lib"))
sys.path.insert(0, str(CORE))

from cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
