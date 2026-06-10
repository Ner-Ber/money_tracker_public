"""Tests for env_config validation helpers."""

from __future__ import annotations

import pytest

from money_tracker import env_config


def test_require_gemini_api_key_rejects_placeholder(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your-gemini-api-key")
    env_config.load_env(force=True)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        env_config.require_gemini_api_key()


def test_require_gmail_config_rejects_placeholder(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "your.email@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "your-16-char-app-password")
    monkeypatch.setenv("REPORT_EMAIL_TO", "recipient@gmail.com")
    env_config.load_env(force=True)
    with pytest.raises(ValueError, match="GMAIL_"):
        env_config.require_gmail_config()


def test_has_gemini_api_key_false_for_empty(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_config.load_env(force=True)
    assert env_config.has_gemini_api_key() is False
