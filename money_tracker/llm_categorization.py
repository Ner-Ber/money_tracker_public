"""LLM batch categorization for expense partners (Gemini)."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Optional

from google.genai import types

from money_tracker.data_loading import is_income_refund_category


def _request_timeout_seconds() -> Optional[float]:
    raw = os.environ.get("GEMINI_REQUEST_TIMEOUT_S", "").strip()
    if not raw:
        return None
    return float(raw)


def run_with_optional_timeout(fn: Callable[[], Any], timeout_s: Optional[float]) -> Any:
    """Run fn; if timeout_s is set, raise FuturesTimeoutError when it elapses."""
    if timeout_s is None or timeout_s <= 0:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        return future.result(timeout=timeout_s)


def guess_categories_batch(
    partner_names: list,
    existing_categories: list,
    *,
    genai_client: Any = None,
    model: Optional[str] = None,
    request_timeout_s: Optional[float] = None,
) -> dict:
    """Use Gemini to predict categories for multiple partners in one request."""
    if not genai_client or not partner_names:
        return {}
    model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    timeout_s = request_timeout_s if request_timeout_s is not None else _request_timeout_seconds()
    categories = [
        c for c in (existing_categories or [])
        if c and not is_income_refund_category(c) and c != "Uncategorized"
    ]
    if "Other" not in categories:
        categories.append("Other")
    categories_str = ", ".join(categories)
    partners_str = ", ".join([f"\"{p}\"" for p in partner_names])
    prompt = f"""
You are an expense categorization assistant.

IMPORTANT: Every partner below is a PAYEE for money going OUT (expenses / purchases / debits).
These are NOT salary, refunds, or money received. Do NOT use "Income / Refund" — it is assigned automatically to incoming payments.

For each partner, choose exactly ONE category from the allowed list that best describes what kind of spending this is
(e.g. groceries, dining, transport, household). Use the exact category spelling from the list.

Allowed categories: [{categories_str}]

Use "Other" only when no other allowed category fits.
If a name is abbreviated, infer the business (context, most to least likely: Germany, Israel, other Europe, elsewhere).

Return a flat JSON object:
- keys: the exact partner strings as given below
- values: one allowed category name (never "Income / Refund")

Expense partners: [{partners_str}]
"""

    def _call():
        response = genai_client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        return json.loads(response.text or "{}")

    def _call_with_timeout():
        return run_with_optional_timeout(_call, timeout_s)

    try:
        return _call_with_timeout()
    except FuturesTimeoutError:
        print("Batch classification timed out.")
        return {}
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            match = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", err_str, re.I)
            wait = float(match.group(1)) if match else 15.0
            print(f"Rate limited; waiting {wait:.0f}s before retry…")
            time.sleep(wait)
            try:
                return _call_with_timeout()
            except FuturesTimeoutError:
                print("Batch classification timed out (after retry).")
                return {}
            except Exception as e2:
                print(f"Error in batch classification (after retry): {e2}")
                return {}
        print(f"Error in batch classification: {e}")
        return {}


def category_updates_from_batch(combined: dict, allowed_set: set) -> list:
    """Build (partner, category) pairs from batch API results, validated against allowed_set."""
    updates = []
    for partner, raw_cat in combined.items():
        partner = (partner or "").strip()
        if not partner:
            continue
        cat = str(raw_cat or "").strip().strip(",")
        if is_income_refund_category(cat):
            continue
        if cat not in allowed_set:
            cat = "Other"
        if cat:
            updates.append((partner, cat))
    return updates
