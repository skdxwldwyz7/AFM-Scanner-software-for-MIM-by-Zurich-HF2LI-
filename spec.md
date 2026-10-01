# GUI-for-mim Project Spec

This file is the working specification and append-only change ledger for the
GUI-for-mim application. Update it after every code or configuration change so
future work can resume from the recorded behavior, files, verification, and open
risks.

## Project Shape

The application is a Python/PyQt AFM control GUI organized around these layers:

```text
afm_gui/ui       panels, user interaction, and feature modules
afm_gui/core     scan configuration, geometry, controllers, and metadata
afm_gui/device   device registry, adapters, and background hardware workers
afm_gui/data     image and export formats
afm_gui/config   device, scan-mode, and startup-layout configuration
tests            offline unit and GUI integration tests
```

The GUI scan path is `ScanModule -> ScanController -> AdapterScannerDevice ->
device adapter`. Acquired lines return through `line_data_ready`, are written
into `ScanController.images`, and are consumed by the channel-image and storage
modules. Hardware calls for adapter scans run in a worker thread. The parameter
tree is the common metadata source for the GUI, GSF metadata JSON, and scan
reports.

## Active FM-AFM Hardware Contract

The active bundled scan mode is `fm_afm` / `FM-AFM / HF2 AUX XY` and expects a
connected Zurich HF2LI assigned to both `scan_scanner` and lock-in readout.
LabOne remains solely responsible for PLL/PID setup and protection; the GUI
does not configure or read PLL/PID nodes during this minimal scan mode.

| HF2 output | Application role | Program behavior |
| --- | --- | --- |
| AUX1 | X scanner voltage | XY scan writes Offset; value is recorded |
| AUX2 | Y scanner voltage | XY scan writes Offset; value is recorded |
| AUX3 | Z PID output | Value is recorded; no software threshold check |
| AUX4 | PLL frequency-shift output | Value is recorded |

Only AUX1/2 are writable by FM scan motion. AUX3/PID and AUX4/PLL remain under
LabOne control. FM scanning and monitoring read only the four AUX output-value
nodes. There is no software check for PLL lock, PID state/routing, AUX routing,
PID saturation, or AUX3/Z voltage limits. A missing selected AUX value still
fails the scan, and local XY geometry/voltage limits remain. External hardware
protection and correct LabOne configuration are therefore mandatory.

## Scan And Data Contract

- Scan geometry is expressed in HF2 output volts for this mode. Scan parameters
  include center, width, height, rotation, pixels, lines, linear speed, sample,
  settle, rest, direction, and trace/retrace selection.
- The selected scan channels are recorded as `images[pass][channel]` arrays;
  not-yet-sampled FM pixels remain NaN rather than fabricated zeroes.
- Runtime scan speed/sample/settle/rest edits apply from the next line. Geometry
  and channel edits apply to a later scan.
- Selected channel-image views, passes, color ranges, and flattening choices are
  display metadata, distinct from raw recorded scan data.
- GSF export and its metadata JSON remain governed by the existing Auto Save
  checkbox. Scan reports are written after every scan end (completed, stopped,
  or failed), independently of that checkbox, to the configured Auto Save
  directory or `~/AFM_scans` when no directory is set.

## Scan Report Contract

Each finished scan produces one UTF-8 `*_scan_report.txt` file. Its detailed
metadata includes:

- scan identifier, completion state, start/end UTC, duration, stop/error reason;
- scan mode, direction, initial/current geometry and timing, selected channels,
  units, passes, calibration, runtime parameter updates, and image display
  selections;
- HF2 device identity/connection context, XY software limits, and the final
  AUX1-AUX4 output-value snapshot;
- AUX1-AUX4 values and any corresponding read failures; PLL/PID parameters and
  routes are intentionally absent in this speed-prioritized mode;
- report output path and the associated application metadata.

After the scan motion loop ends, report capture runs in the scan worker before
it signals completion, so slow LabOne reads do not run inside the GUI thread.
The GUI remains responsive, but the Idle notification and a queued next scan
wait for that final snapshot. The text report and parameter-tree metadata are
records of readable state, not a complete LabOne settings backup. Node reads
can fail after a hardware/server disconnect; such failures must be recorded
rather than replaced with assumed values.

## Change Ledger

Append a new dated entry after every change. Do not rewrite older entries; add a
correction entry if an earlier record was inaccurate.

### 2026-10-01 - Remove PLL/PID safety reads and keep AUX-only imaging

- Restricted FM imaging and Monitor channels to AUX1, AUX2, AUX3, and AUX4.
- Replaced per-channel/whole-group reads with one LabOne wildcard request for
  `auxouts/*/value` per sample, with individual AUX reads only as a compatibility
  fallback when the wildcard response is unavailable or incomplete.
- Removed all PLL/PID reads from scan preflight, per-pixel acquisition, XY
  route rechecks, Monitor, and completed-scan reports.
- Removed PLL lock/PID state, PID routing/saturation, AUX route, and AUX3/Z
  threshold protections. Kept local finite-value checks, XY range limits,
  geometry validation, motion rate limiting, and AUX1/AUX2-only writes.
- Removed unused PLL/PID index and Z threshold fields from the active device
  profile. LabOne and external hardware now carry all feedback-loop protection.
- Files changed: `afm_gui/config/devices.yaml`,
  `afm_gui/config/scan_modes.yaml`, `afm_gui/core/fm_afm.py`,
  `afm_gui/device/adapters/hf2_fm.py`, `afm_gui/ui/modules/fm_afm.py`,
  `afm_gui/ui/panels/fm_afm.py`, `tools/fm_scan_timing.py`,
  `afm_gui/docs/fm_afm_usage.md`,
  `afm_gui/docs/HF2LI_FM_AFM_进针与_mim-gui_扫描_SOP.md`,
  `tests/test_fm_afm.py`, and `spec.md`.
- Verification: `compileall`, YAML loading, `git diff --check`, and an offline
  fake-DAQ test passed. The fake test confirmed one AUX wildcard read, no
  PLL/PID or individual-node reads, and one batched AUX1/AUX2 write. Full pytest
  collection is unavailable in the local base environment because PyQt6 is not
  installed. Real HF2LI timing and wildcard response shape must be verified on
  the remote PC.

### 2026-09-29 - Reduce per-pixel HF2 snapshot reads

- Changed active FM scan snapshots to read only requested HF2 nodes rather than
  issuing wildcard reads for entire PLL/PID/AUX groups at every pixel.
- Static PLL/PID/AUX configuration nodes are cached for one scan. PLL lock and
  enable states, PID enable state, AUX output values, and selected dynamic image
  channels remain freshly read for each pixel.
- Kept preflight validation and the completed-scan report snapshot behavior.
- Clarified node semantics in the implementation: `pids/0/output` is the PID
  output-routing enum, not the measured PID voltage. AUX3 remains the live Z
  voltage safety check; `pid_error` and PID shift remain available when
  selected as channels.
- Files changed: `afm_gui/device/adapters/hf2_fm.py`,
  `tests/test_fm_afm.py`, and `spec.md`.
- Verification: `compileall` passed and a standalone fake-DAQ check confirmed
  no wildcard reads during active scan snapshots, dynamic nodes are reread, and
  static values are cached. The pytest module could not be collected because
  the available Python environment lacks PyQt6. HF2LI timing and scan quality
  still require validation on the remote instrument.

### 2026-09-29 - Rewrite approach SOP and add mim-gui scan SOP

- Rewrote the operating procedure for the current AUX assignment: AUX1=X,
  AUX2=Y, AUX3=Z PID output, and AUX4=PLL frequency-shift output looped back to
  Aux In 1.
- Added the complete LabOne approach workflow: wiring, free-resonance sweep,
  PLL setup, AUX4 loopback calibration, measured feedback-sign test, coarse
  approach, PID routing/limits, bumpless loop enable, tuning, recovery, and
  shutdown.
- Added the mim-gui workflow: environment/server connection, hardware
  preflight, Monitor and manual XY use, scan geometry/timing/channels, fixed
  trace+retrace behavior, saving/reporting, repeat modes, automatic checks,
  and post-scan review.
- Documented the current safety limitation explicitly: software errors stop XY
  and cancel scan sequences but do not automatically disable PID or retract Z.
- Added quick checklists and a per-experiment record table.
- Files changed: `afm_gui/docs/HF2LI_FM_AFM_进针与_mim-gui_扫描_SOP.md`,
  `afm_gui/docs/fm_afm_usage.md`, and `spec.md`.
- Verification: cross-checked port assignments, LabOne route requirements,
  voltage limits, scan-pass behavior, channel defaults, storage behavior, and
  failure handling against current configuration and source. Documentation
  only; no hardware action or real-instrument validation was performed.

### 2026-09-28 - Establish progress ledger and scan reports

- Added this file to preserve the current architecture, FM-AFM hardware
  contract, reporting behavior, validation status, and a repeatable place to
  record future work.
- Added a detailed read-only HF2 report snapshot. It gathers scalar values
  available under the selected PLL, PID, AUX output, and AUX input node groups,
  supplements known required nodes individually, and records read errors.
- Passed worker completion state, duration, error/stop reason, and the final
  HF2 snapshot to `ScanController` before its Idle notification.
- Made final failure metadata authoritative in the controller so error display
  and repeat-sequence cancellation do not depend on queued-signal ordering.
- Added a text report for every scan completion, manual stop, or scan failure;
  it is independent of GSF Auto Save. The report is written to the configured
  output directory and its scan metadata is also attached to the parameter
  tree.
- Added offline coverage for PLL/PID/AUX snapshot contents, read-only behavior,
  worker failure snapshots, and report creation while GSF Auto Save is off.
- Files changed for this entry: `spec.md`,
  `afm_gui/device/adapters/hf2_fm.py`, `afm_gui/device/scan_device.py`,
  `afm_gui/core/scan_controller.py`, `afm_gui/ui/modules/storage.py`,
  `afm_gui/ui/main_window.py`, and `tests/test_fm_afm.py`.
- Verification: `python -m compileall afm_gui tests` passed, and an isolated
  FakeDAQ smoke check confirmed PLL/PID/AUX values are captured with no writes.
  GUI/unit tests could not import because the only available Conda environment
  is `base` and its Python has no PyQt6. No real HF2LI was available.
- Open validation: verify on the target computer that LabOne wildcard reads
  expose the expected node values and that report writing does not produce
  unacceptable scan-completion delay. The scan worker is already stopped at
  this point, and report errors are logged without changing scan outcome.

### Baseline already present in the worktree before this ledger

This is a consolidated snapshot of existing project state, not a claim that
each item was introduced on this date. Earlier worktree edits are uncommitted,
so Git does not provide a reliable per-change historical sequence.

- Added an HF2LI-specific FM-AFM mode, LabOne adapter, monitor, manual XY
  movement, and bounded XY ramp motion.
- Reassigned output roles to AUX1=X, AUX2=Y, AUX3=Z PID output, AUX4=PLL Δf;
  scan motion writes only AUX1/2 offsets and reads AUX3/AUX4.
- Added PLL lock, PID enabled, route, required-signal, and AUX3 range checks;
  loss of safety conditions stops XY while leaving Z under LabOne control.
- Added per-pixel HF2 acquisition and grouped/batched node reads, batched XY
  output updates, and periodic route checks during scanning.
- Changed FM defaults to useful image channels (including AUX3/AUX4, Δf, and
  PID error); removed fragile R/Theta defaults and synchronized scan channel
  checkboxes with channel-image selectors immediately.
- Added live image autoscaling/color-bar updates from valid sampled pixels.
- Added FM-specific startup layout/configuration, architecture/usage notes, and
  simulation-oriented tests. Real hardware validation remains separate.

## Future Entry Template

Copy this block to the end of `Change Ledger` for each implementation task:

```text
### YYYY-MM-DD - Short task name

- Request/scope:
- Behavior changed:
- Files changed:
- Safety/data compatibility notes:
- Verification and result:
- Unverified items / next step:
```

## Maintenance Rules

- Keep the requested scope explicit; do not fold unrelated cleanup into a task.
- Preserve LabOne ownership of PLL/PID settings and the AUX1/2-only FM scan
  write boundary unless a later request explicitly changes the hardware
  contract.
- Add or update tests in proportion to the touched behavior. Prefer fake HF2
  and offline GUI tests; never treat them as real-hardware validation.
- Record failed checks and environmental limitations honestly. Do not mark an
  item verified solely because it compiles.
- Update this specification in the same task as the code change, including the
  exact files and validation outcome.
