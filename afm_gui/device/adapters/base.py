from __future__ import annotations

from typing import Protocol


class DeviceAdapter(Protocol):
    capabilities: tuple[str, ...]

    def snapshot(self) -> dict[str, object]:
        ...

    def close(self) -> None:
        ...


__all__ = ["DeviceAdapter"]
