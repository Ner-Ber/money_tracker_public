"""Dashboard file list: tab switch and refresh re-scan csv_files/."""

from __future__ import annotations

import json

import pytest

from money_tracker.test_support import reload_dashboard


def _files_list_callback_response(app, *, n_clicks=None, tab="tab-data"):
    with app.server.test_client() as client:
        client.get("/")
        deps = client.get("/_dash-dependencies").json
        dep = next(
            spec
            for spec in deps
            if any(item.get("id") == "files-refresh" for item in spec.get("inputs", []))
            and any(item.get("id") == "main-tabs" for item in spec.get("inputs", []))
        )
        inputs = [
            {"id": "files-refresh", "property": "n_clicks", "value": n_clicks},
            {"id": "main-tabs", "property": "value", "value": tab},
        ]
        changed = [f"{item['id']}.{item['property']}" for item in inputs]
        body = {
            "output": dep["output"],
            "outputs": [
                {"id": "files-list", "property": "children"},
                {"id": "files-base-dir", "property": "children"},
            ],
            "inputs": inputs,
            "state": [],
            "changedPropIds": changed,
        }
        response = client.post(
            "/_dash-update-component",
            json=body,
            content_type="application/json",
        )
    assert response.status_code in (200, 204), response.get_data(as_text=True)
    if response.status_code == 204:
        return {}
    return response.get_json()


def test_files_list_skipped_on_charts_tab(tmp_path, monkeypatch):
    (tmp_path / "csv_files").mkdir()
    (tmp_path / "csv_files" / "only.csv").write_text("x\n", encoding="utf-8")
    (tmp_path / "mappings.txt").write_text("", encoding="utf-8")

    dash = reload_dashboard(monkeypatch, tmp_path)
    payload = _files_list_callback_response(dash.app, tab="tab-charts")
    assert payload == {}


def test_files_list_refresh_picks_up_new_csv(tmp_path, monkeypatch):
    csv_dir = tmp_path / "csv_files"
    csv_dir.mkdir()
    (csv_dir / "a.csv").write_text("x\n", encoding="utf-8")
    (tmp_path / "mappings.txt").write_text("", encoding="utf-8")

    dash = reload_dashboard(monkeypatch, tmp_path)
    first = _files_list_callback_response(dash.app, n_clicks=1, tab="tab-data")
    first_text = json.dumps(first)
    assert "csv_files/a.csv" in first_text

    (csv_dir / "b.csv").write_text("y\n", encoding="utf-8")
    second = _files_list_callback_response(dash.app, n_clicks=2, tab="tab-data")
    second_text = json.dumps(second)
    assert "csv_files/b.csv" in second_text
