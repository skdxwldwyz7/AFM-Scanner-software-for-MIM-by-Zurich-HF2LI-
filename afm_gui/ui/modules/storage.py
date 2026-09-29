from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
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
        self._last_scan_report_id = ""

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
            "storage.scan_reports.events": [],
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

    def write_scan_report(self) -> Path | None:
        """Write a text record for every finished scan, independent of GSF autosave."""
        context = dict(self.controller.scan_report_context)
        scan_id = str(context.get("scan_id", ""))
        if not scan_id or scan_id == self._last_scan_report_id:
            return None
        self._sync_extra_metadata()
        directory = Path(self.auto_save_dir.text().strip() or str(self.DEFAULT_AUTO_SAVE_DIR))
        generated_local = datetime.now().astimezone()
        filename = f"afm_{generated_local.strftime('%Y%m%d_%H%M%S_%f')}_scan_report.txt"
        path = directory / filename
        event = {
            "scan_id": scan_id,
            "status": context.get("status", "unknown"),
            "timestamp_local": generated_local.isoformat(timespec="milliseconds"),
            "directory": str(directory),
            "file": filename,
        }
        report = {
            "scan_lifecycle": context,
            "scan": self.controller.parameter_tree.data.get("scan", {}),
            "display_settings": self.controller.parameter_tree.data.get("display", {}),
            "runtime": self.controller.parameter_tree.data.get("runtime", {}),
            "devices_and_experiment_setup": {
                key: value
                for key, value in self.controller.parameter_tree.data.items()
                if key not in {"app", "scan", "display", "runtime", "storage"}
            },
            "storage": {"scan_report": event},
        }
        status = str(context.get("status", "unknown")).upper()
        error = str(context.get("error", "") or "")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            summary = [
                "AFM Scan Report",
                "===============",
                f"Scan ID: {scan_id}",
                f"Status: {status}",
                f"Started (UTC): {context.get('started_utc', 'not recorded')}",
                f"Finished (UTC): {context.get('finished_utc', 'not recorded')}",
                f"Duration (s): {context.get('duration_s', 'not recorded')}",
                f"Error / stop reason: {error or 'None'}",
                f"Report file: {path}",
                "",
                "Detailed scan, channel-display, device, PLL/PID, runtime, and storage metadata:",
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
                "",
            ]
            path.write_text("\n".join(summary), encoding="utf-8")
        except Exception as exc:
            self._log_callback(f"Scan report save failed: {exc}")
            return None
        self._last_scan_report_id = scan_id
        self.controller.parameter_tree.append_path("storage.scan_reports.events", event)
        self._log_callback(f"Saved scan report: {path}")
        return path

    def _sync_extra_metadata(self) -> None:
        if self._metadata_provider is None:
            return
        storage = self.controller.parameter_tree.data.get("storage", {})
        autosave_events = list(storage.get("autosave", {}).get("events", [])) if isinstance(storage, dict) else []
        manual_events = list(storage.get("manual_save", {}).get("events", [])) if isinstance(storage, dict) else []
        report_events = list(storage.get("scan_reports", {}).get("events", [])) if isinstance(storage, dict) else []
        self.controller.parameter_tree.update_paths(self._metadata_provider())
        self.controller.parameter_tree.set_path("storage.autosave.events", autosave_events)
        self.controller.parameter_tree.set_path("storage.manual_save.events", manual_events)
        self.controller.parameter_tree.set_path("storage.scan_reports.events", report_events)


__all__ = ["StorageModule"]
