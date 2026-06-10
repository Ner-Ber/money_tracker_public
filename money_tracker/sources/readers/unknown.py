"""Placeholder reader for sources without a defined format yet."""

from __future__ import annotations

import pandas as pd

from money_tracker.sources.readers import base


class UnknownFormatError(ValueError):
    """Raised when a CSV is assigned to a source with no reader implementation."""


class UnknownReader(base.BankReader):
    """Refuse to load until a bank-specific reader is registered."""

    reader_id = "unknown"

    def read(self, path: str) -> pd.DataFrame:
        raise UnknownFormatError(
            f"No reader is configured for '{path}'. "
            "Add a bank-specific reader under money_tracker/sources/readers/ "
            "and register it in sources.yaml (see sources.yaml.example)."
        )
