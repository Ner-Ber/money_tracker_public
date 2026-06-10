"""N26 CSV export reader."""

from __future__ import annotations

import pandas as pd

from money_tracker.sources.readers import base


class N26Reader(base.BankReader):
    """N26 comma-separated export (European decimal, UTF-8)."""

    reader_id = "n26"

    def read(self, path: str) -> pd.DataFrame:
        return pd.read_csv(path)
