"""Measure the FM-AFM scan path used by the GUI.

The default mode connects to HF2LI, runs the same FM preflight and acquisition
callback as the GUI, but does not write AUX1/AUX2.  Pass ``--live-write`` only
for a deliberately small test when real XY output timing is also required.

This script never writes PLL/PID settings or AUX3/AUX4.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

# Make ``python tools/fm_scan_timing.py`` work from a checkout without an
# editable install.  The GUI itself is normally launched from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from afm_gui.core.fm_afm import FM_CHANNEL_BY_KEY, FMAcquisition
from afm_gui.core.scan_config import ScanConfig
from afm_gui.core.scan_geometry import generate_scan_lines
from afm_gui.core.xy_motion import ramp_xy
from afm_gui.device.registry import create_driver


class CallStats:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.labels: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self.batch_shapes: dict[str, set[int]] = defaultdict(set)

    def add(self, name: str, elapsed: float, label: str = "") -> None:
        self.samples[name].append(elapsed)
        if label:
            self.labels[name][label].append(elapsed)

    def total(self, name: str) -> float:
        return sum(self.samples.get(name, ()))

    def count(self, name: str) -> int:
        return len(self.samples.get(name, ()))

    def timed(self, name: str, func: Callable[..., Any], *args: Any, label: str = "", **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            self.add(name, time.perf_counter() - started, label)

    def print_table(self, title: str) -> None:
        print(f"\n[{title}]")
        for name in sorted(self.samples):
            values = self.samples[name]
            ordered = sorted(values)
            p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]
            print(
                f"{name:24s} count={len(values):5d} total={sum(values):10.4f}s "
                f"avg={statistics.fmean(values):.6f}s median={statistics.median(values):.6f}s "
                f"p95={p95:.6f}s max={max(values):.6f}s"
            )
            for label, labeled in sorted(self.labels[name].items()):
                print(f"  {label:20s} count={len(labeled):5d} total={sum(labeled):10.4f}s")


def install_timers(adapter: object, stats: CallStats) -> None:
    """Wrap adapter methods in place so internal calls are counted too."""
    methods = (
        "read_fm_snapshot",
        "read_demod",
        "_read_batch_group",
        "_get",
        "read_xy",
        "set_xy_voltage",
        "validate_xy_control",
    )
    for name in methods:
        original = getattr(adapter, name, None)
        if not callable(original):
            continue

        def timed(*args: Any, _original=original, _name=name, **kwargs: Any) -> Any:
            label = ""
            if _name in {"_read_batch_group", "_get"} and args:
                label = str(args[0])
            result = stats.timed(_name, _original, *args, label=label, **kwargs)
            if _name == "_read_batch_group" and isinstance(result, dict):
                stats.batch_shapes[label].add(len(result))
            return result

        setattr(adapter, name, timed)


def parse_channels(raw: str) -> tuple[str, ...]:
    aliases = {
        "aux1": "auxout1",
        "aux2": "auxout2",
        "aux3": "auxout3",
        "aux4": "auxout4",
        "pll": "pll_df",
        "df": "pll_df",
        "pid": "pid_error",
    }
    result: list[str] = []
    for item in raw.split(","):
        key = aliases.get(item.strip().lower(), item.strip().lower())
        if not key:
            continue
        if key not in FM_CHANNEL_BY_KEY:
            choices = ", ".join(FM_CHANNEL_BY_KEY)
            raise ValueError(f"Unknown channel {key!r}; choices are: {choices}")
        if key not in result:
            result.append(key)
    if not result:
        raise ValueError("At least one channel is required")
    return tuple(result)


def make_config(args: argparse.Namespace) -> ScanConfig:
    return ScanConfig(
        xc=args.xc,
        yc=args.yc,
        width=args.width,
        height=args.height,
        angle=0.0,
        pixels=args.pixels,
        lines=args.lines,
        linear=args.linear,
        t_sample=args.sample,
        t_settle=args.settle,
        t_rest=args.rest,
        scan_mode="fm_afm",
        channels=parse_channels(args.channels),
        scan_passes=("trace",) if args.trace_only else ("trace", "retrace"),
        xy_unit="V",
        volts_per_nm_x=1.0,
        volts_per_nm_y=1.0,
    )


def sleep_like_gui(seconds: float) -> None:
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.01))


def run_scan(
    adapter: object,
    config: ScanConfig,
    lines: list[tuple[np.ndarray, np.ndarray]],
    acquisition: FMAcquisition,
    stats: CallStats,
    live_write: bool,
) -> None:
    xy_position: tuple[float, float] | None = None
    stop = __import__("threading").Event()
    started = time.perf_counter()
    for line_index, (start, end) in enumerate(lines):
        for scan_pass, first, last in (
            ("trace", start, end),
            *( (("retrace", end, start),) if "retrace" in config.scan_passes else () ),
        ):
            points = np.linspace(first, last, config.pixels)
            if len(points):
                if xy_position is None:
                    xy_position = stats.timed("read_xy_initial", adapter.read_xy)
                if live_write:
                    xy_position = ramp_xy(
                        adapter,
                        xy_position,
                        tuple(points[0]),
                        config.linear,
                        stop,
                    )
                sleep_like_gui(config.t_settle)
            pass_started = time.perf_counter()
            for index, point in enumerate(points):
                if index and live_write:
                    xy_position = ramp_xy(adapter, xy_position, tuple(point), config.linear, stop)
                sleep_like_gui(config.t_sample)
                stats.timed("acquisition", acquisition, config.channels)
            pass_elapsed = time.perf_counter() - pass_started
            print(
                f"line={line_index + 1}/{len(lines)} pass={scan_pass} "
                f"pixels={len(points)} elapsed={pass_elapsed:.4f}s"
            )
        sleep_like_gui(config.t_rest)
    stats.add("scan_total", time.perf_counter() - started)


def connect_hf2() -> tuple[object, object, dict[str, Any]]:
    import yaml

    path = PROJECT_ROOT / "afm_gui" / "config" / "devices.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = next((item for item in data.get("devices", []) if item.get("name") == "zurich_HF2LI"), None)
    if raw is None:
        raise RuntimeError(f"zurich_HF2LI is missing from {path}")
    connection = dict(raw.get("connection") or {})
    instrument, adapter = create_driver(str(raw.get("driver", "zurich.hf2li")), "zurich_HF2LI", connection)
    return instrument, adapter, connection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xc", type=float, default=2.5, help="scan center X in AUX volts")
    parser.add_argument("--yc", type=float, default=2.5, help="scan center Y in AUX volts")
    parser.add_argument("--pixels", type=int, default=8)
    parser.add_argument("--lines", type=int, default=1)
    parser.add_argument("--width", type=float, default=0.1, help="scan width in AUX volts")
    parser.add_argument("--height", type=float, default=0.1, help="scan height in AUX volts")
    parser.add_argument("--linear", type=float, default=0.5, help="XY speed in V/s")
    parser.add_argument("--sample", type=float, default=1e-6, help="per-pixel sample wait in seconds")
    parser.add_argument("--settle", type=float, default=0.0)
    parser.add_argument("--rest", type=float, default=0.0)
    parser.add_argument("--channels", default="auxout3,auxout4", help="comma-separated FM channel keys")
    parser.add_argument("--trace-only", action="store_true", help="omit the retrace pass")
    parser.add_argument(
        "--live-write",
        action="store_true",
        help="write real AUX1/AUX2 positions while scanning; use only for a small controlled test",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.pixels < 1 or args.lines < 1:
        raise SystemExit("--pixels and --lines must be positive")
    instrument = None
    adapter = None
    scan_started = False
    try:
        config = make_config(args)
        lines = generate_scan_lines(config, 0)
        print("Connecting to Zurich HF2LI...")
        connect_started = time.perf_counter()
        instrument, adapter, connection = connect_hf2()
        stats = CallStats()
        install_timers(adapter, stats)
        print(f"Connected in {time.perf_counter() - connect_started:.4f}s")
        print(f"Device={connection.get('device', '')} host={connection.get('host', '')}:{connection.get('port', '')}")
        print(f"Channels={', '.join(config.channels)} passes={', '.join(config.scan_passes)} live_write={args.live_write}")
        print(f"Pixels={config.pixels} lines={config.lines} width={config.width:g}V height={config.height:g}V linear={config.linear:g}V/s")

        preflight_started = time.perf_counter()
        adapter.validate_fm_geometry(config, lines)
        adapter.begin_fm_scan(config, lines)
        scan_started = True
        stats.add("preflight", time.perf_counter() - preflight_started)
        try:
            stats.timed("selected_snapshot", adapter.read_fm_snapshot, set(config.channels))
            stats.timed("full_snapshot", adapter.read_fm_snapshot, set(FM_CHANNEL_BY_KEY))
            if not args.live_write:
                print("Dry movement mode: AUX1/AUX2 writes are disabled; acquisition timings are still real.")
                print("Use --live-write with a small scan to measure ramp/set_xy_voltage overhead.")
            run_scan(adapter, config, lines, FMAcquisition(adapter), stats, args.live_write)
        finally:
            if scan_started:
                adapter.end_fm_scan()
        stats.print_table("timed adapter calls")
        if stats.batch_shapes:
            print("\n[LabOne wildcard batch payloads]")
            for group, sizes in sorted(stats.batch_shapes.items()):
                print(f"{group:24s} calls={len(stats.labels['_read_batch_group'][group]):5d} returned_node_counts={sorted(sizes)}")
        print("\n[phase totals]")
        for name in ("preflight", "selected_snapshot", "full_snapshot", "acquisition", "scan_total"):
            print(f"{name:24s} count={stats.count(name):5d} total={stats.total(name):.4f}s")
        print("\nExpected timing from GUI formula: "
              f"{len(lines) * len(config.scan_passes) * (config.width / config.linear + config.pixels * config.t_sample + config.t_settle + config.t_rest):.4f}s "
              "(excludes LabOne calls and Python overhead).")
        if hasattr(adapter, "close"):
            adapter.close()
        elif instrument is not None and hasattr(instrument, "close"):
            instrument.close()
        return 0
    except Exception as exc:
        if adapter is not None and scan_started:
            try:
                adapter.end_fm_scan()
            except Exception:
                pass
        if adapter is not None and hasattr(adapter, "close"):
            try:
                adapter.close()
            except Exception:
                pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
