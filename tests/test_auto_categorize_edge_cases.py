"""Edge-case tests for auto-categorize callback."""

from __future__ import annotations

import json
from unittest import mock

from money_tracker.test_support import reload_dashboard


def _mock_response(payload: dict):
    class _Response:
        text = json.dumps(payload)

    return _Response()


def test_auto_categorize_all_rows_categorized_shows_idle(monkeypatch, tmp_project, mock_genai_client):
    dashboard = reload_dashboard(monkeypatch, tmp_project, genai_client=mock_genai_client)
    mock_genai_client.models.generate_content = mock.Mock()

    table, badge, _msg = dashboard.auto_categorize_missing(
        1,
        [{"Partner": "Shop", "Category": "Groceries"}],
    )

    assert table is dashboard.no_update
    assert "Nothing to do" in str(badge)
    mock_genai_client.models.generate_content.assert_not_called()


def test_auto_categorize_missing_permitted_categories_file(monkeypatch, tmp_path, mock_genai_client):
    dashboard = reload_dashboard(monkeypatch, tmp_path, genai_client=mock_genai_client)

    table, badge, _msg = dashboard.auto_categorize_missing(
        1,
        [{"Partner": "Shop", "Category": ""}],
    )

    assert table is dashboard.no_update
    assert "permitted_categories" in str(badge).lower()
