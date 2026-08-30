#!/usr/bin/env python3
"""GPL-3.0-only. Fixed synthetic demo; production delivery entry is unchanged."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timeline_demo.demo import main

if __name__ == "__main__":
    raise SystemExit(main())
