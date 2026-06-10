"""Build and deliver periodic money-tracker reports (PDF download, HTML email)."""

from __future__ import annotations

import base64
import colorsys
import hashlib
import html
import io
import os
import re
import smtplib
from dataclasses import dataclass, field
from datetime import date
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Literal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from money_tracker import currency as currency_conv
from money_tracker import data_loading
from money_tracker import env_config
from money_tracker.data_loading import INCOME_REFUND_CATEGORY, is_income_refund_category
from money_tracker.assets import engine as assets_engine
from money_tracker.sequences import (
    apply_sequences_to_df,
    get_sequence_expense_indices,
    load_sequences,
    sequence_expenses_df,
)

_DEFAULT_THEME = "teal"
_FONT_FAMILY = "Inter, Roboto, Lato, sans-serif"
_CHART_WIDTH = 800
_CHART_HEIGHT = 450
_CHART_SCALE = 2
_SEQ_CHART_HEIGHT = 300
_SEQ_CHART_WIDTH = 260

_REPORT_CSS = """
body { font-family: Inter, Roboto, Lato, sans-serif; color: #212529; max-width: 800px; margin: 0 auto; padding: 16px; }
.report-table { border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; }
.report-table th, .report-table td {
  border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; word-wrap: break-word;
}
.report-table th { background: #f5f5f5; font-weight: 600; text-align: left; }
.report-table .num { text-align: right; }
.seq-grid { width: 100%; border-collapse: collapse; margin: 12px 0; }
.seq-grid td { width: 33%; vertical-align: top; text-align: center; padding: 8px; border: none; }
.seq-grid h3 { margin: 0 0 6px; font-size: 15px; }
.seq-grid p { margin: 0 0 8px; font-size: 13px; color: #555; }
.seq-grid img { max-width: 100%; height: auto; margin: 0 auto; }
.chart-img { max-width: 100%; height: auto; display: block; margin: 12px 0; }
"""

_THEME_PALETTES = {
    "teal": {
        "template": "plotly_white",
        "paper": "#ffffff",
        "plot": "#ffffff",
        "font": "#212529",
        "muted": "#495057",
        "grid": "#e3e7eb",
        "hover_bg": "#ffffff",
        "colorway": [
            "#60a5fa", "#7dd3fc", "#6ee7b7", "#86efac", "#fb7185",
            "#fdba74", "#c084fc", "#d8b4fe", "#fcd34d", "#fef08a",
        ],
    },
    "dark": {
        "template": "plotly_dark",
        "paper": "#2d2d2d",
        "plot": "#2d2d2d",
        "font": "#dddddd",
        "muted": "#bbbbbb",
        "grid": "#3a3a3a",
        "hover_bg": "#1e1e1e",
        "colorway": [
            "#1f3b93", "#3f1dcb", "#156e4c", "#22c55e", "#a6192e",
            "#f2634c", "#6b21a8", "#a855f7", "#b45309", "#eab308",
        ],
    },
}


@dataclass
class SequenceReport:
    name: str
    category: str
    total: float
    expense_count: int
    expenses_df: pd.DataFrame
    chart_id: str


@dataclass
class ReportContext:
    display_currency: str
    generated_on: date
    overview: dict[str, Any]
    month_label: str
    month_start: date
    month_end: date
    month_expenses_df: pd.DataFrame
    month_category_totals: pd.DataFrame
    sequences: list[SequenceReport] = field(default_factory=list)


def last_calendar_month_range(
    reference: date | pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return inclusive start/end for the previous full calendar month."""
    ref = pd.Timestamp(reference or pd.Timestamp.today()).normalize()
    first_of_current = ref.replace(day=1)
    last_of_previous = first_of_current - pd.Timedelta(days=1)
    first_of_previous = last_of_previous.replace(day=1)
    return first_of_previous, last_of_previous


def _seq_last_date(seq: dict[str, Any], df: pd.DataFrame) -> pd.Timestamp:
    try:
        indices = get_sequence_expense_indices(seq, df)
    except Exception:
        indices = []
    if not indices or "Booking Date" not in df.columns:
        return pd.Timestamp.min
    dates = pd.to_datetime(df.loc[df.index.isin(indices), "Booking Date"], errors="coerce")
    if dates.empty:
        return pd.Timestamp.min
    last = dates.max()
    return last if pd.notna(last) else pd.Timestamp.min


def select_newest_sequences(
    sequences: list[dict[str, Any]],
    df: pd.DataFrame,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return up to *limit* sequences ordered by most recent expense."""
    ordered = sorted(sequences, key=lambda s: _seq_last_date(s, df), reverse=True)
    return ordered[:limit]


def _slug_chart_id(prefix: str, name: str = "") -> str:
    slug = re.sub(r"[^\w]+", "_", name).strip("_").lower() or "default"
    return f"{prefix}_{slug}"[:64]


def _normalize_theme(theme: str | None) -> str:
    if theme in _THEME_PALETTES:
        return theme
    return _DEFAULT_THEME


def _theme_palette(theme: str | None) -> dict[str, Any]:
    return _THEME_PALETTES[_normalize_theme(theme)]


def _stable_color_for_label(label: Any, theme: str | None) -> str:
    if label is not None and is_income_refund_category(str(label).split(" - ", 1)[0].strip()):
        return "#6b7280"
    key = str(label)
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    hue = (int(digest[:8], 16) % 360) / 360.0
    sat = 0.58
    light = 0.52 if _normalize_theme(theme) == "teal" else 0.42
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _color_with_alpha(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return hex_color
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _color_map_for_labels(labels, theme: str | None) -> dict[str, str]:
    if labels is None:
        return {}
    return {str(label): _stable_color_for_label(label, theme) for label in labels}


def _category_is_income_refund(label: Any) -> bool:
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return False
    base = str(label).split(" - ", 1)[0].strip()
    return is_income_refund_category(base)


def _expense_cat_col(df: pd.DataFrame) -> str:
    return "Display Category" if "Display Category" in df.columns else "Category"


def _apply_chart_theme(fig: go.Figure, theme: str | None) -> go.Figure:
    pal = _theme_palette(theme)
    fig.update_layout(
        template=pal["template"],
        paper_bgcolor=pal["paper"],
        plot_bgcolor=pal["plot"],
        colorway=pal["colorway"],
        font=dict(family=_FONT_FAMILY, color=pal["font"], size=13),
        title=dict(font=dict(family=_FONT_FAMILY, color=pal["font"], size=16)),
        legend=dict(
            font=dict(family=_FONT_FAMILY, color=pal["font"], size=12),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor=pal["hover_bg"],
            bordercolor=pal["grid"],
            font=dict(family=_FONT_FAMILY, color=pal["font"], size=12),
        ),
        margin=dict(t=56, r=24, b=48, l=60),
    )
    fig.update_xaxes(
        gridcolor=pal["grid"], zerolinecolor=pal["grid"],
        linecolor=pal["grid"], color=pal["muted"],
    )
    fig.update_yaxes(
        gridcolor=pal["grid"], zerolinecolor=pal["grid"],
        linecolor=pal["grid"], color=pal["muted"],
    )
    return fig


def _pick_amount_col(df: pd.DataFrame, display_currency: str) -> str:
    return currency_conv.pick_amount_column(df, display_currency)


def _format_money(value: float, currency_code: str) -> str:
    symbols = {"EUR": "€", "ILS": "₪", "USD": "$", "GBP": "£"}
    sym = symbols.get(currency_code)
    if sym:
        return f"{sym}{value:,.2f}"
    return f"{value:,.2f} {currency_code}"


def _load_expense_df(base_dir: str | None = None) -> pd.DataFrame:
    df = data_loading.run_pipeline(base_dir=base_dir)
    return apply_sequences_to_df(df, base_dir=base_dir)


def _filter_month_expenses(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    work = work[
        (work["Booking Date"] >= start) & (work["Booking Date"] <= end)
    ]
    if "is_settlement_excluded" in work.columns:
        work = work[~work["is_settlement_excluded"].fillna(False)]
    return work


def _month_category_totals(df: pd.DataFrame, display_currency: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Category", "Amount"])
    cat_col = "Display Category" if "Display Category" in df.columns else "Category"
    amt_col = _pick_amount_col(df, display_currency)
    grouped = df.groupby(cat_col)[amt_col].sum().reset_index()
    grouped = grouped.rename(columns={cat_col: "Category", amt_col: "Amount"})
    grouped["Amount"] = grouped["Amount"].abs()
    return grouped.sort_values("Amount", ascending=False)


def build_report_context(
    *,
    display_currency: str = "EUR",
    base_dir: str | None = None,
    df: pd.DataFrame | None = None,
    reference_date: date | pd.Timestamp | None = None,
) -> ReportContext:
    """Assemble assets overview, last-month expenses, and newest sequences."""
    if df is None:
        df = _load_expense_df(base_dir)
    month_start, month_end = last_calendar_month_range(reference_date)
    month_df = _filter_month_expenses(df, month_start, month_end)
    overview = assets_engine.build_overview(
        base_dir=base_dir, display_currency=display_currency,
    )
    sequences_raw = load_sequences(base_dir=base_dir)
    newest = select_newest_sequences(sequences_raw, df, limit=3)
    seq_reports: list[SequenceReport] = []
    for seq in newest:
        seq_df = sequence_expenses_df(
            df, seq["name"], sequences_raw, display_currency=display_currency,
        )
        amt_col = _pick_amount_col(seq_df, display_currency) if not seq_df.empty else None
        total = float(seq_df[amt_col].sum()) if amt_col and not seq_df.empty else 0.0
        seq_reports.append(SequenceReport(
            name=seq["name"],
            category=seq.get("category") or "(none)",
            total=total,
            expense_count=len(seq_df),
            expenses_df=seq_df,
            chart_id=_slug_chart_id("seq_pie", seq["name"]),
        ))
    month_label = month_start.strftime("%B %Y")
    gen_on = reference_date or date.today()
    if isinstance(gen_on, pd.Timestamp):
        gen_on = gen_on.date()
    return ReportContext(
        display_currency=display_currency,
        generated_on=gen_on,
        overview=overview,
        month_label=month_label,
        month_start=month_start.date(),
        month_end=month_end.date(),
        month_expenses_df=month_df,
        month_category_totals=_month_category_totals(month_df, display_currency),
        sequences=seq_reports,
    )


def _fig_assets_total(
    history: list[dict[str, Any]],
    theme: str | None,
    display_currency: str,
) -> go.Figure:
    fig = go.Figure()
    if history:
        dates = [p["date"] for p in history]
        values = [p["value"] for p in history]
        fig.add_trace(go.Scatter(
            x=dates, y=values, mode="lines+markers", name="Total assets",
            line=dict(width=2.5),
        ))
    fig.update_layout(
        title="Total Assets over Time — All Sources",
        xaxis_title="Date",
        yaxis_title=f"Amount ({currency_conv.normalize_currency(display_currency)})",
        height=_CHART_HEIGHT,
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return _apply_chart_theme(fig, theme)


def report_email_subject(ctx: ReportContext) -> str:
    return f"Money Tracker Report for {ctx.month_label}"


def _fig_expenses_pie(
    month_df: pd.DataFrame,
    theme: str | None,
    display_currency: str,
) -> go.Figure:
    if month_df.empty:
        fig = px.pie(title="Expense Distribution by Category")
        fig.update_layout(height=_CHART_HEIGHT)
        return _apply_chart_theme(fig, theme)
    cat_col = _expense_cat_col(month_df)
    amt_col = _pick_amount_col(month_df, display_currency)
    grouped = month_df.groupby(cat_col)[amt_col].sum().reset_index()
    grouped = grouped.rename(columns={amt_col: "_amount"})
    grouped["_amount"] = grouped["_amount"].abs()
    grouped = grouped.sort_values("_amount", ascending=False)
    labels = [str(v) for v in grouped[cat_col].tolist()]
    values = grouped["_amount"].tolist()
    colors = [_stable_color_for_label(lbl, theme) for lbl in labels]
    pal = _theme_palette(theme)
    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        sort=False,
        marker=dict(colors=colors, line=dict(color=pal["paper"], width=2)),
        textinfo="percent+label",
        textposition="inside",
    ))
    fig.update_layout(title="Expense Distribution by Category", height=_CHART_HEIGHT)
    return _apply_chart_theme(fig, theme)


def _fig_expenses_cumulative(
    month_df: pd.DataFrame,
    theme: str | None,
    display_currency: str,
) -> go.Figure:
    """Stacked cumulative area by category; income as overlay line (matches dashboard)."""
    if month_df.empty:
        fig = px.line(title="Cumulative Expenses by Category")
        fig.update_layout(height=_CHART_HEIGHT)
        return _apply_chart_theme(fig, theme)
    cat_col = _expense_cat_col(month_df)
    amt_col = _pick_amount_col(month_df, display_currency)
    unit = currency_conv.normalize_currency(display_currency)
    work = month_df.copy()
    work["_amt"] = work[amt_col].abs()
    work["_day"] = pd.to_datetime(work["Booking Date"], errors="coerce").dt.normalize()
    date_index = pd.date_range(work["_day"].min(), work["_day"].max(), freq="D")

    income_mask = work[cat_col].map(_category_is_income_refund)
    expense_work = work[~income_mask]
    income_work = work[income_mask]

    color_map = _color_map_for_labels(expense_work[cat_col].dropna().unique(), theme)
    fig = go.Figure()
    hover = (
        "<b>%{fullData.name}</b><br>%{x|%Y-%m-%d}<br>"
        f"Cumulative: %{{y:.2f}} {unit}<extra></extra>"
    )

    expense_series = []
    for cat in expense_work[cat_col].dropna().unique():
        daily = (
            expense_work.loc[expense_work[cat_col] == cat]
            .groupby("_day")["_amt"]
            .sum()
            .reindex(date_index, fill_value=0)
            .cumsum()
        )
        final = float(daily.iloc[-1]) if len(daily) else 0.0
        expense_series.append((cat, final, daily))

    expense_series.sort(key=lambda item: item[1])
    for _idx, (cat, _final, cumulative) in enumerate(expense_series):
        color = color_map.get(str(cat)) or _stable_color_for_label(cat, theme)
        fig.add_trace(go.Scatter(
            x=date_index,
            y=cumulative,
            mode="lines",
            name=str(cat),
            line=dict(width=1, color=color),
            stackgroup="expenses",
            fillcolor=_color_with_alpha(color, 0.65),
            hovertemplate=hover,
        ))

    if not income_work.empty:
        income_cumulative = (
            income_work.groupby("_day")["_amt"]
            .sum()
            .reindex(date_index, fill_value=0)
            .cumsum()
        )
        income_color = "#000000" if _normalize_theme(theme) == "teal" else "#f5f5f5"
        fig.add_trace(go.Scatter(
            x=date_index,
            y=income_cumulative,
            mode="lines",
            name=INCOME_REFUND_CATEGORY,
            line=dict(color=income_color, width=2.5),
            hovertemplate=hover,
        ))

    fig.update_layout(
        height=_CHART_HEIGHT,
        title="Cumulative Expenses by Category",
        xaxis_title="Date",
        yaxis_title=currency_conv.cumulative_axis_label(display_currency),
        hovermode="x unified",
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )
    return _apply_chart_theme(fig, theme)


def _fig_expenses_bar(
    month_df: pd.DataFrame,
    theme: str | None,
    display_currency: str,
) -> go.Figure:
    """Stacked bar by month and category (matches dashboard month view)."""
    if month_df.empty:
        fig = px.bar(title="Expenses by Month and Category")
        fig.update_layout(height=_CHART_HEIGHT)
        return _apply_chart_theme(fig, theme)
    cat_col = _expense_cat_col(month_df)
    filtered = month_df.copy()
    filtered["Period"] = pd.to_datetime(filtered["Booking Date"]).dt.to_period("M").astype(str)
    amt_col = _pick_amount_col(filtered, display_currency)
    amount_label = currency_conv.amount_axis_label(display_currency)
    grouped = filtered.groupby(["Period", cat_col])[amt_col].sum().reset_index()
    grouped = grouped.rename(columns={amt_col: "_amount"})

    income_mask = grouped[cat_col].map(_category_is_income_refund)
    expenses = grouped[~income_mask].copy()
    income = grouped[income_mask].copy()

    all_periods = sorted(grouped["Period"].unique())
    color_map = _color_map_for_labels(grouped[cat_col].dropna().unique(), theme)
    fig = go.Figure()

    expenses["_amount"] = expenses["_amount"].abs()
    if not expenses.empty:
        for cat in expenses[cat_col].unique():
            cat_data = expenses[expenses[cat_col] == cat]
            y_vals = [
                cat_data[cat_data["Period"] == p]["_amount"].sum()
                if p in cat_data["Period"].values else 0
                for p in all_periods
            ]
            fig.add_trace(go.Bar(
                x=all_periods,
                y=y_vals,
                name=str(cat),
                marker_color=color_map.get(str(cat)) or _stable_color_for_label(cat, theme),
                offsetgroup="expenses",
            ))

    if not income.empty:
        income["_amount"] = income["_amount"].abs()
        income_by_period = income.groupby("Period")["_amount"].sum()
        income_vals = [income_by_period.get(p, 0) for p in all_periods]
        fig.add_trace(go.Bar(
            x=all_periods,
            y=income_vals,
            name=INCOME_REFUND_CATEGORY,
            marker_color=_stable_color_for_label(INCOME_REFUND_CATEGORY, theme),
            offsetgroup="income",
            width=0.125,
        ))

    fig.update_layout(
        barmode="stack",
        height=_CHART_HEIGHT,
        xaxis_title="Month",
        yaxis_title=amount_label,
        hovermode="x unified",
        title="Expenses by Month and Category",
        bargap=0.15,
        xaxis=dict(type="category", categoryorder="array", categoryarray=all_periods),
    )
    return _apply_chart_theme(fig, theme)


def _month_expense_table(month_df: pd.DataFrame, display_currency: str) -> tuple[list[str], list[list[str]], set[int]]:
    """Build expenses table columns/rows like the dashboard Expenses tab."""
    if month_df.empty:
        return [], [], set()
    cat_col = _expense_cat_col(month_df)
    amt_col = _pick_amount_col(month_df, display_currency)
    amount_header = currency_conv.amount_axis_label(display_currency)
    cols = ["Partner Name"]
    if "Source" in month_df.columns:
        cols.append("Source")
    if "Currency" in month_df.columns:
        cols.append("Currency")
    cols.extend(["Booking Date", cat_col, amount_header])

    display = month_df[cols[:-1] + [amt_col]].copy()
    display = display.rename(columns={amt_col: amount_header})
    display = display.sort_values("Booking Date", ascending=False)
    display["Booking Date"] = pd.to_datetime(display["Booking Date"]).dt.strftime("%Y-%m-%d")
    display[amount_header] = display[amount_header].apply(
        lambda x: f"{x:.2f}" if pd.notna(x) else "",
    )
    rows = [
        [str(row[col]) if pd.notna(row[col]) else "" for col in cols]
        for _, row in display.iterrows()
    ]
    return cols, rows, {len(cols) - 1}


def _fig_sequence_pie(
    seq_df: pd.DataFrame,
    title: str,
    theme: str | None,
    display_currency: str,
) -> go.Figure:
    if seq_df is None or seq_df.empty:
        fig = px.pie(title=title)
        fig.update_layout(height=_SEQ_CHART_HEIGHT, margin=dict(t=40, b=24, l=20, r=20))
        return _apply_chart_theme(fig, theme)
    amt_col = _pick_amount_col(seq_df, display_currency)
    grouped = seq_df.groupby("Category")[amt_col].sum().abs()
    if grouped.empty:
        fig = px.pie(title=title)
        fig.update_layout(height=_SEQ_CHART_HEIGHT, margin=dict(t=40, b=24, l=20, r=20))
        return _apply_chart_theme(fig, theme)
    labels = [str(v) for v in grouped.index.tolist()]
    values = grouped.tolist()
    colors = [_stable_color_for_label(lbl, theme) for lbl in labels]
    pal = _theme_palette(theme)
    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.5,
        sort=False,
        marker=dict(colors=colors, line=dict(color=pal["paper"], width=1.5)),
        textinfo="percent+label",
        textposition="inside",
    ))
    fig.update_layout(title=title, height=_SEQ_CHART_HEIGHT, margin=dict(t=40, b=24, l=20, r=20))
    return _apply_chart_theme(fig, theme)


def _figure_to_png(
    fig: go.Figure,
    *,
    width: int = _CHART_WIDTH,
    height: int = _CHART_HEIGHT,
) -> bytes:
    buf = io.BytesIO()
    fig.write_image(
        buf,
        format="png",
        width=width,
        height=height,
        scale=_CHART_SCALE,
    )
    return buf.getvalue()


def render_chart_images(ctx: ReportContext, theme: str | None = _DEFAULT_THEME) -> dict[str, bytes]:
    """Export all report charts as PNG bytes (Kaleido). Keys match HTML cid: references."""
    images: dict[str, bytes] = {}
    assets_fig = _fig_assets_total(
        ctx.overview.get("total_history") or [],
        theme,
        ctx.display_currency,
    )
    images["assets_total"] = _figure_to_png(assets_fig)
    month_df = ctx.month_expenses_df
    images["expenses_pie"] = _figure_to_png(
        _fig_expenses_pie(month_df, theme, ctx.display_currency),
    )
    images["expenses_cumulative"] = _figure_to_png(
        _fig_expenses_cumulative(month_df, theme, ctx.display_currency),
    )
    images["expenses_bar"] = _figure_to_png(
        _fig_expenses_bar(month_df, theme, ctx.display_currency),
    )
    for seq in ctx.sequences:
        seq_fig = _fig_sequence_pie(
            seq.expenses_df,
            seq.name,
            theme,
            ctx.display_currency,
        )
        images[seq.chart_id] = _figure_to_png(
            seq_fig, width=_SEQ_CHART_WIDTH, height=_SEQ_CHART_HEIGHT,
        )
    return images


def _html_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    numeric_cols: set[int] | None = None,
) -> str:
    if not rows:
        return "<p><em>No data.</em></p>"
    numeric_cols = numeric_cols or set()
    parts = ['<table class="report-table"><thead><tr>']
    for idx, header in enumerate(headers):
        cls = ' class="num"' if idx in numeric_cols else ""
        parts.append(f"<th{cls}>{html.escape(header)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for idx, cell in enumerate(row):
            cls = ' class="num"' if idx in numeric_cols else ""
            parts.append(f"<td{cls}>{html.escape(str(cell))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _img_tag(chart_id: str, alt: str, embed_mode: Literal["cid", "base64"], png: bytes) -> str:
    if embed_mode == "base64":
        b64 = base64.b64encode(png).decode("ascii")
        src = f"data:image/png;base64,{b64}"
    else:
        src = f"cid:{chart_id}"
    return f'<img class="chart-img" src="{src}" alt="{html.escape(alt)}" />'


def render_report_html(
    ctx: ReportContext,
    chart_images: dict[str, bytes],
    *,
    embed_mode: Literal["cid", "base64"] = "cid",
) -> str:
    """Plain HTML report (no JavaScript). *embed_mode* controls chart image references."""
    ccy = ctx.display_currency
    overview = ctx.overview
    total = overview.get("total") or 0
    checking = overview.get("checking_total") or 0
    savings = overview.get("savings_total") or 0
    as_of = overview.get("as_of") or "—"

    asset_table_rows: list[list[str]] = []
    for item in overview.get("assets", []):
        asset = item["asset"]
        cur = item.get("current")
        if cur is None:
            value_str = "—"
        else:
            value_str = _format_money(cur.get("display_value", cur["value"]), ccy)
        asset_table_rows.append([
            asset.get("name") or asset.get("id", ""),
            asset.get("type", ""),
            value_str,
            f"{item['pct_1m']:+.1f}%" if item.get("pct_1m") is not None else "—",
            f"{item['pct_1y']:+.1f}%" if item.get("pct_1y") is not None else "—",
        ])

    expense_headers, expense_rows, expense_numeric = _month_expense_table(
        ctx.month_expenses_df, ccy,
    )

    sections: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(report_email_subject(ctx))}</title>",
        f"<style>{_REPORT_CSS}</style></head><body>",
        f"<h1>Money Tracker Report</h1>",
        f"<p>Generated on {ctx.generated_on.isoformat()} · amounts in {ccy}</p>",
        "<h2>Assets Overview</h2>",
        f"<p><strong>Total:</strong> {_format_money(total, ccy)} "
        f"(as of {as_of})<br>",
        f"<strong>Checking:</strong> {_format_money(checking, ccy)} · "
        f"<strong>Savings:</strong> {_format_money(savings, ccy)}</p>",
    ]
    if "assets_total" in chart_images:
        sections.append(_img_tag(
            "assets_total", "Total assets over time", embed_mode, chart_images["assets_total"],
        ))
    sections.append(_html_table(
        ["Asset", "Type", "Value", "1M %", "1Y %"],
        asset_table_rows,
        numeric_cols={2},
    ))

    sections.extend([
        f"<h2>Expenses — {ctx.month_label}</h2>",
        f"<p>{ctx.month_start.isoformat()} to {ctx.month_end.isoformat()}</p>",
    ])
    for chart_id, alt in (
        ("expenses_pie", "Expense Distribution by Category"),
        ("expenses_cumulative", "Cumulative Expenses by Category"),
        ("expenses_bar", "Expenses by Month and Category"),
    ):
        if chart_id in chart_images:
            sections.append(_img_tag(chart_id, alt, embed_mode, chart_images[chart_id]))
    sections.append("<h3>Expenses Table</h3>")
    if expense_rows:
        min_date = ctx.month_expenses_df["Booking Date"].min()
        max_date = ctx.month_expenses_df["Booking Date"].max()
        if pd.notna(min_date) and pd.notna(max_date):
            sections.append(
                f"<p><em>Dates in view: "
                f"{pd.Timestamp(min_date).strftime('%Y-%m-%d')} – "
                f"{pd.Timestamp(max_date).strftime('%Y-%m-%d')}</em></p>",
            )
    sections.append(_html_table(expense_headers, expense_rows, numeric_cols=expense_numeric))

    sections.append("<h2>Newest Sequences</h2>")
    if not ctx.sequences:
        sections.append("<p><em>No sequences defined.</em></p>")
    else:
        sections.append('<table class="seq-grid"><tr>')
        for seq in ctx.sequences:
            cell_parts = [
                "<td>",
                f"<h3>{html.escape(seq.name)}</h3>",
                f"<p>{html.escape(seq.category)} · {_format_money(seq.total, ccy)}</p>",
            ]
            if seq.chart_id in chart_images:
                cell_parts.append(_img_tag(
                    seq.chart_id,
                    f"Categories in {seq.name}",
                    embed_mode,
                    chart_images[seq.chart_id],
                ))
            cell_parts.append("</td>")
            sections.append("".join(cell_parts))
        sections.append("</tr></table>")

    sections.append("</body></html>")
    return "\n".join(sections)


def html_to_pdf(html: str) -> bytes:
    """Render HTML string to PDF bytes via weasyprint."""
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def build_report_pdf(ctx: ReportContext, theme: str | None = _DEFAULT_THEME) -> bytes:
    """Full pipeline: charts → HTML with base64 images → PDF."""
    chart_images = render_chart_images(ctx, theme)
    html = render_report_html(ctx, chart_images, embed_mode="base64")
    return html_to_pdf(html)


def gmail_config() -> tuple[str, str, list[str]]:
    """Return (user, app_password, recipients) from environment."""
    return env_config.require_gmail_config()


def send_gmail_report(
    ctx: ReportContext,
    theme: str | None = _DEFAULT_THEME,
    *,
    subject: str | None = None,
) -> None:
    """Send report as HTML email with inline PNG charts (CID), no PDF attachment."""
    user, password, recipients = gmail_config()
    if not user or not password:
        raise ValueError(
            f"Gmail credentials are missing. {env_config.env_setup_hint()}"
        )
    if not recipients:
        raise ValueError(
            f"REPORT_EMAIL_TO is missing or invalid. {env_config.env_setup_hint()}"
        )

    chart_images = render_chart_images(ctx, theme)
    html = render_report_html(ctx, chart_images, embed_mode="cid")
    if subject is None:
        subject = report_email_subject(ctx)

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    for chart_id, png_bytes in chart_images.items():
        img = MIMEImage(png_bytes, _subtype="png")
        img.add_header("Content-ID", f"<{chart_id}>")
        img.add_header("Content-Disposition", "inline", filename=f"{chart_id}.png")
        msg.attach(img)

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, password)
        smtp.sendmail(user, recipients, msg.as_string())
