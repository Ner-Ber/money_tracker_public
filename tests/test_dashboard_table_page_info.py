"""Tests for scroll-viewport range labels on dashboard expense tables."""

from __future__ import annotations


def test_format_expenses_table_viewport_info_shows_date_range():
    from money_tracker import dashboard

    rows = [
        {"Booking Date": "2025-03-01"},
        {"Booking Date": "2025-01-15"},
    ]
    assert dashboard._format_expenses_table_page_info(rows) == (
        "Dates in view: 2025-01-15 – 2025-03-01"
    )


def test_format_expenses_table_viewport_info_single_date():
    from money_tracker import dashboard

    rows = [{"Booking Date": "2025-06-01"}]
    assert dashboard._format_expenses_table_page_info(rows) == (
        "Dates in view: 2025-06-01"
    )


def test_format_seq_expenses_table_viewport_info_shows_dates_and_indexes():
    from money_tracker import dashboard

    rows = [
        {"Booking Date": "2025-03-01", "Index": 12},
        {"Booking Date": "2025-01-15", "Index": 5},
    ]
    text = dashboard._format_seq_expenses_table_page_info(rows)
    assert text == (
        "Dates in view: 2025-01-15 – 2025-03-01 · Indexes in view: 5 – 12"
    )


def test_format_seq_expenses_table_viewport_info_single_row():
    from money_tracker import dashboard

    rows = [{"Booking Date": "2025-06-01", "Index": 7}]
    assert dashboard._format_seq_expenses_table_page_info(rows) == (
        "Dates in view: 2025-06-01 · Indexes in view: 7"
    )


def _walk(component):
    if hasattr(component, "children"):
        children = component.children
        if children is not None:
            if not isinstance(children, list):
                children = [children]
            for child in children:
                yield from _walk(child)
    yield component


def _find_by_id(layout, component_id):
    return [comp for comp in _walk(layout) if getattr(comp, "id", None) == component_id]


def test_build_expenses_table_uses_scroll_viewport_panel():
    import pandas as pd

    from money_tracker import dashboard

    filtered = pd.DataFrame(
        {
            "Partner Name": ["Shop"],
            "Booking Date": pd.to_datetime(["2025-01-15"]),
            "Currency": ["EUR"],
            "Category": ["Groceries"],
            "Amount (EUR) converted": [-10.0],
        }
    )
    component = dashboard._build_expenses_table(filtered, "Category")

    assert len(_find_by_id(component, "expenses-table-scroll")) == 1
    assert len(_find_by_id(component, "expenses-table-viewport-info")) == 1
    assert _find_by_id(component, "expenses-table")[0].page_action == "none"
