"""Asset valuation: ingest reports, project bank balances, build history."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Mapping

import pandas as pd

from money_tracker import currency as currency_conv
from money_tracker.assets import config
from money_tracker.assets import log
from money_tracker.assets.parsers import registry
from money_tracker.data_loading import get_base_dir
from money_tracker.data_loading import read_csv_files_to_df
from money_tracker.sources import schema as sources_schema

REPORTS_DIR = "asset_reports"


def reports_dir(base_dir: str | None = None) -> str:
    return os.path.join(get_base_dir(base_dir), REPORTS_DIR)


def ensure_reports_dir(base_dir: str | None = None) -> str:
    path = reports_dir(base_dir)
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name)
    base = re.sub(r"[^\w.\-]+", "_", base)
    return base or "upload"


def save_uploaded_report(
    content: bytes,
    filename: str,
    base_dir: str | None = None,
) -> str:
    """Save uploaded report bytes to asset_reports/ and return absolute path."""
    folder = ensure_reports_dir(base_dir)
    safe = _sanitize_filename(filename)
    path = os.path.join(folder, safe)
    if os.path.exists(path):
        stem, ext = os.path.splitext(safe)
        path = os.path.join(folder, f"{stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}")
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def ingest_reports(
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> dict[str, Any]:
    """Scan asset_reports/ for supported report files and append snapshots."""
    folder = ensure_reports_dir(base_dir)
    assets = config.load_assets(base_dir)
    parsed: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    allowed_exts = registry.report_extensions()

    report_files = sorted(
        f for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in allowed_exts
    ) if os.path.isdir(folder) else []

    for filename in report_files:
        path = os.path.join(folder, filename)
        for asset in assets:
            parser_id = asset.get("parser")
            if not parser_id:
                continue
            if not registry.parser_accepts(str(parser_id), path):
                continue
            parser_fn = registry.get_parser(str(parser_id))
            if parser_fn is None:
                continue
            try:
                result = parser_fn(path)
            except Exception as exc:
                errors.append(f"{filename} ({asset['id']}): {exc}")
                continue
            if result is None:
                continue
            snapshot = _snapshot_from_parse(asset, result, filename)
            added = log.append_snapshot(snapshot, base_dir=base_dir, allow_write=allow_write)
            if added:
                parsed.append(f"{asset['id']} ← {filename}")
            else:
                skipped.append(f"{asset['id']} ← {filename}")

    return {"parsed": parsed, "skipped": skipped, "errors": errors}


def _snapshot_from_parse(
    asset: Mapping[str, Any],
    result: Mapping[str, Any],
    report_file: str,
) -> dict[str, Any]:
    snapshot = {
        "asset_id": asset["id"],
        "as_of": result["as_of"],
        "value": result["value"],
        "currency": result.get("currency", asset.get("currency", "EUR")),
        "source": "report",
        "report_file": report_file,
    }
    if result.get("sub_breakdown"):
        snapshot["sub_breakdown"] = result["sub_breakdown"]
    if result.get("liabilities") is not None:
        snapshot["liabilities"] = result["liabilities"]
    return snapshot


def ingest_report_for_asset(
    asset_id: str,
    file_path: str,
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> dict[str, Any]:
    """Parse one report file for a single asset; return success or error details."""
    assets_map = config.asset_by_id(base_dir)
    asset = assets_map.get(asset_id)
    if asset is None:
        return {"ok": False, "message": f"Unknown asset: {asset_id}"}

    parser_id = asset.get("parser")
    if not parser_id:
        return {
            "ok": False,
            "message": "This asset has no report parser. Add a parser or use manual update.",
        }

    parser_key = str(parser_id)
    if not registry.parser_accepts(parser_key, file_path):
        allowed = registry.PARSER_EXTENSIONS.get(parser_key, frozenset())
        ext = os.path.splitext(file_path)[1].lower() or "(none)"
        expected = ", ".join(sorted(allowed)) or "supported file"
        return {
            "ok": False,
            "message": f"Wrong file type '{ext}'. Expected: {expected}.",
        }

    parser_fn = registry.get_parser(parser_key)
    if parser_fn is None:
        return {"ok": False, "message": f"Parser '{parser_key}' is not configured."}

    try:
        result = parser_fn(file_path)
    except Exception as exc:
        return {"ok": False, "message": f"Failed to read report: {exc}"}

    if result is None:
        label = registry.PARSER_LABELS.get(parser_key, parser_key)
        return {
            "ok": False,
            "message": f"File does not match the expected format ({label}).",
        }

    filename = os.path.basename(file_path)
    snapshot = _snapshot_from_parse(asset, result, filename)
    added = log.append_snapshot(snapshot, base_dir=base_dir, allow_write=allow_write)
    value = float(result["value"])
    currency = snapshot["currency"]
    if added:
        return {
            "ok": True,
            "message": (
                f"Ingested successfully: {value:,.2f} {currency} "
                f"as of {str(result['as_of'])[:10]}."
            ),
        }
    return {
        "ok": True,
        "message": (
            f"Already recorded for {str(result['as_of'])[:10]} "
            f"({value:,.2f} {currency}); duplicate skipped."
        ),
    }


def upload_and_ingest_for_asset(
    asset_id: str,
    content: bytes,
    filename: str,
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> dict[str, Any]:
    """Save an uploaded report and ingest it for one asset."""
    path = save_uploaded_report(content, filename, base_dir=base_dir)
    return ingest_report_for_asset(
        asset_id, path, base_dir=base_dir, allow_write=allow_write
    )


def add_manual_snapshot(
    asset_id: str,
    value: float,
    as_of: str | datetime | None = None,
    base_dir: str | None = None,
    *,
    allow_write: bool = False,
) -> bool:
    assets = config.asset_by_id(base_dir)
    asset = assets.get(asset_id)
    if asset is None:
        return False
    if as_of is None:
        as_of_dt = datetime.now()
    elif isinstance(as_of, datetime):
        as_of_dt = as_of
    else:
        as_of_dt = pd.to_datetime(as_of).to_pydatetime()
    snapshot = {
        "asset_id": asset_id,
        "as_of": as_of_dt.isoformat(),
        "value": float(value),
        "currency": asset.get("currency", "EUR"),
        "source": "manual",
    }
    return log.append_snapshot(snapshot, base_dir=base_dir, allow_write=allow_write)


def _load_transactions(base_dir: str | None = None) -> pd.DataFrame:
    df = read_csv_files_to_df(base_dir=base_dir)
    if df.empty:
        return df
    df = df.copy()
    df["Booking Date"] = pd.to_datetime(df["Booking Date"], errors="coerce")
    df["Amount (EUR)"] = pd.to_numeric(df["Amount (EUR)"], errors="coerce")
    return df


def _transaction_delta(
    asset: Mapping[str, Any],
    anchor_as_of: pd.Timestamp,
    transactions: pd.DataFrame,
) -> float:
    source_id = asset.get("expense_source_id")
    if not source_id or transactions.empty:
        return 0.0
    if sources_schema.SOURCE_ID not in transactions.columns:
        return 0.0
    mask = transactions[sources_schema.SOURCE_ID] == source_id
    mask &= transactions["Booking Date"] > anchor_as_of
    return float(transactions.loc[mask, "Amount (EUR)"].sum())


def current_value(
    asset: Mapping[str, Any],
    base_dir: str | None = None,
    transactions: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """Latest value for one asset, with bank projection when applicable."""
    asset_id = str(asset["id"])
    anchor = log.latest_snapshot(asset_id, base_dir)
    if anchor is None:
        return None

    value = float(anchor["value"])
    as_of = pd.to_datetime(anchor["as_of"])
    source = str(anchor.get("source", "report"))
    sub_breakdown = anchor.get("sub_breakdown")
    liabilities = anchor.get("liabilities")

    if asset.get("expense_source_id"):
        if transactions is None:
            transactions = _load_transactions(base_dir)
        delta = _transaction_delta(asset, as_of, transactions)
        if delta != 0.0:
            value += delta
            source = "projected"

    return {
        "asset_id": asset_id,
        "value": value,
        "currency": anchor.get("currency", asset.get("currency", "EUR")),
        "as_of": as_of,
        "source": source,
        "anchor_as_of": as_of,
        "sub_breakdown": sub_breakdown,
        "liabilities": liabilities,
    }


def _convert_to_display(
    value: float,
    from_currency: str,
    display_currency: str,
    to_eur: Mapping[str, float],
) -> float:
    from_ccy = currency_conv.normalize_currency(from_currency)
    to_ccy = currency_conv.normalize_currency(display_currency)
    eur_rate_from = to_eur.get(from_ccy, 1.0)
    eur_rate_to = to_eur.get(to_ccy, 1.0)
    if eur_rate_to <= 0:
        eur_rate_to = 1.0
    in_eur = value * eur_rate_from
    return in_eur / eur_rate_to


def asset_history(
    asset: Mapping[str, Any],
    base_dir: str | None = None,
    transactions: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Time series from log snapshots; bank assets get a projected endpoint."""
    asset_id = str(asset["id"])
    snapshots = log.snapshots_for_asset(asset_id, base_dir)
    points: list[dict[str, Any]] = []
    for snap in snapshots:
        points.append({
            "date": pd.to_datetime(snap["as_of"]),
            "value": float(snap["value"]),
            "source": snap.get("source", "report"),
        })

    current = current_value(asset, base_dir=base_dir, transactions=transactions)
    if current is not None:
        cur_date = current["as_of"]
        if not points or points[-1]["date"] < cur_date or points[-1]["value"] != current["value"]:
            points.append({
                "date": cur_date if isinstance(cur_date, pd.Timestamp) else pd.to_datetime(cur_date),
                "value": current["value"],
                "source": current["source"],
            })
    return points


def pct_change(
    history: list[dict[str, Any]],
    days: int,
) -> float | None:
    if len(history) < 1:
        return None
    current = history[-1]["value"]
    target_date = history[-1]["date"] - timedelta(days=days)
    past_value = None
    for point in history:
        if point["date"] <= target_date:
            past_value = point["value"]
    if past_value is None or past_value == 0:
        return None
    return (current - past_value) / abs(past_value) * 100.0


def build_overview(
    base_dir: str | None = None,
    display_currency: str = "EUR",
) -> dict[str, Any]:
    """Aggregate all assets for dashboard rendering."""
    assets = config.load_assets(base_dir)
    to_eur = currency_conv.load_to_eur_rates(base_dir)
    transactions = _load_transactions(base_dir)

    per_asset: list[dict[str, Any]] = []
    total_now = 0.0
    checking_total = 0.0
    savings_total = 0.0
    latest_dates: list[pd.Timestamp] = []

    for asset in assets:
        cur = current_value(asset, base_dir=base_dir, transactions=transactions)
        history = asset_history(asset, base_dir=base_dir, transactions=transactions)
        if cur is None:
            per_asset.append({
                "asset": asset,
                "current": None,
                "history": history,
                "pct_1m": None,
                "pct_1y": None,
            })
            continue

        display_value = _convert_to_display(
            cur["value"], cur["currency"], display_currency, to_eur
        )
        total_now += display_value
        if asset.get("type") == "bank":
            checking_total += display_value
        else:
            savings_total += display_value
        as_of = cur["as_of"]
        if isinstance(as_of, pd.Timestamp):
            latest_dates.append(as_of)
        else:
            latest_dates.append(pd.to_datetime(as_of))

        per_asset.append({
            "asset": asset,
            "current": {**cur, "display_value": display_value},
            "history": history,
            "pct_1m": pct_change(history, 30),
            "pct_1y": pct_change(history, 365),
        })

    total_history = _build_total_history(per_asset, display_currency, to_eur)

    as_of_label = None
    if latest_dates:
        as_of_label = max(latest_dates).strftime("%Y-%m-%d")

    return {
        "display_currency": display_currency,
        "total": total_now,
        "checking_total": checking_total,
        "savings_total": savings_total,
        "as_of": as_of_label,
        "assets": per_asset,
        "total_history": total_history,
    }


def _build_total_history(
    per_asset: list[dict[str, Any]],
    display_currency: str,
    to_eur: Mapping[str, float],
) -> list[dict[str, Any]]:
    """Sum per-asset histories on union of dates (forward-fill last known value)."""
    all_dates: set[pd.Timestamp] = set()
    for item in per_asset:
        for point in item.get("history", []):
            all_dates.add(point["date"])
    if not all_dates:
        return []

    sorted_dates = sorted(all_dates)
    series: list[dict[str, Any]] = []

    for dt in sorted_dates:
        total = 0.0
        for item in per_asset:
            asset = item["asset"]
            history = item.get("history", [])
            if not history:
                continue
            last_val = None
            last_ccy = asset.get("currency", "EUR")
            for point in history:
                if point["date"] <= dt:
                    last_val = point["value"]
                else:
                    break
            if last_val is not None:
                total += _convert_to_display(last_val, last_ccy, display_currency, to_eur)
        series.append({"date": dt, "value": total})
    return series
