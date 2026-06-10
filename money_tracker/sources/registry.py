"""Source id → reader registry and optional sources.yaml overrides."""

from __future__ import annotations

import os
from typing import Mapping

from money_tracker.sources.readers import base
from money_tracker.sources.readers import n26 as n26_reader
from money_tracker.sources.readers import unknown as unknown_reader

_BUILTIN_READERS: Mapping[str, type[base.BankReader]] = {
    "n26": n26_reader.N26Reader,
    "unknown": unknown_reader.UnknownReader,
}

_DEFAULT_SOURCE_READERS: Mapping[str, str] = {
    "n26": "n26",
    "other": "unknown",
}


def _parse_simple_sources_yaml(text: str) -> dict[str, dict[str, str]]:
    """Parse sources.{id}.reader from a minimal YAML subset (no PyYAML)."""
    result: dict[str, dict[str, str]] = {}
    in_sources = False
    current_id: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "sources:":
            in_sources = True
            continue
        if not in_sources:
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current_id = stripped[:-1]
            result[current_id] = {}
            continue
        if current_id and "reader:" in stripped:
            _, val = stripped.split("reader:", 1)
            result[current_id]["reader"] = val.strip()
    return result


def load_sources_config(base_dir: str | None) -> dict[str, dict[str, str]]:
    """Load sources.yaml from base_dir if present; else built-in defaults."""
    if not base_dir:
        return {sid: {"reader": rid} for sid, rid in _DEFAULT_SOURCE_READERS.items()}
    path = os.path.join(base_dir, "sources.yaml")
    if not os.path.isfile(path):
        return {sid: {"reader": rid} for sid, rid in _DEFAULT_SOURCE_READERS.items()}
    with open(path, encoding="utf-8") as handle:
        parsed = _parse_simple_sources_yaml(handle.read())
    merged = {sid: {"reader": rid} for sid, rid in _DEFAULT_SOURCE_READERS.items()}
    merged.update(parsed)
    return merged


def registered_reader_ids() -> list[str]:
    """Reader keys available for registration (excludes 'unknown')."""
    return sorted(k for k in _BUILTIN_READERS if k != "unknown")


def get_reader(source_id: str, base_dir: str | None = None) -> base.BankReader:
    """Instantiate the reader for source_id."""
    config = load_sources_config(base_dir)
    entry = config.get(source_id)
    if not entry:
        reader_key = "unknown"
    else:
        reader_key = entry.get("reader", "unknown")
    cls = _BUILTIN_READERS.get(reader_key)
    if cls is None:
        cls = unknown_reader.UnknownReader
    return cls()
