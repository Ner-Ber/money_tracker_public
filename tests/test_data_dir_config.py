"""Tests for MONEY_TRACKER_DATA_DIR configuration."""

from __future__ import annotations

import os

from money_tracker import data_loading


def test_get_base_dir_explicit_arg(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEY_TRACKER_DATA_DIR", raising=False)
    assert data_loading.get_base_dir(base_dir=str(tmp_path)) == str(tmp_path)


def test_get_base_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEY_TRACKER_DATA_DIR_LOCAL", raising=False)
    monkeypatch.setenv("MONEY_TRACKER_DATA_DIR", str(tmp_path))
    assert data_loading.get_base_dir() == str(tmp_path)


def test_get_base_dir_local_overrides_drive(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    local = tmp_path / "local"
    drive.mkdir()
    local.mkdir()
    monkeypatch.setenv("MONEY_TRACKER_DATA_DIR", str(drive))
    monkeypatch.setenv("MONEY_TRACKER_DATA_DIR_LOCAL", str(local))
    assert data_loading.get_base_dir() == str(local)


def test_get_base_dir_explicit_overrides_env(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("MONEY_TRACKER_DATA_DIR", "/should/not/use")
    assert data_loading.get_base_dir(base_dir=str(other)) == str(other)


def test_get_base_dir_default_is_repo_root(monkeypatch):
    monkeypatch.delenv("MONEY_TRACKER_DATA_DIR", raising=False)
    monkeypatch.delenv("MONEY_TRACKER_CSV_DIR", raising=False)
    root = data_loading.get_base_dir()
    assert os.path.isdir(root)
    assert os.path.isdir(os.path.join(root, "money_tracker"))


def test_get_csv_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEY_TRACKER_CSV_DIR_LOCAL", raising=False)
    csv_dir = tmp_path / "data_files"
    csv_dir.mkdir()
    (csv_dir / "a.csv").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("MONEY_TRACKER_CSV_DIR", str(csv_dir))
    assert data_loading.get_csv_dir() == str(csv_dir)


def test_get_csv_dir_default_under_base_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEY_TRACKER_CSV_DIR", raising=False)
    local_csv = tmp_path / "csv_files"
    local_csv.mkdir()
    (local_csv / "a.csv").write_text("x\n", encoding="utf-8")
    assert data_loading.get_csv_dir(base_dir=str(tmp_path)) == str(local_csv)


def test_get_csv_dir_local_overrides_drive(tmp_path, monkeypatch):
    drive_csv = tmp_path / "data_files"
    local_csv = tmp_path / "csv_files"
    drive_csv.mkdir()
    local_csv.mkdir()
    (local_csv / "a.csv").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("MONEY_TRACKER_CSV_DIR", str(drive_csv))
    monkeypatch.setenv("MONEY_TRACKER_CSV_DIR_LOCAL", str(local_csv))
    assert data_loading.get_csv_dir() == str(local_csv)


def test_get_csv_dir_falls_back_to_repo_when_env_path_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEY_TRACKER_CSV_DIR_LOCAL", raising=False)
    empty_drive = tmp_path / "data_files"
    empty_drive.mkdir()
    repo_csv = tmp_path / "repo_csv"
    repo_csv.mkdir()
    (repo_csv / "a.csv").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(data_loading, "_REPO_CSV_DIR", str(repo_csv))
    monkeypatch.setenv("MONEY_TRACKER_CSV_DIR", str(empty_drive))
    assert data_loading.get_csv_dir() == str(repo_csv)
