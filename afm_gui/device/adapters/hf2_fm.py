"""HF2 FM-AFM support. The only hardware writes here are AUX1/2 offsets.

LabOne owns all PLL/PID/demodulator configuration and AUX3/4. Connecting,
reading, stopping, and closing this adapter never reset any output.
"""
from __future__ import annotations

import math
import threading
import time
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
    SCAN_ROUTE_RECHECK_S = 0.25

    def _init_fm(self) -> None:
        self.io_lock = threading.RLock()
        self.fm_settings = dict(self.connection.get("fm_afm") or {})
        self.fm_readonly = bool(self.fm_settings.get("enabled", False))
        self.fm_errors: dict[str, str] = {}
        self.pll_index = int(self.fm_settings.get("pll_index", 0))
        self.pid_index = int(self.fm_settings.get("pid_index", 0))
        self.xy_min_v = float(self.fm_settings.get("xy_min_v", 0.0))
        self.xy_max_v = float(self.fm_settings.get("xy_max_v", 5.0))
        self.xy_step_v = float(self.fm_settings.get("max_step_v", 0.01))
        self._fm_scan_active = False
        self._last_scan_route_check = 0.0
        self._pll_oscillator_index: int | None = None
        self._unsupported_batch_read_groups: set[str] = set()
        self._fm_scan_static_nodes = {
            f"plls/{self.pll_index}/{name}"
            for name in ("freqcenter", "freqrange", "setpoint", "demodselect", "oscselect")
        }
        self._fm_scan_static_nodes.update(
            f"pids/{self.pid_index}/{name}"
            for name in ("setpoint", "center", "range", "input", "inputchannel", "output", "outputchannel")
        )
        for index in range(4):
            self._fm_scan_static_nodes.update(
                f"auxouts/{index}/{name}" for name in ("scale", "offset", "outputselect")
            )
        self._fm_scan_static_cache: dict[str, float] = {}
        if not (-10 <= self.xy_min_v < self.xy_max_v <= 10):
            raise ValueError("XY software limits must lie within -10...10 V")
        if not math.isfinite(self.xy_step_v) or self.xy_step_v <= 0:
            raise ValueError("max_step_v must be positive and finite")

    def _path(self, suffix: str) -> str:
        return f"/{self.device_id.lower()}/{suffix}"

    def _get(self, suffix: str, *, integer: bool = False) -> float:
        reader = self.session.daq_server.getInt if integer else self.session.daq_server.getDouble
        return float(reader(self._path(suffix)))

    def _get_scan_node(self, suffix: str, *, integer: bool = False) -> float:
        if self._fm_scan_active and suffix in self._fm_scan_static_nodes:
            if suffix not in self._fm_scan_static_cache:
                self._fm_scan_static_cache[suffix] = self._get(suffix, integer=integer)
            return self._fm_scan_static_cache[suffix]
        return self._get(suffix, integer=integer)

    def _fm_nodes(self) -> dict[str, tuple[str, bool]]:
        pll, pid = f"plls/{self.pll_index}", f"pids/{self.pid_index}"
        result = {
            "pll_df": (f"{pll}/freqdelta", False),
            "pll_error": (f"{pll}/error", False),
            "pll_locked": (f"{pll}/locked", True),
            "pll_enabled": (f"{pll}/enable", True),
            "pll_center": (f"{pll}/freqcenter", False),
            "pll_range": (f"{pll}/freqrange", False),
            "pll_setpoint": (f"{pll}/setpoint", False),
            "pll_demodselect": (f"{pll}/demodselect", True),
            "pll_oscselect": (f"{pll}/oscselect", True),
            "auxin1": ("auxins/0/values/0", False),
            "auxin2": ("auxins/0/values/1", False),
            "pid_error": (f"{pid}/error", False),
            "pid_shift": (f"{pid}/shift", False),
            "pid_enabled": (f"{pid}/enable", True),
            "pid_setpoint": (f"{pid}/setpoint", False),
            "pid_center": (f"{pid}/center", False),
            "pid_range": (f"{pid}/range", False),
            "pid_input": (f"{pid}/input", True),
            "pid_inputchannel": (f"{pid}/inputchannel", True),
            "pid_output": (f"{pid}/output", True),
            "pid_outputchannel": (f"{pid}/outputchannel", True),
        }
        for index in range(4):
            output = f"auxouts/{index}"
            result.update(
                {
                    f"auxout{index + 1}": (f"{output}/value", False),
                    f"auxout{index + 1}_scale": (f"{output}/scale", False),
                    f"auxout{index + 1}_offset": (f"{output}/offset", False),
                    f"auxout{index + 1}_outputselect": (f"{output}/outputselect", True),
                }
            )
        result["aux4_scale"] = result["auxout4_scale"]
        result["aux4_offset"] = result["auxout4_offset"]
        return result

    def read_fm_report_snapshot(self) -> dict[str, object]:
        """Read a detailed, read-only snapshot for a completed FM-AFM scan."""
        groups = (f"plls/{self.pll_index}", f"pids/{self.pid_index}", "auxouts", "auxins/0")
        nodes: dict[str, float] = {}
        errors: dict[str, str] = {}
        daq = self.session.daq_server
        getter = getattr(daq, "get", None)
        with self.io_lock:
            if callable(getter):
                for group in groups:
                    wildcard = self._path(f"{group}/*")
                    try:
                        try:
                            response = getter(wildcard, flat=True)
                        except TypeError:
                            response = getter(wildcard)
                        prefix = self._path("").lower().rstrip("/") + "/"
                        for node_path, raw_value in _flatten_batch_response(response).items():
                            normalized = node_path.lower()
                            if normalized.startswith(prefix):
                                normalized = normalized[len(prefix):]
                            value = _batch_scalar(raw_value)
                            if value is None:
                                continue
                            try:
                                nodes[normalized] = float(value)
                            except (TypeError, ValueError, OverflowError):
                                continue
                    except Exception as exc:
                        errors[wildcard] = str(exc)

            for suffix, integer in sorted(set(self._fm_nodes().values())):
                if suffix in nodes:
                    continue
                try:
                    nodes[suffix] = self._get(suffix, integer=integer)
                except Exception as exc:
                    errors[self._path(suffix)] = str(exc)

            oscillator_node = f"plls/{self.pll_index}/oscselect"
            oscillator = nodes.get(oscillator_node)
            if oscillator is not None and math.isfinite(oscillator):
                frequency_node = f"oscs/{int(oscillator)}/freq"
                try:
                    nodes[frequency_node] = self._get(frequency_node)
                except Exception as exc:
                    errors[self._path(frequency_node)] = str(exc)

        connection = self.connection
        return {
            "captured_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "device_id": str(self.device_id),
            "host": connection.get("host", ""),
            "port": connection.get("port", ""),
            "interface": connection.get("interface", ""),
            "pll_index": self.pll_index,
            "pid_index": self.pid_index,
            "fm_settings": dict(self.fm_settings),
            "software_limits": {
                "xy_min_v": self.xy_min_v,
                "xy_max_v": self.xy_max_v,
                "max_step_v": self.xy_step_v,
                "z_min_v": float(self.fm_settings.get("z_min_v", 0.0)),
                "z_max_v": float(self.fm_settings.get("z_max_v", 5.0)),
            },
            "nodes": nodes,
            "read_errors": errors,
        }

    def read_fm_snapshot(self, channels=None) -> dict[str, float]:
        requested = set(FM_CHANNEL_BY_KEY if channels is None else channels)
        wanted = set(requested)
        if "pid_out" in wanted:
            wanted.update(("pid_center", "pid_shift"))
        if "pid_at_limit" in wanted:
            wanted.update(("pid_shift", "pid_range"))
        if "loopback_error" in wanted:
            wanted.update(("auxin1", "auxout4"))
        values = {key: math.nan for key in wanted}
        errors = {}
        with self.io_lock:
            node_values, node_errors = self._read_fm_nodes(wanted)
            values.update(node_values)
            errors.update(node_errors)
            if wanted & {"x", "y", "r", "theta", "frequency"}:
                try:
                    # Follow the demodulator actually selected by PLL in LabOne.
                    index = int(self._get_scan_node(f"plls/{self.pll_index}/demodselect", integer=True))
                    sample = self.read_demod(demod_index=index)
                    for key, source in {"x": "x_v", "y": "y_v", "r": "r_v", "theta": "phase_deg"}.items():
                        if key in wanted:
                            values[key] = float(sample[source])
                except Exception as exc:
                    for key in wanted & {"x", "y", "r", "theta"}:
                        errors[key] = str(exc)
                if "frequency" in wanted:
                    try:
                        oscillator = self._pll_oscillator_index if self._fm_scan_active else None
                        if oscillator is None:
                            oscillator = int(self._get(f"plls/{self.pll_index}/oscselect", integer=True))
                        values["frequency"] = self._get(f"oscs/{oscillator}/freq")
                    except Exception as exc:
                        errors["frequency"] = str(exc)
            if "pid_out" in wanted:
                values["pid_out"] = values["pid_center"] + values["pid_shift"]
            if "pid_at_limit" in wanted:
                shift, limit = values["pid_shift"], values["pid_range"]
                if math.isfinite(shift) and math.isfinite(limit) and limit > 0:
                    values["pid_at_limit"] = float(abs(shift) >= limit * 0.99)
            if "loopback_error" in wanted:
                values["loopback_error"] = values["auxin1"] - values["auxout4"]
            self.fm_errors = errors
        return {key: values.get(key, math.nan) for key in requested}

    def _read_fm_nodes(self, wanted: set[str]) -> tuple[dict[str, float], dict[str, str]]:
        definitions = self._fm_nodes()
        grouped: dict[str, list[tuple[str, str, bool]]] = {}
        for key in wanted:
            if key not in definitions:
                continue
            node, integer = definitions[key]
            parts = node.split("/")
            group = "auxouts" if parts[0] == "auxouts" else "/".join(parts[:2])
            grouped.setdefault(group, []).append((key, node, integer))

        values: dict[str, float] = {}
        errors: dict[str, str] = {}
        if self._fm_scan_active:
            for key, node, integer in (entry for entries in grouped.values() for entry in entries):
                try:
                    values[key] = self._get_scan_node(node, integer=integer)
                except Exception as exc:
                    errors[key] = str(exc)
            return values, errors

        for group, entries in grouped.items():
            batch_values = self._read_batch_group(group) if group not in self._unsupported_batch_read_groups else None
            if batch_values is not None and not any(node in batch_values for _key, node, _integer in entries):
                self._unsupported_batch_read_groups.add(group)
                batch_values = None
            for key, node, integer in entries:
                if batch_values is not None and node in batch_values:
                    values[key] = batch_values[node]
                    continue
                try:
                    values[key] = self._get(node, integer=integer)
                except Exception as exc:
                    errors[key] = str(exc)
        return values, errors

    def _read_batch_group(self, group: str) -> dict[str, float] | None:
        if group in self._unsupported_batch_read_groups:
            return None
        daq = self.session.daq_server
        getter = getattr(daq, "get", None)
        if not callable(getter):
            self._unsupported_batch_read_groups.add(group)
            return None
        path = self._path(f"{group}/*")
        try:
            try:
                response = getter(path, flat=True)
            except TypeError:
                response = getter(path)
        except Exception:
            self._unsupported_batch_read_groups.add(group)
            return None

        flattened = _flatten_batch_response(response)
        prefix = self._path("").lower().rstrip("/") + "/"
        result: dict[str, float] = {}
        for node_path, raw_value in flattened.items():
            normalized = node_path.lower()
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
            value = _batch_scalar(raw_value)
            if value is None:
                continue
            try:
                result[normalized] = float(value)
            except (TypeError, ValueError, OverflowError):
                continue

        if result:
            return result
        self._unsupported_batch_read_groups.add(group)
        return None

    def validate_xy(self, x: float, y: float) -> None:
        for axis, value in (("X", x), ("Y", y)):
            if not math.isfinite(value) or not self.xy_min_v <= value <= self.xy_max_v:
                raise ValueError(f"{axis}={value:g} V outside AUX software limits {self.xy_min_v:g}...{self.xy_max_v:g} V")

    def validate_xy_control(self) -> None:
        if not self.fm_readonly:
            raise RuntimeError("Enable the FM-AFM connection profile before AUX XY control")
        with self.io_lock:
            for index in (0, 1):
                if self._get(f"auxouts/{index}/outputselect", integer=True) != -1:
                    raise RuntimeError(f"Set AUX{index + 1} Signal to Manual in LabOne before moving XY")
            # Verify no active PID owns either XY offset. No settings are changed.
            # ziListEnum: recursive | absolute | leavesonly. Absolute paths are
            # needed for subsequent getInt calls (flag 0 returns relative names).
            paths = self.session.daq_server.listNodes(self._path("pids/*/enable"), 7)
            if not paths:
                raise RuntimeError("Cannot verify PID ownership of AUX1/2")
            for path in paths:
                base = str(path).lower().rsplit("/", 1)[0]
                daq = self.session.daq_server
                if daq.getInt(base + "/enable") and daq.getInt(base + "/output") == 3:
                    if daq.getInt(base + "/outputchannel") in (0, 1):
                        raise RuntimeError("An active PID owns AUX1/2; XY motion is blocked")

    def read_xy(self) -> tuple[float, float]:
        with self.io_lock:
            return self._get("auxouts/0/value"), self._get("auxouts/1/value")

    def set_xy_voltage(self, x: float, y: float) -> None:
        self.validate_xy(x, y)
        with self.io_lock:
            now = time.monotonic()
            if not self._fm_scan_active or now - self._last_scan_route_check >= self.SCAN_ROUTE_RECHECK_S:
                self.validate_xy_control()
                if self._fm_scan_active:
                    self._last_scan_route_check = now
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
        self.validate_xy_control()
        with self.io_lock:
            pid = f"pids/{self.pid_index}"
            expected = {"input": 4, "inputchannel": 0, "output": 3, "outputchannel": 2}
            for suffix, value in expected.items():
                if self._get(f"{pid}/{suffix}", integer=True) != value:
                    raise RuntimeError("LabOne PID must route Aux In 1 to Aux Out 3 offset")
            if self.pll_index != 0 or self._get("auxouts/3/outputselect", integer=True) != 4:
                raise RuntimeError("This FM wiring requires AUX4 source PLL 1 frequency shift")
            self._pll_oscillator_index = int(self._get(f"plls/{self.pll_index}/oscselect", integer=True))
            if self._get("auxouts/2/outputselect", integer=True) != -1 or self._get("auxouts/2/scale") != 0:
                raise RuntimeError("LabOne AUX3 must use Manual, Scale=0 for the configured Z loop")
            center, limit = self._get(f"{pid}/center"), self._get(f"{pid}/range")
            if not math.isfinite(limit) or limit <= 0:
                raise RuntimeError("Z PID output range must be positive")
            self.check_z_voltage(center - limit)
            self.check_z_voltage(center + limit)
        values = self.read_fm_snapshot(("pll_enabled", "pll_locked", "pid_enabled", "auxout3"))
        if any(values[key] != 1 for key in ("pll_enabled", "pll_locked", "pid_enabled")):
            raise RuntimeError("FM scan requires PLL enabled/locked and Z PID enabled in LabOne")
        self.check_z_voltage(values["auxout3"])

    def begin_fm_scan(self, config, lines) -> None:
        with self.io_lock:
            self._fm_scan_static_cache.clear()
        self.validate_fm_scan(config, lines)
        with self.io_lock:
            self._last_scan_route_check = time.monotonic()
            self._fm_scan_active = True

    def end_fm_scan(self) -> None:
        with self.io_lock:
            self._fm_scan_active = False
            self._last_scan_route_check = 0.0
            self._fm_scan_static_cache.clear()

    def check_z_voltage(self, voltage: float) -> None:
        lower = float(self.fm_settings.get("z_min_v", 0.0))
        upper = float(self.fm_settings.get("z_max_v", 5.0))
        if not math.isfinite(voltage) or not lower <= voltage <= upper:
            raise RuntimeError("AUX3 outside configured Z monitor limits; XY stopped, Z remains under LabOne control")

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
