from __future__ import annotations

from collections.abc import Callable
from typing import Any

from afm_gui.device.adapters.mock import MockAdapter


DriverFactory = Callable[[str, dict[str, Any]], tuple[object | None, object]]


def create_driver(driver: str, name: str, connection: dict[str, Any]) -> tuple[object | None, object]:
    if driver.startswith("mock."):
        capabilities = tuple(connection.get("capabilities", (driver.removeprefix("mock."),)))
        return None, MockAdapter(capabilities=capabilities)

    if driver == "multifield.scanner":
        from afm_gui.device.adapters.multifield import create_multifield_scanner

        return create_multifield_scanner(name, connection)

    if driver == "multifield.newton_lt06":
        from afm_gui.device.adapters.multifield import create_newton_lt06

        return create_newton_lt06(name, connection)

    if driver == "attocube.anc350":
        from afm_gui.device.adapters.attocube import create_attocube_anc350

        return create_attocube_anc350(name, connection)

    if driver == "zurich.hf2li":
        from afm_gui.device.adapters.zurich import create_zurich_hf2li

        return create_zurich_hf2li(name, connection)

    if driver in {"srs.sr830", "srs.sr860", "srs.sr865", "srs.sr865a"}:
        from afm_gui.device.adapters.srs import create_srs_lockin

        return create_srs_lockin(name, connection, driver)

    raise NotImplementedError(f"Driver {driver} is not registered")


__all__ = ["create_driver"]
