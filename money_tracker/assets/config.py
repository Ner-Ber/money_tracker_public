"""Load asset registry from assets.json."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping, Sequence

from money_tracker.data_loading import get_base_dir

ASSETS_FILE = "assets.json"
ASSET_TYPES = ("bank", "investment", "brokerage", "crypto")


def _assets_path(base_dir: str | None = None) -> str:
    return os.path.join(get_base_dir(base_dir), ASSETS_FILE)


def load_assets(base_dir: str | None = None) -> list[dict[str, Any]]:
    """Return asset definitions from assets.json, or defaults when missing."""
    path = _assets_path(base_dir)
    if not os.path.isfile(path):
        return list(_default_assets())
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        return list(_default_assets())
    return [dict(item) for item in assets]


def save_assets(
    assets: Sequence[Mapping[str, Any]],
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> None:
    """Persist asset registry (maintenance / future UI)."""
    from money_tracker import file_guard

    path = _assets_path(base_dir)
    tmp_path = path + ".tmp"
    file_guard.assert_write_allowed(path, allow_write=allow_write, purpose="update assets")
    file_guard.assert_write_allowed(tmp_path, allow_write=allow_write, purpose="update assets")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"assets": list(assets)}, handle, indent=2)
    os.replace(tmp_path, path)


def asset_by_id(base_dir: str | None = None) -> dict[str, dict[str, Any]]:
    return {str(a["id"]): a for a in load_assets(base_dir) if a.get("id")}


def slugify_asset_id(name: str) -> str:
    slug = re.sub(r"[^\w]+", "_", str(name).strip().lower()).strip("_")
    return slug or "asset"


def add_asset(
    name: str,
    asset_type: str,
    currency: str,
    *,
    asset_id: str | None = None,
    parser: str | None = None,
    expense_source_id: str | None = None,
    base_dir: str | None = None,
    allow_write: bool = False,
) -> dict[str, Any]:
    """Register a new asset in assets.json."""
    from money_tracker.assets.parsers import registry

    clean_name = str(name or "").strip()
    if not clean_name:
        return {"ok": False, "message": "Name is required."}

    clean_type = str(asset_type or "").strip().lower()
    if clean_type not in ASSET_TYPES:
        return {"ok": False, "message": f"Type must be one of: {', '.join(ASSET_TYPES)}."}

    clean_currency = str(currency or "").strip().upper()
    if not clean_currency:
        return {"ok": False, "message": "Currency is required."}

    new_id = str(asset_id).strip() if asset_id else slugify_asset_id(clean_name)
    if not new_id:
        return {"ok": False, "message": "Asset id is required."}

    clean_parser = str(parser).strip() if parser else ""
    if clean_parser and clean_parser not in registry.PARSERS:
        return {"ok": False, "message": f"Unknown parser: {clean_parser}"}

    clean_source = str(expense_source_id).strip() if expense_source_id else ""
    if clean_type == "bank" and clean_parser and not clean_source:
        return {
            "ok": False,
            "message": "Bank assets with a report parser need an expense source (e.g. n26).",
        }

    assets = load_assets(base_dir)
    if any(str(a.get("id")) == new_id for a in assets):
        return {"ok": False, "message": f"Asset id '{new_id}' already exists."}

    entry: dict[str, Any] = {
        "id": new_id,
        "name": clean_name,
        "type": clean_type,
        "currency": clean_currency,
    }
    if clean_parser:
        entry["parser"] = clean_parser
    if clean_source:
        entry["expense_source_id"] = clean_source

    assets.append(entry)
    save_assets(assets, base_dir=base_dir, allow_write=allow_write)
    return {"ok": True, "asset_id": new_id, "message": f"Added asset '{clean_name}'."}


def _default_assets() -> list[dict[str, Any]]:
    return [
        {
            "id": "demo_checking",
            "name": "Demo Checking",
            "type": "bank",
            "currency": "EUR",
            "expense_source_id": "n26",
        },
        {
            "id": "demo_savings",
            "name": "Demo Savings",
            "type": "investment",
            "currency": "EUR",
        },
    ]
