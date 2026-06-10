"""Map bank-native DataFrames to the canonical transaction schema."""

from __future__ import annotations

import pandas as pd

from money_tracker.sources import schema


def to_canonical(
    df: pd.DataFrame,
    *,
    source_id: str,
    source_file: str,
) -> pd.DataFrame:
    """
    Ensure canonical columns exist and attach provenance.

    Readers that already match N26 shape pass through; missing optional columns
  are added as empty/NaN.
    """
    if df.empty:
        out = pd.DataFrame(columns=list(schema.CANONICAL_COLUMNS) + list(schema.PROVENANCE_COLUMNS))
        return out

    out = df.copy()
    for col in schema.CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA

    missing = [
        col
        for col in schema.REQUIRED_FOR_PIPELINE
        if col not in out.columns or out[col].notna().sum() == 0
    ]
    if missing:
        raise ValueError(
            f"Missing required column(s) for source '{source_id}' in {source_file}: "
            f"{', '.join(missing)}"
        )

    if schema.SOURCE_ID in out.columns and out[schema.SOURCE_ID].notna().any():
        out[schema.SOURCE_ID] = out[schema.SOURCE_ID].fillna(source_id)
    else:
        out[schema.SOURCE_ID] = source_id

    if schema.SOURCE_FILE in out.columns and out[schema.SOURCE_FILE].notna().any():
        out[schema.SOURCE_FILE] = out[schema.SOURCE_FILE].fillna(source_file)
    else:
        out[schema.SOURCE_FILE] = source_file
    return out
