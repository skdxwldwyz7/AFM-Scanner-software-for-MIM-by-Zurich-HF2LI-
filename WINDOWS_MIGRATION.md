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
afm-cli scan --mode lockin --direction up --pixels 32 --lines 16 --export-gsf .\scan_out --export-prefix smoke
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
- Mock fallbacks remain available for offline development. Registered hardware
  adapters currently include MultiField scanner, Newton LT06, Attocube ANC350,
  Zurich HF2LI, and SRS SR830/SR860/SR865/SR865A lock-ins.
- Device addresses can be edited in the Device Manager before connecting.
- Gwyddion-compatible output is written as one `.gsf` file per channel/pass plus
  a metadata JSON file.
- Spectroscopy-map MVP data is written as `.afmspm.h5`, with selected-slice GSF
  export available from the Spectroscopy panel.
