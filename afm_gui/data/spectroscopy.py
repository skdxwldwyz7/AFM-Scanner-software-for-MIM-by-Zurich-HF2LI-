from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


FORMAT_NAME = "AFM Spectroscopy Bundle"
FORMAT_VERSION = 1


@dataclass(slots=True)
class SpectroscopyBundle:
    spectrum_axis: np.ndarray
    spectra: dict[str, dict[str, np.ndarray]]
    maps: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    axis_name: str = "bias"
    axis_label: str = "Bias"
    axis_unit: str = "V"
    channel_units: dict[str, str] = field(default_factory=dict)


def write_spectroscopy_bundle(path: str | Path, bundle: SpectroscopyBundle) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "format_name": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        **bundle.metadata,
    }

    with h5py.File(output_path, "w") as handle:
        handle.attrs["format_name"] = FORMAT_NAME
        handle.attrs["format_version"] = FORMAT_VERSION
        handle.attrs["metadata_json"] = json.dumps(metadata, indent=2, default=str)

        metadata_dataset = handle.create_dataset("metadata", data=np.bytes_(json.dumps(metadata, default=str)))
        metadata_dataset.attrs["encoding"] = "utf-8"

        axes_group = handle.create_group("axes")
        spectrum = axes_group.create_dataset("spectrum", data=np.asarray(bundle.spectrum_axis, dtype=float))
        spectrum.attrs["name"] = bundle.axis_name
        spectrum.attrs["label"] = bundle.axis_label
        spectrum.attrs["unit"] = bundle.axis_unit

        maps_group = handle.create_group("maps")
        for scan_pass, channels in bundle.maps.items():
            for channel, values in channels.items():
                dataset = maps_group.create_dataset(
                    f"{channel}_{scan_pass}",
                    data=np.asarray(values, dtype=float),
                    compression="gzip",
                )
                _write_dataset_attrs(dataset, channel, scan_pass, bundle.channel_units.get(channel, ""), "line,pixel")

        spectra_group = handle.create_group("spectra")
        for scan_pass, channels in bundle.spectra.items():
            for channel, values in channels.items():
                dataset = spectra_group.create_dataset(
                    f"{channel}_{scan_pass}",
                    data=np.asarray(values, dtype=float),
                    compression="gzip",
                )
                _write_dataset_attrs(
                    dataset,
                    channel,
                    scan_pass,
                    bundle.channel_units.get(channel, ""),
                    "line,pixel,spectrum",
                )
    return output_path


def read_spectroscopy_bundle(path: str | Path) -> SpectroscopyBundle:
    with h5py.File(path, "r") as handle:
        metadata = json.loads(handle.attrs.get("metadata_json", "{}"))
        axis_dataset = handle["axes"]["spectrum"]
        spectrum_axis = np.asarray(axis_dataset[...], dtype=float)
        axis_name = str(axis_dataset.attrs.get("name", "bias"))
        axis_label = str(axis_dataset.attrs.get("label", axis_name.title()))
        axis_unit = str(axis_dataset.attrs.get("unit", ""))
        spectra, channel_units = _read_group(handle.get("spectra"))
        maps, map_units = _read_group(handle.get("maps"))
        channel_units.update(map_units)

    return SpectroscopyBundle(
        spectrum_axis=spectrum_axis,
        spectra=spectra,
        maps=maps,
        metadata=metadata,
        axis_name=axis_name,
        axis_label=axis_label,
        axis_unit=axis_unit,
        channel_units=channel_units,
    )


def _write_dataset_attrs(dataset: h5py.Dataset, channel: str, scan_pass: str, unit: str, axis_order: str) -> None:
    dataset.attrs["channel"] = channel
    dataset.attrs["scan_pass"] = scan_pass
    dataset.attrs["unit"] = unit
    dataset.attrs["axis_order"] = axis_order


def _read_group(group: h5py.Group | None) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, str]]:
    data: dict[str, dict[str, np.ndarray]] = {}
    units: dict[str, str] = {}
    if group is None:
        return data, units
    for dataset in group.values():
        channel = str(dataset.attrs.get("channel", ""))
        scan_pass = str(dataset.attrs.get("scan_pass", "trace"))
        if not channel:
            channel = str(dataset.name.rsplit("/", 1)[-1]).rsplit("_", 1)[0]
        data.setdefault(scan_pass, {})[channel] = np.asarray(dataset[...], dtype=float)
        units[channel] = str(dataset.attrs.get("unit", ""))
    return data, units


__all__ = ["FORMAT_NAME", "FORMAT_VERSION", "SpectroscopyBundle", "read_spectroscopy_bundle", "write_spectroscopy_bundle"]
