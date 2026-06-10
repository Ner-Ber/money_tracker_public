"""Tests for category_mapping.txt read/write/merge."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from money_tracker import data_loading


def _raw_partner_lines(path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _assert_no_duplicate_partners_in_file(path) -> None:
    raw = data_loading._read_category_mapping_raw(base_dir=path.parent)
    partners = [p for p, _c in raw]
    assert len(partners) == len(set(partners)), (
        f"duplicate partners in {path.name}: {len(partners)} lines, {len(set(partners))} unique"
    )


def _assert_categories_are_permitted_or_empty(path) -> None:
    permitted = set(data_loading.read_permitted_categories(base_dir=path.parent))
    for _partner, cat in data_loading._read_category_mapping_raw(base_dir=path.parent):
        if cat:
            assert cat in permitted, f"non-permitted category {cat!r}"


def _assert_file_uses_tab_format(path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        assert "\t" in line, f"line must use tab delimiter, got: {line!r}"
        partner, _cat = line.split("\t", 1)
        assert partner.strip(), f"empty partner on line: {line!r}"


def _assert_no_comma_only_mapping_lines(path) -> None:
    """Comma-only lines are ambiguous; on-disk file must use tabs."""
    permitted = set(data_loading.read_permitted_categories(base_dir=path.parent))
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or "\t" in line:
            continue
        assert False, (
            f"legacy comma-only line still on disk: {line!r}; "
            f"permitted categories include {sorted(permitted)[:3]}..."
        )


def test_merge_category_mapping_writes_file(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text("Household\n", encoding="utf-8")
    path.write_text("Old Partner\tHousehold\n", encoding="utf-8")

    data_loading.merge_category_mapping(
        [("New Partner", "Groceries"), ("Old Partner", "Cafe & Dine")],
        base_dir=tmp_path,
        allow_write=True,
    )

    _assert_file_uses_tab_format(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["New Partner"] == "Groceries"
    assert rows["Old Partner"] == "Cafe & Dine"


def test_merge_skips_income_refund_and_empty(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text("Groceries\n", encoding="utf-8")
    path.write_text("", encoding="utf-8")

    data_loading.merge_category_mapping(
        [
            ("A", "Income / Refund"),
            ("B", ""),
            ("C", "Groceries"),
        ],
        base_dir=tmp_path,
        allow_write=True,
    )

    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows == {"C": "Groceries"}


def test_parse_partner_name_with_commas_not_split_as_category(tmp_path):
    (tmp_path / "permitted_categories.txt").write_text("Groceries\n", encoding="utf-8")
    parsed = data_loading._parse_category_mapping_line(
        "ETH Zürich, Finanzen + Controlling, ",
        permitted=["Groceries"],
    )
    assert parsed == ("ETH Zürich, Finanzen + Controlling", "")


def test_parse_legacy_comma_line_peels_permitted_category(tmp_path):
    permitted = ["Household", "Groceries"]
    parsed = data_loading._parse_legacy_comma_line(
        "Rundfunk ARD, ZDF, DRadio, Household",
        permitted,
    )
    assert parsed == ("Rundfunk ARD, ZDF, DRadio", "Household")


def test_prefix_merge_rundfunk_and_benny(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text(
        "Household\nGroceries\n",
        encoding="utf-8",
    )
    path.write_text(
        "Rundfunk ARD, Household\n"
        "Rundfunk ARD, ZDF, DRadio,\n"
        "Benny Ifhar,\n"
        "Benny Ifhar, Benny,\n",
        encoding="utf-8",
    )

    data_loading.compact_category_mapping_file(base_dir=tmp_path, allow_write=True)

    _assert_file_uses_tab_format(path)
    _assert_no_comma_only_mapping_lines(path)
    _assert_no_duplicate_partners_in_file(path)
    _assert_categories_are_permitted_or_empty(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["Rundfunk ARD, ZDF, DRadio"] == "Household"
    assert "Rundfunk ARD" not in rows
    assert rows["Benny Ifhar, Benny"] == ""
    assert "Benny Ifhar" not in rows
    assert len(rows) == 2


def test_compact_category_mapping_file_removes_duplicate_lines(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text(
        "Groceries\nCafe & Dine\n",
        encoding="utf-8",
    )
    path.write_text(
        "Shop A, Groceries\nShop A, \nShop A, Cafe & Dine\n",
        encoding="utf-8",
    )

    data_loading.compact_category_mapping_file(base_dir=tmp_path, allow_write=True)

    _assert_file_uses_tab_format(path)
    _assert_no_duplicate_partners_in_file(path)
    _assert_categories_are_permitted_or_empty(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows == {"Shop A": "Groceries"}


def test_update_category_mapping_never_writes_duplicate_lines(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text("Groceries\n", encoding="utf-8")
    path.write_text("Shop A, Groceries\nShop A, \n", encoding="utf-8")
    df = pd.DataFrame(
        {
            "Partner Name": ["Shop A", "Shop B", "Shop A"],
            "Amount (EUR)": [-1.0, -2.0, -3.0],
        }
    )

    data_loading.update_category_mapping(df, base_dir=tmp_path, allow_write=True)
    data_loading.update_category_mapping(df, base_dir=tmp_path, allow_write=True)

    _assert_file_uses_tab_format(path)
    _assert_no_duplicate_partners_in_file(path)
    _assert_categories_are_permitted_or_empty(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["Shop A"] == "Groceries"
    assert rows["Shop B"] == ""


def test_merge_category_mapping_never_writes_duplicate_lines(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text(
        "Household\nGroceries\nCafe & Dine\nOther\n",
        encoding="utf-8",
    )
    path.write_text("Partner X, Household\nPartner X, \n", encoding="utf-8")

    data_loading.merge_category_mapping(
        [("Partner X", "Groceries"), ("Partner Y", "Other")],
        base_dir=tmp_path,
        allow_write=True,
    )
    data_loading.merge_category_mapping(
        [("Partner X", "Cafe & Dine")],
        base_dir=tmp_path,
        allow_write=True,
    )

    _assert_file_uses_tab_format(path)
    _assert_no_duplicate_partners_in_file(path)
    _assert_categories_are_permitted_or_empty(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["Partner X"] == "Cafe & Dine"
    assert rows["Partner Y"] == "Other"


def test_compact_fixes_comma_partner_artifacts_and_drops_tail_duplicates(tmp_path):
    path = tmp_path / "category_mapping.txt"
    (tmp_path / "permitted_categories.txt").write_text(
        "Groceries\nOther\n",
        encoding="utf-8",
    )
    path.write_text(
        "ETH Zürich, Finanzen + Controlling,\n"
        "ETH Zürich, Finanzen + Controlling, \n"
        "Ifhar, Benny,\n"
        "Ifhar, Benny,\n"
        "REWE, Groceries\n",
        encoding="utf-8",
    )

    data_loading.compact_category_mapping_file(base_dir=tmp_path, allow_write=True)

    _assert_file_uses_tab_format(path)
    _assert_no_comma_only_mapping_lines(path)
    _assert_no_duplicate_partners_in_file(path)
    _assert_categories_are_permitted_or_empty(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=tmp_path))
    assert rows["ETH Zürich, Finanzen + Controlling"] == ""
    assert rows["Ifhar, Benny"] == ""
    assert rows["REWE"] == "Groceries"
    assert len(rows) == 3


def test_project_category_mapping_file_well_formed():
    """Guard the real category_mapping.txt (regression trap for comma artifacts)."""
    base = Path(data_loading.get_base_dir())
    path = base / "category_mapping.txt"
    permitted_path = base / "permitted_categories.txt"
    if not path.is_file() or not permitted_path.is_file():
        pytest.skip("project mapping files not present")
    data_loading.compact_category_mapping_file(base_dir=base, allow_write=True)
    _assert_file_uses_tab_format(path)
    _assert_no_comma_only_mapping_lines(path)
    _assert_no_duplicate_partners_in_file(path)
    _assert_categories_are_permitted_or_empty(path)
    rows = dict(data_loading.read_category_mapping_file(base_dir=base))
    assert "Rundfunk ARD" not in rows
    assert "Benny Ifhar" not in rows
    if "Rundfunk ARD, ZDF, DRadio" in rows:
        assert rows["Rundfunk ARD, ZDF, DRadio"] == "Household"
