"""Tests for multi-source CSV discovery and loading."""

from __future__ import annotations

import pandas as pd
import pytest

from money_tracker import data_loading
from money_tracker.sources import loader
from money_tracker.sources import schema
def _base_row(**overrides):
    row = {
        "Booking Date": "2025-09-10",
        "Value Date": "2025-09-10",
        "Partner Name": "Partner A",
        "Partner Iban": "",
        "Type": "Presentment",
        "Payment Reference": "ref-1",
        "Account Name": "Main",
        "Amount (EUR)": -12.5,
        "Original Amount": -12.5,
        "Original Currency": "EUR",
        "Exchange Rate": 1.0,
    }
    row.update(overrides)
    return row


def _write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def test_iter_csv_paths_recursive(tmp_path):
    csv_dir = tmp_path / "csv_files"
    n26 = csv_dir / "n26"
    n26.mkdir(parents=True)
    _write_csv(n26 / "a.csv", [_base_row()])
    _write_csv(csv_dir / "root.csv", [_base_row()])

    paths = list(loader.iter_csv_paths(str(csv_dir)))
    rels = {rel for _abs, rel in paths}
    assert rels == {"n26/a.csv", "root.csv"}


def test_flat_layout_assigns_n26_source_id(tmp_path):
    csv_dir = tmp_path / "csv_files"
    csv_dir.mkdir()
    _write_csv(csv_dir / "export.csv", [_base_row()])

    df = loader.load_all_transactions(str(csv_dir))

    assert len(df) == 1
    assert df.iloc[0][schema.SOURCE_ID] == schema.DEFAULT_SOURCE_ID
    assert df.iloc[0][schema.SOURCE_FILE] == "export.csv"


def test_subfolder_layout_uses_folder_as_source_id(tmp_path):
    csv_dir = tmp_path / "csv_files"
    n26 = csv_dir / "n26"
    n26.mkdir(parents=True)
    _write_csv(n26 / "export.csv", [_base_row()])

    df = loader.load_all_transactions(str(csv_dir))

    assert len(df) == 1
    assert df.iloc[0][schema.SOURCE_ID] == "n26"
    assert df.iloc[0][schema.SOURCE_FILE] == "n26/export.csv"


def test_unknown_source_records_error_without_crashing(tmp_path):
    csv_dir = tmp_path / "csv_files"
    other = csv_dir / "other"
    other.mkdir(parents=True)
    _write_csv(other / "mystery.csv", [_base_row()])

    df = loader.load_all_transactions(str(csv_dir))

    assert df.empty
    assert loader.get_last_load_errors()
    assert "mystery.csv" in loader.get_last_load_errors()[0]


def test_dedupe_scoped_by_source_id():
    row = _base_row(**{"Payment Reference": "shared"})
    df = pd.DataFrame(
        [
            {**row, schema.SOURCE_ID: "n26", schema.SOURCE_FILE: "n26/a.csv"},
            {**row, schema.SOURCE_ID: "other", schema.SOURCE_FILE: "other/b.csv"},
        ]
    )
    deduped = data_loading._dedupe_transaction_rows(df)
    assert len(deduped) == 2


def test_infer_source_id():
    assert loader.infer_source_id("n26/file.csv", flat_layout=False) == "n26"
    assert loader.infer_source_id("file.csv", flat_layout=True) == schema.DEFAULT_SOURCE_ID
    assert loader.infer_source_id("file.csv", flat_layout=False) == schema.DEFAULT_SOURCE_ID


def test_read_csv_files_to_df_via_data_loading(tmp_path):
    csv_dir = tmp_path / "csv_files"
    csv_dir.mkdir()
    _write_csv(csv_dir / "one.csv", [_base_row()])

    df = data_loading.read_csv_files_to_df(base_dir=tmp_path)

    assert len(df) == 1
    assert df.iloc[0][schema.SOURCE_ID] == "n26"
