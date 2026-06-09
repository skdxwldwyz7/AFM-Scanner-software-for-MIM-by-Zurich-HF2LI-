from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QPushButton,
    QLabel,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
)


DEVICE_TABLE_HEADERS = ("Name", "Kind", "Capabilities", "Driver", "Connection", "Enabled", "Status")
FUNCTION_TABLE_HEADERS = ("Function", "Requirement", "Assigned Device", "Status")


def build_device_manager_panel(window) -> QGroupBox:
    box = QGroupBox("Device Manager")
    box.setMinimumHeight(500)
    layout = QGridLayout(box)
    layout.setRowStretch(1, 3)
    layout.setRowStretch(3, 3)

    window.device_table = QTableWidget(0, len(DEVICE_TABLE_HEADERS))
    window.device_table.setHorizontalHeaderLabels(DEVICE_TABLE_HEADERS)
    window.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    window.device_table.setEditTriggers(
        QAbstractItemView.EditTrigger.DoubleClicked
        | QAbstractItemView.EditTrigger.SelectedClicked
        | QAbstractItemView.EditTrigger.EditKeyPressed
    )
    window.device_table.setMinimumHeight(210)
    window.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    window.device_function_table = QTableWidget(0, len(FUNCTION_TABLE_HEADERS))
    window.device_function_table.setHorizontalHeaderLabels(FUNCTION_TABLE_HEADERS)
    window.device_function_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.device_function_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    window.device_function_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    window.device_function_table.setMinimumHeight(190)
    window.device_function_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    window.load_devices = QPushButton("Load Config")
    window.connect_device = QPushButton("Connect")
    window.disconnect_device = QPushButton("Disconnect")
    window.apply_device_connection = QPushButton("Apply Connection")
    window.connect_enabled_devices = QPushButton("Connect Enabled")
    window.connect_assigned_devices = QPushButton("Connect Assigned")
    window.disconnect_all_devices = QPushButton("Disconnect All")

    layout.addWidget(QLabel("Function Assignments"), 0, 0, 1, 6)
    layout.addWidget(window.device_function_table, 1, 0, 1, 6)
    layout.addWidget(QLabel("Configured Devices"), 2, 0, 1, 6)
    layout.addWidget(window.device_table, 3, 0, 1, 6)
    layout.addWidget(window.load_devices, 4, 0)
    layout.addWidget(window.apply_device_connection, 4, 1)
    layout.addWidget(window.connect_device, 4, 2)
    layout.addWidget(window.disconnect_device, 4, 3)
    layout.addWidget(window.connect_enabled_devices, 4, 4)
    layout.addWidget(window.connect_assigned_devices, 4, 5)
    layout.addWidget(window.disconnect_all_devices, 5, 0, 1, 6)
    return box


def make_item(text: object) -> QTableWidgetItem:
    return QTableWidgetItem(str(text))


def make_editable_item(text: object) -> QTableWidgetItem:
    return QTableWidgetItem(str(text))


def make_device_combo(devices: list[str], current: str) -> QComboBox:
    combo = QComboBox()
    combo.addItem("")
    combo.addItems(devices)
    if current in devices:
        combo.setCurrentText(current)
    return combo
