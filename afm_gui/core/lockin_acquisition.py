from __future__ import annotations

import threading


class LockinScanAcquisition:
    """Maps scan signal slots to lock-in device/channel/signal readings."""

    SIGNAL_KEYS = {
        "x": "x_v",
        "y": "y_v",
        "r": "r_v",
        "theta": "phase_deg",
        "frequency": "frequency_hz",
    }

    def __init__(self, adapters: dict[str, object], routing: dict[str, dict[str, str]]) -> None:
        self._adapters = dict(adapters)
        self._routing = dict(routing)
        self._locks = {id(adapter): threading.Lock() for adapter in self._adapters.values()}

    def __call__(self, channels: tuple[str, ...]) -> dict[str, float]:
        samples: dict[tuple[int, str], dict[str, object]] = {}
        mapped = {channel: 0.0 for channel in channels}
        for channel in channels:
            adapter = self._adapters.get(channel)
            route = self._routing.get(channel, {})
            if adapter is None or not hasattr(adapter, "read_demod"):
                continue
            adapter_id = id(adapter)
            lockin_channel = str(route.get("lockin_channel", "ch1") or "ch1")
            sample_id = (adapter_id, lockin_channel)
            if sample_id not in samples:
                lock = self._locks.setdefault(adapter_id, threading.Lock())
                with lock:
                    samples[sample_id] = self._read_demod(adapter, lockin_channel)
            signal = str(route.get("signal", "")).lower()
            sample_key = self.SIGNAL_KEYS.get(signal)
            if sample_key:
                value = samples[sample_id].get(sample_key)
                if value is not None:
                    mapped[channel] = value
        return {
            channel: float(value)
            for channel, value in mapped.items()
            if channel in channels and value is not None
        }

    @staticmethod
    def _demod_index(channel: str, adapter: object) -> int:
        index_for_channel = getattr(adapter, "demod_index_for_channel", None)
        if callable(index_for_channel):
            return int(index_for_channel(channel))
        return {"ch1": 0, "ch2": 1}.get(channel, 0)

    @classmethod
    def _read_demod(cls, adapter: object, channel: str) -> dict[str, object]:
        try:
            return adapter.read_demod(demod_index=cls._demod_index(channel, adapter))
        except TypeError:
            try:
                return adapter.read_demod()
            except Exception:
                return {}
        except Exception:
            return {}


class ZeroScanAcquisition:
    def __call__(self, channels: tuple[str, ...]) -> dict[str, float]:
        return {channel: 0.0 for channel in channels}


__all__ = ["LockinScanAcquisition", "ZeroScanAcquisition"]
