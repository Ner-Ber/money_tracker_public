"""Tests for assets.json registry helpers."""

from __future__ import annotations

from money_tracker.assets import config


def test_add_asset_persists_to_file(tmp_path):
    result = config.add_asset(
        "My Crypto",
        "crypto",
        "USD",
        asset_id="my_crypto",
        allow_write=True,
        base_dir=str(tmp_path),
    )
    assert result["ok"] is True
    assets = config.load_assets(base_dir=str(tmp_path))
    assert any(a["id"] == "my_crypto" for a in assets)


def test_add_asset_rejects_duplicate_id(tmp_path):
    config.add_asset("One", "investment", "EUR", asset_id="dup", allow_write=True, base_dir=str(tmp_path))
    result = config.add_asset("Two", "investment", "EUR", asset_id="dup", allow_write=True, base_dir=str(tmp_path))
    assert result["ok"] is False
