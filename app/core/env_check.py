from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

import yt_dlp


@dataclass(frozen=True)
class EnvStatus:
    """Simple tool availability report."""
    name: str
    version: str
    ok: bool
    hint: str = ""


def _run_version_command(command: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def _check_tool(name: str, version_args: list[str], hint: str) -> EnvStatus:
    if not shutil.which(name):
        return EnvStatus(name=name, version="missing", ok=False, hint=hint)
    version_line = _run_version_command([name, *version_args])
    return EnvStatus(
        name=name,
        version=version_line or "unknown",
        ok=bool(version_line),
        hint=hint if not version_line else "",
    )


def check_environment() -> list[EnvStatus]:
    statuses = [
        EnvStatus(name="python", version=sys.version.split()[0], ok=True),
        EnvStatus(name="yt-dlp", version=yt_dlp.version.__version__, ok=True),
        _check_tool(
            name="ffmpeg",
            version_args=["-version"],
            hint="Install FFmpeg and add it to PATH.",
        ),
        _check_tool(
            name="ffprobe",
            version_args=["-version"],
            hint="Install FFmpeg (ffprobe is included) and add it to PATH.",
        ),
        _check_tool(
            name="aria2c",
            version_args=["-v"],
            hint="Install aria2 and add it to PATH for faster downloads.",
        ),
    ]
    return statuses
