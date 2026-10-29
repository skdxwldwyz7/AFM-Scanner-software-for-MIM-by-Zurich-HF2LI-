from __future__ import annotations

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from afm_gui.core.mim import MIMAcquisition, MIM_ROUTES, recommend_time_constant


def seconds(value):
    if value is None:
        return "N/A"
    for scale, unit in ((1e-6, "µs"), (1e-3, "ms"), (1, "s")):
        if value < scale * 1000 or scale == 1:
            return f"{value / scale:.5g} {unit}"


class MIMModule(QObject):
    """Local advisor and explicit device roles; no background monitor or I/O."""
    def __init__(self, manager, scan_module, parent=None):
        super().__init__(parent)
        self.manager, self.scan = manager, scan_module
        self.last_acquisition = {}
        content = QWidget()
        layout = QVBoxLayout(content)
        description = QLabel(
            "MIM = FM scan + two SR830 X readings\n"
            "HF2 AUX1/2: XY; AUX3: Z; AUX4: Δf.\n"
            "I and Q each use OUTP? 1 from a separate GPIB instrument. "
            "Assign MIM I / MIM Q and edit addresses in Device Manager."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.connections = QLabel()
        self.connections.setWordWrap(True)
        layout.addWidget(self.connections)
        box = QGroupBox("SR830 time constant advisor / 时间常数建议")
        form = QFormLayout(box)
        self.follow_scan = QCheckBox("Follow Scan Parameters")
        self.follow_scan.setChecked(True)
        self.line_seconds = QDoubleSpinBox()
        self.line_seconds.setDecimals(6)
        self.line_seconds.setRange(0.000001, 1e9)
        self.line_seconds.setSuffix(" s / pass")
        self.pixels = QSpinBox()
        self.pixels.setRange(1, 4096)
        self.slope = QComboBox()
        for slope in (6, 12, 18, 24):
            self.slope.addItem(f"{slope} dB/oct", slope)
        self.slope.setCurrentIndex(3)
        self.fraction = QComboBox()
        for text, value in (("95%", 0.95), ("99%", 0.99), ("99.9%", 0.999)):
            self.fraction.addItem(text, value)
        self.fraction.setCurrentIndex(1)
        form.addRow(self.follow_scan)
        form.addRow("Active line time (one pass)", self.line_seconds)
        form.addRow("Pixels / pass", self.pixels)
        form.addRow("Filter slope", self.slope)
        form.addRow("Step response target", self.fraction)
        self.result = QLabel()
        self.result.setWordWrap(True)
        form.addRow(self.result)
        layout.addWidget(box)
        notes = QLabel(
            "Linked timing excludes Settle, Rest and communication overhead. "
            "This scanner moves then waits: recommendations are limited to Sample, "
            "the stable wait after reaching each pixel. A slower GPIB bus does not "
            "justify a larger time constant for the first I reading.\n\n"
            "Manual timing uses active line time / pixels as an assumed dwell budget; "
            "exclude turnaround and rest. The selected τ is the largest standard "
            "SR830 setting within that budget.\n\n"
            "Advice assumes ordinary cascaded RC filtering with Sync OFF. "
            "Verify actual slope and τ on BOTH SR830s; high reserve/expand can limit "
            "the minimum τ. The scan reads actual settings and logs settling warnings. "
            "This target describes filter settling, not absolute measurement accuracy. "
            "Set sensitivity/reference/phase on the instruments; this panel only advises."
        )
        notes.setWordWrap(True)
        layout.addWidget(notes)
        self.measured = QLabel("Last MIM scan: no timing measurement yet")
        self.measured.setWordWrap(True)
        layout.addWidget(self.measured)
        layout.addStretch()
        self.widget = QScrollArea()
        self.widget.setWidgetResizable(True)
        self.widget.setWidget(content)
        self.widget.setMinimumWidth(310)
        for control in (self.follow_scan, self.slope, self.fraction):
            if isinstance(control, QCheckBox):
                control.toggled.connect(self.refresh)
            else:
                control.currentIndexChanged.connect(self.refresh)
        self.line_seconds.valueChanged.connect(self.refresh)
        self.pixels.valueChanged.connect(self.refresh)
        for control in (self.scan.width, self.scan.linear, self.scan.pixels, self.scan.t_sample):
            control.valueChanged.connect(self.refresh)
        self.manager.devices_changed.connect(self.refresh_connections)
        self.refresh_connections()
        self.refresh()

    def refresh_connections(self):
        lines = []
        for key, function in MIM_ROUTES.items():
            handle = self.manager.handle_for_function(function) if function in self.manager.functions else None
            if handle is None:
                lines.append(f"{key}: unassigned")
            else:
                address = handle.config.connection.get("address", "no address")
                lines.append(f"{key} ← {handle.config.name}\n{address} / "
                             f"{'Connected' if handle.connected else 'Disconnected'}")
        self.connections.setText("\n".join(lines))

    def acquisition(self, hf2):
        adapters = {}
        for key, function in MIM_ROUTES.items():
            if key not in self.scan.selected_channels():
                continue
            if function not in self.manager.functions:
                raise RuntimeError(f"Device config is missing the {function} function; load the MIM device config")
            adapter = self.manager.adapter_for_function(function)
            if adapter is None:
                raise RuntimeError(f"Connect {key} and assign {function} in Device Manager before MIM scanning")
            adapters[key] = adapter
        return MIMAcquisition(hf2, adapters.get("sr830_I"), adapters.get("sr830_Q"))

    def refresh(self, *_args):
        linked = self.follow_scan.isChecked()
        self.line_seconds.setEnabled(not linked)
        self.pixels.setEnabled(not linked)
        if linked:
            active = self.scan.width.value() / max(self.scan.linear.value(), 1e-12)
            active += self.scan.pixels.value() * self.scan.t_sample.value()
            for widget, value in ((self.line_seconds, active), (self.pixels, self.scan.pixels.value())):
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self.recommendation = recommend_time_constant(
            self.line_seconds.value(), self.pixels.value(), self.slope.currentData(),
            self.fraction.currentData(), dwell_s=self.scan.t_sample.value() if linked else None,
        )
        result = self.recommendation
        tau = result["recommended_tau_s"]
        message = (f"Recommended τ: {seconds(tau)}\n"
                   f"Estimated settling: {seconds(result['settling_s'])}") if tau is not None else (
                       "No standard τ fits: increase Sample / pixel dwell; even 10 µs is too long.")
        self.result.setText(
            f"Time / pixel: {seconds(result['pixel_interval_s'])}\n"
            f"Settling budget: {seconds(result['settling_budget_s'])}\n"
            f"τ ≤ {seconds(result['tau_limit_s'])} ({result['settling_factor']:.3f} × τ)\n" + message
        )

    def show_report(self, report):
        if "acquisition" not in report:
            return
        self.last_acquisition = dict(report["acquisition"])
        reading = self.last_acquisition
        lines = report.get("line_timing", {})
        settings = reading.get("settings_at_start", {})
        actual = "\n".join(f"{key}: τ {seconds(item['time_constant_s'])}, {item['slope_db']} dB/oct"
                           for key, item in settings.items())
        self.measured.setText(
            f"MIM scan ({report.get('status', '')}):\n{actual}\n"
            f"Mean full line (trace + retrace): {seconds(lines.get('mean_line_s'))}\n"
            f"Mean pixel I/O: {seconds(reading.get('mean_read_s'))}\n"
            f"Max pixel I/O: {seconds(reading.get('max_read_s'))}\n"
            f"Mean I/Q query midpoint gap: {seconds(reading.get('mean_pair_midpoint_gap_s'))}\n"
            "Host timing only; the two instruments are read sequentially."
        )

    def snapshot(self):
        return {"advisor": dict(self.recommendation), "follow_scan": self.follow_scan.isChecked(),
                "roles": dict(MIM_ROUTES), "query": "OUTP? 1", "sync_filter_assumed": False}
