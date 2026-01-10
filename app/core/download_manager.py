from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, QThreadPool

from app.core.logger import AppLogger
from app.core.models import DownloadItem, Profile, VideoMetadata
from app.core.ytdlp_client import YtdlpClient


class DownloadTaskSignals(QObject):
    progress = Signal(str, dict)
    completed = Signal(str)
    failed = Signal(str, str)
    canceled = Signal(str)
    output_path = Signal(str, str)


class DownloadTask(QRunnable):
    """Run a single yt-dlp download in a background task."""
    def __init__(
        self,
        item: DownloadItem,
        profile: Profile,
        fragment_threads: int,
        use_aria2: bool,
        logger: AppLogger,
    ) -> None:
        super().__init__()
        self._item = item
        self._profile = profile
        self._fragment_threads = fragment_threads
        self._use_aria2 = use_aria2
        self._logger = logger
        self.signals = DownloadTaskSignals()
        self._process: Optional[subprocess.Popen[str]] = None
        self._canceled = False

        self._progress_re = re.compile(r"^progress:(.*)$")
        self._destination_re = re.compile(r"^\[download\] Destination: (.+)$")

    def cancel(self) -> None:
        self._canceled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                return

    def run(self) -> None:
        client = YtdlpClient()
        output_dir = self._item.output_path
        path = Path(output_dir)
        if path.suffix:
            output_dir = str(path.parent)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        command = client.build_download_command(
            self._item.url,
            output_dir,
            self._profile,
            self._fragment_threads,
            self._use_aria2,
        )
        self._logger.info(f"Download start: {self._item.url}")
        self._logger.info(f"Command: {' '.join(command)}")

        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            self.signals.failed.emit(self._item.item_id, str(exc))
            return

        if not self._process.stdout:
            self.signals.failed.emit(self._item.item_id, "Failed to read yt-dlp output.")
            return

        for raw_line in self._process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            if self._canceled:
                break
            if match := self._destination_re.match(line):
                self.signals.output_path.emit(self._item.item_id, match.group(1))
                continue
            if progress_match := self._progress_re.match(line):
                payload = progress_match.group(1)
                parts = payload.split("/")
                if len(parts) >= 5:
                    downloaded, total, speed, eta, percent = parts[:5]
                    self.signals.progress.emit(
                        self._item.item_id,
                        {
                            "downloaded_text": downloaded if downloaded != "None" else None,
                            "total_text": total if total != "None" else None,
                            "speed": speed if speed != "None" else None,
                            "eta": eta if eta != "None" else None,
                            "progress": _parse_percent(percent),
                        },
                    )
                continue
            if line.startswith("[download]"):
                self._logger.info(line)

        if self._canceled:
            self.signals.canceled.emit(self._item.item_id)
            return

        return_code = self._process.wait()
        if return_code == 0:
            self.signals.completed.emit(self._item.item_id)
        else:
            self.signals.failed.emit(self._item.item_id, f"yt-dlp exited with {return_code}")


def _parse_percent(value: str) -> Optional[float]:
    value = value.strip().replace("%", "")
    try:
        return float(value)
    except ValueError:
        return None


class DownloadManager(QObject):
    """Queue and run downloads with concurrency limits and persistence."""
    item_added = Signal(DownloadItem)
    item_updated = Signal(DownloadItem)
    item_removed = Signal(str)
    queue_loaded = Signal(list)

    def __init__(self, base_dir: Path, logger: AppLogger) -> None:
        super().__init__()
        self._base_dir = base_dir
        self._logger = logger
        self._thread_pool = QThreadPool.globalInstance()
        self._items: Dict[str, DownloadItem] = {}
        self._tasks: Dict[str, DownloadTask] = {}
        self._profiles: Dict[str, Profile] = {}
        self._max_concurrent = 2
        self._fragment_threads = 8
        self._use_aria2 = False
        self._queue_path = base_dir / "data" / "queue.json"

    def register_profiles(self, profiles: Iterable[Profile]) -> None:
        self._profiles = {profile.name: profile for profile in profiles}

    def configure(self, max_concurrent: int, fragment_threads: int, use_aria2: bool) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._fragment_threads = max(1, fragment_threads)
        self._use_aria2 = use_aria2

    def add_items(
        self,
        items: List[VideoMetadata],
        profile: Profile,
        output_dir: str,
    ) -> None:
        self._logger.info(f"Queue add: {len(items)} item(s) for profile {profile.name}")
        for meta in items:
            if not meta.url:
                self._logger.warn("Skipping item with missing URL from metadata.")
                continue
            item = DownloadItem(
                item_id=str(uuid.uuid4()),
                url=meta.url,
                title=meta.title,
                duration=meta.duration,
                expected_size=meta.expected_size,
                output_path=output_dir,
                profile_name=profile.name,
                status="Queued",
            )
            self._items[item.item_id] = item
            self.item_added.emit(item)
        self._save_queue()

    def start(self) -> None:
        active = len(self._tasks)
        for item in list(self._items.values()):
            if active >= self._max_concurrent:
                break
            if item.status != "Queued":
                continue
            profile = self._profiles.get(item.profile_name)
            if not profile:
                item.status = "Failed"
                self.item_updated.emit(item)
                continue
            task = DownloadTask(
                item,
                profile,
                self._fragment_threads,
                self._use_aria2,
                self._logger,
            )
            task.signals.progress.connect(self._on_progress)
            task.signals.completed.connect(self._on_completed)
            task.signals.failed.connect(self._on_failed)
            task.signals.canceled.connect(self._on_canceled)
            task.signals.output_path.connect(self._on_output_path)
            item.status = "Downloading"
            self.item_updated.emit(item)
            self._tasks[item.item_id] = task
            self._thread_pool.start(task)
            active += 1
        self._save_queue()

    def pause_items(self, item_ids: Iterable[str]) -> None:
        for item_id in item_ids:
            self._cancel_item(item_id, status="Paused (requeue)")

    def resume_items(self, item_ids: Iterable[str]) -> None:
        for item_id in item_ids:
            item = self._items.get(item_id)
            if not item:
                continue
            if item.status.startswith("Paused"):
                item.status = "Queued"
                self.item_updated.emit(item)
        self.start()

    def cancel_items(self, item_ids: Iterable[str]) -> None:
        for item_id in item_ids:
            self._cancel_item(item_id, status="Canceled")

    def stop_all(self) -> None:
        for item_id in list(self._tasks.keys()):
            self._cancel_item(item_id, status="Canceled")

    def clear_completed(self) -> None:
        self._remove_by_status("Done")

    def clear_failed(self) -> None:
        self._remove_by_status("Failed")

    def load_queue(self) -> None:
        if not self._queue_path.exists():
            return
        try:
            data = json.loads(self._queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        items = []
        for raw in data.get("items", []):
            item = DownloadItem(**raw)
            self._items[item.item_id] = item
            items.append(item)
        if items:
            self.queue_loaded.emit(items)

    def _remove_by_status(self, status: str) -> None:
        to_remove = [item_id for item_id, item in self._items.items() if item.status == status]
        for item_id in to_remove:
            self._items.pop(item_id, None)
            self.item_removed.emit(item_id)
        self._save_queue()

    def _cancel_item(self, item_id: str, status: str) -> None:
        task = self._tasks.pop(item_id, None)
        if task:
            task.cancel()
        item = self._items.get(item_id)
        if item:
            item.status = status
            self.item_updated.emit(item)
        self._save_queue()

    def _on_progress(self, item_id: str, payload: dict) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        item.downloaded_text = payload.get("downloaded_text")
        item.total_text = payload.get("total_text")
        item.speed = payload.get("speed")
        item.eta = payload.get("eta")
        item.progress = payload.get("progress")
        self.item_updated.emit(item)

    def _on_output_path(self, item_id: str, output_path: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        item.output_path = output_path
        self.item_updated.emit(item)
        self._save_queue()

    def _on_completed(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        item.status = "Done"
        self._tasks.pop(item_id, None)
        self.item_updated.emit(item)
        self._save_queue()
        self.start()

    def _on_failed(self, item_id: str, error: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        item.status = "Failed"
        self._tasks.pop(item_id, None)
        self.item_updated.emit(item)
        self._logger.error(f"Download failed: {item.url} ({error})")
        self._save_queue()
        self.start()

    def _on_canceled(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        self._tasks.pop(item_id, None)
        self.item_updated.emit(item)
        self._save_queue()
        self.start()

    def _save_queue(self) -> None:
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [asdict(item) for item in self._items.values()]}
        self._queue_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
