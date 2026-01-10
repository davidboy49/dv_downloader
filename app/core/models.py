from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Profile:
    name: str
    output_dir: Optional[str] = None
    cookies_path: Optional[str] = None
    cookies_browser: Optional[str] = None
    max_concurrent: int = 2


@dataclass(frozen=True)
class VideoMetadata:
    url: str
    title: str
    source: str
    duration: Optional[int]
    view_count: Optional[int]
    expected_size: Optional[int]


@dataclass
class DownloadItem:
    item_id: str
    url: str
    title: str
    duration: Optional[int]
    expected_size: Optional[int]
    output_path: str
    profile_name: str
    status: str
    downloaded_text: Optional[str] = None
    total_text: Optional[str] = None
    speed: Optional[str] = None
    eta: Optional[str] = None
    progress: Optional[float] = None
