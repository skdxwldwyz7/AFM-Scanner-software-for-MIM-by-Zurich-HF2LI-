# Windows Migration Notes

This archive is intended for continuing AFM GUI development on Windows.

## Recommended Setup

```powershell
conda create -n afm-gui python=3.12
conda activate afm-gui
python -m pip install uv
uv pip install -e .
```

## Run

```powershell
afm-gui
afm-cli modes
afm-cli scan --mode topo --direction up --pixels 32 --lines 16 --export-gsf .\scan_out --export-prefix smoke
```

## Test

```powershell
python -m unittest discover -s tests
```

For headless testing on machines without a display server, set:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests
```

## Notes

- The GUI and CLI set `MPLCONFIGDIR` at startup, so Matplotlib uses a writable
  cache directory even when the default user profile cache is unavailable.
- The bundled `afm_gui/config/layout1.json` is the startup layout.
- Hardware drivers are still represented by mock controllers; real hardware
  adapters should be added behind the device/function loading layer.
- Gwyddion-compatible output is written as one `.gsf` file per channel/pass plus
  a metadata JSON file.
