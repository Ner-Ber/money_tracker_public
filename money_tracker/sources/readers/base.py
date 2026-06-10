"""Abstract bank export reader."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BankReader(ABC):
    """Read one bank CSV file into a DataFrame (bank-native column names)."""

    reader_id: str = ""

    @abstractmethod
    def read(self, path: str) -> pd.DataFrame:
        """Load transactions from path."""
