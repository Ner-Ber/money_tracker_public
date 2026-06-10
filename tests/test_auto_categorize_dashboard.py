"""Tests for dashboard auto-categorize callback and category file persistence."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from money_tracker import data_loading
from money_tracker.test_support import reload_dashboard


def _mock_response(payload: dict):
    class _Response:
        text = json.dumps(payload)

    return _Response()


def _table_rows(*partners):
    return [{"Partner": p, "Category": ""} for p in partners]


def test_auto_categorize_without_api_key_shows_error(monkeypatch, tmp_project):
    dashboard = reload_dashboard(monkeypatch, tmp_project, api_key="")
    dashboard._genai_client = None

    table, badge, msg = dashboard.auto_categorize_missing(
        1, _table_rows("New Shop")
    )

    assert table is dashboard.no_update
    assert "No API key" in str(badge)


def test_auto_categorize_writes_category_file_and_refreshes_table(
    monkeypatch, tmp_project, mock_genai_client
):
    client = mock_genai_client
    client.models.generate_content = mock.Mock(
        return_value=_mock_response({"New Shop": "Groceries", "Cafe XY": "Cafe & Dine"})
    )
    dashboard = reload_dashboard(monkeypatch, tmp_project, genai_client=client)

    table_container, badge, _msg = dashboard.auto_categorize_missing(
        1,
        [
            {"Partner": "New Shop", "Category": ""},
            {"Partner": "Cafe XY", "Category": ""},
            {"Partner": "Existing Shop", "Category": "Household"},
        ],
    )

    mapping = dict(data_loading.read_category_mapping_file(base_dir=tmp_project))
    assert mapping["New Shop"] == "Groceries"
    assert mapping["Cafe XY"] == "Cafe & Dine"
    assert mapping.get("Existing Shop") == "Household"

    table = table_container[0]
    rows = {r["Partner"]: r["Category"] for r in table.data}
    assert rows["New Shop"] == "Groceries"
    assert rows["Cafe XY"] == "Cafe & Dine"
    assert "Done" in str(badge) or "categorized" in str(badge).lower()
    assert client.models.generate_content.call_count >= 1


def test_auto_categorize_api_failure_returns_error_badge(
    monkeypatch, tmp_project, mock_genai_client
):
    client = mock_genai_client
    client.models.generate_content = mock.Mock(side_effect=RuntimeError("quota exceeded"))
    dashboard = reload_dashboard(monkeypatch, tmp_project, genai_client=client)

    table_container, badge, _msg = dashboard.auto_categorize_missing(
        1, _table_rows("Lonely Shop")
    )

    mapping = dict(data_loading.read_category_mapping_file(base_dir=tmp_project))
    assert "Lonely Shop" not in mapping or not mapping.get("Lonely Shop")
    assert "Did not work" in str(badge) or "API" in str(badge)


def test_auto_categorize_batches_multiple_api_calls(monkeypatch, tmp_project, mock_genai_client):
    client = mock_genai_client
    partners = [f"Shop {i}" for i in range(5)]

    def batch_side_effect(**kwargs):
        contents = kwargs["contents"]
        out = {}
        for p in partners:
            if p in contents:
                out[p] = "Groceries"
        return _mock_response(out)

    client.models.generate_content = mock.Mock(side_effect=batch_side_effect)
    monkeypatch.setenv("GEMINI_BATCH_SIZE", "2")
    dashboard = reload_dashboard(monkeypatch, tmp_project, genai_client=client)

    dashboard.auto_categorize_missing(1, _table_rows(*partners))

    assert client.models.generate_content.call_count == 3


def test_auto_categorize_partial_save_on_mid_batch_failure(
    monkeypatch, tmp_project, mock_genai_client
):
    client = mock_genai_client
    call_n = {"n": 0}

    def flaky(**kwargs):
        call_n["n"] += 1
        if call_n["n"] == 1:
            return _mock_response({"First Shop": "Groceries"})
        raise RuntimeError("API busy")

    client.models.generate_content = mock.Mock(side_effect=flaky)
    monkeypatch.setenv("GEMINI_BATCH_SIZE", "1")
    dashboard = reload_dashboard(monkeypatch, tmp_project, genai_client=client)

    _table, badge, _msg = dashboard.auto_categorize_missing(
        1, _table_rows("First Shop", "Second Shop")
    )

    mapping = dict(data_loading.read_category_mapping_file(base_dir=tmp_project))
    assert mapping.get("First Shop") == "Groceries"
    assert "Partial" in str(badge) or "partial" in str(badge).lower()
