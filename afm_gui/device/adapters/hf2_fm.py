"""HF2 FM-AFM support. The only hardware writes here are AUX1/2 offsets.

LabOne owns all PLL/PID/demodulator configuration and AUX3/4. Connecting,
reading, stopping, and closing this adapter never reset any output.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import wraps

from afm_gui.core.fm_afm import FM_CHANNEL_BY_KEY


def serialized_io(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.io_lock:
            return method(self, *args, **kwargs)
    return wrapped


class HF2FMInterface:
    def _init_fm(self) -> None:
        self.io_lock = threading.RLock()
        self.fm_settings = dict(self.connection.get("fm_afm") or {})
        self.fm_readonly = bool(self.fm_settings.get("enabled", False))
        self.fm_errors: dict[str, str] = {}
        self.xy_min_v = float(self.fm_settings.get("xy_min_v", 0.0))
        self.xy_max_v = float(self.fm_settings.get("xy_max_v", 5.0))
        self.xy_step_v = float(self.fm_settings.get("max_step_v", 0.01))
        self._fm_scan_active = False
        if not (-10 <= self.xy_min_v < self.xy_max_v <= 10):
            raise ValueError("XY software limits must lie within -10...10 V")
        if not math.isfinite(self.xy_step_v) or self.xy_step_v <= 0:
            raise ValueError("max_step_v must be positive and finite")

    def _path(self, suffix: str) -> str:
        return f"/{self.device_id.lower()}/{suffix}"

    def _get(self, suffix: str, *, integer: bool = False) -> float:
        reader = self.session.daq_server.getInt if integer else self.session.daq_server.getDouble
        return float(reader(self._path(suffix)))

    def read_fm_report_snapshot(self) -> dict[str, object]:
        """Read AUX and feedback settings once, after acquisition, for the report."""
        with self.io_lock:
            values = self.read_fm_snapshot()
            nodes = {f"auxouts/{index}/value": values[f"auxout{index + 1}"] for index in range(4)}
            read_errors = dict(self.fm_errors)
            daq = self.session.daq_server
            getter = getattr(daq, "get", None)

            for suffix in ("plls/0/*", "pids/0/*"):
                path = self._path(suffix)
                try:
                    if not callable(getter):
                        raise RuntimeError("LabOne DAQ batch get is unavailable")
                    try:
                        response = getter(path, flat=True)
                    except TypeError:
                        response = getter(path)
                    flattened = _flatten_batch_response(response)
                    prefix = self._path("").lower().rstrip("/") + "/"
                    group = suffix.removesuffix("/*").lower() + "/"
                    found = 0
                    for node_path, raw_value in flattened.items():
                        normalized = node_path.lower()
                        if normalized.startswith(prefix):
                            normalized = normalized[len(prefix):]
                        if not normalized.startswith(group):
                            continue
                        value = _batch_scalar(raw_value)
                        if value is not None:
                            nodes[normalized] = value
                            found += 1
                    if not found:
                        read_errors[suffix] = "LabOne returned no scalar nodes for this group"
                except Exception as exc:
                    read_errors[suffix] = str(exc)

            connection = self.connection
            return {
                "captured_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "device_id": str(self.device_id),
                "host": connection.get("host", ""),
                "port": connection.get("port", ""),
                "interface": connection.get("interface", ""),
                "fm_settings": dict(self.fm_settings),
                "software_limits": {
                    "xy_min_v": self.xy_min_v,
                    "xy_max_v": self.xy_max_v,
                    "max_step_v": self.xy_step_v,
                },
                "nodes": nodes,
                "read_errors": read_errors,
            }

    def read_fm_snapshot(self, channels=None) -> dict[str, float]:
        requested = set(FM_CHANNEL_BY_KEY if channels is None else channels)
        unknown = requested - set(FM_CHANNEL_BY_KEY)
        if unknown:
            raise ValueError("Unsupported FM channel(s): " + ", ".join(sorted(unknown)))
        with self.io_lock:
            values, errors = self._read_aux_outputs()
            self.fm_errors = errors
        return {key: values.get(key, math.nan) for key in requested}

    def _read_aux_outputs(self) -> tuple[dict[str, float], dict[str, str]]:
        values: dict[str, float] = {}
        errors: dict[str, str] = {}
        daq = self.session.daq_server
        getter = getattr(daq, "get", None)
        if callable(getter):
            path = self._path("auxouts/*/value")
            try:
                try:
                    response = getter(path, flat=True)
                except TypeError:
                    response = getter(path)
                flattened = _flatten_batch_response(response)
                prefix = self._path("").lower().rstrip("/") + "/"
                for node_path, raw_value in flattened.items():
                    normalized = node_path.lower()
                    if normalized.startswith(prefix):
                        normalized = normalized[len(prefix):]
                    for index in range(4):
                        if normalized != f"auxouts/{index}/value":
                            continue
                        value = _batch_scalar(raw_value)
                        if value is not None:
                            values[f"auxout{index + 1}"] = float(value)
            except Exception as exc:
                errors["auxouts/*/value"] = str(exc)

        for index in range(4):
            key = f"auxout{index + 1}"
            if key in values:
                continue
            try:
                values[key] = self._get(f"auxouts/{index}/value")
            except Exception as exc:
                errors[key] = str(exc)
        return values, errors

    def validate_xy(self, x: float, y: float) -> None:
        for axis, value in (("X", x), ("Y", y)):
            if not math.isfinite(value) or not self.xy_min_v <= value <= self.xy_max_v:
                raise ValueError(f"{axis}={value:g} V outside AUX software limits {self.xy_min_v:g}...{self.xy_max_v:g} V")

    def validate_xy_control(self) -> None:
        if not self.fm_readonly:
            raise RuntimeError("Enable the FM-AFM connection profile before AUX XY control")

    def read_xy(self) -> tuple[float, float]:
        with self.io_lock:
            return self._get("auxouts/0/value"), self._get("auxouts/1/value")

    def set_xy_voltage(self, x: float, y: float) -> None:
        self.validate_xy(x, y)
        with self.io_lock:
            daq = self.session.daq_server
            updates = [
                [self._path("auxouts/0/offset"), float(x)],
                [self._path("auxouts/1/offset"), float(y)],
            ]
            batch_set = getattr(daq, "set", None)
            if callable(batch_set):
                batch_set(updates)
            else:
                for path, value in updates:
                    daq.setDouble(path, value)

    def set_axis_voltage(self, axis: str, value_v: float) -> None:
        if axis not in {"x", "y"}:
            raise ValueError("FM-AFM software can write only X/AUX1 and Y/AUX2")
        x, y = self.read_xy()
        self.set_xy_voltage(value_v if axis == "x" else x, value_v if axis == "y" else y)

    def validate_fm_geometry(self, config, lines) -> None:
        if config.xy_unit != "V":
            raise ValueError("FM-AFM XY coordinates must be HF2 AUX volts")
        if not math.isfinite(config.linear) or config.linear <= 0:
            raise ValueError("XY speed must be positive and finite")
        for name in ("t_sample", "t_settle", "t_rest"):
            value = getattr(config, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be nonnegative and finite")
        if config.pixels < 1 or config.lines < 1 or not lines:
            raise ValueError("FM-AFM scan must contain pixels and lines")
        for start, end in lines:
            for point in (start, end):
                self.validate_xy(float(point[0]), float(point[1]))

    def validate_fm_scan(self, config, lines) -> None:
        self.validate_fm_geometry(config, lines)

    def begin_fm_scan(self, config, lines) -> None:
        self.validate_fm_scan(config, lines)
        with self.io_lock:
            self._fm_scan_active = True

    def end_fm_scan(self) -> None:
        with self.io_lock:
            self._fm_scan_active = False

    def stop(self) -> None:
        """Stop means stop software motion; hold all four outputs unchanged."""


def _flatten_batch_response(response: object) -> dict[str, object]:
    nodes: dict[str, object] = {}

    def visit(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            by_lower = {str(key).lower(): key for key in value}
            if "value" in by_lower:
                nodes[path] = value[by_lower["value"]]
                return
            for key, child in value.items():
                part = str(key)
                next_path = part if part.startswith("/") else f"{path.rstrip('/')}/{part}"
                visit(child, next_path)
            return
        if path:
            nodes[path] = value

    visit(response, "")
    return nodes


def _batch_scalar(value: object) -> object | None:
    while True:
        if isinstance(value, Mapping):
            by_lower = {str(key).lower(): key for key in value}
            if "value" in by_lower:
                value = value[by_lower["value"]]
            elif len(value) == 1:
                value = next(iter(value.values()))
            else:
                return None
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                return None
            value = value[-1]
            continue
        size = getattr(value, "size", None)
        item = getattr(value, "item", None)
        if size is not None and callable(item):
            if size == 0:
                return None
            if size == 1:
                value = item()
                continue
            try:
                value = value[-1].item()
                continue
            except (AttributeError, IndexError, TypeError):
                return None
        return value
