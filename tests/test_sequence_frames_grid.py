"""Tests for sequence overview grid and expense modal."""

from __future__ import annotations

import pandas as pd

from money_tracker.test_support import reload_dashboard


def _walk(component):
    if hasattr(component, "children"):
        children = component.children
        if children is not None:
            if not isinstance(children, list):
                children = [children]
            for child in children:
                yield from _walk(child)
    yield component


def _count_datatables(component):
    from dash.dash_table import DataTable

    return sum(1 for node in _walk(component) if isinstance(node, DataTable))


def _find_by_id(layout, component_id):
    return [comp for comp in _walk(layout) if getattr(comp, "id", None) == component_id]


def test_seq_all_frames_uses_grid_without_expense_tables(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    sequences = [{"name": "Trip", "category": "Trips", "time_spans": [], "expense_indices": []}]
    df_base = pd.DataFrame(
        columns=["Booking Date", "Category", "Partner Name", "Amount (EUR)", "Index"]
    )

    content = dashboard._build_seq_all_frames_content(sequences, df_base)

    assert getattr(content, "className", "") == "mt-seq-grid"
    assert _count_datatables(content) == 0


def test_sequence_frame_modal_content_uses_large_table(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    sequences = [{"name": "Trip", "category": "Trips", "time_spans": [], "expense_indices": [0]}]
    df_base = pd.DataFrame(
        {
            "Booking Date": [pd.Timestamp("2025-06-01")],
            "Category": ["Trips"],
            "Partner Name": ["Shop"],
            "Amount (EUR)": [-10.0],
            "Index": [0],
        }
    )

    title, body = dashboard._build_sequence_frame_modal_content("Trip", df_base, sequences)

    assert title == "Expenses — Trip"
    tables = _count_datatables(body)
    assert tables == 1
    table_nodes = [n for n in _walk(body) if hasattr(n, "page_size")]
    assert table_nodes[0].page_size == dashboard._SEQ_FRAME_MODAL_TABLE_PAGE_SIZE


def test_seq_frame_modal_sequence_opens_and_closes(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    dashboard.callback_context = type(
        "Ctx",
        (),
        {
            "triggered_id": {"type": "seq-show-expenses", "index": "Trip"},
        },
    )()

    assert dashboard.seq_frame_modal_sequence([1], 0, True, dashboard._TAB_SEQUENCES) == "Trip"

    dashboard.callback_context = type(
        "Ctx",
        (),
        {"triggered_id": "seq-frame-modal-close"},
    )()
    assert dashboard.seq_frame_modal_sequence([1], 1, False, dashboard._TAB_SEQUENCES) is None


def test_layout_includes_sequence_expenses_modal(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    layout = dashboard.app.layout
    layout = layout() if callable(layout) else layout

    assert len(_find_by_id(layout, "seq-frame-expenses-modal")) == 1
