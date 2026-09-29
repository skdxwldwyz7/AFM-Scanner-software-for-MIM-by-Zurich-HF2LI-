from __future__ import annotations

from importlib import resources
from pathlib import Path

from pyqtgraph.dockarea import Dock, DockArea
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from afm_gui.core.scan_config import ScanDirection
from afm_gui.core.scan_controller import ScanController
from afm_gui.core.lockin_acquisition import LockinScanAcquisition, ZeroScanAcquisition
from afm_gui.core.fm_afm import FMAcquisition
from afm_gui.device.scan_device import AdapterScannerDevice
from afm_gui.ui.modules.approach import ApproachModule
from afm_gui.ui.modules.channel_images import ChannelImagesModule
from afm_gui.ui.modules.device import DeviceModule
from afm_gui.ui.modules.layout import WindowLayoutModule
from afm_gui.ui.modules.lockin import LockInModule
from afm_gui.ui.modules.metadata import MetadataModule
from afm_gui.ui.modules.scan import ScanModule
from afm_gui.ui.modules.scan_sequence import ScanSequenceModule
from afm_gui.ui.modules.spectroscopy import SpectroscopyModule
from afm_gui.ui.modules.stage import StageModule
from afm_gui.ui.modules.storage import StorageModule
from afm_gui.ui.modules.fm_afm import FMAFMModule
from afm_gui.ui.panels.command_log import build_command_log_panel
from afm_gui.ui.panels.controls import build_controls_panel
from afm_gui.ui.panels.status import build_status_panel


class MainWindow(QMainWindow):
    STARTUP_LAYOUT = "layout_fm_afm.json"

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
        self.scan_module.set_channel_changed_callback(self.channel_images_module.sync_scan_channels)
        self.stage_module = StageModule(self._append_log, self.device_manager, self)
        self.lockin_module = LockInModule(self._append_log, self.device_manager, self)
        self.fm_afm_module = FMAFMModule(self.device_manager, self._append_log, self)
        self.approach_module = ApproachModule(self._append_log, self.device_manager, self)
        self.storage_module = StorageModule(
            self.controller,
            lambda: self.scan_module.current_mode,
            self._scan_extra_metadata,
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
        self.scan_sequence_module = ScanSequenceModule(
            self.controller,
            lambda direction: self.scan_module.start(direction),
            self._append_log,
            self,
        )
        self.stage_controller = self.stage_module.controller
        self.lockin_controllers = self.lockin_module.controllers
        self.lockin_controller = self.lockin_module.primary_controller
        self._last_scan_mode = None
        self.scan_module.set_mode_changed_callback(self._on_scan_mode_changed)
        self.scan_module.set_start_guard(self._validate_scan_start)
        self.panel_actions: dict[str, QAction] = {}
        self.panels: dict[str, dict[str, object]] = {}
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
        self.device_dock = Dock("Device Manager", size=(900, 520))
        self.stage_dock = Dock("Stage Map", size=(360, 430))
        self.fm_afm_dock = Dock("FM-AFM Monitor", size=(520, 780))
        self.lockin_dock = Dock("Lock-in Amplifier", size=(760, 420))
        self.approach_dock = Dock("Approach", size=(760, 520))
        self.spectroscopy_dock = Dock("Spectroscopy", size=(980, 560))
        self.status_dock = Dock("State", size=(820, 160))
        self.metadata_dock = Dock("Parameter Tree", size=(360, 280))
        self.log_dock = Dock("Command Log", size=(360, 180))

        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_scroll.setWidget(self.image_grid_widget)
        self.image_dock.addWidget(image_scroll)
        self.line_dock.addWidget(self.line_plot)
        self.parameter_dock.addWidget(self._parameter_box())
        self.control_dock.addWidget(self._control_box())
        self.device_dock.addWidget(self._device_manager_box())
        self.stage_dock.addWidget(self._stage_map_box())
        self.fm_afm_dock.addWidget(self.fm_afm_module.widget)
        self.lockin_dock.addWidget(self._lockin_box())
        self.approach_dock.addWidget(self._approach_box())
        self.spectroscopy_dock.addWidget(self._spectroscopy_box())
        self.status_dock.addWidget(self._status_box())
        self.metadata_dock.addWidget(self._metadata_box())
        self.log_dock.addWidget(self._log_box())
        self.layout_module = WindowLayoutModule(
            self,
            self.dock_area,
            self._append_log,
            startup_layout=self.STARTUP_LAYOUT,
            toggle_metadata=self.toggle_metadata,
        )

        self.dock_area.addDock(self.stage_dock, "left")
        self.dock_area.addDock(self.fm_afm_dock, "left", self.stage_dock)
        self.dock_area.addDock(self.parameter_dock, "right", self.stage_dock)
        self.dock_area.addDock(self.image_dock, "right", self.parameter_dock)
        self.dock_area.addDock(self.control_dock, "bottom", self.stage_dock)
        self.dock_area.addDock(self.metadata_dock, "bottom", self.control_dock)
        self.dock_area.addDock(self.log_dock, "bottom", self.metadata_dock)
        self.dock_area.addDock(self.line_dock, "bottom", self.image_dock)
        self.dock_area.addDock(self.status_dock, "bottom", self.line_dock)
        self.dock_area.addDock(self.lockin_dock, "bottom", self.status_dock)
        self.dock_area.addDock(self.device_dock, "bottom", self.lockin_dock)
        self.dock_area.addDock(self.approach_dock, "bottom", self.lockin_dock)
        self._register_panels()
        self._build_menus()
        self.default_layout_state = self.dock_area.saveState()
        self.layout_module.default_layout_state = self.default_layout_state
        self._load_startup_layout()

        self.channel_images_module.bind_status_controls(
            self.display_count,
            self.line_channel_selector,
            self.line_pass_selector,
            self.position_label,
        )
        self.lockin_module.set_route_changed_callback(self.channel_images_module.set_channel_aliases)
        self.scan_module.apply_scan_mode(self.scan_module.current_mode)
        self.storage_module.bind_controls(
            self.save_gsf,
            self.auto_save_enabled,
            self.auto_save_dir,
            self.auto_save_browse,
        )
        self.scan_sequence_module.bind_controls(
            self.scan_up,
            self.scan_down,
            self.stop,
            self.scan_repeat_mode,
            self.scan_repeat_count,
        )
        self.metadata_module.refresh()
        self._update_scan_button_state("Idle")

    def _register_panels(self) -> None:
        self.panels = {
            "fm_afm": {"title": "FM-AFM Monitor", "dock": self.fm_afm_dock, "position": "left", "relative": None},
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
            "approach": {
                "title": "Approach",
                "dock": self.approach_dock,
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
        self.layout_module.register_panels(self.panels)

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
        self.layout_module.build_view_menu(view_menu)
        self.panel_actions = self.layout_module.panel_actions

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

    def _approach_box(self) -> QWidget:
        return self.approach_module.widget

    def _spectroscopy_box(self) -> QWidget:
        return self.spectroscopy_module.widget

    def _metadata_box(self) -> QGroupBox:
        return self.metadata_module.widget

    def _log_box(self) -> QGroupBox:
        return build_command_log_panel(self)

    def _connect(self) -> None:
        self.pause.clicked.connect(self.controller.pause)
        self.resume.clicked.connect(self.controller.resume)
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
        self.approach_module.controller.state_changed.connect(self._on_approach_state_changed)
        self.controller.scan_failed.connect(self.scan_sequence_module.cancel_on_error)
        self.fm_afm_module.activity_changed.connect(self._sync_hardware_activity)

    def _on_controller_state_changed(self, state: str) -> None:
        self.state_label.setText(state)
        error = self.controller.parameter_tree.data.get("runtime", {}).get("error") if state == "Idle" else None
        self.state_label.setToolTip(str(error or ""))
        if error:
            self.state_label.setText("Stopped (error — hover for details / see Command Log)")
        self.state_label.setWordWrap(True)
        self._update_scan_button_state(state)
        self.fm_afm_module.set_scan_active(state in {"Scanning", "Paused"})
        self.scan_module.set_running(state in {"Scanning", "Paused"})
        self._sync_hardware_activity()
        if state == "Paused":
            self.storage_module.auto_save("pause")
        if state == "Idle":
            self.storage_module.write_scan_report()
            self.storage_module.auto_save("finish")
            self.metadata_module.refresh()
            self.scan_sequence_module.continue_if_needed()

    def _on_approach_state_changed(self, state: str) -> None:
        self.fm_afm_module.set_external_motion(state in {"Approaching", "Paused"})
        self._sync_hardware_activity()

    def _sync_hardware_activity(self) -> None:
        scan = self.controller.is_running or self.controller.is_paused
        approach = self.approach_module.controller.is_running or self.approach_module.controller.is_paused
        self.device_module.set_hardware_locked(scan or approach or self.fm_afm_module.busy)
        if not scan:
            self.scan_up.setEnabled(not approach and not self.fm_afm_module.moving)
            self.scan_down.setEnabled(not approach and not self.fm_afm_module.moving)

    def _validate_scan_start(self) -> None:
        if self.fm_afm_module.moving or self.approach_module.controller.is_running:
            raise RuntimeError("Stop manual XY/approach motion before scanning")
        if self.device_module._connection_busy:
            raise RuntimeError("Wait for the device connection to finish")

    def _on_scan_mode_changed(self, mode) -> None:
        self.channel_images_module.reset_for_mode(mode)
        if mode.name == "fm_afm" and self._last_scan_mode != "fm_afm":
            self.scan_module.xc.setValue(2.5)
            self.scan_module.yc.setValue(2.5)
            self.scan_module.width.setValue(0.1)
            self.scan_module.height.setValue(0.1)
            self.scan_module.linear.setValue(0.05)
        self._last_scan_mode = mode.name

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
        self.scan_sequence_module.update_controls_enabled(idle)

    def _on_scan_repeat_mode_changed(self) -> None:
        self.scan_sequence_module.on_repeat_mode_changed()

    def _start_scan_sequence(self, direction: int) -> None:
        self.scan_sequence_module.start(direction)

    def _start_next_scan_in_sequence(self) -> None:
        self.scan_sequence_module.start_next()

    def _continue_scan_sequence(self) -> None:
        self.scan_sequence_module.continue_if_needed()

    def _stop_scan_sequence(self) -> None:
        self.scan_sequence_module.stop()

    def _log_scan_sequence_status(self, direction: int) -> None:
        self.scan_sequence_module._log_scan_status(direction)

    @property
    def _scan_sequence_active(self) -> bool:
        return self.scan_sequence_module.active

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
            "approach": self.approach_module.snapshot(),
            "fm_afm": self.fm_afm_module.snapshot(),
        }

    def _scan_acquisition_callback(self):
        if self.scan_module.current_mode.name == "fm_afm":
            adapter = self.device_manager.adapter_for_function("scan_scanner")
            if adapter is None or not hasattr(adapter, "read_fm_snapshot"):
                raise RuntimeError("FM-AFM scanner must be the connected HF2LI")
            return FMAcquisition(adapter)
        adapters = self.lockin_module.scan_adapters()
        if not adapters:
            return ZeroScanAcquisition()
        return LockinScanAcquisition(adapters, self.lockin_module.scan_routing())

    def _toggle_metadata(self) -> None:
        visible = self.metadata_dock.isHidden()
        self._set_panel_visible("metadata", visible)
        self._sync_panel_action("metadata", visible)
        self.toggle_metadata.setText("Hide Metadata" if visible else "Show Metadata")

    def _set_panel_visible(self, key: str, visible: bool, *, allow_floating: bool = True) -> None:
        self.layout_module.set_panel_visible(key, visible, allow_floating=allow_floating)

    def _panel_is_floating(self, key: str) -> bool:
        return self.layout_module.panel_is_floating(key)

    def _track_floating_panel(self, key: str) -> None:
        self.layout_module.track_floating_panel(key)

    def _close_floating_panel(self, key: str) -> None:
        self.layout_module.close_floating_panel(key)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        self.layout_module.event_filter(watched, event)
        return super().eventFilter(watched, event)

    def _show_all_panels(self, *, allow_floating: bool = True) -> None:
        self.layout_module.show_all_panels(allow_floating=allow_floating)

    def _restore_default_layout(self) -> None:
        self.layout_module.restore_default_layout()

    def _restore_code_default_layout(self) -> None:
        self.layout_module.restore_code_default_layout()

    def _save_layout_as(self) -> None:
        self.layout_module.save_layout_as()

    def _load_layout(self) -> None:
        self.layout_module.load_layout()

    def _load_startup_layout(self) -> None:
        self.layout_module.load_startup_layout()

    def _apply_startup_layout(self) -> None:
        self.layout_module.apply_startup_layout()

    def _apply_layout_payload(self, payload: dict[str, object]) -> None:
        self.layout_module.apply_layout_payload(payload)

    def _panel_is_visible(self, key: str) -> bool:
        return self.layout_module.panel_is_visible(key)

    @classmethod
    def _startup_layout_path(cls) -> Path:
        return Path(str(resources.files("afm_gui.config").joinpath(cls.STARTUP_LAYOUT)))

    @staticmethod
    def _layout_dir():
        return WindowLayoutModule.layout_dir()

    def _sync_panel_action(self, key: str, visible: bool) -> None:
        self.layout_module.sync_panel_action(key, visible)

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
        self.scan_sequence_module.stop()
        if hasattr(self.device, "wait_for_finished"):
            if not self.device.wait_for_finished(5000):
                self._append_log("Waiting for XY scan to stop; close again after hardware I/O returns")
                event.ignore()
                return
        if not self.fm_afm_module.shutdown(5000):
            self._append_log("Waiting for HF2 monitor/XY worker to stop; close again after hardware I/O returns")
            event.ignore()
            return
        if hasattr(self.spectroscopy_module.controller, "stop"):
            self.spectroscopy_module.controller.stop()
        self.approach_module.controller.abort()
        if not self.device_module.wait_for_connections(5000):
            event.ignore()
            return
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
