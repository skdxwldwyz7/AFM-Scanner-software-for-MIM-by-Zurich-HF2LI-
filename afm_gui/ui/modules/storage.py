from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog, QWidget

from afm_gui.core.scan_controller import ScanController
from afm_gui.core.scan_modes import ScanModeConfig


class StorageModule(QObject):
    """Owns GUI save actions, auto-save policy, and storage metadata events."""

    DEFAULT_AUTO_SAVE_DIR = Path.home() / "AFM_scans"

    def __init__(
        self,
        controller: ScanController,
        mode_provider: Callable[[], ScanModeConfig],
        metadata_provider: Callable[[], dict[str, object]] | None,
        log_callback: Callable[[str], None],
        dialog_parent: QWidget,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._mode_provider = mode_provider
        self._metadata_provider = metadata_provider
        self._log_callback = log_callback
        self._dialog_parent = dialog_parent

    def bind_controls(self, save_button, auto_save_enabled, auto_save_dir, browse_button) -> None:
        self.save_gsf = save_button
        self.auto_save_enabled = auto_save_enabled
        self.auto_save_dir = auto_save_dir
        self.auto_save_browse = browse_button
        self.save_gsf.clicked.connect(self.save_gsf_bundle)
        self.auto_save_browse.clicked.connect(self.browse_auto_save_dir)

    def metadata_paths(self) -> dict[str, object]:
        return {
            "storage.autosave.enabled": self.auto_save_enabled.isChecked(),
            "storage.autosave.directory": self.auto_save_dir.text().strip(),
            "storage.autosave.events": [],
            "storage.manual_save.events": [],
        }

    def save_gsf_bundle(self) -> None:
        self._sync_extra_metadata()
        path, _ = QFileDialog.getSaveFileName(
            self._dialog_parent,
            "Save GSF Bundle",
            str(Path.home() / "afm_scan.gsf"),
            "Gwyddion Simple Field (*.gsf)",
        )
        if not path:
            return
        output_path = Path(path)
        prefix = output_path.stem if output_path.stem else "afm_scan"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.controller.parameter_tree.append_path(
            "storage.manual_save.events",
            {
                "timestamp_local": timestamp,
                "directory": str(output_path.parent),
                "file_prefix": prefix,
            },
        )
        self.controller.export_gsf_bundle(output_path.parent, self._mode_provider(), file_prefix=prefix)

    def browse_auto_save_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self._dialog_parent,
            "Select Auto Save Folder",
            self.auto_save_dir.text().strip() or str(self.DEFAULT_AUTO_SAVE_DIR),
        )
        if directory:
            self.auto_save_dir.setText(directory)

    def auto_save(self, event: str) -> None:
        if not self.auto_save_enabled.isChecked() or self.controller.current_line_index < 0:
            return
        self._sync_extra_metadata()
        directory = Path(self.auto_save_dir.text().strip() or str(self.DEFAULT_AUTO_SAVE_DIR))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        line_number = self.controller.current_line_index + 1
        prefix = f"afm_{timestamp}_{event}_line{line_number:04d}"
        self.controller.parameter_tree.append_path(
            "storage.autosave.events",
            {
                "event": event,
                "timestamp_local": timestamp,
                "directory": str(directory),
                "file_prefix": prefix,
                "line_index": self.controller.current_line_index,
            },
        )
        try:
            self.controller.export_gsf_bundle(directory, self._mode_provider(), file_prefix=prefix)
        except OSError as exc:
            self._log_callback(f"Auto save failed: {exc}")

    def _sync_extra_metadata(self) -> None:
        if self._metadata_provider is None:
            return
        storage = self.controller.parameter_tree.data.get("storage", {})
        autosave_events = list(storage.get("autosave", {}).get("events", [])) if isinstance(storage, dict) else []
        manual_events = list(storage.get("manual_save", {}).get("events", [])) if isinstance(storage, dict) else []
        self.controller.parameter_tree.update_paths(self._metadata_provider())
        self.controller.parameter_tree.set_path("storage.autosave.events", autosave_events)
        self.controller.parameter_tree.set_path("storage.manual_save.events", manual_events)


__all__ = ["StorageModule"]
