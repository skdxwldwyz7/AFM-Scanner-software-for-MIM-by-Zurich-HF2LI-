from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

from afm_gui.startup import ensure_mpl_config_dir

ensure_mpl_config_dir()

import numpy as np
from PyQt6.QtCore import QCoreApplication, QTimer

from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.scan_controller import ScanController
from afm_gui.core.lockin_controller import LockInController
from afm_gui.core.parameter_tree import build_parameter_tree
from afm_gui.core.scan_modes import ScanModeConfig, load_scan_modes
from afm_gui.core.stage_controller import StageController
from afm_gui.device.loader import DeviceHandle, load_device_config_file
from afm_gui.device.mock_device import MockScannerDevice


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="afm-cli", description="AFM GUI command line control")
    parser.add_argument("--modes-config", type=Path, help="Path to a scan_modes.yaml file")
    parser.add_argument("--devices-config", type=Path, help="Path to a devices.yaml file")
    subparsers = parser.add_subparsers(required=True)

    gui = subparsers.add_parser("gui", help="Launch the PyQt GUI")
    gui.set_defaults(func=_cmd_gui)

    modes = subparsers.add_parser("modes", help="List configured scan modes")
    modes.set_defaults(func=_cmd_modes)

    channels = subparsers.add_parser("channels", help="List channels for one scan mode")
    channels.add_argument("--mode", help="Scan mode name; defaults to configured default")
    channels.set_defaults(func=_cmd_channels)

    devices = subparsers.add_parser("devices", help="List configured devices")
    devices.set_defaults(func=_cmd_devices)

    stage = subparsers.add_parser("stage", help="Move the mock XYZ stage")
    stage.add_argument("--x", type=float, help="Absolute X position in um")
    stage.add_argument("--y", type=float, help="Absolute Y position in um")
    stage.add_argument("--z", type=float, help="Absolute Z position in um")
    stage.add_argument("--dx", type=float, default=0.0, help="Relative X move in um")
    stage.add_argument("--dy", type=float, default=0.0, help="Relative Y move in um")
    stage.add_argument("--dz", type=float, default=0.0, help="Relative Z move in um")
    stage.add_argument("--home", action="store_true", help="Move to 0, 0, 0 um")
    stage.set_defaults(func=_cmd_stage)

    lockin = subparsers.add_parser("lockin", help="Apply reference output settings and read the mock lock-in amplifier")
    lockin.add_argument("--channel", choices=("ch1", "ch2", "all"), default="ch1", help="Lock-in channel")
    lockin.add_argument("--frequency", type=float, default=1000.0, help="Reference frequency in Hz")
    lockin.add_argument("--amplitude", type=float, default=0.1, help="Output amplitude in V")
    lockin.add_argument("--phase", type=float, default=0.0, help="Reference phase in deg")
    lockin.add_argument("--time-constant", type=float, default=0.1, help="Time constant in s")
    lockin.add_argument("--sensitivity", type=float, default=1.0, help="Sensitivity in V")
    lockin.add_argument("--reserve", default="Normal", help="Reserve mode")
    lockin.add_argument("--output", action="store_true", help="Enable reference output")
    lockin.set_defaults(func=_cmd_lockin)

    scan = subparsers.add_parser("scan", help="Run one mock scan from the CLI")
    _add_scan_arguments(scan)
    scan.set_defaults(func=_cmd_scan)

    preview = subparsers.add_parser("preview-commands", help="Print first-line SPM commands")
    _add_scan_arguments(preview, include_output=False)
    preview.set_defaults(func=_cmd_preview_commands)

    return parser


def _add_scan_arguments(parser: argparse.ArgumentParser, *, include_output: bool = True) -> None:
    parser.add_argument("--mode", help="Scan mode name; defaults to configured default")
    parser.add_argument("--direction", choices=("up", "down"), default="up")
    parser.add_argument("--channels", help="Comma-separated channels; defaults to enabled mode channels")
    parser.add_argument("--xc", type=float, default=0.0)
    parser.add_argument("--yc", type=float, default=0.0)
    parser.add_argument("--width", type=float, default=500.0)
    parser.add_argument("--height", type=float, default=500.0)
    parser.add_argument("--angle", type=float, default=0.0)
    parser.add_argument("--pixels", type=int, default=256)
    parser.add_argument("--lines", type=int, default=256)
    parser.add_argument("--linear", type=float, default=500.0)
    parser.add_argument("--sample", type=float, default=0.001)
    parser.add_argument("--settle", type=float, default=0.02)
    parser.add_argument("--rest", type=float, default=0.01)
    parser.add_argument("--print-commands", action="store_true", help="Print device commands while scanning")
    if include_output:
        parser.add_argument("--export-gsf", type=Path, help="Directory for Gwyddion Simple Field output")
        parser.add_argument("--export-prefix", default="", help="Optional filename prefix for exported GSF bundle")
        parser.add_argument("--auto-save-dir", type=Path, help="Automatically save a timestamped GSF bundle on finish")
        parser.add_argument("--timeout-ms", type=int, default=0, help="Abort the Qt loop after this timeout")
        parser.add_argument("--update-after-line", type=int, help="Apply runtime updates after this 1-based line")
        parser.add_argument("--update-linear", type=float, help="Runtime linear speed update")
        parser.add_argument("--update-sample", type=float, help="Runtime sample time update")
        parser.add_argument("--update-settle", type=float, help="Runtime settle time update")
        parser.add_argument("--update-rest", type=float, help="Runtime rest time update")


def _cmd_gui(args: argparse.Namespace) -> int:
    from afm_gui.main import main as gui_main

    return gui_main()


def _cmd_modes(args: argparse.Namespace) -> int:
    registry = _registry(args)
    for mode in registry.modes.values():
        default_mark = " *" if mode.name == registry.default_mode else ""
        print(f"{mode.name}{default_mark}: {mode.label}")
        print(f"  default_display_count: {mode.default_display_count}")
        print(f"  enabled_channels: {', '.join(mode.default_channels)}")
    return 0


def _cmd_channels(args: argparse.Namespace) -> int:
    registry = _registry(args)
    mode = _mode(registry, args.mode)
    for channel in mode.channels:
        enabled = "enabled" if channel.enabled else "disabled"
        unit = f" [{channel.unit}]" if channel.unit else ""
        print(f"{channel.name}: {channel.label}{unit} ({enabled})")
    return 0


def _cmd_devices(args: argparse.Namespace) -> int:
    functions, devices = _device_config_snapshot(args)
    if functions:
        print("functions:")
        for function in functions:
            print(
                f"  {function['name']}: {function['label']} "
                f"({function['required_kind']}) -> {function['device'] or '<unassigned>'}"
            )
    print("devices:")
    for device in devices:
        enabled = "enabled" if device["enabled"] else "disabled"
        print(f"  {device['name']}: {device['label']} ({device['kind']}, {device['driver']}, {enabled})")
        print(f"  connection: {device['connection']}")
    return 0


def _cmd_stage(args: argparse.Namespace) -> int:
    app = QCoreApplication.instance() or QCoreApplication([])
    _ = app
    stage = StageController()
    if args.home:
        stage.home()
    elif args.x is not None or args.y is not None or args.z is not None:
        stage.move_absolute(
            args.x if args.x is not None else 0.0,
            args.y if args.y is not None else 0.0,
            args.z if args.z is not None else 0.0,
        )
    else:
        stage.move_relative(args.dx, args.dy, args.dz)
    snapshot = stage.snapshot()
    position = snapshot["position_um"]
    print(f"x_um: {position['x']:.3f}")
    print(f"y_um: {position['y']:.3f}")
    print(f"z_um: {position['z']:.3f}")
    print(f"path_points: {snapshot['path_points']}")
    return 0


def _cmd_lockin(args: argparse.Namespace) -> int:
    app = QCoreApplication.instance() or QCoreApplication([])
    _ = app
    channels = ("ch1", "ch2") if args.channel == "all" else (args.channel,)
    for channel in channels:
        _run_lockin_channel(args, channel)
    return 0


def _run_lockin_channel(args: argparse.Namespace, channel: str) -> None:
    lockin = LockInController()
    lockin.configure(
        frequency_hz=args.frequency,
        amplitude_v=args.amplitude,
        phase_deg=args.phase,
        time_constant_s=args.time_constant,
        sensitivity_v=args.sensitivity,
        reserve=args.reserve,
        output_enabled=args.output,
    )
    reading = lockin.read()
    print(f"channel: {channel}")
    print(f"x_v: {reading.x_v:.6g}")
    print(f"y_v: {reading.y_v:.6g}")
    print(f"r_v: {reading.r_v:.6g}")
    print(f"theta_deg: {reading.theta_deg:.3f}")


def _cmd_scan(args: argparse.Namespace) -> int:
    registry = _registry(args)
    mode = _mode(registry, args.mode)
    config = _scan_config(args, mode)
    direction = _direction(args.direction)
    tree = build_parameter_tree(
        config,
        direction,
        mode=mode,
        display_count=0,
        source="cli",
    )
    tree.update_paths(
        {
            "storage.autosave.enabled": args.auto_save_dir is not None,
            "storage.autosave.directory": str(args.auto_save_dir) if args.auto_save_dir else "",
            "storage.autosave.events": [],
            "devices.config_path": str(args.devices_config) if args.devices_config else "",
            "devices.items": _device_snapshot(args),
            "devices.functions": _device_function_snapshot(args),
        }
    )

    app = QCoreApplication.instance() or QCoreApplication([])
    device = MockScannerDevice()
    controller = ScanController(device)
    if args.print_commands:
        controller.log_message.connect(print)

    finished = {"done": False}
    update_state = {"applied": False}

    def on_idle(state: str) -> None:
        if state == "Idle":
            finished["done"] = True
            app.quit()

    controller.state_changed.connect(on_idle)

    runtime_updates = _runtime_updates(args)
    if runtime_updates and args.update_after_line is None:
        raise SystemExit("--update-after-line is required when runtime update values are provided")

    def on_line(line_index: int, data: object) -> None:
        if not runtime_updates or update_state["applied"]:
            return
        if line_index + 1 >= int(args.update_after_line):
            controller.update_runtime_params(**runtime_updates)
            update_state["applied"] = True

    controller.line_changed.connect(on_line)
    if args.timeout_ms:
        QTimer.singleShot(args.timeout_ms, app.quit)

    controller.start(config, direction, tree)
    app.exec()

    if not finished["done"]:
        controller.stop()
        print("scan did not finish before timeout", file=sys.stderr)
        return 2

    _print_scan_summary(controller)
    if args.auto_save_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        line_number = max(0, controller.config.lines)
        prefix = f"afm_{timestamp}_finish_line{line_number:04d}"
        controller.parameter_tree.append_path(
            "storage.autosave.events",
            {
                "event": "finish",
                "timestamp_local": timestamp,
                "directory": str(args.auto_save_dir),
                "file_prefix": prefix,
                "line_index": controller.config.lines - 1,
            },
        )
        paths = controller.export_gsf_bundle(args.auto_save_dir, mode, file_prefix=prefix)
        for path in paths:
            print(path)
    if args.export_gsf:
        paths = controller.export_gsf_bundle(args.export_gsf, mode, file_prefix=args.export_prefix)
        for path in paths:
            print(path)
    return 0


def _cmd_preview_commands(args: argparse.Namespace) -> int:
    registry = _registry(args)
    mode = _mode(registry, args.mode)
    config = _scan_config(args, mode)
    direction = _direction(args.direction)
    device = MockScannerDevice()
    controller = ScanController(device)
    controller.config = config
    controller.direction = direction
    from afm_gui.core.scan_geometry import generate_scan_lines

    controller.lines = generate_scan_lines(config, direction)
    for command in controller._first_line_commands():
        print(command.rstrip())
    return 0


def _registry(args: argparse.Namespace):
    return load_scan_modes(args.modes_config)


def _mode(registry, mode_name: str | None) -> ScanModeConfig:
    selected = mode_name or registry.default_mode
    if selected not in registry.modes:
        valid = ", ".join(registry.modes)
        raise SystemExit(f"Unknown scan mode {selected!r}. Valid modes: {valid}")
    return registry.modes[selected]


def _device_config_snapshot(args: argparse.Namespace) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    configs, functions = load_device_config_file(args.devices_config)
    device_snapshot = []
    for config in configs:
        handle = DeviceHandle(config=config)
        device_snapshot.append(
            {
                "name": config.name,
                "label": config.label,
                "kind": config.kind,
                "driver": config.driver,
                "enabled": config.enabled,
                "connection": dict(config.connection),
                "connected": handle.connected,
                "status": handle.status,
            }
        )
    function_snapshot = [
        {
            "name": function.name,
            "label": function.label,
            "required_kind": function.required_kind,
            "device": function.device,
            "device_status": "",
        }
        for function in functions
    ]
    return function_snapshot, device_snapshot


def _device_snapshot(args: argparse.Namespace) -> list[dict[str, object]]:
    _functions, devices = _device_config_snapshot(args)
    return devices


def _device_function_snapshot(args: argparse.Namespace) -> list[dict[str, object]]:
    functions, _devices = _device_config_snapshot(args)
    return functions


def _scan_config(args: argparse.Namespace, mode: ScanModeConfig) -> ScanConfig:
    channels = _channels(args.channels, mode)
    return ScanConfig(
        xc=args.xc,
        yc=args.yc,
        width=args.width,
        height=args.height,
        angle=args.angle,
        pixels=args.pixels,
        lines=args.lines,
        linear=args.linear,
        t_sample=args.sample,
        t_settle=args.settle,
        t_rest=args.rest,
        scan_mode=mode.name,
        channels=channels,
        scan_passes=mode.scan_passes,
    )


def _channels(raw: str | None, mode: ScanModeConfig) -> tuple[str, ...]:
    if not raw:
        return mode.default_channels
    channels = tuple(channel.strip() for channel in raw.split(",") if channel.strip())
    unknown = sorted(set(channels) - set(mode.channel_names))
    if unknown:
        valid = ", ".join(mode.channel_names)
        raise SystemExit(f"Unknown channel(s): {', '.join(unknown)}. Valid channels: {valid}")
    return channels


def _direction(raw: str) -> int:
    return ScanDirection.UP if raw == "up" else ScanDirection.DOWN


def _runtime_updates(args: argparse.Namespace) -> dict[str, float]:
    updates = {}
    mapping = {
        "linear": "update_linear",
        "t_sample": "update_sample",
        "t_settle": "update_settle",
        "t_rest": "update_rest",
    }
    for param_name, arg_name in mapping.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            updates[param_name] = value
    return updates


def _print_scan_summary(controller: ScanController) -> None:
    finite = {
        scan_pass: {
            channel: int(np.isfinite(image).sum())
            for channel, image in channels.items()
        }
        for scan_pass, channels in controller.images.items()
    }
    print(f"scan_mode: {controller.config.scan_mode}")
    print(f"channels: {', '.join(controller.config.channels)}")
    print(f"shape: {controller.config.lines} x {controller.config.pixels}")
    print(f"finite_points: {finite}")


if __name__ == "__main__":
    raise SystemExit(main())
