"""Cumulative chart: stacked areas for expenses, income overlay line."""

import pandas as pd

from money_tracker import dashboard
from money_tracker.data_loading import INCOME_REFUND_CATEGORY


def test_fig_cumulative_stacked_expenses_and_income_line():
    df = pd.DataFrame({
        "Booking Date": pd.to_datetime([
            "2025-01-01",
            "2025-01-02",
            "2025-01-03",
            "2025-01-04",
        ]),
        "Category": [
            "Groceries",
            "Groceries",
            INCOME_REFUND_CATEGORY,
            "Entertainment",
        ],
        "Amount (EUR)": [-50.0, -30.0, 200.0, -20.0],
    })
    fig = dashboard._fig_cumulative(df, None, None, None, "teal")
    stack_traces = [t for t in fig.data if getattr(t, "stackgroup", None)]
    income_traces = [t for t in fig.data if t.name == INCOME_REFUND_CATEGORY]
    assert len(stack_traces) == 2
    assert all(t.mode == "lines" for t in stack_traces)
    assert len(income_traces) == 1
    assert income_traces[0].line.color in ("#000000", "#000", "rgb(0, 0, 0)")
    assert income_traces[0].stackgroup is None


def test_fig_cumulative_excludes_income_from_stack():
    df = pd.DataFrame({
        "Booking Date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        "Category": [INCOME_REFUND_CATEGORY, INCOME_REFUND_CATEGORY],
        "Amount (EUR)": [100.0, 50.0],
    })
    fig = dashboard._fig_cumulative(df, None, None, None, "teal")
    assert not any(getattr(t, "stackgroup", None) for t in fig.data)
    assert len(fig.data) == 1
    assert fig.data[0].name == INCOME_REFUND_CATEGORY
