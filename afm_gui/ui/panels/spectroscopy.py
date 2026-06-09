from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def build_spectroscopy_panel(module) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(6, 6, 6, 6)

    controls = QGroupBox("Spectroscopy")
    grid = QGridLayout(controls)

    module.axis_type = QComboBox()
    module.axis_type.addItems(("Bias", "Frequency", "Z", "Field", "Custom"))
    module.start = module.double_spin(-1.0e9, 1.0e9, -1.0, " V", 4)
    module.stop = module.double_spin(-1.0e9, 1.0e9, 1.0, " V", 4)
    module.points = module.int_spin(2, 10001, 201)
    module.dwell = module.double_spin(0.0, 1000.0, 0.001, " s", 6)
    module.settle = module.double_spin(0.0, 1000.0, 0.02, " s", 6)
    module.trace_pass = QCheckBox("Trace")
    module.trace_pass.setChecked(True)
    module.retrace_pass = QCheckBox("Retrace")

    module.current_channel = QCheckBox("Current")
    module.current_channel.setChecked(True)
    module.didv_channel = QCheckBox("dI/dV")
    module.didv_channel.setChecked(True)
    module.amplitude_channel = QCheckBox("Amplitude")
    module.phase_channel = QCheckBox("Phase")

    module.start_button = QPushButton("Start")
    module.pause_button = QPushButton("Pause")
    module.resume_button = QPushButton("Resume")
    module.stop_button = QPushButton("Stop")
    module.save_button = QPushButton("Save")
    module.save_slice_button = QPushButton("Save Slice")
    module.memory_label = QLabel("Memory: -")

    grid.addWidget(QLabel("Axis"), 0, 0)
    grid.addWidget(module.axis_type, 0, 1)
    grid.addWidget(QLabel("Start"), 0, 2)
    grid.addWidget(module.start, 0, 3)
    grid.addWidget(QLabel("Stop"), 0, 4)
    grid.addWidget(module.stop, 0, 5)
    grid.addWidget(QLabel("Points"), 1, 0)
    grid.addWidget(module.points, 1, 1)
    grid.addWidget(QLabel("Dwell"), 1, 2)
    grid.addWidget(module.dwell, 1, 3)
    grid.addWidget(QLabel("Settle"), 1, 4)
    grid.addWidget(module.settle, 1, 5)

    pass_row = QWidget()
    pass_layout = QHBoxLayout(pass_row)
    pass_layout.setContentsMargins(0, 0, 0, 0)
    pass_layout.addWidget(module.trace_pass)
    pass_layout.addWidget(module.retrace_pass)
    pass_layout.addStretch(1)
    grid.addWidget(QLabel("Passes"), 2, 0)
    grid.addWidget(pass_row, 2, 1, 1, 2)

    channels = QWidget()
    channel_layout = QHBoxLayout(channels)
    channel_layout.setContentsMargins(0, 0, 0, 0)
    for checkbox in (
        module.current_channel,
        module.didv_channel,
        module.amplitude_channel,
        module.phase_channel,
    ):
        channel_layout.addWidget(checkbox)
    channel_layout.addStretch(1)
    grid.addWidget(QLabel("Channels"), 2, 3)
    grid.addWidget(channels, 2, 4, 1, 2)

    buttons = QWidget()
    button_layout = QHBoxLayout(buttons)
    button_layout.setContentsMargins(0, 0, 0, 0)
    for button in (
        module.start_button,
        module.pause_button,
        module.resume_button,
        module.stop_button,
        module.save_button,
        module.save_slice_button,
    ):
        button_layout.addWidget(button)
    grid.addWidget(buttons, 3, 0, 1, 4)
    grid.addWidget(module.memory_label, 3, 4, 1, 2)
    layout.addWidget(controls)

    view_controls = QGroupBox("View")
    view_layout = QGridLayout(view_controls)
    module.channel_selector = QComboBox()
    module.pass_selector = QComboBox()
    module.pass_selector.addItems(("trace", "retrace"))
    module.slice_slider = QSlider(Qt.Orientation.Horizontal)
    module.slice_slider.setRange(0, module.points.value() - 1)
    module.slice_label = QLabel("0")
    module.progress_label = QLabel("Idle")
    view_layout.addWidget(QLabel("Channel"), 0, 0)
    view_layout.addWidget(module.channel_selector, 0, 1)
    view_layout.addWidget(QLabel("Pass"), 0, 2)
    view_layout.addWidget(module.pass_selector, 0, 3)
    view_layout.addWidget(QLabel("Slice"), 1, 0)
    view_layout.addWidget(module.slice_slider, 1, 1, 1, 3)
    view_layout.addWidget(module.slice_label, 1, 4)
    view_layout.addWidget(module.progress_label, 1, 5)
    layout.addWidget(view_controls)

    plots = QWidget()
    plot_layout = QHBoxLayout(plots)
    plot_layout.setContentsMargins(0, 0, 0, 0)

    module.spectrum_plot = pg.PlotWidget()
    module.spectrum_plot.setBackground("k")
    module.spectrum_plot.setLabel("bottom", "Axis")
    module.spectrum_plot.setLabel("left", "Signal")
    module.spectrum_curve = module.spectrum_plot.plot(pen=pg.mkPen("#4dabf7", width=2))

    module.slice_plot = pg.PlotWidget()
    module.slice_plot.setBackground("k")
    module.slice_plot.setAspectLocked(True)
    module.slice_plot.setLabel("bottom", "X", units="V")
    module.slice_plot.setLabel("left", "Y", units="V")
    module.slice_image = pg.ImageItem()
    module.slice_plot.addItem(module.slice_image)

    plot_layout.addWidget(module.spectrum_plot, 1)
    plot_layout.addWidget(module.slice_plot, 1)
    layout.addWidget(plots, 1)
    return widget


def axis_metadata(axis_type: str) -> tuple[str, str, str]:
    lookup = {
        "Bias": ("bias", "Bias", "V"),
        "Frequency": ("frequency", "Frequency", "Hz"),
        "Z": ("z", "Z", "nm"),
        "Field": ("field", "Field", "T"),
        "Custom": ("custom", "Custom", ""),
    }
    return lookup.get(axis_type, lookup["Bias"])


__all__ = ["axis_metadata", "build_spectroscopy_panel"]
