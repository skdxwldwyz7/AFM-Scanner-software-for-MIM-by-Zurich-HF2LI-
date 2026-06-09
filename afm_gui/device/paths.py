from __future__ import annotations

from pathlib import Path
import sys


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def add_first_existing_path(*relative_paths: str) -> Path | None:
    root = workspace_root()
    for relative_path in relative_paths:
        path = root / relative_path
        if path.exists():
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
            return path
    return None


__all__ = ["add_first_existing_path", "workspace_root"]
