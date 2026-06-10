"""Sequences tab loads only when selected; charts tab skips heavy callbacks."""

from __future__ import annotations

import importlib
import sys

import pandas as pd
import pytest
from dash.exceptions import PreventUpdate

from money_tracker import sequences
from money_tracker.test_support import reload_dashboard


def _reload_dashboard_for_sequences(monkeypatch, tmp_path):
    empty_df = pd.DataFrame(
        columns=["Booking Date", "Category", "Partner Name", "Amount (EUR)"]
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("money_tracker.data_loading.run_pipeline", lambda *a, **k: empty_df)
    monkeypatch.setattr(
        "money_tracker.data_loading.get_base_dir",
        lambda base_dir=None: str(tmp_path),
    )
    if "money_tracker.dashboard" in sys.modules:
        del sys.modules["money_tracker.dashboard"]
    import money_tracker.dashboard as dashboard

    importlib.reload(dashboard)
    monkeypatch.setattr(
        "money_tracker.dashboard.load_sequences",
        lambda: sequences.load_sequences(base_dir=str(tmp_path)),
    )
    dashboard._pipeline_df_cache = None
    dashboard._pipeline_cache_key_val = None
    return dashboard


def test_seq_all_frames_skipped_on_charts_tab(monkeypatch, tmp_path):
    (tmp_path / "csv_files").mkdir()
    (tmp_path / "mappings.txt").write_text("", encoding="utf-8")
    (tmp_path / "sequences.json").write_text('{"sequences":[]}', encoding="utf-8")

    dash = reload_dashboard(monkeypatch, tmp_path)
    with pytest.raises(PreventUpdate):
        dash.update_seq_all_frames(dash._TAB_CHARTS, 0)


def test_seq_all_frames_loads_on_sequences_tab(monkeypatch, tmp_path):
    (tmp_path / "csv_files").mkdir()
    (tmp_path / "csv_files" / "a.csv").write_text(
        "Partner Name,Amount (EUR),Booking Date,Original Currency,Category\n"
        "Shop,-10.00,2025-06-01,EUR,Groceries\n",
        encoding="utf-8",
    )
    (tmp_path / "mappings.txt").write_text("", encoding="utf-8")
    (tmp_path / "category_mapping.txt").write_text("Shop,Groceries\n", encoding="utf-8")
    (tmp_path / "sequences.json").write_text(
        '{"sequences":[{"name":"Trip","category":"Trips","time_spans":[],"expense_indices":[0],"exclude_indices":[]}]}',
        encoding="utf-8",
    )

    dash = _reload_dashboard_for_sequences(monkeypatch, tmp_path)
    result = dash.update_seq_all_frames(dash._TAB_SEQUENCES, 0)
    assert "Trip" in str(result)


def test_seq_edit_panel_skips_full_table_without_selection(monkeypatch, tmp_path):
    dash = reload_dashboard(monkeypatch, tmp_path)
    with pytest.raises(PreventUpdate):
        dash.update_seq_edit_panel(dash._TAB_CHARTS, None, 0)

    panel = dash.update_seq_edit_panel(dash._TAB_SEQUENCES, None, 0)
    text = str(panel)
    assert "Select a sequence above" in text
    assert "seq-edit-expenses-table" not in text
