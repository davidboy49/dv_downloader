from __future__ import annotations

import threading
from typing import List

from PySide6.QtCore import QObject, QRunnable, Signal

from app.core.logger import AppLogger
from app.core.models import Profile, VideoMetadata
from app.core.ytdlp_client import YtdlpClient


class ProfileFetchSignals(QObject):
    fetched = Signal(list)
    error = Signal(str)
    stopped = Signal()


class ProfileFetchTask(QRunnable):
    """Background task to fetch profile videos using yt-dlp."""
    def __init__(
        self,
        platform: str,
        profile_url: str,
        profile: Profile,
        logger: AppLogger,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._platform = platform
        self._profile_url = profile_url
        self._profile = profile
        self._logger = logger
        self._cancel_event = cancel_event
        self.signals = ProfileFetchSignals()

    def run(self) -> None:
        client = YtdlpClient()
        try:
            if self._cancel_event.is_set():
                self.signals.stopped.emit()
                return
            items = client.fetch_profile_videos(
                self._platform, self._profile_url, self._profile, logger=self._logger.info
            )
            if self._cancel_event.is_set():
                self.signals.stopped.emit()
                return
            self.signals.fetched.emit(items)
        except Exception as exc:  # noqa: BLE001 - surface message in UI
            self._logger.error(f"Profile fetch failed: {exc}")
            self.signals.error.emit(str(exc))
