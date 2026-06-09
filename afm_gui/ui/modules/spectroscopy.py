from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QRectF, Qt
from PyQt6.QtWidgets import QFileDialog, QDoubleSpinBox, QSpinBox

from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.spectroscopy_config import SpectroscopyConfig
from afm_gui.core.spectroscopy_controller import SpectroscopyController
from afm_gui.data.gsf import safe_filename, write_gsf
from afm_gui.ui.panels.spectroscopy import axis_metadata, build_spectroscopy_panel


class SpectroscopyModule(QObject):
    MEMORY_WARNING_BYTES = 512 * 1024 * 1024

    def __init__(
        self,
        scan_config_provider: Callable[[], ScanConfig],
        extra_metadata_provider: Callable[[], dict[str, object]],
        log_callback: Callable[[str], None],
        dialog_parent,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = SpectroscopyController(self)
        self._scan_config_provider = scan_config_provider
        self._extra_metadata_provider = extra_metadata_provider
        self._log_callback = log_callback
        self._dialog_parent = dialog_parent
        self.widget = build_spectroscopy_panel(self)
        self.latest_spectra: dict[str, np.ndarray] = {}
        self.latest_slice_maps: dict[str, dict[str, np.ndarray]] = {}
        self._connect()
        self._sync_channels()
        self._sync_axis_units()
        self.update_memory_estimate()
        self._update_button_state("Idle")

    def config(self) -> SpectroscopyConfig:
        axis_name, axis_label, axis_unit = axis_metadata(self.axis_type.currentText())
        channels = []
        if self.current_channel.isChecked():
            channels.append("current")
        if self.didv_channel.isChecked():
            channels.append("didv")
        if self.amplitude_channel.isChecked():
            channels.append("amplitude")
        if self.phase_channel.isChecked():
            channels.append("phase")
        if not channels:
            channels = ["current"]
        scan_passes = []
        if self.trace_pass.isChecked():
            scan_passes.append("trace")
        if self.retrace_pass.isChecked():
            scan_passes.append("retrace")
        if not scan_passes:
            scan_passes = ["trace"]
        return SpectroscopyConfig(
            axis_name=axis_name,
            axis_label=axis_label,
            axis_unit=axis_unit,
            start=self.start.value(),
            stop=self.stop.value(),
            points=self.points.value(),
            dwell=self.dwell.value(),
            settle=self.settle.value(),
            channels=tuple(channels),
            scan_passes=tuple(scan_passes),
        )

    def start_map(self) -> None:
        scan_config = self._scan_config_provider()
        spec_config = self.config()
        estimate = self.estimated_data_bytes(scan_config, spec_config)
        if estimate >= self.MEMORY_WARNING_BYTES:
            self._log_callback(
                "Large spectroscopy map estimate: "
                f"{self.format_bytes(estimate)} raw cube data before GUI/export overhead"
            )
        self.latest_spectra = {}
        self.latest_slice_maps = {}
        self.slice_slider.setRange(0, spec_config.points - 1)
        self.controller.start(scan_config, spec_config, ScanDirection.UP)
        self._sync_channels()
        self._refresh_slice_label()
        self._update_button_state("Spectroscopy")

    def save_bundle(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self._dialog_parent,
            "Save Spectroscopy Bundle",
            str(Path.home() / "afm_spectroscopy.afmspm.h5"),
            "AFM Spectroscopy Bundle (*.afmspm.h5);;HDF5 (*.h5)",
        )
        if not path:
            return
        self.controller.export_bundle(path, metadata=self._extra_metadata_provider())

    def save_slice_gsf(self) -> None:
        scan_pass = self.pass_selector.currentText()
        channel = self.channel_selector.currentText()
        if scan_pass not in self.latest_slice_maps or channel not in self.latest_slice_maps[scan_pass]:
            self._log_callback("No spectroscopy slice is available to export")
            return

        axis = self.controller.spectrum_axis
        slice_index = min(self.slice_slider.value(), len(axis) - 1)
        axis_value = axis[slice_index]
        axis_name, axis_label, axis_unit = axis_metadata(self.axis_type.currentText())
        default_name = (
            f"afm_{safe_filename(channel)}_{safe_filename(axis_name)}_"
            f"{safe_filename(f'{axis_value:.4g}{axis_unit}')}.gsf"
        )
        path, _ = QFileDialog.getSaveFileName(
            self._dialog_parent,
            "Save Spectroscopy Slice",
            str(Path.home() / default_name),
            "Gwyddion Simple Field (*.gsf)",
        )
        if not path:
            return

        scan_config = self.controller.scan_config
        x_real_m = self._gsf_lateral_size_m(scan_config.width, scan_config.xy_unit)
        y_real_m = self._gsf_lateral_size_m(scan_config.height, scan_config.xy_unit)
        write_gsf(
            path,
            self.latest_slice_maps[scan_pass][channel],
            x_real_m=x_real_m,
            y_real_m=y_real_m,
            z_unit=self.channel_unit(channel),
            title=f"AFM {channel} {axis_label} slice",
            metadata={
                "Channel": channel,
                "ScanPass": scan_pass,
                "XYUnit": scan_config.xy_unit,
                "XCenter": f"{scan_config.xc:.12g}",
                "YCenter": f"{scan_config.yc:.12g}",
                "XWidth": f"{scan_config.width:.12g}",
                "YHeight": f"{scan_config.height:.12g}",
                "SpectrumAxis": axis_name,
                "SpectrumAxisLabel": axis_label,
                "SpectrumAxisUnit": axis_unit,
                "SpectrumIndex": slice_index,
                "SpectrumValue": f"{axis_value:.12g}",
            },
        )
        self._log_callback(f"Saved spectroscopy slice GSF: {path}")

    def show_point(self, line_index: int, pixel_index: int, data: object) -> None:
        self.latest_spectra = {channel: np.asarray(values, dtype=float) for channel, values in dict(data).items()}
        self.progress_label.setText(f"Line {line_index + 1}, Pixel {pixel_index + 1}")
        self._sync_channels()
        self.refresh_spectrum_plot()

    def show_slice_maps(self, maps: object) -> None:
        self.latest_slice_maps = {
            scan_pass: {
                channel: np.asarray(values, dtype=float)
                for channel, values in dict(channels).items()
            }
            for scan_pass, channels in dict(maps).items()
        }
        self.save_slice_button.setEnabled(bool(self.latest_slice_maps))
        self.refresh_slice_map()

    def refresh_spectrum_plot(self, *_args: object) -> None:
        channel = self.channel_selector.currentText()
        if channel not in self.latest_spectra:
            return
        self.spectrum_curve.setData(self.controller.spectrum_axis, self.latest_spectra[channel])

    def refresh_slice_map(self, *_args: object) -> None:
        scan_pass = self.pass_selector.currentText()
        channel = self.channel_selector.currentText()
        if scan_pass not in self.latest_slice_maps or channel not in self.latest_slice_maps[scan_pass]:
            return
        scan_config = self.controller.scan_config
        image = np.nan_to_num(self.latest_slice_maps[scan_pass][channel], nan=0.0)
        self.slice_plot.setLabel("bottom", "X", units=scan_config.xy_unit)
        self.slice_plot.setLabel("left", "Y", units=scan_config.xy_unit)
        self.slice_image.setRect(
            QRectF(
                scan_config.xc - scan_config.width / 2.0,
                scan_config.yc - scan_config.height / 2.0,
                scan_config.width,
                scan_config.height,
            )
        )
        self.slice_image.setImage(image.T, autoLevels=True)

    def _connect(self) -> None:
        self.start_button.clicked.connect(self.start_map)
        self.pause_button.clicked.connect(self.controller.pause)
        self.resume_button.clicked.connect(self.controller.resume)
        self.stop_button.clicked.connect(self.controller.stop)
        self.save_button.clicked.connect(self.save_bundle)
        self.save_slice_button.clicked.connect(self.save_slice_gsf)
        self.axis_type.currentTextChanged.connect(self._sync_axis_units)
        self.points.valueChanged.connect(lambda value: self.slice_slider.setRange(0, value - 1))
        self.slice_slider.valueChanged.connect(self._on_slice_changed)
        self.channel_selector.currentTextChanged.connect(self.refresh_spectrum_plot)
        self.channel_selector.currentTextChanged.connect(self.refresh_slice_map)
        self.pass_selector.currentTextChanged.connect(self.refresh_slice_map)
        self.controller.spectrum_point_changed.connect(self.show_point)
        self.controller.spectrum_slice_changed.connect(self.show_slice_maps)
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.log_message.connect(self._log_callback)
        self.controller.export_finished.connect(lambda path: self._log_callback(f"Spectroscopy export finished: {path}"))
        for widget in (
            self.start,
            self.stop,
            self.points,
            self.dwell,
            self.settle,
            self.trace_pass,
            self.retrace_pass,
            self.current_channel,
            self.didv_channel,
            self.amplitude_channel,
            self.phase_channel,
        ):
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.update_memory_estimate)
            if hasattr(widget, "toggled"):
                widget.toggled.connect(self._on_selection_changed)

    def _on_selection_changed(self, *_args: object) -> None:
        self._sync_channels()
        self.update_memory_estimate()

    def _on_state_changed(self, state: str) -> None:
        self.progress_label.setText(state)
        self._update_button_state(state)

    def _on_slice_changed(self, value: int) -> None:
        self.controller.set_selected_slice_index(value)
        self._refresh_slice_label()

    def _refresh_slice_label(self) -> None:
        axis = self.controller.spectrum_axis
        index = min(self.slice_slider.value(), len(axis) - 1)
        _, _, unit = axis_metadata(self.axis_type.currentText())
        self.slice_label.setText(f"{axis[index]:.4g} {unit}".strip())

    def _sync_axis_units(self, *_args: object) -> None:
        _, label, unit = axis_metadata(self.axis_type.currentText())
        suffix = f" {unit}" if unit else ""
        self.start.setSuffix(suffix)
        self.stop.setSuffix(suffix)
        self.spectrum_plot.setLabel("bottom", label, units=unit)
        self._refresh_slice_label()
        self.update_memory_estimate()

    def _sync_channels(self) -> None:
        channels = list(self.config().channels)
        current = self.channel_selector.currentText()
        if channels == [self.channel_selector.itemText(i) for i in range(self.channel_selector.count())]:
            return
        self.channel_selector.blockSignals(True)
        self.channel_selector.clear()
        self.channel_selector.addItems(channels)
        if current in channels:
            self.channel_selector.setCurrentText(current)
        self.channel_selector.blockSignals(False)

    def update_memory_estimate(self, *_args: object) -> None:
        estimate = self.estimated_data_bytes(self._scan_config_provider(), self.config())
        prefix = "Memory"
        if estimate >= self.MEMORY_WARNING_BYTES:
            prefix = "Memory warning"
        self.memory_label.setText(f"{prefix}: {self.format_bytes(estimate)} raw")

    def estimated_data_bytes(self, scan_config: ScanConfig, config: SpectroscopyConfig) -> int:
        cube_values = (
            scan_config.lines
            * scan_config.pixels
            * max(2, config.points)
            * max(1, len(config.channels))
            * max(1, len(config.scan_passes))
        )
        topo_values = scan_config.lines * scan_config.pixels * max(1, len(config.scan_passes))
        return int((cube_values + topo_values) * np.dtype(float).itemsize)

    @staticmethod
    def format_bytes(byte_count: int) -> str:
        value = float(byte_count)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024.0 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024.0
        return f"{value:.1f} TB"

    @staticmethod
    def channel_unit(channel: str) -> str:
        return {
            "current": "A",
            "didv": "S",
            "amplitude": "V",
            "phase": "deg",
            "topography": "nm",
        }.get(channel, "")

    @staticmethod
    def _gsf_lateral_size_m(value: float, unit: str) -> float:
        scale_by_unit = {
            "m": 1.0,
            "mm": 1e-3,
            "um": 1e-6,
            "µm": 1e-6,
            "nm": 1e-9,
        }
        scale = scale_by_unit.get(unit)
        if scale is None:
            return 1.0
        return max(abs(float(value)) * scale, 1e-12)

    def _update_button_state(self, state: str) -> None:
        running = state == "Spectroscopy"
        paused = state == "Spectroscopy Paused"
        self.start_button.setEnabled(not running and not paused)
        self.pause_button.setEnabled(running)
        self.resume_button.setEnabled(paused)
        self.stop_button.setEnabled(running or paused)
        self.save_button.setEnabled(not running)
        self.save_slice_button.setEnabled(bool(self.latest_slice_maps))
        for widget in (
            self.axis_type,
            self.start,
            self.stop,
            self.points,
            self.dwell,
            self.settle,
            self.trace_pass,
            self.retrace_pass,
            self.current_channel,
            self.didv_channel,
            self.amplitude_channel,
            self.phase_channel,
        ):
            widget.setEnabled(not running and not paused)

    @staticmethod
    def double_spin(
        minimum: float,
        maximum: float,
        value: float,
        suffix: str = "",
        decimals: int = 3,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        widget.setSuffix(suffix)
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        return widget

    @staticmethod
    def int_spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        return widget


__all__ = ["SpectroscopyModule"]
