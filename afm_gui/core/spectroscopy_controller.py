from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.scan_geometry import generate_scan_lines
from afm_gui.core.spectroscopy_config import SpectroscopyConfig
from afm_gui.data.spectroscopy import SpectroscopyBundle, write_spectroscopy_bundle


class SpectroscopyController(QObject):
    spectrum_point_changed = pyqtSignal(int, int, object)
    spectrum_slice_changed = pyqtSignal(object)
    probe_position_changed = pyqtSignal(float, float)
    state_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)
    export_finished = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.scan_config = ScanConfig(scan_mode="spectroscopy")
        self.config = SpectroscopyConfig()
        self.direction = ScanDirection.UP
        self.spectrum_axis = self.config.axis()
        self.spectra = self._empty_spectra(self.scan_config, self.config)
        self.maps = self._empty_maps(self.scan_config)
        self.current_line_index = -1
        self.current_pixel_index = -1
        self.selected_slice_index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._acquire_next_point)
        self._running = False
        self._paused = False
        self._line_points: list[np.ndarray] = []
        self._point_number = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self, scan_config: ScanConfig, config: SpectroscopyConfig, direction: int = ScanDirection.UP) -> None:
        self.scan_config = scan_config
        self.config = config
        self.direction = direction
        self.spectrum_axis = config.axis()
        self.spectra = self._empty_spectra(scan_config, config)
        self.maps = self._empty_maps(scan_config)
        self.current_line_index = -1
        self.current_pixel_index = -1
        self.selected_slice_index = 0
        self._point_number = 0
        self._line_points = [
            np.linspace(start, end, scan_config.pixels)
            for start, end in generate_scan_lines(scan_config, direction)
        ]
        self._running = True
        self._paused = False
        interval_ms = int(max(5.0, (config.settle + config.dwell * len(self.spectrum_axis)) * 1000.0))
        self._timer.start(interval_ms)
        self.state_changed.emit("Spectroscopy")
        self.log_message.emit(
            "Started spectroscopy map: "
            f"{scan_config.lines}x{scan_config.pixels}, {len(self.spectrum_axis)} {config.axis_unit} points"
        )

    def pause(self) -> None:
        if not self._running or self._paused:
            return
        self._timer.stop()
        self._paused = True
        self.state_changed.emit("Spectroscopy Paused")

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        interval_ms = int(max(5.0, (self.config.settle + self.config.dwell * len(self.spectrum_axis)) * 1000.0))
        self._timer.start(interval_ms)
        self._paused = False
        self.state_changed.emit("Spectroscopy")

    def stop(self) -> None:
        if not self._running:
            return
        self._timer.stop()
        self._running = False
        self._paused = False
        self.state_changed.emit("Idle")
        self.log_message.emit("Spectroscopy map stopped")

    def set_selected_slice_index(self, index: int) -> None:
        self.selected_slice_index = int(np.clip(index, 0, len(self.spectrum_axis) - 1))
        self.spectrum_slice_changed.emit(self.slice_maps())

    def slice_maps(self) -> dict[str, dict[str, np.ndarray]]:
        return {
            scan_pass: {
                channel: values[:, :, self.selected_slice_index]
                for channel, values in channels.items()
            }
            for scan_pass, channels in self.spectra.items()
        }

    def export_bundle(self, path: str | Path, metadata: dict[str, object] | None = None) -> Path:
        payload = {
            "created_local": datetime.now().isoformat(timespec="seconds"),
            "scan": {
                "mode": "spectroscopy",
                "lines": self.scan_config.lines,
                "pixels": self.scan_config.pixels,
                "xy_unit": self.scan_config.xy_unit,
                "width": self.scan_config.width,
                "height": self.scan_config.height,
                "center_x": self.scan_config.xc,
                "center_y": self.scan_config.yc,
                "angle_deg": self.scan_config.angle,
            },
            "spectroscopy": {
                "axis_name": self.config.axis_name,
                "axis_label": self.config.axis_label,
                "axis_unit": self.config.axis_unit,
                "start": self.config.start,
                "stop": self.config.stop,
                "points": len(self.spectrum_axis),
                "dwell": self.config.dwell,
                "settle": self.config.settle,
                "channels": self.config.channels,
            },
            **(metadata or {}),
        }
        bundle = SpectroscopyBundle(
            spectrum_axis=self.spectrum_axis,
            spectra=self.spectra,
            maps=self.maps,
            metadata=payload,
            axis_name=self.config.axis_name,
            axis_label=self.config.axis_label,
            axis_unit=self.config.axis_unit,
            channel_units={"current": "A", "didv": "S", "topography": "nm"},
        )
        output_path = write_spectroscopy_bundle(path, bundle)
        self.export_finished.emit(str(output_path))
        self.log_message.emit(f"Saved spectroscopy bundle: {output_path}")
        return output_path

    def _acquire_next_point(self) -> None:
        total = self.scan_config.lines * self.scan_config.pixels
        if self._point_number >= total:
            self._timer.stop()
            self._running = False
            self._paused = False
            self.state_changed.emit("Idle")
            self.log_message.emit("Spectroscopy map finished")
            return

        line_index = self._point_number // self.scan_config.pixels
        pixel_index = self._point_number % self.scan_config.pixels
        image_line_index = self._image_line_index(line_index)
        point = self._line_points[line_index][pixel_index]
        curves = self._synthetic_spectrum(line_index, pixel_index)
        topo_value = self._synthetic_topography(line_index, pixel_index)
        for scan_pass in self.config.scan_passes:
            self.maps.setdefault(scan_pass, {}).setdefault(
                "topography",
                np.full((self.scan_config.lines, self.scan_config.pixels), np.nan, dtype=float),
            )[image_line_index, pixel_index] = topo_value
            for channel, values in curves.items():
                self.spectra[scan_pass][channel][image_line_index, pixel_index, :] = values

        self.current_line_index = line_index
        self.current_pixel_index = pixel_index
        self.spectrum_point_changed.emit(line_index, pixel_index, curves)
        self.spectrum_slice_changed.emit(self.slice_maps())
        self.probe_position_changed.emit(float(point[0]), float(point[1]))
        self._point_number += 1

    def _synthetic_spectrum(self, line_index: int, pixel_index: int) -> dict[str, np.ndarray]:
        axis = self.spectrum_axis
        x = pixel_index / max(self.scan_config.pixels - 1, 1)
        y = line_index / max(self.scan_config.lines - 1, 1)
        center = 0.35 * np.sin(2.0 * np.pi * y)
        amplitude = 1.0 + 0.4 * np.cos(2.0 * np.pi * x)
        current = 1e-9 * amplitude * (np.tanh(4.0 * (axis - center)) + 0.08 * axis**3)
        didv = np.gradient(current, axis, edge_order=1)
        available = {
            "current": current,
            "didv": didv,
            "amplitude": 1.0 + 0.1 * amplitude * np.exp(-((axis - center) ** 2) / 0.18),
            "phase": 20.0 * np.sin(np.pi * axis + 2.0 * np.pi * y),
        }
        return {channel: available.get(channel, current) for channel in self.config.channels}

    def _synthetic_topography(self, line_index: int, pixel_index: int) -> float:
        x = pixel_index / max(self.scan_config.pixels - 1, 1) - 0.5
        y = line_index / max(self.scan_config.lines - 1, 1) - 0.5
        return float(3.0 * np.exp(-8.0 * (x * x + y * y)) + 0.4 * np.sin(8.0 * x))

    def _image_line_index(self, acquisition_line_index: int) -> int:
        if self.direction == ScanDirection.DOWN:
            return self.scan_config.lines - 1 - acquisition_line_index
        return acquisition_line_index

    @staticmethod
    def _empty_spectra(scan_config: ScanConfig, config: SpectroscopyConfig) -> dict[str, dict[str, np.ndarray]]:
        return {
            scan_pass: {
                channel: np.full((scan_config.lines, scan_config.pixels, len(config.axis())), np.nan, dtype=float)
                for channel in config.channels
            }
            for scan_pass in config.scan_passes
        }

    @staticmethod
    def _empty_maps(scan_config: ScanConfig) -> dict[str, dict[str, np.ndarray]]:
        return {
            "trace": {
                "topography": np.full((scan_config.lines, scan_config.pixels), np.nan, dtype=float),
            }
        }


__all__ = ["SpectroscopyController"]
