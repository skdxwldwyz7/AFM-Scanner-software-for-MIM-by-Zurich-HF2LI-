# AFM GUI Progress Summary

## Project Goal

Build a modular AFM scan-control program that can be controlled from both GUI
and CLI. The current implementation uses a mock scanner device while preserving
the architecture needed for future hardware adapters.

## Environment

- Conda environment: `afm-gui`
- Package manager inside the environment: `uv`
- Main GUI stack: PyQt6, pyqtgraph
- Instrument-control foundation: QCoDeS
- Data/export support: numpy, h5py, pandas, scipy, matplotlib, PyYAML

## Current Package Layout

```text
afm_gui/
  cli.py
  main.py
  config/
    devices.yaml
    scan_modes.yaml
  core/
    scan_config.py
    scan_controller.py
    spectroscopy_config.py
    spectroscopy_controller.py
    lockin_controller.py
    scan_geometry.py
    scan_modes.py
    stage_controller.py
    parameter_tree.py
  data/
    gsf.py
    spectroscopy.py
  device/
    loader.py
    mock_device.py
  docs/
    architecture_summary.md
    spectroscopy_design.md
    progress_summary.md
  protocol/
    spm_commands.py
  ui/
    main_window.py
    panels/
      channel_images.py
      command_log.py
      controls.py
      device_manager.py
      lockin.py
      line_plot.py
      parameter_tree.py
      scan_parameters.py
      spectroscopy.py
      stage_map.py
      status.py
    modules/
      channel_images.py
      device.py
      lockin.py
      metadata.py
      scan.py
      spectroscopy.py
      stage.py
      storage.py
```

## GUI Status

The GUI has a main workbench window with a pyqtgraph `DockArea`. The menu bar is
fixed and remains available even when individual panels are moved, hidden, or
closed.

Menus:

- `File`: save GSF output, exit.
- `Settings`: reload scan modes, load device config, refresh parameter tree.
- `View`: show/hide panels, restore default layout, save/load user layouts.
- `Help`: scan-mode config path, architecture summary, about dialog.

Dockable panels:

- `Channel Images`
- `Line Plot`
- `Scan Parameters`
- `Controls`
- `Stage Map`
- `Lock-in Amplifier`
- `State`
- `Device Manager`
- `Parameter Tree`
- `Command Log`

The `Scan Parameters` panel now represents open-loop scanner voltage rather
than calibrated sample displacement. Center X/Y, width, height, image axes, ROI
coordinates, and probe position are displayed in V, and linear speed is V/s.
GUI-created scan configs set `xy_unit="V"` and use a direct voltage scale for
scanner output.
The panel also shows an estimated full-image scan time. The estimate assumes
trace and retrace passes and uses `lines * (2 * (width / linear + settle +
pixels * sample) + rest)`.

The fallback default layout is stored in code and treated as an internal safety
net. At startup the GUI loads `afm_gui/config/layout1.json` as the preferred
working layout, and `Restore Default Layout` reloads the same startup layout.
The current startup layout uses a three-column top area: Stage Map, Scan
Parameters, and Channel Images. Controls, Parameter Tree, and Command Log sit
below the left column; Line Plot and State sit below the right column. User
layouts are saved and loaded as JSON files.
Panels hidden by the startup layout, such as Device Manager and Lock-in
Amplifier, now open as floating panels from `View` to keep the default
workspace compact. Closing these floating windows hides the panel rather than
returning it to the main dock layout.

## Stage Map

The Stage Map panel is the first version of sample navigation. It uses a mock
XYZ stage controller and shows the X/Y motion path on an aspect-locked map. The
map is placed above the stage controls.

Current controls:

- current X/Y/Z display in micrometers
- target X/Y/Z absolute move
- configurable XY and Z jog steps
- `+X`, `-X`, `+Y`, `-Y`
- `+Z`, `-Z`
- `Move XY`
- `Move Z`
- `Home`
- `Home Z`
- `Clear Path`

The stage snapshot is recorded in scan metadata at scan start. When the
assigned `coarse_stage` device is connected in Device Manager, Stage Map
movement commands are sent through that adapter; otherwise the panel falls back
to the local mock controller.

## Lock-in Amplifier

The Lock-in Amplifier panel is the first version of lock-in control. It uses two
mock lock-in controllers, one for each channel, and is hidden by the startup
layout, but can be opened from `View` as a floating panel. The two channel
panels are arranged vertically, and each includes reference settings and demod
readout. PID and PLL are intentionally left to the instrument-side setup.

Current controls:

- output enabled/disabled
- reference frequency
- output amplitude
- phase
- time constant
- sensitivity
- reserve mode
- `Apply`
- `Read`

Current readouts:

- X
- Y
- R
- Theta

Lock-in reference settings and the latest reading are recorded in scan metadata
at scan start. When the assigned `lockin` device is connected in Device
Manager, apply/read commands are sent through that adapter; otherwise the panel
falls back to the local mock controller.

## Device Manager

The Device Manager panel is the first version of a general hardware loader. It
loads device definitions from:

```text
afm_gui/config/devices.yaml
```

Current example device definitions:

- mock AFM scanner
- attocube XYZ stage placeholder
- multi-field positioner placeholder
- lock-in amplifier placeholder

The panel can:

- load an alternate YAML config
- show function assignments and choose which device fulfills each function
- list device name, kind, driver, connection, enabled state, and status
- edit a device connection JSON in the device table and apply it before
  connecting
- connect one selected device
- disconnect one selected device
- connect all enabled devices
- connect all assigned devices
- disconnect all devices

Real hardware adapters are now registered for MultiField, Newton LT06,
Attocube, and Zurich HF2LI. A device snapshot and function assignment snapshot
are recorded in scan metadata at scan start.

The hardware loading layer now has the first capability-adapter path. Device
definitions can declare capabilities such as `scanner_voltage` and `xyz_stage`,
and function assignments can require a capability instead of only a broad device
kind. `DeviceHandle` can instantiate registered QCoDeS-style drivers, keep the
raw instrument and GUI-facing adapter, and expose adapters by function name via
`DeviceManager.adapter_for_function()`.

Current hardware assignments:

```text
multifield_scanner -> COM3 -> capability scanner_voltage
newton_lt06        -> COM5 -> capability xyz_stage
zurich_HF2LI       -> LabOne 127.0.0.1:8005 DEV18388 USB -> capabilities lockin_demod, lockin_output
```

Both real devices are configured but not auto-enabled, so explicit connection is
required before hardware commands are sent.

The GUI scan path now uses `AdapterScannerDevice` instead of directly owning a
`MockScannerDevice`. The bridge asks Device Manager for the assigned
`scan_scanner` adapter. With a connected MultiField scanner it starts a
background `QThread` worker that sets X/Y voltages point-by-point for each
generated scan line, emits the same `line_data_ready` signal used by the
existing image/export pipeline, and uses an acquisition callback for per-point
channel data. Keeping hardware I/O in the worker prevents slow serial/LabOne
calls from blocking ordinary GUI interaction. The current GUI acquisition
callback reads the assigned `lockin` adapter when connected and maps Zurich
demod data into scan channels; missing channels remain `NaN`. If no
`scan_scanner` adapter is connected, the bridge falls back to mock scanning.
The worker also emits lightweight line/pixel progress updates. The State panel
shows the current pass, line, and pixel while images still update by completed
line to avoid excessive redraw load.

The Zurich HF2LI device has a registry entry and GUI-facing adapter that wraps
the existing `Zurich/scripts/hf2li_tools.py` helpers for status, demod readout,
and output control. Current hardware validation status: the MultiField scanner
can be controlled from the GUI through `scan_scanner`; the Zurich lock-in
connection is still failing and should be debugged next before relying on
lock-in-backed scan-channel acquisition.

Hardware vendor Python drivers used by the GUI are copied into fixed package
paths under:

```text
afm_gui/device/vendor/
```

Adapters prefer these package-local copies before falling back to the external
`Hardwares/` folders. This keeps GUI hardware loading independent from the
workspace hardware-documentation layout.

## Channel Image Features

- User-defined number of channel views.
- Equal-sized, aspect-locked image plots.
- Independent channel selector per view.
- Independent scan pass selector per view: `trace` or `retrace`.
- Independent display flattening per view: `Raw`, `Line Mean`, or `Plane`.
- Display flattening does not modify saved raw data.
- Linked viewboxes keep all channel-image coordinates synchronized during
  pan/zoom.
- Left-drag creates a shared ROI rectangle.
- Existing pyqtgraph right-click menu is preserved.
- ROI context menu actions:
  - `Load ROI Into Scan Parameters`
  - `Clear ROI`
- Loading an ROI writes center and size into scan geometry for the next scan and
  then clears the ROI.
- Each image has a color scale.
- Right-clicking a color scale opens a colormap menu.

## Scan Control

Current scan controls:

- Scan Up
- Scan Down
- Pause
- Resume
- Stop
- Save GSF
- Show/Hide Metadata
- Auto Save enabled/disabled
- Auto Save directory selection

Auto Save is enabled by default in the GUI. The default directory is:

```text
~/AFM_scans
```

It saves timestamped GSF bundles when a scan is paused and when a scan finishes.

Scan direction affects image fill order:

- `Scan Up`: acquired lines fill bottom-to-top in acquisition order.
- `Scan Down`: acquired lines are mapped so displayed refresh direction matches
  the requested scan direction.

Runtime-editable parameters:

- `linear`
- `t_sample`
- `t_settle`
- `t_rest`

These are hot-update parameters. Changes are recorded in the parameter tree and
take effect from the next line. Structural scan parameters are treated as
next-scan settings.

## Scan Modes

Scan modes are loaded from:

```text
afm_gui/config/scan_modes.yaml
```

The current active bundled mode is:

- `lockin`

Each mode can define channel names, labels, units, default enabled states, and a
default channel-view count.

The `lockin` mode is intended for hardware bringup. It enables only
`lockin_x` and `lockin_phase` and uses two channel views, so scans can focus on
Zurich demod X and phase without requiring topography/error channel mapping.
The `topo`, `spectroscopy`, and `lift` mode definitions remain in
`scan_modes.yaml` but are temporarily marked `enabled: false`.

## Data Model

Recorded images are stored as:

```python
images[scan_pass][channel] -> numpy.ndarray
```

Each image is shaped:

```text
lines x pixels
```

The current mock device emits both `trace` and `retrace` data for each selected
channel.

Spectroscopy-map MVP data is stored separately as:

```python
spectra[scan_pass][channel] -> numpy.ndarray
```

Each spectroscopy cube is shaped:

```text
lines x pixels x spectrum_points
```

The dedicated spectroscopy export format is an HDF5 bundle with the extension:

```text
.afmspm.h5
```

The first implementation includes a mock point-wise spectroscopy controller, a
standalone Spectroscopy dock, live current-spectrum display, selected-slice map
display, HDF5 bundle writer/reader support, selected-slice GSF export, raw data
memory estimation, and acquisition-state button management.

## Metadata

The controller owns a single `ParameterTree`. It records:

- app name and metadata schema
- metadata creation time
- GUI or CLI source
- scan mode
- scan direction
- geometry
- timing
- channel list
- trace/retrace passes
- channel units
- calibration values
- display state
- current line index
- runtime update history
- storage/autosave settings and autosave event history
- device config path and device snapshot

The same tree is shown in the GUI and exported as a metadata JSON file.

For long-run responsiveness, the Parameter Tree dock refreshes on:

- scan start
- scan finish
- runtime parameter update
- manual refresh

It is not rebuilt on every scan line.

## Export

Export format:

- Gwyddion Simple Field (`.gsf`)
- One file per channel/pass pair.
- Complete parameter tree saved as a metadata JSON file.
- Each GSF file contains compact metadata and references `MetadataFile =
  <metadata filename>`.

GUI export asks for a base filename. For example, saving as `sample01.gsf`
creates a prefixed export bundle.

Auto Save creates timestamped prefixes containing the event and line number:

```text
afm_20260606_033000_pause_line0128
afm_20260606_033500_finish_line0256
```

Example files:

```text
sample01_topography_trace.gsf
sample01_topography_retrace.gsf
sample01_error_trace.gsf
sample01_error_retrace.gsf
sample01_metadata.json
```

## CLI Status

Entry point:

```bash
afm-cli
```

Commands:

```bash
afm-cli gui
afm-cli modes
afm-cli channels --mode topo
afm-cli devices
afm-cli stage --dx 10 --dy 0 --dz 0
afm-cli lockin --channel ch1 --output --frequency 1000 --amplitude 0.1
afm-cli preview-commands --mode topo
afm-cli scan --mode topo --export-gsf ./scan_out --export-prefix sample01
afm-cli scan --mode topo --auto-save-dir ./scan_out
```

The CLI supports the same scan configuration fields as the GUI and can exercise
runtime updates with:

```bash
--update-after-line
--update-linear
--update-sample
--update-settle
--update-rest
```

## Long-Run Guardrails

- Command Log uses a bounded `QPlainTextEdit` buffer and keeps the latest 5000
  blocks.
- GUI Auto Save is enabled by default but can be disabled from Controls.
- A new scan replaces the previous image buffers instead of accumulating scan
  history in memory.
- Line plot data keeps only the latest line.
- Image display refresh remains synchronized with scan line events but only
  redraws visible views whose selected channel/pass changed.
- Parameter Tree refresh no longer happens on every line.

Approximate raw image memory:

```text
passes * channels * lines * pixels * 8 bytes
```

Examples:

```text
256 x 256, 4 channels, 2 passes   ~ 4 MB raw
512 x 512, 4 channels, 2 passes   ~ 16 MB raw
1024 x 1024, 4 channels, 2 passes ~ 64 MB raw
2048 x 2048, 4 channels, 2 passes ~ 256 MB raw
4096 x 4096, 4 channels, 2 passes ~ 1 GB raw
4096 x 4096, 8 channels, 2 passes ~ 2 GB raw
```

Reserve roughly 3-6 times the raw size for GUI display, temporary arrays,
Qt/pyqtgraph overhead, and export operations.

## Recent Backup

A project backup was created before panel refactoring:

```text
backups/afm_gui_before_panel_refactor_20260606_0215.tar.gz
```

The backup directory is ignored by git.

Future manual project backups should exclude large external/reference folders
that are not required to restore the current GUI source tree:

```text
AFM_scan_reverse/
autosave-scan/
Hardwares/
```

The package-local hardware driver copies under `afm_gui/device/vendor/` should
still be included, because the GUI imports those fixed paths.

## Verified Checks

Recent checks used during development:

```bash
conda run -n afm-gui python -m compileall afm_gui tests
QT_QPA_PLATFORM=offscreen conda run -n afm-gui python -m unittest discover -s tests
```

The offscreen scan checks confirmed finite data for all default topo channels in
both `trace` and `retrace`. The current automated smoke tests cover core
scan/export behavior, metadata tree rendering, GUI module wiring,
ROI-to-scan-parameter updates, and auto-save bundle creation.

## Next Suggested Work

- Continue the spectroscopy-map MVP from `afm_gui/docs/spectroscopy_design.md`:
  harden the standalone Spectroscopy panel, add stronger large-map confirmation
  prompts and chunked on-disk recording, and prepare real hardware integration
  behind the device manager.
- Continue slimming `MainWindow` into feature modules. Started with
  `StageModule`, `LockInModule`, `StorageModule`, `DeviceModule`, and
  `ChannelImagesModule`, `ScanModule`, and `MetadataModule`; next candidates are
  help/layout/status/window coordination management.
- Harden the real scan acquisition worker with hardware-specific timing,
  buffered waveforms where supported, richer channel mapping, and stronger
  safety interlocks.
- Add schema versions for metadata, saved layouts, and scan-mode configuration.
- Define a clearer hardware capability/interface layer before connecting real
  devices.
- Add pre-scan memory budget estimation and GUI warning.
- Broaden automated tests for CLI scan/export edge cases and GUI configuration
  behavior.
- Consider optional `float32` storage or chunked on-disk recording for very
  large scans.
