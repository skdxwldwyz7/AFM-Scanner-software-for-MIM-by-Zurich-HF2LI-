from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.parameter_tree import (
    ParameterTree,
    build_parameter_tree,
    gsf_metadata_from_tree,
    record_runtime_update,
    write_parameter_tree_json,
)
from afm_gui.core.scan_geometry import generate_scan_lines, line_time, pos_to_voltage
from afm_gui.core.scan_modes import ScanModeConfig
from afm_gui.data.gsf import safe_filename, write_gsf
from afm_gui.protocol import spm_commands as cmd


class ScanController(QObject):
    HOT_UPDATE_PARAMS = frozenset({"linear", "t_sample", "t_settle", "t_rest"})

    image_changed = pyqtSignal(object)
    line_changed = pyqtSignal(int, object)
    probe_position_changed = pyqtSignal(float, float)
    log_message = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    export_finished = pyqtSignal(str)
    runtime_parameters_changed = pyqtSignal(object)
    scan_progress_changed = pyqtSignal(int, int, int, int, str)

    def __init__(self, device: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self.config = ScanConfig()
        self.direction = ScanDirection.UP
        self.lines: list[tuple[np.ndarray, np.ndarray]] = []
        self.images = self._empty_images(self.config)
        self.parameter_tree = build_parameter_tree(self.config, self.direction)
        self.current_line_index = -1
        self._running = False
        self._paused = False

        self.device.line_data_ready.connect(self._on_line_data)
        self.device.command_logged.connect(lambda text: self.log_message.emit(f"> {text}"))
        self.device.scan_finished.connect(self._on_finished)
        if hasattr(self.device, "scan_progress_changed"):
            self.device.scan_progress_changed.connect(self._on_scan_progress)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(
        self,
        config: ScanConfig,
        direction: int,
        parameter_tree: ParameterTree | None = None,
    ) -> None:
        self.config = config
        self.direction = direction
        self.lines = generate_scan_lines(config, direction)
        self.images = self._empty_images(config)
        self.parameter_tree = parameter_tree or build_parameter_tree(config, direction)
        self.current_line_index = -1
        self._running = True
        self._paused = False
        self.scan_progress_changed.emit(0, config.lines, 0, config.pixels, "trace")

        if hasattr(self.device, "configure_scan"):
            self.device.configure_scan(config, self.lines)
        self.device.send_commands(self._first_line_commands())
        interval_ms = int(max(20.0, line_time(config) * 1000.0))
        self.device.start_scan(config.lines, config.pixels, interval_ms, config.channels)
        self.image_changed.emit(self.images)
        self.state_changed.emit("Scanning")
        channels = ", ".join(config.channels)
        self.log_message.emit(f"Started {'up' if direction == ScanDirection.UP else 'down'} scan")
        self.log_message.emit(f"Recording channels: {channels}")

    def pause(self) -> None:
        if not self._running or self._paused:
            return
        self.device.send_commands([cmd.pause()])
        self.device.pause()
        self._paused = True
        self.state_changed.emit("Paused")

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        self.device.send_commands([cmd.unpause()])
        self.device.resume(int(max(20.0, line_time(self.config) * 1000.0)))
        self._paused = False
        self.state_changed.emit("Scanning")

    def stop(self) -> None:
        if not self._running:
            return
        self.device.send_commands([cmd.stop()])
        self.device.stop()

    def update_runtime_params(self, **params: float) -> dict[str, float]:
        unsupported = sorted(set(params) - self.HOT_UPDATE_PARAMS)
        if unsupported:
            valid = ", ".join(sorted(self.HOT_UPDATE_PARAMS))
            raise ValueError(f"Cannot update during scan: {', '.join(unsupported)}. Hot params: {valid}")

        cleaned = {name: float(value) for name, value in params.items() if value is not None}
        if not cleaned:
            return {}

        self.config = replace(self.config, **cleaned)
        if self._running and not self._paused:
            self.device.set_line_interval(int(max(20.0, line_time(self.config) * 1000.0)))

        changed = ", ".join(f"{name}={value:g}" for name, value in cleaned.items())
        target_line = max(0, self.current_line_index + 1)
        record_runtime_update(
            self.parameter_tree,
            current_line_index=self.current_line_index,
            applied_to_line_index=target_line,
            params=cleaned,
        )
        self.log_message.emit(f"Runtime parameters updated for next line >= {target_line}: {changed}")
        self.runtime_parameters_changed.emit(cleaned)
        return cleaned

    def export_gsf_bundle(
        self,
        directory: str | Path,
        mode: ScanModeConfig | None = None,
        *,
        file_prefix: str = "",
    ) -> list[Path]:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        exported = []
        base_metadata = gsf_metadata_from_tree(self.parameter_tree)
        prefix = safe_filename(file_prefix) if file_prefix else ""
        filename_prefix = f"{prefix}_" if prefix else ""
        metadata_filename = f"{prefix}_metadata.json" if prefix else "metadata.json"

        for scan_pass, channels in self.images.items():
            for channel, image in channels.items():
                data = image
                z_unit = mode.unit_for(channel) if mode is not None else ("nm" if channel == "topography" else "")
                x_real = self.config.width if self.config.xy_unit == "V" else self.config.width * 1e-9
                y_real = self.config.height if self.config.xy_unit == "V" else self.config.height * 1e-9
                path = output_dir / f"{filename_prefix}{safe_filename(channel)}_{safe_filename(scan_pass)}.gsf"
                write_gsf(
                    path,
                    data,
                    x_real_m=x_real,
                    y_real_m=y_real,
                    xy_unit=self.config.xy_unit,
                    z_unit=z_unit,
                    title=f"AFM {channel} {scan_pass}",
                    metadata={
                        **base_metadata,
                        "Channel": channel,
                        "ScanPass": scan_pass,
                        "MetadataFile": metadata_filename,
                    },
                )
                exported.append(path)

        write_parameter_tree_json(
            output_dir / metadata_filename,
            self.parameter_tree,
            extra={
                "data": {
                    "format": "Gwyddion Simple Field",
                    "files": [path.name for path in exported],
                }
            },
        )
        self.export_finished.emit(str(output_dir))
        self.log_message.emit(f"Exported {len(exported)} GSF files and {metadata_filename} to {output_dir}")
        return exported

    def _first_line_commands(self) -> list[str]:
        start, end = self.lines[0]
        x1, y1 = pos_to_voltage(start, self.config)
        x2, y2 = pos_to_voltage(end, self.config)
        velocity = self.config.linear * max(self.config.volts_per_nm_x, self.config.volts_per_nm_y)
        return [
            cmd.set_line_endpoint("x1", x1),
            cmd.set_line_endpoint("y1", y1),
            cmd.set_line_endpoint("x2", x2),
            cmd.set_line_endpoint("y2", y2),
            cmd.set_npoints(self.config.pixels),
            cmd.set_sample(self.config.t_sample),
            cmd.set_settle(self.config.t_settle),
            cmd.set_idle(self.config.t_rest),
            cmd.set_velocity(velocity),
            cmd.run(),
        ]

    def _next_line_commands(self, line_index: int) -> list[str]:
        start, end = self.lines[line_index]
        x1, y1 = pos_to_voltage(start, self.config)
        x2, y2 = pos_to_voltage(end, self.config)
        velocity = self.config.linear * max(self.config.volts_per_nm_x, self.config.volts_per_nm_y)
        return [
            cmd.set_line_endpoint("x1", x1),
            cmd.set_line_endpoint("y1", y1),
            cmd.set_line_endpoint("x2", x2),
            cmd.set_line_endpoint("y2", y2),
            cmd.set_sample(self.config.t_sample),
            cmd.set_settle(self.config.t_settle),
            cmd.set_idle(self.config.t_rest),
            cmd.set_velocity(velocity),
        ]

    @staticmethod
    def _empty_images(config: ScanConfig) -> dict[str, dict[str, np.ndarray]]:
        return {
            scan_pass: {
                channel: np.full((config.lines, config.pixels), np.nan, dtype=float)
                for channel in config.channels
            }
            for scan_pass in config.scan_passes
        }

    def _on_line_data(self, line_index: int, data: object) -> None:
        self.current_line_index = line_index
        self.parameter_tree.set_path("runtime.current_line_index", line_index)
        image_line_index = self._image_line_index(line_index)
        line_data = {}
        for channel, values in dict(data).items():
            if isinstance(values, dict):
                line_data[channel] = {
                    scan_pass: np.asarray(pass_values, dtype=float)
                    for scan_pass, pass_values in values.items()
                }
            else:
                line_data[channel] = {"trace": np.asarray(values, dtype=float)}

        for channel, pass_data in line_data.items():
            for scan_pass, values in pass_data.items():
                if scan_pass not in self.images:
                    self.images[scan_pass] = {}
                if channel not in self.images[scan_pass]:
                    self.images[scan_pass][channel] = np.full(
                        (self.config.lines, self.config.pixels),
                        np.nan,
                        dtype=float,
                    )
                self.images[scan_pass][channel][image_line_index, :] = values
        self.image_changed.emit(self.images)
        self.line_changed.emit(line_index, line_data)

        start, end = self.lines[line_index]
        self.probe_position_changed.emit(float(end[0]), float(end[1]))
        next_line = line_index + 1
        if next_line < len(self.lines):
            self.device.send_commands(self._next_line_commands(next_line))

    def _on_scan_progress(
        self,
        line_index: int,
        total_lines: int,
        pixel_index: int,
        total_pixels: int,
        scan_pass: str,
    ) -> None:
        self.scan_progress_changed.emit(line_index, total_lines, pixel_index, total_pixels, scan_pass)

    def _image_line_index(self, acquisition_line_index: int) -> int:
        if self.direction == ScanDirection.DOWN:
            return self.config.lines - 1 - acquisition_line_index
        return acquisition_line_index

    def _on_finished(self) -> None:
        self._running = False
        self._paused = False
        self.state_changed.emit("Idle")
        self.scan_progress_changed.emit(0, max(1, self.config.lines), 0, max(1, self.config.pixels), "idle")
        self.log_message.emit("Scan finished")
        self.current_line_index = -1
