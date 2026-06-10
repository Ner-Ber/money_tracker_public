"""Context-aware, high-separability colors for asset cards."""

from __future__ import annotations

import colorsys
import hashlib

_TYPE_HUE_BANDS: dict[str, tuple[float, float]] = {
    "bank": (195.0, 215.0),
    "investment": (115.0, 145.0),
    "brokerage": (265.0, 295.0),
    "crypto": (25.0, 45.0),
}

_DEFAULT_BAND = (180.0, 220.0)


def asset_color(asset_id: str, asset_type: str, *, theme: str = "teal") -> str:
    """Deterministic accent color for an asset card border/sparkline."""
    band = _TYPE_HUE_BANDS.get(str(asset_type).lower(), _DEFAULT_BAND)
    digest = hashlib.md5(str(asset_id).encode("utf-8")).hexdigest()
    fraction = int(digest[:8], 16) / 0xFFFFFFFF
    hue = (band[0] + fraction * (band[1] - band[0])) / 360.0
    light = 0.48 if theme == "dark" else 0.42
    sat = 0.62
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
