# AFM Scan Control Architecture

## Overview

AFM Scan Control is a PyQt6, pyqtgraph, and QCoDeS-based prototype for AFM scan
control. The current hardware layer can connect configured adapters through the
Device Manager while preserving a mock fallback for offline development.

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
  controller, geometry, scan modes, parameter tree.
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

The first acquisition callback is implemented in `MainWindow`: when the
assigned `lockin` adapter is connected, Zurich demod samples are mapped into
scan channels such as `topography`, `error`, `amplitude`, `phase`, `current`,
`didv`, `lockin_x`, and `lockin_phase`. Missing channels are filled with `NaN`.

## GUI

The GUI uses pyqtgraph `DockArea`. The fixed top menu bar remains available even
when panels are moved, hidden, or closed.

The visible panel widgets are being split into small modules under
`afm_gui/ui/panels/`. The main window remains the workbench: it owns controller
signals, shared GUI state, menus, dock layout, and cross-panel coordination.

Dockable panels:

- Channel Images
- Line Plot
- Scan Parameters
- Controls
- Stage Map
- Lock-in Amplifier
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
Panels that are hidden in the startup layout, such as Device Manager and
Lock-in Amplifier, open as floating panels from `View` instead of being docked
into the already dense startup workspace. Closing the floating window hides the
panel and updates the `View` menu state instead of restoring the panel into the
main DockArea.

The Controls panel includes Auto Save settings. Auto Save is enabled by default,
uses `~/AFM_scans` by default, and can be disabled by the user.

The Stage Map panel provides mock XYZ stage motion and sample navigation. It
supports relative jogs, absolute moves, home, Z-only movement, Z home, path
clearing, and an aspect-locked X/Y sample map in micrometers. The map is placed
above the stage controls. Stage position, including Z, is recorded in the
parameter tree when a scan starts.

The Lock-in Amplifier panel provides mock lock-in setup and readout for two
channels arranged vertically. Each channel controls reference frequency,
amplitude, phase, time constant, sensitivity, reserve mode, and output state.
Each channel displays X, Y, R, and Theta and provides `Apply` and `Read`
actions. PID and PLL are configured on the instrument side rather than from the
GUI. The panel is hidden in the startup layout and can be opened from `View` as
a floating panel. Lock-in reference and latest reading state for both channels
are recorded in the parameter tree when a scan starts.

The Device Manager panel loads hardware definitions from `devices.yaml`, shows
configured devices, provides connect/disconnect actions, and lets the user map
hardware functions to devices. The first version uses mock connections and marks
non-mock drivers as pending implementation.

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

Example functions include scan scanner, coarse positioning stage, multi-field
stage, and lock-in detection. Device snapshots and function assignments are
recorded in the parameter tree when a scan starts.

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

The `lockin` mode is a hardware-bringup mode that only enables `lockin_x` and
`lockin_phase` by default. It is useful when the scanner motion path works but
topography-specific signal mapping is not ready or the Zurich connection is
being debugged.
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
- geometry
- timing
- channels and units
- trace/retrace passes
- calibration
- GUI display state
- runtime line index
- runtime parameter update history

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
sample01_topography_trace.gsf
sample01_topography_retrace.gsf
sample01_error_trace.gsf
sample01_error_retrace.gsf
sample01_metadata.json
```

A complete metadata JSON file is saved next to the GSF files. Each GSF header
also contains compact metadata and references the matching metadata filename.

Auto Save uses timestamped bundle prefixes:

```text
afm_20260606_033000_finish_line0256_topography_trace.gsf
afm_20260606_033000_finish_line0256_metadata.json
```

The autosave event, output directory, prefix, and line index are recorded in the
parameter tree before export.

Future spectroscopy-map data should use a dedicated HDF5-based bundle instead
of forcing complete three-dimensional spectrum cubes into GSF. The proposed
format and panel/controller design are documented in
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
afm-cli channels --mode topo
afm-cli devices
afm-cli stage --dx 10 --dy 0 --dz 0
afm-cli lockin --channel ch1 --output --frequency 1000 --amplitude 0.1
afm-cli preview-commands --mode topo
afm-cli scan --mode topo --export-gsf ./scan_out --export-prefix sample01
afm-cli scan --mode topo --auto-save-dir ./scan_out
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
  device.py
  stage.py
  lockin.py
  metadata.py
  scan.py
  storage.py
```

The current refactoring direction is:

- keep slimming `MainWindow` by extracting feature modules around clean
  boundaries
- add schema versions for metadata, layout files, and scan-mode configuration
- define a clearer hardware capability/interface layer before connecting real
  devices

The first item has started with `StageModule`, `LockInModule`, `StorageModule`,
`DeviceModule`, `ChannelImagesModule`, `ScanModule`, and `MetadataModule`.
These modules now own their panel widgets or bound controls,
controllers/managers, signal wiring, display updates, save/device actions, scan
parameter orchestration, channel image display, line plot updates, ROI
handling, metadata snapshots/events, and parameter tree rendering. The next
extraction candidates are help, layout, status, and remaining window
coordination logic. Another near-term step is to add pre-scan memory budget
estimation and warning logic for large scans.

## Tests

The automated smoke suite uses standard-library `unittest`:

```bash
QT_QPA_PLATFORM=offscreen conda run -n afm-gui python -m unittest discover -s tests
```

It covers core scan/export behavior, metadata tree rendering, GUI module wiring,
ROI-to-scan-parameter updates, and auto-save bundle creation.
