"""Discover CSV files, read per source, normalize, and merge."""

from __future__ import annotations

import os
from typing import Iterator

import pandas as pd

from money_tracker.sources import normalize
from money_tracker.sources import registry
from money_tracker.sources.readers import unknown as unknown_reader

# Populated by the last load_all_transactions call (for dashboard error display).
_last_load_errors: list[str] = []


def get_last_load_errors() -> list[str]:
    """Human-readable errors from the most recent load (empty if none)."""
    return list(_last_load_errors)


def clear_last_load_errors() -> None:
    _last_load_errors.clear()


def iter_csv_paths(csv_dir: str) -> Iterator[tuple[str, str]]:
    """
    Yield (absolute_path, relative_path) for every .csv under csv_dir.

    relative_path uses forward slashes (e.g. n26/2025.csv).
    """
    if not os.path.isdir(csv_dir):
        return
    for root, _dirs, files in os.walk(csv_dir):
        for name in sorted(files):
            if not name.lower().endswith(".csv"):
                continue
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, csv_dir).replace("\\", "/")
            yield abs_path, rel


def _csv_in_subdirectories(csv_dir: str) -> bool:
    """True if any CSV lives in a subdirectory of csv_dir."""
    for _abs_path, rel in iter_csv_paths(csv_dir):
        if "/" in rel:
            return True
    return False


def infer_source_id(rel_path: str, *, flat_layout: bool) -> str:
    """
    Assign source_id from path.

    Flat layout (production): all root-level files → n26.
    Subfolder layout (dev): first path segment is source_id (e.g. n26/export.csv).
    """
    from money_tracker.sources import schema

    if flat_layout or "/" not in rel_path:
        return schema.DEFAULT_SOURCE_ID
    return rel_path.split("/", 1)[0]


def load_all_transactions(
    csv_dir: str,
    base_dir: str | None = None,
) -> pd.DataFrame:
    """
    Load all CSVs under csv_dir, normalize, and concatenate.

    Does not dedupe; caller (data_loading) applies deduplication.
    """
    global _last_load_errors
    _last_load_errors = []

    if not os.path.isdir(csv_dir):
        return pd.DataFrame()

    flat_layout = not _csv_in_subdirectories(csv_dir)
    frames: list[pd.DataFrame] = []

    for abs_path, rel_path in iter_csv_paths(csv_dir):
        source_id = infer_source_id(rel_path, flat_layout=flat_layout)
        try:
            reader = registry.get_reader(source_id, base_dir=base_dir)
            raw = reader.read(abs_path)
            canonical = normalize.to_canonical(
                raw,
                source_id=source_id,
                source_file=rel_path,
            )
            frames.append(canonical)
        except (ValueError, unknown_reader.UnknownFormatError) as exc:
            _last_load_errors.append(f"{rel_path}: {exc}")
        except Exception as exc:
            _last_load_errors.append(f"{rel_path}: {type(exc).__name__}: {exc}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
