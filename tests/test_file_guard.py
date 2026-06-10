"""Tests that data sources and config files cannot be written accidentally."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from money_tracker import data_loading, file_guard, sequences


def _write_minimal_csv_project(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv_files"
    csv_dir.mkdir()
    (csv_dir / "bank.csv").write_text(
        "Partner Name,Amount (EUR),Booking Date,Original Currency,Category\n"
        "REWE,-10.00,2025-06-01,EUR,\n",
        encoding="utf-8",
    )
    (tmp_path / "mappings.txt").write_text("", encoding="utf-8")
    (tmp_path / "category_mapping.txt").write_text("REWE\tGroceries\n", encoding="utf-8")
    (tmp_path / "sequences.json").write_text('{"sequences": []}', encoding="utf-8")


def test_run_pipeline_does_not_modify_category_mapping(tmp_path):
    _write_minimal_csv_project(tmp_path)
    before = (tmp_path / "category_mapping.txt").read_text(encoding="utf-8")

    data_loading.run_pipeline(base_dir=tmp_path)
    data_loading.run_pipeline(base_dir=tmp_path)

    after = (tmp_path / "category_mapping.txt").read_text(encoding="utf-8")
    assert before == after


def test_run_pipeline_does_not_modify_sequences_or_mappings(tmp_path):
    _write_minimal_csv_project(tmp_path)
    mappings_before = (tmp_path / "mappings.txt").read_text(encoding="utf-8")
    sequences_before = (tmp_path / "sequences.json").read_text(encoding="utf-8")

    data_loading.run_pipeline(base_dir=tmp_path)

    assert (tmp_path / "mappings.txt").read_text(encoding="utf-8") == mappings_before
    assert (tmp_path / "sequences.json").read_text(encoding="utf-8") == sequences_before


def test_write_category_mapping_requires_allow_write(tmp_path):
    path = tmp_path / "category_mapping.txt"
    path.write_text("Shop\tGroceries\n", encoding="utf-8")

    with pytest.raises(file_guard.ProtectedFileWriteError):
        data_loading.write_category_mapping_file([("Shop", "Groceries")], base_dir=tmp_path)

    data_loading.write_category_mapping_file(
        [("Shop", "Groceries")], base_dir=tmp_path, allow_write=True
    )
    assert "Groceries" in path.read_text(encoding="utf-8")


def test_write_mappings_requires_allow_write(tmp_path):
    with pytest.raises(file_guard.ProtectedFileWriteError):
        data_loading.write_mappings_file([("AMAZON", "AMAZON")], base_dir=tmp_path)

    data_loading.write_mappings_file([("AMAZON", "AMAZON")], base_dir=tmp_path, allow_write=True)
    assert "AMAZON" in (tmp_path / "mappings.txt").read_text(encoding="utf-8")


def test_save_sequences_requires_allow_write(tmp_path):
    with pytest.raises(file_guard.ProtectedFileWriteError):
        sequences.save_sequences([], base_dir=tmp_path)

    sequences.save_sequences([], base_dir=tmp_path, allow_write=True)
    assert (tmp_path / "sequences.json").exists()


def test_csv_data_paths_are_never_writable(tmp_path):
    csv_path = tmp_path / "csv_files" / "bank.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("x\n", encoding="utf-8")

    with pytest.raises(file_guard.ProtectedFileWriteError):
        file_guard.assert_write_allowed(str(csv_path), allow_write=True)

    with pytest.raises(file_guard.ProtectedFileWriteError):
        data_loading.write_category_mapping_file([], category_file=str(csv_path), allow_write=True)


def test_create_sequence_without_allow_write_does_not_save(tmp_path):
    with pytest.raises(file_guard.ProtectedFileWriteError):
        sequences.create_sequence("Trip A", base_dir=tmp_path)

    assert not (tmp_path / "sequences.json").exists() or (
        sequences.load_sequences(base_dir=tmp_path) == []
    )

    sequences.create_sequence("Trip A", base_dir=tmp_path, allow_write=True)
    assert sequences.load_sequences(base_dir=tmp_path)[0]["name"] == "Trip A"
