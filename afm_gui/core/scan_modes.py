from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    name: str
    label: str
    unit: str = ""
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ScanModeConfig:
    name: str
    label: str
    channels: tuple[ChannelConfig, ...]
    default_display_count: int = 2
    scan_passes: tuple[str, ...] = ("trace", "retrace")

    @property
    def default_channels(self) -> tuple[str, ...]:
        selected = tuple(channel.name for channel in self.channels if channel.enabled)
        if selected:
            return selected
        return tuple(channel.name for channel in self.channels[:1])

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(channel.name for channel in self.channels)

    def label_for(self, channel_name: str) -> str:
        for channel in self.channels:
            if channel.name == channel_name:
                return channel.label
        return channel_name

    def unit_for(self, channel_name: str) -> str:
        for channel in self.channels:
            if channel.name == channel_name:
                return channel.unit
        return ""


@dataclass(frozen=True, slots=True)
class ScanModeRegistry:
    modes: dict[str, ScanModeConfig]
    default_mode: str

    @property
    def default(self) -> ScanModeConfig:
        return self.modes[self.default_mode]


def load_scan_modes(path: str | Path | None = None) -> ScanModeRegistry:
    if path is None:
        with resources.files("afm_gui.config").joinpath("scan_modes.yaml").open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file)
    else:
        with Path(path).open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file)

    return _parse_registry(raw)


def _parse_registry(raw: dict[str, Any]) -> ScanModeRegistry:
    modes = {}
    for mode_name, mode_raw in raw["modes"].items():
        if not bool(mode_raw.get("enabled", True)):
            continue
        channels = tuple(
            ChannelConfig(
                name=str(channel["name"]),
                label=str(channel.get("label", channel["name"])),
                unit=str(channel.get("unit", "")),
                enabled=bool(channel.get("enabled", True)),
            )
            for channel in mode_raw["channels"]
        )
        modes[mode_name] = ScanModeConfig(
            name=mode_name,
            label=str(mode_raw.get("label", mode_name)),
            channels=channels,
            default_display_count=int(mode_raw.get("default_display_count", min(2, len(channels)))),
            scan_passes=tuple(str(item) for item in mode_raw.get("scan_passes", ("trace", "retrace"))),
        )

    if not modes:
        raise ValueError("Scan mode config has no enabled modes")
    default_mode = str(raw.get("default_mode") or next(iter(modes)))
    if default_mode not in modes:
        default_mode = next(iter(modes))
    return ScanModeRegistry(modes=modes, default_mode=default_mode)
