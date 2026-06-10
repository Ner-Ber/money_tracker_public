"""Matplotlib plotting for notebook: static figures with configurable options."""

import pandas as pd
import matplotlib.pyplot as plt


def _filter_df(df, start_date=None, end_date=None, categories=None):
    """Filter dataframe by date range and categories. Returns (filtered_df, cat_col)."""
    filtered = df.copy()
    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        filtered = filtered[filtered["Booking Date"] >= start_date]
    if end_date is not None:
        end_date = pd.to_datetime(end_date)
        filtered = filtered[filtered["Booking Date"] <= end_date]

    cat_col = "Display Category" if "Display Category" in filtered.columns else "Category"
    if categories:
        filtered = filtered[filtered[cat_col].isin(categories)]

    return filtered, cat_col


def plot_expenses_by_period_mpl(
    df,
    start_date=None,
    end_date=None,
    categories=None,
    period="month",
    title=None,
    figsize=(10, 5),
    ax=None,
):
    """
    Stacked bar chart: expenses by period (week/month) and category.
    Returns (fig, ax). If ax is provided, only ax is used.
    """
    filtered, cat_col = _filter_df(df, start_date, end_date, categories)
    if filtered.empty:
        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "No data for selected filters", ha="center", va="center", transform=ax.transAxes)
        return (ax.figure, ax) if ax is not None else (plt.gcf(), ax)

    if period == "week":
        filtered = filtered.copy()
        filtered["Period"] = filtered["Booking Date"].dt.to_period("W").astype(str)
    else:
        filtered = filtered.copy()
        filtered["Period"] = filtered["Booking Date"].dt.to_period("M").astype(str)

    amt_col = "Amount (EUR) converted" if "Amount (EUR) converted" in filtered.columns else "Amount (EUR)"
    grouped = filtered.groupby(["Period", cat_col])[amt_col].sum().reset_index()
    grouped = grouped.rename(columns={amt_col: "Amount (EUR)"})
    grouped["Amount (EUR)"] = grouped["Amount (EUR)"].abs()

    pivot = grouped.pivot(index="Period", columns=cat_col, values="Amount (EUR)").fillna(0)
    pivot = pivot.reindex(columns=grouped[cat_col].unique(), fill_value=0)

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    pivot.plot(kind="bar", stacked=True, ax=ax, width=0.7)
    ax.set_xlabel(period.capitalize())
    ax.set_ylabel("Amount (EUR)")
    ax.set_title(title or f"Expenses by {period.capitalize()} and Category")
    ax.legend(title=cat_col, bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    fig.tight_layout()
    return fig, ax


def plot_category_pie_mpl(
    df,
    start_date=None,
    end_date=None,
    categories=None,
    title=None,
    figsize=(8, 8),
    ax=None,
):
    """
    Pie/donut chart: expense distribution by category.
    Returns (fig, ax).
    """
    filtered, cat_col = _filter_df(df, start_date, end_date, categories)
    if filtered.empty:
        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "No data for selected filters", ha="center", va="center", transform=ax.transAxes)
        return (ax.figure, ax) if ax is not None else (plt.gcf(), ax)

    amt_col = "Amount (EUR) converted" if "Amount (EUR) converted" in filtered.columns else "Amount (EUR)"
    grouped = filtered.groupby(cat_col)[amt_col].sum().reset_index()
    grouped = grouped.rename(columns={amt_col: "Amount (EUR)"})
    grouped["Amount (EUR)"] = grouped["Amount (EUR)"].abs()
    grouped = grouped.sort_values("Amount (EUR)", ascending=False)

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    ax.pie(
        grouped["Amount (EUR)"],
        labels=grouped[cat_col],
        autopct="%1.1f%%",
        startangle=90,
        wedgeprops=dict(width=0.6),
    )
    ax.set_title(title or "Expense Distribution by Category")
    ax.axis("equal")
    fig.tight_layout()
    return fig, ax


def plot_cumulative_expenses_mpl(
    df,
    start_date=None,
    end_date=None,
    categories=None,
    title=None,
    figsize=(10, 5),
    ax=None,
):
    """
    Line chart: cumulative expenses over time per category.
    X-axis = expense date (no rounding). Y-axis = cumulative amount (EUR).
    Returns (fig, ax).
    """
    filtered, cat_col = _filter_df(df, start_date, end_date, categories)
    if filtered.empty:
        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "No data for selected filters", ha="center", va="center", transform=ax.transAxes)
        return (ax.figure, ax) if ax is not None else (plt.gcf(), ax)

    amt_col = "Amount (EUR) converted" if "Amount (EUR) converted" in filtered.columns else "Amount (EUR)"
    work = filtered.copy()
    work["_amt"] = work[amt_col].abs()
    work = work.sort_values("Booking Date")

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    colors = plt.cm.tab10.colors
    for idx, cat in enumerate(work[cat_col].dropna().unique()):
        cat_df = work[work[cat_col] == cat].sort_values("Booking Date")
        cat_df = cat_df.assign(Cumulative=cat_df["_amt"].cumsum())
        ax.plot(
            cat_df["Booking Date"],
            cat_df["Cumulative"],
            marker="o",
            markersize=3,
            label=cat,
            color=colors[idx % len(colors)],
        )
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Amount (EUR)")
    ax.set_title(title or "Cumulative Expenses by Category")
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    fig.tight_layout()
    return fig, ax
