"""Central snapshot log for asset values (assets_log.json)."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Sequence

from money_tracker import file_guard
from money_tracker.data_loading import get_base_dir

LOG_FILE = "assets_log.json"


def _log_path(base_dir: str | None = None) -> str:
    return os.path.join(get_base_dir(base_dir), LOG_FILE)


def load_log(base_dir: str | None = None) -> list[dict[str, Any]]:
    path = _log_path(base_dir)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    snapshots = payload.get("snapshots", [])
    if not isinstance(snapshots, list):
        return []
    return [dict(item) for item in snapshots]


def save_log(
    snapshots: Sequence[Mapping[str, Any]],
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> None:
    path = _log_path(base_dir)
    tmp_path = path + ".tmp"
    file_guard.assert_write_allowed(path, allow_write=allow_write, purpose="update assets log")
    file_guard.assert_write_allowed(tmp_path, allow_write=allow_write, purpose="update assets log")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"snapshots": list(snapshots)}, handle, indent=2)
    os.replace(tmp_path, path)


def _snapshot_key(snapshot: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(snapshot.get("asset_id", "")),
        str(snapshot.get("as_of", "")),
        str(snapshot.get("source", "")),
    )


def append_snapshot(
    snapshot: Mapping[str, Any],
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> bool:
    """Append snapshot if (asset_id, as_of, source) is not already present. Returns True if added."""
    snapshots = load_log(base_dir)
    key = _snapshot_key(snapshot)
    if any(_snapshot_key(s) == key for s in snapshots):
        return False
    snapshots.append(dict(snapshot))
    save_log(snapshots, base_dir=base_dir, allow_write=allow_write)
    return True


def snapshots_for_asset(
    asset_id: str,
    base_dir: str | None = None,
) -> list[dict[str, Any]]:
    rows = [s for s in load_log(base_dir) if str(s.get("asset_id")) == str(asset_id)]
    return sorted(rows, key=lambda s: str(s.get("as_of", "")))


def latest_snapshot(
    asset_id: str,
    base_dir: str | None = None,
) -> dict[str, Any] | None:
    rows = snapshots_for_asset(asset_id, base_dir)
    return rows[-1] if rows else None
