# AFM GUI Progress Summary

## Project Goal

Build a modular AFM scan-control program that can be controlled from both GUI
and CLI. The current implementation keeps mock fallbacks for offline
development and supports configured hardware adapters through Device Manager.

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
    approach_config.py
    approach_controller.py
    scan_config.py
    scan_controller.py
    lockin_acquisition.py
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
    adapters/
      attocube.py
      mock.py
      multifield.py
      srs.py
      zurich.py
    loader.py
    mock_device.py
    registry.py
    scan_device.py
    vendor/
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
      approach.py
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
      approach.py
      device.py
      layout.py
      lockin.py
      metadata.py
      scan.py
      scan_sequence.py
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
- `Approach`
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
Device Manager opens automatically as a floating window at startup so
connection state is visible immediately without consuming dock space. Lock-in
Amplifier opens as a floating panel from `View` to keep the default workspace
compact. Closing these floating windows hides the panel rather than returning it
to the main dock layout. The Spectroscopy module remains implemented and
covered by tests, but is temporarily hidden from the main GUI until its
real-hardware routing is clarified.

## Stage Map

The Stage Map panel is the first version of sample navigation. It uses the
assigned `coarse_stage` adapter when connected, otherwise falls back to the
local stage controller, and shows the X/Y motion path on an aspect-locked map.
The map is placed above the stage controls.

Current controls:

- current X/Y/Z display in micrometers
- target X/Y/Z absolute move
- configurable XY and Z jog steps, both defaulting to `1 um`
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

The Lock-in Amplifier panel is the first version of lock-in control. It uses
local lock-in controllers for panel state and readout fallback, and sends
commands through a connected lock-in adapter when available. The panel is hidden
by the startup layout, but can be opened from `View` as a floating panel. The
channel panels are arranged vertically, and each includes reference settings and
demod readout. PID and PLL are intentionally left to the instrument-side setup.

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
- Frequency

Lock-in reference settings and the latest reading are recorded in scan metadata
at scan start. When the assigned `lockin` device is connected in Device
Manager, apply/read commands are sent through that adapter; otherwise the panel
falls back to the local mock controller.

## Approach

The Approach panel is the first generic condition-based approach controller. It
moves a selected actuator in small Z steps, reads a selected signal, and stops
when a condition is satisfied for a required number of consecutive samples. This
keeps AFM/STM-specific behavior out of the controller; individual modes should
be represented later as recipes.

Current controls:

- actuator selection: `mock.z` or a conservative `coarse_stage.z` provider
- direction: up/down
- step size and settle time
- signal source: mock or configured lock-in device/channel/quantity
- condition: `above`, `below`, `delta`, `between`, or `outside`
- consecutive-hit requirement
- max travel, max steps, and retract distance
- start, pause, resume, abort, retract, and read-signal actions

The default path is mock-safe for offline validation. The panel can now also use
the connected device assigned to `coarse_stage` for `coarse_stage.z` motion and
can read stop-condition signals from any connected lock-in device/channel/
quantity. Real hardware selections fail explicitly if the required stage or
lock-in is not connected, and Device Manager connection controls are locked
while approach is running or paused. Real hardware approach recipes still need
explicit validation before relying on them during experiments.

## Device Manager

The Device Manager panel is the first version of a general hardware loader. It
loads device definitions from:

```text
afm_gui/config/devices.yaml
```

Current example device definitions:

- mock AFM scanner
- MultiField scanner
- Newton LT06 stage
- Attocube XYZ stage
- Zurich HF2LI lock-in
- SRS SR830/SR860/SR865/SR865A lock-ins

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
Attocube, Zurich HF2LI, and SRS lock-ins. A device snapshot and function
assignment snapshot are recorded in scan metadata at scan start and refreshed
again before export.

The hardware loading layer now has the first capability-adapter path. Device
definitions can declare capabilities such as `scanner_voltage` and `xyz_stage`,
and function assignments can require a capability instead of only a broad device
kind. `DeviceHandle` can instantiate registered QCoDeS-style drivers, keep the
raw instrument and GUI-facing adapter, and expose adapters by function name via
`DeviceManager.adapter_for_function()`.

Current hardware assignments:

```text
scan_scanner -> multifield_scanner -> COM3 -> capability scanner_voltage
coarse_stage -> attocube_xyz -> TCP 192.168.0.9:9090 -> capability xyz_stage
lockin       -> zurich_HF2LI -> LabOne 127.0.0.1:8005 DEV18388 USB -> capabilities lockin_demod, lockin_output
srs_sr830    -> VISA GPIB0::8::INSTR -> capabilities lockin_demod, lockin_output
srs_sr860    -> VISA USB placeholder -> capabilities lockin_demod, lockin_output
srs_sr865    -> VISA USB placeholder -> capabilities lockin_demod, lockin_output
srs_sr865a   -> VISA USB placeholder -> capabilities lockin_demod, lockin_output
```

Newton LT06 remains registered as `newton_lt06` on default `COM5` and can be
selected in Device Manager as an alternate `coarse_stage` provider. Real
devices are configured but not auto-enabled, so explicit connection is required
before hardware commands are sent.

The GUI scan path now uses `AdapterScannerDevice` instead of directly owning a
`MockScannerDevice`. The bridge asks Device Manager for the assigned
`scan_scanner` adapter. With a connected MultiField scanner it starts a
background `QThread` worker that sets X/Y voltages point-by-point for each
generated scan line, emits the same `line_data_ready` signal used by the
existing image/export pipeline, and uses an acquisition callback for per-point
channel data. Keeping hardware I/O in the worker prevents slow serial/LabOne
calls from blocking ordinary GUI interaction. The current GUI acquisition
callback is provided by `LockinScanAcquisition`, which reads the applied Scan
Routing table and maps `signal_a` through `signal_d` to configured lock-in
device/channel/signal sources. Missing, disconnected, or temporarily failing
routes are filled with `0`. If no
`scan_scanner` adapter is connected, the bridge falls back to mock scanning.
The worker also emits lightweight line/pixel progress updates. The State panel
shows the current pass, line, and pixel while images still update by completed
line to avoid excessive redraw load.

The Zurich HF2LI device has a registry entry and GUI-facing adapter that wraps
the package-local `hf2li_tools.py` helpers for status, demod readout, demod
configuration, and output control. SRS lock-ins use QCoDeS driver classes
through a shared SRS adapter. Current hardware validation status: the MultiField
scanner can be controlled from the GUI through `scan_scanner`; each physical
lock-in setup should still be validated by connecting in Device Manager and
checking `Read` before relying on scan-channel acquisition.

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
- Each image color scale can use automatic range or manual min/max values.

## Scan Control

Current scan controls:

- Scan Up
- Scan Down
- Repeat mode: Single, Continuous Up/Down, or Count
- Count value for fixed total scan count
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

Continuous and counted scans alternate direction automatically from the button
used to start the sequence. `Stop` cancels the rest of the sequence.

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

The `lockin` mode is intended for hardware bringup. It exposes the A-D signal
route slots (`signal_a` through `signal_d`), records A/B by default, and uses
channel views whose display names are generated from the applied Scan Routing,
such as `A-zurich_HF2LI-x`.
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
Spectroscopy module/panel kept out of the main GUI for now, live
current-spectrum display, selected-slice map display, HDF5 bundle writer/reader
support, selected-slice GSF export, raw data memory estimation, and
acquisition-state button management.

## Metadata

The controller owns a single `ParameterTree`. It records:

- app name and metadata schema
- metadata creation time
- GUI or CLI source
- scan mode
- scan direction
- initial scan parameters
- current/final scan parameters
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
- stage state
- lock-in setup, latest readout, and scan routing
- approach setup and latest progress

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
sample01_signal_a_trace.gsf
sample01_signal_a_retrace.gsf
sample01_signal_b_trace.gsf
sample01_signal_b_retrace.gsf
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
afm-cli channels --mode lockin
afm-cli devices
afm-cli stage --dx 10 --dy 0 --dz 0
afm-cli lockin --channel ch1 --output --frequency 1000 --amplitude 0.1
afm-cli preview-commands --mode lockin
afm-cli scan --mode lockin --export-gsf ./scan_out --export-prefix sample01
afm-cli scan --mode lockin --auto-save-dir ./scan_out
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

The latest source backup after the lock-in routing, scan sequencing, and
metadata work is:

```text
backups/afm_gui_backup_20260610_003556.zip
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

The current automated smoke tests cover core scan/export behavior, metadata
tree rendering, GUI module wiring, ROI-to-scan-parameter updates, lock-in
routing, scan sequencing, approach control paths, runtime metadata updates,
spectroscopy export, and auto-save bundle creation.

## Next Suggested Work

- Harden the spectroscopy-map MVP from `afm_gui/docs/spectroscopy_design.md`:
  add stronger large-map confirmation prompts, chunked on-disk recording, and
  real hardware integration behind the Device Manager.
- Continue slimming `MainWindow` into feature modules. Current extracted
  modules include `StageModule`, `LockInModule`, `ApproachModule`,
  `StorageModule`, `DeviceModule`, `ChannelImagesModule`, `ScanModule`,
  `ScanSequenceModule`, `WindowLayoutModule`, and `MetadataModule`; next
  candidates are help/status and remaining window coordination management.
- Define and validate real AFM/STM approach recipes before enabling unattended
  hardware approach workflows.
- Add approach recipe presets once the safe signal thresholds and actuator
  directions are validated on the real instruments.
- Harden the real scan acquisition worker with hardware-specific timing,
  buffered waveforms where supported, richer channel mapping, and stronger
  safety interlocks.
- Continue schema-version cleanup for metadata, saved layouts, and scan-mode
  configuration.
- Harden hardware capability interfaces, timing, routing validation, and safety
  interlocks for real devices.
- Add pre-scan memory budget warning for ordinary image scans.
- Broaden automated tests for CLI scan/export edge cases and GUI configuration
  behavior.
- Consider optional `float32` storage or chunked on-disk recording for very
  large scans.
