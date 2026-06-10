"""Convert transaction amounts into a common display currency for charts."""

from __future__ import annotations

import json
import os
from typing import Mapping

import numpy as np
import pandas as pd

# EUR value of one unit of each currency (multiply native amount to get EUR).
_DEFAULT_TO_EUR: Mapping[str, float] = {
    "EUR": 1.0,
    "ILS": 0.255,
    "GBP": 1.17,
    "USD": 0.92,
    "CHF": 1.05,
    "CZK": 0.041,
    "ALL": 0.0085,
}

_AMOUNT_COL_PREFIX = "Amount ("


_CURRENCY_ALIASES = {
    "EU": "EUR",
    "GB": "GBP",
    "$": "USD",
}


def normalize_currency(code) -> str:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return "EUR"
    text = str(code).strip().upper()
    if not text:
        return "EUR"
    return _CURRENCY_ALIASES.get(text, text)


def amount_column_name(currency_code: str) -> str:
    return f"{_AMOUNT_COL_PREFIX}{normalize_currency(currency_code)})"


def amount_axis_label(currency_code: str) -> str:
    return f"Amount ({normalize_currency(currency_code)})"


def cumulative_axis_label(currency_code: str) -> str:
    return f"Cumulative amount ({normalize_currency(currency_code)})"


def load_to_eur_rates(base_dir: str | None = None) -> dict[str, float]:
    """Load EUR-per-unit rates from exchange_rates.json in base_dir, else defaults."""
    rates = dict(_DEFAULT_TO_EUR)
    if not base_dir:
        return rates
    path = os.path.join(os.path.abspath(base_dir), "exchange_rates.json")
    if not os.path.isfile(path):
        return rates
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    for code, value in payload.get("to_eur", payload.get("rates", {})).items():
        rates[normalize_currency(code)] = float(value)
    rates["EUR"] = 1.0
    return rates


def relevant_currencies(df: pd.DataFrame) -> list[str]:
    if df.empty or "Currency" not in df.columns:
        return ["EUR"]
    codes = {normalize_currency(c) for c in df["Currency"].dropna().unique()}
    codes.add("EUR")
    return sorted(codes)


def signed_native_amount(
    amount_signed: pd.Series,
    original_amount: pd.Series | None,
) -> pd.Series:
    """Signed amount in the transaction's original currency."""
    signed = pd.to_numeric(amount_signed, errors="coerce")
    if original_amount is None:
        return signed
    original = pd.to_numeric(original_amount, errors="coerce")
    sign = np.sign(signed.fillna(0))
    use_original = original.notna() & (original != 0)
    native = signed.where(~use_original, sign * original.abs())
    return native


def _amount_in_eur(
    currency: pd.Series,
    signed_native: pd.Series,
    bank_amount: pd.Series,
    exchange_rate: pd.Series | None,
    to_eur: Mapping[str, float],
) -> pd.Series:
    ccy = currency.map(normalize_currency)
    rate_series = ccy.map(lambda code: to_eur.get(code, to_eur.get("EUR", 1.0)))
    converted = signed_native * rate_series

    if exchange_rate is None:
        return converted

    ex = pd.to_numeric(exchange_rate, errors="coerce")
    use_bank_eur = (ccy != "EUR") & (ccy != "ILS") & ex.notna() & (ex != 0)
    bank = pd.to_numeric(bank_amount, errors="coerce")
    return bank.where(use_bank_eur, converted)


def add_display_amount_columns(df: pd.DataFrame, base_dir: str | None = None) -> pd.DataFrame:
    """
    Add Amount (EUR), Amount (ILS), … columns with consistent cross-currency conversion.

    Uses N26 bank EUR amounts when Exchange Rate is present; otherwise converts from
    native currency using exchange_rates.json or built-in defaults.
    """
    if df.empty:
        return df

    out = df.copy()
    out["Currency"] = out["Currency"].map(normalize_currency)
    signed_native = signed_native_amount(
        out["Amount (EUR)"],
        out["Original Amount"] if "Original Amount" in out.columns else None,
    )
    to_eur = load_to_eur_rates(base_dir)
    exchange = out["Exchange Rate"] if "Exchange Rate" in out.columns else None
    eur_amounts = _amount_in_eur(
        out["Currency"],
        signed_native,
        out["Amount (EUR)"],
        exchange,
        to_eur,
    )

    for code in relevant_currencies(out):
        rate = to_eur.get(code, to_eur.get("EUR", 1.0))
        if rate <= 0:
            rate = 1.0
        out[amount_column_name(code)] = eur_amounts / rate

    eur_col = amount_column_name("EUR")
    out["Amount (EUR) converted"] = out[eur_col]
    return out


def pick_amount_column(df: pd.DataFrame, display_currency: str) -> str:
    col = amount_column_name(display_currency)
    if col in df.columns:
        return col
    if "Amount (EUR) converted" in df.columns:
        return "Amount (EUR) converted"
    return amount_column_name("EUR")
