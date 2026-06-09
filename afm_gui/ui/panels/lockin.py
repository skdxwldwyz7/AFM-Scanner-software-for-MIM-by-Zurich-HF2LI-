from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


TIME_CONSTANTS = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
SENSITIVITIES = (1e-9, 3e-9, 10e-9, 30e-9, 100e-9, 300e-9, 1e-6, 3e-6, 10e-6, 100e-6, 1e-3, 1.0)
RESERVES = ("High Reserve", "Normal", "Low Noise")


def build_lockin_panel(window) -> QWidget:
    box = QWidget()
    box.setMaximumWidth(760)
    box.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setSpacing(6)
    window.lockin_channels = {}

    layout.addWidget(_build_lockin_channel(window, "ch1", "Channel 1"))
    layout.addWidget(_build_lockin_channel(window, "ch2", "Channel 2"))
    layout.addWidget(_build_scan_routing(window))
    layout.addStretch(1)
    return box


def _build_scan_routing(window) -> QGroupBox:
    box = QGroupBox("Scan Routing")
    layout = QGridLayout(box)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(4)
    window.lockin_scan_routes = {}

    layout.addWidget(QLabel("Image"), 0, 0)
    layout.addWidget(QLabel("Device"), 0, 1)
    layout.addWidget(QLabel("Channel"), 0, 2)
    layout.addWidget(QLabel("Signal"), 0, 3)
    window.lockin_apply_routes = QPushButton("Apply")
    window.lockin_apply_routes.setMaximumWidth(82)
    layout.addWidget(window.lockin_apply_routes, 0, 4)
    for row, (channel, label, signal) in enumerate(
        (
            ("signal_a", "A", "x"),
            ("signal_b", "B", "y"),
            ("signal_c", "C", "r"),
            ("signal_d", "D", "theta"),
        ),
        start=1,
    ):
        device_combo = QComboBox()
        device_combo.setMinimumWidth(180)
        channel_combo = QComboBox()
        channel_combo.setMinimumWidth(74)
        signal_combo = QComboBox()
        signal_combo.addItems(("x", "y", "r", "theta", "frequency"))
        signal_combo.setCurrentText(signal)
        controls = {"device": device_combo, "lockin_channel": channel_combo, "signal": signal_combo, "label": label}
        window.lockin_scan_routes[channel] = controls
        layout.addWidget(QLabel(label), row, 0)
        layout.addWidget(device_combo, row, 1)
        layout.addWidget(channel_combo, row, 2)
        layout.addWidget(signal_combo, row, 3)
    layout.setColumnStretch(1, 1)
    return box


def _build_lockin_channel(window, key: str, title: str) -> QGroupBox:
    channel_box = QGroupBox(title)
    channel_box.setMaximumWidth(740)
    channel_box.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    layout = QGridLayout(channel_box)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(4)
    controls = {}

    settings_box = QGroupBox("Reference")
    settings_form = QFormLayout(settings_box)
    _compact_form(settings_form)
    controls["output_enabled"] = QCheckBox("Output")
    controls["frequency"] = _double(0.001, 10_000_000, 1000, " Hz", decimals=3)
    controls["amplitude"] = _double(0.0, 10.0, 0.1, " V", decimals=6)
    controls["phase"] = _double(-360.0, 360.0, 0.0, " deg", decimals=3)
    controls["time_constant"] = QComboBox()
    controls["time_constant"].addItems([f"{value:g} s" for value in TIME_CONSTANTS])
    controls["time_constant"].setCurrentText("0.1 s")
    controls["time_constant"].setMaximumWidth(180)
    controls["sensitivity"] = QComboBox()
    controls["sensitivity"].addItems([_format_voltage(value) for value in SENSITIVITIES])
    controls["sensitivity"].setCurrentText("1 V")
    controls["sensitivity"].setMaximumWidth(180)
    controls["reserve"] = QComboBox()
    controls["reserve"].addItems(RESERVES)
    controls["reserve"].setCurrentText("Normal")
    controls["reserve"].setMaximumWidth(180)
    settings_form.addRow("Output", controls["output_enabled"])
    settings_form.addRow("Frequency", controls["frequency"])
    settings_form.addRow("Amplitude", controls["amplitude"])
    settings_form.addRow("Phase", controls["phase"])
    settings_form.addRow("Time Constant", controls["time_constant"])
    settings_form.addRow("Sensitivity", controls["sensitivity"])
    settings_form.addRow("Reserve", controls["reserve"])

    reading_box = QGroupBox("Readout")
    reading_form = QFormLayout(reading_box)
    _compact_form(reading_form)
    controls["x_label"] = QLabel("0.000000 V")
    controls["y_label"] = QLabel("0.000000 V")
    controls["r_label"] = QLabel("0.000000 V")
    controls["theta_label"] = QLabel("0.000 deg")
    controls["frequency_label"] = QLabel("0 Hz")
    controls["apply"] = QPushButton("Apply")
    controls["read"] = QPushButton("Read")
    controls["apply"].setMaximumWidth(82)
    controls["read"].setMaximumWidth(82)
    reading_form.addRow("X", controls["x_label"])
    reading_form.addRow("Y", controls["y_label"])
    reading_form.addRow("R", controls["r_label"])
    reading_form.addRow("Theta", controls["theta_label"])
    reading_form.addRow("Frequency", controls["frequency_label"])
    reading_form.addRow(controls["apply"], controls["read"])

    layout.addWidget(settings_box, 0, 0)
    layout.addWidget(reading_box, 0, 1)
    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 1)
    controls["box"] = channel_box
    window.lockin_channels[key] = controls
    return channel_box


def _compact_form(layout: QFormLayout) -> None:
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(2)
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)


def _double(minimum: float, maximum: float, value: float, suffix: str = "", decimals: int = 3) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setAlignment(Qt.AlignmentFlag.AlignRight)
    widget.setMinimumWidth(92)
    widget.setMaximumWidth(180)
    return widget


def _format_voltage(value: float) -> str:
    if value >= 1:
        return f"{value:g} V"
    if value >= 1e-3:
        return f"{value * 1e3:g} mV"
    if value >= 1e-6:
        return f"{value * 1e6:g} uV"
    return f"{value * 1e9:g} nV"
