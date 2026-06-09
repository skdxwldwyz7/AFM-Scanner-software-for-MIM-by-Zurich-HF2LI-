from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QRectF, Qt
from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QSpinBox

from afm_gui.core.parameter_tree import build_parameter_tree
from afm_gui.core.scan_config import ScanConfig
from afm_gui.core.scan_controller import ScanController
from afm_gui.core.scan_modes import ScanModeConfig, load_scan_modes
from afm_gui.ui.panels.scan_parameters import build_scan_parameters_panel


class ScanModule(QObject):
    """Owns scan parameters, scan-mode changes, hot updates, and scan start metadata."""

    def __init__(
        self,
        controller: ScanController,
        display_metadata_provider: Callable[[], dict[str, object]],
        extra_metadata_provider: Callable[[], dict[str, object]],
        metadata_refresh: Callable[[], None],
        log_callback: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._display_metadata_provider = display_metadata_provider
        self._extra_metadata_provider = extra_metadata_provider
        self._metadata_refresh = metadata_refresh
        self._log_callback = log_callback
        self._mode_changed_callback: Callable[[ScanModeConfig], None] | None = None
        self.mode_registry = load_scan_modes()
        self.current_mode = self.mode_registry.default
        self.widget = build_scan_parameters_panel(self)
        self._connect()
        self.update_scan_time_estimate()

    def set_mode_changed_callback(self, callback: Callable[[ScanModeConfig], None]) -> None:
        self._mode_changed_callback = callback

    def start(self, direction: int) -> None:
        config = self.config()
        tree = build_parameter_tree(
            config,
            direction,
            mode=self.current_mode,
            **self._display_metadata_provider(),
            source="gui",
        )
        tree.update_paths(self._extra_metadata_provider())
        self.controller.start(config, direction, tree)
        self._metadata_refresh()

    def config(self) -> ScanConfig:
        channels = tuple(
            channel for channel, checkbox in self.channel_checks.items() if checkbox.isChecked()
        )
        if not channels:
            channels = ("topography",)
        return ScanConfig(
            xc=self.xc.value(),
            yc=self.yc.value(),
            width=self.width.value(),
            height=self.height.value(),
            angle=self.angle.value(),
            pixels=self.pixels.value(),
            lines=self.lines.value(),
            linear=self.linear.value(),
            t_sample=self.t_sample.value(),
            t_settle=self.t_settle.value(),
            t_rest=self.t_rest.value(),
            scan_mode=self.current_mode.name,
            channels=channels,
            scan_passes=self.current_mode.scan_passes,
            xy_unit="V",
            volts_per_nm_x=1.0,
            volts_per_nm_y=1.0,
        )

    def image_geometry(self) -> tuple[float, float, float, float]:
        return self.xc.value(), self.yc.value(), self.width.value(), self.height.value()

    def apply_roi_to_scan_parameters(self, rect: QRectF) -> None:
        self.xc.setValue(rect.center().x())
        self.yc.setValue(rect.center().y())
        self.width.setValue(rect.width())
        self.height.setValue(rect.height())
        self.update_scan_time_estimate()

    def reload_scan_modes(self) -> None:
        current = self.current_mode.name
        self.mode_registry = load_scan_modes()
        self.scan_mode.blockSignals(True)
        self.scan_mode.clear()
        for mode_name, mode in self.mode_registry.modes.items():
            self.scan_mode.addItem(mode.label, mode_name)
        selected = current if current in self.mode_registry.modes else self.mode_registry.default_mode
        self.scan_mode.setCurrentIndex(max(0, self.scan_mode.findData(selected)))
        self.scan_mode.blockSignals(False)
        self.apply_scan_mode(self.mode_registry.modes[selected])
        self._log_callback("Reloaded scan modes")

    def apply_scan_mode(self, mode: ScanModeConfig) -> None:
        self.current_mode = mode
        self._rebuild_channel_checks(mode)
        if self._mode_changed_callback is not None:
            self._mode_changed_callback(mode)
        self.update_scan_time_estimate()
        self._log_callback(f"Loaded scan mode: {mode.label}")

    def _connect(self) -> None:
        self.scan_mode.currentIndexChanged.connect(self._on_scan_mode_changed)
        self.linear.valueChanged.connect(lambda value: self._update_runtime_param("linear", value))
        self.t_sample.valueChanged.connect(lambda value: self._update_runtime_param("t_sample", value))
        self.t_settle.valueChanged.connect(lambda value: self._update_runtime_param("t_settle", value))
        self.t_rest.valueChanged.connect(lambda value: self._update_runtime_param("t_rest", value))
        for widget in (
            self.width,
            self.height,
            self.pixels,
            self.lines,
            self.linear,
            self.t_sample,
            self.t_settle,
            self.t_rest,
        ):
            widget.valueChanged.connect(lambda _value: self.update_scan_time_estimate())

    def update_scan_time_estimate(self) -> float:
        seconds = self.estimated_scan_time_s()
        self.scan_time_label.setText(self._format_duration(seconds))
        return seconds

    def estimated_scan_time_s(self) -> float:
        passes = max(1, len(self.current_mode.scan_passes))
        width = float(self.width.value())
        linear = max(float(self.linear.value()), 1e-12)
        pixels = int(self.pixels.value())
        lines = int(self.lines.value())
        pass_time = width / linear + float(self.t_settle.value()) + pixels * float(self.t_sample.value())
        return lines * (passes * pass_time + float(self.t_rest.value()))

    def _on_scan_mode_changed(self) -> None:
        mode_name = self.scan_mode.currentData()
        if not mode_name:
            return
        self.apply_scan_mode(self.mode_registry.modes[str(mode_name)])

    def _update_runtime_param(self, name: str, value: float) -> None:
        if not self.controller.is_running:
            return
        try:
            self.controller.update_runtime_params(**{name: value})
        except ValueError as exc:
            self._log_callback(str(exc))

    def _rebuild_channel_checks(self, mode: ScanModeConfig) -> None:
        while self.channel_layout.count():
            item = self.channel_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.channel_checks = {}
        for channel in mode.channels:
            label = channel.label if not channel.unit else f"{channel.label} ({channel.unit})"
            checkbox = QCheckBox(label)
            checkbox.setChecked(channel.enabled)
            self.channel_checks[channel.name] = checkbox
            self.channel_layout.addWidget(checkbox)

    @staticmethod
    def _double(
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
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        return widget

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        if seconds < 60:
            return f"{seconds:.1f} s"
        if seconds < 3600:
            minutes = int(seconds // 60)
            remainder = int(round(seconds - minutes * 60))
            if remainder == 60:
                minutes += 1
                remainder = 0
            return f"{minutes} min {remainder:02d} s"
        hours = int(seconds // 3600)
        minutes = int(round((seconds - hours * 3600) / 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return f"{hours} h {minutes:02d} min"


__all__ = ["ScanModule"]
