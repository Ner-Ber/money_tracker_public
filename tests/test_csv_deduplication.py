"""Tests for deduplicating overlapping CSV exports."""

from __future__ import annotations

import pandas as pd
import pytest

from money_tracker import data_loading

_DEDUP_KEY = list(data_loading._TRANSACTION_DEDUP_COLUMNS)


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


def _csv_dir(tmp_path):
    csv_dir = tmp_path / "csv_files"
    csv_dir.mkdir()
    return csv_dir


def _load_csvs(tmp_path):
    return data_loading.read_csv_files_to_df(base_dir=tmp_path)


def _assert_no_dedup_key_duplicates(df):
    cols = [c for c in _DEDUP_KEY if c in df.columns]
    assert not df.duplicated(subset=cols, keep=False).any()


def test_dedupe_transaction_rows_empty_dataframe():
    result = data_loading._dedupe_transaction_rows(pd.DataFrame())
    assert result.empty


def test_dedupe_transaction_rows_no_dedup_columns():
    df = pd.DataFrame({"Partner Name": ["A"], "Amount (EUR)": [-1.0]})
    result = data_loading._dedupe_transaction_rows(df)
    assert len(result) == 1


@pytest.mark.parametrize("copies", [2, 3, 5, 10])
def test_dedupe_transaction_rows_collapses_n_identical_copies(copies):
    df = pd.DataFrame([_base_row()] * copies)
    result = data_loading._dedupe_transaction_rows(df)
    assert len(result) == 1


@pytest.mark.parametrize("num_files", [2, 3, 4, 7])
def test_identical_transaction_in_any_number_of_files_dedupes_to_one(tmp_path, num_files):
    csv_dir = _csv_dir(tmp_path)
    row = _base_row(**{"Payment Reference": "shared-tx"})
    for i in range(num_files):
        _write_csv(csv_dir / f"export_{i:02d}.csv", [row])

    df = _load_csvs(tmp_path)

    assert len(df) == 1
    _assert_no_dedup_key_duplicates(df)


@pytest.mark.parametrize("num_files", [2, 3, 5])
def test_multiple_distinct_transactions_repeated_across_files(tmp_path, num_files):
    csv_dir = _csv_dir(tmp_path)
    rows = [
        _base_row(
            **{
                "Partner Name": f"Partner {i}",
                "Payment Reference": f"tx-{i}",
                "Amount (EUR)": float(-10 - i),
            }
        )
        for i in range(4)
    ]
    for f in range(num_files):
        _write_csv(csv_dir / f"batch_{f}.csv", rows)

    df = _load_csvs(tmp_path)

    assert len(df) == len(rows)
    _assert_no_dedup_key_duplicates(df)


def test_dedupes_when_duplicate_appears_in_arbitrary_file_subset(tmp_path):
    """Same transaction may repeat in any subset of source files, not necessarily all."""
    csv_dir = _csv_dir(tmp_path)
    shared = _base_row(**{"Payment Reference": "shared"})
    only_in_a = _base_row(**{"Partner Name": "Partner B", "Payment Reference": "only-a"})
    in_b_and_c = _base_row(**{"Partner Name": "Partner C", "Payment Reference": "bc"})
    only_in_d = _base_row(**{"Partner Name": "Partner D", "Payment Reference": "only-d"})

    _write_csv(csv_dir / "a.csv", [shared, only_in_a])
    _write_csv(csv_dir / "b.csv", [in_b_and_c])
    _write_csv(csv_dir / "c.csv", [shared, in_b_and_c])
    _write_csv(csv_dir / "d.csv", [only_in_d])
    _write_csv(csv_dir / "e.csv", [shared])

    df = _load_csvs(tmp_path)

    assert len(df) == 4
    _assert_no_dedup_key_duplicates(df)


def test_keeps_first_occurrence_when_deduplicating_across_files(tmp_path):
    csv_dir = _csv_dir(tmp_path)
    first = _base_row()
    first["_source"] = "first-file"
    second = _base_row()
    second["_source"] = "second-file"
    _write_csv(csv_dir / "aaa.csv", [first])
    _write_csv(csv_dir / "bbb.csv", [second])

    df = _load_csvs(tmp_path)

    assert len(df) == 1
    assert df.iloc[0]["_source"] == "first-file"


def test_preserves_distinct_transactions_that_share_partner_date_and_amount(tmp_path):
    """Different payment references on the same day are separate transactions."""
    csv_dir = _csv_dir(tmp_path)
    shared = {
        "Partner Name": "Vendor X",
        "Booking Date": "2025-02-07",
        "Value Date": "2025-02-07",
        "Amount (EUR)": -85.7,
        "Original Amount": -85.7,
        "Type": "Direct Debit",
    }
    _write_csv(
        csv_dir / "bank.csv",
        [
            _base_row(**shared, **{"Payment Reference": "invoice-101"}),
            _base_row(**shared, **{"Payment Reference": "invoice-102"}),
        ],
    )

    df = _load_csvs(tmp_path)

    assert len(df) == 2
    assert set(df["Payment Reference"]) == {"invoice-101", "invoice-102"}


def test_preserves_distinct_transactions_with_same_booking_date_but_different_value_date(
    tmp_path,
):
    csv_dir = _csv_dir(tmp_path)
    shared = {
        "Partner Name": "Transit Co",
        "Booking Date": "2025-04-14",
        "Amount (EUR)": -3.8,
        "Original Amount": -3.8,
        "Payment Reference": "",
        "Type": "Presentment",
    }
    _write_csv(
        csv_dir / "bank.csv",
        [
            _base_row(**shared, **{"Value Date": "2025-04-13"}),
            _base_row(**shared, **{"Value Date": "2025-04-14"}),
        ],
    )

    df = _load_csvs(tmp_path)

    assert len(df) == 2


def test_mixed_unique_and_overlapping_rows_across_many_files(tmp_path):
    csv_dir = _csv_dir(tmp_path)
    overlap_a = _base_row(**{"Payment Reference": "overlap-a"})
    overlap_b = _base_row(**{"Partner Name": "Partner B", "Payment Reference": "overlap-b"})
    unique_rows = [
        _base_row(**{"Partner Name": f"Unique {i}", "Payment Reference": f"unique-{i}"})
        for i in range(3)
    ]

    _write_csv(csv_dir / "01.csv", [overlap_a, unique_rows[0]])
    _write_csv(csv_dir / "02.csv", [overlap_a, overlap_b, unique_rows[1]])
    _write_csv(csv_dir / "03.csv", [overlap_b, unique_rows[2]])
    _write_csv(csv_dir / "04.csv", [overlap_a])
    _write_csv(csv_dir / "05.csv", [unique_rows[0], unique_rows[2]])

    df = _load_csvs(tmp_path)

    # 2 overlapping + 3 unique partners
    assert len(df) == 5
    _assert_no_dedup_key_duplicates(df)


def test_run_pipeline_applies_deduplication(tmp_path):
    csv_dir = _csv_dir(tmp_path)
    (tmp_path / "category_mapping.txt").write_text("", encoding="utf-8")
    (tmp_path / "mappings.txt").write_text("", encoding="utf-8")
    row = _base_row(**{"Payment Reference": "pipeline-tx"})
    for name in ("source_a.csv", "source_b.csv", "source_c.csv"):
        _write_csv(csv_dir / name, [row])

    result = data_loading.run_pipeline(base_dir=tmp_path)

    assert len(result) == 1
    assert not result.duplicated(
        subset=["Partner Name", "Booking Date", "Amount (EUR) converted", "Currency"],
        keep=False,
    ).any()
