from __future__ import annotations

import pyqtgraph as pg


def build_line_plot_panel(window) -> pg.PlotWidget:
    plot = pg.PlotWidget()
    plot.setMaximumHeight(180)
    window.line_curve = plot.plot(pen=pg.mkPen("#1f77b4", width=2))
    plot.setLabel("bottom", "Pixel")
    plot.setLabel("left", "Signal")
    return plot
