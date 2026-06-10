"""Tests for offline category suggestion (no LLM)."""

from __future__ import annotations

from money_tracker.test_support import reload_dashboard


def test_suggest_categories_offline_exact_and_substring_match():
    from money_tracker.dashboard import _suggest_categories_offline

    data = [
        {"Partner": "REWE Leipzig Plagwitz", "Category": "Groceries"},
        {"Partner": "REWE", "Category": ""},
        {"Partner": "Totally Different GmbH", "Category": ""},
    ]
    updated, filled = _suggest_categories_offline(data)

    by_partner = {r["Partner"]: r["Category"] for r in updated}
    assert filled == 1
    assert by_partner["REWE"] == "Groceries"
    assert by_partner["Totally Different GmbH"] == ""


def test_suggest_categories_offline_prefers_longer_substring_match():
    from money_tracker.dashboard import _suggest_categories_offline

    data = [
        {"Partner": "ARAL", "Category": "Transportation"},
        {"Partner": "ARAL Tankstelle Leipzig", "Category": "Household"},
        {"Partner": "ARAL Tankstelle", "Category": ""},
    ]
    updated, filled = _suggest_categories_offline(data)

    by_partner = {r["Partner"]: r["Category"] for r in updated}
    assert filled == 1
    assert by_partner["ARAL Tankstelle"] == "Household"


def test_suggest_categories_offline_empty_data():
    from money_tracker.dashboard import _suggest_categories_offline

    updated, filled = _suggest_categories_offline([])
    assert updated == []
    assert filled == 0


def test_suggest_offline_callback_updates_table_without_writing_file(
    monkeypatch, tmp_project
):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    data = [
        {"Partner": "KAUFLAND Berlin", "Category": "Groceries"},
        {"Partner": "KAUFLAND", "Category": ""},
    ]

    table_container, msg = dashboard.suggest_offline(1, data)

    assert "Suggested 1" in msg
    rows = {r["Partner"]: r["Category"] for r in table_container[0].data}
    assert rows["KAUFLAND"] == "Groceries"

    from money_tracker import data_loading

    mapping = dict(data_loading.read_category_mapping_file(base_dir=tmp_project))
    assert "KAUFLAND" not in mapping or not mapping.get("KAUFLAND")


def test_suggest_offline_callback_no_match_returns_message(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)

    table, msg = dashboard.suggest_offline(
        1,
        [
            {"Partner": "Alpha", "Category": "Groceries"},
            {"Partner": "Beta", "Category": ""},
        ],
    )

    assert table is dashboard.no_update
    assert "No empty categories could be suggested" in msg
