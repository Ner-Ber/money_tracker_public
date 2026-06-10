"""Load .env and validate settings with actionable error messages."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_LOADED = False
_PLACEHOLDER_PREFIXES = ("your-", "changeme", "example", "xxx", "replace-")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def env_file_path() -> Path:
    return repo_root() / ".env"


def env_example_path() -> Path:
    return repo_root() / ".env.example"


def load_env(*, force: bool = False) -> None:
    """Load variables from repo-root `.env` (idempotent)."""
    global _ENV_LOADED
    if _ENV_LOADED and not force:
        return
    load_dotenv(env_file_path())
    _ENV_LOADED = True


def env_setup_hint() -> str:
    example = env_example_path()
    if example.is_file():
        return f"Copy {example.name} to .env in the repo root and fill in your values."
    return "Create a .env file in the repo root with the required variables."


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    return lowered.startswith(_PLACEHOLDER_PREFIXES)


def _require_env(name: str, *, purpose: str) -> str:
    load_env()
    value = os.environ.get(name, "").strip()
    if _looks_like_placeholder(value):
        raise ValueError(
            f"{name} is missing or still a placeholder ({purpose}). {env_setup_hint()}"
        )
    return value


def optional_env(name: str, default: str = "") -> str:
    load_env()
    raw = os.environ.get(name, default)
    return raw.strip() if raw is not None else default


def require_gemini_api_key() -> str:
    return _require_env(
        "GEMINI_API_KEY",
        purpose="needed for AI auto-categorization",
    )


def require_gmail_config() -> tuple[str, str, list[str]]:
    user = _require_env("GMAIL_USER", purpose="needed to send email reports")
    password = _require_env(
        "GMAIL_APP_PASSWORD",
        purpose="needed to send email reports (use a Gmail app password)",
    )
    raw_to = _require_env(
        "REPORT_EMAIL_TO",
        purpose="needed to send email reports (comma-separated recipients)",
    )
    recipients = [addr.strip() for addr in raw_to.split(",") if addr.strip()]
    if not recipients:
        raise ValueError(
            f"REPORT_EMAIL_TO has no valid addresses. {env_setup_hint()}"
        )
    return user, password, recipients


def has_gemini_api_key() -> bool:
    return not _looks_like_placeholder(optional_env("GEMINI_API_KEY"))


def has_gmail_config() -> bool:
    return all(
        not _looks_like_placeholder(optional_env(name))
        for name in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "REPORT_EMAIL_TO")
    )


def startup_env_status() -> list[str]:
    """Human-readable notes about optional .env settings (for console on startup)."""
    load_env()
    messages: list[str] = []
    if not env_file_path().is_file():
        messages.append(
            "No .env file found — using demo defaults. "
            + env_setup_hint()
            + " Optional features (AI categorization, email reports) stay disabled until configured."
        )
        return messages

    if _looks_like_placeholder(optional_env("GEMINI_API_KEY")):
        messages.append(
            "GEMINI_API_KEY is not set — AI auto-categorization is disabled."
        )
    gmail_missing = any(
        _looks_like_placeholder(optional_env(name))
        for name in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "REPORT_EMAIL_TO")
    )
    if gmail_missing:
        messages.append(
            "Gmail settings are incomplete — email reports are disabled."
        )
    return messages
