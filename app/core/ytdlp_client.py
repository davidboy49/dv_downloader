from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from app.core.models import Profile, VideoMetadata


class YtdlpClient:
    """Thin wrapper around yt-dlp for metadata and downloads."""
    def __init__(self) -> None:
        self._base_opts = {
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
            "noplaylist": False,
        }

    def extract_metadata(
        self,
        url: str,
        profile: Profile,
        logger: Optional[Callable[[str], None]] = None,
    ) -> List[VideoMetadata]:
        options = dict(self._base_opts)
        if profile.cookies_path:
            options["cookiefile"] = profile.cookies_path
        if profile.cookies_browser:
            options["cookiesfrombrowser"] = profile.cookies_browser

        if logger:
            logger(f"yt-dlp metadata extract: {url}")

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)

        return self._flatten_info(info)

    def fetch_profile_videos(
        self,
        platform: str,
        profile_url: str,
        profile: Profile,
        logger: Optional[Callable[[str], None]] = None,
    ) -> List[VideoMetadata]:
        options = dict(self._base_opts)
        options["extract_flat"] = "in_playlist"
        options["skip_download"] = True
        if profile.cookies_path:
            options["cookiefile"] = profile.cookies_path
        if profile.cookies_browser:
            options["cookiesfrombrowser"] = profile.cookies_browser

        if logger:
            logger(f"yt-dlp profile fetch ({platform}): {profile_url}")

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(profile_url, download=False)

        return self._flatten_info(info)

    def build_download_command(
        self,
        url: str,
        output_dir: str,
        profile: Profile,
        fragment_threads: int,
        use_aria2: bool,
    ) -> List[str]:
        output_template = str(Path(output_dir) / "%(title).200s.%(ext)s")
        args = [
            "yt-dlp",
            "--newline",
            "--no-warnings",
            "--progress",
            "--progress-template",
            "download:progress:%(progress.downloaded_bytes)s/%(progress.total_bytes)s/%(progress.speed)s/%(progress.eta)s/%(progress._percent_str)s",
            "--windows-filenames",
            "--trim-filenames",
            "200",
            "-N",
            str(fragment_threads),
            "-o",
            output_template,
            url,
        ]
        if profile.cookies_path:
            args.extend(["--cookies", profile.cookies_path])
        if profile.cookies_browser:
            args.extend(["--cookies-from-browser", profile.cookies_browser])
        if use_aria2:
            args.extend(
                [
                    "--downloader",
                    "aria2c",
                    "--downloader-args",
                    "aria2c:-x 8 -k 1M",
                ]
            )
        return args

    def _flatten_info(self, info: dict) -> List[VideoMetadata]:
        if info.get("entries"):
            items = []
            for entry in info["entries"]:
                if entry:
                    items.extend(self._flatten_info(entry))
            return items
        return [self._to_metadata(info)]

    def _to_metadata(self, info: dict) -> VideoMetadata:
        url = self._resolve_url(info)
        source = self._source_from_url(url) or info.get("extractor", "unknown")
        return VideoMetadata(
            url=url,
            title=info.get("title") or "Untitled",
            source=source,
            duration=self._to_int(info.get("duration")),
            view_count=self._to_int(info.get("view_count")),
            expected_size=self._to_int(info.get("filesize") or info.get("filesize_approx")),
        )

    def _resolve_url(self, info: dict) -> str:
        url = info.get("webpage_url") or info.get("original_url") or info.get("url") or ""
        if url and not url.startswith(("http://", "https://")):
            key = info.get("ie_key") or info.get("extractor_key") or info.get("extractor")
            if key:
                return f"{key}:{url}"
        return url

    def _source_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        if "://" not in url and ":" in url:
            return url.split(":", 1)[0].lower()
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def _to_int(self, value: object) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
