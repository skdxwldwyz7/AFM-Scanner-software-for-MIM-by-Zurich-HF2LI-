from __future__ import annotations

import math
import time
from typing import Any


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
        }

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
    instrument = instrument_class(name, address, **kwargs)
    adapter = SRSLockinAdapter(instrument, {**connection, "address": address, "model": class_name})
    return instrument, adapter


__all__ = ["SRSLockinAdapter", "create_srs_lockin"]
