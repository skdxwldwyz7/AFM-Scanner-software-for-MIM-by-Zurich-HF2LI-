from __future__ import annotations

from collections.abc import Callable
import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QRectF, Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QMenu, QWidget

from afm_gui.core.scan_modes import ScanModeConfig
from afm_gui.ui.panels.channel_images import build_channel_images_panel, create_channel_view
from afm_gui.ui.panels.line_plot import build_line_plot_panel


class ChannelImagesModule(QObject):
    """Owns channel image views, line plot data, colormaps, ROI, and probe display."""

    COLORMAPS = ("viridis", "plasma", "inferno", "magma", "cividis", "gray", "turbo")

    def __init__(
        self,
        mode_provider: Callable[[], ScanModeConfig],
        geometry_provider: Callable[[], tuple[float, float, float, float]],
        roi_callback: Callable[[QRectF], None],
        log_callback: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode_provider = mode_provider
        self._geometry_provider = geometry_provider
        self._roi_callback = roi_callback
        self._log_callback = log_callback
        self.widget = build_channel_images_panel(self)
        self.line_plot = build_line_plot_panel(self)
        self.channel_views: list[dict[str, object]] = []
        self.shared_roi_rect: QRectF | None = None
        self.latest_images: dict[str, dict[str, np.ndarray]] = {}
        self.latest_lines: dict[str, dict[str, np.ndarray]] = {}
        self.display_count = None
        self.line_channel_selector = None
        self.line_pass_selector = None
        self.position_label = None
        self.channel_aliases: dict[str, str] = {}

    @property
    def current_mode(self) -> ScanModeConfig:
        return self._mode_provider()

    def bind_status_controls(self, display_count, line_channel_selector, line_pass_selector, position_label) -> None:
        self.display_count = display_count
        self.line_channel_selector = line_channel_selector
        self.line_pass_selector = line_pass_selector
        self.position_label = position_label
        self.display_count.valueChanged.connect(self.set_display_count)
        self.line_channel_selector.currentTextChanged.connect(self.refresh_line_channel)
        self.line_pass_selector.currentTextChanged.connect(self.refresh_line_channel)

    def display_metadata(self) -> dict[str, object]:
        return {
            "display_count": self.display_count.value(),
            "display_channels": tuple(self._selector_channel(selector) for selector in self.image_selectors()),
            "display_passes": tuple(selector.currentText() for selector in self.image_pass_selectors()),
            "display_flatten_modes": tuple(selector.currentText() for selector in self.image_flatten_selectors()),
            "display_colormaps": tuple(str(view.get("colormap", "")) for view in self.channel_views),
            "display_ranges": tuple(self._range_metadata(view) for view in self.channel_views),
            "line_channel": self._selector_channel(self.line_channel_selector),
            "line_pass": self.line_pass_selector.currentText(),
        }

    def reset_for_mode(self, mode: ScanModeConfig) -> None:
        self.latest_images = {}
        self.latest_lines = {}
        self.display_count.setValue(min(8, max(1, mode.default_display_count)))
        self.set_display_count(self.display_count.value())
        self.sync_channel_selectors(mode.channel_names)
        self.assign_default_view_channels(mode)

    def show_image(self, images: object, *, refresh_all: bool = False) -> None:
        self.latest_images = {
            scan_pass: {
                name: np.asarray(values, dtype=float)
                for name, values in dict(channels).items()
            }
            for scan_pass, channels in dict(images).items()
        }
        channel_names = self.available_image_channels()
        self.sync_channel_selectors(channel_names)
        if refresh_all:
            self.refresh_image_views()

    def sync_scan_channels(self, channels: object) -> None:
        """Keep image and line selectors aligned with scan checkboxes."""

        names = [str(channel) for channel in channels]
        if not names:
            names = list(self.current_mode.default_channels[:1])
        self.sync_channel_selectors(names)
        self.refresh_image_views()
        self.refresh_line_channel()

    def show_line(self, line_index: int, data: object) -> None:
        self.latest_lines = {}
        changed_pairs: set[tuple[str, str]] = set()
        for channel, values in dict(data).items():
            if isinstance(values, dict):
                for scan_pass, pass_values in values.items():
                    self.latest_lines.setdefault(scan_pass, {})[channel] = np.asarray(pass_values, dtype=float)
                    changed_pairs.add((scan_pass, channel))
            else:
                self.latest_lines.setdefault("trace", {})[channel] = np.asarray(values, dtype=float)
                changed_pairs.add(("trace", channel))
        self.refresh_image_views(changed_pairs)
        self.refresh_line_channel()
        self._log_callback(f"Line {line_index + 1} received ({', '.join(self.available_line_channels())})")

    def refresh_image_views(self, changed_pairs: set[tuple[str, str]] | None = None) -> None:
        for view in self.channel_views:
            selector = view["selector"]
            pass_selector = view["pass_selector"]
            image_item = view["image_item"]
            if (
                not isinstance(selector, QComboBox)
                or not isinstance(pass_selector, QComboBox)
                or not isinstance(image_item, pg.ImageItem)
            ):
                continue
            channel = self._selector_channel(selector)
            scan_pass = pass_selector.currentText()
            if changed_pairs is not None and (scan_pass, channel) not in changed_pairs:
                continue
            if scan_pass in self.latest_images and channel in self.latest_images[scan_pass]:
                self.set_image(view, self.display_image_for_view(view, self.latest_images[scan_pass][channel]))

    def display_image_for_view(self, view: dict[str, object], image: np.ndarray) -> np.ndarray:
        flatten_selector = view.get("flatten_selector")
        mode = flatten_selector.currentText() if isinstance(flatten_selector, QComboBox) else "Raw"
        if mode == "Line Mean":
            return self.subtract_line_mean(image)
        if mode == "Plane":
            return self.subtract_plane(image)
        return image

    @staticmethod
    def subtract_line_mean(image: np.ndarray) -> np.ndarray:
        arr = np.asarray(image, dtype=float).copy()
        finite = np.isfinite(arr)
        counts = finite.sum(axis=1, keepdims=True)
        sums = np.where(finite, arr, 0.0).sum(axis=1, keepdims=True)
        means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
        arr[finite] -= np.repeat(means, arr.shape[1], axis=1)[finite]
        return arr

    @staticmethod
    def subtract_plane(image: np.ndarray) -> np.ndarray:
        arr = np.asarray(image, dtype=float).copy()
        yy, xx = np.indices(arr.shape)
        mask = np.isfinite(arr)
        if mask.sum() < 3:
            return arr
        design = np.column_stack([xx[mask], yy[mask], np.ones(mask.sum())])
        coeffs, *_ = np.linalg.lstsq(design, arr[mask], rcond=None)
        plane = coeffs[0] * xx + coeffs[1] * yy + coeffs[2]
        arr[mask] -= plane[mask]
        return arr

    def refresh_line_channel(self) -> None:
        channel = self._selector_channel(self.line_channel_selector)
        scan_pass = self.line_pass_selector.currentText()
        if scan_pass in self.latest_lines and channel in self.latest_lines[scan_pass]:
            self.line_curve.setData(self.latest_lines[scan_pass][channel])

    def set_image(self, view: dict[str, object], image: np.ndarray) -> None:
        image_item = view.get("image_item")
        if not isinstance(image_item, pg.ImageItem):
            return
        xc, yc, width, height = self._geometry_provider()
        raw = np.asarray(image, dtype=float)
        levels = self._levels_for_view(view, raw)
        arr = np.nan_to_num(raw, nan=levels[0], posinf=levels[1], neginf=levels[0])
        image_item.setRect(QRectF(xc - width / 2.0, yc - height / 2.0, width, height))
        image_item.setImage(arr.T, autoLevels=False, levels=levels)
        histogram = view.get("histogram")
        if isinstance(histogram, pg.HistogramLUTWidget):
            histogram.item.setLevels(*levels)

    def _levels_for_view(self, view: dict[str, object], image: np.ndarray) -> tuple[float, float]:
        auto = view.get("range_auto")
        auto_enabled = not isinstance(auto, QCheckBox) or auto.isChecked()
        if auto_enabled:
            levels = self._finite_min_max(image)
            if levels is None:
                levels = (0.0, 1.0)
            self._show_auto_levels(view, levels)
            return levels
        minimum = self._spin_value(view.get("range_min"), 0.0)
        maximum = self._spin_value(view.get("range_max"), 1.0)
        if maximum <= minimum:
            maximum = minimum + 1e-12
        return float(minimum), float(maximum)

    def _show_auto_levels(self, view: dict[str, object], levels: tuple[float, float]) -> None:
        minimum_spin = view.get("range_min")
        maximum_spin = view.get("range_max")
        if not isinstance(minimum_spin, QDoubleSpinBox) or not isinstance(maximum_spin, QDoubleSpinBox):
            return
        minimum, maximum = levels
        minimum_spin.blockSignals(True)
        maximum_spin.blockSignals(True)
        minimum_spin.setValue(minimum)
        maximum_spin.setValue(maximum)
        minimum_spin.blockSignals(False)
        maximum_spin.blockSignals(False)

    def _range_metadata(self, view: dict[str, object]) -> dict[str, float | str]:
        auto = view.get("range_auto")
        mode = "auto" if not isinstance(auto, QCheckBox) or auto.isChecked() else "manual"
        return {
            "mode": mode,
            "min": self._spin_value(view.get("range_min"), 0.0),
            "max": self._spin_value(view.get("range_max"), 1.0),
        }

    @staticmethod
    def _spin_value(widget: object, default: float) -> float:
        if isinstance(widget, QDoubleSpinBox):
            return float(widget.value())
        return float(default)

    @staticmethod
    def _finite_min_max(image: np.ndarray) -> tuple[float, float] | None:
        finite = image[np.isfinite(image)]
        if finite.size == 0:
            return None
        minimum = float(np.min(finite))
        maximum = float(np.max(finite))
        if maximum <= minimum:
            maximum = minimum + 1e-12
        return minimum, maximum

    def sync_channel_selectors(self, channels: object) -> None:
        names = list(channels)
        for selector in [self.line_channel_selector, *self.image_selectors()]:
            current = self._selector_channel(selector)
            existing = [self._item_channel(selector, i) for i in range(selector.count())]
            if names == existing:
                self._refresh_selector_labels(selector)
                continue
            selector.blockSignals(True)
            selector.clear()
            for name in names:
                selector.addItem(self._display_channel_name(name), name)
            if current in names:
                self._set_selector_channel(selector, current)
            selector.blockSignals(False)

    def assign_default_view_channels(self, mode: ScanModeConfig) -> None:
        for index, selector in enumerate(self.image_selectors()):
            if index < len(mode.channel_names):
                self._set_selector_channel(selector, mode.channel_names[index])
        if mode.channel_names:
            self._set_selector_channel(self.line_channel_selector, mode.channel_names[0])
        self.line_pass_selector.setCurrentText("trace")

    def set_channel_aliases(self, aliases: dict[str, str]) -> None:
        self.channel_aliases = dict(aliases)
        self.sync_channel_selectors(self.available_image_channels() or self.current_mode.channel_names)
        self.refresh_image_views()
        self.refresh_line_channel()

    def _display_channel_name(self, channel: str) -> str:
        return self.channel_aliases.get(channel, channel)

    def _selector_channel(self, selector: QComboBox) -> str:
        data = selector.currentData()
        if data is not None:
            return str(data)
        return selector.currentText()

    def _item_channel(self, selector: QComboBox, index: int) -> str:
        data = selector.itemData(index)
        if data is not None:
            return str(data)
        return selector.itemText(index)

    def _set_selector_channel(self, selector: QComboBox, channel: str) -> None:
        index = selector.findData(channel)
        if index >= 0:
            selector.setCurrentIndex(index)
            return
        selector.setCurrentText(channel)

    def _refresh_selector_labels(self, selector: QComboBox) -> None:
        current = self._selector_channel(selector)
        selector.blockSignals(True)
        for index in range(selector.count()):
            channel = self._item_channel(selector, index)
            selector.setItemText(index, self._display_channel_name(channel))
        self._set_selector_channel(selector, current)
        selector.blockSignals(False)

    def set_display_count(self, count: int) -> None:
        while len(self.channel_views) > count:
            view = self.channel_views.pop()
            widget = view["widget"]
            if isinstance(widget, QWidget):
                self.image_grid.removeWidget(widget)
                widget.deleteLater()
        while len(self.channel_views) < count:
            index = len(self.channel_views)
            self.channel_views.append(create_channel_view(self, index))
        self.relayout_channel_views()
        self.sync_channel_selectors(self.available_image_channels() or self.current_mode.channel_names)
        self.refresh_image_views()

    def show_colormap_menu(self, histogram: pg.HistogramLUTWidget, position) -> None:
        menu = QMenu()
        for name in self.COLORMAPS:
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, cmap=name, hist=histogram: self.apply_colormap(hist, cmap))
        menu.exec(histogram.mapToGlobal(position))

    def apply_colormap(self, histogram: pg.HistogramLUTWidget, name: str) -> None:
        try:
            cmap = pg.colormap.get(name)
        except Exception as exc:
            self._log_callback(f"Could not load colormap {name}: {exc}")
            return
        histogram.item.gradient.setColorMap(cmap)
        for view in self.channel_views:
            if view.get("histogram") is histogram:
                view["colormap"] = name
                break

    def relayout_channel_views(self) -> None:
        for view in self.channel_views:
            widget = view["widget"]
            if isinstance(widget, QWidget):
                self.image_grid.removeWidget(widget)
        count = max(1, len(self.channel_views))
        columns = min(2, math.ceil(math.sqrt(count)))
        for index, view in enumerate(self.channel_views):
            widget = view["widget"]
            if isinstance(widget, QWidget):
                self.image_grid.addWidget(widget, index // columns, index % columns)
        for row in range(math.ceil(count / columns)):
            self.image_grid.setRowStretch(row, 1)
        for column in range(columns):
            self.image_grid.setColumnStretch(column, 1)
        self.sync_plot_links()
        if self.shared_roi_rect is not None:
            self.refresh_shared_roi_items()

    def image_selectors(self) -> list[QComboBox]:
        return [view["selector"] for view in self.channel_views if isinstance(view.get("selector"), QComboBox)]

    def image_pass_selectors(self) -> list[QComboBox]:
        return [view["pass_selector"] for view in self.channel_views if isinstance(view.get("pass_selector"), QComboBox)]

    def image_flatten_selectors(self) -> list[QComboBox]:
        return [
            view["flatten_selector"]
            for view in self.channel_views
            if isinstance(view.get("flatten_selector"), QComboBox)
        ]

    def available_image_channels(self) -> list[str]:
        names: list[str] = []
        for channels in self.latest_images.values():
            for channel in channels:
                if channel not in names:
                    names.append(channel)
        return names

    def available_line_channels(self) -> list[str]:
        names: list[str] = []
        for channels in self.latest_lines.values():
            for channel in channels:
                if channel not in names:
                    names.append(channel)
        return names

    def set_shared_roi_from_points(self, x0: float, y0: float, x1: float, y1: float) -> None:
        left = min(x0, x1)
        top = min(y0, y1)
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        if width <= 0 or height <= 0:
            return
        self.shared_roi_rect = QRectF(left, top, width, height)
        self.refresh_shared_roi_items()

    def refresh_shared_roi_items(self) -> None:
        if self.shared_roi_rect is None:
            return
        for view in self.channel_views:
            plot = view.get("plot")
            if not isinstance(plot, pg.PlotWidget):
                continue
            roi = view.get("roi_item")
            if roi is None:
                roi = pg.RectROI(
                    [self.shared_roi_rect.x(), self.shared_roi_rect.y()],
                    [self.shared_roi_rect.width(), self.shared_roi_rect.height()],
                    pen=pg.mkPen("#ffd43b", width=2),
                    movable=False,
                    removable=False,
                )
                roi.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                roi.setZValue(20)
                plot.addItem(roi)
                view["roi_item"] = roi
            roi.setPos([self.shared_roi_rect.x(), self.shared_roi_rect.y()])
            roi.setSize([self.shared_roi_rect.width(), self.shared_roi_rect.height()])

    def load_roi_into_scan_parameters(self) -> None:
        if self.shared_roi_rect is None:
            return
        rect = self.shared_roi_rect.normalized()
        self._roi_callback(rect)
        self._log_callback(
            "Loaded ROI into scan parameters: "
            f"xc={rect.center().x():.3f} V, yc={rect.center().y():.3f} V, "
            f"width={rect.width():.3f} V, height={rect.height():.3f} V"
        )
        self.clear_shared_roi()

    def clear_shared_roi(self) -> None:
        self.shared_roi_rect = None
        for view in self.channel_views:
            plot = view.get("plot")
            roi = view.get("roi_item")
            if isinstance(plot, pg.PlotWidget) and roi is not None:
                plot.removeItem(roi)
            view["roi_item"] = None

    def sync_plot_links(self) -> None:
        if not self.channel_views:
            return
        first_plot = self.channel_views[0].get("plot")
        if not isinstance(first_plot, pg.PlotWidget):
            return
        for view in self.channel_views[1:]:
            plot = view.get("plot")
            if isinstance(plot, pg.PlotWidget):
                plot.setXLink(first_plot)
                plot.setYLink(first_plot)

    def show_probe_position(self, x: float, y: float) -> None:
        self.position_label.setText(f"{x:.3f}, {y:.3f} V")

    def _show_colormap_menu(self, histogram: pg.HistogramLUTWidget, position) -> None:
        self.show_colormap_menu(histogram, position)

    def _apply_colormap(self, histogram: pg.HistogramLUTWidget, name: str) -> None:
        self.apply_colormap(histogram, name)

    def _refresh_image_views(self) -> None:
        self.refresh_image_views()

    def _set_view_auto_range(self, index: int, checked: bool) -> None:
        if index < 0 or index >= len(self.channel_views):
            return
        view = self.channel_views[index]
        for key in ("range_min", "range_max"):
            widget = view.get(key)
            if isinstance(widget, QDoubleSpinBox):
                widget.setEnabled(not checked)
        self.refresh_image_views()

    def _set_shared_roi_from_points(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.set_shared_roi_from_points(x0, y0, x1, y1)

    def _load_roi_into_scan_parameters(self) -> None:
        self.load_roi_into_scan_parameters()

    def _clear_shared_roi(self) -> None:
        self.clear_shared_roi()


__all__ = ["ChannelImagesModule"]
