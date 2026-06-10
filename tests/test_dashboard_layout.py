"""Tests that dashboard layout embeds category mapping data for the UI."""

from __future__ import annotations

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


def _layout(dashboard):
    layout = dashboard.app.layout
    return layout() if callable(layout) else layout


def _find_by_id(layout, component_id):
    return [comp for comp in _walk(layout) if getattr(comp, "id", None) == component_id]


def test_layout_category_table_includes_mapping_rows(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)

    tables = _find_by_id(_layout(dashboard), "category-table")

    assert len(tables) == 1
    partners = {row.get("Partner") for row in tables[0].data}
    assert "Existing Shop" in partners


def test_layout_has_display_currency_selector(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    dropdowns = _find_by_id(_layout(dashboard), "display-currency")
    assert len(dropdowns) == 1


def test_layout_charts_tab_has_update_time_range_button(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    buttons = _find_by_id(_layout(dashboard), "btn-update-charts-range")
    assert len(buttons) == 1
    assert buttons[0].children == "Update time range"


def test_layout_charts_tab_has_initial_figures(monkeypatch, tmp_project):
    """Charts tab graphs must render on first paint, not only after callback."""
    dashboard = reload_dashboard(monkeypatch, tmp_project)

    for graph_id in ("bar-chart", "pie-chart", "cumulative-chart"):
        graphs = _find_by_id(_layout(dashboard), graph_id)
        assert len(graphs) == 1
        assert graphs[0].figure is not None
        assert graphs[0].style.get("height") == "450px"

    table_container = _find_by_id(_layout(dashboard), "expenses-table-container")
    assert len(table_container) == 1
    assert table_container[0].children is not None


def test_layout_has_assets_overview_tab(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)
    layout = _layout(dashboard)

    tabs = [comp for comp in _walk(layout) if getattr(comp, "id", None) == "main-tabs"]
    assert len(tabs) == 1
    tab_labels = [child.label for child in tabs[0].children if hasattr(child, "label")]
    assert tab_labels == [
        "Assets Overview",
        "Expenses",
        "Sequences",
        "Data & Mappings",
    ]

    for component_id in (
        "assets-total-summary",
        "assets-total-chart",
        "assets-grid",
        "assets-display-currency",
        "btn-assets-refresh",
        "btn-add-asset",
        "asset-add-modal",
        "asset-card-messages",
    ):
        found = _find_by_id(layout, component_id)
        assert len(found) == 1, f"missing {component_id}"


def test_sequence_edit_panel_has_checked_expense_controls(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project)

    for button_id in ("btn-add-checked", "btn-remove-checked"):
        buttons = _find_by_id(_layout(dashboard), button_id)
        assert len(buttons) == 1

    msg = _find_by_id(_layout(dashboard), "seq-checked-msg")
    assert len(msg) == 1

    modals = _find_by_id(_layout(dashboard), "seq-add-modal")
    assert len(modals) == 0

    revision = _find_by_id(_layout(dashboard), "seq-revision")
    assert len(revision) == 1

    tabs = _find_by_id(_layout(dashboard), "main-tabs")
    assert len(tabs) == 1
    assert tabs[0].value == dashboard._TAB_ASSETS
