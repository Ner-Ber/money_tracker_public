"""Tests for single-asset report ingest."""

from __future__ import annotations

import pytest

from money_tracker.assets import engine
from money_tracker.assets.parsers import registry


@pytest.fixture
def demo_pdf_parser(monkeypatch):
    monkeypatch.setitem(registry.PARSERS, "demo_statement_pdf", lambda _path: None)
    monkeypatch.setitem(registry.PARSER_EXTENSIONS, "demo_statement_pdf", frozenset({".pdf"}))
    monkeypatch.setitem(registry.PARSER_LABELS, "demo_statement_pdf", "Demo statement (PDF)")


def test_ingest_report_wrong_format(tmp_path, monkeypatch, demo_pdf_parser):
    monkeypatch.setattr(
        "money_tracker.assets.config.load_assets",
        lambda base_dir=None: [{
            "id": "demo_checking",
            "parser": "demo_statement_pdf",
            "currency": "EUR",
        }],
    )
    bad = tmp_path / "bad.txt"
    bad.write_text("not a report", encoding="utf-8")
    result = engine.ingest_report_for_asset("demo_checking", str(bad), base_dir=str(tmp_path))
    assert result["ok"] is False
    assert "Wrong file type" in result["message"]


def test_ingest_report_format_mismatch(tmp_path, monkeypatch, demo_pdf_parser):
    monkeypatch.setattr(
        "money_tracker.assets.config.load_assets",
        lambda base_dir=None: [{
            "id": "demo_checking",
            "parser": "demo_statement_pdf",
            "currency": "EUR",
        }],
    )
    pdf = tmp_path / "fake.pdf"
    pdf.write_text("%PDF-1.4", encoding="utf-8")
    result = engine.ingest_report_for_asset("demo_checking", str(pdf), base_dir=str(tmp_path))
    assert result["ok"] is False
    assert "does not match" in result["message"]
