"""Command-line tools for the HF2LI QCoDeS control helpers."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from hf2li_tools import (
    ConnectionConfig,
    InitDefaults,
    apply_defaults,
    average_demod_samples,
    connect,
    device_status,
    frequency_sweep,
    init_plan,
    read_demod_sample,
    set_output,
    write_samples_csv,
)


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8005)
    parser.add_argument("--device", default="DEV18388")
    parser.add_argument("--interface", default="USB")


def connection_from_args(args: argparse.Namespace) -> ConnectionConfig:
    return ConnectionConfig(args.host, args.port, args.device, args.interface)


def print_dict(data: dict[str, object]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_status(args: argparse.Namespace) -> None:
    session, device = connect(connection_from_args(args))
    print_dict(device_status(session, device, args.device))


def defaults_from_args(args: argparse.Namespace) -> InitDefaults:
    return InitDefaults(
        input_range=args.input_range,
        ac_coupling=int(args.ac_coupling),
        diff_input=int(args.diff_input),
        input_50ohm=int(args.input_50ohm),
        frequency=args.frequency,
        output_range=args.output_range,
        output_amplitude=args.output_amplitude,
        output_mixer_enable=int(args.output_mixer_enable),
        output_on=int(args.output_on),
        demod_timeconstant=args.timeconstant,
        demod_rate=args.demod_rate,
        demod_order=args.demod_order,
        demod_sinc=int(args.sinc_filter),
    )


def cmd_init(args: argparse.Namespace) -> None:
    session, device = connect(connection_from_args(args))
    defaults = defaults_from_args(args)
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    for label, before, after, unit in init_plan(session, device, defaults, args.device):
        suffix = f" {unit}" if unit else ""
        print(f"{label}: {before} -> {after}{suffix}")
    if args.apply:
        apply_defaults(session, device, defaults, args.device)
        print("Applied defaults.")
    else:
        print("No settings were written. Add --apply to write settings.")


def cmd_sample(args: argparse.Namespace) -> None:
    _, device = connect(connection_from_args(args))
    sample = average_demod_samples(device, args.count, args.delay) if args.count > 1 else read_demod_sample(device)
    print_dict(
        {
            "timestamp": sample.timestamp,
            "x_v": sample.x,
            "y_v": sample.y,
            "r_v": sample.r,
            "phase_deg": sample.phase_deg,
            "frequency_hz": sample.frequency,
            "auxin0_v": sample.auxin0,
            "auxin1_v": sample.auxin1,
        }
    )


def cmd_monitor(args: argparse.Namespace) -> None:
    _, device = connect(connection_from_args(args))
    rows = []
    for index in range(args.count):
        sample = read_demod_sample(device)
        row = {
            "index": index,
            "unix_time_s": time.time(),
            "frequency_hz": sample.frequency,
            "x_v": sample.x,
            "y_v": sample.y,
            "r_v": sample.r,
            "phase_deg": sample.phase_deg,
            "auxin0_v": sample.auxin0,
            "auxin1_v": sample.auxin1,
        }
        rows.append(row)
        print_dict(row)
        if index + 1 < args.count:
            time.sleep(args.interval)
    if args.csv:
        write_samples_csv(Path(args.csv), rows)
        print(f"Wrote {args.csv}")


def cmd_output(args: argparse.Namespace) -> None:
    session, device = connect(connection_from_args(args))
    if not args.apply:
        print("DRY RUN: no output settings were written. Add --apply to write.")
        return
    output_on = None if args.output_on is None else args.output_on == "on"
    mixer_enable = None if args.mixer_enable is None else args.mixer_enable == "on"
    set_output(session, device, args.device, args.amplitude, mixer_enable, output_on)
    print("Output settings applied.")


def cmd_sweep(args: argparse.Namespace) -> None:
    _, device = connect(connection_from_args(args))
    rows = frequency_sweep(
        device,
        start_hz=args.start,
        stop_hz=args.stop,
        points=args.points,
        settle_s=args.settle,
        averages=args.averages,
        average_delay_s=args.average_delay,
        apply=args.apply,
    )
    for row in rows:
        print_dict(row)
    if args.csv:
        write_samples_csv(Path(args.csv), rows)
        print(f"Wrote {args.csv}")
    if not args.apply:
        print("DRY RUN: no frequencies were written. Add --apply to run the sweep.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Read current HF2LI status.")
    add_connection_args(status)
    status.set_defaults(func=cmd_status)

    init = subparsers.add_parser("init", help="Preview or apply conservative default settings.")
    add_connection_args(init)
    init.add_argument("--apply", action="store_true")
    init.add_argument("--frequency", type=float, default=1.0e6)
    init.add_argument("--output-amplitude", type=float, default=0.01)
    init.add_argument("--output-range", type=float, default=1.0)
    init.add_argument("--output-on", action="store_true")
    init.add_argument("--output-mixer-enable", action="store_true")
    init.add_argument("--input-range", type=float, default=1.0)
    init.add_argument("--ac-coupling", action="store_true")
    init.add_argument("--diff-input", action="store_true")
    init.add_argument("--input-50ohm", action="store_true")
    init.add_argument("--timeconstant", type=float, default=0.01)
    init.add_argument("--demod-rate", type=float, default=1000.0)
    init.add_argument("--demod-order", type=int, default=4)
    init.add_argument("--sinc-filter", action="store_true")
    init.set_defaults(func=cmd_init)

    sample = subparsers.add_parser("sample", help="Read one demod sample or an averaged sample.")
    add_connection_args(sample)
    sample.add_argument("--count", type=int, default=1)
    sample.add_argument("--delay", type=float, default=0.01)
    sample.set_defaults(func=cmd_sample)

    monitor = subparsers.add_parser("monitor", help="Read demod samples repeatedly.")
    add_connection_args(monitor)
    monitor.add_argument("--count", type=int, default=10)
    monitor.add_argument("--interval", type=float, default=0.2)
    monitor.add_argument("--csv")
    monitor.set_defaults(func=cmd_monitor)

    output = subparsers.add_parser("output", help="Set Signal Output 1 amplitude/enable/on state.")
    add_connection_args(output)
    output.add_argument("--apply", action="store_true")
    output.add_argument("--amplitude", type=float)
    output.add_argument("--mixer-enable", choices=["on", "off"])
    output.add_argument("--output-on", choices=["on", "off"])
    output.set_defaults(func=cmd_output)

    sweep = subparsers.add_parser("sweep", help="Sweep Oscillator 1 frequency and read Demod 1.")
    add_connection_args(sweep)
    sweep.add_argument("--apply", action="store_true")
    sweep.add_argument("--start", type=float, required=True)
    sweep.add_argument("--stop", type=float, required=True)
    sweep.add_argument("--points", type=int, default=101)
    sweep.add_argument("--settle", type=float, default=0.05)
    sweep.add_argument("--averages", type=int, default=3)
    sweep.add_argument("--average-delay", type=float, default=0.01)
    sweep.add_argument("--csv")
    sweep.set_defaults(func=cmd_sweep)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
