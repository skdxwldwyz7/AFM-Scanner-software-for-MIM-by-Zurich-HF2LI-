# AFM Scan Control Architecture

## Overview

AFM Scan Control is a PyQt6, pyqtgraph, and QCoDeS-based prototype for AFM scan
control. The current hardware layer can connect configured adapters through the
Device Manager while preserving a mock fallback for legacy offline development.
The default FM-AFM GUI path requires the HF2LI and explicitly disables fallback.

## FM-AFM extension

The existing layers remain intact. `ZurichHF2LIAdapter` now also provides XY
scanner output through `HF2FMInterface`: AUX1/2 offsets are the only new writable
nodes. `FMAcquisition` reads the selected channels and validates feedback state;
`AdapterScannerDevice` executes bounded XY ramps in its existing worker thread.
PLL/PID/AUX3/AUX4 remain owned by LabOne. The MultiField controller is not a
software dependency in this profile.

`FMAFMModule` owns background readout, three time plots, bounded CSV history and
manual XY; it shares a serialized HF2 I/O lock with scanning. The default
`devices.yaml`, `scan_modes.yaml` and `layout_fm_afm.json` select this workflow.
See `fm_afm_usage.md` for wiring, units, limits and polling limitations. Legacy
stage, A–D lock-in and spectroscopy paths described below remain separate.

The detailed progress archive is stored in:

```text
afm_gui/docs/progress_summary.md
```

The architecture diagrams are stored in:

```text
afm_gui/docs/architecture_diagram.md
```

Spectroscopy-map design notes are stored in:

```text
afm_gui/docs/spectroscopy_design.md
```

Hardware integration notes are stored in:

```text
afm_gui/docs/hardware_integration_notes.md
```

## Main Layers

- `ui/`: PyQt6 GUI, dockable panels, menus, display controls.
- `core/`: scan configuration, scan controller, stage controller, lock-in
  controller, approach controller, geometry, scan modes, parameter tree.
- `device/`: device adapters, scan-device bridges, mock devices, and the
  config-driven `DeviceManager`.
- `protocol/`: SPM command builders.
- `data/`: data exporters, currently Gwyddion Simple Field (`.gsf`).
- `config/`: scan mode/channel definitions and device definitions.
- `docs/`: architecture and progress documentation shown from Help or kept as
  project notes.

## Core Flow

```text
GUI / CLI
  -> ScanConfig + scan_modes.yaml
  -> DeviceManager + devices.yaml
  -> ParameterTree
  -> ScanController
  -> AdapterScannerDevice / MockScannerDevice fallback
  -> line_data_ready
  -> images[scan_pass][channel][line, pixel]
  -> GUI display / CLI summary / GSF export
```

The GUI scan path uses `AdapterScannerDevice`. At scan start it asks
`DeviceManager.adapter_for_function("scan_scanner")` for the assigned scanner
adapter. If a connected adapter is available, each line is acquired by stepping
through the generated scan points, setting X/Y voltages on the scanner adapter,
and reading channel values through an acquisition callback. If no scanner
adapter is connected, it falls back to `MockScannerDevice` so the GUI remains
usable offline.

The first acquisition callback is implemented by `LockinScanAcquisition` in
`core/lockin_acquisition.py`: it reads the applied Lock-in Scan Routing table.
Internal image channels such as `signal_a` through `signal_d` are mapped to a
configured lock-in device, device channel, and signal (`x`, `y`, `r`, `theta`,
or `frequency`). Multiple image channels can therefore read from
different lock-ins, or from different channels on the same Zurich HF2LI.
Missing, disconnected, or temporarily failing routes are filled with `0` so
scanner motion can continue during hardware bringup.

## GUI

The GUI uses pyqtgraph `DockArea`. The fixed top menu bar remains available even
when panels are moved, hidden, or closed.

The visible panel widgets are split into small builders under
`afm_gui/ui/panels/`, while feature modules under `afm_gui/ui/modules/` own
most panel logic. The main window remains the workbench: it creates the shared
controllers and wires cross-panel coordination.

Dockable panels:

- Channel Images
- Line Plot
- Scan Parameters
- Controls
- Stage Map
- Lock-in Amplifier
- Approach
- State
- Device Manager
- Parameter Tree
- Command Log

The GUI `Scan Parameters` panel treats X/Y scan geometry as open-loop scanner
output voltage. Center X/Y, width, height, image axes, ROI coordinates, and
probe readout are shown in volts, and linear speed is shown in V/s. The GUI
sets `ScanConfig.xy_unit` to `V` and uses a direct voltage scale for scanner
output. The CLI keeps its older default coordinate convention unless changed
explicitly.

The `View` menu can show, hide, and restore panels. It can also reload the
startup layout or save/load user layout JSON files.

At startup the GUI loads `afm_gui/config/layout1.json` as the preferred working
layout. `Restore Default Layout` reloads this startup layout; the code-defined
fallback layout is used only when the startup layout is missing or invalid. The
current startup layout uses three main columns: Stage Map on the left, Scan
Parameters in the middle, and Channel Images on the right.
Controls, Parameter Tree, and Command Log sit below the left column; Line Plot
and State sit below the right column.
Device Manager opens automatically as a floating window at startup so
connection state is visible without taking space from the main DockArea.
Lock-in Amplifier opens as a floating panel from `View` instead of being docked
into the already dense startup workspace. Closing the floating window hides the
panel and updates the `View` menu state instead of restoring the panel into the
main DockArea. The Spectroscopy module remains implemented and tested, but is
temporarily hidden from the main GUI until its real-hardware routing is
clarified.

The Controls panel includes scan sequencing and Auto Save settings. It can run
a single scan, continuously alternate up/down scans, or run a fixed total count
while alternating direction from the starting button. Auto Save is enabled by
default, uses `~/AFM_scans` by default, and can be disabled by the user.

The Stage Map panel provides XYZ stage motion and sample navigation through the
assigned `coarse_stage` adapter when connected, with a local controller fallback
when no stage adapter is available. It supports relative jogs, absolute moves,
home, Z-only movement, Z home, path clearing, and an aspect-locked X/Y sample
map in micrometers. The map is placed above the stage controls. Stage position,
including Z, is recorded in the parameter tree when a scan starts.

The Lock-in Amplifier panel provides lock-in setup and readout through local
controllers, with hardware adapter calls when a lock-in is connected. Channels
are arranged vertically. Each visible channel controls reference frequency,
amplitude, phase, time constant, sensitivity, reserve mode, and output state.
Each channel displays X, Y, R, and Theta and provides `Apply` and `Read`
actions. The readout also includes demod frequency when the adapter provides it.
PID and PLL are configured on the instrument side rather than from the GUI. The
panel is hidden in the startup layout and can be opened from `View` as a
floating panel. Lock-in reference and latest reading state for both channels are
recorded in the parameter tree when a scan starts.

The Approach panel provides a generic condition-based approach controller. It
does not encode a specific AFM or STM approach recipe; instead it moves a
selected actuator in small Z steps, reads a selected signal, and completes when
a configurable condition is satisfied for a required number of consecutive
samples. The first implementation supports `above`, `below`, `delta`,
`between`, and `outside` conditions, max travel/step safety limits,
pause/resume/abort/retract controls, and a mock actuator/signal path for safe
offline validation. Real hardware routes are available through conservative
providers: `coarse_stage.z` uses the connected device assigned to the
`coarse_stage` function, and signal readout can use any connected lock-in
device/channel/quantity. Selecting a real actuator or signal without the
required connection fails explicitly instead of falling back to mock data.
Device Manager is locked while approach is running or paused. Real approach
recipes should still be validated recipe by recipe before use.

The Device Manager panel loads hardware definitions from `devices.yaml`, shows
configured devices, provides connect/disconnect actions, lets the user edit
device connection JSON, and maps hardware functions to devices. Registered
drivers currently include mock scanner, MultiField scanner, Newton LT06,
Attocube ANC350, Zurich HF2LI, and SRS SR830/SR860/SR865/SR865A lock-ins.

## Device Loading

Device definitions are loaded from:

```text
afm_gui/config/devices.yaml
```

Each device definition includes:

- device name and label
- kind, such as scanner, stage, or lockin
- driver identifier
- enabled state
- connection parameters

The same file can define function assignments. Each function includes:

- function name and label
- required device kind
- assigned device name

Example functions include scan scanner, coarse positioning stage, and lock-in
detection. Device snapshots and function assignments are recorded in the
parameter tree when a scan starts and refreshed again before export.

## Scan Modes And Channels

Scan modes are loaded from:

```text
afm_gui/config/scan_modes.yaml
```

Each mode defines:

- mode name and label
- default display count
- available channels
- channel labels
- channel units
- default enabled state

The current active mode is:

- `lockin`

The `lockin` mode is a hardware-bringup mode that exposes route slots A-D and
records A/B by default. It is useful when the scanner motion path works but
topography-specific signal mapping is not ready, or when lock-in hardware is
being validated through Device Manager.
The `topo`, `spectroscopy`, and `lift` definitions remain in
`scan_modes.yaml` but are temporarily disabled with `enabled: false`.

## Data Model

Recorded data is stored as:

```python
images[scan_pass][channel] -> 2D numpy array
```

Example:

```python
images["trace"]["topography"]
images["retrace"]["phase"]
```

Each image is shaped:

```text
lines x pixels
```

The GUI can display multiple channel views at once. Each view independently
selects:

- channel
- scan pass: `trace` or `retrace`
- display flattening mode
- colormap
- color range mode: auto or manual min/max

During scanning, image display updates are scoped to visible views whose
selected channel/pass changed on the latest line. This keeps display timing
matched to the scan line rate without redrawing unrelated channel views.

All channel image viewboxes are linked. A left-drag ROI can be loaded into scan
geometry through the plot context menu, and the ROI clears after loading.

## Runtime Parameter Updates

The following parameters can be changed while scanning. They take effect from
the next line:

- `linear`
- `t_sample`
- `t_settle`
- `t_rest`

Structural parameters such as width, height, pixels, lines, channels, and scan
mode are treated as next-scan parameters.

## Parameter Tree And Metadata

The controller owns a single parameter tree:

```python
controller.parameter_tree
```

It records:

- app metadata schema
- scan mode
- scan direction
- initial scan parameters
- current/final scan parameters
- geometry
- timing
- channels and units
- trace/retrace passes
- calibration
- GUI display state
- runtime line index
- runtime parameter update history
- storage events
- device/function snapshots
- stage state
- lock-in setup, latest readout, and scan routing
- approach setup and latest progress

The Parameter Tree dock displays this tree live. The same tree is saved with
data as `metadata.json`.

To keep long runs responsive, the tree is refreshed on scan start, scan finish,
manual refresh, and runtime parameter updates. It is not rebuilt on every scan
line.

## Long-Run Guardrails

- The command log uses a bounded text buffer and keeps only the latest 5000
  blocks.
- Recorded images are replaced at the start of each scan, so historical scans
  are not accumulated in memory.
- Line data shown in the line plot keeps only the latest line.
- Display flattening is applied only to the view being refreshed; saved data
  remains raw.
- Image refresh remains synchronized with line acquisition but skips unrelated
  visible views.
- Auto Save can write timestamped bundles on pause and finish.

Approximate raw image memory:

```text
passes * channels * lines * pixels * 8 bytes
```

Large scans should reserve several times this raw size for display and temporary
arrays.

## Export

Data export currently uses Gwyddion Simple Field (`.gsf`). Each channel/pass
combination is exported as a separate file. GUI export asks for a base filename;
that filename becomes the prefix for the exported bundle:

```text
sample01_signal_a_trace.gsf
sample01_signal_a_retrace.gsf
sample01_signal_b_trace.gsf
sample01_signal_b_retrace.gsf
sample01_metadata.json
```

Disabled modes such as `topo` keep their own channel names in
`scan_modes.yaml`, but exported filenames always follow the selected channels
of the active mode.

A complete metadata JSON file is saved next to the GSF files. Each GSF header
also contains compact metadata and references the matching metadata filename.

Auto Save uses timestamped bundle prefixes:

```text
afm_20260606_033000_finish_line0256_signal_a_trace.gsf
afm_20260606_033000_finish_line0256_metadata.json
```

The autosave event, output directory, prefix, and line index are recorded in the
parameter tree before export.

Future spectroscopy-map data should use a dedicated HDF5-based bundle instead
of forcing complete three-dimensional spectrum cubes into GSF. The current MVP
has a Spectroscopy panel, mock point-wise controller, HDF5 `.afmspm.h5` bundle
writer/reader, memory estimate, button state handling, and selected-slice GSF
export. Design notes and remaining questions are documented in
`afm_gui/docs/spectroscopy_design.md`.

## CLI

The CLI entry point is:

```bash
afm-cli
```

Available commands:

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

The CLI and GUI share the same scan controller, scan mode definitions, metadata
tree, and export logic.

Runtime update flags are available on CLI scans:

```bash
--update-after-line
--update-linear
--update-sample
--update-settle
--update-rest
```

## Next Architectural Direction

Panel modules now live in:

```text
ui/panels/
  channel_images.py
  approach.py
  stage_map.py
  lockin.py
  line_plot.py
  scan_parameters.py
  controls.py
  status.py
  parameter_tree.py
  command_log.py
```

Feature modules are starting to live in:

```text
ui/modules/
  channel_images.py
  approach.py
  device.py
  stage.py
  lockin.py
  layout.py
  metadata.py
  scan.py
  scan_sequence.py
  storage.py
```

The current refactoring direction is:

- keep slimming `MainWindow` by extracting feature modules around clean
  boundaries
- harden real hardware timing, routing validation, and safety interlocks
- continue evolving schema versions for metadata, layout files, and scan-mode
  configuration

The first item has started with `StageModule`, `LockInModule`, `StorageModule`,
`DeviceModule`, `ChannelImagesModule`, `ApproachModule`, `ScanModule`,
`ScanSequenceModule`, `WindowLayoutModule`, and `MetadataModule`. These modules
now own their panel widgets or bound controls, controllers/managers, signal
wiring, display updates, save/device actions, scan sequencing, dock layout
persistence, floating-panel behavior, approach state, scan parameter
orchestration, channel image display, line plot updates, ROI handling, metadata
snapshots/events, and parameter tree rendering. The next extraction candidates
are help/status and remaining window coordination logic.

## Tests

The automated smoke suite uses standard-library `unittest`:

```bash
QT_QPA_PLATFORM=offscreen conda run -n afm-gui python -m unittest discover -s tests
```

It covers core scan/export behavior, metadata tree rendering, GUI module wiring,
ROI-to-scan-parameter updates, lock-in routing, scan sequencing, approach
control paths, runtime metadata updates, spectroscopy export, and auto-save
bundle creation.
