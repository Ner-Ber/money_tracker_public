"""Tests for assets_log.json persistence."""

from __future__ import annotations

from money_tracker.assets import log


def test_append_and_dedupe_snapshot(tmp_path):
    snap = {
        "asset_id": "n26_joint",
        "as_of": "2026-04-30T00:00:00",
        "value": 6345.27,
        "currency": "EUR",
        "source": "report",
    }
    assert log.append_snapshot(snap, base_dir=str(tmp_path), allow_write=True)
    assert not log.append_snapshot(snap, base_dir=str(tmp_path), allow_write=True)

    rows = log.load_log(base_dir=str(tmp_path))
    assert len(rows) == 1
    assert log.latest_snapshot("n26_joint", base_dir=str(tmp_path))["value"] == 6345.27


def test_manual_snapshot_distinct_from_report(tmp_path):
    base = {
        "asset_id": "n26_joint",
        "as_of": "2026-04-30T00:00:00",
        "value": 6000.0,
        "currency": "EUR",
    }
    log.append_snapshot({**base, "source": "report"}, base_dir=str(tmp_path), allow_write=True)
    log.append_snapshot({**base, "source": "manual", "value": 6100.0},
                        base_dir=str(tmp_path), allow_write=True)
    assert len(log.load_log(base_dir=str(tmp_path))) == 2
