"""Data loading and cleaning pipeline for expense CSVs."""

import os
import re

import pandas as pd

from money_tracker import currency as currency_conv
from money_tracker import file_guard
from money_tracker import settlement_filter
from money_tracker.sources import loader as sources_loader
from money_tracker.sources import schema as sources_schema

INCOME_REFUND_CATEGORY = "Income / Refund"
_LEGACY_INCOME_NAMES = frozenset({"income", "income / refund"})


def is_income_refund_category(category):
    """True for Income / Refund or legacy 'Income' labels."""
    if category is None:
        return False
    return str(category).strip().lower() in _LEGACY_INCOME_NAMES


def get_base_dir(base_dir=None):
    """Config root: explicit arg, MONEY_TRACKER_DATA_DIR env, or repo root (dev default)."""
    if base_dir is not None:
        return os.path.abspath(base_dir)
    local_dir = os.environ.get("MONEY_TRACKER_DATA_DIR_LOCAL", "").strip()
    if local_dir and os.path.isdir(local_dir):
        return os.path.abspath(local_dir)
    env_dir = os.environ.get("MONEY_TRACKER_DATA_DIR", "").strip()
    if env_dir:
        return os.path.abspath(env_dir)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_REPO_CSV_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "csv_files",
)


def _dir_has_csv_files(directory):
    if not os.path.isdir(directory):
        return False
    for _root, _dirs, files in os.walk(directory):
        if any(name.lower().endswith(".csv") for name in files):
            return True
    return False


def get_csv_dir(base_dir=None):
    """Bank CSV folder: MONEY_TRACKER_CSV_DIR env, or {base_dir}/csv_files (dev default)."""
    if base_dir is not None:
        primary = os.path.join(get_base_dir(base_dir), "csv_files")
        if _dir_has_csv_files(primary):
            return primary
        if (
            _dir_has_csv_files(_REPO_CSV_DIR)
            and os.path.normpath(primary) != os.path.normpath(_REPO_CSV_DIR)
        ):
            print(
                f"Warning: no CSVs found in {primary}; using {_REPO_CSV_DIR}"
            )
            return _REPO_CSV_DIR
        return primary

    local_dir = os.environ.get("MONEY_TRACKER_CSV_DIR_LOCAL", "").strip()
    if local_dir and _dir_has_csv_files(local_dir):
        return os.path.abspath(local_dir)

    env_dir = os.environ.get("MONEY_TRACKER_CSV_DIR", "").strip()
    if env_dir:
        primary = os.path.abspath(env_dir)
    else:
        primary = os.path.join(get_base_dir(base_dir), "csv_files")

    if _dir_has_csv_files(primary):
        return primary
    if (
        _dir_has_csv_files(_REPO_CSV_DIR)
        and os.path.normpath(primary) != os.path.normpath(_REPO_CSV_DIR)
    ):
        print(
            f"Warning: no CSVs found in {primary}; using {_REPO_CSV_DIR}"
        )
        return _REPO_CSV_DIR
    return primary


def get_csv_dir_label(base_dir=None):
    """Short label for UI file lists (e.g. data_files or csv_files)."""
    return os.path.basename(get_csv_dir(base_dir))


_TRANSACTION_DEDUP_COLUMNS = (
    sources_schema.SOURCE_ID,
    "Partner Name",
    "Booking Date",
    "Value Date",
    "Amount (EUR)",
    "Original Currency",
    "Payment Reference",
    "Type",
)


def _dedupe_transaction_rows(df):
    """Drop rows duplicated across overlapping CSV exports; keep first occurrence."""
    if df.empty:
        return df
    cols = [c for c in _TRANSACTION_DEDUP_COLUMNS if c in df.columns]
    if not cols:
        return df
    before = len(df)
    df = df.drop_duplicates(subset=cols, keep="first").reset_index(drop=True)
    removed = before - len(df)
    if removed:
        print(
            f"Removed {removed} duplicate transaction(s) from overlapping CSV exports."
        )
    return df


def read_csv_files_to_df(folder_name="csv_files", base_dir=None):
    """Read all CSV files from folder into a single deduplicated DataFrame."""
    if folder_name == "csv_files":
        full_path = get_csv_dir(base_dir)
    else:
        full_path = os.path.join(get_base_dir(base_dir), folder_name)

    if not os.path.exists(full_path):
        print(f"Directory not found: {full_path}")
        print(f"Current working directory is: {os.getcwd()}")
        return pd.DataFrame()

    config_root = get_base_dir(base_dir)
    df = sources_loader.load_all_transactions(full_path, base_dir=config_root)
    for message in sources_loader.get_last_load_errors():
        print(f"Warning: failed to load CSV — {message}")

    if df.empty:
        return df
    df = settlement_filter.mark_card_settlements(df)
    return _dedupe_transaction_rows(df)


_PAYMENT_PREFIX_RE = re.compile(
    r"^(?:Zettle_|PAYPAL\s+\*|SumUp\s+\*|UZR\*|SQ|SPC\*)\*?",
    re.IGNORECASE,
)


def normalize_partner_name(name, mapping_file="mappings.txt", base_dir=None):
    """Strip payment-provider prefixes and apply mappings.txt (case-insensitive)."""
    if not isinstance(name, str):
        return name
    name = _PAYMENT_PREFIX_RE.sub("", name)
    for key, value in read_mappings_file(mapping_file=mapping_file, base_dir=base_dir):
        if key.lower() in name.lower():
            return value
    return name.strip()


def modify_partner_name(df, mapping_file="mappings.txt", base_dir=None):
    """Normalize Partner Name (prefix strip + mappings)."""
    if df.empty:
        return df
    df = df.copy()
    df["Partner Name"] = df["Partner Name"].apply(
        lambda n: normalize_partner_name(n, mapping_file=mapping_file, base_dir=base_dir)
    )
    return df


def read_mappings_file(mapping_file="mappings.txt", base_dir=None):
    """Return list of (from_pattern, to_name) from mappings file."""
    root = get_base_dir(base_dir)
    path = os.path.join(root, mapping_file)
    out = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "," in line:
                    k, v = line.split(",", 1)
                    out.append((k.strip(), v.strip()))
    return out


def write_mappings_file(rows, mapping_file="mappings.txt", base_dir=None, *, allow_write=False):
    """Write list of (from_pattern, to_name) to mappings file. rows: list of (str, str)."""
    root = get_base_dir(base_dir)
    path = os.path.join(root, mapping_file)
    file_guard.assert_write_allowed(path, allow_write=allow_write, purpose="update mappings")
    with open(path, "w", encoding="utf-8") as f:
        for k, v in rows:
            f.write(f"{k}, {v}\n")


def read_permitted_categories(
    permitted_file="permitted_categories.txt",
    base_dir=None,
):
    """Return allowed category names from permitted_categories.txt."""
    root = get_base_dir(base_dir)
    path = os.path.join(root, permitted_file)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


_CATEGORY_MAPPING_SEP = "\t"


def _parse_legacy_comma_line(line, permitted):
    """Parse pre-tab lines: peel a permitted category from the right across commas."""
    line = (line or "").strip().rstrip(",")
    if not line:
        return None
    parts = [p.strip() for p in line.split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return (parts[0], "")
    allowed = set(permitted)
    for n in range(1, len(parts)):
        cat = parts[-n]
        if cat in allowed and not is_income_refund_category(cat):
            partner = ", ".join(parts[:-n]).strip()
            if partner:
                return (partner, cat)
    return (", ".join(parts), "")


def _parse_category_mapping_line(line, permitted=None):
    """Parse one category_mapping.txt line (tab-separated, or legacy comma format)."""
    line = (line or "").strip()
    if not line:
        return None
    if _CATEGORY_MAPPING_SEP in line:
        partner, cat = line.split(_CATEGORY_MAPPING_SEP, 1)
        return (partner.strip(), cat.strip()) if partner.strip() else None
    if permitted:
        return _parse_legacy_comma_line(line, permitted)
    if "," not in line:
        return (line, "")
    partner, cat = (p.strip() for p in line.rsplit(",", 1))
    return (partner, cat.rstrip(",").strip()) if partner else None


def _is_partner_prefix(shorter, longer):
    shorter = (shorter or "").strip()
    longer = (longer or "").strip()
    if not shorter or not longer or shorter == longer:
        return False
    return longer.startswith(shorter) and longer[len(shorter)] in ",\t "


def _read_category_mapping_raw(category_file="category_mapping.txt", base_dir=None):
    """Return (partner, category) rows as stored in the file (may include duplicate partners)."""
    root = get_base_dir(base_dir)
    path = os.path.join(root, category_file)
    permitted = read_permitted_categories(base_dir=base_dir)
    out = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_category_mapping_line(line, permitted=permitted or None)
                if parsed:
                    out.append(parsed)
    return out


def _merge_prefix_duplicate_partners(rows):
    """Merge rows where one partner is a prefix of another (truncated bank labels)."""
    rows = _dedupe_category_rows(rows)
    if len(rows) < 2:
        return rows

    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            p_i, p_j = rows[i][0], rows[j][0]
            if _is_partner_prefix(p_i, p_j) or _is_partner_prefix(p_j, p_i):
                union(i, j)

    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(rows[i])

    merged = []
    for group in groups.values():
        best_partner = max((p for p, _c in group), key=len)
        best_cat = ""
        for _p, cat in group:
            if cat:
                best_cat = cat
                break
        merged.append((best_partner, best_cat))
    return merged


def read_category_mapping_file(category_file="category_mapping.txt", base_dir=None):
    """Return one (partner, category) per partner for UI (deduped, preferring non-empty category)."""
    raw = _read_category_mapping_raw(category_file=category_file, base_dir=base_dir)
    return _merge_prefix_duplicate_partners(raw)


def _partner_identity_key(partner):
    """Normalize partner strings for deduplication (comma spacing)."""
    return re.sub(r",\s*", ", ", (partner or "").strip())


def _dedupe_category_rows(rows):
    """One row per partner; prefer non-empty category; preserve first-seen order."""
    dedup = {}
    key_for_partner = {}
    for partner, cat in rows:
        partner = (partner or "").strip()
        cat = (cat or "").strip()
        if not partner:
            continue
        key = _partner_identity_key(partner)
        if key not in key_for_partner:
            key_for_partner[key] = partner
            dedup[partner] = cat
        else:
            canon = key_for_partner[key]
            if not dedup[canon] and cat:
                dedup[canon] = cat
    return [(key_for_partner[k], dedup[key_for_partner[k]]) for k in key_for_partner]


def write_category_mapping_file(rows, category_file="category_mapping.txt", base_dir=None, *, allow_write=False):
    """Write list of (partner, category) to category mapping file. rows: list of (str, str)."""
    root = get_base_dir(base_dir)
    path = os.path.join(root, category_file)
    file_guard.assert_write_allowed(path, allow_write=allow_write, purpose="update category mapping")
    merged = _merge_prefix_duplicate_partners(rows)
    with open(path, "w", encoding="utf-8") as f:
        for partner, cat in merged:
            f.write(f"{partner}{_CATEGORY_MAPPING_SEP}{cat}\n")


def compact_category_mapping_file(category_file="category_mapping.txt", base_dir=None, *, allow_write=False):
    """Rewrite category_mapping.txt so each partner appears on exactly one line."""
    write_category_mapping_file(
        read_category_mapping_file(category_file=category_file, base_dir=base_dir),
        category_file=category_file,
        base_dir=base_dir,
        allow_write=allow_write,
    )


def clear_income_categories_from_mapping_file(
    category_file="category_mapping.txt", base_dir=None, *, allow_write=False
):
    """Remove Income / Refund (and legacy Income) from partner mappings — assigned by amount in pipeline."""
    rows = read_category_mapping_file(category_file=category_file, base_dir=base_dir)
    new_rows = [(p, "" if is_income_refund_category(c) else c) for p, c in rows]
    if any(is_income_refund_category(c) for _p, c in rows):
        write_category_mapping_file(
            new_rows, category_file=category_file, base_dir=base_dir, allow_write=allow_write
        )
        return sum(1 for _p, c in rows if is_income_refund_category(c))
    return 0


def apply_income_refund_by_amount(df, amount_col="Amount (EUR)"):
    """
    Positive amounts → Income / Refund (automatic).
    Non-positive amounts → never Income / Refund (use expense category from mapping).
    """
    if df.empty or "Category" not in df.columns:
        return df
    df = df.copy()
    amounts = pd.to_numeric(df[amount_col], errors="coerce")
    df.loc[amounts > 0, "Category"] = INCOME_REFUND_CATEGORY
    income_on_expense = amounts <= 0
    income_on_expense &= df["Category"].map(is_income_refund_category)
    df.loc[income_on_expense, "Category"] = None
    return df


def merge_category_mapping(
    updates, category_file="category_mapping.txt", base_dir=None, transaction_df=None, *, allow_write=False
):
    """Apply (partner, category) updates and rewrite the file once (deduped). Skips empty categories."""
    del transaction_df  # kept for call-site compatibility
    existing = dict(read_category_mapping_file(category_file=category_file, base_dir=base_dir))
    for partner, cat in updates:
        partner = (partner or "").strip()
        cat = (cat or "").strip()
        if not partner or not cat or is_income_refund_category(cat):
            continue
        existing[partner] = cat
    write_category_mapping_file(
        list(existing.items()), category_file=category_file, base_dir=base_dir, allow_write=allow_write
    )


def map_name(df, mapping_file="mappings.txt", base_dir=None):
    """Apply partner name mappings from file (same as modify_partner_name)."""
    return modify_partner_name(df, mapping_file=mapping_file, base_dir=base_dir)


def migrate_category_mapping_keys(
    category_file="category_mapping.txt",
    base_dir=None,
    mapping_file="mappings.txt",
    *,
    allow_write=False,
):
    """Rewrite category_mapping.txt: normalize partners, merge prefix dupes, tab format."""
    rows = read_category_mapping_file(category_file=category_file, base_dir=base_dir)
    if not rows:
        return
    migrated = {}
    for partner, cat in rows:
        norm = normalize_partner_name(partner, mapping_file=mapping_file, base_dir=base_dir)
        if not norm:
            continue
        cat = (cat or "").strip()
        if norm not in migrated:
            migrated[norm] = cat
        elif not migrated[norm] and cat:
            migrated[norm] = cat
    write_category_mapping_file(
        list(migrated.items()), category_file=category_file, base_dir=base_dir, allow_write=allow_write
    )


def update_category_mapping(
    df,
    category_file="category_mapping.txt",
    base_dir=None,
    mapping_file="mappings.txt",
    *,
    allow_write=False,
):
    """Add new partners (empty category) and rewrite file once (no duplicate lines)."""
    migrate_category_mapping_keys(
        category_file=category_file,
        base_dir=base_dir,
        mapping_file=mapping_file,
        allow_write=allow_write,
    )
    rows = dict(read_category_mapping_file(category_file=category_file, base_dir=base_dir))
    changed = False
    if not df.empty:
        for partner in df["Partner Name"].unique():
            if not isinstance(partner, str):
                continue
            partner = partner.strip()
            if partner and partner not in rows:
                rows[partner] = ""
                changed = True
    raw = _read_category_mapping_raw(category_file=category_file, base_dir=base_dir)
    if changed or len(raw) != len(rows):
        write_category_mapping_file(
            list(rows.items()), category_file=category_file, base_dir=base_dir, allow_write=allow_write
        )


def map_category(
    df,
    category_file="category_mapping.txt",
    base_dir=None,
    mapping_file="mappings.txt",
):
    """Map Partner Name to Category using category file."""
    if df.empty:
        return df

    category_map = {}
    for partner, cat in read_category_mapping_file(
        category_file=category_file, base_dir=base_dir
    ):
        norm = normalize_partner_name(partner, mapping_file=mapping_file, base_dir=base_dir)
        if norm and (norm not in category_map or (cat and not category_map[norm])):
            category_map[norm] = cat

    df = df.copy()
    df["Category"] = df["Partner Name"].map(category_map)
    df["Category"] = df["Category"].replace("", None)
    return df


def run_pipeline(
    folder_name="csv_files",
    mapping_file="mappings.txt",
    category_file="category_mapping.txt",
    base_dir=None,
):
    """
    Run full pipeline: load CSVs, clean names, apply mappings, map categories.
    Read-only for config files (category_mapping.txt, mappings.txt) and CSV data sources.
    Returns DataFrame with columns: Partner Name, Amount (EUR), Booking Date, Currency, Category,
    Amount (EUR) converted, and ExpenseIndex as index.
    Currency: original transaction currency; missing/empty treated as EUR.
    Amount (EUR) converted: value in EUR using the rate at date of purchase (bank rate when available).
    """
    base_dir = get_base_dir(base_dir)
    df = read_csv_files_to_df(folder_name=folder_name, base_dir=base_dir)
    df = modify_partner_name(df)
    df = map_name(df, mapping_file=mapping_file, base_dir=base_dir)
    df = map_category(df, category_file=category_file, base_dir=base_dir)

    # Ensure required columns exist (older CSVs may lack Original Currency)
    if "Original Currency" not in df.columns:
        df["Original Currency"] = "EUR"
    df["Amount (EUR)"] = pd.to_numeric(df["Amount (EUR)"], errors="coerce")
    df["Booking Date"] = pd.to_datetime(df["Booking Date"], errors="coerce")

    pipeline_cols = [
        "Partner Name",
        "Amount (EUR)",
        "Booking Date",
        "Original Currency",
        "Category",
    ]
    if "Original Amount" in df.columns:
        pipeline_cols.append("Original Amount")
    if "Exchange Rate" in df.columns:
        pipeline_cols.append("Exchange Rate")
    if sources_schema.SOURCE_ID in df.columns:
        pipeline_cols.append(sources_schema.SOURCE_ID)
    if settlement_filter.SETTLEMENT_EXCLUDED_COL in df.columns:
        pipeline_cols.append(settlement_filter.SETTLEMENT_EXCLUDED_COL)
    result = df[pipeline_cols].copy()
    result = result.rename(columns={"Original Currency": "Currency"})
    if sources_schema.SOURCE_ID in result.columns:
        result["Source"] = result[sources_schema.SOURCE_ID].map(
            sources_schema.source_display_name
        )
        result = result.drop(columns=[sources_schema.SOURCE_ID])
    result["Currency"] = result["Currency"].fillna("EUR").replace("", "EUR").astype(str).str.strip()
    result.loc[result["Currency"].str.upper() == "", "Currency"] = "EUR"
    result = currency_conv.add_display_amount_columns(result, base_dir=base_dir)
    result = apply_income_refund_by_amount(result)
    result.reset_index(drop=True, inplace=True)
    result.index.name = "ExpenseIndex"
    return result
