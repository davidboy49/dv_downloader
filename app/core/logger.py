from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal


class AppLogger(QObject):
    """Emit logs to UI and write rolling log files."""
    message_logged = Signal(str, str)

    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self._logger = logging.getLogger("dv_downloader")
        self._logger.setLevel(logging.INFO)
        self._configure_handlers(base_dir)

    def _configure_handlers(self, base_dir: Path) -> None:
        if self._logger.handlers:
            return
        log_dir = base_dir / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "app.log"
        handler = RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    def info(self, message: str) -> None:
        self._emit("INFO", message)

    def warn(self, message: str) -> None:
        self._emit("WARN", message)

    def error(self, message: str) -> None:
        self._emit("ERROR", message)

    def _emit(self, level: str, message: str) -> None:
        log_func = self._logger.info
        if level == "WARN":
            log_func = self._logger.warning
        elif level == "ERROR":
            log_func = self._logger.error
        log_func(message)
        self.message_logged.emit(level, message)

    def get_log_path(self, base_dir: Path) -> Path:
        return base_dir / "data" / "logs" / "app.log"

    def log_exception(self, message: str, exc: Optional[BaseException]) -> None:
        if exc:
            self._emit("ERROR", f"{message}: {exc}")
        else:
            self._emit("ERROR", message)
