from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel

from afm_gui.core.scan_config import SCAN_PASSES


def build_status_panel(window) -> QGroupBox:
    box = QGroupBox("State")
    layout = QFormLayout(box)
    mode = window.scan_module.current_mode if hasattr(window, "scan_module") else window.current_mode
    window.state_label = QLabel("Idle")
    window.scan_progress_label = QLabel("Line 0/0, Pixel 0/0")
    window.position_label = QLabel("0.0, 0.0 V")
    window.display_count = window._spin(1, 8, 2)
    window.line_channel_selector = QComboBox()
    window.line_channel_selector.addItems(mode.channel_names)
    window.line_pass_selector = QComboBox()
    window.line_pass_selector.addItems(SCAN_PASSES)
    layout.addRow("Mode", window.state_label)
    layout.addRow("Progress", window.scan_progress_label)
    layout.addRow("Probe", window.position_label)
    layout.addRow("Views", window.display_count)
    layout.addRow("Line Plot", window.line_channel_selector)
    layout.addRow("Line Pass", window.line_pass_selector)
    return box
