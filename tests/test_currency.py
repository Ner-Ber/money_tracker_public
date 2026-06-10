"""Tests for multi-currency amount conversion."""

from __future__ import annotations

import pandas as pd
import pytest

from money_tracker import currency


def test_amount_in_eur_uses_bank_column_for_n26_foreign():
    df = pd.DataFrame({
        "Amount (EUR)": [-50.0],
        "Original Amount": [43.0],
        "Currency": ["GBP"],
        "Exchange Rate": [1.16],
    })
    signed = currency.signed_native_amount(df["Amount (EUR)"], df["Original Amount"])
    eur = currency._amount_in_eur(
        df["Currency"], signed, df["Amount (EUR)"], df["Exchange Rate"], {"EUR": 1.0, "GBP": 1.17}
    )
    assert eur.iloc[0] == -50.0


def test_amount_in_eur_converts_ils_from_native():
    df = pd.DataFrame({
        "Amount (EUR)": [-1000.0],
        "Original Amount": [1000.0],
        "Currency": ["ILS"],
        "Exchange Rate": [pd.NA],
    })
    signed = currency.signed_native_amount(df["Amount (EUR)"], df["Original Amount"])
    eur = currency._amount_in_eur(
        df["Currency"], signed, df["Amount (EUR)"], df["Exchange Rate"],
        {"EUR": 1.0, "ILS": 0.25},
    )
    assert eur.iloc[0] == pytest.approx(-250.0)


def test_add_display_amount_columns_adds_ils_and_eur():
    df = pd.DataFrame({
        "Partner Name": ["A", "B"],
        "Amount (EUR)": [-100.0, -10.0],
        "Original Amount": [100.0, 10.0],
        "Currency": ["ILS", "EUR"],
        "Booking Date": pd.to_datetime(["2024-06-01", "2024-06-02"]),
        "Category": [pd.NA, pd.NA],
    })
    out = currency.add_display_amount_columns(df)
    assert "Amount (ILS)" in out.columns
    assert "Amount (EUR)" in out.columns
    assert out.loc[1, "Amount (EUR)"] == -10.0
    assert out.loc[0, "Amount (ILS)"] == pytest.approx(-100.0)
