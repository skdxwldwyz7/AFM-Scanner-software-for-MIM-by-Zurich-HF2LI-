# Hardware Integration Notes

This document records the hardware-integration lessons learned while adding
MultiField, Newton LT06, Attocube, Zurich HF2LI, and SRS lock-in support.

Core rule:

```text
driver first, then adapter, then registry, then devices.yaml, then GUI wiring.
```

## Current Hardware Layer

The hardware layer has four parts:

- Vendor driver: existing vendor or lab control files under
  `afm_gui/device/vendor/`.
- Adapter: a small wrapper under `afm_gui/device/adapters/` that exposes a
  consistent capability interface to the GUI.
- Registry: `afm_gui/device/registry.py` maps a `devices.yaml` driver string
  to a concrete adapter.
- Device Manager: the GUI panel that reads `devices.yaml`, lets the user edit
  connection settings, and connects/disconnects devices.

Current devices:

| Device name | Driver | Kind | Capabilities | Notes |
| --- | --- | --- | --- | --- |
| `scanner_mock` | `mock.scanner` | `scanner` | `scanner_voltage` | Software scanner simulator |
| `multifield_scanner` | `multifield.scanner` | `scanner` | `scanner_voltage` | MultiField scanner, default `COM3` |
| `newton_lt06` | `multifield.newton_lt06` | `stage` | `xyz_stage` | Newton LT06 stage, default `COM5` |
| `attocube_xyz` | `attocube.anc350` | `stage` | `xyz_stage` | Attocube XYZ stage, default `192.168.0.9:9090` |
| `zurich_HF2LI` | `zurich.hf2li` | `lockin` | `lockin_demod`, `lockin_output` | Zurich HF2LI lock-in |
| `srs_sr830` | `srs.sr830` | `lockin` | `lockin_demod`, `lockin_output` | QCoDeS SR830 lock-in |
| `srs_sr860` | `srs.sr860` | `lockin` | `lockin_demod`, `lockin_output` | QCoDeS SR860 lock-in |
| `srs_sr865` | `srs.sr865` | `lockin` | `lockin_demod`, `lockin_output` | QCoDeS SR865 lock-in |
| `srs_sr865a` | `srs.sr865a` | `lockin` | `lockin_demod`, `lockin_output` | QCoDeS SR865A lock-in |

Current function assignments:

| Function | Required kind | Required capability | Assigned device |
| --- | --- | --- | --- |
| `scan_scanner` | `scanner` | `scanner_voltage` | `multifield_scanner` |
| `coarse_stage` | `stage` | `xyz_stage` | `attocube_xyz` |
| `lockin` | `lockin` | `lockin_demod` | `zurich_HF2LI` |

## Add A New Hardware Device

### 1. Validate the hardware outside the GUI

Start with a standalone script or notebook and test the smallest safe loop:

- Import the vendor driver.
- Open the connection, such as serial, TCP, or LabOne server.
- Read one status value.
- Execute one small safe action.
- Close the connection.

Do not start with GUI integration. A standalone validation keeps failures
limited to ports, dependencies, vendor drivers, and the hardware itself.

Known MultiField/Newton validation ports:

```python
SCANNER_PORT = "COM3"
NEWTON_PORT = "COM5"
```

Known Zurich HF2LI connection values:

```yaml
host: 127.0.0.1
port: 8005
device: DEV18388
interface: USB
```

Known SRS QCoDeS lock-in connection values use VISA addresses. Edit the
`address` field in Device Manager before connecting:

```yaml
driver: srs.sr830   # or srs.sr860, srs.sr865, srs.sr865a
connection:
  backend: visa
  address: GPIB0::8::INSTR
```

### 2. Copy vendor files into the package

Copy the required hardware-control files into:

```text
afm_gui/device/vendor/<vendor_or_device_name>/
```

Current package-local vendor layout:

```text
afm_gui/device/vendor/multifield/
  MultiFieldScanner.py
  NewtonLT06.py

afm_gui/device/vendor/zurich/scripts/
  hf2li_tools.py
  ...

afm_gui/device/vendor/attocube/python/
  AMC.py
  ...
```

Reasons:

- The GUI does not depend on temporary local paths.
- Packaged installs can still find the driver files.
- Device Manager connections do not fail just because the working directory
  changed.

When adding vendor files, check that `pyproject.toml` package data includes
them.

### 3. Add or update an adapter

Create or extend an adapter under:

```text
afm_gui/device/adapters/
```

Adapter responsibilities:

- Prefer package-local vendor paths.
- Read `DeviceConfig.connection`.
- Connect to real hardware.
- Expose a consistent capability object, such as scanner, stage, or lock-in.
- Hide vendor API naming differences from the GUI layer.

Current adapter files:

```text
afm_gui/device/adapters/base.py
afm_gui/device/adapters/mock.py
afm_gui/device/adapters/multifield.py
afm_gui/device/adapters/zurich.py
afm_gui/device/adapters/attocube.py
afm_gui/device/adapters/srs.py
```

Adapters should not depend on GUI widgets. They should only handle hardware
connection and hardware actions.

### 4. Register the driver

Register the `devices.yaml` driver string in:

```text
afm_gui/device/registry.py
```

Rules of thumb:

- Keep `driver` names stable, for example `zurich.hf2li`.
- Device instance names can be more specific, for example `zurich_HF2LI`.
- If one vendor has multiple models, include the model or protocol in the
  driver string.

### 5. Add the device to devices.yaml

Edit:

```text
afm_gui/config/devices.yaml
```

Minimum shape:

```yaml
- name: example_device
  label: Example Device
  kind: scanner
  driver: vendor.model
  enabled: false
  capabilities:
    - scanner_voltage
  connection:
    backend: serial
    port: COM3
    baudrate: 115200
```

Field meanings:

- `name`: internal device name used by the GUI and function assignments.
- `label`: display name in Device Manager.
- `kind`: broad device type, such as `scanner`, `stage`, or `lockin`.
- `driver`: adapter key registered in `registry.py`.
- `enabled`: whether the device is enabled by default.
- `capabilities`: actions this device can provide.
- `connection`: address and protocol settings. Device Manager can edit this.

### 6. Assign the device to a function

Function assignments live in the same `devices.yaml` file:

```yaml
functions:
  - name: scan_scanner
    label: Scan Scanner
    required_kind: scanner
    required_capability: scanner_voltage
    device: multifield_scanner
```

Rules of thumb:

- GUI modules should look up devices by function, not hard-code device names.
- `required_kind` filters the broad device type.
- `required_capability` confirms the needed feature.
- Swapping hardware should usually require only a function-assignment change.

### 7. Test imports before connecting

Run an import check inside the `afm-gui` environment:

```powershell
conda run -n afm-gui python -c "from afm_gui.device.adapters import multifield, zurich, attocube; import MultiFieldScanner, NewtonLT06, hf2li_tools, AMC; print('ok')"
```

Errors seen before:

```text
No module named 'MultiFieldScanner'
No module named 'NewtonLT06'
No module named 'hf2li_tools'
No module named 'AMC'
```

Fixes:

- Copy vendor driver files into `afm_gui/device/vendor/`.
- Make adapters prefer package-local vendor paths.
- Install third-party packages into `afm-gui`; Zurich needs the `zhinst-*`
  packages.

### 8. Test connection in Device Manager

Start the GUI:

```powershell
conda run -n afm-gui python -m afm_gui.main
```

In Device Manager:

1. Select the device.
2. Edit the `Connection` JSON, such as serial port, host, or device id.
3. Click `Apply Connection`.
4. Click `Connect`.
5. Read the status or error message.

Runtime edits in Device Manager are useful for testing. After a setting is
confirmed, copy it back into `devices.yaml` if it should be the default.

### 9. Wire GUI modules after connection works

After Device Manager can connect and return an adapter, wire feature panels by
function:

- Scan module uses `scan_scanner`.
- Stage module uses `coarse_stage`.
- Lock-in module uses `lockin` for the channel setup/readout panel.
- Approach module can use `coarse_stage.z` for Z approach motion and any
  connected lock-in device as its stop-condition signal source.
- Scan Routing can map A-D image slots (`signal_a` through `signal_d`) to any
  configured lock-in device/channel/signal. Signals include `x`, `y`, `r`,
  `theta`, and `frequency`. Zurich HF2LI exposes `ch1` and `ch2`; SRS lock-ins
  expose `ch1`.

The GUI should call the unified adapter interface, not import vendor drivers
directly.

Approach hardware behavior is intentionally strict:

- `mock.z` and mock signal remain available for offline validation.
- `coarse_stage.z` requires the assigned `coarse_stage` function to be
  connected in Device Manager.
- A real approach signal requires the selected lock-in device to be connected
  and to provide `read_demod`.
- Missing real hardware causes the approach to enter `Failed`; it does not
  silently fall back to mock data.
- Device Manager is locked while approach is running or paused, matching the
  scan lockout behavior.

### 10. Add tests

Add at least two types of tests:

- Registry/loader tests: confirm the driver key is registered and can be
  instantiated.
- Adapter mock tests: confirm the GUI-facing capability interface behaves as
  expected.

Real-hardware tests should remain manual notebooks or explicit hardware
validation scripts. They should not run as normal unit tests.

## Troubleshooting

### Import error

Symptom:

```text
No module named '<driver_module>'
```

Check:

- Vendor files are copied into `afm_gui/device/vendor/`.
- The adapter adds the correct vendor path.
- `pyproject.toml` package data includes the files.
- The command is running in the `afm-gui` environment.

### Serial port error

Check:

- COM number in Windows Device Manager.
- Whether a notebook, vendor app, or another GUI instance is using the port.
- Baudrate matches the standalone validation.

### Zurich connection error

Check:

- LabOne server is running.
- Host and port are `127.0.0.1:8005`.
- Device id matches the instrument, for example `DEV18388`.
- Interface matches LabOne, for example `USB`.
- `zhinst-qcodes`, `zhinst-core`, and `zhinst-toolkit` are installed in
  `afm-gui`.
- For SRS instruments, confirm the VISA backend and address in Device Manager.
  The default entries are placeholders and should be edited before connecting.

Current status note:

- MultiField scanner control from the GUI through `scan_scanner` has been
  observed working.
- Zurich HF2LI and SRS adapters are registered and wired into the GUI. Treat
  each physical lock-in setup as hardware-validation-required until Device
  Manager connects cleanly and `Read` returns the expected X/Y/R/Theta values.

### GUI connects but controls do nothing

This usually means Device Manager has connected an adapter, but the specific
GUI module has not yet been wired to the function adapter.

Check:

- The GUI module uses `DeviceManager.adapter_for_function(...)`.
- The function assignment points to the correct device.
- The device provides the required capability.

For Approach, also check:

- `coarse_stage` is assigned to the intended Z actuator.
- The adapter exposes either `move_relative(dz=...)` or
  `read_position()` plus `move_absolute(z=...)`.
- The selected lock-in route can be read manually from the Lock-in Amplifier
  panel before using it as an approach condition.

## Checklist

Use this order for new hardware:

- [ ] Validate the smallest hardware loop in a standalone script/notebook.
- [ ] Copy vendor driver files into `afm_gui/device/vendor/`.
- [ ] Update `pyproject.toml` package data if needed.
- [ ] Add or update the adapter under `afm_gui/device/adapters/`.
- [ ] Register the driver in `afm_gui/device/registry.py`.
- [ ] Add the device to `afm_gui/config/devices.yaml`.
- [ ] Assign the device to a function in `devices.yaml`.
- [ ] Run the import check.
- [ ] Run unit tests.
- [ ] Edit the address and connect in Device Manager.
- [ ] Wire GUI modules to the adapter only after connection works.
