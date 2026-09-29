from __future__ import annotations

from dataclasses import replace
import csv
import math
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="afm_fm_test_"))

import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from qcodes.instrument import Instrument

from afm_gui.core.fm_afm import FM_CHANNELS, FMAcquisition
from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.scan_geometry import generate_scan_lines
from afm_gui.core.xy_motion import ramp_xy
from afm_gui.device.adapters.hf2_fm import HF2FMInterface
from afm_gui.device.adapters.zurich import ZurichHF2LIAdapter
from afm_gui.device.scan_device import _AdapterScanWorker
from afm_gui.ui.main_window import MainWindow


class FakeDAQ:
    def __init__(self):
        self.values = {
            "plls/0/enable": 1, "plls/0/locked": 1, "plls/0/demodselect": 2,
            "plls/0/oscselect": 1, "plls/0/freqdelta": -1.25,
            "plls/0/error": 0.1, "plls/0/freqcenter": 32768,
            "plls/0/freqrange": 10, "plls/0/setpoint": 90,
            "oscs/1/freq": 32766.75,
            "auxins/0/values/0": -0.125, "auxins/0/values/1": 0.01,
            "pids/0/enable": 1, "pids/0/input": 4, "pids/0/inputchannel": 0,
            "pids/0/output": 3, "pids/0/outputchannel": 2,
            "pids/0/error": 0.001, "pids/0/shift": 0.1,
            "pids/0/center": 2.5, "pids/0/range": 0.5,
            "pids/0/setpoint": -0.124,
            "auxouts/0/outputselect": -1, "auxouts/1/outputselect": -1,
            "auxouts/2/outputselect": -1, "auxouts/3/outputselect": 4,
            "auxouts/0/value": 2.5, "auxouts/1/value": 2.5,
            "auxouts/2/value": 2.6, "auxouts/3/value": -0.125,
            "auxouts/0/scale": 1, "auxouts/0/offset": 0,
            "auxouts/1/scale": 1, "auxouts/1/offset": 0,
            "auxouts/2/scale": 0, "auxouts/2/offset": 0,
            "auxouts/3/scale": 0.1, "auxouts/3/offset": 0,
        }
        self.writes = []
        self.reads = []
        self.batch_calls = []
        self.batch_reads = []
        self.list_node_calls = 0

    def getDouble(self, path):
        key = path.lower().split("/", 2)[2]
        self.reads.append(key)
        return self.values[key]

    def getInt(self, path):
        return int(self.getDouble(path))

    def listNodes(self, path, flags):
        self.list_node_calls += 1
        if not flags & 2:
            raise AssertionError("PID ownership needs absolute node paths")
        return ["/dev18388/pids/0/enable"]

    def get(self, path, flat=True):
        self.batch_reads.append((path, flat))
        group = path.lower().split("/", 2)[2].removesuffix("/*")
        return {
            f"/dev18388/{node}": {"value": [value]}
            for node, value in self.values.items()
            if node.startswith(group + "/")
        }

    def set(self, updates):
        self.batch_calls.append(updates)
        for path, value in updates:
            self.setDouble(path, value)

    def setDouble(self, path, value):
        key = path.split("/", 2)[2]
        if key not in {"auxouts/0/offset", "auxouts/1/offset"}:
            raise AssertionError(f"Forbidden write: {path}")
        self.writes.append((key, value))
        self.values[key.replace("offset", "value")] = value


class FakeHF2(HF2FMInterface):
    def __init__(self):
        self.daq = FakeDAQ()
        self.session = SimpleNamespace(daq_server=self.daq)
        self.device_id = "DEV18388"
        self.connection = {"fm_afm": {"enabled": True}}
        self.capabilities = ("lockin_demod", "scanner_voltage", "fm_afm_readout")
        self.lockin_channels = ("ch1", "ch2")
        self._init_fm()
        self.demod_indices = []

    def read_demod(self, demod_index=0):
        self.demod_indices.append(demod_index)
        return {"x_v": 0.03, "y_v": 0.04, "r_v": 0.05, "phase_deg": 53.13, "frequency_hz": 32766.75}

    def snapshot(self):
        return {"adapter": "FakeHF2"}

    def close(self):
        pass


class FMAFMAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeHF2()

    def config(self):
        return ScanConfig(xc=2.5, yc=2.5, width=0.01, height=0.01, pixels=3, lines=2,
                          linear=100, t_sample=0, t_settle=0, t_rest=0,
                          scan_mode="fm_afm", channels=("auxout3", "pll_df"),
                          xy_unit="V", volts_per_nm_x=1, volts_per_nm_y=1)

    def test_snapshot_reads_real_nodes_and_never_writes(self):
        sample = self.adapter.read_fm_snapshot()
        self.assertEqual(set(sample), {c.key for c in FM_CHANNELS})
        self.assertTrue(all(math.isfinite(v) for v in sample.values()))
        self.assertEqual(sample["frequency"], 32766.75)
        self.assertEqual(sample["pll_df"], -1.25)
        self.assertAlmostEqual(sample["pid_out"], 2.6)
        self.assertEqual(sample["loopback_error"], 0)
        self.assertEqual(self.adapter.demod_indices, [2])
        self.assertGreater(len(self.adapter.daq.batch_reads), 0)
        self.assertLess(len(self.adapter.daq.reads), 10)
        self.assertEqual(self.adapter.daq.writes, [])

    def test_scan_snapshots_read_exact_nodes_and_cache_static_settings(self):
        config = self.config()
        lines = generate_scan_lines(config, ScanDirection.UP)
        self.adapter.begin_fm_scan(config, lines)
        batch_count = len(self.adapter.daq.batch_reads)
        self.adapter.daq.reads.clear()
        channels = (
            "pll_locked", "pll_enabled", "pid_enabled", "auxout3", "auxout4",
            "pll_center", "pid_center", "pid_error",
        )

        first = self.adapter.read_fm_snapshot(channels)
        second = self.adapter.read_fm_snapshot(channels)

        self.assertEqual(first, second)
        self.assertEqual(len(self.adapter.daq.batch_reads), batch_count)
        self.assertEqual(self.adapter.daq.reads.count("plls/0/locked"), 2)
        self.assertEqual(self.adapter.daq.reads.count("plls/0/enable"), 2)
        self.assertEqual(self.adapter.daq.reads.count("pids/0/enable"), 2)
        self.assertEqual(self.adapter.daq.reads.count("auxouts/2/value"), 2)
        self.assertEqual(self.adapter.daq.reads.count("auxouts/3/value"), 2)
        self.assertEqual(self.adapter.daq.reads.count("pids/0/error"), 2)
        self.assertEqual(self.adapter.daq.reads.count("plls/0/freqcenter"), 1)
        self.assertEqual(self.adapter.daq.reads.count("pids/0/center"), 1)
        self.adapter.end_fm_scan()

    def test_report_snapshot_contains_detailed_pll_pid_and_aux_nodes_read_only(self):
        report = self.adapter.read_fm_report_snapshot()
        nodes = report["nodes"]
        self.assertEqual(report["device_id"], "DEV18388")
        self.assertEqual(nodes["plls/0/freqdelta"], -1.25)
        self.assertEqual(nodes["plls/0/oscselect"], 1)
        self.assertEqual(nodes["pids/0/input"], 4)
        self.assertEqual(nodes["pids/0/outputchannel"], 2)
        self.assertEqual(nodes["auxouts/2/outputselect"], -1)
        self.assertEqual(nodes["auxouts/3/scale"], 0.1)
        self.assertEqual(report["read_errors"], {})
        self.assertEqual(self.adapter.daq.writes, [])

    def test_missing_nodes_are_nan_and_scan_fails(self):
        del self.adapter.daq.values["plls/0/freqdelta"]
        self.assertTrue(math.isnan(self.adapter.read_fm_snapshot()["pll_df"]))
        with self.assertRaisesRegex(RuntimeError, "pll_df"):
            FMAcquisition(self.adapter)(("pll_df",))

    def test_xy_only_write_allowlist_and_limits(self):
        self.adapter.set_xy_voltage(2.51, 2.49)
        self.assertEqual({p for p, _ in self.adapter.daq.writes}, {"auxouts/0/offset", "auxouts/1/offset"})
        self.assertEqual(len(self.adapter.daq.batch_calls), 1)
        self.adapter.daq.writes.clear()
        for xy in ((-0.01, 2), (2, 5.01), (math.nan, 2)):
            with self.assertRaises(ValueError):
                self.adapter.set_xy_voltage(*xy)
        with self.assertRaises(ValueError):
            self.adapter.set_axis_voltage("z", 2.5)
        self.adapter.stop()
        self.assertEqual(self.adapter.daq.writes, [])

    def test_scan_batches_xy_writes_and_rechecks_routes_at_bounded_interval(self):
        config = self.config()
        lines = generate_scan_lines(config, ScanDirection.UP)
        self.adapter.begin_fm_scan(config, lines)
        self.assertEqual(self.adapter.daq.list_node_calls, 1)

        self.adapter.set_xy_voltage(2.501, 2.502)
        self.adapter.set_xy_voltage(2.503, 2.504)
        self.assertEqual(self.adapter.daq.list_node_calls, 1)
        self.assertEqual(len(self.adapter.daq.batch_calls), 2)

        self.adapter.daq.values["auxouts/0/outputselect"] = 4
        self.adapter._last_scan_route_check -= self.adapter.SCAN_ROUTE_RECHECK_S + 0.01
        with self.assertRaisesRegex(RuntimeError, "Manual"):
            self.adapter.set_xy_voltage(2.505, 2.506)
        self.assertEqual(len(self.adapter.daq.batch_calls), 2)
        self.adapter.end_fm_scan()

    def test_manual_mode_and_pid_ownership_checked_before_writing(self):
        self.adapter.daq.values["auxouts/0/outputselect"] = 4
        with self.assertRaisesRegex(RuntimeError, "Manual"):
            self.adapter.set_xy_voltage(2.5, 2.5)
        self.adapter.daq.values["auxouts/0/outputselect"] = -1
        self.adapter.daq.values["pids/0/outputchannel"] = 0
        with self.assertRaisesRegex(RuntimeError, "owns"):
            self.adapter.set_xy_voltage(2.5, 2.5)
        self.assertEqual(self.adapter.daq.writes, [])

    def test_preflight_checks_rotated_extents_and_feedback(self):
        config = self.config()
        self.adapter.validate_fm_scan(config, generate_scan_lines(config, ScanDirection.UP))
        outside = replace(config, xc=4.99, width=0.1, height=0.1, angle=45)
        with self.assertRaises(ValueError):
            self.adapter.validate_fm_scan(outside, generate_scan_lines(outside, ScanDirection.UP))
        self.adapter.daq.values["pids/0/range"] = 3
        with self.assertRaisesRegex(RuntimeError, "Z monitor limits"):
            self.adapter.validate_fm_scan(config, generate_scan_lines(config, ScanDirection.UP))
        self.assertEqual(self.adapter.daq.writes, [])

    def test_scan_stops_on_loss_of_lock_without_writing_z(self):
        self.adapter.daq.values["plls/0/locked"] = 0
        with self.assertRaisesRegex(RuntimeError, "PLL unlocked"):
            FMAcquisition(self.adapter)(("auxout3",))
        self.assertEqual(self.adapter.daq.writes, [])

    def test_real_adapter_blocks_legacy_writes_in_fm_profile(self):
        adapter = ZurichHF2LIAdapter(self.adapter.session, object(), self.adapter.connection)
        with self.assertRaises(RuntimeError):
            adapter.set_output(amplitude=0.1)
        with self.assertRaises(RuntimeError):
            adapter.configure_demod(frequency_hz=32000)
        self.assertEqual(self.adapter.daq.writes, [])

    def test_close_uses_serial_and_does_not_reset_outputs(self):
        disconnected = []
        self.adapter.session.disconnect_device = disconnected.append
        adapter = ZurichHF2LIAdapter(self.adapter.session, object(), self.adapter.connection)
        adapter.close()
        self.assertEqual(disconnected, ["dev18388"])
        self.assertEqual(self.adapter.daq.writes, [])

    def test_worker_preflight_failure_never_moves(self):
        config = self.config()
        self.adapter.daq.values["pids/0/outputchannel"] = 0
        worker = _AdapterScanWorker(adapter=self.adapter, config=config,
                                    lines=generate_scan_lines(config, ScanDirection.UP),
                                    channels=config.channels, acquisition_callback=FMAcquisition(self.adapter),
                                    report_context={})
        failures = []
        worker.failed.connect(failures.append)
        worker.run()
        self.assertTrue(failures)
        self.assertEqual(worker.report_context["status"], "failed")
        self.assertIsNotNone(worker.report_context["hardware_snapshot"])
        self.assertEqual(self.adapter.daq.writes, [])

    def test_runtime_config_is_applied_at_next_line(self):
        config = self.config()
        worker = _AdapterScanWorker(adapter=self.adapter, config=config,
                                    lines=generate_scan_lines(config, ScanDirection.UP),
                                    channels=config.channels, acquisition_callback=FMAcquisition(self.adapter),
                                    report_context={})
        seen = []
        acquire = worker._acquire_line
        def capture(index, start, end):
            seen.append(worker._config.linear)
            return acquire(index, start, end)
        worker._acquire_line = capture
        worker.line_data_ready.connect(lambda i, _d: worker.set_pending_config(replace(config, linear=200)) if i == 0 else None)
        worker.run()
        self.assertEqual(seen, [100, 200])

    def test_ramp_is_bounded_and_cancel_holds_position(self):
        stop = threading.Event()
        seen = []
        original = self.adapter.set_xy_voltage
        def setter(x, y):
            original(x, y)
            seen.append((x, y))
            if len(seen) == 2:
                stop.set()
        self.adapter.set_xy_voltage = setter
        end = ramp_xy(self.adapter, (2.5, 2.5), (2.6, 2.6), 1000, stop)
        self.assertEqual(end, seen[-1])
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(end, (2.6, 2.6))
        previous = (2.5, 2.5)
        for point in seen:
            self.assertLessEqual(math.dist(point, previous), self.adapter.xy_step_v + 1e-12)
            previous = point

    def test_worker_acquires_trace_retrace_with_only_aux_xy_writes(self):
        config = self.config()
        worker = _AdapterScanWorker(adapter=self.adapter, config=config,
                                    lines=generate_scan_lines(config, ScanDirection.UP),
                                    channels=config.channels, acquisition_callback=FMAcquisition(self.adapter))
        received, failures = [], []
        worker.line_data_ready.connect(lambda i, d: received.append(d))
        worker.failed.connect(failures.append)
        worker.run()
        self.assertEqual(failures, [])
        self.assertFalse(self.adapter._fm_scan_active)
        self.assertEqual(len(received), 2)
        self.assertEqual(worker.report_context["status"], "completed")
        self.assertEqual(worker.report_context["hardware_snapshot"]["read_errors"], {})
        np.testing.assert_allclose(received[0]["auxout3"]["trace"], 2.6)
        self.assertEqual({key for key, _ in self.adapter.daq.writes}, {"auxouts/0/offset", "auxouts/1/offset"})

    def test_retrace_is_reversed_into_image_x_order(self):
        config = self.config()
        worker = _AdapterScanWorker(adapter=self.adapter, config=config, lines=[], channels=("x",), acquisition_callback=None)
        worker._acquire_pass = lambda *args: {"x": np.array([1, 2, 3])}
        line = worker._acquire_line(0, np.array([0, 0]), np.array([1, 0]))
        np.testing.assert_array_equal(line["x"]["retrace"], [3, 2, 1])


class FMAFMGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Instrument.close_all()
        self.window = MainWindow()
        self.scan_output_dir = tempfile.TemporaryDirectory(prefix="afm_scan_report_test_")
        self.window.auto_save_dir.setText(self.scan_output_dir.name)
        self.window.auto_save_enabled.setChecked(False)
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.scan_output_dir.cleanup()
        Instrument.close_all()

    def connect_fake(self):
        adapter = FakeHF2()
        handle = self.window.device_manager.handles["zurich_HF2LI"]
        handle.connected, handle.adapter = True, adapter
        self.window.device_manager.devices_changed.emit()
        return adapter

    def test_scan_channel_selection_updates_image_selectors_immediately(self):
        scan = self.window.scan_module
        images = self.window.channel_images_module

        def selector_channels():
            return {
                selector.itemData(index)
                for selector in [images.line_channel_selector, *images.image_selectors()]
                for index in range(selector.count())
            }

        self.assertEqual(selector_channels(), set(scan.selected_channels()))
        scan.channel_checks["auxout3"].setChecked(False)
        self.app.processEvents()
        self.assertEqual(selector_channels(), set(scan.selected_channels()))
        self.assertNotIn("auxout3", selector_channels())

    def test_auto_scale_updates_image_and_colorbar_from_sampled_pixels(self):
        images = self.window.channel_images_module
        view = images.channel_views[0]
        view["range_auto"].setChecked(True)
        sampled = np.array([[2.4, 2.6], [np.nan, np.nan]], dtype=float)

        images.set_image(view, sampled)

        self.assertAlmostEqual(view["range_min"].value(), 2.4)
        self.assertAlmostEqual(view["range_max"].value(), 2.6)
        self.assertEqual(tuple(view["image_item"].getLevels()), (2.4, 2.6))
        self.assertEqual(tuple(view["histogram"].item.getLevels()), (2.4, 2.6))
        self.assertEqual(float(np.min(view["image_item"].image)), 2.4)

    def wait_until(self, condition, timeout=3000):
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: loop.quit() if condition() else None)
        poll.start(10)
        QTimer.singleShot(timeout, loop.quit)
        loop.exec()
        poll.stop()
        self.assertTrue(condition())

    def test_default_profile_and_no_disconnected_mock_scan(self):
        self.assertEqual(self.window.scan_module.current_mode.name, "fm_afm")
        self.assertEqual(self.window.device_manager.functions["scan_scanner"].device, "zurich_HF2LI")
        self.assertTrue(self.window._panel_is_visible("fm_afm"))
        self.assertFalse(self.window.lockin_module.lockin_channels["ch1"]["apply"].isEnabled())
        self.window.scan_up.click()
        self.assertFalse(self.window.controller.is_running)
        self.assertIn("Connect Zurich", self.window.log.toPlainText())

    def test_monitor_read_once_plot_history_csv_no_hardware_writes(self):
        adapter = self.connect_fake()
        module = self.window.fm_afm_module
        module.start_monitor(once=True)
        self.wait_until(lambda: not module.busy)
        self.assertEqual(module.latest["pll_df"], -1.25)
        self.assertEqual(len(module.history), 1)
        self.assertEqual(module.time_views[0][2].getData()[1][0], 2.6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.csv"
            module.write_history(path)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 2)
            self.assertIn("auxout4 [V]", rows[0])
        self.assertFalse(self.window.device_manager.hardware_locked)
        self.assertEqual(adapter.daq.writes, [])

    def test_complete_hf2_scan_exports_actual_fm_channels(self):
        adapter = self.connect_fake()
        module = self.window.scan_module
        module.pixels.setValue(2)
        module.lines.setValue(2)
        module.width.setValue(0.002)
        module.height.setValue(0.002)
        module.linear.setValue(100)
        module.t_sample.setValue(0.000001)
        module.t_settle.setValue(0)
        module.t_rest.setValue(0)
        self.window.scan_up.click()
        self.wait_until(lambda: not self.window.controller.is_running)
        self.assertNotIn("error", self.window.controller.parameter_tree.data["runtime"])
        np.testing.assert_allclose(self.window.controller.images["trace"]["auxout3"], 2.6)
        np.testing.assert_allclose(self.window.controller.images["trace"]["pll_df"], -1.25)
        reports = list(Path(self.scan_output_dir.name).glob("*_scan_report.txt"))
        self.assertEqual(len(reports), 1)
        report_text = reports[0].read_text(encoding="utf-8")
        self.assertIn('"pids/0/setpoint": -0.124', report_text)
        self.assertIn('"plls/0/freqdelta": -1.25', report_text)
        self.assertIn('"recorded": [', report_text)
        with tempfile.TemporaryDirectory() as tmp:
            files = self.window.controller.export_gsf_bundle(tmp, module.current_mode)
            self.assertTrue(any(p.name == "auxout3_trace.gsf" for p in files))
            self.assertIn(b"ZUnits = V", (Path(tmp) / "auxout3_trace.gsf").read_bytes())
        self.assertEqual({key for key, _ in adapter.daq.writes}, {"auxouts/0/offset", "auxouts/1/offset"})

    def test_invalid_feedback_cancels_continuous_sequence(self):
        adapter = self.connect_fake()
        adapter.daq.values["plls/0/locked"] = 0
        sequence = self.window.scan_sequence_module
        sequence.repeat_mode.setCurrentIndex(sequence.repeat_mode.findData("continuous"))
        self.window.scan_up.click()
        self.wait_until(lambda: not self.window.controller.is_running)
        self.assertFalse(sequence.active)
        self.assertIn("error", self.window.controller.parameter_tree.data["runtime"])
        self.assertEqual(adapter.daq.writes, [])

    def test_monitor_can_run_during_scan_and_stop_keeps_missing_pixels(self):
        adapter = self.connect_fake()
        monitor = self.window.fm_afm_module
        monitor.start_monitor()
        self.wait_until(lambda: bool(monitor.latest))
        scan = self.window.scan_module
        scan.width.setValue(0.01)
        scan.height.setValue(0.01)
        scan.pixels.setValue(32)
        scan.lines.setValue(2)
        scan.linear.setValue(1)
        scan.t_sample.setValue(0.02)
        self.window.scan_up.click()
        self.wait_until(lambda: bool(adapter.daq.writes))
        self.assertFalse(monitor.xy_move.isEnabled())
        self.window.pause.click()
        self.assertTrue(self.window.controller.is_paused)
        self.window.resume.click()
        self.assertFalse(self.window.controller.is_paused)
        self.window.stop.click()
        self.wait_until(lambda: not self.window.controller.is_running)
        self.assertTrue(self.window.device_manager.hardware_locked)
        data = self.window.controller.images["trace"]["auxout3"]
        self.assertTrue(np.isnan(data).any())
        with tempfile.TemporaryDirectory() as tmp:
            self.window.controller.export_gsf_bundle(tmp, scan.current_mode)
            raw = (Path(tmp) / "auxout3_trace.gsf").read_bytes()
            offset = raw.index(b"\0") + 1
            offset += (-offset) % 4
            self.assertTrue(np.isnan(np.frombuffer(raw[offset:], dtype='<f4')).any())
        monitor.stop_monitor()
        self.wait_until(lambda: not monitor.busy)
        self.assertFalse(self.window.device_manager.hardware_locked)
        self.assertEqual({key for key, _ in adapter.daq.writes}, {"auxouts/0/offset", "auxouts/1/offset"})
