# AFM GUI Prototype

This repository contains the current AFM scan-control GUI prototype. It is a
fresh framework built with PyQt6, pyqtgraph, and QCoDeS. Hardware control is
still represented by a mock device, but the application already exercises the
same scan-controller path that a future real device adapter can use.

## Current Scope

- Dockable PyQt6 GUI for AFM scan control.
- CLI commands that share the same controller, scan config, scan modes, and
  export path as the GUI.
- Configurable scan modes and channel definitions loaded from YAML.
- Configurable device definitions loaded from YAML.
- Device Manager panel for connecting/disconnecting hardware adapters.
- Stage Map panel for XYZ stage jogging and sample navigation.
- Lock-in Amplifier panel for mock lock-in setup and readout.
- Multi-channel trace/retrace data recording.
- Multiple synchronized channel image views.
- Display-only image flattening without changing saved raw data.
- ROI loading from channel images into the next scan's geometry.
- Parameter tree metadata saved with exported data.
- Gwyddion Simple Field (`.gsf`) export.
- Long-run guardrails for bounded logs and lower GUI refresh overhead.

## Environment

The current development environment is named `afm-gui`.

```bash
conda activate afm-gui
uv pip install -e .
```

## Run

GUI:

```bash
conda run -n afm-gui python -m afm_gui.main
```

CLI:

```bash
afm-cli gui
afm-cli modes
afm-cli channels --mode topo
afm-cli devices
afm-cli stage --dx 10 --dy 0 --dz 0
afm-cli lockin --channel ch1 --output --frequency 1000 --amplitude 0.1
afm-cli preview-commands --mode topo --direction up --pixels 128 --lines 128
afm-cli scan --mode topo --direction up --pixels 128 --lines 128 \
  --export-gsf ./scan_out --export-prefix sample01
afm-cli scan --mode topo --auto-save-dir ./scan_out
```

Runtime parameter updates can be exercised from the CLI:

```bash
afm-cli scan --pixels 16 --lines 4 --width 20 --height 20 --linear 10000 \
  --sample 0 --settle 0 --rest 0 \
  --update-after-line 2 --update-linear 20000 --print-commands
```

## GUI Workflow

The GUI is built around pyqtgraph `DockArea` widgets. The fixed top menu bar
contains `File`, `Settings`, `View`, and `Help`. The `View` menu can show,
hide, and restore panels, reload the startup layout, and save/load
user layout JSON files.
At startup the GUI loads `afm_gui/config/layout1.json` as the preferred working
layout. If that file is missing or invalid, the code-defined fallback layout is
used. `Restore Default Layout` reloads the startup layout and only falls back to
the code-defined layout if the startup layout cannot be loaded.
Less frequently used panels such as Device Manager and Command Log also provide
a right-click `Close Panel` action and can be restored from `View`.
Panels that are hidden in the startup layout, such as Device Manager and
Lock-in Amplifier, open as floating panels from `View` so the main workspace
does not grow wider. Closing one of these floating panels hides it and clears
the matching `View` menu check mark instead of docking it back into the main
window.

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

The Controls panel includes Auto Save settings. Auto Save is enabled by default
and uses `~/AFM_scans` unless the user chooses another directory. It writes a
timestamped GSF bundle when a scan is paused and when a scan finishes.

The Stage Map panel controls a mock XYZ stage and displays the sample navigation
path in X/Y. It supports relative jogs, absolute moves, home, Z-only movement,
Z home, path clearing, and a linked X/Y map in micrometers. Stage position,
including Z, is included in scan metadata.

The Lock-in Amplifier panel controls two mock lock-in channels arranged as
Channel 1 and Channel 2. Each channel has the same reference, readout, PID, and
PLL sections. It can set reference frequency, amplitude, phase, time constant,
sensitivity, reserve mode, output state, PID gains/limits, and PLL center,
bandwidth, phase setpoint, and frequency limits. Readout values X, Y, R, and
Theta are shown for each channel. Reference, PID, PLL, and readout state for
both channels are recorded in scan metadata. The panel is hidden by the startup
layout and can be opened from `View` as a floating panel.

The Device Manager panel loads hardware definitions from YAML. The default
configuration is:

```text
afm_gui/config/devices.yaml
```

It currently supports mock connections and records pending real drivers such as
attocube stages, multi-field positioners, and lock-in amplifiers. The same YAML
file also defines function assignments, such as which device is used for scan
scanner, coarse stage, field stage, or lock-in detection. The GUI shows these in
a Function Assignments table, and both device state and function assignments are
included in scan metadata.

## Architecture Direction

Current refactoring priorities:

- keep slimming `MainWindow` into feature modules; `StageModule`,
  `LockInModule`, `StorageModule`, `DeviceModule`, `ChannelImagesModule`, and
  `ScanModule`, and `MetadataModule` now own their panel-local controllers,
  signal wiring,
  save/device actions, scan parameter orchestration, channel image display, ROI
  handling, line plot updates, metadata snapshots/events, and parameter tree
  rendering
- add schema versions for metadata, saved layouts, and scan-mode configuration
- define a clearer hardware capability/interface layer before connecting real
  devices

Channel image views are equal-sized, aspect-locked plots. Each view can select:

- channel
- scan pass: `trace` or `retrace`
- display flattening: `Raw`, `Line Mean`, or `Plane`
- colormap via the color scale context menu

All channel image viewboxes are linked, so pan and zoom stay synchronized.
Left-drag in a channel image creates a shared ROI rectangle. Right-click the
image and choose `Load ROI Into Scan Parameters` to use the rectangle center and
size for the next scan; the ROI clears after it is loaded.

## Scan Modes

Scan modes and channels are loaded from:

```text
afm_gui/config/scan_modes.yaml
```

Each mode defines:

- mode name and label
- default number of display views
- available channels
- channel labels and units
- default enabled state

The current bundled modes are:

- `topo`
- `spectroscopy`
- `lift`

## Data And Metadata

Recorded data is stored in memory as:

```python
images[scan_pass][channel] -> 2D numpy array
```

Each selected channel/pass pair is exported as a separate `.gsf` file. A
complete metadata parameter tree is saved next to the GSF files, and each GSF
header references that metadata file.

In the GUI, `Save GSF` asks for a base filename. For example, saving as
`sample01.gsf` writes files such as:

```text
sample01_topography_trace.gsf
sample01_topography_retrace.gsf
sample01_metadata.json
```

The CLI uses `--export-prefix` for the same naming behavior. Without a prefix,
the legacy names `topography_trace.gsf` and `metadata.json` are used.

Auto Save filenames include a local timestamp, event name, and line number:

```text
afm_20260606_033000_pause_line0128_topography_trace.gsf
afm_20260606_033000_pause_line0128_metadata.json
```

The autosave event is recorded in the exported metadata.

Runtime-editable parameters:

```text
linear, sample, settle, rest
```

These take effect from the next scan line. Structural parameters such as width,
height, pixels, lines, channels, and scan mode are next-scan settings.

## Long-Run Notes

- Command Log keeps only the latest 5000 text blocks.
- Image data is replaced at the start of each new scan; previous scans are not
  accumulated in memory.
- The line plot keeps only the latest line.
- Parameter Tree refreshes on scan start, scan finish, runtime updates, and
  manual refresh. It is not rebuilt on every scan line.
- Image display stays synchronized to scan line updates, but only visible views
  whose selected channel/pass changed are redrawn.
- Auto Save is enabled by default in the GUI and can be disabled from the
  Controls panel.

Approximate raw image memory:

```text
passes * channels * lines * pixels * 8 bytes
```

For large scans, reserve roughly 3-6 times the raw data size for GUI display,
temporary arrays, Qt/pyqtgraph overhead, and export operations.

## Test

The current automated smoke suite uses the Python standard-library `unittest`
runner, so it does not require installing `pytest`:

```bash
QT_QPA_PLATFORM=offscreen conda run -n afm-gui python -m unittest discover -s tests
```

It covers core scan/export behavior, metadata tree rendering, GUI module wiring,
ROI-to-scan-parameter updates, and auto-save bundle creation.

## Documentation

The GUI Help menu displays:

```text
afm_gui/docs/architecture_summary.md
```

The architecture diagrams are stored in:

```text
afm_gui/docs/architecture_diagram.md
```

The detailed current progress archive is:

```text
afm_gui/docs/progress_summary.md
```
