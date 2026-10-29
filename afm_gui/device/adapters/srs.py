from __future__ import annotations

import math
import threading
import time
from functools import wraps
from typing import Any

from afm_gui.core.mim import SR830_TIME_CONSTANTS


_SRS_IO_LOCK = threading.RLock()


def serialized_srs_io(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        # A query/response is indivisible, including across a shared GPIB bus.
        with _SRS_IO_LOCK:
            return method(self, *args, **kwargs)
    return wrapped


SRS_DRIVER_CLASSES = {
    "srs.sr830": "SR830",
    "srs.sr860": "SR860",
    "srs.sr865": "SR865",
    "srs.sr865a": "SR865A",
}


class SRSLockinAdapter:
    capabilities = ("lockin_demod", "lockin_output")
    lockin_channels = ("ch1",)

    def __init__(self, instrument: object, connection: dict[str, Any]) -> None:
        self.instrument = instrument
        self.connection = dict(connection)
        self.address = str(connection.get("address", ""))
        self.model = str(connection.get("model", type(instrument).__name__))
        self.mim_settings = {}

    @serialized_srs_io
    def read_demod(self, count: int = 1, delay_s: float = 0.01, demod_index: int = 0) -> dict[str, float | int | None]:
        samples = [self._read_once()]
        for _ in range(max(1, int(count)) - 1):
            if delay_s > 0:
                time.sleep(delay_s)
            samples.append(self._read_once())

        x = sum(sample["x_v"] for sample in samples) / len(samples)
        y = sum(sample["y_v"] for sample in samples) / len(samples)
        r_values = [sample["r_v"] for sample in samples if sample["r_v"] is not None]
        phase_values = [sample["phase_deg"] for sample in samples if sample["phase_deg"] is not None]
        frequency_values = [sample["frequency_hz"] for sample in samples if sample["frequency_hz"] is not None]
        return {
            "timestamp": None,
            "x_v": x,
            "y_v": y,
            "r_v": sum(r_values) / len(r_values) if r_values else math.hypot(x, y),
            "phase_deg": sum(phase_values) / len(phase_values) if phase_values else math.degrees(math.atan2(y, x)),
            "frequency_hz": sum(frequency_values) / len(frequency_values) if frequency_values else None,
            "auxin0_v": None,
            "auxin1_v": None,
        }

    @serialized_srs_io
    def set_output(
        self,
        amplitude: float | None = None,
        mixer_enable: bool | None = None,
        output_on: bool | None = None,
        output_index: int = 0,
        amplitude_index: int = 0,
    ) -> None:
        if amplitude is not None:
            self._set_first_available(("amplitude", "sine_outdc", "sine_outdc_voltage"), float(amplitude))

    @serialized_srs_io
    def configure_demod(
        self,
        *,
        demod_index: int = 0,
        input_index: int = 0,
        oscillator_index: int = 0,
        frequency_hz: float | None = None,
        phase_deg: float | None = None,
        time_constant_s: float | None = None,
        enable: bool = True,
    ) -> None:
        if frequency_hz is not None:
            self._set_first_available(("frequency",), float(frequency_hz))
        if phase_deg is not None:
            self._set_first_available(("phase", "phase_shift"), float(phase_deg))
        if time_constant_s is not None:
            self._set_first_available(("time_constant",), float(time_constant_s))

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
            "model": self.model,
            "address": self.address,
            "mim_settings": dict(self.mim_settings),
        }

    @serialized_srs_io
    def read_x(self) -> float:
        """One SR830 native digital X query, preserving its ASCII precision."""
        value = float(self.instrument.ask("OUTP? 1"))
        if not math.isfinite(value):
            raise ValueError(f"Invalid SR830 X response: {value}")
        return value

    @serialized_srs_io
    def read_mim_settings(self) -> dict:
        def integer(command, minimum, maximum):
            value = float(self.instrument.ask(command))
            if not math.isfinite(value) or not value.is_integer() or not minimum <= value <= maximum:
                raise ValueError(f"Invalid {command} response: {value}")
            return int(value)

        tau_index = integer("OFLT?", 0, 19)
        slope_index = integer("OFSL?", 0, 3)
        frequency = float(self.instrument.ask("FREQ?"))
        if not math.isfinite(frequency) or frequency <= 0:
            raise ValueError("Invalid SR830 reference frequency")
        self.mim_settings = {
            "time_constant_s": SR830_TIME_CONSTANTS[tau_index],
            "slope_db": 6 * (slope_index + 1),
            "input_mode": integer("ISRC?", 0, 3),
            "sync_filter": bool(integer("SYNC?", 0, 1)),
            "frequency_hz": frequency,
            "harmonic": integer("HARM?", 1, 19999),
            "sensitivity_index": integer("SENS?", 0, 26),
            "reserve_index": integer("RMOD?", 0, 2),
            "phase_deg": float(self.instrument.ask("PHAS?")),
            "x_offset_expand": str(self.instrument.ask("OEXP? 1")).strip(),
        }
        return dict(self.mim_settings)

    @serialized_srs_io
    def close(self) -> None:
        close = getattr(self.instrument, "close", None)
        if callable(close):
            close()

    def _read_once(self) -> dict[str, float | None]:
        x, y, r = self._read_xy_r()
        phase = self._read_first_available(("P", "T", "phase"))
        frequency = self._read_first_available(("frequency",))
        if r is None:
            r = math.hypot(x, y)
        if phase is None:
            phase = math.degrees(math.atan2(y, x))
        return {
            "x_v": x,
            "y_v": y,
            "r_v": r,
            "phase_deg": phase,
            "frequency_hz": frequency,
        }

    def _read_xy_r(self) -> tuple[float, float, float | None]:
        get_values = getattr(self.instrument, "get_values", None)
        if callable(get_values):
            try:
                x, y, r = get_values("X", "Y", "R")
                return float(x), float(y), float(r)
            except Exception:
                pass

        snap = getattr(self.instrument, "snap", None)
        if callable(snap):
            try:
                x, y = snap("X", "Y")
                return float(x), float(y), None
            except Exception:
                pass

        x = self._read_first_available(("X", "x"))
        y = self._read_first_available(("Y", "y"))
        r = self._read_first_available(("R", "r"))
        return float(x or 0.0), float(y or 0.0), r

    def _read_first_available(self, names: tuple[str, ...]) -> float | None:
        for name in names:
            param = getattr(self.instrument, name, None)
            if param is None:
                continue
            try:
                value = param() if callable(param) else param
                return float(value)
            except Exception:
                continue
        return None

    def _set_first_available(self, names: tuple[str, ...], value: float) -> bool:
        for name in names:
            param = getattr(self.instrument, name, None)
            if param is None or not callable(param):
                continue
            try:
                param(value)
                return True
            except Exception:
                continue
        return False


def create_srs_lockin(name: str, connection: dict[str, Any], driver: str) -> tuple[object, SRSLockinAdapter]:
    from qcodes.instrument_drivers import stanford_research

    class_name = SRS_DRIVER_CLASSES[driver]
    instrument_class = getattr(stanford_research, class_name)
    address = str(connection.get("address") or connection.get("visa_address") or connection.get("port") or "")
    if not address:
        raise ValueError(f"{class_name} connection requires a VISA address")

    kwargs = dict(connection.get("kwargs") or {})
    if driver == "srs.sr830":
        # QCoDeS timeout is in seconds; bound cancellation latency on a bad bus.
        kwargs.setdefault("timeout", 1.0)
    instrument = instrument_class(name, address, **kwargs)
    adapter = SRSLockinAdapter(instrument, {**connection, "address": address, "model": class_name})
    return instrument, adapter


__all__ = ["SRSLockinAdapter", "create_srs_lockin"]
