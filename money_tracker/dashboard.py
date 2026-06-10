"""
Plotly Dash dashboard: interactive charts and sequence management.
Run with: python -m money_tracker.dashboard
Then open http://127.0.0.1:8050
"""

from money_tracker.sequences import (
    load_sequences,
    create_sequence,
    add_timespan,
    remove_timespan,
    add_expenses_to_sequence,
    remove_expenses_from_sequence,
    parse_indices_string,
    rename_sequence,
    set_sequence_category,
    apply_sequences_to_df,
    sequence_expenses_df,
    sequences_expenses_df,
    get_sequence_expense_indices,
)
from money_tracker import currency as currency_conv
from money_tracker import data_loading
from money_tracker.assets import colors as asset_colors
from money_tracker.assets import config as assets_config
from money_tracker.assets import engine as assets_engine
from money_tracker.assets.parsers import registry as assets_parser_registry
from money_tracker.sources import loader as sources_loader
from money_tracker.data_loading import (
    run_pipeline,
    get_base_dir,
    get_csv_dir,
    get_csv_dir_label,
    read_mappings_file,
    write_mappings_file,
    read_category_mapping_file,
    write_category_mapping_file,
    merge_category_mapping,
    INCOME_REFUND_CATEGORY,
    is_income_refund_category,
)
import datetime as dt
import dash_bootstrap_components as dbc
from dash.dash_table import DataTable
from dash import ALL, Dash, dcc, html, Input, Output, State, callback, no_update, callback_context
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import hashlib
import colorsys
from google import genai
import base64
import json
import os
import time
from money_tracker import env_config
from money_tracker import llm_categorization
from money_tracker import reporting
from money_tracker.sources import registry as sources_registry

env_config.load_env()


def _gemini_client_from_env():
    if not env_config.has_gemini_api_key():
        return None
    return genai.Client(api_key=env_config.optional_env("GEMINI_API_KEY"))


def _expense_source_dropdown_options() -> list[dict[str, str]]:
  from money_tracker.sources import schema as sources_schema

  options = [{"label": "(none)", "value": ""}]
  for source_id in sources_registry.registered_reader_ids():
    label = sources_schema.source_display_name(source_id)
    options.append({"label": label, "value": source_id})
  return options

_genai_client = _gemini_client_from_env()
_GEMINI_MODEL = env_config.optional_env("GEMINI_MODEL", "gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Theme palettes (kept in sync with assets/theme.css). A single value
# ("teal" | "dark") drives both the UI (via CSS variables) and every Plotly
# figure (via _apply_chart_theme below) so the two modes stay synchronized.
# ---------------------------------------------------------------------------
_DEFAULT_THEME = "teal"
_FONT_FAMILY = "Inter, Roboto, Lato, sans-serif"

custom_light_colors = [
    "#60a5fa", "#7dd3fc", "#6ee7b7", "#86efac", "#fb7185",
    "#fdba74", "#c084fc", "#d8b4fe", "#fcd34d", "#fef08a",
    "#5eead4", "#a5f3fc", "#f9a8d4", "#fbcfe8", "#94a3b8",
]
custom_dark_colors = [
    "#1f3b93", "#3f1dcb", "#156e4c", "#22c55e", "#a6192e",
    "#f2634c", "#6b21a8", "#a855f7", "#b45309", "#eab308",
    "#0d9488", "#06b6d4", "#db2777", "#f472b6", "#334155",
]

_THEME_PALETTES = {
    "teal": {
        "template": "plotly_white",
        "paper": "#ffffff",
        "plot": "#ffffff",
        "font": "#212529",
        "muted": "#495057",
        "grid": "#e3e7eb",
        "hover_bg": "#ffffff",
        "colorway": custom_light_colors,
    },
    "dark": {
        "template": "plotly_dark",
        "paper": "#2d2d2d",
        "plot": "#2d2d2d",
        "font": "#dddddd",
        "muted": "#bbbbbb",
        "grid": "#3a3a3a",
        "hover_bg": "#1e1e1e",
        "colorway": custom_dark_colors,
    },
}


def _normalize_theme(theme):
  return theme if theme in _THEME_PALETTES else _DEFAULT_THEME


def _theme_palette(theme):
  return _THEME_PALETTES[_normalize_theme(theme)]


def _theme_colorway(theme):
  return _theme_palette(theme)["colorway"]


def _color_with_alpha(hex_color, alpha):
  hex_color = hex_color.lstrip("#")
  if len(hex_color) != 6:
    return hex_color
  r = int(hex_color[0:2], 16)
  g = int(hex_color[2:4], 16)
  b = int(hex_color[4:6], 16)
  return f"rgba({r},{g},{b},{alpha})"


def _stable_color_for_label(label, theme):
  """Deterministic category->color mapping (stable across filtering + figures)."""
  if _is_maybe_income_refund_label(label):
    # Keep income/refund visually distinct and constant.
    return "#6b7280"

  key = str(label)
  digest = hashlib.md5(key.encode("utf-8")).hexdigest()

  # Stable hue for a label, independent of which labels are present.
  hue = (int(digest[:8], 16) % 360) / 360.0
  sat = 0.58
  light = 0.52 if _normalize_theme(theme) == "teal" else 0.42

  r, g, b = colorsys.hls_to_rgb(hue, light, sat)
  return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _color_map_for_labels(labels, theme):
  if labels is None:
    return {}
  return {str(l): _stable_color_for_label(l, theme) for l in list(labels)}


def _category_is_income_refund(label):
  if label is None or (isinstance(label, float) and pd.isna(label)):
    return False
  base = str(label).split(" - ", 1)[0].strip()
  return is_income_refund_category(base)


def _apply_chart_theme(fig, theme):
  """Synchronize a Plotly figure with the active mode's palette/typography."""
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
  fig.update_xaxes(gridcolor=pal["grid"], zerolinecolor=pal["grid"],
                   linecolor=pal["grid"], color=pal["muted"])
  fig.update_yaxes(gridcolor=pal["grid"], zerolinecolor=pal["grid"],
                   linecolor=pal["grid"], color=pal["muted"])
  return fig


# Shared DataTable styling that follows the active theme via CSS variables.
_TABLE_HEADER_STYLE = {
    "backgroundColor": "var(--table-header-bg)",
    "color": "var(--table-header-text)",
    "fontWeight": "600",
    "border": "1px solid var(--border)",
}
_TABLE_CELL_STYLE = {
    "textAlign": "left",
    "padding": "8px 10px",
    "fontFamily": _FONT_FAMILY,
    "border": "1px solid var(--border)",
}
_TABLE_DATA_STYLE = {
    "backgroundColor": "var(--card-bg)",
    "color": "var(--table-text)",
}


def guess_categories_batch(partner_names: list, existing_categories: list) -> dict:
  """Use Gemini to predict categories for multiple partners in one request."""
  return llm_categorization.guess_categories_batch(
      partner_names,
      existing_categories,
      genai_client=_genai_client,
      model=_GEMINI_MODEL,
  )


def _category_updates_from_batch(combined, allowed_set):
  return llm_categorization.category_updates_from_batch(combined, allowed_set)


def _load_permitted_categories():
  """Return list of category names from permitted_categories.txt (project root)."""
  base_dir = get_base_dir()
  path = os.path.join(base_dir, "permitted_categories.txt")
  if not os.path.exists(path):
    return []
  with open(path, "r", encoding="utf-8") as f:
    cats = [line.strip() for line in f if line.strip()]
  return cats


def _auto_cat_status_badge(text, state="idle"):
  """Colored status pill for auto-categorize (idle | working | success | warning | error)."""
  palette = {
      "idle": ("#eceff1", "#455a64", "#b0bec5", "Ready"),
      "working": ("#e3f2fd", "#1565c0", "#90caf9", "…"),
      "success": ("#e8f5e9", "#2e7d32", "#a5d6a7", "✓"),
      "warning": ("#fff8e1", "#e65100", "#ffcc80", "!"),
      "error": ("#ffebee", "#c62828", "#ef9a9a", "✕"),
  }
  bg, fg, border, icon = palette.get(state, palette["idle"])
  return html.Span(
      [
          html.Span(icon, style={"marginRight": "6px", "fontWeight": "bold"}),
          text,
      ],
      style={
          "display": "inline-block",
          "marginLeft": "10px",
          "padding": "4px 12px",
          "borderRadius": "14px",
          "fontSize": "13px",
          "fontWeight": "500",
          "backgroundColor": bg,
          "color": fg,
          "border": f"1px solid {border}",
          "verticalAlign": "middle",
      },
  )


def _normalize_partner(s):
  """Normalize partner name for matching: lower, strip, collapse spaces."""
  if not s or not isinstance(s, str):
    return ""
  return " ".join(s.lower().strip().split())


def _suggest_categories_offline(data: list) -> tuple[list, int]:
  """
  Fill empty categories using only existing table data (no API).
  For each row with empty category, if another row has the same or a similar
  partner (substring match after normalizing), reuse its category.
  Returns (updated data list, number of rows filled).
  """
  if not data:
    return [], 0
  known = {}
  for row in data:
    p = (row.get("Partner") or "").strip()
    c = (row.get("Category") or "").strip()
    if p and c:
      norm = _normalize_partner(p)
      if norm and (norm not in known or len(p) > len(known.get(norm, ("",))[0])):
        known[norm] = (p, c)
  updated = []
  filled = 0
  for row in data:
    partner = (row.get("Partner") or "").strip()
    category = (row.get("Category") or "").strip()
    if not category and partner:
      norm = _normalize_partner(partner)
      best_cat = None
      best_len = 0
      for known_norm, (known_partner, known_cat) in known.items():
        if not known_norm:
          continue
        if (known_norm in norm or norm in known_norm) and len(known_norm) > best_len:
          best_cat = known_cat
          best_len = len(known_norm)
      if best_cat:
        category = best_cat
        filled += 1
    updated.append({"Partner": row.get("Partner") or "",
                   "Category": category or row.get("Category") or ""})
  return updated, filled


def _filter_df(
    df,
    start_date=None,
    end_date=None,
    categories=None,
    *,
    exclude_series=False,
    sources=None,
    currencies=None,
):
  cat_col = "Display Category" if "Display Category" in df.columns else "Category"
  filtered = df.copy()
  if start_date:
    filtered = filtered[filtered["Booking Date"] >= pd.to_datetime(start_date)]
  if end_date:
    filtered = filtered[filtered["Booking Date"] <= pd.to_datetime(end_date)]
  if exclude_series and cat_col in filtered.columns:
    filtered = filtered[~filtered[cat_col].astype(str).str.contains(r"\s-\s", regex=True)]
  if categories:
    filtered = filtered[filtered[cat_col].isin(categories)]
  if sources and "Source" in filtered.columns:
    filtered = filtered[filtered["Source"].isin(sources)]
  if currencies and "Currency" in filtered.columns:
    norm = filtered["Currency"].map(currency_conv.normalize_currency)
    filtered = filtered[norm.isin(currencies)]
  if "is_settlement_excluded" in filtered.columns:
    filtered = filtered[~filtered["is_settlement_excluded"].fillna(False)]
  return filtered, cat_col


def _pick_amount_col(df, display_currency):
  return currency_conv.pick_amount_column(df, display_currency)


def _display_currency_options(df):
  return [
      {"label": code, "value": code}
      for code in currency_conv.relevant_currencies(df)
  ]


def _default_display_currency(df):
  codes = currency_conv.relevant_currencies(df)
  return "EUR" if "EUR" in codes else codes[0]


def _fig_bar(
    df,
    start_date,
    end_date,
    categories,
    period,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
    *,
    exclude_series=False,
    sources=None,
    currencies=None,
):
  filtered, cat_col = _filter_df(
      df,
      start_date,
      end_date,
      categories,
      exclude_series=exclude_series,
      sources=sources,
      currencies=currencies,
  )
  if filtered.empty:
    fig = px.bar(title="No data for selected filters")
    fig.update_layout(height=400, autosize=True)
    return _apply_chart_theme(fig, theme)
  if period == "week":
    filtered = filtered.copy()
    filtered["Period"] = filtered["Booking Date"].dt.to_period("W").astype(str)
  else:
    filtered = filtered.copy()
    filtered["Period"] = filtered["Booking Date"].dt.to_period("M").astype(str)

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

  # Main stacked bars: expenses (original colors)
  expenses["_amount"] = expenses["_amount"].abs()
  if not expenses.empty:
    expense_cats = expenses[cat_col].unique()
    for _idx, cat in enumerate(expense_cats):
      cat_data = expenses[expenses[cat_col] == cat]
      y_vals = [cat_data[cat_data["Period"] == p]["_amount"].sum(
      ) if p in cat_data["Period"].values else 0 for p in all_periods]
      fig.add_trace(go.Bar(
          x=all_periods,
          y=y_vals,
          name=cat,
          marker_color=color_map.get(str(cat)) or _stable_color_for_label(cat, theme),
          offsetgroup="expenses",
      ))

  # Narrow bar next to main bar: Income / Refund (same scale, positive)
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
      height=450,
      autosize=True,
      xaxis_title=period.capitalize(),
      yaxis_title=amount_label,
      hovermode="x unified",
      title=f"Expenses by {period.capitalize()} and Category",
      bargap=0.15,
      xaxis=dict(type="category", categoryorder="array", categoryarray=all_periods),
  )
  return _apply_chart_theme(fig, theme)


def _fig_pie(
    df,
    start_date,
    end_date,
    categories,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
    *,
    exclude_series=False,
    sources=None,
    currencies=None,
):
  filtered, cat_col = _filter_df(
      df,
      start_date,
      end_date,
      categories,
      exclude_series=exclude_series,
      sources=sources,
      currencies=currencies,
  )
  if filtered.empty:
    fig = px.pie(title="No data for selected filters")
    fig.update_layout(height=400, autosize=True)
    return _apply_chart_theme(fig, theme)
  amt_col = _pick_amount_col(filtered, display_currency)
  grouped = filtered.groupby(cat_col)[amt_col].sum().reset_index()
  grouped = grouped.rename(columns={amt_col: "_amount"})
  grouped["_amount"] = grouped["_amount"].abs()
  grouped = grouped.sort_values("_amount", ascending=False)
  labels = [str(v) for v in grouped[cat_col].tolist()]
  values = grouped["_amount"].tolist()
  colors = [_stable_color_for_label(lbl, theme) for lbl in labels]
  fig = go.Figure(
      go.Pie(
          labels=labels,
          values=values,
          hole=0.55,
          sort=False,
          marker=dict(colors=colors, line=dict(color=_theme_palette(theme)["paper"], width=2)),
          textinfo="percent+label",
          textposition="inside",
          name="",
      )
  )
  fig.update_layout(title="Expense Distribution by Category", height=450, autosize=True)
  return _apply_chart_theme(fig, theme)


def _fig_cumulative(
    df,
    start_date,
    end_date,
    categories,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
    *,
    exclude_series=False,
    sources=None,
    currencies=None,
):
  """Stacked cumulative area by expense category; income as overlay line."""
  filtered, cat_col = _filter_df(
      df,
      start_date,
      end_date,
      categories,
      exclude_series=exclude_series,
      sources=sources,
      currencies=currencies,
  )
  if filtered.empty:
    fig = px.line(title="No data for selected filters")
    fig.update_layout(height=400, autosize=True)
    return _apply_chart_theme(fig, theme)
  amt_col = _pick_amount_col(filtered, display_currency)
  unit = currency_conv.normalize_currency(display_currency)
  work = filtered.copy()
  work["_amt"] = work[amt_col].abs()
  work["_day"] = work["Booking Date"].dt.normalize()
  date_index = pd.date_range(work["_day"].min(), work["_day"].max(), freq="D")

  income_mask = work[cat_col].map(_category_is_income_refund)
  expense_work = work[~income_mask]
  income_work = work[income_mask]

  color_map = _color_map_for_labels(expense_work[cat_col].dropna().unique(), theme)
  fig = go.Figure()
  hover = ("<b>%{fullData.name}</b><br>%{x|%Y-%m-%d}<br>"
           f"Cumulative: %{{y:.2f}} {unit}<extra></extra>")

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
        name=cat,
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
      height=450,
      autosize=True,
      title="Cumulative Expenses by Category",
      xaxis_title="Date",
      yaxis_title=currency_conv.cumulative_axis_label(display_currency),
      hovermode="x unified",
      legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
  )
  return _apply_chart_theme(fig, theme)


def _load_data():
  df = _cached_run_pipeline()
  return apply_sequences_to_df(df)


_TAB_CHARTS = "tab-charts"
_TAB_ASSETS = "tab-assets"
_TAB_SEQUENCES = "tab-sequences"
_TAB_DATA = "tab-data"

_SEQ_EXPENSES_TABLE_PAGE_SIZE = 50

_pipeline_df_cache = None
_pipeline_cache_key_val = None


def _pipeline_cache_key(base_dir=None):
  """Fingerprint CSV and config files so pipeline results can be reused."""
  base = get_base_dir(base_dir)
  parts = []
  csv_dir = get_csv_dir(base_dir)
  if os.path.isdir(csv_dir):
    for abs_path, _rel in sources_loader.iter_csv_paths(csv_dir):
      parts.append(os.path.getmtime(abs_path))
  for fname in ("mappings.txt", "category_mapping.txt", "sequences.json"):
    path = os.path.join(base, fname)
    parts.append(os.path.getmtime(path) if os.path.exists(path) else 0)
  return tuple(parts)


def _cached_run_pipeline(base_dir=None):
  global _pipeline_df_cache, _pipeline_cache_key_val
  key = _pipeline_cache_key(base_dir)
  if _pipeline_df_cache is None or key != _pipeline_cache_key_val:
    fresh = run_pipeline(base_dir=base_dir)
    csv_dir = get_csv_dir(base_dir)
    if fresh.empty and (
        not os.path.isdir(csv_dir)
        or not data_loading._dir_has_csv_files(csv_dir)
    ):
      return fresh
    _pipeline_df_cache = fresh
    _pipeline_cache_key_val = key
  return _pipeline_df_cache


def _data_load_status(df, error=None):
  """Banner when no transactions loaded (paths + optional error)."""
  csv_dir = get_csv_dir()
  csv_label = get_csv_dir_label()
  if error:
    body = f"Could not load data: {error}"
    color = "var(--banner-error-text)"
  elif df is not None and not df.empty:
    return html.Div()
  else:
    csv_count = 0
    if os.path.isdir(csv_dir):
      csv_count = sum(1 for _abs, _rel in sources_loader.iter_csv_paths(csv_dir))
    body = (
        f"No transactions loaded. CSV folder: {csv_dir} "
        f"({csv_count} .csv file(s)). "
        "Check that Google Drive is mounted in WSL and paths in "
        "scripts/local_config.env match your Drive layout."
    )
    load_errors = sources_loader.get_last_load_errors()
    if load_errors:
      body += " Load errors: " + "; ".join(load_errors)
    color = "var(--banner-warn-text)"
  return html.Div(
      body,
      style={
          "margin": "8px auto 12px",
          "padding": "12px 16px",
          "maxWidth": "1200px",
          "backgroundColor": "var(--banner-error-bg)" if error else "var(--banner-warn-bg)",
          "color": color,
          "border": f"1px solid {color}",
          "borderRadius": "10px",
          "fontSize": "14px",
      },
  )


def _sequences_tab_active(tab):
  return tab == _TAB_SEQUENCES


def _assets_tab_active(tab):
  return tab == _TAB_ASSETS


def _format_asset_money(value, currency_code):
  symbols = {"EUR": "€", "ILS": "₪", "USD": "$", "GBP": "£"}
  sym = symbols.get(currency_code, currency_code + " ")
  if currency_code in symbols and sym != currency_code + " ":
    return f"{sym}{value:,.2f}"
  return f"{value:,.2f} {currency_code}"


def _format_pct_change(pct):
  if pct is None:
    return "—"
  sign = "+" if pct >= 0 else ""
  return f"{sign}{pct:.1f}%"


def _pct_change_class(pct):
  if pct is None:
    return "mt-change--na"
  return "mt-change--up" if pct >= 0 else "mt-change--down"


def _fig_assets_total(history, theme=_DEFAULT_THEME, display_currency="EUR"):
  fig = go.Figure()
  if history:
    dates = [p["date"] for p in history]
    values = [p["value"] for p in history]
    fig.add_trace(go.Scatter(
        x=dates,
        y=values,
        mode="lines+markers",
        name="Total assets",
        line=dict(width=2.5),
    ))
  fig.update_layout(
      title="Total Assets over Time — All Sources",
      xaxis_title="Date",
      yaxis_title=f"Amount ({currency_conv.normalize_currency(display_currency)})",
      height=450,
      margin=dict(l=50, r=30, t=50, b=50),
  )
  return _apply_chart_theme(fig, theme)


def _fig_asset_sparkline(history, color, theme=_DEFAULT_THEME):
  fig = go.Figure()
  if history:
    tail = history[-24:]
    fig.add_trace(go.Scatter(
        x=[p["date"] for p in tail],
        y=[p["value"] for p in tail],
        mode="lines",
        line=dict(width=2, color=color),
        fill="tozeroy",
        fillcolor=_color_with_alpha(color, 0.25),
    ))
  fig.update_layout(
      height=80,
      margin=dict(l=0, r=0, t=0, b=0),
      showlegend=False,
      xaxis=dict(visible=False),
      yaxis=dict(visible=False),
  )
  return _apply_chart_theme(fig, theme)


def _assets_currency_options():
  rates = currency_conv.load_to_eur_rates(get_base_dir())
  codes = sorted(rates.keys())
  return [{"label": c, "value": c} for c in codes]


def _asset_card_manual_section(asset_id):
  return html.Details([
      html.Summary("Update value manually"),
      html.Div([
          dcc.Input(
              id={"type": "asset-manual-value", "index": asset_id},
              type="number",
              placeholder="Value",
              step="any",
              className="mt-input",
              style={"width": "140px", "marginRight": "8px"},
          ),
          dcc.Input(
              id={"type": "asset-manual-date", "index": asset_id},
              type="text",
              placeholder="YYYY-MM-DD (optional)",
              className="mt-input",
              style={"width": "150px", "marginRight": "8px"},
          ),
          html.Button("Save", id={"type": "asset-manual-save", "index": asset_id},
                      n_clicks=0),
      ], style={"display": "flex", "flexWrap": "wrap", "gap": "8px",
                "alignItems": "center", "marginTop": "8px"}),
  ], className="mt-asset-card__manual")


def _asset_card_upload_section(asset, card_messages):
  asset_id = asset["id"]
  sections = []
  if asset.get("parser"):
    sections.append(dcc.Upload(
        id={"type": "asset-report-upload", "index": asset_id},
        children=html.Button("Upload new report file", n_clicks=0),
        className="mt-asset-card__upload-wrap",
        multiple=False,
    ))
  msg = (card_messages or {}).get(asset_id)
  if msg and msg.get("text"):
    kind = msg.get("kind", "info")
    sections.append(html.Div(
        msg["text"],
        className=f"mt-asset-card__upload-msg mt-asset-card__upload-msg--{kind}",
    ))
  return html.Div(sections, className="mt-asset-card__upload") if sections else None


def _build_asset_card(item, theme=_DEFAULT_THEME, display_currency="EUR", card_messages=None):
  asset = item["asset"]
  asset_id = asset["id"]
  name = asset.get("name", asset_id)
  asset_type = asset.get("type", "bank")
  color = asset_colors.asset_color(asset_id, asset_type, theme=_normalize_theme(theme))
  current = item.get("current")
  upload_section = _asset_card_upload_section(asset, card_messages)
  manual_section = _asset_card_manual_section(asset_id)

  if current is None:
    body = html.Div([
        html.Div(
            "No data yet — upload a report or enter a value manually.",
            className="mt-muted",
            style={"fontStyle": "italic", "marginBottom": "8px"},
        ),
        upload_section,
        manual_section,
    ])
  else:
    native = _format_asset_money(current["value"], current["currency"])
    display = _format_asset_money(current["display_value"], display_currency)
    value_block = html.Div([
        html.Div(display, className="mt-asset-card__value"),
        html.Div(native, className="mt-asset-card__native"),
    ])
    sub = current.get("sub_breakdown")
    sub_rows = []
    if sub:
      for label, amount in sub.items():
        sub_rows.append(html.Div([
            html.Span(label, className="mt-asset-card__sub-label"),
            html.Span(_format_asset_money(amount, current["currency"]),
                      className="mt-asset-card__sub-value"),
        ], className="mt-asset-card__sub-row"))
    body = html.Div([
        value_block,
        html.Div([
            html.Span("1M ", className="mt-asset-card__pct-label"),
            html.Span(_format_pct_change(item.get("pct_1m")),
                      className=_pct_change_class(item.get("pct_1m"))),
            html.Span("  1Y ", className="mt-asset-card__pct-label",
                      style={"marginLeft": "12px"}),
            html.Span(_format_pct_change(item.get("pct_1y")),
                      className=_pct_change_class(item.get("pct_1y"))),
        ], className="mt-asset-card__changes"),
        dcc.Graph(
            id={"type": "asset-spark", "index": asset_id},
            figure=_fig_asset_sparkline(item.get("history", []), color, theme),
            config={"displayModeBar": False, "staticPlot": True},
            style={"height": "80px"},
        ),
        html.Div(sub_rows, className="mt-asset-card__breakdown") if sub_rows else None,
        upload_section,
        manual_section,
    ])

  return html.Div([
      html.Div([
          html.Span(name, className="mt-asset-card__name"),
          html.Span(asset_type, className="mt-asset-card__type"),
      ], className="mt-asset-card__header"),
      body,
  ], className="mt-asset-card", style={"borderLeftColor": color})


def _assets_liquidity_bar_segments(total, checking, savings):
  if total <= 0 or (checking <= 0 and savings <= 0):
    return []
  segments = []
  if checking > 0:
    segments.append(
        html.Div(
            className="mt-assets-total__bar-seg mt-assets-total__bar-seg--checking",
            style={"width": f"{(checking / total) * 100:.2f}%"},
        )
    )
  if savings > 0:
    segments.append(
        html.Div(
            className="mt-assets-total__bar-seg mt-assets-total__bar-seg--savings",
            style={"width": f"{(savings / total) * 100:.2f}%"},
        )
    )
  return segments


def _build_assets_total_summary(overview, display_currency):
  total = overview.get("total") or 0
  checking = overview.get("checking_total") or 0
  savings = overview.get("savings_total") or 0
  total_label = _format_asset_money(total, display_currency)
  checking_label = _format_asset_money(checking, display_currency)
  savings_label = _format_asset_money(savings, display_currency)
  as_of = overview.get("as_of") or "—"
  bar_segments = _assets_liquidity_bar_segments(total, checking, savings)
  bar_class = "mt-assets-total__bar"
  if not bar_segments:
    bar_class += " mt-assets-total__bar--empty"
  return html.Div([
      html.Div([
          html.Div("Total Assets", className="mt-assets-total__label"),
          html.Div(f"As of {as_of}", className="mt-assets-total__asof"),
      ], className="mt-assets-total__header"),
      html.Div(total_label, className="mt-assets-total__amount"),
      html.Div(bar_segments, className=bar_class),
      html.Div([
          html.Span([
              html.Span([
                  "Checking",
                  html.Span("Bank accounts", className="mt-assets-total__badge-hint"),
              ], className="mt-assets-total__badge-label"),
              html.Span(checking_label, className="mt-assets-total__badge-value"),
          ], className="mt-assets-total__badge mt-assets-total__badge--checking"),
          html.Span([
              html.Span("Savings", className="mt-assets-total__badge-label"),
              html.Span(savings_label, className="mt-assets-total__badge-value"),
          ], className="mt-assets-total__badge mt-assets-total__badge--savings"),
      ], className="mt-assets-total__badges"),
  ], className="mt-assets-total__summary")


def _build_assets_grid(overview, theme, display_currency, card_messages=None):
  return [
      _build_asset_card(item, theme, display_currency, card_messages)
      for item in overview["assets"]
  ]


def _asset_add_modal_body():
  parser_options = [{"label": "(none — manual updates only)", "value": ""}]
  parser_options.extend(assets_parser_registry.parser_dropdown_options())
  type_options = [{"label": t.title(), "value": t} for t in assets_config.ASSET_TYPES]
  currency_options = _assets_currency_options()
  return html.Div([
      html.Div([
          html.Label("Name *"),
          dcc.Input(id="asset-add-name", type="text", placeholder="e.g. Crypto wallet",
                    className="mt-input", style={"width": "100%"}),
      ], className="mt-asset-form-row"),
      html.Div([
          html.Label("Asset id (optional)"),
          dcc.Input(id="asset-add-id", type="text",
                    placeholder="Auto-generated from name if empty",
                    className="mt-input", style={"width": "100%"}),
      ], className="mt-asset-form-row"),
      html.Div([
          html.Label("Type *"),
          dcc.Dropdown(id="asset-add-type", options=type_options, value="investment",
                       clearable=False),
      ], className="mt-asset-form-row"),
      html.Div([
          html.Label("Currency *"),
          dcc.Dropdown(id="asset-add-currency", options=currency_options, value="EUR",
                       clearable=False),
      ], className="mt-asset-form-row"),
      html.Div([
          html.Label("Report parser (optional)"),
          dcc.Dropdown(id="asset-add-parser", options=parser_options, value="",
                       clearable=False),
      ], className="mt-asset-form-row"),
      html.Div([
          html.Label("Expense source (optional, for bank auto-update)"),
          dcc.Dropdown(
              id="asset-add-expense-source",
              options=_expense_source_dropdown_options(),
              value="",
              clearable=False,
          ),
      ], className="mt-asset-form-row"),
      html.Hr(),
      html.P("Optional starting balance (no report file):",
             style={"fontSize": "0.9rem", "color": "var(--text-secondary)"}),
      html.Div([
          html.Label("Initial value"),
          dcc.Input(id="asset-add-initial-value", type="number", step="any",
                    placeholder="e.g. 10000", className="mt-input",
                    style={"width": "100%"}),
      ], className="mt-asset-form-row"),
      html.Div([
          html.Label("As of date"),
          dcc.Input(id="asset-add-as-of", type="text", placeholder="YYYY-MM-DD",
                    className="mt-input", style={"width": "100%"}),
      ], className="mt-asset-form-row"),
      html.Div(id="asset-add-msg", className="mt-asset-form-msg"),
  ], className="mt-asset-form")


def _seq_loading_placeholder(text="Loading…"):
  return html.Div(
      text,
      style={"padding": "10px", "color": "#666", "fontStyle": "italic"},
  )


def _expand_category_filter(df, categories):
  """Expand sequence names to full 'Category - SequenceName' for filtering."""
  categories = categories or []
  cat_col = "Display Category" if "Display Category" in df.columns else "Category"
  expanded = set(categories)
  for c in categories:
    for val in df[cat_col].dropna().unique():
      if pd.notna(val) and str(val).endswith(" - " + str(c)):
        expanded.add(val)
      if pd.notna(val) and str(val).startswith(str(c) + " - "):
        expanded.add(val)
  return list(expanded), cat_col


_EXPENSES_TABLE_VIEWPORT_HEIGHT = "360px"
_SEQ_EXPENSES_TABLE_VIEWPORT_HEIGHT = "280px"
_SEQ_EDIT_EXPENSES_VIEWPORT_HEIGHT = "60vh"
_SEQ_EDIT_EXPENSES_PAGE_SIZE = 25
_SEQ_FRAME_MODAL_TABLE_HEIGHT = "70vh"
_SEQ_FRAME_MODAL_TABLE_PAGE_SIZE = 25


def _scrollable_table_panel(viewport_id, info_id, table, viewport_height):
  return html.Div(
      className="scrollable-table-panel",
      children=[
          html.Div(
              id=viewport_id,
              className="scrollable-table-viewport",
              style={"maxHeight": viewport_height, "overflowY": "auto"},
              children=[table],
          ),
          html.Div(
              className="scrollable-table-range-bar",
              children=html.Span(id=info_id, className="scrollable-table-range"),
          ),
      ],
  )


def _format_expenses_table_page_info(visible_rows):
  if not visible_rows:
    return ""
  dates = sorted(r.get("Booking Date") for r in visible_rows if r.get("Booking Date"))
  if not dates:
    return ""
  if dates[0] == dates[-1]:
    return f"Dates in view: {dates[0]}"
  return f"Dates in view: {dates[0]} – {dates[-1]}"


def _format_seq_expenses_table_page_info(visible_rows):
  if not visible_rows:
    return ""
  dates = sorted(r.get("Booking Date") for r in visible_rows if r.get("Booking Date"))
  indices = sorted(int(r["Index"]) for r in visible_rows if r.get("Index") is not None)
  parts = []
  if dates:
    if dates[0] == dates[-1]:
      parts.append(f"Dates in view: {dates[0]}")
    else:
      parts.append(f"Dates in view: {dates[0]} – {dates[-1]}")
  if indices:
    if indices[0] == indices[-1]:
      parts.append(f"Indexes in view: {indices[0]}")
    else:
      parts.append(f"Indexes in view: {indices[0]} – {indices[-1]}")
  return " · ".join(parts)


def _expense_table_base_cols(df, cat_col):
  """Column order for expense tables: partner, source, currency, date, category."""
  cols = ["Partner Name"]
  if "Source" in df.columns:
    cols.append("Source")
  if "Currency" in df.columns:
    cols.append("Currency")
  cols.extend(["Booking Date", cat_col])
  return cols


def _data_table_column_defs(column_names):
  return [{"name": col, "id": col} for col in column_names]


def _seq_expenses_table_columns(cat_col, *, include_source=False, include_currency=True):
  cols = ["Index", "Partner Name"]
  if include_source:
    cols.append("Source")
  if include_currency:
    cols.append("Currency")
  cols.extend(["Booking Date", cat_col, "Amount (EUR) converted"])
  return _data_table_column_defs(cols)


def _seq_edit_expenses_table_columns(cat_col, amount_col, *, include_source=False, include_currency=True):
  cols = ["In sequence", "Index", "Partner Name"]
  if include_source:
    cols.append("Source")
  if include_currency:
    cols.append("Currency")
  cols.extend(["Booking Date", cat_col, amount_col])
  return _data_table_column_defs(cols)


def _prepare_seq_edit_expenses_display(df, seq, display_currency="EUR"):
  """All expenses with sequence members listed first, then the rest."""
  if df.empty:
    return pd.DataFrame()
  cat_col = "Display Category" if "Display Category" in df.columns else "Category"
  in_seq = get_sequence_expense_indices(seq, df)
  in_df = df.loc[df.index.isin(in_seq)].copy()
  out_df = df.loc[~df.index.isin(in_seq)].copy()
  in_df = in_df.sort_values("Booking Date", ascending=False)
  out_df = out_df.sort_values("Booking Date", ascending=False)
  display_df = pd.concat([in_df, out_df])
  amt_col = _pick_amount_col(display_df, display_currency)
  amount_header = currency_conv.amount_axis_label(display_currency)
  base_cols = _expense_table_base_cols(display_df, cat_col)
  display_df = display_df[base_cols + [amt_col]].copy()
  display_df = display_df.rename(columns={amt_col: amount_header})
  display_df.insert(0, "Index", display_df.index)
  display_df.insert(0, "In sequence", display_df["Index"].map(lambda i: "Yes" if i in in_seq else "No"))
  display_df["Booking Date"] = pd.to_datetime(display_df["Booking Date"]).dt.strftime("%Y-%m-%d")
  display_df[amount_header] = display_df[amount_header].apply(
      lambda x: f"{x:.2f}" if pd.notna(x) else "")
  return display_df


def _build_seq_edit_expenses_table(display_df, cat_col, selectable):
  amount_col = "Amount (EUR) converted"
  if not display_df.empty:
    # _prepare_seq_edit_expenses_display renames the amount column to a currency-specific header.
    for c in display_df.columns:
      if isinstance(c, str) and c.startswith("Amount ("):
        amount_col = c
        break
  return DataTable(
      id="seq-edit-expenses-table",
      data=display_df.to_dict("records") if not display_df.empty else [],
      columns=_seq_edit_expenses_table_columns(
          cat_col,
          amount_col,
          include_source=not display_df.empty and "Source" in display_df.columns,
          include_currency=not display_df.empty and "Currency" in display_df.columns,
      ),
      row_selectable="multi" if selectable else False,
      page_size=_SEQ_EDIT_EXPENSES_PAGE_SIZE,
      sort_action="none",
      style_table={"width": "100%", "overflowX": "auto"},
      style_cell=_TABLE_CELL_STYLE,
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE,
      style_data_conditional=[
          {"if": {"filter_query": "{In sequence} = 'Yes'"},
           "backgroundColor": "var(--row-highlight)",
           "fontWeight": "600"},
      ],
  )


def _empty_seq_expenses_table(cat_col="Display Category"):
  return DataTable(
      id="seq-expenses-table",
      data=[],
      columns=_seq_expenses_table_columns(cat_col),
      style_cell=_TABLE_CELL_STYLE,
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE | {"whiteSpace": "normal", "height": "auto"},
      page_action="none",
      sort_action="native",
  )


def _build_expenses_table(filtered, cat_col, display_currency="EUR"):
  if filtered.empty:
    return html.Div("No data for selected filters")
  amt_col = _pick_amount_col(filtered, display_currency)
  amount_header = currency_conv.amount_axis_label(display_currency)
  base_cols = _expense_table_base_cols(filtered, cat_col)
  display_df = filtered[base_cols + [amt_col]].copy()
  display_df = display_df.rename(columns={amt_col: amount_header})
  display_df = display_df.sort_values("Booking Date", ascending=False)
  display_df["Booking Date"] = display_df["Booking Date"].dt.strftime("%Y-%m-%d")
  display_df[amount_header] = display_df[amount_header].apply(
      lambda x: f"{x:.2f}" if pd.notna(x) else "")
  table = DataTable(
      id="expenses-table",
      data=display_df.to_dict("records"),
      columns=_data_table_column_defs(list(display_df.columns)),
      style_cell=_TABLE_CELL_STYLE,
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE | {"whiteSpace": "normal", "height": "auto"},
      page_action="none",
      sort_action="native",
  )
  return _scrollable_table_panel(
      "expenses-table-scroll",
      "expenses-table-viewport-info",
      table,
      _EXPENSES_TABLE_VIEWPORT_HEIGHT,
  )


def _build_charts_outputs(
    df,
    start_date,
    end_date,
    categories,
    period,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
    *,
    exclude_series=False,
    sources=None,
    currencies=None,
):
  """Return (bar, pie, cumulative, expenses table) for the Charts tab."""
  display_currency = currency_conv.normalize_currency(display_currency)
  chart_kwargs = {
      "exclude_series": exclude_series,
      "sources": sources,
      "currencies": currencies,
  }
  if df.empty:
    return (
        _fig_bar(df, None, None, None, period or "month", theme, display_currency, **chart_kwargs),
        _fig_pie(df, None, None, None, theme, display_currency, **chart_kwargs),
        _fig_cumulative(df, None, None, None, theme, display_currency, **chart_kwargs),
        html.Div("No data for selected filters"),
    )
  expanded_list, cat_col = _expand_category_filter(df, categories)
  filtered, cat_col = _filter_df(
      df,
      start_date,
      end_date,
      expanded_list,
      exclude_series=exclude_series,
      sources=sources,
      currencies=currencies,
  )
  return (
      _fig_bar(
          df,
          start_date,
          end_date,
          expanded_list,
          period or "month",
          theme,
          display_currency,
          **chart_kwargs,
      ),
      _fig_pie(df, start_date, end_date, expanded_list, theme, display_currency, **chart_kwargs),
      _fig_cumulative(df, start_date, end_date, expanded_list, theme, display_currency, **chart_kwargs),
      _build_expenses_table(filtered, cat_col, display_currency),
  )


def _list_dashboard_files():
  """Return a stable list of data/config files used by the dashboard."""
  base_dir = get_base_dir()
  files = []
  csv_label = get_csv_dir_label()

  csv_dir = get_csv_dir()
  if os.path.isdir(csv_dir):
    for _abs_path, rel in sources_loader.iter_csv_paths(csv_dir):
      files.append(os.path.join(csv_label, rel))

  # Mappings/config
  for name in ["mappings.txt", "category_mapping.txt", "sequences.txt"]:
    if os.path.exists(os.path.join(base_dir, name)):
      files.append(name)

  return base_dir, files


# Build layout (data loaded in callbacks).
# The assets live in the repository-root "assets" folder (one level above this
# package). Dash would otherwise look inside the package directory, so point it
# at the real location explicitly.
_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
app = Dash(
    __name__,
    title="Money Tracker",
    suppress_callback_exceptions=True,
    assets_folder=_ASSETS_DIR,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
    ],
)

@app.server.route("/health")
def _health_check():
  return "ok", 200


_INIT_EXPENSES_TABLE_PLACEHOLDER = html.Div(
    "Loading expenses…",
    style={"padding": "10px", "color": "#666", "fontStyle": "italic"},
)
_INIT_SEQ_PLACEHOLDER = _seq_loading_placeholder()
_GRAPH_STYLE = {"height": "450px"}

# Tab label styling (CSS vars keep the colors in sync with the active mode).
# Tab Headings: ~1.25rem, slightly lighter weight than the page title.
_TAB_STYLE = {
    "padding": "12px 22px",
    "fontSize": "1.25rem",
    "fontWeight": "500",
    "color": "var(--text-secondary)",
    "backgroundColor": "transparent",
    "border": "none",
    "borderBottom": "2px solid transparent",
}
_TAB_SELECTED_STYLE = _TAB_STYLE | {
    "color": "var(--accent)",
    "fontWeight": "600",
    "borderBottom": "2px solid var(--accent)",
}


def _theme_toggle():
  """Mode switch that lives in the same horizontal row as the main tabs."""
  return html.Button(
      [
          html.Span(className="theme-toggle-track"),
          html.Span("Dark", id="theme-toggle-label", className="theme-toggle-label"),
      ],
      id="theme-toggle",
      n_clicks=0,
      className="theme-toggle",
      title="Switch between Teal (light) and Dark mode",
  )


def _mappings_table_data(rows):
  return [{"From": k, "To": v} for k, v in rows]


def _category_table_data(rows):
  return [{"Partner": p, "Category": c} for p, c in rows]


def _build_mappings_table(data):
  return DataTable(
      id="mappings-table",
      data=data,
      columns=[{"name": "From", "id": "From"}, {"name": "To", "id": "To"}],
      editable=True,
      row_deletable=True,
      page_size=20,
      style_table={"overflowX": "auto"},
      style_cell=_TABLE_CELL_STYLE | {"overflow": "visible"},
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE,
  )


def _build_category_table(data):
  return DataTable(
      id="category-table",
      data=data,
      columns=[{"name": "Partner", "id": "Partner"},
               {"name": "Category", "id": "Category"}],
      editable=True,
      row_deletable=True,
      page_size=25,
      style_table={"overflowX": "auto"},
      style_cell=_TABLE_CELL_STYLE | {"overflow": "visible"},
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE,
  )


def _build_category_reference_tiles(existing_categories):
  """Return a list of rows containing small reference tiles for each known category."""
  icon_by_name = {
      "Cafe & Dine": "🍽",
      "Groceries": "🛒",
      "Entertainment": "🎬",
      "Trips": "🧳",
      "Health & Insurance": "⚕️",
      "Finanzen + Controlling": "📊",
  }
  default_icon = "🏷"
  pastel_colors = [
      "#FFCDD2", "#F8BBD0", "#E1BEE7", "#D1C4E9", "#C5CAE9", "#BBDEFB",
      "#B3E5FC", "#B2EBF2", "#B2DFDB", "#C8E6C9", "#DCEDC8", "#F0F4C3",
      "#FFF9C4", "#FFECB3", "#FFE0B2", "#FFCCBC", "#D7CCC8", "#CFD8DC",
  ]
  ordered = []
  for name in ["Cafe & Dine", "Groceries", "Entertainment", "Trips", "Health & Insurance", "Finanzen + Controlling"]:
    if name in existing_categories:
      ordered.append(name)
  for name in existing_categories:
    if name not in ordered:
      ordered.append(name)

  cols = []
  for name in ordered:
    idx = ordered.index(name)
    bg = pastel_colors[idx % len(pastel_colors)]
    fg = "#263238"
    icon = icon_by_name.get(name, default_icon)
    tile = html.Div(
        [
            html.Span(
                "REF",
                style={
                    "position": "absolute",
                    "top": "4px",
                    "left": "6px",
                    "fontSize": "8px",
                    "fontWeight": "600",
                    "letterSpacing": "0.06em",
                    "opacity": 0.8,
                },
            ),
            html.Div(icon, style={"fontSize": "16px", "marginBottom": "2px"}),
            html.Div(
                name,
                style={
                    "fontSize": "11px",
                    "fontWeight": "600",
                    "lineHeight": "1.2",
                },
            ),
        ],
        style={
            "position": "relative",
            "backgroundColor": bg,
            "color": fg,
            "borderRadius": "8px",
            "boxShadow": "0 1px 3px rgba(0,0,0,0.14)",
            "padding": "6px 4px 4px",
            "textAlign": "center",
            "minHeight": "70px",
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "justifyContent": "center",
        },
    )
    cols.append(dbc.Col(tile, width=3))

  rows = []
  for i in range(0, len(cols), 4):
    rows.append(dbc.Row(cols[i:i + 4], className="g-1", style={"marginBottom": "4px"}))
  return rows


def _category_options_from_df(df):
  """Build category dropdown options from pipeline data and config."""
  cat_col = "Display Category" if "Display Category" in df.columns else "Category"
  permitted_cats = [c for c in _load_permitted_categories() if c]
  permitted_set = set(permitted_cats) | {"Other"}
  seq_names = [s["name"] for s in load_sequences()]
  cats_from_df = []
  if not df.empty:
    for c in df[cat_col].dropna().unique():
      if not c:
        continue
      cs = str(c).strip()
      if " - " in cs or cs in permitted_set:
        cats_from_df.append(cs)
  return sorted(set(permitted_cats) | set(cats_from_df) | set(seq_names))


def _base_category_options_from_df(df):
  """Categories for the category pill row (no series names / combined labels)."""
  cat_col = "Display Category" if "Display Category" in df.columns else "Category"
  permitted_cats = [c for c in _load_permitted_categories() if c]
  seq_names = {s["name"] for s in load_sequences()}

  cats = set(permitted_cats)
  if not df.empty and cat_col in df.columns:
    for c in df[cat_col].dropna().unique():
      if not c:
        continue
      cs = str(c).strip()
      if not cs:
        continue
      if cs in seq_names:
        continue
      if " - " in cs:
        continue
      cats.add(cs)
  return sorted(cats)


def _source_options_from_df(df):
  if df.empty or "Source" not in df.columns:
    return []
  sources = set()
  for value in df["Source"].dropna().unique():
    label = str(value).strip()
    if label:
      sources.add(label)
  return sorted(sources)


def _transaction_currency_options_from_df(df):
  if df.empty or "Currency" not in df.columns:
    return []
  codes = {
      currency_conv.normalize_currency(c)
      for c in df["Currency"].dropna().unique()
  }
  return sorted(code for code in codes if code)


def _pill_button(label, pill_type, value, *, active=False, extra_class=""):
  cls = f"mt-pill mt-pill--{pill_type}"
  if active:
    cls += " mt-pill--active"
  if extra_class:
    cls += " " + extra_class
  return html.Button(
      label,
      id={"type": pill_type, "value": value},
      n_clicks=0,
      className=cls,
  )


def _pill_row(title, children):
  return html.Div(
      [
          html.Span(title, className="mt-pill-row-title"),
          html.Div(children, className="mt-pill-row"),
      ],
      className="mt-pill-row-wrap",
  )


def _toggle_pill_selection(selected, all_values, val):
  selected = list(selected or [])
  all_values = list(all_values or [])
  if val == "__all__":
    return all_values
  if val in selected:
    selected = [item for item in selected if item != val]
  else:
    selected.append(val)
  if not selected:
    selected = all_values
  return selected


def _active_pill_filter(selected, all_values):
  """Return values to pass to _filter_df, or None when all options are active."""
  selected = list(selected or [])
  all_values = list(all_values or [])
  if not all_values:
    return None
  if not selected or set(selected) >= set(all_values):
    return None
  return selected


def _is_maybe_income_refund_label(label):
  # Keep this loose: the UI shows "Income / Refund" as a special filter
  # even if the underlying category column uses a slightly different label.
  return str(label).strip().lower() in {
      str(INCOME_REFUND_CATEGORY).strip().lower(),
      "income/refund",
      "income / refund",
      "income & refund",
      "income + refund",
  }


def _build_app_layout(load_data=False):
  permitted_cats = [c for c in _load_permitted_categories() if c]
  seq_options = [{"label": s["name"], "value": s["name"]} for s in load_sequences()]
  initial_mappings = read_mappings_file()
  initial_categories = read_category_mapping_file()
  existing_categories = sorted({c for c in permitted_cats if c})

  if load_data:
    df = _load_data()
    min_date = df["Booking Date"].min().date() if not df.empty else None
    max_date = df["Booking Date"].max().date() if not df.empty else None
    all_cats = _base_category_options_from_df(df)
    all_sources = _source_options_from_df(df)
    all_tx_currencies = _transaction_currency_options_from_df(df)
    # Still used for the Sequences tab's "Main category" dropdown.
    cat_options = [{"label": c, "value": c} for c in all_cats]
    default_currency = _default_display_currency(df)
    currency_options = _display_currency_options(df)
    init_bar, init_pie, init_cumulative, init_table = _build_charts_outputs(
        df, min_date, max_date, all_cats, "month", display_currency=default_currency)
    load_status = _data_load_status(df)
    sequences = load_sequences()
    series_names = [s["name"] for s in sequences]
    df_base = _cached_run_pipeline()
    seq_expenses_children = _build_seq_expenses_table_content(
        df, min_date, max_date, default_currency)
    seq_all_frames_children = _build_seq_all_frames_content(
        sequences, df_base, display_currency=default_currency)
    seq_list_children = _build_seq_list_table(sequences, df_base)
    default_seq = sequences[0] if sequences else None
    default_seq_name = default_seq["name"] if default_seq else None
    default_rename = default_seq_name or ""
    default_category = (default_seq.get("category") or None) if default_seq else None
    default_timespan_options = _seq_timespan_dropdown_options(default_seq)
    seq_edit_children = (
        _build_seq_edit_panel_content(
            default_seq_name, sequences, df, display_currency=default_currency)
        if default_seq_name else _build_seq_edit_panel_placeholder()
    )
  else:
    min_date = max_date = None
    all_cats = []
    all_sources = []
    all_tx_currencies = []
    series_names = []
    cat_options = []
    default_currency = "EUR"
    currency_options = [{"label": "EUR", "value": "EUR"}]
    init_bar, init_pie, init_cumulative, _ = _build_charts_outputs(
        pd.DataFrame(), None, None, [], "month", display_currency=default_currency)
    init_table = _INIT_EXPENSES_TABLE_PLACEHOLDER
    load_status = html.Div(
        "Loading data from CSV folder…",
        style={"color": "#666", "fontStyle": "italic"},
    )
    seq_expenses_children = _INIT_SEQ_PLACEHOLDER
    seq_all_frames_children = _INIT_SEQ_PLACEHOLDER
    seq_list_children = _INIT_SEQ_PLACEHOLDER
    seq_edit_children = _INIT_SEQ_PLACEHOLDER
    default_seq_name = None
    default_rename = ""
    default_category = None
    default_timespan_options = []

  return html.Div(
    [
        dcc.Store(id="seq-revision", data=0),
        dcc.Store(id="assets-revision", data=0),
        dcc.Store(id="asset-card-messages", data={}),
        dcc.Store(id="seq-frame-modal-sequence", data=None),
        dcc.Store(id="seq-show-reference-table", data=False),
        dcc.Store(id="theme-store", storage_type="local", data=_DEFAULT_THEME),
        dcc.Store(id="charts-all-categories", data=all_cats),
        dcc.Store(id="charts-selected-categories", data=all_cats),
        dcc.Store(id="charts-all-sources", data=all_sources),
        dcc.Store(id="charts-selected-sources", data=all_sources),
        dcc.Store(id="charts-all-currencies", data=all_tx_currencies),
        dcc.Store(id="charts-selected-currencies", data=all_tx_currencies),
        dcc.Store(id="charts-exclude-series", data=False),
        dcc.Store(id="charts-selected-time-range", data=None),
        html.H1("Money Tracker", className="app-title"),
        html.Div(id="app-load-status", children=load_status),
        dcc.Download(id="report-pdf-download"),
        html.Div(
            [
                html.Label("Display amounts in"),
                dcc.Dropdown(
                    id="display-currency",
                    options=currency_options,
                    value=default_currency,
                    clearable=False,
                    style={"width": "140px"},
                ),
                html.Button(
                    "Export report (PDF)",
                    id="btn-export-report-pdf",
                    n_clicks=0,
                ),
                html.Button(
                    "Send report by email",
                    id="btn-send-report-email",
                    n_clicks=0,
                ),
                html.Div(id="report-email-status"),
                html.Div(_theme_toggle(), style={"marginLeft": "auto"}),
            ],
            className="mt-card",
            style={
                "display": "flex",
                "flexWrap": "wrap",
                "gap": "12px",
                "alignItems": "center",
                "marginBottom": "12px",
            },
        ),
        html.Div(
          [
            dcc.Tabs(
                id="main-tabs",
                value=_TAB_ASSETS,
                parent_className="mt-tabs-parent",
                className="mt-tabs",
                children=[
            dcc.Tab(label="Assets Overview", value=_TAB_ASSETS, className="mt-tab",
                    selected_className="mt-tab--selected",
                    style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE, children=[
                html.Div([
                    html.Div(id="assets-total-summary", children=_seq_loading_placeholder()),
                    html.Div([
                        html.Label("Display in"),
                        dcc.Dropdown(
                            id="assets-display-currency",
                            options=_assets_currency_options(),
                            value="EUR",
                            clearable=False,
                            style={"width": "120px"},
                        ),
                    ], className="mt-assets-total__currency"),
                ], className="mt-card mt-assets-total"),
                html.Div(dcc.Graph(
                    id="assets-total-chart",
                    figure=go.Figure(),
                    config={"responsive": True},
                    style=_GRAPH_STYLE,
                ), className="mt-card"),
                html.Div([
                    html.Button("Refresh all reports", id="btn-assets-refresh", n_clicks=0),
                    html.Button("Add asset", id="btn-add-asset", n_clicks=0),
                    html.Div(id="assets-ingest-status", className="mt-assets-status"),
                ], className="mt-card mt-assets-toolbar"),
                html.Div(id="assets-grid", className="mt-assets-grid",
                         children=_seq_loading_placeholder()),
                dbc.Modal(
                    [
                        dbc.ModalHeader(
                            dbc.ModalTitle("Add asset"),
                            close_button=True,
                        ),
                        dbc.ModalBody(_asset_add_modal_body()),
                        dbc.ModalFooter([
                            dbc.Button("Cancel", id="btn-asset-add-cancel", n_clicks=0,
                                       className="me-2"),
                            dbc.Button("Add asset", id="btn-asset-add-save", n_clicks=0,
                                       color="primary"),
                        ]),
                    ],
                    id="asset-add-modal",
                    is_open=False,
                    centered=True,
                ),
                html.Div(style={"height": "48px"}),
            ]),
            dcc.Tab(label="Expenses", value=_TAB_CHARTS, className="mt-tab",
                    selected_className="mt-tab--selected",
                    style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE, children=[
                html.Div([
                    html.Div(
                        id="charts-pill-filters",
                        className="mt-card mt-card--flush",
                        style={"marginBottom": "12px"},
                    ),
                    html.Label("Start date"),
                    dcc.DatePickerSingle(id="start-date", date=min_date,
                                         display_format="YYYY-MM-DD"),
                    html.Label("End date"),
                    dcc.DatePickerSingle(id="end-date", date=max_date,
                                         display_format="YYYY-MM-DD"),
                    html.Button(
                        "Update time range",
                        id="btn-update-charts-range",
                        n_clicks=0,
                        style={"display": "none"},
                    ),
                    html.Label("Period"),
                    dcc.RadioItems(id="period", options=[{"label": "Week", "value": "week"}, {
                        "label": "Month", "value": "month"}], value="month"),
                ], className="mt-card", style={"display": "flex", "flexWrap": "wrap", "gap": "16px", "alignItems": "center"}),
                html.Div(dcc.Graph(
                    id="pie-chart",
                    figure=init_pie,
                    style=_GRAPH_STYLE,
                    config={"responsive": True},
                ), className="mt-card"),
                html.Div(dcc.Graph(
                    id="cumulative-chart",
                    figure=init_cumulative,
                    style=_GRAPH_STYLE,
                    config={"responsive": True},
                ), className="mt-card"),
                html.Div(dcc.Graph(
                    id="bar-chart",
                    figure=init_bar,
                    style=_GRAPH_STYLE,
                    config={"responsive": True},
                ), className="mt-card"),
                html.H3("Expenses Table"),
                html.Div(
                    id="expenses-table-container",
                    children=init_table,
                    className="mt-card",
                ),
                html.Div(style={"height": "48px"}),
            ]),
            dcc.Tab(label="Sequences", value=_TAB_SEQUENCES, className="mt-tab",
                    selected_className="mt-tab--selected",
                    style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE, children=[
                # ---- Reference: date range and full expenses table ----
                html.H4("Reference: expenses in date range (use Index when adding/removing)"),
                html.Div([
                    html.Label("Start date"),
                    dcc.DatePickerSingle(id="seq-view-start",
                                         date=min_date, display_format="YYYY-MM-DD"),
                    html.Label("End date"),
                    dcc.DatePickerSingle(id="seq-view-end", date=max_date,
                                         display_format="YYYY-MM-DD"),
                ], className="mt-card", style={"display": "flex", "flexWrap": "wrap", "gap": "16px", "alignItems": "center"}),
                html.Button(
                    "Show expenses in date range",
                    id="btn-toggle-seq-reference",
                    n_clicks=0,
                    style={"marginBottom": "8px"},
                ),
                html.Div(
                    id="seq-expenses-table-container",
                    children=seq_expenses_children,
                    className="mt-card",
                    style={"display": "none"},
                ),
                # ---- All sequences: pie charts on a grid; expense tables on demand ----
                html.H4("All sequences"),
                html.Div(
                    id="seq-all-frames",
                    children=seq_all_frames_children,
                ),
                # ---- Create new sequence ----
                html.H4("Create new sequence"),
                html.Div([
                    html.Label("Name"),
                    dcc.Input(id="seq-name", type="text",
                              placeholder="e.g. Trip to Israel"),
                    html.Button("Create sequence", id="btn-create-seq", n_clicks=0),
                ], className="mt-card", style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "alignItems": "center"}),
                html.Div(id="seq-create-msg", style={"marginBottom": "20px"}),
                # ---- Select sequence and edit controls (all IDs must exist in layout) ----
                html.H4("Edit sequence"),
                html.Div([
                    html.Label("Select sequence"),
                    dcc.Dropdown(id="seq-select", options=seq_options, value=default_seq_name,
                                 placeholder="Select a sequence to edit", clearable=True),
                ], style={"margin": "10px", "marginBottom": "12px"}),
                html.Div(
                    [
                        html.Div([
                            html.Label("Rename sequence", style={
                                "display": "block", "marginBottom": "4px"}),
                            dcc.Input(id="seq-rename-value", type="text", value=default_rename,
                                      placeholder="New name",
                                      style={"marginRight": "8px", "width": "200px"}),
                            html.Button("Rename", id="btn-rename-seq", n_clicks=0),
                            html.Div(
                                id="seq-rename-msg", style={"marginTop": "4px", "fontSize": "13px", "color": "#333"}),
                        ], style={"marginBottom": "10px"}),
                        html.Div([
                            html.Label("Main category (for Charts)", style={
                                "display": "block", "marginBottom": "4px"}),
                            dcc.Dropdown(id="seq-category-value", options=cat_options, value=default_category,
                                         placeholder="Category", style={
                                "width": "220px", "display": "inline-block", "marginRight": "8px"}),
                            html.Button("Set category",
                                        id="btn-set-category", n_clicks=0),
                            html.Div(
                                id="seq-category-msg", style={"marginTop": "4px", "fontSize": "13px", "color": "#333"}),
                        ], style={"marginBottom": "10px"}),
                        html.Div([
                            html.Label("Add time span", style={
                                "display": "block", "marginBottom": "4px"}),
                            html.Div([
                                dcc.DatePickerSingle(id="seq-timespan-start",
                                                     date=min_date, display_format="YYYY-MM-DD"),
                                dcc.DatePickerSingle(id="seq-timespan-end",
                                                     date=max_date, display_format="YYYY-MM-DD"),
                                html.Button("Add time span",
                                            id="btn-add-timespan", n_clicks=0),
                            ], style={"display": "flex", "flexWrap": "wrap",
                                      "gap": "8px", "alignItems": "center"}),
                            html.Div(id="seq-timespan-msg",
                                     style={"marginTop": "4px", "fontSize": "13px"}),
                        ], style={"marginBottom": "10px"}),
                        html.Div([
                            html.Label("Remove time span", style={
                                "display": "block", "marginBottom": "4px"}),
                            dcc.Dropdown(id="seq-remove-timespan", options=default_timespan_options,
                                         placeholder="Select a time span to remove",
                                         clearable=True, style={"width": "240px", "display": "inline-block", "marginRight": "8px"}),
                            html.Button("Remove time span",
                                        id="btn-remove-timespan", n_clicks=0),
                            html.Div(id="seq-remove-timespan-msg",
                                     style={"marginTop": "4px", "fontSize": "13px"}),
                        ], style={"marginBottom": "10px"}),
                        html.Div([
                            html.Label("Add expenses (indices)", style={
                                "display": "block", "marginBottom": "4px"}),
                            dcc.Input(id="seq-indices", type="text", placeholder="e.g. 1, 5, 16-21",
                                      style={"width": "200px", "marginRight": "8px"}),
                            html.Button("Add expenses", id="btn-assign", n_clicks=0),
                            html.Div(id="seq-assign-msg",
                                     style={"marginTop": "4px", "fontSize": "13px"}),
                        ], style={"marginBottom": "10px"}),
                        html.Div([
                            html.Label("Remove expenses (indices)", style={
                                "display": "block", "marginBottom": "4px"}),
                            dcc.Input(id="seq-remove-index", type="text", placeholder="e.g. 15 or 1, 5, 16-21",
                                      style={"width": "200px", "marginRight": "8px"}),
                            html.Button("Remove from sequence",
                                        id="btn-remove-expense", n_clicks=0),
                            html.Div(id="seq-remove-msg",
                                     style={"marginTop": "4px", "fontSize": "13px"}),
                        ], style={"marginBottom": "10px"}),
                    ],
                    className="mt-card",
                ),
                html.Div(
                    id="seq-edit-panel",
                    children=seq_edit_children,
                    className="mt-card",
                ),
                html.Div([
                    html.Button(
                        "Add checked to sequence",
                        id="btn-add-checked",
                        n_clicks=0,
                        style={"marginRight": "8px"},
                    ),
                    html.Button(
                        "Remove checked from sequence",
                        id="btn-remove-checked",
                        n_clicks=0,
                    ),
                    html.Div(
                        id="seq-checked-msg",
                        style={"marginTop": "6px", "fontSize": "13px", "color": "#333"},
                    ),
                ], style={"marginBottom": "20px"}),
                # ---- All sequences summary table ----
                html.H4("All sequences and their expenses"),
                html.Div([html.Button("Refresh", id="btn-seq-refresh", n_clicks=0)],
                         style={"marginBottom": "8px"}),
                html.Div(
                    id="seq-list",
                    children=seq_list_children,
                    className="mt-card",
                    style={"maxHeight": "350px", "overflowY": "auto"},
                ),
                dbc.Modal(
                    [
                        dbc.ModalHeader(
                            dbc.ModalTitle(id="seq-frame-modal-title"),
                            close_button=True,
                        ),
                        dbc.ModalBody(id="seq-frame-modal-body"),
                        dbc.ModalFooter(
                            dbc.Button(
                                "Close",
                                id="seq-frame-modal-close",
                                className="ms-auto",
                                n_clicks=0,
                            ),
                        ),
                    ],
                    id="seq-frame-expenses-modal",
                    is_open=False,
                    size="xl",
                    scrollable=True,
                    centered=True,
                    className="mt-seq-expenses-modal",
                ),
                html.Div(style={"height": "48px"}),
            ]),
            dcc.Tab(label="Data & Mappings", value=_TAB_DATA, className="mt-tab",
                    selected_className="mt-tab--selected",
                    style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE, children=[
                html.P("Data files and conversion rules (partner names and categories).", style={
                       "marginBottom": "12px"}),
                html.Div([
                    html.Button("Refresh file list", id="files-refresh", n_clicks=0),
                    html.Span(id="files-base-dir",
                              style={"marginLeft": "12px", "color": "#666"}),
                ], style={"margin": "10px 0"}),
                html.Div(id="files-list", style={"marginBottom": "24px"}),
                html.H4("Partner name conversions (mappings.txt)",
                        style={"marginTop": "16px"}),
                html.P("From: pattern in bank description → To: normalized partner name.", style={
                       "fontSize": "13px", "color": "#555", "marginBottom": "8px"}),
                html.Div([
                    html.Button("Refresh", id="mappings-refresh",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Button("Add row", id="mappings-add-row",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Button("Save to file", id="mappings-save",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Span(
                        id="mappings-msg", style={"marginLeft": "8px", "fontSize": "13px", "color": "#333"}),
                ], style={"marginBottom": "8px"}),
                html.Div(
                    id="mappings-table-container",
                    children=[_build_mappings_table(
                        _mappings_table_data(initial_mappings))],
                    className="mt-card",
                    style={"overflow": "visible"},
                ),
                html.H4("Category mappings (category_mapping.txt)",
                        style={"marginTop": "16px"}),
                html.P("Partner name → Display category for charts and reports.", style={
                       "fontSize": "13px", "color": "#555", "marginBottom": "8px"}),
                html.Div([
                    html.Button("Refresh", id="category-refresh",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Button("Add row", id="category-add-row",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Button("Save to file", id="category-save",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Button("Auto-Categorize Missing", id="btn-auto-categorize",
                                n_clicks=0, style={"marginRight": "8px"}),
                    html.Button("Suggest (offline)", id="btn-suggest-offline",
                                n_clicks=0, style={"marginRight": "8px"}),
                    dcc.Loading(
                        id="category-auto-loading",
                        type="circle",
                        color="#1565c0",
                        parent_style={"display": "inline-block", "verticalAlign": "middle"},
                        children=html.Span(
                            id="category-auto-status",
                            children=_auto_cat_status_badge("Ready", "idle"),
                        ),
                    ),
                    html.Span(
                        id="category-msg", style={"marginLeft": "8px", "fontSize": "13px", "color": "#555"}),
                ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "4px"}),
                html.Div(
                    [
                        html.Span(
                            "Reference categories",
                            style={
                                "fontSize": "12px",
                                "color": "#555",
                                "display": "block",
                                "marginBottom": "6px",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.04em",
                            },
                        ),
                        html.Div(_build_category_reference_tiles(existing_categories)),
                    ],
                    style={"marginBottom": "10px"},
                ),
                html.Div(
                    id="category-table-container",
                    children=[_build_category_table(
                        _category_table_data(initial_categories))],
                    className="mt-card",
                    style={"overflow": "visible"},
                ),
                html.Div(style={"height": "48px"}),
            ]),
                ],
            ),
          ],
          className="mt-tabbar-wrap",
        ),
    ],
    id="main-container",
    style={
        "maxWidth": "1200px",
        "width": "95%",
        "margin": "0 auto",
        "padding": "10px",
    },
)


app.layout = _build_app_layout()


# Flip the persisted theme on toggle click.
app.clientside_callback(
    """
    function(n_clicks, current) {
        if (!n_clicks) { return window.dash_clientside.no_update; }
        return (current === 'dark') ? 'teal' : 'dark';
    }
    """,
    Output("theme-store", "data"),
    Input("theme-toggle", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)

# Apply the active theme to <html> (also on first load, restoring persistence)
# and label the toggle with the mode it will switch to.
app.clientside_callback(
    """
    function(theme) {
        theme = (theme === 'dark') ? 'dark' : 'teal';
        document.documentElement.setAttribute('data-theme', theme);
        return (theme === 'dark') ? 'Light' : 'Dark';
    }
    """,
    Output("theme-toggle-label", "children"),
    Input("theme-store", "data"),
)


@callback(
    [
        Output("bar-chart", "figure"),
        Output("pie-chart", "figure"),
        Output("cumulative-chart", "figure"),
        Output("expenses-table-container", "children"),
    ],
    [
        Input("btn-update-charts-range", "n_clicks"),
        Input("charts-selected-categories", "data"),
        Input("charts-selected-sources", "data"),
        Input("charts-selected-currencies", "data"),
        Input("charts-exclude-series", "data"),
        Input("period", "value"),
        Input("theme-store", "data"),
        Input("display-currency", "value"),
        Input("start-date", "date"),
        Input("end-date", "date"),
    ],
    prevent_initial_call=False,
)
def update_charts(
    _n_clicks,
    selected_categories,
    selected_sources,
    selected_currencies,
    exclude_series,
    period,
    theme,
    display_currency,
    start_date,
    end_date,
):
  df = _load_data()
  selected_categories = list(selected_categories or [])
  categories = list(dict.fromkeys(selected_categories))
  sources = _active_pill_filter(selected_sources, _source_options_from_df(df))
  currencies = _active_pill_filter(
      selected_currencies, _transaction_currency_options_from_df(df))
  return _build_charts_outputs(
      df,
      start_date,
      end_date,
      categories,
      period,
      theme,
      display_currency,
      exclude_series=bool(exclude_series),
      sources=sources,
      currencies=currencies,
  )


@callback(
    Output("charts-pill-filters", "children"),
    Input("charts-all-categories", "data"),
    Input("charts-selected-categories", "data"),
    Input("charts-all-sources", "data"),
    Input("charts-selected-sources", "data"),
    Input("charts-all-currencies", "data"),
    Input("charts-selected-currencies", "data"),
    Input("charts-exclude-series", "data"),
    Input("charts-selected-time-range", "data"),
)
def render_charts_pill_filters(
    all_categories,
    selected_categories,
    all_sources,
    selected_sources,
    all_currencies,
    selected_currencies,
    exclude_series,
    selected_time_range,
):
  all_categories = list(all_categories or [])
  selected_categories = list(selected_categories or [])
  all_sources = list(all_sources or [])
  selected_sources = list(selected_sources or [])
  all_currencies = list(all_currencies or [])
  selected_currencies = list(selected_currencies or [])

  def _pill_children(all_values, selected_values, pill_type, *, extra_class_fn=None):
    all_set = set(all_values)
    sel_set = set(selected_values or [])
    all_active = bool(all_values) and (not selected_values or sel_set == all_set)
    children = [
        _pill_button("All", pill_type, "__all__", active=all_active),
    ]
    for value in all_values:
      active = all_active or (value in sel_set)
      extra_class = extra_class_fn(value) if extra_class_fn else ""
      children.append(
          _pill_button(value, pill_type, value, active=active, extra_class=extra_class)
      )
    return children

  cat_children = _pill_children(
      all_categories,
      selected_categories,
      "charts-category-pill",
      extra_class_fn=(
          lambda c: "mt-pill--income-refund" if _is_maybe_income_refund_label(c) else ""
      ),
  )

  options_children = [
      _pill_button("Exclude series", "charts-exclude-series-pill", "exclude", active=bool(exclude_series)),
  ]

  time_children = [
      _pill_button("All", "charts-time-pill", "all", active=(selected_time_range == "all")),
      _pill_button("1W", "charts-time-pill", "1w", active=(selected_time_range == "1w")),
      _pill_button("1M", "charts-time-pill", "1m", active=(selected_time_range == "1m")),
      _pill_button("1Y", "charts-time-pill", "1y", active=(selected_time_range == "1y")),
      _pill_button("MTD", "charts-time-pill", "mtd", active=(selected_time_range == "mtd")),
  ]

  rows = [
      _pill_row("Category", cat_children),
  ]
  if all_sources:
    rows.append(_pill_row("Source", _pill_children(all_sources, selected_sources, "charts-source-pill")))
  if all_currencies:
    rows.append(
        _pill_row("Currency", _pill_children(all_currencies, selected_currencies, "charts-currency-pill"))
    )
  rows.extend([
      _pill_row("Options", options_children),
      _pill_row("Time range", time_children),
  ])
  return rows


@callback(
    Output("charts-selected-time-range", "data"),
    Input({"type": "charts-time-pill", "value": ALL}, "n_clicks_timestamp"),
    State("charts-selected-time-range", "data"),
    prevent_initial_call=True,
)
def on_charts_time_pill_active(_timestamps, current):
  # Use the max timestamp to identify the clicked pill (robust to re-renders).
  inputs = (callback_context.inputs_list or [])
  pill_inputs = inputs[0] if inputs else []
  if not pill_inputs:
    raise PreventUpdate
  latest = max(pill_inputs, key=lambda it: it.get("value") or 0)
  ts = latest.get("value") or 0
  if ts <= 0:
    raise PreventUpdate
  pill_id = latest.get("id") or {}
  val = pill_id.get("value")
  return None if current == val else val


@callback(
    Output("charts-selected-categories", "data"),
    Input({"type": "charts-category-pill", "value": ALL}, "n_clicks"),
    State("charts-selected-categories", "data"),
    State("charts-all-categories", "data"),
    prevent_initial_call=True,
)
def on_charts_pills(_cat_clicks, selected_categories, all_categories):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if not (isinstance(triggered, dict) and triggered.get("type") == "charts-category-pill"):
    raise PreventUpdate
  return _toggle_pill_selection(selected_categories, all_categories, triggered.get("value"))


@callback(
    Output("charts-selected-sources", "data"),
    Input({"type": "charts-source-pill", "value": ALL}, "n_clicks"),
    State("charts-selected-sources", "data"),
    State("charts-all-sources", "data"),
    prevent_initial_call=True,
)
def on_charts_source_pills(_clicks, selected_sources, all_sources):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if not (isinstance(triggered, dict) and triggered.get("type") == "charts-source-pill"):
    raise PreventUpdate
  return _toggle_pill_selection(selected_sources, all_sources, triggered.get("value"))


@callback(
    Output("charts-selected-currencies", "data"),
    Input({"type": "charts-currency-pill", "value": ALL}, "n_clicks"),
    State("charts-selected-currencies", "data"),
    State("charts-all-currencies", "data"),
    prevent_initial_call=True,
)
def on_charts_currency_pills(_clicks, selected_currencies, all_currencies):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if not (isinstance(triggered, dict) and triggered.get("type") == "charts-currency-pill"):
    raise PreventUpdate
  return _toggle_pill_selection(selected_currencies, all_currencies, triggered.get("value"))


@callback(
    Output("charts-exclude-series", "data"),
    Input({"type": "charts-exclude-series-pill", "value": ALL}, "n_clicks"),
    State("charts-exclude-series", "data"),
    prevent_initial_call=True,
)
def on_exclude_series_pill(_clicks, current):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if not (isinstance(triggered, dict) and triggered.get("type") == "charts-exclude-series-pill"):
    raise PreventUpdate
  return not bool(current)


@callback(
    Output("start-date", "date"),
    Output("end-date", "date"),
    Input({"type": "charts-time-pill", "value": ALL}, "n_clicks_timestamp"),
    State("end-date", "date"),
    prevent_initial_call=True,
)
def on_charts_time_range(_timestamps, current_end_date):
  # Identify the clicked pill via the max timestamp (robust to re-renders).
  inputs = (callback_context.inputs_list or [])
  pill_inputs = inputs[0] if inputs else []
  if not pill_inputs:
    raise PreventUpdate
  latest = max(pill_inputs, key=lambda it: it.get("value") or 0)
  ts = latest.get("value") or 0
  if ts <= 0:
    raise PreventUpdate
  pill_id = latest.get("id") or {}
  key = pill_id.get("value")

  # Anchor ranges to the latest transaction date (dataset max), so presets
  # don't jump around based on an old end-date picker value.
  df = _load_data()
  max_date = None
  if df is not None and not df.empty and "Booking Date" in df.columns:
    max_ts = pd.to_datetime(df["Booking Date"], errors="coerce").max()
    if pd.notna(max_ts):
      max_date = max_ts.date()
  if key == "all":
    if df is None or df.empty or "Booking Date" not in df.columns:
      raise PreventUpdate
    start = pd.to_datetime(df["Booking Date"], errors="coerce").min()
    end = pd.to_datetime(df["Booking Date"], errors="coerce").max()
    if pd.isna(start) or pd.isna(end):
      raise PreventUpdate
    return start.date().isoformat(), end.date().isoformat()

  end = max_date or dt.date.today()
  if key == "1w":
    start = end - dt.timedelta(days=7)
  elif key == "1m":
    start = end - dt.timedelta(days=30)
  elif key == "1y":
    start = end - dt.timedelta(days=365)
  elif key == "mtd":
    start = end.replace(day=1)
  else:
    raise PreventUpdate
  return start.isoformat(), end.isoformat()


def _fig_pie_small(
    df_by_cat,
    title="Category distribution",
    theme=_DEFAULT_THEME,
    display_currency="EUR",
):
  """Small pie chart from a series or dataframe with Category and Amount (use converted if present)."""
  def _empty():
    fig = px.pie(title=title)
    fig.update_layout(height=300, margin=dict(t=40, b=24, l=20, r=20))
    return _apply_chart_theme(fig, theme)

  if df_by_cat is None or df_by_cat.empty:
    return _empty()
  amt_col = _pick_amount_col(df_by_cat, display_currency)
  if amt_col not in df_by_cat.columns and hasattr(df_by_cat, "sum"):
    s = df_by_cat
  else:
    s = df_by_cat.groupby("Category")[amt_col].sum()
  s = s.abs()
  if s.empty:
    return _empty()
  labels = [str(v) for v in list(s.index)]
  values = list(s.values)
  colors = [_stable_color_for_label(lbl, theme) for lbl in labels]
  fig = go.Figure(
      go.Pie(
          labels=labels,
          values=values,
          hole=0.5,
          sort=False,
          marker=dict(colors=colors, line=dict(color=_theme_palette(theme)["paper"], width=1.5)),
          textinfo="percent+label",
          textposition="inside",
          name="",
      )
  )
  fig.update_layout(title=title, height=300, margin=dict(t=40, b=24, l=20, r=20))
  return _apply_chart_theme(fig, theme)


def _build_seq_expenses_table_content(df, start_date, end_date, display_currency="EUR"):
  cat_col = "Display Category" if not df.empty and "Display Category" in df.columns else "Category"
  empty_panel = _scrollable_table_panel(
      "seq-expenses-table-scroll",
      "seq-expenses-table-viewport-info",
      _empty_seq_expenses_table(cat_col),
      _SEQ_EXPENSES_TABLE_VIEWPORT_HEIGHT,
  )
  if df.empty:
    return html.Div([html.P("No data available.", style={"marginBottom": "4px"}), empty_panel])
  filtered, cat_col = _filter_df(df, start_date, end_date, None)
  if filtered.empty:
    return html.Div([html.P("No data for selected date range.", style={"marginBottom": "4px"}), empty_panel])
  amt_col = _pick_amount_col(filtered, display_currency)
  amount_header = currency_conv.amount_axis_label(display_currency)
  base_cols = _expense_table_base_cols(filtered, cat_col)
  display_df = filtered[base_cols + [amt_col]].copy()
  display_df = display_df.rename(columns={amt_col: amount_header})
  display_df.insert(0, "Index", display_df.index)
  display_df = display_df.sort_values("Booking Date", ascending=False)
  display_df["Booking Date"] = display_df["Booking Date"].dt.strftime("%Y-%m-%d")
  display_df[amount_header] = display_df[amount_header].apply(
      lambda x: f"{x:.2f}" if pd.notna(x) else "")
  table = DataTable(
      id="seq-expenses-table",
      data=display_df.to_dict("records"),
      columns=_data_table_column_defs(list(display_df.columns)),
      style_cell=_TABLE_CELL_STYLE,
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE | {"whiteSpace": "normal", "height": "auto"},
      page_size=_SEQ_EXPENSES_TABLE_PAGE_SIZE,
      sort_action="native",
  )
  return html.Div([
      _scrollable_table_panel(
          "seq-expenses-table-scroll",
          "seq-expenses-table-viewport-info",
          table,
          _SEQ_EXPENSES_TABLE_VIEWPORT_HEIGHT,
      ),
  ])


def _build_seq_all_frames_content(
    sequences,
    df_base,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
):
  if not sequences:
    return html.Div("No sequences yet. Create one below.", className="mt-muted",
                    style={"fontStyle": "italic"})
  def _seq_last_date(seq):
    try:
      indices = get_sequence_expense_indices(seq, df_base)
    except Exception:
      indices = []
    if not indices:
      return pd.Timestamp.min
    col = "Booking Date" if "Booking Date" in df_base.columns else None
    if not col:
      return pd.Timestamp.min
    s = pd.to_datetime(df_base.loc[df_base.index.isin(indices), col], errors="coerce")
    if s.empty:
      return pd.Timestamp.min
    last = s.max()
    return last if pd.notna(last) else pd.Timestamp.min

  sequences = sorted(list(sequences), key=_seq_last_date, reverse=True)
  frames = [
      _build_sequence_frame(s["name"], s, df_base, sequences, theme, display_currency)
      for s in sequences
  ]
  return html.Div(frames, className="mt-seq-grid")


def _build_seq_list_table(sequences, df_base):
  table_df = sequences_expenses_df(df_base, sequences)
  if table_df.empty:
    return html.Div("No expenses in any sequence yet.")
  display_df = table_df.copy()
  display_df["Booking Date"] = pd.to_datetime(display_df["Booking Date"]).dt.strftime("%Y-%m-%d")
  amt_col = "Amount (EUR) converted" if "Amount (EUR) converted" in display_df.columns else "Amount (EUR)"
  display_df[amt_col] = display_df[amt_col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")
  return DataTable(
      data=display_df.to_dict("records"),
      columns=[{"name": col, "id": col} for col in display_df.columns],
      style_cell=_TABLE_CELL_STYLE,
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE | {"whiteSpace": "normal", "height": "auto"},
      page_size=50,
      sort_action="native",
  )


def _seq_timespan_dropdown_options(seq):
  spans = seq.get("time_spans", []) if seq else []
  return [
      {"label": f"{s['start']} to {s['end']}", "value": f"{s['start']}|{s['end']}"}
      for s in spans
  ]


def _build_seq_edit_panel_content(
    seq_name,
    sequences,
    df_base,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
):
  seq = next((s for s in sequences if s["name"] == seq_name), None)
  if not seq:
    return html.Div("Sequence not found.")
  seq_df = sequence_expenses_df(
      df_base, seq_name, sequences, display_currency=display_currency)
  pie_fig = _fig_pie_small(
      seq_df, title=f"Categories in '{seq_name}'", theme=theme, display_currency=display_currency)
  cat_col = "Display Category" if "Display Category" in df_base.columns else "Category"
  display_df = _prepare_seq_edit_expenses_display(df_base, seq, display_currency)
  if not display_df.empty and "Display Category" in display_df.columns:
    cat_col = "Display Category"
  elif not display_df.empty and "Category" in display_df.columns:
    cat_col = "Category"
  expenses_table = _build_seq_edit_expenses_table(display_df, cat_col, selectable=True)
  in_count = int((display_df["In sequence"] == "Yes").sum()) if not display_df.empty else 0
  total_count = len(display_df)
  spans = seq.get("time_spans", [])
  span_text = ", ".join(f"{s['start']} – {s['end']}" for s in spans) if spans else "(none)"
  return html.Div([
      html.Div([html.Strong(f"Sequence: {seq_name}")], style={"marginBottom": "8px"}),
      html.Div(
          f"Category: {seq.get('category') or '(none)'} · Time spans: {span_text}",
          style={"marginBottom": "12px", "color": "#555", "fontSize": "14px"},
      ),
      html.Div([
          html.Div(dcc.Graph(figure=pie_fig, config={"staticPlot": False}), style={
                   "width": "280px", "display": "inline-block"}),
      ], style={"marginBottom": "12px"}),
      html.Label(
          f"All expenses ({in_count} in sequence, {total_count} total). "
          "Check rows below, then use the buttons beneath this panel.",
          style={"display": "block", "marginBottom": "6px"}),
      html.Div(
          expenses_table,
          style={"maxHeight": _SEQ_EDIT_EXPENSES_VIEWPORT_HEIGHT, "overflowY": "auto"},
      ),
  ])


def _build_seq_edit_panel_placeholder():
  return html.Div([
      html.Div(
          "Select a sequence above to edit it (use controls above for rename, category, time spans, expenses)."),
      html.P(
          "The full expenses list with checkboxes appears once you select a sequence.",
          style={"marginTop": "12px", "color": "#333", "fontStyle": "italic"},
      ),
  ])


@callback(
    Output("seq-expenses-table-container", "children"),
    [
        Input("main-tabs", "value"),
        Input("seq-view-start", "date"),
        Input("seq-view-end", "date"),
        Input("seq-revision", "data"),
        Input("display-currency", "value"),
    ],
)
def update_seq_expenses_table(tab, start_date, end_date, _revision, display_currency="EUR"):
  if not _sequences_tab_active(tab):
    raise PreventUpdate
  return _build_seq_expenses_table_content(
      _load_data(), start_date, end_date, display_currency)


def _format_sequence_frame_expenses_df(seq_df):
  if seq_df.empty:
    return seq_df
  disp = seq_df.copy()
  disp["Booking Date"] = pd.to_datetime(disp["Booking Date"]).dt.strftime("%Y-%m-%d")
  amt_col = "Amount (EUR) converted" if "Amount (EUR) converted" in disp.columns else "Amount (EUR)"
  disp[amt_col] = disp[amt_col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")
  if amt_col != "Amount (EUR) converted":
    disp = disp.rename(columns={amt_col: "Amount (EUR) converted"})
  return disp


def _build_sequence_frame_modal_content(seq_name, df_base, sequences):
  seq_df = sequence_expenses_df(df_base, seq_name, sequences)
  title = f"Expenses — {seq_name}"
  if seq_df.empty:
    return title, html.P("No expenses in this sequence yet.", className="mt-muted")
  disp = _format_sequence_frame_expenses_df(seq_df)
  table = DataTable(
      data=disp.to_dict("records"),
      columns=[{"name": col, "id": col} for col in disp.columns],
      style_cell=_TABLE_CELL_STYLE,
      style_header=_TABLE_HEADER_STYLE,
      style_data=_TABLE_DATA_STYLE,
      page_size=_SEQ_FRAME_MODAL_TABLE_PAGE_SIZE,
      sort_action="native",
      filter_action="native",
  )
  body = html.Div([
      html.P(f"{len(disp)} expense(s)", className="mt-muted", style={"marginBottom": "8px"}),
      html.Div(
          table,
          className="seq-frame-modal-table-wrap",
          style={"maxHeight": _SEQ_FRAME_MODAL_TABLE_HEIGHT, "overflowY": "auto"},
      ),
  ])
  return title, body


def _build_sequence_frame(
    seq_name,
    seq,
    df_base,
    sequences,
    theme=_DEFAULT_THEME,
    display_currency="EUR",
):
  """Build one grid cell: title, category, pie chart; expenses open in a modal."""
  seq_df = sequence_expenses_df(
      df_base, seq_name, sequences, display_currency=display_currency)
  pie_fig = _fig_pie_small(
      seq_df, title=f"Categories in '{seq_name}'", theme=theme, display_currency=display_currency)
  cat = seq.get("category") or "(none)"
  amt_col = _pick_amount_col(seq_df, display_currency)
  unit = currency_conv.normalize_currency(display_currency)
  total = seq_df[amt_col].sum() if not seq_df.empty and amt_col in seq_df.columns else 0
  total_str = f"{total:.2f} {unit}"
  expense_count = len(seq_df)
  return html.Div([
      html.Div([
          html.Strong(f"{seq_name}"),
          html.Span(f" — {cat}", className="mt-muted", style={"fontSize": "14px"}),
          html.Span(f" — Total: {total_str}", className="mt-muted", style={
                    "fontSize": "14px", "marginLeft": "8px"}),
      ], style={"marginBottom": "8px"}),
      html.Div(
          dcc.Graph(
              figure=pie_fig,
              config={"staticPlot": False, "displayModeBar": False, "responsive": True},
          ),
          className="mt-seq-plot",
      ),
      html.Button(
          f"Show expenses ({expense_count})",
          id={"type": "seq-show-expenses", "index": seq_name},
          n_clicks=0,
          style={"marginTop": "4px"},
      ),
  ], className="mt-card mt-card--flush mt-seq-frame")


@callback(
    Output("seq-frame-modal-sequence", "data"),
    [
        Input({"type": "seq-show-expenses", "index": ALL}, "n_clicks"),
        Input("seq-frame-modal-close", "n_clicks"),
        Input("seq-frame-expenses-modal", "is_open"),
        Input("main-tabs", "value"),
    ],
    prevent_initial_call=True,
)
def seq_frame_modal_sequence(_open_clicks, _close_clicks, is_open, tab):
  triggered = callback_context.triggered_id
  if triggered == "main-tabs":
    if not _sequences_tab_active(tab):
      return None
    raise PreventUpdate
  if triggered in ("seq-frame-modal-close", "seq-frame-expenses-modal"):
    if triggered == "seq-frame-expenses-modal" and is_open:
      raise PreventUpdate
    return None
  if isinstance(triggered, dict) and triggered.get("type") == "seq-show-expenses":
    return triggered["index"]
  raise PreventUpdate


@callback(
    Output("seq-frame-expenses-modal", "is_open"),
    Input("seq-frame-modal-sequence", "data"),
)
def seq_frame_modal_is_open(seq_name):
  return seq_name is not None


@callback(
    Output("seq-frame-modal-title", "children"),
    Output("seq-frame-modal-body", "children"),
    [
        Input("seq-frame-modal-sequence", "data"),
        Input("seq-revision", "data"),
    ],
)
def update_seq_frame_modal_content(seq_name, _revision):
  if not seq_name:
    return "", html.Div()
  sequences = load_sequences()
  df_base = _cached_run_pipeline()
  return _build_sequence_frame_modal_content(seq_name, df_base, sequences)


@callback(
    Output("seq-show-reference-table", "data"),
    Input("btn-toggle-seq-reference", "n_clicks"),
    State("seq-show-reference-table", "data"),
    prevent_initial_call=True,
)
def toggle_seq_reference_table(_n_clicks, visible):
  return not bool(visible)


@callback(
    Output("seq-expenses-table-container", "style"),
    Output("btn-toggle-seq-reference", "children"),
    Input("seq-show-reference-table", "data"),
)
def sync_seq_reference_table_visibility(visible):
  if visible:
    return {}, "Hide expenses in date range"
  return {"display": "none"}, "Show expenses in date range"


@callback(
    Output("seq-all-frames", "children"),
    [
        Input("main-tabs", "value"),
        Input("seq-revision", "data"),
        Input("theme-store", "data"),
        Input("display-currency", "value"),
    ],
)
def update_seq_all_frames(tab, _revision, theme=_DEFAULT_THEME, display_currency="EUR"):
  """Show one frame per sequence in a grid; expenses open in a modal."""
  if not _sequences_tab_active(tab):
    raise PreventUpdate
  sequences = load_sequences()
  if not sequences:
    return html.Div("No sequences yet. Create one below.", className="mt-muted",
                    style={"fontStyle": "italic"})
  df_base = _cached_run_pipeline()
  return _build_seq_all_frames_content(sequences, df_base, theme, display_currency)


@callback(
    Output("seq-create-msg", "children"),
    Input("btn-create-seq", "n_clicks"),
    State("seq-name", "value"),
    prevent_initial_call=True,
)
def on_create_sequence(n_clicks, name):
  if not name or not name.strip():
    return "Please enter a sequence name."
  create_sequence(name.strip(), allow_write=True)
  return f"Sequence '{name.strip()}' created (empty)."



@callback(
    Output("seq-edit-panel", "children"),
    [
        Input("main-tabs", "value"),
        Input("seq-select", "value"),
        Input("seq-revision", "data"),
        Input("theme-store", "data"),
        Input("display-currency", "value"),
    ],
)
def update_seq_edit_panel(tab, seq_name, _revision, theme=_DEFAULT_THEME, display_currency="EUR"):
  if not _sequences_tab_active(tab):
    raise PreventUpdate
  if not seq_name:
    return _build_seq_edit_panel_placeholder()
  sequences = load_sequences()
  return _build_seq_edit_panel_content(
      seq_name, sequences, _load_data(), theme, display_currency)


@callback(
    [
        Output("seq-rename-value", "value"),
        Output("seq-category-value", "value"),
        Output("seq-remove-timespan", "options"),
        Output("seq-remove-timespan", "value"),
        Output("seq-remove-timespan-msg", "children"),
    ],
    [
        Input("seq-select", "value"),
        Input("btn-remove-timespan", "n_clicks"),
    ],
    [
        State("seq-select", "value"),
        State("seq-remove-timespan", "value"),
    ],
)
def sync_seq_edit_inputs_and_remove_timespan(seq_select_value, n_remove_clicks, state_seq_name, state_remove_value):
  """Sync rename/category/dropdown when sequence changes; or remove time span and refresh dropdown when button clicked."""
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if triggered == "btn-remove-timespan":
    if not state_seq_name:
      return no_update, no_update, no_update, no_update, "Select a sequence first."
    if not state_remove_value or "|" not in state_remove_value:
      return no_update, no_update, no_update, no_update, "Select a time span to remove."
    start_date, end_date = state_remove_value.split("|", 1)
    start_date, end_date = start_date.strip(), end_date.strip()
    try:
      remove_timespan(state_seq_name, start_date, end_date, allow_write=True)
    except ValueError as e:
      return no_update, no_update, no_update, no_update, str(e)
    sequences = load_sequences()
    seq = next((s for s in sequences if s["name"] == state_seq_name), None)
    options = _seq_timespan_dropdown_options(seq)
    return no_update, no_update, options, None, f"Time span {start_date} to {end_date} removed."
  # Triggered by seq-select or initial load
  if not seq_select_value:
    return "", None, [], None, no_update
  sequences = load_sequences()
  seq = next((s for s in sequences if s["name"] == seq_select_value), None)
  if not seq:
    return seq_select_value, None, [], None, no_update
  return seq_select_value, seq.get("category") or None, _seq_timespan_dropdown_options(seq), None, no_update


@callback(
    Output("seq-checked-msg", "children"),
    [
        Input("btn-add-checked", "n_clicks"),
        Input("btn-remove-checked", "n_clicks"),
    ],
    [
        State("seq-edit-expenses-table", "derived_virtual_selected_rows"),
        State("seq-edit-expenses-table", "data"),
        State("seq-select", "value"),
    ],
    prevent_initial_call=True,
)
def on_checked_sequence_actions(n_add, n_remove, selected_rows, data, seq_name):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if not seq_name:
    return "Select a sequence first."
  if not data or not selected_rows:
    return "Check one or more rows in the table above."
  indices = [
      int(data[i]["Index"])
      for i in selected_rows
      if i < len(data) and data[i].get("Index") is not None
  ]
  if not indices:
    return "No valid rows selected."
  if triggered == "btn-add-checked":
    add_expenses_to_sequence(seq_name, indices, allow_write=True)
    return f"Added {len(indices)} expense(s) to sequence."
  if triggered == "btn-remove-checked":
    remove_expenses_from_sequence(seq_name, indices, allow_write=True)
    return f"Removed {len(indices)} expense(s) from sequence."
  return no_update


@callback(
    Output("seq-timespan-msg", "children"),
    Input("btn-add-timespan", "n_clicks"),
    State("seq-select", "value"),
    State("seq-timespan-start", "date"),
    State("seq-timespan-end", "date"),
    prevent_initial_call=True,
)
def on_add_timespan(n_clicks, seq_name, start_date, end_date):
  if not seq_name:
    return "Select a sequence first."
  if not start_date or not end_date:
    return "Select start and end date."
  try:
    add_timespan(seq_name, start_date, end_date, allow_write=True)
    return f"Time span {start_date} to {end_date} added."
  except ValueError as e:
    return str(e)


@callback(
    Output("seq-assign-msg", "children"),
    Input("btn-assign", "n_clicks"),
    State("seq-select", "value"),
    State("seq-indices", "value"),
    prevent_initial_call=True,
)
def on_assign(n_clicks, seq_name, indices_str):
  if not seq_name:
    return "Select a sequence first."
  if not indices_str or not indices_str.strip():
    return "Enter expense indices (e.g. 1, 5, 16-21)."
  try:
    indices = parse_indices_string(indices_str)
    if not indices:
      return "No valid indices found (use e.g. 1, 5, 16-21)."
    add_expenses_to_sequence(seq_name, indices, allow_write=True)
    return f"Added {len(indices)} expenses."
  except ValueError as e:
    return str(e)


@callback(
    Output("seq-remove-msg", "children"),
    Input("btn-remove-expense", "n_clicks"),
    State("seq-select", "value"),
    State("seq-remove-index", "value"),
    prevent_initial_call=True,
)
def on_remove_expense(n_clicks, seq_name, index_str):
  if not seq_name:
    return "Select a sequence first."
  if index_str is None or str(index_str).strip() == "":
    return "Enter indices to remove (e.g. 15 or 1, 5, 16-21)."
  try:
    indices = parse_indices_string(index_str)
    if not indices:
      return "No valid indices found (use e.g. 15 or 1, 5, 16-21)."
    remove_expenses_from_sequence(seq_name, indices, allow_write=True)
    return f"Removed {len(indices)} expense(s)."
  except ValueError as e:
    return str(e)


@callback(
    [Output("seq-rename-msg", "children"), Output("seq-select", "value")],
    Input("btn-rename-seq", "n_clicks"),
    State("seq-select", "value"),
    State("seq-rename-value", "value"),
    prevent_initial_call=True,
)
def on_rename_sequence(n_clicks, old_name, new_name):
  if not old_name:
    return "Select a sequence first.", no_update
  if not new_name or not str(new_name).strip():
    return "Enter a new name.", no_update
  new_name = str(new_name).strip()
  if new_name == old_name:
    return "Name unchanged.", no_update
  try:
    rename_sequence(old_name, new_name, allow_write=True)
    return f"Renamed to '{new_name}'.", new_name  # keep selection on renamed sequence
  except ValueError as e:
    return str(e), no_update


@callback(
    Output("seq-category-msg", "children"),
    Input("btn-set-category", "n_clicks"),
    State("seq-select", "value"),
    State("seq-category-value", "value"),
    prevent_initial_call=True,
)
def on_set_category(n_clicks, seq_name, category):
  if not seq_name:
    return "Select a sequence first."
  try:
    set_sequence_category(seq_name, category or "", allow_write=True)
    return f"Main category set to '{category or '(none)'}'."
  except ValueError as e:
    return str(e)


@callback(
    [
        Output("seq-list", "children"),
        Output("seq-select", "options"),
    ],
    [
        Input("main-tabs", "value"),
        Input("seq-revision", "data"),
    ],
)
def update_seq_list(tab, _revision):
  if not _sequences_tab_active(tab):
    raise PreventUpdate
  sequences = load_sequences()
  options = [{"label": s["name"], "value": s["name"]} for s in sequences]
  df_base = _cached_run_pipeline()
  return _build_seq_list_table(sequences, df_base), options


@callback(
    Output("seq-revision", "data"),
    [
        Input("btn-create-seq", "n_clicks"),
        Input("btn-add-timespan", "n_clicks"),
        Input("btn-remove-timespan", "n_clicks"),
        Input("btn-assign", "n_clicks"),
        Input("btn-remove-expense", "n_clicks"),
        Input("btn-seq-refresh", "n_clicks"),
        Input("btn-rename-seq", "n_clicks"),
        Input("btn-set-category", "n_clicks"),
        Input("btn-add-checked", "n_clicks"),
        Input("btn-remove-checked", "n_clicks"),
    ],
    State("seq-revision", "data"),
    prevent_initial_call=True,
)
def bump_seq_revision(_n1, _n2, _n3, _n4, _n5, _n6, _n7, _n8, _n9, _n10, revision):
  return (revision or 0) + 1


@callback(
    [Output("mappings-table-container", "children"),
     Output("mappings-msg", "children")],
    [Input("mappings-refresh", "n_clicks"), Input("mappings-save",
                                                  "n_clicks"), Input("mappings-add-row", "n_clicks")],
    State("mappings-table", "data"),
    prevent_initial_call=True,
)
def mappings_table_action(_refresh, _save, _add, data):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if triggered == "mappings-refresh":
    rows = read_mappings_file()
    return [_build_mappings_table(_mappings_table_data(rows))], no_update
  if triggered == "mappings-save":
    if not data:
      return no_update, "No data to save."
    rows = [((d.get("From") or "").strip(), (d.get("To") or "").strip()) for d in data]
    rows = [r for r in rows if r[0] or r[1]]
    write_mappings_file(rows, allow_write=True)
    return [_build_mappings_table(_mappings_table_data(rows))], "Saved."
  if triggered == "mappings-add-row":
    new_data = (data or []) + [{"From": "", "To": ""}]
    return [_build_mappings_table(new_data)], no_update
  return no_update, no_update


@callback(
    [Output("category-table-container", "children"),
     Output("category-msg", "children")],
    [Input("category-refresh", "n_clicks"), Input("category-save",
                                                  "n_clicks"), Input("category-add-row", "n_clicks")],
    State("category-table", "data"),
    prevent_initial_call=True,
)
def category_table_action(_refresh, _save, _add, data):
  triggered = callback_context.triggered_id if callback_context.triggered else None
  if triggered == "category-refresh":
    rows = read_category_mapping_file()
    return [_build_category_table(_category_table_data(rows))], no_update
  if triggered == "category-save":
    if not data:
      return no_update, "No data to save."
    existing = dict(read_category_mapping_file())
    for d in data:
      partner = (d.get("Partner") or "").strip()
      if not partner:
        continue
      cat = (d.get("Category") or "").strip()
      if is_income_refund_category(cat):
        cat = ""
      existing[partner] = cat
    rows = list(existing.items())
    write_category_mapping_file(rows, allow_write=True)
    return [_build_category_table(_category_table_data(rows))], "Saved."
  if triggered == "category-add-row":
    new_data = list(data or [])
    new_data.append({"Partner": "", "Category": ""})
    return [_build_category_table(new_data)], no_update
  return no_update, no_update


@callback(
    [Output("category-table-container", "children", allow_duplicate=True),
     Output("category-auto-status", "children"),
     Output("category-msg", "children", allow_duplicate=True)],
    Input("btn-auto-categorize", "n_clicks"),
    State("category-table", "data"),
    prevent_initial_call=True,
)
def auto_categorize_missing(n_clicks, data):
  if not n_clicks or not data:
    return no_update, no_update, no_update
  if not _genai_client:
    return no_update, _auto_cat_status_badge(
        f"No API key — copy .env.example to .env and set GEMINI_API_KEY ({env_config.env_setup_hint()})",
        "error",
    ), ""
  permitted = [c for c in _load_permitted_categories() if c and not is_income_refund_category(c)]
  if not permitted:
    return no_update, _auto_cat_status_badge("permitted_categories.txt missing or empty", "error"), ""
  allowed_set = set(permitted) | {"Other"}
  partner_names = []
  for row in data:
    partner = (row.get("Partner") or "").strip()
    category = (row.get("Category") or "").strip()
    if not category and partner:
      partner_names.append(partner)
  if not partner_names:
    return no_update, _auto_cat_status_badge("Nothing to do — all rows already have a category", "idle"), ""
  partner_names = list(dict.fromkeys(partner_names))
  total = len(partner_names)
  batch_size = int(os.environ.get("GEMINI_BATCH_SIZE", "20"))
  combined = {}
  processed = 0
  for i in range(0, len(partner_names), batch_size):
    chunk = partner_names[i:i + batch_size]
    result = guess_categories_batch(chunk, permitted)
    if not result:
      updated = []
      filled = 0
      for row in data:
        partner = (row.get("Partner") or "").strip()
        category = (row.get("Category") or "").strip()
        if not category and partner and partner in combined:
          category = str(combined[partner] or "").strip().strip(",")
          if is_income_refund_category(category) or category not in allowed_set:
            category = "Other"
          filled += 1
        updated.append({"Partner": row.get("Partner") or "", "Category": category or row.get("Category") or ""})
      if filled > 0:
        merge_category_mapping(_category_updates_from_batch(combined, allowed_set), allow_write=True)
        badge = _auto_cat_status_badge(
            f"Partial — saved {filled} of {total} (stopped at {processed}/{total}, API busy or quota)", "warning")
        return [_build_category_table(_category_table_data(read_category_mapping_file()))], badge, ""
      badge = _auto_cat_status_badge(
          f"Did not work — API busy or quota ({processed}/{total} processed)", "error")
      return [_build_category_table(updated)], badge, ""
    combined.update(result)
    processed += len(chunk)
  updated = []
  filled = 0
  for row in data:
    partner = (row.get("Partner") or "").strip()
    category = (row.get("Category") or "").strip()
    if not category and partner and partner in combined:
      category = str(combined[partner] or "").strip().strip(",")
      if is_income_refund_category(category) or category not in allowed_set:
        category = "Other"
      filled += 1
    updated.append({"Partner": row.get("Partner") or "",
                   "Category": category or row.get("Category") or ""})
  if filled > 0:
    merge_category_mapping(_category_updates_from_batch(combined, allowed_set), allow_write=True)
    badge = _auto_cat_status_badge(f"Done — categorized and saved {filled} of {total} partner(s)", "success")
    return [_build_category_table(_category_table_data(read_category_mapping_file()))], badge, ""
  badge = _auto_cat_status_badge("Did not work — API returned no categories", "error")
  return [_build_category_table(updated)], badge, ""


@callback(
    [Output("category-table-container", "children", allow_duplicate=True),
     Output("category-msg", "children", allow_duplicate=True)],
    Input("btn-suggest-offline", "n_clicks"),
    State("category-table", "data"),
    prevent_initial_call=True,
)
def suggest_offline(n_clicks, data):
  if not n_clicks or not data:
    return no_update, no_update
  updated, filled = _suggest_categories_offline(data)
  if filled == 0:
    return no_update, "No empty categories could be suggested from existing data."
  return [_build_category_table(updated)], f"Suggested {filled} categor(y/ies) from similar partners (offline). Click Save to file to persist."


@callback(
    [
        Output("assets-total-summary", "children"),
        Output("assets-total-chart", "figure"),
        Output("assets-grid", "children"),
    ],
    [
        Input("main-tabs", "value"),
        Input("assets-revision", "data"),
        Input("theme-store", "data"),
        Input("assets-display-currency", "value"),
        Input("asset-card-messages", "data"),
    ],
)
def update_assets_tab(tab, _revision, theme, display_currency, card_messages):
  if not _assets_tab_active(tab):
    raise PreventUpdate
  currency = display_currency or "EUR"
  overview = assets_engine.build_overview(display_currency=currency)
  return (
      _build_assets_total_summary(overview, currency),
      _fig_assets_total(overview["total_history"], theme, currency),
      _build_assets_grid(overview, theme, currency, card_messages),
  )


def _format_ingest_status(result):
  parts = []
  if result.get("parsed"):
    parts.append(f"Parsed: {', '.join(result['parsed'])}")
  if result.get("skipped"):
    parts.append(f"Skipped (duplicate): {', '.join(result['skipped'])}")
  if result.get("errors"):
    parts.append(f"Errors: {', '.join(result['errors'])}")
  return " · ".join(parts) if parts else "No new snapshots from reports."


@callback(
    [
        Output("assets-revision", "data", allow_duplicate=True),
        Output("assets-ingest-status", "children", allow_duplicate=True),
    ],
    Input("btn-assets-refresh", "n_clicks"),
    State("assets-revision", "data"),
    prevent_initial_call=True,
)
def on_assets_refresh(_n_clicks, revision):
  result = assets_engine.ingest_reports(allow_write=True)
  print(f"Assets ingest: {result}", flush=True)
  return (revision or 0) + 1, _format_ingest_status(result)


@callback(
    [
        Output("assets-revision", "data", allow_duplicate=True),
        Output("asset-card-messages", "data", allow_duplicate=True),
    ],
    Input({"type": "asset-report-upload", "index": ALL}, "contents"),
    State({"type": "asset-report-upload", "index": ALL}, "filename"),
    State({"type": "asset-report-upload", "index": ALL}, "id"),
    State("asset-card-messages", "data"),
    State("assets-revision", "data"),
    prevent_initial_call=True,
)
def on_asset_report_upload(contents_list, filename_list, upload_ids, messages, revision):
  triggered = callback_context.triggered_id
  if not isinstance(triggered, dict) or triggered.get("type") != "asset-report-upload":
    raise PreventUpdate
  asset_id = triggered.get("index")
  if not contents_list or not filename_list:
    raise PreventUpdate

  target_idx = None
  for idx, uid in enumerate(upload_ids or []):
    if uid.get("index") == asset_id:
      target_idx = idx
      break
  if target_idx is None or target_idx >= len(contents_list):
    raise PreventUpdate

  contents = contents_list[target_idx]
  filename = filename_list[target_idx]
  if not contents or not filename:
    raise PreventUpdate

  _, content_string = contents.split(",", 1)
  decoded = base64.b64decode(content_string)
  result = assets_engine.upload_and_ingest_for_asset(
      asset_id, decoded, filename, allow_write=True
  )

  updated_messages = dict(messages or {})
  kind = "success" if result.get("ok") else "error"
  updated_messages[asset_id] = {"kind": kind, "text": result.get("message", "")}
  return (revision or 0) + 1, updated_messages


@callback(
    Output("asset-add-modal", "is_open"),
    [
        Input("btn-add-asset", "n_clicks"),
        Input("btn-asset-add-cancel", "n_clicks"),
    ],
    prevent_initial_call=True,
)
def toggle_asset_add_modal(_open_clicks, _cancel_clicks):
  triggered = callback_context.triggered_id
  if triggered == "btn-add-asset":
    return True
  if triggered == "btn-asset-add-cancel":
    return False
  raise PreventUpdate


@callback(
    [
        Output("assets-revision", "data", allow_duplicate=True),
        Output("assets-ingest-status", "children", allow_duplicate=True),
        Output("asset-add-msg", "children"),
        Output("asset-add-name", "value"),
        Output("asset-add-id", "value"),
        Output("asset-add-initial-value", "value"),
        Output("asset-add-as-of", "value"),
        Output("asset-add-modal", "is_open", allow_duplicate=True),
    ],
    Input("btn-asset-add-save", "n_clicks"),
    [
        State("asset-add-name", "value"),
        State("asset-add-id", "value"),
        State("asset-add-type", "value"),
        State("asset-add-currency", "value"),
        State("asset-add-parser", "value"),
        State("asset-add-expense-source", "value"),
        State("asset-add-initial-value", "value"),
        State("asset-add-as-of", "value"),
        State("assets-revision", "data"),
    ],
    prevent_initial_call=True,
)
def on_asset_add_save(
    _n_clicks,
    name,
    asset_id,
    asset_type,
    currency,
    parser,
    expense_source,
    initial_value,
    as_of,
    revision,
):
  result = assets_config.add_asset(
      name,
      asset_type,
      currency,
      asset_id=asset_id or None,
      parser=parser or None,
      expense_source_id=expense_source or None,
      allow_write=True,
  )
  if not result.get("ok"):
    return (
        no_update,
        no_update,
        result.get("message", "Could not add asset."),
        no_update,
        no_update,
        no_update,
        no_update,
        no_update,
    )

  new_id = result["asset_id"]
  status_parts = [result.get("message", "Asset added.")]
  if initial_value is not None and str(initial_value).strip() != "":
    added = assets_engine.add_manual_snapshot(
        new_id,
        float(initial_value),
        as_of=as_of or None,
        allow_write=True,
    )
    if added:
      status_parts.append("Initial balance recorded.")
    else:
      status_parts.append("Initial balance skipped (duplicate snapshot).")

  return (
      (revision or 0) + 1,
      " · ".join(status_parts),
      "",
      "",
      "",
      None,
      "",
      False,
  )


@callback(
    Output("assets-revision", "data", allow_duplicate=True),
    Input({"type": "asset-manual-save", "index": ALL}, "n_clicks"),
    State({"type": "asset-manual-value", "index": ALL}, "value"),
    State({"type": "asset-manual-date", "index": ALL}, "value"),
    State({"type": "asset-manual-save", "index": ALL}, "id"),
    State("assets-revision", "data"),
    prevent_initial_call=True,
)
def on_asset_manual_save(_clicks, values, dates, ids, revision):
  triggered = callback_context.triggered_id
  if not isinstance(triggered, dict) or triggered.get("type") != "asset-manual-save":
    raise PreventUpdate
  asset_id = triggered.get("index")
  value = None
  as_of = None
  for sid, val, dt_val in zip(ids, values, dates):
    if sid.get("index") == asset_id:
      value = val
      as_of = dt_val
      break
  if value is None:
    raise PreventUpdate
  assets_engine.add_manual_snapshot(
      asset_id, float(value), as_of=as_of or None, allow_write=True
  )
  return (revision or 0) + 1


@callback(
    [Output("files-list", "children"), Output("files-base-dir", "children")],
    [Input("files-refresh", "n_clicks"), Input("main-tabs", "value")],
)
def update_files_list(_n_clicks, tab):
  if tab != _TAB_DATA:
    raise PreventUpdate
  base_dir, files = _list_dashboard_files()
  base_label = f"Base dir: {base_dir}"

  if not files:
    return html.Div("No files found."), base_label

  return (
      html.Ul([html.Li(f) for f in files]),
      base_label,
  )


@callback(
    Output("report-pdf-download", "data"),
    Output("report-email-status", "children", allow_duplicate=True),
    Input("btn-export-report-pdf", "n_clicks"),
    [
        State("display-currency", "value"),
        State("theme-store", "data"),
    ],
    prevent_initial_call=True,
)
def export_report_pdf(_n_clicks, display_currency, theme):
  try:
    currency = display_currency or "EUR"
    ctx = reporting.build_report_context(
        display_currency=currency,
        df=_load_data(),
    )
    pdf_bytes = reporting.build_report_pdf(ctx, theme)
    filename = f"money-tracker-report-{ctx.generated_on.isoformat()}.pdf"
    return dcc.send_bytes(pdf_bytes, filename), no_update
  except Exception as exc:
    print(f"PDF export failed: {exc}", flush=True)
    return no_update, _auto_cat_status_badge(f"PDF export failed: {exc}", "error")


@callback(
    Output("report-email-status", "children"),
    Input("btn-send-report-email", "n_clicks"),
    [
        State("display-currency", "value"),
        State("theme-store", "data"),
    ],
    prevent_initial_call=True,
)
def send_report_email(_n_clicks, display_currency, theme):
  try:
    currency = display_currency or "EUR"
    ctx = reporting.build_report_context(
        display_currency=currency,
        df=_load_data(),
    )
    reporting.send_gmail_report(ctx, theme)
    return _auto_cat_status_badge("Report sent by email", "success")
  except ValueError as exc:
    return _auto_cat_status_badge(str(exc), "error")
  except Exception as exc:
    return _auto_cat_status_badge(f"Email failed: {exc}", "error")


def _preload_data_blocking():
  csv_dir = get_csv_dir()
  data_dir = get_base_dir()
  print(f"Loading transactions (data: {data_dir}, csv: {csv_dir})...", flush=True)
  started = time.monotonic()
  df = _cached_run_pipeline()
  elapsed = time.monotonic() - started
  print(f"Loaded {len(df)} row(s) in {elapsed:.1f}s.", flush=True)
  return df


def main():
  for line in env_config.startup_env_status():
    print(line, flush=True)

  host = env_config.optional_env("MONEY_TRACKER_HOST", "127.0.0.1")
  port = int(env_config.optional_env("MONEY_TRACKER_PORT", "8050"))
  debug = env_config.optional_env("MONEY_TRACKER_DEBUG").lower() in ("1", "true", "yes")

  df = _preload_data_blocking()
  has_data = not df.empty
  assets_engine.ensure_reports_dir()
  assets_engine.ingest_reports(allow_write=True)
  app.layout = _build_app_layout(load_data=has_data)

  app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
  main()
