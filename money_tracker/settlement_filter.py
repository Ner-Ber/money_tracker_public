"""Card/bank settlement deduplication (stub for public template).

Add institution-specific settlement logic here when you wire credit-card
sources to checking-account exports.
"""

from __future__ import annotations

import pandas as pd

SETTLEMENT_EXCLUDED_COL = "settlement_excluded"


def mark_card_settlements(df: pd.DataFrame) -> pd.DataFrame:
    """Return df unchanged; public template does not dedupe settlements."""
    if df.empty:
        return df
    out = df.copy()
    out[SETTLEMENT_EXCLUDED_COL] = False
    return out
