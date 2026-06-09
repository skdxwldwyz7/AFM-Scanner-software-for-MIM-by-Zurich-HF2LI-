from __future__ import annotations

from pathlib import Path
import re

import numpy as np


_GSF_MAGIC = b"Gwyddion Simple Field 1.0\n"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", name.strip())
    return cleaned.strip("._") or "channel"


def write_gsf(
    path: str | Path,
    data: np.ndarray,
    *,
    x_real_m: float,
    y_real_m: float,
    xy_unit: str = "m",
    z_unit: str = "",
    title: str = "",
    metadata: dict[str, str | int | float] | None = None,
) -> None:
    """Write one 2D channel as a Gwyddion Simple Field file."""

    array = np.asarray(data, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError("GSF export expects a 2D array")

    y_res, x_res = array.shape
    header = {
        "XRes": x_res,
        "YRes": y_res,
        "XReal": f"{x_real_m:.12g}",
        "YReal": f"{y_real_m:.12g}",
        "XYUnits": xy_unit,
    }
    if z_unit:
        header["ZUnits"] = z_unit
    if title:
        header["Title"] = title
    if metadata:
        header.update({str(key): str(value) for key, value in metadata.items()})

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0).astype("<f4", copy=False)

    with path.open("wb") as file:
        file.write(_GSF_MAGIC)
        for key, value in header.items():
            file.write(f"{key} = {value}\n".encode("utf-8"))
        file.write(b"\x00")
        padding = (-file.tell()) % 4
        if padding:
            file.write(b"\x00" * padding)
        file.write(body.tobytes(order="C"))
