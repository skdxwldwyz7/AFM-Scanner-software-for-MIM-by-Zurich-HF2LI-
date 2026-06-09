from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from afm_gui.device.paths import add_first_existing_path

ZURICH_SCRIPTS_DIR = add_first_existing_path(
    "afm_gui/device/vendor/zurich/scripts",
    "Hardwares/Zurich/scripts",
    "Zurich/scripts",
)


class ZurichHF2LIAdapter:
    capabilities = ("lockin_demod", "lockin_output")

    def __init__(self, session: Any, device: Any, connection: dict[str, object]) -> None:
        self.session = session
        self.device = device
        self.connection = dict(connection)
        self.device_id = str(connection.get("device", "DEV18388"))

    def status(self) -> dict[str, object]:
        from hf2li_tools import device_status

        return device_status(self.session, self.device, self.device_id)

    def read_demod(self, count: int = 1, delay_s: float = 0.01) -> dict[str, float | int | None]:
        from hf2li_tools import average_demod_samples, read_demod_sample

        sample = average_demod_samples(self.device, count, delay_s) if count > 1 else read_demod_sample(self.device)
        return {
            "timestamp": sample.timestamp,
            "x_v": sample.x,
            "y_v": sample.y,
            "r_v": sample.r,
            "phase_deg": sample.phase_deg,
            "frequency_hz": sample.frequency,
            "auxin0_v": sample.auxin0,
            "auxin1_v": sample.auxin1,
        }

    def set_output(
        self,
        amplitude: float | None = None,
        mixer_enable: bool | None = None,
        output_on: bool | None = None,
    ) -> None:
        from hf2li_tools import set_output

        set_output(self.session, self.device, self.device_id, amplitude, mixer_enable, output_on)

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
            "host": self.connection.get("host", "127.0.0.1"),
            "port": self.connection.get("port", 8005),
            "device": self.connection.get("device", self.device_id),
            "interface": self.connection.get("interface", "USB"),
        }

    def close(self) -> None:
        disconnect = getattr(self.session, "disconnect_device", None)
        if callable(disconnect):
            try:
                disconnect(self.device)
            except Exception:
                pass


def create_zurich_hf2li(name: str, connection: dict[str, object]) -> tuple[object, ZurichHF2LIAdapter]:
    try:
        from hf2li_tools import ConnectionConfig, connect
    except ModuleNotFoundError as exc:
        if exc.name == "zhinst":
            raise ModuleNotFoundError(
                "Zurich HF2LI support requires zhinst packages in the afm-gui environment. "
                "Install zhinst-qcodes, zhinst-core, and zhinst-toolkit."
            ) from exc
        raise

    config = ConnectionConfig(
        host=str(connection.get("host", "127.0.0.1")),
        port=int(connection.get("port", 8005)),
        device=str(connection.get("device", "DEV18388")),
        interface=str(connection.get("interface", "USB")),
    )
    session, device = connect(config)
    return session, ZurichHF2LIAdapter(session, device, connection)


__all__ = ["ZurichHF2LIAdapter", "create_zurich_hf2li"]
