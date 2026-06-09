from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="afm_gui_mpl_"))

from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import QApplication
from qcodes.instrument import Instrument

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
        self.assertEqual(self.window.display_count.value(), 2)
        self.assertEqual(len(self.window.channel_images_module.channel_views), 2)
        self.assertIs(self.window.device_manager, self.window.device_module.manager)
        self.assertIs(self.window.lockin_controller, self.window.lockin_module.primary_controller)
        self.assertIs(self.window.spectroscopy_dock.widgets[0], self.window.spectroscopy_module.widget)
        self.assertIn("spectroscopy", self.window.panels)

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

        stage.stage_target_z.setValue(12.5)
        stage._move_z_absolute()
        self.assertAlmostEqual(stage.controller.position.z_um, 12.5)
        self.assertEqual(stage.stage_z_label.text(), "12.500 um")

        stage.stage_z_step.setValue(0.5)
        stage.controller.move_z_relative(-stage.stage_z_step.value())
        self.assertAlmostEqual(stage.controller.position.z_um, 12.0)
        self.assertEqual(stage.snapshot()["position_um"]["z"], 12.0)

    def test_lockin_panel_keeps_only_apply_and_read_controls(self) -> None:
        controls = self.window.lockin_module.lockin_channels["ch1"]

        self.assertIn("apply", controls)
        self.assertIn("read", controls)
        self.assertNotIn("pid_enabled", controls)
        self.assertNotIn("pll_enabled", controls)

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

        self.window._update_scan_button_state("Scanning")
        self.assertFalse(self.window.scan_up.isEnabled())
        self.assertFalse(self.window.scan_down.isEnabled())
        self.assertTrue(self.window.pause.isEnabled())
        self.assertFalse(self.window.resume.isEnabled())
        self.assertTrue(self.window.stop.isEnabled())
        self.assertFalse(self.window.save_gsf.isEnabled())
        self.assertFalse(self.window.auto_save_browse.isEnabled())

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
