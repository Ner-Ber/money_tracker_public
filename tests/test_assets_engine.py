"""Tests for asset valuation engine and bank projection."""

from __future__ import annotations

import pandas as pd

from money_tracker.assets import engine
from money_tracker.assets import log
from money_tracker.sources import schema as sources_schema


def _write_n26_csv(tmp_path):
    csv_dir = tmp_path / "csv_files" / "n26"
    csv_dir.mkdir(parents=True)
    (csv_dir / "a.csv").write_text(
        "Booking Date,Value Date,Partner Name,Type,Payment Reference,Account Name,Amount (EUR)\n"
        "2026-01-01,2026-01-01,Card settlement,Presentment,,Main,-100.00\n"
        "2026-01-15,2026-01-15,Employer Payroll,Income,,Main,5000.00\n",
        encoding="utf-8",
    )


def test_bank_projection_after_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr("money_tracker.data_loading.get_csv_dir", lambda base_dir=None: str(tmp_path / "csv_files"))
    _write_n26_csv(tmp_path)

    log.append_snapshot({
        "asset_id": "demo_checking",
        "as_of": "2025-12-31T00:00:00",
        "value": 10000.0,
        "currency": "EUR",
        "source": "report",
    }, base_dir=str(tmp_path), allow_write=True)

    asset = {
        "id": "demo_checking",
        "currency": "EUR",
        "expense_source_id": "n26",
    }
    cur = engine.current_value(asset, base_dir=str(tmp_path))
    assert cur is not None
    assert cur["value"] == 14900.0
    assert cur["source"] == "projected"


def test_ignore_transactions_before_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr("money_tracker.data_loading.get_csv_dir", lambda base_dir=None: str(tmp_path / "csv_files"))
    _write_n26_csv(tmp_path)

    log.append_snapshot({
        "asset_id": "demo_checking",
        "as_of": "2026-01-10T00:00:00",
        "value": 10000.0,
        "currency": "EUR",
        "source": "manual",
    }, base_dir=str(tmp_path), allow_write=True)

    asset = {"id": "demo_checking", "currency": "EUR", "expense_source_id": "n26"}
    cur = engine.current_value(asset, base_dir=str(tmp_path))
    assert cur["value"] == 15000.0


def test_transaction_delta_includes_settlement_rows():
    asset = {"expense_source_id": "n26"}
    anchor = pd.Timestamp("2025-12-31")
    tx = pd.DataFrame({
        sources_schema.SOURCE_ID: ["n26", "n26"],
        "Booking Date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-15")],
        "Amount (EUR)": [-100.0, 5000.0],
        "is_settlement_excluded": [True, False],
    })
    delta = engine._transaction_delta(asset, anchor, tx)
    assert delta == 4900.0
