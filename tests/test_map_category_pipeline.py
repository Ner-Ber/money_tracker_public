"""Tests for category_mapping.txt applied via map_category / pipeline helpers."""

from __future__ import annotations

import pandas as pd

from money_tracker import data_loading


def _expense_df(*partners):
    return pd.DataFrame(
        {
            "Partner Name": list(partners),
            "Amount (EUR)": [-10.0] * len(partners),
            "Booking Date": pd.to_datetime(["2025-01-15"] * len(partners)),
            "Currency": ["EUR"] * len(partners),
        }
    )


def test_map_category_applies_mapping_file(tmp_path):
    (tmp_path / "category_mapping.txt").write_text(
        "REWE Leipzig, Groceries\nUnknown Shop, \n",
        encoding="utf-8",
    )
    df = _expense_df("REWE Leipzig", "Unknown Shop", "No Mapping Yet")

    result = data_loading.map_category(df, base_dir=tmp_path)

    assert result.loc[result["Partner Name"] == "REWE Leipzig", "Category"].iloc[0] == "Groceries"
    assert pd.isna(result.loc[result["Partner Name"] == "Unknown Shop", "Category"].iloc[0])
    assert pd.isna(result.loc[result["Partner Name"] == "No Mapping Yet", "Category"].iloc[0])


def test_map_category_dedupes_duplicate_partner_lines(tmp_path):
    (tmp_path / "category_mapping.txt").write_text(
        "Shop A, \nShop A, Groceries\n",
        encoding="utf-8",
    )
    df = _expense_df("Shop A")

    result = data_loading.map_category(df, base_dir=tmp_path)

    assert result.loc[0, "Category"] == "Groceries"


def test_apply_income_refund_by_amount_overrides_positive(tmp_path):
    df = pd.DataFrame(
        {
            "Partner Name": ["Employer", "REWE"],
            "Amount (EUR)": [500.0, -20.0],
            "Booking Date": pd.to_datetime(["2025-02-01", "2025-02-02"]),
            "Currency": ["EUR", "EUR"],
            "Category": ["Groceries", "Groceries"],
        }
    )

    result = data_loading.apply_income_refund_by_amount(df)

    assert result.loc[0, "Category"] == data_loading.INCOME_REFUND_CATEGORY
    assert result.loc[1, "Category"] == "Groceries"


def test_normalize_partner_name_strips_sumup_and_maps_amazon(tmp_path):
    (tmp_path / "mappings.txt").write_text(
        "AMAZON, AMAZON\nAmazon.de, AMAZON\n",
        encoding="utf-8",
    )
    assert (
        data_loading.normalize_partner_name("SumUp  *Lisa Vogel", base_dir=tmp_path)
        == "Lisa Vogel"
    )
    assert (
        data_loading.normalize_partner_name("SumUp *Morgen wird be", base_dir=tmp_path)
        == "Morgen wird be"
    )
    assert (
        data_loading.normalize_partner_name("Amazon.de*Z94XR64D4", base_dir=tmp_path)
        == "AMAZON"
    )


def test_migrate_category_mapping_keys_rewrites_raw_partners(tmp_path):
    (tmp_path / "mappings.txt").write_text("Amazon.de, AMAZON\n", encoding="utf-8")
    (tmp_path / "category_mapping.txt").write_text(
        "Amazon.de*ZX6MC4JY4, Household\n"
        "SumUp  *Lisa Vogel, Personal Shopping\n",
        encoding="utf-8",
    )
    data_loading.migrate_category_mapping_keys(base_dir=tmp_path, allow_write=True)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["AMAZON"] == "Household"
    assert rows["Lisa Vogel"] == "Personal Shopping"
    assert "Amazon.de*ZX6MC4JY4" not in rows


def test_update_category_mapping_appends_new_partners_only(tmp_path):
    (tmp_path / "category_mapping.txt").write_text(
        "Existing, Groceries\n",
        encoding="utf-8",
    )
    df = _expense_df("Existing", "Brand New Partner")

    data_loading.update_category_mapping(df, base_dir=tmp_path, allow_write=True)

    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["Existing"] == "Groceries"
    assert rows["Brand New Partner"] == ""
