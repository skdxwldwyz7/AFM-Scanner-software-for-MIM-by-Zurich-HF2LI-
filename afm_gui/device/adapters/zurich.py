from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from afm_gui.device.paths import add_first_existing_path
from afm_gui.device.adapters.hf2_fm import HF2FMInterface, serialized_io

ZURICH_SCRIPTS_DIR = add_first_existing_path(
    "afm_gui/device/vendor/zurich/scripts",
    "Hardwares/Zurich/scripts",
    "Zurich/scripts",
)


class ZurichHF2LIAdapter(HF2FMInterface):
    capabilities = ("lockin_demod", "lockin_output", "scanner_voltage", "fm_afm_readout")
    lockin_channels = ("ch1", "ch2")
    DEFAULT_CHANNELS = {
        "ch1": {"demod_index": 0, "input_index": 0, "oscillator_index": 0, "output_index": 0, "amplitude_index": 6},
        "ch2": {"demod_index": 1, "input_index": 1, "oscillator_index": 1, "output_index": 1, "amplitude_index": 7},
    }

    def __init__(self, session: Any, device: Any, connection: dict[str, object]) -> None:
        self.session = session
        self.device = device
        self.connection = dict(connection)
        self.device_id = str(connection.get("device", "DEV18388"))
        self.channels = self._parse_channels(connection.get("channels"))
        self._init_fm()

    @serialized_io
    def status(self) -> dict[str, object]:
        from hf2li_tools import device_status

        return device_status(self.session, self.device, self.device_id)

    @serialized_io
    def read_demod(
        self,
        count: int = 1,
        delay_s: float = 0.01,
        demod_index: int = 0,
    ) -> dict[str, float | int | None]:
        from hf2li_tools import average_demod_samples, read_demod_sample

        sample = (
            average_demod_samples(self.device, count, delay_s, demod_index=demod_index)
            if count > 1
            else read_demod_sample(self.device, demod_index=demod_index)
        )
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

    @serialized_io
    def set_output(
        self,
        amplitude: float | None = None,
        mixer_enable: bool | None = None,
        output_on: bool | None = None,
        output_index: int = 0,
        amplitude_index: int = 6,
    ) -> None:
        from hf2li_tools import set_output

        if self.fm_readonly:
            raise RuntimeError("FM-AFM profile: excitation is configured only in LabOne")

        set_output(
            self.session,
            self.device,
            self.device_id,
            amplitude,
            mixer_enable,
            output_on,
            output_index=output_index,
            amplitude_index=amplitude_index,
        )

    @serialized_io
    def configure_demod(
        self,
        *,
        demod_index: int = 0,
        input_index: int = 0,
        oscillator_index: int = 0,
        frequency_hz: float | None = None,
        phase_deg: float | None = None,
        time_constant_s: float | None = None,
        enable: bool = True,
    ) -> None:
        from hf2li_tools import configure_demod

        if self.fm_readonly:
            raise RuntimeError("FM-AFM profile: demodulators/PLL are configured only in LabOne")

        configure_demod(
            self.device,
            demod_index=demod_index,
            input_index=input_index,
            oscillator_index=oscillator_index,
            frequency_hz=frequency_hz,
            phase_deg=phase_deg,
            time_constant_s=time_constant_s,
            enable=enable,
        )

    def demod_index_for_channel(self, channel: str) -> int:
        return int(self.channels.get(channel, {}).get("demod_index", 0))

    def input_index_for_channel(self, channel: str) -> int:
        return int(self.channels.get(channel, {}).get("input_index", self.demod_index_for_channel(channel)))

    def oscillator_index_for_channel(self, channel: str) -> int:
        return int(self.channels.get(channel, {}).get("oscillator_index", self.demod_index_for_channel(channel)))

    def output_index_for_channel(self, channel: str) -> int:
        return int(self.channels.get(channel, {}).get("output_index", 0))

    def amplitude_index_for_channel(self, channel: str) -> int:
        return int(self.channels.get(channel, {}).get("amplitude_index", 6 + self.output_index_for_channel(channel)))

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
            "host": self.connection.get("host", "127.0.0.1"),
            "port": self.connection.get("port", 8005),
            "device": self.connection.get("device", self.device_id),
            "interface": self.connection.get("interface", "USB"),
            "channels": self.channels,
            "fm_afm": self.fm_settings,
        }

    @serialized_io
    def close(self) -> None:
        disconnect = getattr(self.session, "disconnect_device", None)
        if callable(disconnect):
            try:
                disconnect(self.device_id.lower())
            except Exception:
                pass

    @classmethod
    def _parse_channels(cls, raw: object) -> dict[str, dict[str, int]]:
        channels = {
            name: dict(mapping)
            for name, mapping in cls.DEFAULT_CHANNELS.items()
        }
        if isinstance(raw, dict):
            for name, mapping in raw.items():
                if not isinstance(mapping, dict):
                    continue
                key = str(name)
                current = channels.setdefault(key, {})
                if "demod_index" in mapping:
                    current["demod_index"] = int(mapping["demod_index"])
                if "input_index" in mapping:
                    current["input_index"] = int(mapping["input_index"])
                if "oscillator_index" in mapping:
                    current["oscillator_index"] = int(mapping["oscillator_index"])
                if "output_index" in mapping:
                    current["output_index"] = int(mapping["output_index"])
                if "amplitude_index" in mapping:
                    current["amplitude_index"] = int(mapping["amplitude_index"])
        return channels


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
