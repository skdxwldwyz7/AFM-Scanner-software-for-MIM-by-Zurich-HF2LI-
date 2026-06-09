"""Reusable helpers for controlling a Zurich Instruments HF2LI with QCoDeS."""

from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zhinst.qcodes import ZISession


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8005
DEFAULT_DEVICE = "DEV18388"
DEFAULT_INTERFACE = "USB"


@dataclass(frozen=True)
class ConnectionConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    device: str = DEFAULT_DEVICE
    interface: str = DEFAULT_INTERFACE


@dataclass(frozen=True)
class DemodSample:
    timestamp: int
    x: float
    y: float
    r: float
    phase_deg: float
    frequency: float
    auxin0: float | None = None
    auxin1: float | None = None


@dataclass(frozen=True)
class InitDefaults:
    input_range: float = 1.0
    ac_coupling: int = 0
    diff_input: int = 0
    input_50ohm: int = 0
    frequency: float = 1.0e6
    output_range: float = 1.0
    output_offset: float = 0.0
    output_amplitude: float = 0.01
    output_mixer_enable: int = 0
    output_on: int = 0
    demod_input: int = 0
    demod_osc: int = 0
    demod_harmonic: int = 1
    demod_phase_shift: float = 0.0
    demod_order: int = 4
    demod_timeconstant: float = 0.01
    demod_rate: float = 1000.0
    demod_sinc: int = 0
    pid_enable: int = 0
    pll_enable: int = 0


def connect(config: ConnectionConfig = ConnectionConfig()) -> tuple[Any, Any]:
    session = ZISession(config.host, config.port, hf2=True)
    device = session.connect_device(config.device, interface=config.interface)
    return session, device


def scalar(value: Any) -> Any:
    try:
        return value[0]
    except (TypeError, IndexError):
        return value


def raw_device_id(device_id: str) -> str:
    return device_id.lower()


def sigout_osc_amplitude_path(device_id: str, sigout: int = 0) -> str:
    return f"/{raw_device_id(device_id)}/sigouts/{sigout}/amplitudes/6"


def sigout_osc_enable_path(device_id: str, sigout: int = 0) -> str:
    return f"/{raw_device_id(device_id)}/sigouts/{sigout}/enables/6"


def read_raw(session: Any, path: str, kind: str) -> Any:
    if kind == "double":
        return session.daq_server.getDouble(path)
    if kind == "int":
        return session.daq_server.getInt(path)
    raise ValueError(f"Unsupported raw node kind: {kind}")


def write_raw(session: Any, path: str, kind: str, value: Any) -> None:
    if kind == "double":
        session.daq_server.setDouble(path, float(value))
        return
    if kind == "int":
        session.daq_server.setInt(path, int(value))
        return
    raise ValueError(f"Unsupported raw node kind: {kind}")


def device_status(session: Any, device: Any, device_id: str = DEFAULT_DEVICE) -> dict[str, Any]:
    demod = device.demods[0]
    return {
        "name": device.name,
        "serial": device.serial,
        "type": device.device_type,
        "options": device.device_options(),
        "clockbase_hz": device.clockbase(),
        "sigin0_range_v": device.sigins[0].range(),
        "sigin0_ac": device.sigins[0].ac(),
        "sigin0_diff": device.sigins[0].diff(),
        "sigin0_50ohm": device.sigins[0].imp50(),
        "sigout0_range_v": device.sigouts[0].range(),
        "sigout0_offset_v": device.sigouts[0].offset(),
        "sigout0_on": device.sigouts[0].on(),
        "sigout0_osc_amplitude_v": read_raw(session, sigout_osc_amplitude_path(device_id), "double"),
        "sigout0_osc_enable": read_raw(session, sigout_osc_enable_path(device_id), "int"),
        "osc0_freq_hz": device.oscs[0].freq(),
        "demod0_enable": demod.enable(),
        "demod0_input": demod.adcselect(),
        "demod0_osc": demod.oscselect(),
        "demod0_harmonic": demod.harmonic(),
        "demod0_phase_shift_deg": demod.phaseshift(),
        "demod0_order": demod.order(),
        "demod0_timeconstant_s": demod.timeconstant(),
        "demod0_rate_sps": demod.rate(),
        "pid0_enable": device.pids[0].enable(),
        "pll0_enable": device.plls[0].enable(),
    }


def init_plan(session: Any, device: Any, defaults: InitDefaults, device_id: str = DEFAULT_DEVICE) -> list[tuple[str, Any, Any, str]]:
    return [
        ("Signal Input 1 range", device.sigins[0].range(), defaults.input_range, "V"),
        ("Signal Input 1 AC coupling", device.sigins[0].ac(), defaults.ac_coupling, ""),
        ("Signal Input 1 differential", device.sigins[0].diff(), defaults.diff_input, ""),
        ("Signal Input 1 50 Ohm", device.sigins[0].imp50(), defaults.input_50ohm, ""),
        ("Oscillator 1 frequency", device.oscs[0].freq(), defaults.frequency, "Hz"),
        ("Signal Output 1 range", device.sigouts[0].range(), defaults.output_range, "V"),
        ("Signal Output 1 offset", device.sigouts[0].offset(), defaults.output_offset, "V"),
        ("Signal Output 1 oscillator amplitude", read_raw(session, sigout_osc_amplitude_path(device_id), "double"), defaults.output_amplitude, "V"),
        ("Signal Output 1 oscillator enable", read_raw(session, sigout_osc_enable_path(device_id), "int"), defaults.output_mixer_enable, ""),
        ("Signal Output 1 output ON", device.sigouts[0].on(), defaults.output_on, ""),
        ("Demod 1 enable", device.demods[0].enable(), 1, ""),
        ("Demod 1 input select", device.demods[0].adcselect(), defaults.demod_input, ""),
        ("Demod 1 oscillator select", device.demods[0].oscselect(), defaults.demod_osc, ""),
        ("Demod 1 harmonic", device.demods[0].harmonic(), defaults.demod_harmonic, ""),
        ("Demod 1 phase shift", device.demods[0].phaseshift(), defaults.demod_phase_shift, "deg"),
        ("Demod 1 filter order", device.demods[0].order(), defaults.demod_order, ""),
        ("Demod 1 time constant", device.demods[0].timeconstant(), defaults.demod_timeconstant, "s"),
        ("Demod 1 sample rate", device.demods[0].rate(), defaults.demod_rate, "Sa/s"),
        ("Demod 1 sinc filter", device.demods[0].sinc(), defaults.demod_sinc, ""),
        ("PID 1 enable", device.pids[0].enable(), defaults.pid_enable, ""),
        ("PLL 1 enable", device.plls[0].enable(), defaults.pll_enable, ""),
    ]


def apply_defaults(session: Any, device: Any, defaults: InitDefaults, device_id: str = DEFAULT_DEVICE) -> None:
    device.sigins[0].range(defaults.input_range)
    device.sigins[0].ac(defaults.ac_coupling)
    device.sigins[0].diff(defaults.diff_input)
    device.sigins[0].imp50(defaults.input_50ohm)
    device.oscs[0].freq(defaults.frequency)
    device.sigouts[0].range(defaults.output_range)
    device.sigouts[0].offset(defaults.output_offset)
    write_raw(session, sigout_osc_amplitude_path(device_id), "double", defaults.output_amplitude)
    write_raw(session, sigout_osc_enable_path(device_id), "int", defaults.output_mixer_enable)
    device.sigouts[0].on(defaults.output_on)
    device.demods[0].enable(1)
    device.demods[0].adcselect(defaults.demod_input)
    device.demods[0].oscselect(defaults.demod_osc)
    device.demods[0].harmonic(defaults.demod_harmonic)
    device.demods[0].phaseshift(defaults.demod_phase_shift)
    device.demods[0].order(defaults.demod_order)
    device.demods[0].timeconstant(defaults.demod_timeconstant)
    device.demods[0].rate(defaults.demod_rate)
    device.demods[0].sinc(defaults.demod_sinc)
    device.pids[0].enable(defaults.pid_enable)
    device.plls[0].enable(defaults.pll_enable)


def set_output(session: Any, device: Any, device_id: str, amplitude: float | None, enable: bool | None, output_on: bool | None) -> None:
    if amplitude is not None:
        write_raw(session, sigout_osc_amplitude_path(device_id), "double", amplitude)
    if enable is not None:
        write_raw(session, sigout_osc_enable_path(device_id), "int", int(enable))
    if output_on is not None:
        device.sigouts[0].on(int(output_on))


def read_demod_sample(device: Any, demod_index: int = 0) -> DemodSample:
    sample = device.demods[demod_index].sample()
    x = float(scalar(sample["x"]))
    y = float(scalar(sample["y"]))
    auxin0 = float(scalar(sample["auxin0"])) if "auxin0" in sample else None
    auxin1 = float(scalar(sample["auxin1"])) if "auxin1" in sample else None
    return DemodSample(
        timestamp=int(scalar(sample["timestamp"])),
        x=x,
        y=y,
        r=math.hypot(x, y),
        phase_deg=math.degrees(math.atan2(y, x)),
        frequency=float(scalar(sample["frequency"])),
        auxin0=auxin0,
        auxin1=auxin1,
    )


def average_demod_samples(device: Any, count: int, delay_s: float, demod_index: int = 0) -> DemodSample:
    samples = []
    for _ in range(count):
        samples.append(read_demod_sample(device, demod_index))
        if delay_s > 0:
            time.sleep(delay_s)

    x = sum(s.x for s in samples) / count
    y = sum(s.y for s in samples) / count
    aux0_values = [s.auxin0 for s in samples if s.auxin0 is not None]
    aux1_values = [s.auxin1 for s in samples if s.auxin1 is not None]
    return DemodSample(
        timestamp=samples[-1].timestamp,
        x=x,
        y=y,
        r=math.hypot(x, y),
        phase_deg=math.degrees(math.atan2(y, x)),
        frequency=sum(s.frequency for s in samples) / count,
        auxin0=sum(aux0_values) / len(aux0_values) if aux0_values else None,
        auxin1=sum(aux1_values) / len(aux1_values) if aux1_values else None,
    )


def write_samples_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def frequency_sweep(
    device: Any,
    start_hz: float,
    stop_hz: float,
    points: int,
    settle_s: float,
    averages: int,
    average_delay_s: float,
    apply: bool,
) -> list[dict[str, Any]]:
    if points < 2:
        raise ValueError("Sweep requires at least 2 points.")

    rows: list[dict[str, Any]] = []
    original_freq = device.oscs[0].freq()
    for index in range(points):
        freq = start_hz + (stop_hz - start_hz) * index / (points - 1)
        if apply:
            device.oscs[0].freq(freq)
            time.sleep(settle_s)
            sample = average_demod_samples(device, averages, average_delay_s)
        else:
            sample = DemodSample(0, 0.0, 0.0, 0.0, 0.0, freq)
        rows.append(
            {
                "index": index,
                "target_frequency_hz": freq,
                "measured_frequency_hz": sample.frequency,
                "x_v": sample.x,
                "y_v": sample.y,
                "r_v": sample.r,
                "phase_deg": sample.phase_deg,
                "auxin0_v": sample.auxin0,
                "auxin1_v": sample.auxin1,
            }
        )
    if apply:
        device.oscs[0].freq(original_freq)
    return rows
