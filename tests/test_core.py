from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="afm_gui_mpl_"))

import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from qcodes.instrument import Instrument

from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.scan_controller import ScanController
from afm_gui.core.scan_modes import load_scan_modes
from afm_gui.core.spectroscopy_config import SpectroscopyConfig
from afm_gui.core.spectroscopy_controller import SpectroscopyController
from afm_gui.core.stage_controller import StageController
from afm_gui.data.gsf import write_gsf
from afm_gui.data.spectroscopy import SpectroscopyBundle, read_spectroscopy_bundle, write_spectroscopy_bundle
from afm_gui.device.loader import DeviceManager, load_device_config_file
from afm_gui.device.mock_device import MockScannerDevice
from afm_gui.device.registry import create_driver
from afm_gui.device.scan_device import AdapterScannerDevice
from afm_gui.startup import ensure_mpl_config_dir


class CoreSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        Instrument.close_all()

    def test_default_scan_mode_uses_lockin_mode_only(self) -> None:
        registry = load_scan_modes()

        self.assertEqual(registry.default.name, "lockin")
        self.assertEqual(registry.default.default_display_count, 2)
        self.assertEqual(set(registry.modes), {"lockin"})
        self.assertEqual(registry.default.default_channels, ("lockin_x", "lockin_phase"))

    def test_lockin_scan_mode_uses_lockin_channels(self) -> None:
        registry = load_scan_modes()
        mode = registry.modes["lockin"]

        self.assertEqual(mode.label, "Lock-in Scan")
        self.assertEqual(mode.default_display_count, 2)
        self.assertEqual(mode.default_channels, ("lockin_x", "lockin_phase"))
        self.assertEqual(mode.unit_for("lockin_x"), "V")
        self.assertEqual(mode.unit_for("lockin_phase"), "deg")

    def test_device_config_loads_capability_assignments(self) -> None:
        devices, functions = load_device_config_file()
        device_by_name = {device.name: device for device in devices}
        function_by_name = {function.name: function for function in functions}

        self.assertEqual(device_by_name["multifield_scanner"].connection["port"], "COM3")
        self.assertIn("scanner_voltage", device_by_name["multifield_scanner"].capabilities)
        self.assertEqual(device_by_name["newton_lt06"].connection["port"], "COM5")
        self.assertIn("xyz_stage", device_by_name["newton_lt06"].capabilities)
        self.assertEqual(function_by_name["scan_scanner"].required_capability, "scanner_voltage")
        self.assertEqual(function_by_name["scan_scanner"].device, "multifield_scanner")

    def test_device_manager_filters_and_connects_mock_capabilities(self) -> None:
        manager = DeviceManager()

        self.assertIn("scanner_mock", manager.devices_for_capability("scanner_voltage"))
        manager.assign_function("scan_scanner", "scanner_mock")
        manager.connect_device("scanner_mock")

        handle = manager.handles["scanner_mock"]
        self.assertTrue(handle.connected)
        self.assertEqual(handle.status, "Connected")
        self.assertIn("scanner_voltage", handle.capabilities())
        self.assertIs(manager.adapter_for_function("scan_scanner"), handle.adapter)
        manager.disconnect_all()

    def test_device_manager_updates_connection_in_memory(self) -> None:
        manager = DeviceManager()

        manager.update_device_connection("multifield_scanner", {"backend": "serial", "port": "COM7"})

        handle = manager.handles["multifield_scanner"]
        self.assertEqual(handle.config.connection["port"], "COM7")
        self.assertEqual(handle.status, "Configured")

    def test_zurich_hf2li_registry_uses_helper_adapter(self) -> None:
        fake_tools = types.ModuleType("hf2li_tools")

        class FakeConfig:
            def __init__(self, host: str, port: int, device: str, interface: str) -> None:
                self.host = host
                self.port = port
                self.device = device
                self.interface = interface

        class FakeSample:
            timestamp = 123
            x = 1.0
            y = 2.0
            r = 3.0
            phase_deg = 45.0
            frequency = 1000.0
            auxin0 = None
            auxin1 = None

        def fake_connect(config):
            return {"config": config}, {"device": config.device}

        def fake_status(session, device, device_id):
            return {"device": device_id, "type": "HF2LI"}

        def fake_sample(device):
            return FakeSample()

        fake_tools.ConnectionConfig = FakeConfig
        fake_tools.connect = fake_connect
        fake_tools.device_status = fake_status
        fake_tools.read_demod_sample = fake_sample
        fake_tools.average_demod_samples = lambda device, count, delay_s: FakeSample()
        fake_tools.set_output = lambda session, device, device_id, amplitude, enable, output_on: None
        previous = sys.modules.get("hf2li_tools")
        sys.modules["hf2li_tools"] = fake_tools
        try:
            instrument, adapter = create_driver(
                "zurich.hf2li",
                "zurich_HF2LI",
                {
                    "host": "127.0.0.1",
                    "port": 8005,
                    "device": "DEV18388",
                    "interface": "USB",
                },
            )
            self.assertEqual(instrument["config"].device, "DEV18388")
            self.assertIn("lockin_demod", adapter.capabilities)
            self.assertEqual(adapter.status()["type"], "HF2LI")
            self.assertEqual(adapter.read_demod()["x_v"], 1.0)
        finally:
            if previous is None:
                sys.modules.pop("hf2li_tools", None)
            else:
                sys.modules["hf2li_tools"] = previous

    def test_attocube_anc350_registry_uses_bundled_python_api(self) -> None:
        fake_amc = types.ModuleType("AMC")

        class FakeMove:
            def __init__(self) -> None:
                self.positions = {0: 1000, 1: 2000, 2: 3000}
                self.targets: dict[int, int] = {}
                self.steps: list[tuple[int, bool, int]] = []

            def getPosition(self, axis: int) -> int:
                return self.positions[axis]

            def setControlTargetPosition(self, axis: int, target: int) -> None:
                self.targets[axis] = target
                self.positions[axis] = target

            def setControlContinuousFwd(self, axis: int, enabled: bool) -> None:
                return None

            def setControlContinuousBkwd(self, axis: int, enabled: bool) -> None:
                return None

            def setSingleStep(self, axis: int, backward: bool) -> None:
                self.steps.append((axis, backward, 1))

            def setNSteps(self, axis: int, backward: bool, count: int) -> None:
                self.steps.append((axis, backward, count))

        class FakeControl:
            def __init__(self) -> None:
                self.outputs: dict[int, bool] = {}
                self.moves: dict[int, bool] = {}

            def setControlOutput(self, axis: int, enabled: bool) -> None:
                self.outputs[axis] = enabled

            def getControlOutput(self, axis: int) -> bool:
                return self.outputs.get(axis, False)

            def setControlMove(self, axis: int, enabled: bool) -> None:
                self.moves[axis] = enabled

            def searchReferencePosition(self, axis: int) -> None:
                self.moves[axis] = True

        class FakeStatus:
            def getStatusConnected(self, axis: int) -> bool:
                return True

            def getStatusMoving(self, axis: int) -> int:
                return 0

            def getStatusTargetRange(self, axis: int) -> bool:
                return True

        class FakeDevice:
            def __init__(self, host: str) -> None:
                self.host = host
                self.TCP_PORT = 9090
                self.connected = False
                self.closed = False
                self.move = FakeMove()
                self.control = FakeControl()
                self.status = FakeStatus()

            def connect(self) -> None:
                self.connected = True

            def close(self) -> None:
                self.closed = True

        fake_amc.Device = FakeDevice
        previous = sys.modules.get("AMC")
        sys.modules["AMC"] = fake_amc
        try:
            instrument, adapter = create_driver(
                "attocube.anc350",
                "attocube_xyz",
                {
                    "host": "192.168.1.1",
                    "port": 9090,
                    "axes": {"x": 0, "y": 1, "z": 2},
                },
            )
            self.assertTrue(instrument.connected)
            self.assertIn("xyz_stage", adapter.capabilities)
            self.assertEqual(adapter.read_position(), {"x": 1.0, "y": 2.0, "z": 3.0})

            adapter.move_absolute(x=4.5, z=6.0)

            self.assertEqual(instrument.move.targets[0], 4500)
            self.assertEqual(instrument.move.targets[2], 6000)
            self.assertTrue(instrument.control.outputs[0])
            self.assertTrue(instrument.control.moves[2])
            self.assertEqual(adapter.snapshot()["host"], "192.168.1.1")
            adapter.close()
            self.assertTrue(instrument.closed)
        finally:
            if previous is None:
                sys.modules.pop("AMC", None)
            else:
                sys.modules["AMC"] = previous

    def test_write_gsf_creates_gwyddion_simple_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.gsf"
            write_gsf(
                path,
                np.arange(6, dtype=float).reshape(2, 3),
                x_real_m=1e-6,
                y_real_m=2e-6,
                z_unit="nm",
                title="unit test",
                metadata={"Channel": "topography"},
            )

            raw = path.read_bytes()

        self.assertTrue(raw.startswith(b"Gwyddion Simple Field 1.0\n"))
        self.assertIn(b"XRes = 3\n", raw)
        self.assertIn(b"YRes = 2\n", raw)
        self.assertIn(b"ZUnits = nm\n", raw)
        self.assertIn(b"Channel = topography\n", raw)

    def test_scan_controller_down_scan_writes_first_line_at_top(self) -> None:
        controller = ScanController(MockScannerDevice())
        config = ScanConfig(lines=4, pixels=3, channels=("topography",))
        controller.start(config, ScanDirection.DOWN)

        controller._on_line_data(
            0,
            {"topography": {"trace": np.array([1.0, 2.0, 3.0]), "retrace": np.array([4.0, 5.0, 6.0])}},
        )

        np.testing.assert_allclose(controller.images["trace"]["topography"][3], [1.0, 2.0, 3.0])
        self.assertTrue(np.isnan(controller.images["trace"]["topography"][0]).all())
        controller.stop()

    def test_adapter_scanner_device_uses_motion_and_acquisition_callbacks(self) -> None:
        class FakeScanner:
            def __init__(self) -> None:
                self.voltages: list[tuple[str, float]] = []
                self.stopped = False

            def set_axis_voltage(self, axis: str, value: float) -> None:
                self.voltages.append((axis, value))

            def stop(self) -> None:
                self.stopped = True

        scanner = FakeScanner()
        samples = iter([1.0, 2.0, 3.0])
        device = AdapterScannerDevice(
            lambda: scanner,
            lambda: (lambda channels: {"topography": next(samples)}),
        )
        config = ScanConfig(
            lines=1,
            pixels=3,
            width=1800.0,
            height=1.0,
            channels=("topography",),
            scan_passes=("trace",),
            t_sample=0.0,
            t_settle=0.0,
        )
        from afm_gui.core.scan_geometry import generate_scan_lines

        received: list[tuple[int, object]] = []
        progress: list[tuple[int, int, int, int, str]] = []
        finished = {"done": False}
        loop = QEventLoop()
        device.line_data_ready.connect(lambda line_index, data: received.append((line_index, data)))
        device.scan_progress_changed.connect(
            lambda line_index, total_lines, pixel_index, total_pixels, scan_pass: progress.append(
                (line_index, total_lines, pixel_index, total_pixels, scan_pass)
            )
        )
        device.scan_finished.connect(lambda: finished.update(done=True))
        device.scan_finished.connect(loop.quit)
        device.configure_scan(config, generate_scan_lines(config, ScanDirection.UP))
        device.start_scan(config.lines, config.pixels, 20, config.channels)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertTrue(finished["done"])
        self.assertTrue(scanner.stopped)
        self.assertEqual(received[0][0], 0)
        np.testing.assert_allclose(received[0][1]["topography"]["trace"], [1.0, 2.0, 3.0])
        self.assertEqual([axis for axis, _value in scanner.voltages], ["x", "y", "x", "y", "x", "y"])
        self.assertEqual(progress[-1], (0, 1, 2, 3, "trace"))

    def test_stage_controller_tracks_z_position(self) -> None:
        controller = StageController()

        controller.move_absolute(1.0, 2.0, 3.0)
        controller.move_z_relative(-0.5)

        self.assertAlmostEqual(controller.position.x_um, 1.0)
        self.assertAlmostEqual(controller.position.y_um, 2.0)
        self.assertAlmostEqual(controller.position.z_um, 2.5)
        self.assertEqual(controller.path_array().shape[1], 3)
        self.assertEqual(controller.snapshot()["position_um"]["z"], 2.5)

    def test_startup_uses_writable_mpl_config_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configured = Path(tmp) / "mpl"
            previous = os.environ.pop("MPLCONFIGDIR", None)
            previous_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                path = ensure_mpl_config_dir()
                self.assertTrue(path.exists())
                self.assertEqual(path, Path(tmp) / ".cache" / "afm_gui" / "matplotlib")
                os.environ["MPLCONFIGDIR"] = str(configured)
                self.assertEqual(ensure_mpl_config_dir(), configured)
            finally:
                if previous is None:
                    os.environ.pop("MPLCONFIGDIR", None)
                else:
                    os.environ["MPLCONFIGDIR"] = previous
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home

    def test_startup_falls_back_when_home_cache_is_unwritable(self) -> None:
        previous = os.environ.pop("MPLCONFIGDIR", None)
        previous_home = os.environ.get("HOME")
        os.environ["HOME"] = "/dev/null"
        try:
            path = ensure_mpl_config_dir()
            self.assertTrue(path.exists())
            self.assertEqual(path, Path(tempfile.gettempdir()) / "afm_gui" / "matplotlib")
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = previous
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home

    def test_spectroscopy_bundle_round_trips_hdf5(self) -> None:
        axis = np.linspace(-1.0, 1.0, 5)
        spectra = {"trace": {"current": np.arange(30, dtype=float).reshape(2, 3, 5)}}
        maps = {"trace": {"topography": np.arange(6, dtype=float).reshape(2, 3)}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.afmspm.h5"
            write_spectroscopy_bundle(
                path,
                SpectroscopyBundle(
                    spectrum_axis=axis,
                    spectra=spectra,
                    maps=maps,
                    metadata={"sample": "unit"},
                    axis_name="bias",
                    axis_label="Bias",
                    axis_unit="V",
                    channel_units={"current": "A", "topography": "nm"},
                ),
            )
            loaded = read_spectroscopy_bundle(path)

        np.testing.assert_allclose(loaded.spectrum_axis, axis)
        np.testing.assert_allclose(loaded.spectra["trace"]["current"], spectra["trace"]["current"])
        np.testing.assert_allclose(loaded.maps["trace"]["topography"], maps["trace"]["topography"])
        self.assertEqual(loaded.metadata["sample"], "unit")
        self.assertEqual(loaded.axis_unit, "V")

    def test_spectroscopy_controller_acquires_mock_spectra(self) -> None:
        controller = SpectroscopyController()
        scan_config = ScanConfig(lines=2, pixels=3, channels=("topography",), scan_mode="spectroscopy")
        spec_config = SpectroscopyConfig(points=7, channels=("current", "didv"))
        controller.start(scan_config, spec_config, ScanDirection.UP)
        controller.pause()

        controller._acquire_next_point()

        self.assertEqual(controller.spectra["trace"]["current"].shape, (2, 3, 7))
        self.assertTrue(np.isfinite(controller.spectra["trace"]["current"][0, 0]).all())
        self.assertTrue(np.isfinite(controller.maps["trace"]["topography"][0, 0]))
        controller.stop()


if __name__ == "__main__":
    unittest.main()
