"""Tests for the N26 bank reader and normalizer."""

from __future__ import annotations

import pandas as pd
import pytest

from money_tracker.sources import normalize
from money_tracker.sources import schema
from money_tracker.sources.readers import n26 as n26_reader
from money_tracker.sources.readers import unknown as unknown_reader


def _base_row(**overrides):
    row = {
        "Booking Date": "2025-09-10",
        "Value Date": "2025-09-10",
        "Partner Name": "Partner A",
        "Type": "Presentment",
        "Payment Reference": "ref-1",
        "Account Name": "Main",
        "Amount (EUR)": -12.5,
        "Original Currency": "EUR",
    }
    row.update(overrides)
    return row


def test_n26_reader_roundtrip(tmp_path):
    path = tmp_path / "n26.csv"
    pd.DataFrame([_base_row()]).to_csv(path, index=False)

    raw = n26_reader.N26Reader().read(str(path))
    canonical = normalize.to_canonical(
        raw, source_id="n26", source_file="n26.csv"
    )

    assert canonical.iloc[0]["Partner Name"] == "Partner A"
    assert canonical.iloc[0][schema.SOURCE_ID] == "n26"


def test_normalize_requires_partner_name(tmp_path):
    raw = pd.DataFrame([{"Booking Date": "2025-01-01", "Amount (EUR)": -1.0}])
    with pytest.raises(ValueError, match="Partner Name"):
        normalize.to_canonical(raw, source_id="n26", source_file="bad.csv")


def test_unknown_reader_raises():
    with pytest.raises(unknown_reader.UnknownFormatError):
        unknown_reader.UnknownReader().read("/no/such/file.csv")
