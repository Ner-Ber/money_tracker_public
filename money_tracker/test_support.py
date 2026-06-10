"""Test helpers for loading the dashboard with patched dependencies."""

from __future__ import annotations

import importlib
import sys

import pandas as pd


def reload_dashboard(monkeypatch, tmp_path, genai_client=None, api_key="test-key"):
    empty_df = pd.DataFrame(
        columns=["Booking Date", "Category", "Partner Name", "Amount (EUR)"]
    )
    monkeypatch.delenv("MONEY_TRACKER_DATA_DIR", raising=False)
    monkeypatch.delenv("MONEY_TRACKER_CSV_DIR", raising=False)
    monkeypatch.delenv("MONEY_TRACKER_DATA_DIR_LOCAL", raising=False)
    monkeypatch.delenv("MONEY_TRACKER_CSV_DIR_LOCAL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", api_key)
    monkeypatch.setattr("money_tracker.data_loading.run_pipeline", lambda *a, **k: empty_df)
    monkeypatch.setattr("money_tracker.sequences.load_sequences", lambda: [])
    monkeypatch.setattr(
        "money_tracker.data_loading.get_base_dir",
        lambda base_dir=None: str(tmp_path),
    )
    if "money_tracker.dashboard" in sys.modules:
        del sys.modules["money_tracker.dashboard"]
    import money_tracker.dashboard as dashboard

    importlib.reload(dashboard)
    if genai_client is not None:
        dashboard._genai_client = genai_client
    return dashboard
