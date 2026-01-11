from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from app.core.download_manager import DownloadManager
from app.core.env_check import EnvStatus, check_environment
from app.core.logger import AppLogger
from app.core.models import DownloadItem, Profile, VideoMetadata
from app.core.profile_fetcher import ProfileFetchTask
from app.core.profiles import ProfileStore
from app.core.ytdlp_client import YtdlpClient


class LinksDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Links to Queue")
        self.resize(500, 300)
        self._text = QPlainTextEdit()
        self._text.setPlaceholderText("Paste one or more URLs, one per line.")

        buttons = QHBoxLayout()
        ok_button = QPushButton("Add")
        cancel_button = QPushButton("Cancel")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout()
        layout.addWidget(self._text)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def urls(self) -> List[str]:
        return [line.strip() for line in self._text.toPlainText().splitlines() if line.strip()]


class ProfileEditorDialog(QDialog):
    def __init__(self, parent: QWidget, profiles: List[Profile], store: ProfileStore) -> None:
        super().__init__(parent)
        self.setWindowTitle("Profiles")
        self.resize(520, 360)
        self._store = store
        self._profiles = list(profiles)

        self._profile_combo = QComboBox()
        self._profile_combo.currentIndexChanged.connect(self._load_profile)

        self._name_edit = QLineEdit()
        self._output_edit = QLineEdit()
        self._cookies_file_edit = QLineEdit()
        self._cookies_browser_edit = QLineEdit()
        self._max_concurrent = QSpinBox()
        self._max_concurrent.setRange(1, 10)

        browse_output = QPushButton("Browse")
        browse_output.clicked.connect(self._browse_output)
        browse_cookies = QPushButton("Browse")
        browse_cookies.clicked.connect(self._browse_cookies)

        output_row = QHBoxLayout()
        output_row.addWidget(self._output_edit)
        output_row.addWidget(browse_output)

        cookies_row = QHBoxLayout()
        cookies_row.addWidget(self._cookies_file_edit)
        cookies_row.addWidget(browse_cookies)

        form = QFormLayout()
        form.addRow("Profile:", self._profile_combo)
        form.addRow("Name:", self._name_edit)
        form.addRow("Output Folder:", output_row)
        form.addRow("Cookies File:", cookies_row)
        form.addRow("Cookies Browser:", self._cookies_browser_edit)
        form.addRow("Max Concurrent:", self._max_concurrent)

        add_button = QPushButton("Add New")
        remove_button = QPushButton("Remove")
        add_button.clicked.connect(self._add_profile)
        remove_button.clicked.connect(self._remove_profile)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)

        actions = QHBoxLayout()
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(button_box)
        self.setLayout(layout)

        self._reload_combo()

    def _reload_combo(self) -> None:
        self._profile_combo.clear()
        for profile in self._profiles:
            self._profile_combo.addItem(profile.name, profile)
        if self._profiles:
            self._profile_combo.setCurrentIndex(0)

    def _load_profile(self) -> None:
        profile = self._profile_combo.currentData()
        if not isinstance(profile, Profile):
            return
        self._name_edit.setText(profile.name)
        self._output_edit.setText(profile.output_dir or "")
        self._cookies_file_edit.setText(profile.cookies_path or "")
        self._cookies_browser_edit.setText(profile.cookies_browser or "")
        self._max_concurrent.setValue(profile.max_concurrent)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder", self._output_edit.text())
        if path:
            self._output_edit.setText(path)

    def _browse_cookies(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Cookies File", "", "Text Files (*.txt)")
        if path:
            self._cookies_file_edit.setText(path)

    def _add_profile(self) -> None:
        self._profiles.append(Profile(name="New Profile", max_concurrent=2))
        self._reload_combo()
        self._profile_combo.setCurrentIndex(len(self._profiles) - 1)

    def _remove_profile(self) -> None:
        idx = self._profile_combo.currentIndex()
        if idx < 0:
            return
        self._profiles.pop(idx)
        if not self._profiles:
            self._profiles.append(Profile(name="Default", max_concurrent=2))
        self._reload_combo()

    def _save(self) -> None:
        idx = self._profile_combo.currentIndex()
        if idx >= 0 and idx < len(self._profiles):
            self._profiles[idx] = Profile(
                name=self._name_edit.text().strip() or "Default",
                output_dir=self._output_edit.text().strip() or None,
                cookies_path=self._cookies_file_edit.text().strip() or None,
                cookies_browser=self._cookies_browser_edit.text().strip() or None,
                max_concurrent=self._max_concurrent.value(),
            )
        self._store.save(self._profiles)
        self.accept()

    def profiles(self) -> List[Profile]:
        return self._profiles


class LogPanel(QWidget):
    def __init__(self, logger: AppLogger, base_dir: Path) -> None:
        super().__init__()
        self._logger = logger
        self._base_dir = base_dir
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)

        self._copy_button = QPushButton("Copy Logs")
        self._save_button = QPushButton("Save Logs")
        self._copy_button.clicked.connect(self._copy_logs)
        self._save_button.clicked.connect(self._save_logs)

        controls = QHBoxLayout()
        controls.addStretch(1)
        controls.addWidget(self._copy_button)
        controls.addWidget(self._save_button)

        layout = QVBoxLayout()
        layout.addWidget(self._text)
        layout.addLayout(controls)
        self.setLayout(layout)

        self._logger.message_logged.connect(self._append_log)

    def _append_log(self, level: str, message: str) -> None:
        self._text.appendPlainText(f"[{level}] {message}")

    def _copy_logs(self) -> None:
        QApplication.clipboard().setText(self._text.toPlainText())

    def _save_logs(self) -> None:
        default_path = str(self._base_dir / "data" / "logs" / "ui_logs.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save Logs", default_path, "Text Files (*.txt)")
        if not path:
            return
        Path(path).write_text(self._text.toPlainText(), encoding="utf-8")


class EnvStatusWidget(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Environment Status")
        self._labels: Dict[str, QLabel] = {}
        layout = QVBoxLayout()
        for tool in ["python", "yt-dlp", "ffmpeg", "ffprobe", "aria2c"]:
            label = QLabel(f"{tool}: checking...")
            self._labels[tool] = label
            layout.addWidget(label)
        self.setLayout(layout)

    def update_status(self, statuses: List[EnvStatus]) -> None:
        for status in statuses:
            label = self._labels.get(status.name)
            if not label:
                continue
            state = "OK" if status.ok else "MISSING"
            hint = f" - {status.hint}" if status.hint else ""
            label.setText(f"{status.name}: {status.version} [{state}]{hint}")
            label.setStyleSheet("color: #2a7a2a;" if status.ok else "color: #b23b3b;")


class EnvCheckTaskSignals(QObject):
    result = Signal(list)


class EnvCheckTask(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = EnvCheckTaskSignals()

    def run(self) -> None:
        statuses = check_environment()
        self.signals.result.emit(statuses)


class MetadataFetchSignals(QObject):
    result = Signal(list)
    error = Signal(str)


class MetadataFetchTask(QRunnable):
    def __init__(self, urls: List[str], profile: Profile, logger: AppLogger) -> None:
        super().__init__()
        self._urls = urls
        self._profile = profile
        self._logger = logger
        self.signals = MetadataFetchSignals()

    def run(self) -> None:
        client = YtdlpClient()
        items: List[VideoMetadata] = []
        try:
            for url in self._urls:
                items.extend(client.extract_metadata(url, self._profile, logger=self._logger.info))
            self.signals.result.emit(items)
        except Exception as exc:  # noqa: BLE001
            self._logger.error(f"Metadata fetch failed: {exc}")
            self.signals.error.emit(str(exc))


class QueueTab(QWidget):
    def __init__(self, logger: AppLogger, manager: DownloadManager, profiles: List[Profile]) -> None:
        super().__init__()
        self._logger = logger
        self._manager = manager
        self._profiles = profiles
        self._row_by_id: Dict[str, int] = {}

        self._output_path = QLineEdit(str(Path("exports").resolve()))
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._browse_output)
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(self._open_folder)

        self._profile_combo = QComboBox()
        for profile in profiles:
            self._profile_combo.addItem(profile.name, profile)

        self._max_concurrent = QSpinBox()
        self._max_concurrent.setRange(1, 10)
        self._max_concurrent.setValue(2)

        self._fragment_threads = QSpinBox()
        self._fragment_threads.setRange(1, 32)
        self._fragment_threads.setValue(8)

        self._aria2_checkbox = QCheckBox("Use aria2c (if available)")
        self._aria2_checkbox.setEnabled(False)

        self._add_links_button = QPushButton("Add Links to Queue")
        self._start_button = QPushButton("Start")
        self._stop_all_button = QPushButton("Stop All")
        self._pause_button = QPushButton("Pause Selected (requeue)")
        self._resume_button = QPushButton("Resume Selected")
        self._cancel_button = QPushButton("Cancel Selected")
        self._clear_done_button = QPushButton("Clear Completed")
        self._clear_failed_button = QPushButton("Clear Failed")
        self._clear_all_button = QPushButton("Clear All")

        self._add_links_button.clicked.connect(self._on_add_links)
        self._start_button.clicked.connect(self._on_start)
        self._stop_all_button.clicked.connect(self._manager.stop_all)
        self._pause_button.clicked.connect(self._on_pause)
        self._resume_button.clicked.connect(self._on_resume)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._clear_done_button.clicked.connect(self._manager.clear_completed)
        self._clear_failed_button.clicked.connect(self._manager.clear_failed)
        self._clear_all_button.clicked.connect(self._on_clear_all)

        self._table = QTableWidget(0, 10)
        self._table.setHorizontalHeaderLabels(
            [
                "Status",
                "Title",
                "Duration",
                "Expected Size",
                "Downloaded/Total",
                "Speed",
                "ETA",
                "Progress %",
                "Output Path",
                "Profile Name",
            ]
        )
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)

        form = QFormLayout()
        output_row = QHBoxLayout()
        output_row.addWidget(self._output_path)
        output_row.addWidget(browse_button)
        output_row.addWidget(open_button)
        form.addRow("Output Folder:", output_row)
        form.addRow("Profile:", self._profile_combo)
        form.addRow("Max Concurrent Downloads:", self._max_concurrent)
        form.addRow("Fragment Threads (-N):", self._fragment_threads)
        form.addRow("", self._aria2_checkbox)

        buttons = QHBoxLayout()
        buttons.addWidget(self._add_links_button)
        buttons.addWidget(self._start_button)
        buttons.addWidget(self._stop_all_button)
        buttons.addWidget(self._pause_button)
        buttons.addWidget(self._resume_button)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._clear_done_button)
        buttons.addWidget(self._clear_failed_button)
        buttons.addWidget(self._clear_all_button)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self._table)
        self.setLayout(layout)
        layout.setStretchFactor(self._table, 1)
        self._table.setMinimumHeight(320)

        self._manager.item_added.connect(self._add_row)
        self._manager.item_updated.connect(self._update_row)
        self._manager.item_removed.connect(self._remove_row)
        self._manager.queue_loaded.connect(self._load_rows)

    def set_env_status(self, statuses: List[EnvStatus]) -> None:
        aria2 = next((s for s in statuses if s.name == "aria2c"), None)
        self._aria2_checkbox.setEnabled(bool(aria2 and aria2.ok))

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder", self._output_path.text())
        if path:
            self._output_path.setText(path)

    def _open_folder(self) -> None:
        path = Path(self._output_path.text()).resolve()
        if not path.exists():
            QMessageBox.warning(self, "Missing Folder", "Output folder does not exist.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_add_links(self) -> None:
        dialog = LinksDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        urls = dialog.urls()
        if not urls:
            return
        profile = self._profile_combo.currentData()
        if not isinstance(profile, Profile):
            QMessageBox.warning(self, "Profile Missing", "Select a profile.")
            return
        self._logger.info(f"Queue metadata fetch: {len(urls)} URL(s)")
        task = MetadataFetchTask(urls, profile, self._logger)
        task.signals.result.connect(lambda items: self._manager.add_items(items, profile, self._output_path.text()))
        task.signals.error.connect(lambda message: QMessageBox.critical(self, "Metadata Error", message))
        QThreadPool.globalInstance().start(task)

    def _on_start(self) -> None:
        self._manager.configure(
            self._max_concurrent.value(),
            self._fragment_threads.value(),
            self._aria2_checkbox.isChecked(),
        )
        self._manager.start()

    def _selected_item_ids(self) -> List[str]:
        rows = [index.row() for index in self._table.selectionModel().selectedRows()]
        ids = []
        for row in rows:
            item_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if item_id:
                ids.append(item_id)
        return ids

    def _on_pause(self) -> None:
        ids = self._selected_item_ids()
        if not ids:
            return
        self._logger.warn("Pause = cancel and requeue from scratch.")
        self._manager.pause_items(ids)

    def _on_resume(self) -> None:
        ids = self._selected_item_ids()
        if not ids:
            return
        self._manager.resume_items(ids)

    def _on_cancel(self) -> None:
        ids = self._selected_item_ids()
        if not ids:
            return
        self._manager.cancel_items(ids)

    def _on_clear_all(self) -> None:
        if self._table.rowCount() == 0:
            return
        if (
            QMessageBox.question(
                self, "Clear All", "Remove all items from the queue?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._manager.clear_all()

    def _add_row(self, item: DownloadItem) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._row_by_id[item.item_id] = row
        self._update_row(item)

    def _load_rows(self, items: List[DownloadItem]) -> None:
        for item in items:
            self._add_row(item)

    def _remove_row(self, item_id: str) -> None:
        row = self._row_by_id.pop(item_id, None)
        if row is None:
            return
        self._table.removeRow(row)
        self._row_by_id = {
            self._table.item(idx, 0).data(Qt.ItemDataRole.UserRole): idx
            for idx in range(self._table.rowCount())
            if self._table.item(idx, 0)
        }

    def _update_row(self, item: DownloadItem) -> None:
        row = self._row_by_id.get(item.item_id)
        if row is None:
            return
        self._set_item(row, 0, item.status, item.item_id)
        self._set_item(row, 1, item.title)
        self._set_item(row, 2, _format_duration(item.duration))
        self._set_item(row, 3, _format_size(item.expected_size))
        downloaded = item.downloaded_text or "-"
        total = item.total_text or "-"
        self._set_item(row, 4, f"{downloaded} / {total}")
        self._set_item(row, 5, item.speed or "-")
        self._set_item(row, 6, item.eta or "-")
        progress = f"{item.progress:.1f}" if item.progress is not None else "-"
        self._set_item(row, 7, progress)
        self._set_item(row, 8, item.output_path)
        self._set_item(row, 9, item.profile_name)

    def _set_item(self, row: int, col: int, text: str, item_id: Optional[str] = None) -> None:
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            self._table.setItem(row, col, item)
        item.setText(text)
        if col == 0 and item_id:
            item.setData(Qt.ItemDataRole.UserRole, item_id)
        item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)

    def output_dir(self) -> str:
        return self._output_path.text()

    def selected_profile(self) -> Optional[Profile]:
        profile = self._profile_combo.currentData()
        if isinstance(profile, Profile):
            return profile
        return None

    def set_profiles(self, profiles: List[Profile]) -> None:
        self._profiles = profiles
        self._profile_combo.clear()
        for profile in profiles:
            self._profile_combo.addItem(profile.name, profile)


class ProfilesTab(QWidget):
    def __init__(self, logger: AppLogger, manager: DownloadManager, profiles: List[Profile], queue_tab: QueueTab) -> None:
        super().__init__()
        self._logger = logger
        self._manager = manager
        self._profiles = profiles
        self._queue_tab = queue_tab
        self._thread_pool = QThreadPool.globalInstance()
        self._current_task: Optional[ProfileFetchTask] = None
        self._cancel_event = threading.Event()
        self._results: List[VideoMetadata] = []

        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["YouTube", "TikTok"])

        self._profile_url = QLineEdit()
        self._profile_url.setPlaceholderText("https://www.youtube.com/@channel or https://www.tiktok.com/@user")

        self._profile_combo = QComboBox()
        for profile in profiles:
            self._profile_combo.addItem(profile.name, profile)

        fetch_button = QPushButton("Fetch")
        stop_button = QPushButton("Stop Fetch")
        fetch_button.clicked.connect(self._on_fetch)
        stop_button.clicked.connect(self._on_stop)

        self._select_all = QPushButton("Select All")
        self._select_none = QPushButton("Select None")
        self._add_selected = QPushButton("Add Selected to Queue")
        self._select_all.clicked.connect(self._on_select_all)
        self._select_none.clicked.connect(self._on_select_none)
        self._add_selected.clicked.connect(self._on_add_selected)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Select", "Title", "Duration", "Views", "Video URL"])
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)

        form = QFormLayout()
        form.addRow("Platform:", self._platform_combo)
        form.addRow("Profile URL:", self._profile_url)
        form.addRow("Profile:", self._profile_combo)

        actions = QHBoxLayout()
        actions.addWidget(fetch_button)
        actions.addWidget(stop_button)
        actions.addStretch(1)
        actions.addWidget(self._select_all)
        actions.addWidget(self._select_none)
        actions.addWidget(self._add_selected)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self._table)
        self.setLayout(layout)
        layout.setStretchFactor(self._table, 1)
        self._table.setMinimumHeight(280)

    def _on_fetch(self) -> None:
        profile_url = self._profile_url.text().strip()
        if not profile_url:
            QMessageBox.information(self, "Missing URL", "Enter a profile URL to fetch.")
            return
        profile = self._profile_combo.currentData()
        if not isinstance(profile, Profile):
            QMessageBox.warning(self, "Profile Missing", "Select a profile.")
            return
        if self._current_task:
            QMessageBox.information(self, "Fetch Running", "A fetch is already running.")
            return
        self._cancel_event.clear()
        platform = self._platform_combo.currentText()
        self._logger.info(f"Profile fetch requested: {platform} {profile_url}")
        task = ProfileFetchTask(platform, profile_url, profile, self._logger, self._cancel_event)
        task.signals.fetched.connect(self._on_fetched)
        task.signals.error.connect(self._on_fetch_error)
        task.signals.stopped.connect(self._on_fetch_stopped)
        self._current_task = task
        self._thread_pool.start(task)

    def _on_stop(self) -> None:
        if not self._current_task:
            return
        self._logger.warn("Fetch stop requested (will stop after current extraction).")
        self._cancel_event.set()

    def _on_fetched(self, items: List[VideoMetadata]) -> None:
        self._current_task = None
        self._results = items
        self._table.setRowCount(0)
        for item in items:
            self._append_row(item)
        self._logger.info(f"Profile fetch complete: {len(items)} item(s)")

    def _on_fetch_error(self, message: str) -> None:
        self._current_task = None
        QMessageBox.critical(self, "Fetch Error", message)

    def _on_fetch_stopped(self) -> None:
        self._current_task = None
        self._logger.warn("Profile fetch stopped.")

    def _append_row(self, item: VideoMetadata) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        checkbox = QTableWidgetItem()
        checkbox.setCheckState(Qt.CheckState.Unchecked)
        checkbox.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        self._table.setItem(row, 0, checkbox)
        self._table.setItem(row, 1, QTableWidgetItem(item.title))
        self._table.setItem(row, 2, QTableWidgetItem(_format_duration(item.duration)))
        self._table.setItem(row, 3, QTableWidgetItem(_format_views(item.view_count)))
        self._table.setItem(row, 4, QTableWidgetItem(item.url))
        for col in range(1, 5):
            self._table.item(row, col).setFlags(self._table.item(row, col).flags() ^ Qt.ItemFlag.ItemIsEditable)

    def _on_select_all(self) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _on_select_none(self) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_add_selected(self) -> None:
        selected = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(self._results[row])
        if not selected:
            QMessageBox.information(self, "No Selection", "Select videos to add to the queue.")
            return
        missing_urls = [item for item in selected if not item.url]
        if missing_urls:
            QMessageBox.warning(
                self,
                "Missing URLs",
                "Some items did not include a URL and will be skipped. Try fetching again.",
            )
            selected = [item for item in selected if item.url]
            if not selected:
                return
        profile = self._profile_combo.currentData()
        if not isinstance(profile, Profile):
            QMessageBox.warning(self, "Profile Missing", "Select a profile.")
            return
        output_dir = self._queue_tab.output_dir()
        self._manager.add_items(selected, profile, output_dir)
        self._logger.info(f"Added {len(selected)} profile items to queue.")

    def set_profiles(self, profiles: List[Profile]) -> None:
        self._profiles = profiles
        self._profile_combo.clear()
        for profile in profiles:
            self._profile_combo.addItem(profile.name, profile)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("dv_downloader")
        self.resize(1200, 800)

        self._base_dir = Path(__file__).resolve().parents[2]
        self._logger = AppLogger(self._base_dir)

        self._profile_store = ProfileStore(self._base_dir)
        self._profiles = self._profile_store.load()

        self._download_manager = DownloadManager(self._base_dir, self._logger)
        self._download_manager.register_profiles(self._profiles)

        self._queue_tab = QueueTab(self._logger, self._download_manager, self._profiles)
        self._profiles_tab = ProfilesTab(
            self._logger, self._download_manager, self._profiles, self._queue_tab
        )

        self._env_status = EnvStatusWidget()
        self._queue_tab.layout().addWidget(self._env_status)

        self._edit_profiles_button = QPushButton("Edit Profiles")
        self._edit_profiles_button.clicked.connect(self._open_profiles_editor)

        tabs = QTabWidget()
        tabs.addTab(self._queue_tab, "Queue")
        tabs.addTab(self._profiles_tab, "Profiles")

        self._theme_toggle = QCheckBox("Dark mode")
        self._theme_toggle.toggled.connect(self._apply_theme)

        header = QHBoxLayout()
        header.addWidget(QLabel("dv_downloader"))
        header.addStretch(1)
        header.addWidget(self._edit_profiles_button)
        header.addWidget(self._theme_toggle)

        log_panel = LogPanel(self._logger, self._base_dir)
        log_container = QGroupBox("Logs")
        log_layout = QVBoxLayout()
        log_layout.addWidget(log_panel)
        log_container.setLayout(log_layout)

        central = QWidget()
        central_layout = QVBoxLayout()
        central_layout.addLayout(header)
        central_layout.addWidget(tabs)
        central_layout.addWidget(log_container)
        central.setLayout(central_layout)
        self.setCentralWidget(central)

        self._download_manager.load_queue()
        self._run_env_check()
        self._apply_theme(self._theme_toggle.isChecked())

    def _run_env_check(self) -> None:
        task = EnvCheckTask()
        task.signals.result.connect(self._on_env_checked)
        QThreadPool.globalInstance().start(task)

    def _on_env_checked(self, statuses: List[EnvStatus]) -> None:
        self._env_status.update_status(statuses)
        self._queue_tab.set_env_status(statuses)

    def _apply_theme(self, dark_mode: bool) -> None:
        app = QApplication.instance()
        if not app:
            return
        app.setStyleSheet(_build_stylesheet(dark_mode))

    def _open_profiles_editor(self) -> None:
        dialog = ProfileEditorDialog(self, self._profiles, self._profile_store)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._profiles = dialog.profiles()
        self._download_manager.register_profiles(self._profiles)
        self._queue_tab.set_profiles(self._profiles)
        self._profiles_tab.set_profiles(self._profiles)


def _build_stylesheet(dark_mode: bool) -> str:
    if dark_mode:
        return """
        QWidget { font-family: "Segoe UI"; font-size: 11pt; color: #e6e6e6; background: #15181b; }
        QMainWindow { background: #15181b; }
        QGroupBox { border: 1px solid #2a3137; border-radius: 8px; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
        QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
            background: #1e2328; border: 1px solid #2f3840; border-radius: 6px; padding: 6px;
        }
        QTabWidget::pane { border: 1px solid #2a3137; border-radius: 8px; padding: 4px; }
        QTabBar::tab { background: #1e2328; border: 1px solid #2a3137; padding: 6px 12px; margin-right: 4px; }
        QTabBar::tab:selected { background: #2a3137; }
        QTableWidget { background: #1b2025; gridline-color: #2a3137; border: 1px solid #2a3137; }
        QHeaderView::section { background: #222931; border: 0; padding: 6px; }
        QTableWidget::item:selected { background: #314154; }
        QScrollBar:vertical { background: #1e2328; width: 12px; margin: 0; }
        QScrollBar::handle:vertical { background: #2f3840; border-radius: 6px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QPushButton {
            background: #2e3740; border: 1px solid #3a4550; border-radius: 6px; padding: 6px 10px;
        }
        QPushButton:hover { background: #38424c; }
        QCheckBox { spacing: 6px; }
        """
    return """
    QWidget { font-family: "Segoe UI"; font-size: 11pt; color: #1a1a1a; background: #f5f6f8; }
    QMainWindow { background: #f5f6f8; }
    QGroupBox { border: 1px solid #d5dbe1; border-radius: 8px; margin-top: 8px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
        background: #ffffff; border: 1px solid #c9d1d9; border-radius: 6px; padding: 6px;
    }
    QTabWidget::pane { border: 1px solid #d5dbe1; border-radius: 8px; padding: 4px; }
    QTabBar::tab { background: #f0f3f6; border: 1px solid #d5dbe1; padding: 6px 12px; margin-right: 4px; }
    QTabBar::tab:selected { background: #ffffff; }
    QTableWidget { background: #ffffff; gridline-color: #e2e6ea; border: 1px solid #d5dbe1; }
    QHeaderView::section { background: #eef1f4; border: 0; padding: 6px; }
    QTableWidget::item:selected { background: #cfe3ff; }
    QScrollBar:vertical { background: #eef1f4; width: 12px; margin: 0; }
    QScrollBar::handle:vertical { background: #c9d1d9; border-radius: 6px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QPushButton {
        background: #ffffff; border: 1px solid #c9d1d9; border-radius: 6px; padding: 6px 10px;
    }
    QPushButton:hover { background: #f1f4f7; }
    QCheckBox { spacing: 6px; }
    """


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_views(views: int | None) -> str:
    if views is None:
        return "-"
    return f"{views:,}"


def _format_size(size: int | None) -> str:
    if size is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024:
            return f"{value:0.1f} {unit}"
        value /= 1024
    return f"{value:0.1f} PB"
