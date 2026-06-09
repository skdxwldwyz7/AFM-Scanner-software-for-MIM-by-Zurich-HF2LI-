from __future__ import annotations

from PyQt6.QtWidgets import QGroupBox, QTreeWidget, QVBoxLayout


def build_parameter_tree_panel(window) -> QGroupBox:
    window.metadata_box = QGroupBox("Parameter Tree")
    layout = QVBoxLayout(window.metadata_box)
    window.metadata_tree = QTreeWidget()
    window.metadata_tree.setHeaderLabels(["Parameter", "Value"])
    layout.addWidget(window.metadata_tree)
    return window.metadata_box
