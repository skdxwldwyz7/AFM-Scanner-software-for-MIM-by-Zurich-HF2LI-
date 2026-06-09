# Spectroscopy Map Design Notes

## Goal

Add a spectroscopy-map mode where each raster point records a one-dimensional
spectrum instead of only scalar image values. This should support workflows such
as bias spectroscopy, frequency sweeps, force curves, or other point-wise
one-dimensional sweeps.

The first implementation is a mock-device MVP that proves the full workflow:

- configure spectroscopy parameters
- acquire one spectrum at each scan point
- display a live one-dimensional spectrum
- display a two-dimensional slice map at a selected spectrum value
- save the complete data as a dedicated spectroscopy data bundle

Current implementation status:

- `SpectroscopyConfig` exists.
- `SpectroscopyController` performs mock point-wise acquisition.
- `Spectroscopy` module, panel, and tests exist, but the dock is temporarily
  hidden from the GUI/View menu until the real-hardware routing is clarified.
- The panel has axis controls, start/pause/resume/stop state management,
  memory estimate, live spectrum display, slice map display, HDF5 bundle save,
  and selected-slice GSF export.
- The complete bundle uses `.afmspm.h5`.

The remaining design work is primarily real hardware integration, large-map
streaming/chunking, stronger confirmation prompts, and richer spectroscopy
inspection workflows.

## High-Level Concept

The current scan data model stores one scalar per channel/pass/pixel:

```python
images[scan_pass][channel] -> ndarray(lines, pixels)
```

Spectroscopy mapping adds a third axis:

```python
spectra[scan_pass][channel] -> ndarray(lines, pixels, spectrum_points)
spectrum_axis -> ndarray(spectrum_points)
```

For bias spectroscopy, examples would be:

```python
spectrum_axis                      # bias values in V
spectra["trace"]["current"][y, x]  # I-V curve at one point
spectra["trace"]["didv"][y, x]     # dI/dV curve at one point
```

Two-dimensional scalar maps can still be kept for topography or preview data:

```python
maps[scan_pass][channel] -> ndarray(lines, pixels)
```

## Package Structure

Implemented files:

```text
afm_gui/core/spectroscopy_config.py
afm_gui/core/spectroscopy_controller.py
afm_gui/data/spectroscopy.py
afm_gui/ui/panels/spectroscopy.py
afm_gui/ui/modules/spectroscopy.py
```

Keep `ScanController` focused on ordinary line-based image scans. Add a
parallel `SpectroscopyController` for point-wise spectroscopy acquisition. The
two controllers can share scan geometry, device assignments, metadata helpers,
and UI state, but their acquisition timing and signals should remain separate.

## Configuration Model

The spectroscopy configuration can either extend `ScanConfig` or live as a
separate dataclass combined with `ScanConfig` when a spectroscopy map starts.
A separate dataclass is cleaner for early development:

```python
@dataclass(slots=True)
class SpectroscopyConfig:
    enabled: bool = False
    axis_name: str = "bias"
    axis_label: str = "Bias"
    axis_unit: str = "V"
    start: float = -1.0
    stop: float = 1.0
    points: int = 201
    dwell: float = 0.001
    settle: float = 0.02
    channels: tuple[str, ...] = ("current", "didv")
```

Potential axis types:

- `bias`
- `frequency`
- `z`
- `field`
- `custom`

## Acquisition Flow

Ordinary scans are line-based. Spectroscopy maps are point-based:

```text
for each line:
  for each pixel:
    move probe/scanner to point
    wait spectroscopy settle time
    sweep spectrum axis
    record one-dimensional arrays for selected channels
    update current spectrum plot
    update selected two-dimensional slice map
```

Controller signals should be point-oriented:

```python
spectrum_point_changed = pyqtSignal(int, int, object)
spectrum_slice_changed = pyqtSignal(object)
spectroscopy_state_changed = pyqtSignal(str)
spectroscopy_finished = pyqtSignal()
```

The mock device can synthesize curves first, for example:

- current: nonlinear I-V curve with position-dependent amplitude
- didv: numerical derivative or analytic derivative
- amplitude/phase: simple smooth functions for lock-in-like channels

## Spectroscopy Panel

Add a standalone dockable panel named `Spectroscopy`. It should be available
from the `View` menu. It can start hidden or floating by default until the
workflow matures.

Suggested controls:

- axis type selector: Bias, Frequency, Z, Field, Custom
- start, stop, points, dwell, settle
- channel selection
- selected scan pass
- start spectroscopy map
- pause
- resume
- stop
- save spectroscopy bundle
- slice index/value control

Suggested views:

- current point one-dimensional spectrum
- two-dimensional slice map at the selected spectrum-axis value
- current line/pixel progress
- selected pixel spectrum inspector, eventually driven by clicking the slice
  map

The panel should read shared raster geometry from the existing scan-parameter
state:

- center X/Y
- width/height
- angle
- pixels/lines
- scan direction

## Data Format

Do not force complete spectroscopy data into Gwyddion Simple Field. GSF remains
appropriate for two-dimensional image exports and optional slice previews, but
the complete spectroscopy map needs a dedicated format.

Use an HDF5-based bundle with a project-specific extension:

```text
sample01.afmspm.h5
```

Proposed layout:

```text
/
  metadata
  axes/
    x_nm
    y_nm
    spectrum
  maps/
    topography_trace
    topography_retrace
  spectra/
    current_trace
    didv_trace
    amplitude_trace
    phase_trace
  previews/
    current_at_bias_000
    didv_at_bias_100
```

Dataset shapes:

```text
axes/spectrum          -> (spectrum_points,)
maps/topography_trace  -> (lines, pixels)
spectra/current_trace  -> (lines, pixels, spectrum_points)
spectra/didv_trace     -> (lines, pixels, spectrum_points)
```

Dataset attributes should include:

- label
- unit
- channel
- scan_pass
- axis_order

Bundle-level metadata should include:

- format name: `AFM Spectroscopy Bundle`
- format version
- app/software version
- created time
- scan geometry
- scan mode
- scan direction
- spectroscopy axis name/label/unit
- spectroscopy start/stop/points/dwell/settle
- selected channels and units
- device snapshot and function assignments
- export source: GUI or CLI

The `afm_gui/data/spectroscopy.py` module should expose:

```python
write_spectroscopy_bundle(path, bundle)
read_spectroscopy_bundle(path)
```

## GSF Relationship

GSF export should remain available for two-dimensional data:

- ordinary topography/error/amplitude/phase images
- selected spectroscopy slice maps
- preview images

The complete spectroscopy cube should be stored in `.afmspm.h5`. A selected
slice can be exported as GSF with metadata recording the corresponding spectrum
axis value.

Example output:

```text
sample01.afmspm.h5
sample01_current_bias_0.100V.gsf
sample01_metadata.json
```

## MVP Implementation Plan

Completed:

1. Add spectroscopy data-format writer and reader with tests.
2. Add `SpectroscopyConfig` and a mock spectroscopy acquisition path.
3. Add `SpectroscopyController` with point-wise progress signals.
4. Add `SpectroscopyPanel` with bias/frequency/Z/field/custom axis controls,
   current spectrum plot, selected slice map, button state management, and raw
   memory estimate.
5. Add `SpectroscopyModule` and keep it available in code/tests; expose it in
   `MainWindow` and the `View` menu only after the real-hardware routing is
   clarified.
6. Add save action for `.afmspm.h5`.
7. Add selected-slice GSF export.

Next implementation work:

1. Connect real bias source, lock-in, and Zurich/device-manager integrations.
2. Add chunked on-disk recording for large maps.
3. Add stronger large-map confirmation prompts.
4. Add selected-pixel spectrum inspection from the slice map.
5. Decide trace/retrace policy for real spectroscopy acquisition.

## Open Design Questions

- Should spectroscopy acquisition be point-by-point only, or should line-based
  batched spectra be supported for faster hardware?
- Should live storage stream directly into HDF5 for large maps, or should the
  first version keep all data in memory and save at the end?
- Should `spectroscopy` in `scan_modes.yaml` represent scalar spectroscopy-map
  preview channels, full spectrum channels, or both?
- How should trace/retrace work for spectroscopy maps: acquire both directions,
  trace only, or user-selectable passes?
- Which hardware function assignments are required for the first real device
  implementation: scanner, bias source, lock-in, Zurich HF2LI, or additional
  DAQ?
