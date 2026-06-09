from __future__ import annotations

import os
from pathlib import Path
import tempfile


def _home_dir() -> Path:
    home = os.environ.get("HOME")
    if home:
        return Path(home)
    return Path.home()


def ensure_mpl_config_dir() -> Path:
    """Point Matplotlib at an app-owned writable cache directory."""

    existing = os.environ.get("MPLCONFIGDIR")
    if existing:
        return Path(existing)

    home = os.environ.get("HOME")
    cache_dir = _home_dir() / ".cache" / "afm_gui" / "matplotlib"
    try:
        if os.name == "nt" and home and home.startswith("/") and not home.startswith("//"):
            raise OSError("HOME is not a Windows path")
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache_dir = Path(tempfile.gettempdir()) / "afm_gui" / "matplotlib"
        cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_dir)
    return cache_dir


__all__ = ["ensure_mpl_config_dir"]
