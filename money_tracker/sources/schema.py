"""Canonical transaction columns shared by all bank readers."""

from __future__ import annotations

SOURCE_ID = "source_id"
SOURCE_FILE = "source_file"

DEFAULT_SOURCE_ID = "n26"

SOURCE_DISPLAY_NAMES = {
    "n26": "N26",
}


def source_display_name(source_id: str) -> str:
    """Human-readable label for dashboard tables."""
    key = str(source_id).strip().lower()
    if key.startswith("cal_"):
        return f"CAL {key[4:]}"
    return SOURCE_DISPLAY_NAMES.get(key, str(source_id))

# Bank-native / pipeline columns (N26 export is the reference shape).
CANONICAL_COLUMNS = (
    "Booking Date",
    "Value Date",
    "Partner Name",
    "Partner Iban",
    "Type",
    "Payment Reference",
    "Account Name",
    "Amount (EUR)",
    "Original Amount",
    "Original Currency",
    "Exchange Rate",
)

PROVENANCE_COLUMNS = (SOURCE_ID, SOURCE_FILE)

REQUIRED_FOR_PIPELINE = (
    "Partner Name",
    "Booking Date",
    "Amount (EUR)",
)
