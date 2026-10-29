from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from qcodes.instrument import Instrument

from afm_gui.core.mim import MIMAcquisition, recommend_time_constant, settling_factor
from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.scan_geometry import generate_scan_lines
from afm_gui.device.adapters.srs import SRSLockinAdapter
from afm_gui.device.scan_device import _AdapterScanWorker, AdapterScannerDevice
from afm_gui.ui.main_window import MainWindow
from test_fm_afm import FakeHF2


class SR830Instrument:
    def __init__(self, value=1.234567890123e-6):
        self.value = value
        self.queries = []
        self.settings = {"OFLT?": "0", "OFSL?": "3", "ISRC?": "0", "SYNC?": "0",
                         "FREQ?": "1000", "HARM?": "1", "SENS?": "10", "RMOD?": "1",
                         "PHAS?": "0", "OEXP? 1": "0.0,0", "LIAS?": "0"}

    def ask(self, command):
        self.queries.append(command)
        if command == "OUTP? 1":
            value = self.value() if callable(self.value) else self.value
            return str(value)
        return self.settings[command]


def srs(address="GPIB0::8::INSTR", value=1.234567890123e-6):
    return SRSLockinAdapter(SR830Instrument(value), {"model": "SR830", "address": address})


def scan_config(**kwargs):
    return replace(ScanConfig(xc=2.5, yc=2.5, width=0.002, height=0.002, pixels=3, lines=2,
                              linear=100, t_sample=0.0002, t_settle=0, t_rest=0, scan_mode="mim",
                              channels=("auxout3", "auxout4", "sr830_I", "sr830_Q"),
                              xy_unit="V", volts_per_nm_x=1, volts_per_nm_y=1), **kwargs)


class MIMCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settling_targets_and_discrete_limits(self):
        self.assertAlmostEqual(settling_factor(6), -math.log(0.01), places=10)
        self.assertAlmostEqual(settling_factor(24), 10.0451175, places=6)
        answer = recommend_time_constant(2.56, 256, 24)
        self.assertAlmostEqual(answer["recommended_tau_s"], 0.0003)
        self.assertLessEqual(answer["settling_s"], 0.01)
        short = recommend_time_constant(2.56, 256, 24, dwell_s=0.001)
        self.assertAlmostEqual(short["recommended_tau_s"], 30e-6)
        self.assertIsNone(recommend_time_constant(0.001, 256, 24)["recommended_tau_s"])
        self.assertIsNone(recommend_time_constant(1, 256, dwell_s=0)["recommended_tau_s"])
        for args in ((math.nan, 256), (0, 256), (1, 0), (1, 256, 7)):
            with self.assertRaises(ValueError):
                recommend_time_constant(*args)

    def test_native_x_one_query_no_rounding_no_retry(self):
        adapter = srs()
        self.assertEqual(adapter.read_x(), 1.234567890123e-6)
        self.assertEqual(adapter.instrument.queries, ["OUTP? 1"])
        adapter.instrument.value = "nan"
        with self.assertRaises(ValueError):
            adapter.read_x()
        adapter.instrument.value = "broken"
        with self.assertRaises(ValueError):
            adapter.read_x()
        self.assertEqual(len(adapter.instrument.queries), 3)

    def test_two_instruments_and_addresses_must_be_distinct(self):
        i = srs()
        with self.assertRaisesRegex(ValueError, "distinct"):
            MIMAcquisition(FakeHF2(), i, i)
        for address in ("GPIB::8", "gpib0::08::INSTR", "GPIB0::8::0::INSTR"):
            with self.assertRaisesRegex(ValueError, "same GPIB"):
                MIMAcquisition(FakeHF2(), i, srs(address))
        with self.assertRaisesRegex(ValueError, "GPIB"):
            MIMAcquisition(FakeHF2(), i, srs("COM3"))

    def test_preflight_readonly_settings_and_warnings(self):
        hf2, i, q = FakeHF2(), srs(), srs("GPIB0::9::INSTR")
        acquisition = MIMAcquisition(hf2, i, q)
        log = []
        acquisition.prepare(scan_config(t_sample=0), log.append)
        self.assertEqual(len(log), 2)
        self.assertAlmostEqual(acquisition.settings["sr830_I"]["time_constant_s"], 10e-6)
        self.assertEqual(hf2.daq.writes, [])
        self.assertTrue(all("?" in command for command in i.instrument.queries + q.instrument.queries))
        i.instrument.settings["ISRC?"] = "2"
        with self.assertRaisesRegex(RuntimeError, "voltage input"):
            acquisition.prepare(scan_config(), log.append)

    def test_pixel_queries_only_selected_x_and_aux(self):
        hf2, i, q = FakeHF2(), srs(), srs("GPIB0::9::INSTR", -2.123456789e-6)
        acquisition = MIMAcquisition(hf2, i, q)
        sample = acquisition(("auxout3", "sr830_I", "sr830_Q"))
        self.assertEqual(sample, {"auxout3": 2.6, "sr830_I": 1.234567890123e-6, "sr830_Q": -2.123456789e-6})
        self.assertEqual(i.instrument.queries, ["OUTP? 1"])
        self.assertEqual(q.instrument.queries, ["OUTP? 1"])
        self.assertEqual(len(hf2.daq.batch_reads), 1)
        self.assertEqual(acquisition.snapshot()["pixel_reads"], 1)
        self.assertGreaterEqual(acquisition.snapshot()["mean_pair_midpoint_gap_s"], 0)

    def worker(self, hf2, i, q, config=None):
        config = config or scan_config()
        acquisition = MIMAcquisition(hf2, i, q)
        worker = _AdapterScanWorker(adapter=hf2, config=config,
                                    lines=generate_scan_lines(config, ScanDirection.UP),
                                    channels=config.channels, acquisition_callback=acquisition)
        return worker, acquisition

    def test_xy_held_for_iq_retrace_alignment_and_report(self):
        hf2 = FakeHF2()
        sampled = []
        def at_xy():
            xy = hf2.read_xy()
            sampled.append(xy)
            return xy[0]
        i, q = srs(value=at_xy), srs("GPIB0::9::INSTR", at_xy)
        worker, acquisition = self.worker(hf2, i, q)
        lines, errors = [], []
        worker.line_data_ready.connect(lambda index, data: lines.append(data))
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(lines), 2)
        for data in lines:
            np.testing.assert_allclose(data["sr830_I"]["trace"], data["sr830_Q"]["trace"])
            np.testing.assert_allclose(data["sr830_I"]["trace"], data["sr830_I"]["retrace"])
        for index in range(0, len(sampled), 2):
            self.assertEqual(sampled[index], sampled[index + 1])
        self.assertEqual(acquisition.count, 12)
        self.assertEqual(worker.report_context["acquisition"]["pixel_reads"], 12)
        self.assertEqual(worker.report_context["line_timing"]["completed_lines"], 2)
        self.assertEqual({path for path, value in hf2.daq.writes}, {"auxouts/0/offset", "auxouts/1/offset"})

    def test_failed_q_keeps_previous_pairs_and_nan_at_failed_pixel(self):
        hf2, i, q = FakeHF2(), srs(), srs("GPIB0::9::INSTR")
        calls = []
        def fail_on_second():
            calls.append(1)
            if len(calls) == 2:
                raise TimeoutError("GPIB timeout")
            return -1e-6
        q.instrument.value = fail_on_second
        worker, _ = self.worker(hf2, i, q)
        lines, errors = [], []
        worker.line_data_ready.connect(lambda index, data: lines.append(data))
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(len(lines), 1)
        self.assertIn("sr830_Q", errors[0])
        for key in scan_config().channels:
            self.assertTrue(math.isfinite(lines[0][key]["trace"][0]))
            self.assertTrue(np.isnan(lines[0][key]["trace"][1:]).all())
            self.assertTrue(np.isnan(lines[0][key]["retrace"]).all())
        self.assertEqual(worker.report_context["status"], "failed")
        self.assertFalse(hf2._fm_scan_active)

    def test_stop_in_q_does_not_move_xy_or_fill_future_pixels(self):
        hf2, i, q = FakeHF2(), srs(), srs("GPIB0::9::INSTR")
        worker, _ = self.worker(hf2, i, q)
        q.instrument.value = lambda: (worker.request_stop() or 7e-6)
        lines = []
        worker.line_data_ready.connect(lambda index, data: lines.append(data))
        worker.run()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["sr830_Q"]["trace"][0], 7e-6)
        self.assertTrue(np.isnan(lines[0]["sr830_Q"]["trace"][1:]).all())
        self.assertEqual(worker.report_context["status"], "stopped")

    def test_overload_preflight_no_xy_writes_and_line_overload_excluded(self):
        hf2, i, q = FakeHF2(), srs(), srs("GPIB0::9::INSTR")
        q.instrument.settings["LIAS?"] = "1"
        worker, _ = self.worker(hf2, i, q)
        worker.run()
        self.assertEqual(worker.report_context["status"], "failed")
        self.assertEqual(hf2.daq.writes, [])
        q.instrument.settings["LIAS?"] = "0"
        def overload():
            q.instrument.settings["LIAS?"] = "4"
            return 1e-6
        q.instrument.value = overload
        worker, _ = self.worker(hf2, i, q)
        lines = []
        worker.line_data_ready.connect(lambda index, data: lines.append(data))
        worker.run()
        self.assertTrue(all(np.isnan(values).all() for passes in lines[0].values() for values in passes.values()))
        self.assertEqual(worker.report_context["status"], "failed")

    def test_mim_never_falls_back_to_mock(self):
        device = AdapterScannerDevice(lambda: None)
        config = scan_config()
        with self.assertRaises(RuntimeError):
            device.validate_scan(config, generate_scan_lines(config, ScanDirection.UP))
        from afm_gui.cli import main
        with self.assertRaisesRegex(SystemExit, "GUI"):
            main(["scan", "--mode", "mim"])


class MIMGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Instrument.close_all()
        self.window = MainWindow()
        self.output = tempfile.TemporaryDirectory()
        self.window.auto_save_dir.setText(self.output.name)
        self.window.auto_save_enabled.setChecked(False)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.output.cleanup()
        Instrument.close_all()

    def wait_until(self, condition):
        loop, timer = QEventLoop(), QTimer()
        timer.timeout.connect(lambda: loop.quit() if condition() else None)
        timer.start(10)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        timer.stop()
        self.assertTrue(condition())

    def mim_mode(self):
        scan = self.window.scan_module
        scan.scan_mode.setCurrentIndex(scan.scan_mode.findData("mim"))
        return scan

    def connect(self, name, adapter):
        handle = self.window.device_manager.handles[name]
        handle.connected, handle.adapter = True, adapter
        self.window.device_manager.devices_changed.emit()

    def test_mode_hides_stops_monitor_advisor_is_local_and_default_views(self):
        self.connect("zurich_HF2LI", FakeHF2())
        monitor = self.window.fm_afm_module
        monitor.start_monitor()
        self.wait_until(lambda: bool(monitor.latest))
        scan = self.mim_mode()
        self.wait_until(lambda: not monitor.busy)
        self.assertEqual(self.window.fm_mim_stack.currentWidget(), self.window.mim_module.widget)
        monitor.start_monitor()
        self.assertFalse(monitor.busy)
        self.assertEqual(scan.selected_channels(), ("auxout3", "auxout4", "sr830_I", "sr830_Q"))
        self.assertEqual([selector.currentData() for selector in self.window.channel_images_module.image_selectors()],
                         list(scan.selected_channels()))
        advisor = self.window.mim_module
        scan.t_sample.setValue(0.001)
        self.assertAlmostEqual(advisor.recommendation["recommended_tau_s"], 30e-6)
        advisor.follow_scan.setChecked(False)
        advisor.pixels.setValue(256)
        advisor.line_seconds.setValue(2.56)
        self.assertAlmostEqual(advisor.recommendation["recommended_tau_s"], 300e-6)

    def test_missing_role_refused_before_scanner_moves(self):
        hf2 = FakeHF2()
        self.connect("zurich_HF2LI", hf2)
        self.mim_mode()
        self.window.scan_up.click()
        self.assertFalse(self.window.controller.is_running)
        self.assertEqual(hf2.daq.writes, [])
        self.assertIn("Connect sr830_I", self.window.log.toPlainText())

    def test_single_sr830_requires_only_selected_channel(self):
        hf2 = FakeHF2()
        self.connect("zurich_HF2LI", hf2)
        scan = self.mim_mode()
        for selected, other, address in (("sr830_I", "sr830_Q", "GPIB0::8::INSTR"),
                                         ("sr830_Q", "sr830_I", "GPIB0::9::INSTR")):
            self.connect(selected, srs(address))
            scan.channel_checks[selected].setChecked(True)
            scan.channel_checks[other].setChecked(False)
            acquisition = self.window._scan_acquisition_callback()
            self.assertEqual(set(acquisition.adapters), {selected})
            acquisition.prepare(scan.config(), lambda message: None)
            self.assertTrue(math.isfinite(acquisition(scan.selected_channels())[selected]))

    def test_scan_export_float64_and_gsf_metadata_timing(self):
        self.connect("zurich_HF2LI", FakeHF2())
        self.connect("sr830_I", srs())
        self.connect("sr830_Q", srs("GPIB0::9::INSTR", -2.1234567890123e-6))
        scan = self.mim_mode()
        scan.pixels.setValue(3)
        scan.lines.setValue(2)
        scan.width.setValue(0.002)
        scan.height.setValue(0.002)
        scan.linear.setValue(100)
        scan.t_sample.setValue(0.0002)
        scan.t_settle.setValue(0)
        scan.t_rest.setValue(0)
        self.window.scan_up.click()
        self.wait_until(lambda: not self.window.controller.is_running)
        context = self.window.controller.scan_report_context
        self.assertEqual(context["status"], "completed")
        self.assertEqual(context["acquisition"]["pixel_reads"], 12)
        self.assertIn("Mean pixel I/O", self.window.mim_module.measured.text())
        exported = self.window.controller.export_gsf_bundle(self.output.name, scan.current_mode)
        self.assertEqual(len(exported), 9)
        with np.load(Path(self.output.name) / "raw.npz") as raw:
            self.assertEqual(raw["trace__sr830_I"].dtype, np.float64)
            self.assertEqual(raw["trace__sr830_I"][0, 0], 1.234567890123e-6)
        metadata = json.loads((Path(self.output.name) / "metadata.json").read_text(encoding="utf-8"))
        self.assertIn("OUTP? 1", json.dumps(metadata))
        self.assertEqual(metadata["data"]["raw_float64_archive"], "raw.npz")
        self.assertIn(b"ZUnits = V", (Path(self.output.name) / "sr830_Q_trace.gsf").read_bytes())
        # Preparing another mode must not relabel the previous scan on export.
        scan.scan_mode.setCurrentIndex(scan.scan_mode.findData("fm_afm"))
        self.window.controller.export_gsf_bundle(self.output.name, scan.current_mode, file_prefix="after_switch")
        self.assertIn(b"ZUnits = V", (Path(self.output.name) / "after_switch_sr830_Q_trace.gsf").read_bytes())
        previous = json.loads((Path(self.output.name) / "after_switch_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(previous["scan"]["mode"]["name"], "mim")
        self.assertIn("MIM", previous["scan"]["mode"]["label"])

    def test_generic_lockin_read_and_apply_blocked_during_scan(self):
        self.mim_mode()
        i = srs()
        self.connect("sr830_I", i)
        self.window.device_manager.assign_function("lockin", "sr830_I")
        self.window.device_module.set_hardware_locked(True)
        self.window.lockin_module.apply_settings("ch1")
        self.window.lockin_module.read("ch1")
        self.assertEqual(i.instrument.queries, [])
        self.assertFalse(self.window.lockin_module.lockin_channels["ch1"]["apply"].isEnabled())
        self.window.device_module.set_hardware_locked(False)
