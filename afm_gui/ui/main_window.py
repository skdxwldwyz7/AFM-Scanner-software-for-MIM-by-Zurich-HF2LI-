from __future__ import annotations

import json
from pathlib import Path
from importlib import resources
import threading

from pyqtgraph.dockarea import Dock, DockArea
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from afm_gui.core.scan_config import ScanDirection
from afm_gui.core.scan_controller import ScanController
from afm_gui.device.scan_device import AdapterScannerDevice
from afm_gui.ui.modules.channel_images import ChannelImagesModule
from afm_gui.ui.modules.device import DeviceModule
from afm_gui.ui.modules.lockin import LockInModule
from afm_gui.ui.modules.metadata import MetadataModule
from afm_gui.ui.modules.scan import ScanModule
from afm_gui.ui.modules.spectroscopy import SpectroscopyModule
from afm_gui.ui.modules.stage import StageModule
from afm_gui.ui.modules.storage import StorageModule
from afm_gui.ui.panels.command_log import build_command_log_panel
from afm_gui.ui.panels.controls import build_controls_panel
from afm_gui.ui.panels.status import build_status_panel


class MainWindow(QMainWindow):
    STARTUP_LAYOUT = "layout1.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AFM Scan Control")

        self.device_module = DeviceModule(self._append_log, self, self)
        self.device_manager = self.device_module.manager
        self.device = AdapterScannerDevice(
            lambda: self.device_manager.adapter_for_function("scan_scanner"),
            self._scan_acquisition_callback,
            self,
        )
        self.controller = ScanController(self.device, self)
        self.metadata_module = MetadataModule(lambda: self.controller.parameter_tree.to_dict(), self)
        self.scan_module = ScanModule(
            self.controller,
            lambda: self.channel_images_module.display_metadata(),
            self._scan_extra_metadata,
            self.metadata_module.refresh,
            self._append_log,
            self,
        )
        self.channel_images_module = ChannelImagesModule(
            lambda: self.scan_module.current_mode,
            self.scan_module.image_geometry,
            self.scan_module.apply_roi_to_scan_parameters,
            self._append_log,
            self,
        )
        self.scan_module.set_mode_changed_callback(self.channel_images_module.reset_for_mode)
        self.stage_module = StageModule(self._append_log, self.device_manager, self)
        self.lockin_module = LockInModule(self._append_log, self.device_manager, self)
        self.storage_module = StorageModule(
            self.controller,
            lambda: self.scan_module.current_mode,
            self._append_log,
            self,
            self,
        )
        self.spectroscopy_module = SpectroscopyModule(
            self.scan_module.config,
            self._scan_extra_metadata,
            self._append_log,
            self,
            self,
        )
        self.stage_controller = self.stage_module.controller
        self.lockin_controllers = self.lockin_module.controllers
        self.lockin_controller = self.lockin_module.primary_controller
        self.panel_actions: dict[str, QAction] = {}
        self.panels: dict[str, dict[str, object]] = {}
        self._floating_panel_windows: dict[QWidget, str] = {}
        self.default_layout_state: dict[str, object] = {}

        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        self.dock_area = DockArea()
        self.setCentralWidget(self.dock_area)

        self.image_grid_widget = self.channel_images_module.widget
        self.line_plot = self.channel_images_module.line_plot

        self.image_dock = Dock("Channel Images", size=(980, 560))
        self.line_dock = Dock("Line Plot", size=(820, 180))
        self.parameter_dock = Dock("Scan Parameters", size=(360, 430))
        self.control_dock = Dock("Controls", size=(360, 120))
        self.device_dock = Dock("Device Manager", size=(820, 180))
        self.stage_dock = Dock("Stage Map", size=(360, 430))
        self.lockin_dock = Dock("Lock-in Amplifier", size=(980, 520))
        self.spectroscopy_dock = Dock("Spectroscopy", size=(980, 560))
        self.status_dock = Dock("State", size=(820, 160))
        self.metadata_dock = Dock("Parameter Tree", size=(360, 280))
        self.log_dock = Dock("Command Log", size=(360, 180))

        self.image_dock.addWidget(self.image_grid_widget)
        self.line_dock.addWidget(self.line_plot)
        self.parameter_dock.addWidget(self._parameter_box())
        self.control_dock.addWidget(self._control_box())
        self.device_dock.addWidget(self._device_manager_box())
        self.stage_dock.addWidget(self._stage_map_box())
        self.lockin_dock.addWidget(self._lockin_box())
        self.spectroscopy_dock.addWidget(self._spectroscopy_box())
        self.status_dock.addWidget(self._status_box())
        self.metadata_dock.addWidget(self._metadata_box())
        self.log_dock.addWidget(self._log_box())

        self.dock_area.addDock(self.stage_dock, "left")
        self.dock_area.addDock(self.parameter_dock, "right", self.stage_dock)
        self.dock_area.addDock(self.image_dock, "right", self.parameter_dock)
        self.dock_area.addDock(self.control_dock, "bottom", self.stage_dock)
        self.dock_area.addDock(self.metadata_dock, "bottom", self.control_dock)
        self.dock_area.addDock(self.log_dock, "bottom", self.metadata_dock)
        self.dock_area.addDock(self.line_dock, "bottom", self.image_dock)
        self.dock_area.addDock(self.status_dock, "bottom", self.line_dock)
        self.dock_area.addDock(self.lockin_dock, "bottom", self.status_dock)
        self.dock_area.addDock(self.spectroscopy_dock, "bottom", self.lockin_dock)
        self.dock_area.addDock(self.device_dock, "bottom", self.spectroscopy_dock)
        self._register_panels()
        self._build_menus()
        self.default_layout_state = self.dock_area.saveState()
        self._load_startup_layout()

        self.channel_images_module.bind_status_controls(
            self.display_count,
            self.line_channel_selector,
            self.line_pass_selector,
            self.position_label,
        )
        self.scan_module.apply_scan_mode(self.scan_module.current_mode)
        self.storage_module.bind_controls(
            self.save_gsf,
            self.auto_save_enabled,
            self.auto_save_dir,
            self.auto_save_browse,
        )
        self.metadata_module.refresh()
        self._update_scan_button_state("Idle")

    def _register_panels(self) -> None:
        self.panels = {
            "stage": {"title": "Stage Map", "dock": self.stage_dock, "position": "left", "relative": None},
            "images": {"title": "Channel Images", "dock": self.image_dock, "position": "right", "relative": "parameters"},
            "line": {"title": "Line Plot", "dock": self.line_dock, "position": "bottom", "relative": "images"},
            "parameters": {
                "title": "Scan Parameters",
                "dock": self.parameter_dock,
                "position": "right",
                "relative": "stage",
            },
            "controls": {"title": "Controls", "dock": self.control_dock, "position": "bottom", "relative": "stage"},
            "devices": {
                "title": "Device Manager",
                "dock": self.device_dock,
                "position": "bottom",
                "relative": "state",
                "context_close": True,
                "open_floating": True,
            },
            "lockin": {
                "title": "Lock-in Amplifier",
                "dock": self.lockin_dock,
                "position": "bottom",
                "relative": "state",
                "context_close": True,
                "default_visible": False,
                "open_floating": True,
            },
            "spectroscopy": {
                "title": "Spectroscopy",
                "dock": self.spectroscopy_dock,
                "position": "bottom",
                "relative": "state",
                "context_close": True,
                "default_visible": False,
                "open_floating": True,
            },
            "state": {"title": "State", "dock": self.status_dock, "position": "bottom", "relative": "line"},
            "metadata": {
                "title": "Parameter Tree",
                "dock": self.metadata_dock,
                "position": "bottom",
                "relative": "controls",
            },
            "log": {
                "title": "Command Log",
                "dock": self.log_dock,
                "position": "bottom",
                "relative": "metadata",
                "context_close": True,
            },
        }
        for key, panel in self.panels.items():
            dock = panel["dock"]
            if isinstance(dock, Dock):
                dock.sigClosed.connect(lambda _dock, panel_key=key: self._sync_panel_action(panel_key, False))
                if panel.get("context_close"):
                    self._install_panel_context_menu(key, dock)

    def _install_panel_context_menu(self, key: str, dock: Dock) -> None:
        dock.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        dock.customContextMenuRequested.connect(
            lambda position, panel_key=key, panel_dock=dock: self._show_panel_context_menu(
                panel_key,
                panel_dock.mapToGlobal(position),
            )
        )

    def _show_panel_context_menu(self, key: str, global_position) -> None:
        panel = self.panels.get(key)
        if panel is None:
            return
        menu = QMenu(self)
        close_action = menu.addAction(f"Close {panel['title']}")
        close_action.triggered.connect(lambda _checked=False, panel_key=key: self._close_panel_from_context(panel_key))
        menu.exec(global_position)

    def _close_panel_from_context(self, key: str) -> None:
        self._set_panel_visible(key, False)
        self._sync_panel_action(key, False)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        save_gsf = QAction("Save GSF...", self)
        save_gsf.triggered.connect(self.storage_module.save_gsf_bundle)
        file_menu.addAction(save_gsf)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        settings_menu = menu_bar.addMenu("Settings")
        reload_modes = QAction("Reload Scan Modes", self)
        reload_modes.triggered.connect(self.scan_module.reload_scan_modes)
        settings_menu.addAction(reload_modes)
        load_devices = QAction("Load Device Config", self)
        load_devices.triggered.connect(self.device_module.load_config)
        settings_menu.addAction(load_devices)
        refresh_metadata = QAction("Refresh Parameter Tree", self)
        refresh_metadata.triggered.connect(self.metadata_module.refresh)
        settings_menu.addAction(refresh_metadata)

        view_menu = menu_bar.addMenu("View")
        self.panel_actions = {}
        for key, panel in self.panels.items():
            action = QAction(str(panel["title"]), self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, panel_key=key: self._set_panel_visible(panel_key, checked))
            view_menu.addAction(action)
            self.panel_actions[key] = action

        view_menu.addSeparator()
        show_all = QAction("Show All Panels", self)
        show_all.triggered.connect(self._show_all_panels)
        view_menu.addAction(show_all)
        restore_default = QAction("Restore Default Layout", self)
        restore_default.triggered.connect(self._restore_default_layout)
        view_menu.addAction(restore_default)
        view_menu.addSeparator()
        save_layout = QAction("Save Layout As...", self)
        save_layout.triggered.connect(self._save_layout_as)
        view_menu.addAction(save_layout)
        load_layout = QAction("Load Layout...", self)
        load_layout.triggered.connect(self._load_layout)
        view_menu.addAction(load_layout)

        help_menu = menu_bar.addMenu("Help")
        config_action = QAction("Show Scan Modes Config Path", self)
        config_action.triggered.connect(self._show_config_path)
        help_menu.addAction(config_action)
        architecture_action = QAction("Architecture Summary", self)
        architecture_action.triggered.connect(self._show_architecture_summary)
        help_menu.addAction(architecture_action)
        about_action = QAction("About AFM Scan Control", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _parameter_box(self) -> QGroupBox:
        return self.scan_module.widget

    def _control_box(self) -> QGroupBox:
        return build_controls_panel(self)

    def _status_box(self) -> QGroupBox:
        return build_status_panel(self)

    def _device_manager_box(self) -> QGroupBox:
        return self.device_module.widget

    def _stage_map_box(self) -> QWidget:
        return self.stage_module.widget

    def _lockin_box(self) -> QWidget:
        return self.lockin_module.widget

    def _spectroscopy_box(self) -> QWidget:
        return self.spectroscopy_module.widget

    def _metadata_box(self) -> QGroupBox:
        return self.metadata_module.widget

    def _log_box(self) -> QGroupBox:
        return build_command_log_panel(self)

    def _connect(self) -> None:
        self.scan_up.clicked.connect(lambda: self.scan_module.start(ScanDirection.UP))
        self.scan_down.clicked.connect(lambda: self.scan_module.start(ScanDirection.DOWN))
        self.pause.clicked.connect(self.controller.pause)
        self.resume.clicked.connect(self.controller.resume)
        self.stop.clicked.connect(self.controller.stop)
        self.toggle_metadata.clicked.connect(self._toggle_metadata)
        self.controller.image_changed.connect(
            lambda images: self.channel_images_module.show_image(
                images,
                refresh_all=self.controller.current_line_index < 0,
            )
        )
        self.controller.line_changed.connect(self.channel_images_module.show_line)
        self.controller.probe_position_changed.connect(self.channel_images_module.show_probe_position)
        self.controller.log_message.connect(self._append_log)
        self.controller.state_changed.connect(self._on_controller_state_changed)
        self.controller.scan_progress_changed.connect(self._show_scan_progress)
        self.controller.runtime_parameters_changed.connect(lambda _: self.metadata_module.refresh())

    def _on_controller_state_changed(self, state: str) -> None:
        self.state_label.setText(state)
        self._update_scan_button_state(state)
        self.device_module.set_hardware_locked(state in {"Scanning", "Paused"})
        if state == "Paused":
            self.storage_module.auto_save("pause")
        if state == "Idle":
            self.storage_module.auto_save("finish")
            self.metadata_module.refresh()

    def _update_scan_button_state(self, state: str) -> None:
        scanning = state == "Scanning"
        paused = state == "Paused"
        idle = not scanning and not paused

        self.scan_up.setEnabled(idle)
        self.scan_down.setEnabled(idle)
        self.pause.setEnabled(scanning)
        self.resume.setEnabled(paused)
        self.stop.setEnabled(scanning or paused)
        self.save_gsf.setEnabled(idle or paused)
        self.auto_save_browse.setEnabled(idle)
        self.auto_save_dir.setEnabled(idle)

    def _show_scan_progress(
        self,
        line_index: int,
        total_lines: int,
        pixel_index: int,
        total_pixels: int,
        scan_pass: str,
    ) -> None:
        if scan_pass == "idle":
            self.scan_progress_label.setText("Line 0/0, Pixel 0/0")
            return
        self.scan_progress_label.setText(
            f"{scan_pass} line {line_index + 1}/{total_lines}, pixel {pixel_index + 1}/{total_pixels}"
        )

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _scan_extra_metadata(self) -> dict[str, object]:
        return {
            **self.storage_module.metadata_paths(),
            **self.device_module.metadata_paths(),
            "stage": self.stage_module.snapshot(),
            "lockin": self.lockin_module.snapshot(),
        }

    def _scan_acquisition_callback(self):
        adapter = self.device_manager.adapter_for_function("lockin")
        if adapter is None or not hasattr(adapter, "read_demod"):
            return None
        return _LockinScanAcquisition(adapter)

    def _toggle_metadata(self) -> None:
        visible = self.metadata_dock.isHidden()
        self._set_panel_visible("metadata", visible)
        self._sync_panel_action("metadata", visible)
        self.toggle_metadata.setText("Hide Metadata" if visible else "Show Metadata")

    def _set_panel_visible(self, key: str, visible: bool, *, allow_floating: bool = True) -> None:
        panel = self.panels[key]
        dock = panel["dock"]
        if not isinstance(dock, Dock):
            return

        if visible:
            if getattr(dock, "_container", None) is None:
                relative_key = panel["relative"]
                relative = self.panels[relative_key]["dock"] if relative_key else None
                self.dock_area.addDock(dock, str(panel["position"]), relative)
            dock.setHidden(False)
            if allow_floating and panel.get("open_floating"):
                dock.float()
                self._track_floating_panel(key)
        else:
            if panel.get("open_floating") and self._panel_is_floating(key):
                self._close_floating_panel(key)
            else:
                dock.setHidden(True)
        if key == "metadata":
            self.toggle_metadata.setText("Hide Metadata" if visible else "Show Metadata")

    def _panel_is_floating(self, key: str) -> bool:
        dock = self.panels[key]["dock"]
        return isinstance(dock, Dock) and getattr(dock, "area", None) not in (None, self.dock_area)

    def _track_floating_panel(self, key: str) -> None:
        dock = self.panels[key]["dock"]
        area = getattr(dock, "area", None)
        if not isinstance(dock, Dock) or area in (None, self.dock_area):
            return
        window = getattr(area, "win", None)
        if not isinstance(window, QWidget):
            window = area.window()
        if not isinstance(window, QWidget) or window in self._floating_panel_windows:
            return
        self._floating_panel_windows[window] = key
        window.installEventFilter(self)
        window.destroyed.connect(lambda _obj=None, watched=window: self._floating_panel_windows.pop(watched, None))

    def _close_floating_panel(self, key: str) -> None:
        dock = self.panels[key]["dock"]
        area = getattr(dock, "area", None)
        window = getattr(area, "win", None) if area is not None else None
        if not isinstance(window, QWidget) and area is not None:
            window = area.window()
        if isinstance(dock, Dock) and getattr(dock, "_container", None) is not None:
            dock.close()
        self._sync_panel_action(key, False)
        if isinstance(window, QWidget):
            window.close()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Close and isinstance(watched, QWidget):
            key = self._floating_panel_windows.pop(watched, None)
            if key is not None:
                dock = self.panels[key]["dock"]
                if isinstance(dock, Dock) and self._panel_is_floating(key):
                    dock.close()
                self._sync_panel_action(key, False)
        return super().eventFilter(watched, event)

    def _show_all_panels(self, *, allow_floating: bool = True) -> None:
        for key in self.panels:
            self._set_panel_visible(key, True, allow_floating=allow_floating)
            self._sync_panel_action(key, True)

    def _restore_default_layout(self) -> None:
        try:
            self._apply_startup_layout()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._append_log(f"Could not restore startup layout: {exc}")
            self._restore_code_default_layout()
            return
        self._append_log(f"Restored startup layout: {self._startup_layout_path()}")

    def _restore_code_default_layout(self) -> None:
        self._show_all_panels(allow_floating=False)
        self.dock_area.restoreState(self.default_layout_state, missing="ignore")
        self._show_all_panels(allow_floating=False)
        self._append_log("Restored fallback layout")

    def _save_layout_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Layout",
            str(self._layout_dir() / "layout.json"),
            "AFM Layout (*.json)",
        )
        if not path:
            return
        payload = {
            "schema": "afm_gui.layout.v1",
            "dock_state": self.dock_area.saveState(),
            "visible_panels": {
                key: self._panel_is_visible(key)
                for key in self.panels
            },
        }
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._append_log(f"Saved layout: {path_obj}")

    def _load_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Layout",
            str(self._layout_dir()),
            "AFM Layout (*.json)",
        )
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            self._apply_layout_payload(payload)
        except ValueError as exc:
            QMessageBox.warning(self, "Load Layout", str(exc))
            return
        self._append_log(f"Loaded layout: {path}")

    def _load_startup_layout(self) -> None:
        path = self._startup_layout_path()
        if not path.exists():
            self._append_log(f"Startup layout not found: {path}")
            return
        try:
            self._apply_startup_layout()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._append_log(f"Could not load startup layout {path}: {exc}")
            self._restore_code_default_layout()
            return
        self._append_log(f"Loaded startup layout: {path}")

    def _apply_startup_layout(self) -> None:
        path = self._startup_layout_path()
        if not path.exists():
            raise OSError(f"Startup layout not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._apply_layout_payload(payload)

    def _apply_layout_payload(self, payload: dict[str, object]) -> None:
        if payload.get("schema") != "afm_gui.layout.v1":
            raise ValueError("This is not an AFM GUI layout file.")
        self._show_all_panels(allow_floating=False)
        dock_state = payload.get("dock_state")
        if not isinstance(dock_state, dict):
            raise ValueError("Layout file is missing dock_state.")
        self.dock_area.restoreState(dock_state, missing="ignore")
        visible_panels = payload.get("visible_panels", {})
        if not isinstance(visible_panels, dict):
            visible_panels = {}
        for key, panel in self.panels.items():
            visible = bool(visible_panels.get(key, panel.get("default_visible", True)))
            self._set_panel_visible(key, visible, allow_floating=False)
            self._sync_panel_action(key, visible)

    def _panel_is_visible(self, key: str) -> bool:
        dock = self.panels[key]["dock"]
        return isinstance(dock, Dock) and getattr(dock, "_container", None) is not None and not dock.isHidden()

    @classmethod
    def _startup_layout_path(cls) -> Path:
        return Path(str(resources.files("afm_gui.config").joinpath(cls.STARTUP_LAYOUT)))

    @staticmethod
    def _layout_dir() -> Path:
        return Path.home() / ".afm_gui" / "layouts"

    def _sync_panel_action(self, key: str, visible: bool) -> None:
        action = self.panel_actions.get(key)
        if action is None:
            return
        action.blockSignals(True)
        action.setChecked(visible)
        action.blockSignals(False)
        if key == "metadata":
            self.toggle_metadata.setText("Hide Metadata" if visible else "Show Metadata")

    def _show_config_path(self) -> None:
        QMessageBox.information(
            self,
            "Scan Modes Config",
            "Bundled scan mode configuration:\n"
            "afm_gui/config/scan_modes.yaml\n\n"
            "CLI can load an alternate file with --modes-config.",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About AFM Scan Control",
            "AFM Scan Control\n\n"
            "PyQt6 + pyqtgraph + QCoDeS prototype for AFM scan control, "
            "multi-channel recording, metadata, and Gwyddion export.",
        )

    def closeEvent(self, event: QEvent) -> None:
        self.controller.stop()
        if hasattr(self.device, "wait_for_finished"):
            self.device.wait_for_finished(5000)
        if hasattr(self.spectroscopy_module.controller, "stop"):
            self.spectroscopy_module.controller.stop()
        self.device_module.wait_for_connections(5000)
        self.device_module.set_hardware_locked(False)
        self.device_manager.disconnect_all()
        event.accept()

    def _show_architecture_summary(self) -> None:
        with resources.files("afm_gui.docs").joinpath("architecture_summary.md").open(
            "r",
            encoding="utf-8",
        ) as file:
            text = file.read()
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Architecture Summary")
        dialog.setText("AFM Scan Control Architecture")
        dialog.setDetailedText(text)
        dialog.exec()

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        return widget


class _LockinScanAcquisition:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter
        self._lock = threading.Lock()

    def __call__(self, channels: tuple[str, ...]) -> dict[str, float]:
        with self._lock:
            sample = self._adapter.read_demod()
        mapped = {
            "topography": sample.get("r_v"),
            "error": sample.get("x_v"),
            "amplitude": sample.get("r_v"),
            "phase": sample.get("phase_deg"),
            "current": sample.get("auxin0_v"),
            "didv": sample.get("auxin1_v"),
            "lockin_x": sample.get("x_v"),
            "lockin_y": sample.get("y_v"),
            "lockin_r": sample.get("r_v"),
            "lockin_phase": sample.get("phase_deg"),
        }
        return {
            channel: float(value)
            for channel, value in mapped.items()
            if channel in channels and value is not None
        }
