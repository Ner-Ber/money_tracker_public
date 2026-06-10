"""Charts tab pill filters for source and transaction currency."""

from __future__ import annotations

import pandas as pd

from money_tracker import dashboard


def test_filter_df_by_source_and_currency():
    df = pd.DataFrame(
        {
            "Booking Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "Category": ["Food", "Travel"],
            "Amount (EUR)": [-10.0, -20.0],
            "Source": ["N26", "Hapoalim"],
            "Currency": ["EUR", "ILS"],
        }
    )
    filtered, _cat_col = dashboard._filter_df(
        df,
        sources=["N26"],
        currencies=["EUR"],
    )
    assert len(filtered) == 1
    assert filtered.iloc[0]["Source"] == "N26"
    assert filtered.iloc[0]["Currency"] == "EUR"


def test_active_pill_filter_none_when_all_selected():
    assert dashboard._active_pill_filter(["N26", "Hapoalim"], ["N26", "Hapoalim"]) is None
    assert dashboard._active_pill_filter([], ["EUR"]) is None


def test_active_pill_filter_subset():
    assert dashboard._active_pill_filter(["N26"], ["N26", "Hapoalim"]) == ["N26"]
