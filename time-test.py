"""Convenience entry point for the FM-AFM timing diagnostic.

Run this file from VS Code or from the project root.  The implementation lives
in ``tools/fm_scan_timing.py`` so it can also be run directly from PowerShell.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "tools" / "fm_scan_timing.py"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")
