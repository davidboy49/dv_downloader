from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_appdata) / "dv_downloader"
    return Path(__file__).resolve().parents[2]
