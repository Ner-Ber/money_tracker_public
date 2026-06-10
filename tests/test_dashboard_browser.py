"""Browser tests: category UI renders and updates via Dash HTTP callback API."""

from __future__ import annotations

import json
from unittest import mock

import pytest

pytest.importorskip("selenium")
pytest.importorskip("psutil")
pytest.importorskip("multiprocess")
pytest.importorskip("bs4")

from money_tracker import data_loading
from money_tracker.test_support import reload_dashboard


def _mock_response(payload: dict):
    class _Response:
        text = json.dumps(payload)

    return _Response()


@pytest.fixture
def browser_auto_cat_project(tmp_path):
    from constants import PERMITTED_CATEGORIES

    (tmp_path / "permitted_categories.txt").write_text(PERMITTED_CATEGORIES, encoding="utf-8")
    (tmp_path / "category_mapping.txt").write_text(
        "Browser Shop, \nExisting Shop, Household\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def browser_suggest_project(tmp_path):
    from constants import PERMITTED_CATEGORIES

    (tmp_path / "permitted_categories.txt").write_text(PERMITTED_CATEGORIES, encoding="utf-8")
    (tmp_path / "category_mapping.txt").write_text(
        "REWE Leipzig, Groceries\nREWE, \n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def patched_dashboard_auto(monkeypatch, browser_auto_cat_project, mock_genai_client):
    client = mock_genai_client
    client.models.generate_content = mock.Mock(
        return_value=_mock_response({"Browser Shop": "Groceries"})
    )
    return reload_dashboard(monkeypatch, browser_auto_cat_project, genai_client=client)


@pytest.fixture
def patched_dashboard_suggest(monkeypatch, browser_suggest_project, mock_genai_client):
    return reload_dashboard(monkeypatch, browser_suggest_project, genai_client=mock_genai_client)


@pytest.fixture
def dash_duo():
    from dash.testing.application_runners import ThreadedRunner
    from dash.testing.composite import DashComposite

    with DashComposite(ThreadedRunner(), browser="Chrome") as dc:
        yield dc


def _open_data_mappings_tab(dash_duo):
    dash_duo.wait_for_element("#main-container", timeout=15)
    for el in dash_duo.driver.find_elements("xpath", "//*[contains(text(), 'Data & Mappings')]"):
        el.click()
        break
    dash_duo.wait_for_element("#btn-auto-categorize", timeout=15)


_OUTPUTS_BY_BUTTON = {
    "btn-auto-categorize": [
        {"id": "category-table-container", "property": "children"},
        {"id": "category-auto-status", "property": "children"},
        {"id": "category-msg", "property": "children"},
    ],
    "btn-suggest-offline": [
        {"id": "category-table-container", "property": "children"},
        {"id": "category-msg", "property": "children"},
    ],
}


def _dispatch_dash_callback(app, button_id: str, *, input_values: dict, state_values: dict):
    """Invoke a Dash callback via the same HTTP API the browser uses."""
    with app.server.test_client() as client:
        client.get("/")
        deps = client.get("/_dash-dependencies").json
        dep = next(
            spec
            for spec in deps
            if any(item.get("id") == button_id for item in spec.get("inputs", []))
        )
        inputs = []
        for item in dep.get("inputs", []):
            inputs.append({
                "id": item["id"],
                "property": item["property"],
                "value": input_values[item["id"]],
            })
        state = []
        for item in dep.get("state", []):
            state.append({
                "id": item["id"],
                "property": item["property"],
                "value": state_values[item["id"]],
            })
        changed = [
            f"{item['id']}.{item['property']}"
            for item in dep.get("inputs", [])
            if item["id"] in input_values
        ]
        body = {
            "output": dep["output"],
            "outputs": _OUTPUTS_BY_BUTTON[button_id],
            "inputs": inputs,
            "state": state,
            "changedPropIds": changed,
        }
        response = client.post(
            "/_dash-update-component",
            json=body,
            content_type="application/json",
        )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_browser_data_mappings_tab_shows_uncategorized_partner(
    dash_duo, patched_dashboard_auto
):
    dash_duo.start_server(patched_dashboard_auto.app, debug=False, use_reloader=False)
    _open_data_mappings_tab(dash_duo)

    dash_duo.wait_for_contains_text("#category-table", "Browser Shop", timeout=15)
    table_text = dash_duo.find_element("#category-table").text
    assert "Existing Shop" in table_text
    assert "Auto-Categorize" in dash_duo.find_element("#btn-auto-categorize").text


def test_browser_auto_categorize_via_http_updates_file_and_response(
    patched_dashboard_auto, browser_auto_cat_project
):
    app = patched_dashboard_auto.app
    table_data = [
        {"Partner": "Browser Shop", "Category": ""},
        {"Partner": "Existing Shop", "Category": "Household"},
    ]
    response = _dispatch_dash_callback(
        app,
        "btn-auto-categorize",
        input_values={"btn-auto-categorize": 1},
        state_values={"category-table": table_data},
    )
    response_text = json.dumps(response)
    assert "Groceries" in response_text
    assert "Done" in response_text or "categorized" in response_text.lower()

    mapping = dict(data_loading.read_category_mapping_file(base_dir=browser_auto_cat_project))
    assert mapping.get("Browser Shop") == "Groceries"


def test_browser_suggest_offline_via_http_updates_table_not_file(
    patched_dashboard_suggest, browser_suggest_project
):
    app = patched_dashboard_suggest.app
    table_data = [
        {"Partner": "REWE Leipzig", "Category": "Groceries"},
        {"Partner": "REWE", "Category": ""},
    ]
    response = _dispatch_dash_callback(
        app,
        "btn-suggest-offline",
        input_values={"btn-suggest-offline": 1},
        state_values={"category-table": table_data},
    )
    assert "Suggested" in json.dumps(response)

    mapping = dict(data_loading.read_category_mapping_file(base_dir=browser_suggest_project))
    assert not mapping.get("REWE")
    assert "Groceries" in json.dumps(response)
