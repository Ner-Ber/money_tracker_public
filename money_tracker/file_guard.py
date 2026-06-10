"""Guard writes to read-only data sources and config files."""

from __future__ import annotations

import os

CONFIG_FILENAMES = frozenset(
    {
        "assets.json",
        "assets_log.json",
        "category_mapping.txt",
        "mappings.txt",
        "sequences.json",
        "sequences.txt",
    }
)


class ProtectedFileWriteError(PermissionError):
    """Raised when code attempts to write a protected file without permission."""


def _config_basename(path: str) -> str:
    name = os.path.basename(path)
    if name.endswith(".tmp"):
        inner = name[:-4]
        if inner in CONFIG_FILENAMES:
            return inner
    return name


def _is_csv_data_path(path: str) -> bool:
    norm = os.path.normpath(path).replace("\\", "/").lower()
    if norm.endswith(".csv"):
        return True
    if "/csv_files/" in f"/{norm}/":
        return True
    csv_dir = os.environ.get("MONEY_TRACKER_CSV_DIR", "").strip()
    if csv_dir:
        csv_norm = os.path.normpath(csv_dir).replace("\\", "/").lower().rstrip("/")
        if norm.startswith(csv_norm + "/") or norm == csv_norm:
            return True
    return False


def assert_write_allowed(path: str, *, allow_write: bool, purpose: str = "write") -> None:
    """Refuse writes to CSV data sources and config files unless explicitly allowed."""
    if _is_csv_data_path(path):
        raise ProtectedFileWriteError(
            f"Refusing to {purpose} data source CSV '{path}'. "
            "Bank export CSVs under csv_files/ are read-only."
        )
    if _config_basename(path) in CONFIG_FILENAMES and not allow_write:
        raise ProtectedFileWriteError(
            f"Refusing to {purpose} '{os.path.basename(path)}' without allow_write=True. "
            "Use an explicit dashboard Save action or pass allow_write=True from a "
            "deliberate maintenance script."
        )
