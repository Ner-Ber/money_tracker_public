"""Tests for LLM expense categorization (Gemini batch API)."""

from __future__ import annotations

import json
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from unittest import mock

import pytest

from money_tracker import llm_categorization


def _mock_response(payload: dict):
    class _Response:
        text = json.dumps(payload)

    return _Response()


def test_empty_partners_skips_api_call(mock_genai_client):
    client = mock_genai_client
    client.models.generate_content = mock.Mock()

    result = llm_categorization.guess_categories_batch(
        [],
        ["Groceries"],
        genai_client=client,
    )

    assert result == {}
    client.models.generate_content.assert_not_called()


def test_no_client_returns_empty_without_call():
    result = llm_categorization.guess_categories_batch(
        ["REWE Leipzig"],
        ["Groceries"],
        genai_client=None,
    )
    assert result == {}


def test_api_called_with_json_config_and_returns_parsed_answer(mock_genai_client):
    client = mock_genai_client
    client.models.generate_content = mock.Mock(
        return_value=_mock_response({"REWE Leipzig": "Groceries"})
    )

    result = llm_categorization.guess_categories_batch(
        ["REWE Leipzig"],
        ["Groceries", "Cafe & Dine", "Income / Refund", "Uncategorized"],
        genai_client=client,
        model="test-model",
    )

    assert result == {"REWE Leipzig": "Groceries"}
    client.models.generate_content.assert_called_once()
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert "REWE Leipzig" in kwargs["contents"]
    allowed_block = kwargs["contents"].split("Allowed categories:")[1].split("Use \"Other\"")[0]
    assert "Income / Refund" not in allowed_block
    assert "Uncategorized" not in allowed_block
    assert "Other" in allowed_block
    assert kwargs["config"].response_mime_type == "application/json"
    assert kwargs["config"].temperature == 0.1


def test_api_error_returns_empty_dict(mock_genai_client):
    client = mock_genai_client
    client.models.generate_content = mock.Mock(side_effect=RuntimeError("API unavailable"))

    result = llm_categorization.guess_categories_batch(
        ["Partner A"],
        ["Groceries"],
        genai_client=client,
    )

    assert result == {}


def test_rate_limit_retries_after_sleep(mock_genai_client):
    client = mock_genai_client
    err = RuntimeError("429 RESOURCE_EXHAUSTED retry in 2.5 s")
    client.models.generate_content = mock.Mock(
        side_effect=[err, _mock_response({"Shop": "Groceries"})]
    )

    with mock.patch("money_tracker.llm_categorization.time.sleep") as sleep_mock:
        result = llm_categorization.guess_categories_batch(
            ["Shop"],
            ["Groceries"],
            genai_client=client,
        )

    assert result == {"Shop": "Groceries"}
    assert client.models.generate_content.call_count == 2
    sleep_mock.assert_called_once_with(2.5)


def test_timeout_happens_after_slow_api_call_not_before(mock_genai_client):
    """Timeout must fire only after generate_content runs (genuine in-flight call)."""
    client = mock_genai_client
    call_started = []

    def slow_generate(**kwargs):
        call_started.append(time.monotonic())
        time.sleep(0.25)
        return _mock_response({"Slow Shop": "Groceries"})

    client.models.generate_content = slow_generate

    t0 = time.monotonic()
    result = llm_categorization.guess_categories_batch(
        ["Slow Shop"],
        ["Groceries"],
        genai_client=client,
        request_timeout_s=0.08,
    )
    elapsed = time.monotonic() - t0

    assert result == {}
    assert len(call_started) == 1
    assert elapsed >= 0.08


def test_run_with_optional_timeout_raises_after_work_starts():
    started = []

    def work():
        started.append(True)
        time.sleep(0.2)
        return "done"

    with pytest.raises(FuturesTimeoutError):
        llm_categorization.run_with_optional_timeout(work, 0.05)

    assert started == [] or len(started) == 1


def test_category_updates_from_batch_maps_and_coerces():
    allowed = {"Groceries", "Other"}
    updates = llm_categorization.category_updates_from_batch(
        {
            "A": "Groceries",
            "B": "Unknown Cat",
            "C": "Income / Refund",
            "": "Groceries",
        },
        allowed,
    )
    assert ("A", "Groceries") in updates
    assert ("B", "Other") in updates
    assert not any(p == "C" for p, _ in updates)
