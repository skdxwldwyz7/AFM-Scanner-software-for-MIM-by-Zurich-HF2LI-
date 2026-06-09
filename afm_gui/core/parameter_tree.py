from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from afm_gui.core.scan_config import ScanConfig, ScanDirection
from afm_gui.core.scan_modes import ScanModeConfig


@dataclass(slots=True)
class ParameterTree:
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.data)

    def set_path(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def update_paths(self, values: dict[str, Any]) -> None:
        for path, value in values.items():
            self.set_path(path, value)

    def append_path(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault(parts[-1], []).append(value)

    def flatten(self, prefix: str = "") -> dict[str, Any]:
        return _flatten(self.data, prefix=prefix)


def build_parameter_tree(
    config: ScanConfig,
    direction: int,
    *,
    mode: ScanModeConfig | None = None,
    display_count: int | None = None,
    display_channels: tuple[str, ...] = (),
    display_passes: tuple[str, ...] = (),
    display_flatten_modes: tuple[str, ...] = (),
    display_colormaps: tuple[str, ...] = (),
    display_ranges: tuple[dict[str, object], ...] = (),
    line_channel: str = "",
    line_pass: str = "",
    source: str = "unknown",
) -> ParameterTree:
    direction_name = "up" if direction == ScanDirection.UP else "down"
    mode_label = mode.label if mode is not None else config.scan_mode
    channel_units = {
        channel: mode.unit_for(channel) if mode is not None else ""
        for channel in config.channels
    }
    parameter_snapshot = scan_config_snapshot(config, direction, mode=mode)

    geometry = {
        "coordinate_unit": config.xy_unit,
        "center_x": config.xc,
        "center_y": config.yc,
        "width": config.width,
        "height": config.height,
        "angle_deg": config.angle,
        "pixels": config.pixels,
        "lines": config.lines,
    }
    if config.xy_unit == "nm":
        geometry.update(
            {
                "center_x_nm": config.xc,
                "center_y_nm": config.yc,
                "width_nm": config.width,
                "height_nm": config.height,
            }
        )
    elif config.xy_unit == "V":
        geometry.update(
            {
                "center_x_v": config.xc,
                "center_y_v": config.yc,
                "width_v": config.width,
                "height_v": config.height,
            }
        )
    timing = {
        "linear": config.linear,
        "linear_unit": f"{config.xy_unit}/s",
        "sample_s": config.t_sample,
        "settle_s": config.t_settle,
        "rest_s": config.t_rest,
    }
    if config.xy_unit == "nm":
        timing["linear_nm_s"] = config.linear
    elif config.xy_unit == "V":
        timing["linear_v_s"] = config.linear

    tree = ParameterTree(
        {
            "app": {
                "name": "afm-gui",
                "metadata_schema": "afm.parameter_tree.v1",
                "created_utc": _now_utc(),
                "source": source,
            },
            "scan": {
                "mode": {
                    "name": config.scan_mode,
                    "label": mode_label,
                },
                "direction": direction_name,
                "parameters": {
                    "initial": deepcopy(parameter_snapshot),
                    "current": deepcopy(parameter_snapshot),
                },
                "geometry": geometry,
                "timing": timing,
                "channels": {
                    "recorded": list(config.channels),
                    "passes": list(config.scan_passes),
                    "units": channel_units,
                },
                "calibration": {
                    "volts_per_nm_x": config.volts_per_nm_x,
                    "volts_per_nm_y": config.volts_per_nm_y,
                },
            },
            "display": {
                "view_count": display_count,
                "view_channels": list(display_channels),
                "view_passes": list(display_passes),
                "flatten_modes": list(display_flatten_modes),
                "colormaps": list(display_colormaps),
                "color_ranges": [dict(item) for item in display_ranges],
                "line_channel": line_channel,
                "line_pass": line_pass,
            },
            "runtime": {
                "current_line_index": -1,
                "updates": [],
            },
        }
    )
    return tree


def parameter_tree_from_config(config: ScanConfig, direction: int) -> ParameterTree:
    return build_parameter_tree(config, direction)


def scan_config_snapshot(
    config: ScanConfig,
    direction: int,
    *,
    mode: ScanModeConfig | None = None,
) -> dict[str, Any]:
    direction_name = "up" if direction == ScanDirection.UP else "down"
    channel_units = {
        channel: mode.unit_for(channel) if mode is not None else ""
        for channel in config.channels
    }
    return {
        "mode": {
            "name": config.scan_mode,
            "label": mode.label if mode is not None else config.scan_mode,
        },
        "direction": direction_name,
        "geometry": {
            "coordinate_unit": config.xy_unit,
            "center_x": config.xc,
            "center_y": config.yc,
            "width": config.width,
            "height": config.height,
            "angle_deg": config.angle,
            "pixels": config.pixels,
            "lines": config.lines,
        },
        "timing": {
            "linear": config.linear,
            "linear_unit": f"{config.xy_unit}/s",
            "sample_s": config.t_sample,
            "settle_s": config.t_settle,
            "rest_s": config.t_rest,
        },
        "channels": {
            "recorded": list(config.channels),
            "passes": list(config.scan_passes),
            "units": channel_units,
        },
        "calibration": {
            "volts_per_nm_x": config.volts_per_nm_x,
            "volts_per_nm_y": config.volts_per_nm_y,
        },
    }


def sync_scan_config_to_tree(
    tree: ParameterTree,
    config: ScanConfig,
    direction: int,
    *,
    mode: ScanModeConfig | None = None,
) -> None:
    snapshot = scan_config_snapshot(config, direction, mode=mode)
    tree.set_path("scan.parameters.current", snapshot)
    tree.set_path("scan.mode", snapshot["mode"])
    tree.set_path("scan.direction", snapshot["direction"])
    tree.set_path("scan.geometry", snapshot["geometry"])
    if config.xy_unit == "nm":
        tree.update_paths(
            {
                "scan.geometry.center_x_nm": config.xc,
                "scan.geometry.center_y_nm": config.yc,
                "scan.geometry.width_nm": config.width,
                "scan.geometry.height_nm": config.height,
            }
        )
    elif config.xy_unit == "V":
        tree.update_paths(
            {
                "scan.geometry.center_x_v": config.xc,
                "scan.geometry.center_y_v": config.yc,
                "scan.geometry.width_v": config.width,
                "scan.geometry.height_v": config.height,
            }
        )
    tree.set_path("scan.timing", snapshot["timing"])
    if config.xy_unit == "nm":
        tree.set_path("scan.timing.linear_nm_s", config.linear)
    elif config.xy_unit == "V":
        tree.set_path("scan.timing.linear_v_s", config.linear)
    tree.set_path("scan.channels", snapshot["channels"])
    tree.set_path("scan.calibration", snapshot["calibration"])
    tree.set_path("scan.parameters.updated_utc", _now_utc())


def record_runtime_update(
    tree: ParameterTree,
    *,
    current_line_index: int,
    applied_to_line_index: int,
    params: dict[str, float],
) -> None:
    flat = tree.flatten()
    linear_unit = flat.get("scan.timing.linear_unit", "")
    path_map = {
        "t_sample": "scan.timing.sample_s",
        "t_settle": "scan.timing.settle_s",
        "t_rest": "scan.timing.rest_s",
    }
    if "linear" in params:
        tree.set_path("scan.timing.linear", params["linear"])
        if linear_unit == "V/s":
            tree.set_path("scan.timing.linear_v_s", params["linear"])
        elif linear_unit == "nm/s":
            tree.set_path("scan.timing.linear_nm_s", params["linear"])
    tree.update_paths({path_map[name]: value for name, value in params.items() if name in path_map})
    tree.append_path(
        "runtime.updates",
        {
            "time_utc": _now_utc(),
            "current_line_index": current_line_index,
            "applied_to_line_index": applied_to_line_index,
            "params": deepcopy(params),
        },
    )


def write_parameter_tree_json(
    path: str | Path,
    tree: ParameterTree,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    data = tree.to_dict()
    if extra:
        data.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def gsf_metadata_from_tree(tree: ParameterTree) -> dict[str, str | int | float]:
    flat = tree.flatten()
    selected = {
        "MetadataSchema": flat.get("app.metadata_schema", ""),
        "MetadataCreatedUTC": flat.get("app.created_utc", ""),
        "ScanMode": flat.get("scan.mode.name", ""),
        "ScanDirection": flat.get("scan.direction", ""),
        "XYUnit": flat.get("scan.geometry.coordinate_unit", ""),
        "CenterX": flat.get("scan.geometry.center_x", ""),
        "CenterY": flat.get("scan.geometry.center_y", ""),
        "Width": flat.get("scan.geometry.width", ""),
        "Height": flat.get("scan.geometry.height", ""),
        "CenterX_nm": flat.get("scan.geometry.center_x_nm", ""),
        "CenterY_nm": flat.get("scan.geometry.center_y_nm", ""),
        "Width_nm": flat.get("scan.geometry.width_nm", ""),
        "Height_nm": flat.get("scan.geometry.height_nm", ""),
        "CenterX_V": flat.get("scan.geometry.center_x_v", ""),
        "CenterY_V": flat.get("scan.geometry.center_y_v", ""),
        "Width_V": flat.get("scan.geometry.width_v", ""),
        "Height_V": flat.get("scan.geometry.height_v", ""),
        "Angle_deg": flat.get("scan.geometry.angle_deg", ""),
        "Linear": flat.get("scan.timing.linear", ""),
        "LinearUnit": flat.get("scan.timing.linear_unit", ""),
        "Linear_nm_s": flat.get("scan.timing.linear_nm_s", ""),
        "Linear_V_s": flat.get("scan.timing.linear_v_s", ""),
        "Sample_s": flat.get("scan.timing.sample_s", ""),
        "Settle_s": flat.get("scan.timing.settle_s", ""),
        "Rest_s": flat.get("scan.timing.rest_s", ""),
    }
    return {key: value for key, value in selected.items() if value != ""}


def _flatten(value: Any, *, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        items = {}
        for key, nested in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            items.update(_flatten(nested, prefix=child_prefix))
        return items
    if isinstance(value, list):
        return {prefix: json.dumps(value)}
    return {prefix: value}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
