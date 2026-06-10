"""Shared fixtures for money_tracker tests."""

from __future__ import annotations

import pytest

from money_tracker.test_support import reload_dashboard


PERMITTED_CATEGORIES = """Groceries
Cafe & Dine
Transportation
Household
Other
"""


@pytest.fixture
def tmp_project(tmp_path):
    """Minimal project root with permitted_categories.txt."""
    (tmp_path / "permitted_categories.txt").write_text(
        PERMITTED_CATEGORIES, encoding="utf-8"
    )
    (tmp_path / "category_mapping.txt").write_text(
        "Existing Shop, Household\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def mock_genai_client():
    class _Models:
        def __init__(self):
            self.calls = []
            self.generate_content = None

    class _Client:
        def __init__(self):
            self.models = _Models()

    return _Client()


@pytest.fixture
def dashboard_module(monkeypatch, tmp_project, mock_genai_client):
    return reload_dashboard(monkeypatch, tmp_project, genai_client=mock_genai_client)
