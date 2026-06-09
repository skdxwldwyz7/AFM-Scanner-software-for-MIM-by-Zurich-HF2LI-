"""Initialize conservative default settings for an HF2LI used with QCoDeS.

By default this script is a dry run. Add --apply to write settings.
The defaults are intentionally conservative for AFM bring-up:
- Signal output is left OFF.
- Output oscillator amplitude is preloaded to a small value.
- PID and PLL loops are disabled.
- Demodulator 1 is enabled for readout from Signal Input 1.
"""

from __future__ import annotations

import argparse
from hf2li_tools import (
    ConnectionConfig,
    InitDefaults,
    apply_defaults,
    average_demod_samples,
    connect,
    device_status,
    init_plan,
)


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8005
DEVICE_ID = "DEV18388"
INTERFACE = "USB"


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.9g}"
    return str(value)


def print_sample(device) -> None:
    sample = average_demod_samples(device, 1, 0.0)
    print("\nDemod 1 sample after connection")
    print(f"  x: {sample.x:.9e} V")
    print(f"  y: {sample.y:.9e} V")
    print(f"  R: {sample.r:.9e} V")
    print(f"  Phase: {sample.phase_deg:.6f} deg")
    print(f"  Sample frequency: {sample.frequency:.6f} Hz")


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
        demod_input=args.demod_input,
        demod_timeconstant=args.timeconstant,
        demod_rate=args.demod_rate,
        demod_order=args.demod_order,
        demod_sinc=int(args.sinc_filter),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write settings to the HF2LI. Without this flag, only print planned changes.")
    parser.add_argument("--host", default=SERVER_HOST)
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument("--device", default=DEVICE_ID)
    parser.add_argument("--interface", default=INTERFACE)
    parser.add_argument("--frequency", type=float, default=1.0e6, help="Oscillator 1 frequency in Hz.")
    parser.add_argument("--output-amplitude", type=float, default=0.01, help="Signal Output 1 oscillator 1 amplitude in V.")
    parser.add_argument("--output-range", type=float, default=1.0, help="Signal Output 1 range in V.")
    parser.add_argument("--output-on", action="store_true", help="Turn Signal Output 1 on. Default keeps it off.")
    parser.add_argument("--output-mixer-enable", action="store_true", help="Enable oscillator 1 contribution to Signal Output 1.")
    parser.add_argument("--input-range", type=float, default=1.0, help="Signal Input 1 range in V.")
    parser.add_argument("--ac-coupling", action="store_true", help="Enable AC coupling on Signal Input 1.")
    parser.add_argument("--diff-input", action="store_true", help="Use differential Signal Input 1.")
    parser.add_argument("--input-50ohm", action="store_true", help="Enable 50 Ohm termination on Signal Input 1.")
    parser.add_argument("--demod-input", type=int, default=0, help="Demod 1 input select. 0 is Signal Input 1.")
    parser.add_argument("--timeconstant", type=float, default=0.01, help="Demod 1 time constant in seconds.")
    parser.add_argument("--demod-rate", type=float, default=1_000.0, help="Demod 1 sample rate in Sa/s.")
    parser.add_argument("--demod-order", type=int, default=4, help="Demod 1 low-pass filter order.")
    parser.add_argument("--sinc-filter", action="store_true", help="Enable Demod 1 sinc filter.")
    parser.add_argument("--read-sample", action="store_true", help="Read and print one Demod 1 sample after connecting.")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    config = ConnectionConfig(args.host, args.port, args.device, args.interface)
    session, device = connect(config)
    status = device_status(session, device, args.device)
    defaults = defaults_from_args(args)

    print(f"Connected: {device.name}")
    print(f"Serial: {status['serial']}")
    print(f"Type: {status['type']}")
    print(f"Options: {status['options']}")
    print(f"Clockbase: {status['clockbase_hz']} Hz")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")

    print("\nDefault settings")
    for label, before, after, unit in init_plan(session, device, defaults, args.device):
        suffix = f" {unit}" if unit else ""
        print(f"  {label}: {format_value(before)} -> {format_value(after)}{suffix}")
    if args.apply:
        apply_defaults(session, device, defaults, args.device)
        print("Applied defaults.")

    if args.read_sample:
        print_sample(device)

    if not args.apply:
        print("\nNo settings were written. Re-run with --apply to initialize the HF2LI.")


if __name__ == "__main__":
    main()
