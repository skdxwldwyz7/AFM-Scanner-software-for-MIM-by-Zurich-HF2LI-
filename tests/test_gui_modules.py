from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="afm_gui_mpl_"))

from PyQt6.QtCore import QEventLoop, QRectF, QTimer
from PyQt6.QtWidgets import QApplication
from qcodes.instrument import Instrument

from afm_gui.core.scan_config import ScanDirection
from afm_gui.ui.main_window import MainWindow


class GuiModuleSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        Instrument.close_all()
        self.window = MainWindow()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.controller.stop()
        self.window.close()
        self.app.processEvents()
        Instrument.close_all()

    def test_main_window_wires_split_modules(self) -> None:
        self.assertIs(self.window.metadata_dock.widgets[0], self.window.metadata_module.widget)
        self.assertEqual(self.window.display_count.value(), 4)
        self.assertEqual(len(self.window.channel_images_module.channel_views), 4)
        self.assertIs(self.window.device_manager, self.window.device_module.manager)
        self.assertIs(self.window.lockin_controller, self.window.lockin_module.primary_controller)
        self.assertIs(self.window.approach_dock.widgets[0], self.window.approach_module.widget)
        self.assertIn("approach", self.window.panels)
        self.assertIs(self.window.spectroscopy_dock.widgets[0], self.window.spectroscopy_module.widget)
        self.assertNotIn("spectroscopy", self.window.panels)
        self.assertNotIn("spectroscopy", self.window.panel_actions)

    def test_device_manager_can_edit_connection_json(self) -> None:
        module = self.window.device_module
        names = [
            module.device_table.item(row, 0).text()
            for row in range(module.device_table.rowCount())
        ]
        row = names.index("multifield_scanner")
        module.device_table.selectRow(row)
        module.device_table.item(row, 4).setText('{"backend": "serial", "port": "COM7", "baudrate": 115200}')

        module._apply_selected_device_connection()

        connection = module.manager.handles["multifield_scanner"].config.connection
        self.assertEqual(connection["port"], "COM7")
        self.assertEqual(connection["baudrate"], 115200)

    def test_device_manager_can_edit_enabled_state(self) -> None:
        module = self.window.device_module
        names = [
            module.device_table.item(row, 0).text()
            for row in range(module.device_table.rowCount())
        ]
        row = names.index("multifield_scanner")
        module.device_table.selectRow(row)
        module.device_table.item(row, 5).setText("yes")

        module._apply_selected_device_connection()

        self.assertTrue(module.manager.handles["multifield_scanner"].config.enabled)

    def test_device_manager_panel_has_room_for_tables(self) -> None:
        module = self.window.device_module

        self.assertGreaterEqual(module.widget.minimumHeight(), 500)
        self.assertGreaterEqual(module.device_function_table.minimumHeight(), 190)
        self.assertGreaterEqual(module.device_table.minimumHeight(), 210)

    def test_device_manager_opens_floating_by_default(self) -> None:
        self.assertTrue(self.window._panel_is_visible("devices"))
        self.assertTrue(self.window._panel_is_floating("devices"))

    def test_metadata_module_renders_parameter_tree(self) -> None:
        self.window.metadata_module.refresh()
        root = self.window.metadata_module.metadata_tree.invisibleRootItem()
        names = {root.child(index).text(0) for index in range(root.childCount())}

        self.assertIn("scan", names)
        self.assertIn("runtime", names)

    def test_roi_can_update_next_scan_geometry(self) -> None:
        self.window.scan_module.apply_roi_to_scan_parameters(QRectF(1.0, 2.0, 3.0, 4.0))

        config = self.window.scan_module.config()

        self.assertAlmostEqual(config.xc, 2.5)
        self.assertAlmostEqual(config.yc, 4.0)
        self.assertAlmostEqual(config.width, 3.0)
        self.assertAlmostEqual(config.height, 4.0)
        self.assertEqual(config.xy_unit, "V")
        self.assertEqual(config.volts_per_nm_x, 1.0)
        self.assertEqual(config.volts_per_nm_y, 1.0)
        self.assertEqual(config.scan_passes, self.window.scan_module.current_mode.scan_passes)

    def test_channel_image_color_range_can_be_auto_or_manual(self) -> None:
        view = self.window.channel_images_module.channel_views[0]

        self.assertTrue(view["range_auto"].isChecked())
        self.assertFalse(view["range_min"].isEnabled())
        self.assertFalse(view["range_max"].isEnabled())

        view["range_auto"].setChecked(False)
        view["range_min"].setValue(-0.5)
        view["range_max"].setValue(0.5)
        metadata = self.window.channel_images_module.display_metadata()

        self.assertTrue(view["range_min"].isEnabled())
        self.assertTrue(view["range_max"].isEnabled())
        self.assertEqual(metadata["display_ranges"][0], {"mode": "manual", "min": -0.5, "max": 0.5})

    def test_scan_start_accepts_channel_image_display_range_metadata(self) -> None:
        view = self.window.channel_images_module.channel_views[0]
        view["range_auto"].setChecked(False)
        view["range_min"].setValue(-0.5)
        view["range_max"].setValue(0.5)

        self.window.scan_module.start(ScanDirection.DOWN)
        self.app.processEvents()

        self.assertTrue(self.window.controller.is_running)
        self.assertEqual(
            self.window.controller.parameter_tree.to_dict()["display"]["color_ranges"][0],
            {"mode": "manual", "min": -0.5, "max": 0.5},
        )

    def test_scan_parameter_panel_uses_voltage_units(self) -> None:
        scan = self.window.scan_module

        self.assertEqual(scan.xc.suffix(), " V")
        self.assertEqual(scan.yc.suffix(), " V")
        self.assertEqual(scan.width.suffix(), " V")
        self.assertEqual(scan.height.suffix(), " V")
        self.assertEqual(scan.linear.suffix(), " V/s")

    def test_scan_parameter_panel_shows_estimated_scan_time(self) -> None:
        scan = self.window.scan_module
        scan.width.setValue(1.0)
        scan.linear.setValue(1.0)
        scan.pixels.setValue(10)
        scan.lines.setValue(2)
        scan.t_sample.setValue(0.1)
        scan.t_settle.setValue(0.5)
        scan.t_rest.setValue(0.25)

        seconds = scan.update_scan_time_estimate()

        self.assertAlmostEqual(seconds, 10.5)
        self.assertEqual(scan.scan_time_label.text(), "10.5 s")

    def test_stage_panel_controls_z_axis(self) -> None:
        stage = self.window.stage_module

        self.assertAlmostEqual(stage.stage_step.value(), 1.0)
        stage.stage_target_z.setValue(12.5)
        stage._move_z_absolute()
        self.assertAlmostEqual(stage.controller.position.z_um, 12.5)
        self.assertEqual(stage.stage_z_label.text(), "12.500 um")

        stage.stage_z_step.setValue(0.5)
        stage.controller.move_z_relative(-stage.stage_z_step.value())
        self.assertAlmostEqual(stage.controller.position.z_um, 12.0)
        self.assertEqual(stage.snapshot()["position_um"]["z"], 12.0)

    def test_approach_panel_runs_mock_approach(self) -> None:
        module = self.window.approach_module
        module.approach_step.setValue(0.1)
        module.approach_settle.setValue(0.001)
        module.approach_threshold.setValue(1.0)
        module.approach_consecutive.setValue(2)
        loop = QEventLoop()
        module.controller.state_changed.connect(
            lambda state: loop.quit() if state in {"Complete", "Failed"} else None
        )

        module.start()
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertEqual(module.controller.progress.state, "Complete")
        self.assertEqual(module.approach_state.text(), "Complete")
        self.assertGreaterEqual(module.controller.progress.steps, 2)
        self.assertTrue(module.approach_start.isEnabled())

    def test_approach_signal_can_read_connected_lockin_quantity(self) -> None:
        class FakeLockinAdapter:
            capabilities = ("lockin_demod",)

            def demod_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 1}[channel]

            def read_demod(self, **kwargs) -> dict[str, float]:
                return {"r_v": 2.0 + float(kwargs.get("demod_index", 0))}

        handle = self.window.device_manager.handles["zurich_HF2LI"]
        handle.connected = True
        handle.adapter = FakeLockinAdapter()
        self.window.approach_module._refresh_signal_devices()
        self.window.approach_module.approach_signal_device.setCurrentText("zurich_HF2LI")
        self.window.approach_module.approach_signal_channel.setCurrentText("ch2")
        self.window.approach_module.approach_signal_quantity.setCurrentText("r")

        value = self.window.approach_module.read_signal_once()

        self.assertEqual(value, 3.0)
        self.assertEqual(self.window.approach_module.approach_signal_value.text(), "3")

    def test_approach_real_actuator_requires_connected_stage(self) -> None:
        module = self.window.approach_module
        module.approach_actuator.setCurrentText("coarse_stage.z")

        module.start()
        self.app.processEvents()

        self.assertEqual(module.controller.progress.state, "Failed")
        self.assertIn("coarse_stage.z requires", module.controller.progress.message)
        self.assertEqual(module.approach_state.text(), "Failed")

    def test_approach_can_move_connected_stage_and_read_lockin_signal(self) -> None:
        class FakeStageAdapter:
            capabilities = ("xyz_stage",)

            def __init__(self) -> None:
                self.moves: list[float] = []

            def move_relative(self, dz: float = 0.0, **_kwargs) -> None:
                self.moves.append(float(dz))

        class FakeLockinAdapter:
            capabilities = ("lockin_demod",)

            def demod_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 1}[channel]

            def read_demod(self, **kwargs) -> dict[str, float]:
                return {"r_v": 2.0 + float(kwargs.get("demod_index", 0))}

        stage = FakeStageAdapter()
        stage_handle = self.window.device_manager.handles["attocube_xyz"]
        stage_handle.connected = True
        stage_handle.adapter = stage
        lockin_handle = self.window.device_manager.handles["zurich_HF2LI"]
        lockin_handle.connected = True
        lockin_handle.adapter = FakeLockinAdapter()
        self.window.approach_module._refresh_signal_devices()
        module = self.window.approach_module
        module.approach_actuator.setCurrentText("coarse_stage.z")
        module.approach_signal_device.setCurrentText("zurich_HF2LI")
        module.approach_signal_channel.setCurrentText("ch2")
        module.approach_signal_quantity.setCurrentText("r")
        module.approach_step.setValue(0.1)
        module.approach_settle.setValue(0.001)
        module.approach_threshold.setValue(2.5)
        module.approach_consecutive.setValue(1)
        loop = QEventLoop()
        module.controller.state_changed.connect(
            lambda state: loop.quit() if state in {"Complete", "Failed"} else None
        )

        module.start()
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertEqual(module.controller.progress.state, "Complete")
        self.assertEqual(stage.moves, [-0.1])
        self.assertFalse(self.window.device_module.manager.hardware_locked)

    def test_lockin_panel_keeps_only_apply_and_read_controls(self) -> None:
        controls = self.window.lockin_module.lockin_channels["ch1"]

        self.assertIn("apply", controls)
        self.assertIn("read", controls)
        self.assertNotIn("pid_enabled", controls)
        self.assertNotIn("pll_enabled", controls)

    def test_lockin_panel_has_compact_width_limits(self) -> None:
        self.assertEqual(self.window.lockin_module.widget.maximumWidth(), 760)
        self.assertLessEqual(self.window.lockin_module.lockin_apply_routes.maximumWidth(), 82)
        for controls in self.window.lockin_module.lockin_channels.values():
            self.assertLessEqual(controls["frequency"].maximumWidth(), 180)
            self.assertLessEqual(controls["read"].maximumWidth(), 82)

    def test_lockin_panel_channels_follow_assigned_device(self) -> None:
        module = self.window.lockin_module

        self.assertEqual(module.active_channels, ("ch1", "ch2"))
        self.assertFalse(module.lockin_channels["ch2"]["box"].isHidden())

        self.window.device_manager.assign_function("lockin", "srs_sr830")

        self.assertEqual(module.active_channels, ("ch1",))
        self.assertTrue(module.lockin_channels["ch2"]["box"].isHidden())

    def test_lockin_scan_routing_defaults_to_assigned_zurich_ch1(self) -> None:
        for controls in self.window.lockin_module.lockin_scan_routes.values():
            self.assertEqual(controls["device"].currentText(), "zurich_HF2LI")
            self.assertEqual(controls["lockin_channel"].currentText(), "ch1")

    def test_scan_lockin_routing_can_use_multiple_devices(self) -> None:
        class FakeLockinAdapter:
            capabilities = ("lockin_demod", "lockin_output")

            def __init__(
                self,
                samples: dict[int, dict[str, float]],
                channels: tuple[str, ...] = ("ch1",),
            ) -> None:
                self.samples = samples
                self.lockin_channels = channels
                self.read_count = 0
                self.demod_indices: list[int] = []

            def demod_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 1}[channel]

            def read_demod(self, **kwargs) -> dict[str, float]:
                self.read_count += 1
                demod_index = int(kwargs.get("demod_index", 0))
                self.demod_indices.append(demod_index)
                return dict(self.samples[demod_index])

        zurich = FakeLockinAdapter(
            {
                0: {"x_v": 1.0, "y_v": 2.0, "r_v": 3.0, "phase_deg": 4.0, "frequency_hz": 1000.0},
                1: {"x_v": 101.0, "y_v": 102.0, "r_v": 103.0, "phase_deg": 104.0, "frequency_hz": 2000.0},
            },
            ("ch1", "ch2"),
        )
        srs = FakeLockinAdapter({0: {"x_v": 10.0, "y_v": 20.0, "r_v": 30.0, "phase_deg": 40.0, "frequency_hz": 3000.0}})
        self.window.device_manager.handles["zurich_HF2LI"].connected = True
        self.window.device_manager.handles["zurich_HF2LI"].adapter = zurich
        self.window.device_manager.handles["srs_sr830"].connected = True
        self.window.device_manager.handles["srs_sr830"].adapter = srs
        self.window.lockin_module._refresh_scan_route_devices()
        self.window.lockin_module.lockin_scan_routes["signal_a"]["device"].setCurrentText("zurich_HF2LI")
        self.window.lockin_module.lockin_scan_routes["signal_a"]["lockin_channel"].setCurrentText("ch2")
        self.window.lockin_module.lockin_scan_routes["signal_a"]["signal"].setCurrentText("x")
        self.window.lockin_module.lockin_scan_routes["signal_d"]["device"].setCurrentText("srs_sr830")
        self.window.lockin_module.lockin_scan_routes["signal_d"]["signal"].setCurrentText("theta")
        self.window.lockin_module.apply_scan_routing()

        callback = self.window._scan_acquisition_callback()
        self.assertIsNotNone(callback)
        values = callback(("signal_a", "signal_d"))

        self.assertEqual(values, {"signal_a": 101.0, "signal_d": 40.0})
        self.assertEqual(zurich.read_count, 1)
        self.assertEqual(zurich.demod_indices, [1])
        self.assertEqual(srs.read_count, 1)

    def test_scan_lockin_routing_can_use_frequency_signal(self) -> None:
        class FakeLockinAdapter:
            capabilities = ("lockin_demod", "lockin_output")
            lockin_channels = ("ch1", "ch2")

            def __init__(self) -> None:
                self.demod_indices: list[int] = []

            def demod_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 1}[channel]

            def read_demod(self, **kwargs) -> dict[str, float]:
                demod_index = int(kwargs.get("demod_index", 0))
                self.demod_indices.append(demod_index)
                return {"frequency_hz": 1000.0 + demod_index}

        adapter = FakeLockinAdapter()
        self.window.device_manager.handles["zurich_HF2LI"].connected = True
        self.window.device_manager.handles["zurich_HF2LI"].adapter = adapter
        self.window.lockin_module._refresh_scan_route_devices()
        self.window.lockin_module.lockin_scan_routes["signal_b"]["device"].setCurrentText("zurich_HF2LI")
        self.window.lockin_module.lockin_scan_routes["signal_b"]["lockin_channel"].setCurrentText("ch2")
        self.window.lockin_module.lockin_scan_routes["signal_b"]["signal"].setCurrentText("frequency")
        self.window.lockin_module.apply_scan_routing()

        callback = self.window._scan_acquisition_callback()
        values = callback(("signal_b",))

        self.assertEqual(values, {"signal_b": 1001.0})
        self.assertEqual(adapter.demod_indices, [1])
        self.assertEqual(self.window.channel_images_module.channel_aliases["signal_b"], "B-zurich_HF2LI-frequency")

    def test_scan_acquisition_without_connected_lockin_returns_zeroes(self) -> None:
        callback = self.window._scan_acquisition_callback()

        values = callback(("signal_a", "signal_b"))

        self.assertEqual(values, {"signal_a": 0.0, "signal_b": 0.0})

    def test_scan_acquisition_keeps_running_when_lockin_read_fails(self) -> None:
        class FailingLockinAdapter:
            capabilities = ("lockin_demod",)
            lockin_channels = ("ch1",)

            def read_demod(self, **_kwargs) -> dict[str, float]:
                raise RuntimeError("temporary read failure")

        self.window.device_manager.handles["zurich_HF2LI"].connected = True
        self.window.device_manager.handles["zurich_HF2LI"].adapter = FailingLockinAdapter()
        self.window.lockin_module._refresh_scan_route_devices()
        self.window.lockin_module.apply_scan_routing()

        callback = self.window._scan_acquisition_callback()
        values = callback(("signal_a", "signal_b"))

        self.assertEqual(values, {"signal_a": 0.0, "signal_b": 0.0})

    def test_scan_lockin_routing_apply_updates_channel_image_aliases(self) -> None:
        class FakeLockinAdapter:
            capabilities = ("lockin_demod", "lockin_output")
            lockin_channels = ("ch1",)

            def read_demod(self, **_kwargs) -> dict[str, float]:
                return {"x_v": 0.0, "y_v": 0.0, "r_v": 0.0, "phase_deg": 0.0}

        for name in ("zurich_HF2LI", "srs_sr830", "srs_sr860"):
            self.window.device_manager.handles[name].connected = True
            self.window.device_manager.handles[name].adapter = FakeLockinAdapter()

        self.window.lockin_module._refresh_scan_route_devices()
        self.window.lockin_module.lockin_scan_routes["signal_a"]["device"].setCurrentText("zurich_HF2LI")
        self.window.lockin_module.lockin_scan_routes["signal_a"]["signal"].setCurrentText("x")
        self.window.lockin_module.apply_scan_routing()
        routes = self.window.lockin_module.scan_routing()

        self.assertEqual(routes["signal_a"]["device"], "zurich_HF2LI")
        self.assertEqual(routes["signal_a"]["signal"], "x")
        self.assertEqual(self.window.channel_images_module.channel_aliases["signal_a"], "A-zurich_HF2LI-x")

    def test_lockin_without_hardware_readout_stays_zero(self) -> None:
        controls = self.window.lockin_module.lockin_channels["ch2"]
        controls["output_enabled"].setChecked(True)
        controls["amplitude"].setValue(1.0)

        self.window.lockin_module.apply_settings("ch2")

        reading = self.window.lockin_module.controllers["ch2"].reading
        self.assertEqual(reading.x_v, 0.0)
        self.assertEqual(reading.y_v, 0.0)
        self.assertEqual(reading.r_v, 0.0)
        self.assertEqual(reading.theta_deg, 0.0)
        self.assertEqual(reading.frequency_hz, 0.0)
        self.assertEqual(controls["x_label"].text(), "0 V")
        self.assertEqual(controls["frequency_label"].text(), "0 Hz")

    def test_lockin_channel2_uses_configured_zurich_indices(self) -> None:
        class FakeLockinAdapter:
            def __init__(self) -> None:
                self.output_indices: list[int] = []
                self.amplitude_indices: list[int] = []
                self.demod_indices: list[int] = []
                self.configured_demods: list[dict[str, object]] = []

            def demod_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 3}[channel]

            def input_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 1}[channel]

            def oscillator_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 2}[channel]

            def output_index_for_channel(self, channel: str) -> int:
                return {"ch1": 0, "ch2": 2}[channel]

            def amplitude_index_for_channel(self, channel: str) -> int:
                return {"ch1": 6, "ch2": 7}[channel]

            def set_output(self, **kwargs) -> None:
                self.output_indices.append(kwargs["output_index"])
                self.amplitude_indices.append(kwargs["amplitude_index"])

            def configure_demod(self, **kwargs) -> None:
                self.configured_demods.append(dict(kwargs))

            def read_demod(self, **kwargs) -> dict[str, float]:
                demod_index = kwargs["demod_index"]
                self.demod_indices.append(demod_index)
                return {
                    "x_v": float(demod_index + 1),
                    "y_v": 0.0,
                    "r_v": float(demod_index + 1),
                    "phase_deg": 0.0,
                    "frequency_hz": 1234.5,
                }

        adapter = FakeLockinAdapter()
        device_name = self.window.device_manager.functions["lockin"].device
        handle = self.window.device_manager.handles[device_name]
        handle.connected = True
        handle.adapter = adapter
        self.window.lockin_module.lockin_channels["ch2"]["output_enabled"].setChecked(True)

        self.window.lockin_module.apply_settings("ch2")

        self.assertEqual(adapter.output_indices, [2])
        self.assertEqual(adapter.amplitude_indices, [7])
        self.assertEqual(adapter.configured_demods[-1]["demod_index"], 3)
        self.assertEqual(adapter.configured_demods[-1]["input_index"], 1)
        self.assertEqual(adapter.configured_demods[-1]["oscillator_index"], 2)
        self.assertEqual(adapter.demod_indices, [3])
        self.assertEqual(self.window.lockin_module.controllers["ch2"].reading.x_v, 4.0)
        self.assertEqual(self.window.lockin_module.controllers["ch2"].reading.frequency_hz, 1234.5)
        self.assertEqual(self.window.lockin_module.lockin_channels["ch2"]["frequency_label"].text(), "1234.5 Hz")

    def test_lockin_hardware_read_failure_does_not_fallback_to_mock(self) -> None:
        class FailingLockinAdapter:
            def read_demod(self, **_kwargs) -> dict[str, float]:
                raise RuntimeError("demod not enabled")

        device_name = self.window.device_manager.functions["lockin"].device
        handle = self.window.device_manager.handles[device_name]
        handle.connected = True
        handle.adapter = FailingLockinAdapter()

        self.window.lockin_module.read("ch2")

        controls = self.window.lockin_module.lockin_channels["ch2"]
        self.assertEqual(controls["x_label"].text(), "Error")
        self.assertEqual(controls["y_label"].text(), "-")
        self.assertEqual(controls["frequency_label"].text(), "-")
        self.assertEqual(self.window.lockin_module.controllers["ch2"].reading.x_v, 0.0)

    def test_auto_save_writes_gsf_bundle_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.window.auto_save_dir.setText(tmp)
            self.window.auto_save_enabled.setChecked(True)
            self.window.controller.current_line_index = 0
            self.window.storage_module.auto_save("unit")
            files = sorted(Path(tmp).glob("*"))

        self.assertTrue(any(path.name.endswith("_metadata.json") for path in files))
        self.assertTrue(any(path.suffix == ".gsf" for path in files))

    def test_main_scan_buttons_follow_controller_state(self) -> None:
        self.assertTrue(self.window.scan_up.isEnabled())
        self.assertTrue(self.window.scan_down.isEnabled())
        self.assertFalse(self.window.pause.isEnabled())
        self.assertFalse(self.window.resume.isEnabled())
        self.assertFalse(self.window.stop.isEnabled())
        self.assertTrue(self.window.save_gsf.isEnabled())
        self.assertTrue(self.window.auto_save_browse.isEnabled())
        self.assertTrue(self.window.scan_repeat_mode.isEnabled())

        self.window._update_scan_button_state("Scanning")
        self.assertFalse(self.window.scan_up.isEnabled())
        self.assertFalse(self.window.scan_down.isEnabled())
        self.assertTrue(self.window.pause.isEnabled())
        self.assertFalse(self.window.resume.isEnabled())
        self.assertTrue(self.window.stop.isEnabled())
        self.assertFalse(self.window.save_gsf.isEnabled())
        self.assertFalse(self.window.auto_save_browse.isEnabled())
        self.assertFalse(self.window.scan_repeat_mode.isEnabled())

        self.window._update_scan_button_state("Paused")
        self.assertFalse(self.window.scan_up.isEnabled())
        self.assertFalse(self.window.pause.isEnabled())
        self.assertTrue(self.window.resume.isEnabled())
        self.assertTrue(self.window.stop.isEnabled())
        self.assertTrue(self.window.save_gsf.isEnabled())

        self.window._update_scan_button_state("Idle")
        self.assertTrue(self.window.scan_up.isEnabled())
        self.assertTrue(self.window.scan_down.isEnabled())
        self.assertFalse(self.window.pause.isEnabled())
        self.assertFalse(self.window.resume.isEnabled())
        self.assertFalse(self.window.stop.isEnabled())
        self.assertTrue(self.window.save_gsf.isEnabled())
        self.assertTrue(self.window.auto_save_browse.isEnabled())

    def test_scan_down_button_starts_scan(self) -> None:
        self.window.scan_module.pixels.setValue(4)
        self.window.scan_module.lines.setValue(4)
        self.window.scan_module.linear.setValue(100.0)
        self.window.scan_module.t_sample.setValue(0.0)
        self.window.scan_module.t_settle.setValue(0.0)
        self.window.scan_module.t_rest.setValue(0.0)

        self.window.scan_down.click()
        self.app.processEvents()

        self.assertTrue(self.window.controller.is_running)
        self.assertEqual(self.window.state_label.text(), "Scanning")

    def test_scan_sequence_count_alternates_up_down(self) -> None:
        directions = []
        self.window.scan_repeat_mode.setCurrentIndex(self.window.scan_repeat_mode.findData("count"))
        self.window.scan_repeat_count.setValue(3)
        self.window.scan_module.start = lambda direction: directions.append(direction)

        self.window._start_scan_sequence(ScanDirection.UP)
        self.window._continue_scan_sequence()
        self.window._continue_scan_sequence()
        self.window._continue_scan_sequence()

        self.assertEqual(directions, [ScanDirection.UP, ScanDirection.DOWN, ScanDirection.UP])
        self.assertFalse(self.window._scan_sequence_active)

    def test_scan_sequence_continuous_keeps_running_until_stop(self) -> None:
        directions = []
        self.window.scan_repeat_mode.setCurrentIndex(self.window.scan_repeat_mode.findData("continuous"))
        self.window.scan_module.start = lambda direction: directions.append(direction)

        self.window._start_scan_sequence(ScanDirection.DOWN)
        self.window._continue_scan_sequence()
        self.window._continue_scan_sequence()
        self.window._stop_scan_sequence()

        self.assertEqual(directions, [ScanDirection.DOWN, ScanDirection.UP, ScanDirection.DOWN])
        self.assertFalse(self.window._scan_sequence_active)

    def test_spectroscopy_buttons_and_memory_estimate_update(self) -> None:
        module = self.window.spectroscopy_module
        self.window.scan_module.pixels.setValue(2)
        self.window.scan_module.lines.setValue(2)
        module.points.setValue(5)

        self.assertIn("raw", module.memory_label.text())
        self.assertTrue(module.start_button.isEnabled())
        self.assertFalse(module.pause_button.isEnabled())
        self.assertFalse(module.resume_button.isEnabled())
        self.assertFalse(module.stop_button.isEnabled())

        module.start_map()
        self.assertFalse(module.start_button.isEnabled())
        self.assertTrue(module.pause_button.isEnabled())
        self.assertFalse(module.resume_button.isEnabled())
        self.assertTrue(module.stop_button.isEnabled())

        module.controller.pause()
        self.assertFalse(module.pause_button.isEnabled())
        self.assertTrue(module.resume_button.isEnabled())
        self.assertTrue(module.stop_button.isEnabled())

        module.controller.stop()
        self.assertTrue(module.start_button.isEnabled())
        self.assertFalse(module.pause_button.isEnabled())
        self.assertFalse(module.resume_button.isEnabled())

    def test_spectroscopy_slice_exports_gsf(self) -> None:
        module = self.window.spectroscopy_module
        self.window.scan_module.pixels.setValue(2)
        self.window.scan_module.lines.setValue(2)
        module.points.setValue(5)
        module.start_map()
        module.controller.pause()
        module.controller._acquire_next_point()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slice.gsf"
            with patch(
                "afm_gui.ui.modules.spectroscopy.QFileDialog.getSaveFileName",
                return_value=(str(path), "Gwyddion Simple Field (*.gsf)"),
            ):
                module.save_slice_gsf()
            raw = path.read_bytes()

        self.assertTrue(raw.startswith(b"Gwyddion Simple Field 1.0\n"))
        self.assertIn(b"SpectrumAxis = bias\n", raw)
        self.assertIn(b"SpectrumIndex = 0\n", raw)
        self.assertIn(b"XYUnit = V\n", raw)
        module.controller.stop()


if __name__ == "__main__":
    unittest.main()
