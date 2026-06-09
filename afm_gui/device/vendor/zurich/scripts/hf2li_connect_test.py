"""Read-only QCoDeS connection test for Zurich Instruments HF2LI."""

from __future__ import annotations

from hf2li_tools import ConnectionConfig, connect, device_status, read_demod_sample


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8005
DEVICE_ID = "DEV18388"
INTERFACE = "USB"


def main() -> None:
    config = ConnectionConfig(SERVER_HOST, SERVER_PORT, DEVICE_ID, INTERFACE)
    session, device = connect(config)
    status = device_status(session, device, DEVICE_ID)

    print(f"Connected: {device.name}")
    print(f"Serial: {status['serial']}")
    print(f"Type: {status['type']}")
    print(f"Options: {status['options']}")
    print(f"Clockbase: {status['clockbase_hz']} Hz")

    print("\nDemod 1")
    print(f"Enabled: {status['demod0_enable']}")
    print(f"Frequency: {status['osc0_freq_hz']} Hz")
    print(f"Rate: {status['demod0_rate_sps']} Sa/s")
    print(f"Time constant: {status['demod0_timeconstant_s']} s")

    sample = read_demod_sample(device)
    print("\nDemod 1 sample")
    print(f"x: {sample.x:.9e} V")
    print(f"y: {sample.y:.9e} V")
    print(f"R: {sample.r:.9e} V")
    print(f"Phase: {sample.phase_deg:.6f} deg")
    print(f"Sample frequency: {sample.frequency:.6f} Hz")


if __name__ == "__main__":
    main()
