from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from afm_gui.core.scan_config import SCAN_PASSES


class RoiViewBox(pg.ViewBox):
    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self._install_roi_menu_actions()

    def _install_roi_menu_actions(self) -> None:
        menu = self.getMenu(None)
        if menu is None:
            return
        menu.addSeparator()
        load_roi = QAction("Load ROI Into Scan Parameters", menu)
        load_roi.triggered.connect(self.window._load_roi_into_scan_parameters)
        menu.addAction(load_roi)
        clear_roi = QAction("Clear ROI", menu)
        clear_roi.triggered.connect(self.window._clear_shared_roi)
        menu.addAction(clear_roi)

    def mouseDragEvent(self, event, axis=None) -> None:  # noqa: N802 - pyqtgraph API
        if event.button() == Qt.MouseButton.LeftButton:
            start = self.mapSceneToView(event.buttonDownScenePos())
            end = self.mapSceneToView(event.scenePos())
            self.window._set_shared_roi_from_points(start.x(), start.y(), end.x(), end.y())
            event.accept()
            return
        super().mouseDragEvent(event, axis=axis)


def build_channel_images_panel(window) -> QWidget:
    widget = QWidget()
    window.image_grid = QGridLayout(widget)
    window.image_grid.setContentsMargins(0, 0, 0, 0)
    window.image_grid.setSpacing(8)
    return widget


def create_channel_view(window, index: int) -> dict[str, object]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)

    header = QWidget()
    header_layout = QGridLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)

    selector = QComboBox()
    selector.addItems(window.current_mode.channel_names)
    pass_selector = QComboBox()
    pass_selector.addItems(SCAN_PASSES)
    flatten_selector = QComboBox()
    flatten_selector.addItems(("Raw", "Line Mean", "Plane"))
    if index < len(window.current_mode.channel_names):
        selector.setCurrentText(window.current_mode.channel_names[index])

    image_area = QWidget()
    image_area_layout = QHBoxLayout(image_area)
    image_area_layout.setContentsMargins(0, 0, 0, 0)
    image_area_layout.setSpacing(4)

    plot = pg.PlotWidget(viewBox=RoiViewBox(window))
    plot.setMouseEnabled(x=True, y=True)
    plot.setBackground("k")
    plot.setMinimumSize(280, 280)
    plot.setAspectLocked(True)
    plot.setLabel("bottom", "X", units="V")
    plot.setLabel("left", "Y", units="V")
    image_item = pg.ImageItem()
    plot.addItem(image_item)

    histogram = pg.HistogramLUTWidget()
    histogram.setImageItem(image_item)
    histogram.setMinimumWidth(70)
    histogram.setMaximumWidth(120)
    histogram.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    histogram.customContextMenuRequested.connect(
        lambda position, hist=histogram: window._show_colormap_menu(hist, position)
    )
    window._apply_colormap(histogram, "viridis")

    if window.channel_views:
        first_plot = window.channel_views[0].get("plot")
        if isinstance(first_plot, pg.PlotWidget):
            plot.setXLink(first_plot)
            plot.setYLink(first_plot)

    header_layout.addWidget(selector, 0, 0)
    header_layout.addWidget(pass_selector, 0, 1)
    header_layout.addWidget(flatten_selector, 0, 2)
    layout.addWidget(header)
    image_area_layout.addWidget(plot, 1)
    image_area_layout.addWidget(histogram)
    layout.addWidget(image_area, 1)

    selector.currentTextChanged.connect(window._refresh_image_views)
    pass_selector.currentTextChanged.connect(window._refresh_image_views)
    flatten_selector.currentTextChanged.connect(window._refresh_image_views)
    return {
        "widget": widget,
        "selector": selector,
        "pass_selector": pass_selector,
        "flatten_selector": flatten_selector,
        "plot": plot,
        "image_item": image_item,
        "histogram": histogram,
        "colormap": "viridis",
        "roi_item": None,
    }
