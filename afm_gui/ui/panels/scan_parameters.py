from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget


def build_scan_parameters_panel(window) -> QGroupBox:
    box = QGroupBox("Scan Parameters")
    form = QFormLayout(box)
    window.scan_mode = QComboBox()
    for mode_name, mode in window.mode_registry.modes.items():
        window.scan_mode.addItem(mode.label, mode_name)
    window.scan_mode.setCurrentIndex(
        max(0, window.scan_mode.findData(window.mode_registry.default_mode))
    )
    window.xc = window._double(-10, 10, 0, " V")
    window.yc = window._double(-10, 10, 0, " V")
    window.width = window._double(0.001, 20, 1, " V")
    window.height = window._double(0.001, 20, 1, " V")
    window.angle = window._double(-180, 180, 0, " deg")
    window.linear = window._double(0.001, 100, 0.2, " V/s")
    window.t_sample = window._double(0.000001, 10, 0.001, " s", decimals=6)
    window.t_settle = window._double(0, 60, 0.02, " s", decimals=4)
    window.t_rest = window._double(0, 60, 0.01, " s", decimals=4)
    window.pixels = window._spin(2, 4096, 256)
    window.lines = window._spin(2, 4096, 256)
    window.scan_time_label = QLabel("0.0 s")
    window.channel_checks: dict[str, QCheckBox] = {}
    window.channel_widget = QWidget()
    window.channel_layout = QVBoxLayout(window.channel_widget)
    window.channel_layout.setContentsMargins(0, 0, 0, 0)

    form.addRow("Scan Mode", window.scan_mode)
    form.addRow("Center X", window.xc)
    form.addRow("Center Y", window.yc)
    form.addRow("Width", window.width)
    form.addRow("Height", window.height)
    form.addRow("Angle", window.angle)
    form.addRow("Pixels", window.pixels)
    form.addRow("Lines", window.lines)
    form.addRow("Linear", window.linear)
    form.addRow("Sample", window.t_sample)
    form.addRow("Settle", window.t_settle)
    form.addRow("Rest", window.t_rest)
    form.addRow("Estimated Time", window.scan_time_label)
    channel_scroll = QScrollArea()
    channel_scroll.setWidgetResizable(True)
    channel_scroll.setWidget(window.channel_widget)
    channel_scroll.setMinimumHeight(100)
    channel_scroll.setMaximumHeight(190)
    form.addRow("Channels", channel_scroll)
    return box
