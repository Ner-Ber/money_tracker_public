"""Tests for PDF/HTML report generation and email delivery."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from money_tracker import reporting
from money_tracker.sequences import load_sequences, save_sequences


def _sample_expense_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Partner Name": ["Shop A", "Shop B", "Shop C", "Shop D", "Shop E"],
        "Booking Date": pd.to_datetime([
            "2026-05-05", "2026-05-12", "2026-04-20",
            "2026-06-01", "2026-03-01",
        ]),
        "Category": ["Groceries", "Transportation", "Cafe & Dine", "Household", "Other"],
        "Amount (EUR)": [50.0, 20.0, 15.0, 100.0, 5.0],
        "Currency": ["EUR"] * 5,
        "is_settlement_excluded": [False] * 5,
    })


def _write_sequences(tmp_path, names: list[str], indices: list[int]) -> None:
    sequences = [
        {
            "name": n,
            "category": "Household",
            "time_spans": [],
            "expense_indices": [idx],
            "exclude_indices": [],
        }
        for n, idx in zip(names, indices)
    ]
    save_sequences(sequences, base_dir=str(tmp_path), allow_write=True)


def test_report_email_subject(tmp_path, monkeypatch):
    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr(
        "money_tracker.assets.engine.build_overview",
        lambda **kwargs: {"total": 0, "checking_total": 0, "savings_total": 0, "as_of": None, "assets": [], "total_history": []},
    )
    ctx = reporting.build_report_context(
        display_currency="EUR",
        base_dir=str(tmp_path),
        df=_sample_expense_df(),
        reference_date=pd.Timestamp("2026-06-09"),
    )
    assert reporting.report_email_subject(ctx) == "Money Tracker Report for May 2026"


def test_last_calendar_month_range():
    start, end = reporting.last_calendar_month_range(pd.Timestamp("2026-06-09"))
    assert start == pd.Timestamp("2026-05-01")
    assert end == pd.Timestamp("2026-05-31")


def test_newest_sequences_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    df = _sample_expense_df()
    df.index = [10, 20, 30, 40, 50]
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    _write_sequences(tmp_path, names, [10, 20, 30, 40, 50])
    sequences = load_sequences(base_dir=str(tmp_path))
    newest = reporting.select_newest_sequences(sequences, df, limit=3)
    assert len(newest) == 3
    assert [s["name"] for s in newest] == ["Delta", "Beta", "Alpha"]


def test_render_html_sections(tmp_path, monkeypatch):
    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr(
        "money_tracker.assets.engine.build_overview",
        lambda **kwargs: {
            "total": 10000.0,
            "checking_total": 3000.0,
            "savings_total": 7000.0,
            "as_of": "2026-05-31",
            "assets": [],
            "total_history": [],
        },
    )
    df = _sample_expense_df().iloc[:1].copy()
    df.index = [100]
    _write_sequences(tmp_path, ["Trip Israel"], [100])
    ctx = reporting.build_report_context(
        display_currency="EUR",
        base_dir=str(tmp_path),
        df=df,
        reference_date=pd.Timestamp("2026-06-09"),
    )
    html = reporting.render_report_html(ctx, {}, embed_mode="cid")
    assert "Assets Overview" in html
    assert "May 2026" in html
    assert "Trip Israel" in html
    assert 'class="report-table"' in html
    assert 'class="seq-grid"' in html
    assert "Expenses Table" in html
    assert "Cumulative Expenses by Category" not in html  # alt text only in img tags when charts present
    assert "<script" not in html.lower()


def test_send_gmail_mocked(tmp_path, monkeypatch):
    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr(
        "money_tracker.assets.engine.build_overview",
        lambda **kwargs: {
            "total": 0.0,
            "checking_total": 0.0,
            "savings_total": 0.0,
            "as_of": None,
            "assets": [],
            "total_history": [],
        },
    )
    monkeypatch.setenv("GMAIL_USER", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    monkeypatch.setenv("REPORT_EMAIL_TO", "recipient@gmail.com")

    df = _sample_expense_df()
    ctx = reporting.build_report_context(
        display_currency="EUR",
        base_dir=str(tmp_path),
        df=df,
        reference_date=pd.Timestamp("2026-06-09"),
    )
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    chart_images = {
        "assets_total": fake_png,
        "expenses_pie": fake_png,
        "expenses_cumulative": fake_png,
        "expenses_bar": fake_png,
    }

    smtp_instance = MagicMock()
    smtp_cls = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=smtp_instance), __exit__=MagicMock(return_value=False)))

    with patch("money_tracker.reporting.render_chart_images", return_value=chart_images):
        with patch("money_tracker.reporting.smtplib.SMTP", smtp_cls):
            reporting.send_gmail_report(ctx)

    smtp_instance.login.assert_called_once_with("sender@gmail.com", "secret")
    smtp_instance.sendmail.assert_called_once()
    raw = smtp_instance.sendmail.call_args[0][2]
    msg = BytesParser(policy=policy.default).parsebytes(raw.encode("utf-8"))
    assert msg["Subject"] == "Money Tracker Report for May 2026"

    html_parts = [p for p in msg.walk() if p.get_content_type() == "text/html"]
    assert html_parts
    html_body = html_parts[0].get_content()
    assert "cid:assets_total" in html_body
    assert "<script" not in html_body.lower()

    png_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert png_parts
    cids = {p["Content-ID"].strip("<>") for p in png_parts if p.get("Content-ID")}
    assert "assets_total" in cids
    assert all(p.get_content_disposition() == "inline" for p in png_parts)

    pdf_parts = [p for p in msg.walk() if p.get_content_type() == "application/pdf"]
    assert not pdf_parts


def test_chart_images_kaleido(tmp_path, monkeypatch):
    pytest.importorskip("kaleido", reason="kaleido not installed")

    def _skip_if_no_chrome(exc: BaseException) -> None:
        msg = str(exc)
        if "Chrome" in msg or "Kaleido" in msg:
            pytest.skip("Kaleido/Chrome not available for chart export")

    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr(
        "money_tracker.assets.engine.build_overview",
        lambda **kwargs: {
            "total": 1000.0,
            "checking_total": 500.0,
            "savings_total": 500.0,
            "as_of": "2026-05-31",
            "assets": [],
            "total_history": [{"date": pd.Timestamp("2026-05-01"), "value": 1000.0}],
        },
    )
    df = _sample_expense_df()
    ctx = reporting.build_report_context(
        display_currency="EUR",
        base_dir=str(tmp_path),
        df=df,
        reference_date=pd.Timestamp("2026-06-09"),
    )
    try:
        images = reporting.render_chart_images(ctx)
    except RuntimeError as exc:
        _skip_if_no_chrome(exc)
        raise
    assert "assets_total" in images
    assert "expenses_pie" in images
    assert "expenses_cumulative" in images
    assert "expenses_bar" in images
    assert images["assets_total"][:4] == b"\x89PNG"
    assert len(images["assets_total"]) > 100


def test_pdf_smoke(tmp_path, monkeypatch):
    weasyprint = pytest.importorskip("weasyprint", reason="weasyprint not installed")
    del weasyprint

    monkeypatch.setattr("money_tracker.data_loading.get_base_dir", lambda base_dir=None: str(tmp_path))
    monkeypatch.setattr(
        "money_tracker.assets.engine.build_overview",
        lambda **kwargs: {
            "total": 1000.0,
            "checking_total": 500.0,
            "savings_total": 500.0,
            "as_of": "2026-05-31",
            "assets": [],
            "total_history": [],
        },
    )
    df = _sample_expense_df()
    ctx = reporting.build_report_context(
        display_currency="EUR",
        base_dir=str(tmp_path),
        df=df,
        reference_date=pd.Timestamp("2026-06-09"),
    )
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    chart_images = {
        "assets_total": fake_png,
        "expenses_pie": fake_png,
        "expenses_cumulative": fake_png,
        "expenses_bar": fake_png,
    }
    html = reporting.render_report_html(ctx, chart_images, embed_mode="base64")
    pdf = reporting.html_to_pdf(html)
    assert pdf[:4] == b"%PDF"
