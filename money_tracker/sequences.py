"""Sequence management: load/save, create empty, add time spans or indices, exclude indices, apply to dataframe."""

import json
import os
import pandas as pd

from money_tracker import currency as currency_conv
from money_tracker import file_guard
from money_tracker.data_loading import get_base_dir

SEQUENCE_FILE = "sequences.json"
LEGACY_FILE = "sequences.txt"


def _seq_path(sequence_file, base_dir):
    root = get_base_dir(base_dir)
    return os.path.join(root, sequence_file)


def load_sequences(sequence_file=SEQUENCE_FILE, base_dir=None):
    """Load sequences from JSON. Falls back to legacy sequences.txt and converts to new format."""
    path = _seq_path(sequence_file, base_dir)
    legacy_path = _seq_path(LEGACY_FILE, base_dir)

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                raise json.JSONDecodeError("Empty file", "", 0)
            data = json.loads(raw)
        except (json.JSONDecodeError, StopIteration):
            # Corrupted or empty JSON: fall through to legacy or return []
            pass
        else:
            sequences = data.get("sequences", [])
            for seq in sequences:
                seq.setdefault("category", "")
            return sequences

    # Legacy: sequences.txt format name, category, start_date, end_date, expense_indices
    if os.path.exists(legacy_path):
        sequences = []
        with open(legacy_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    seq_name = parts[0].strip()
                    start_date = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
                    end_date = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
                    expense_indices = []
                    if len(parts) > 4:
                        indices_str = ",".join(parts[4:]).strip()
                        if indices_str:
                            try:
                                expense_indices = [
                                    int(x.strip()) for x in indices_str.split(",") if x.strip().isdigit()
                                ]
                            except Exception:
                                pass
                    time_spans = []
                    if start_date and end_date:
                        time_spans.append({"start": start_date, "end": end_date})
                    sequences.append({
                        "name": seq_name,
                        "category": "",
                        "time_spans": time_spans,
                        "expense_indices": expense_indices,
                        "exclude_indices": [],
                    })
        if sequences:
            save_sequences(
                sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=True
            )
        return sequences

    return []


def save_sequences(sequences, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False):
    """Save sequences to JSON. Writes to a temp file then renames for atomicity."""
    path = _seq_path(sequence_file, base_dir)
    tmp_path = path + ".tmp"
    file_guard.assert_write_allowed(path, allow_write=allow_write, purpose="update sequences")
    file_guard.assert_write_allowed(tmp_path, allow_write=allow_write, purpose="update sequences")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"sequences": sequences}, f, indent=2)
    os.replace(tmp_path, path)


def create_sequence(
    name,
    category=None,
    start_date=None,
    end_date=None,
    expense_indices=None,
    sequence_file=SEQUENCE_FILE,
    base_dir=None,
    *,
    allow_write=False,
):
    """Create a new sequence (empty, or with optional time span and/or indices). If name exists, no-op."""
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == name:
            return
    seq = {
        "name": name.strip(),
        "category": (category or "").strip() if category else "",
        "time_spans": [],
        "expense_indices": list(expense_indices) if expense_indices else [],
        "exclude_indices": [],
    }
    if start_date and end_date:
        seq["time_spans"].append({"start": start_date, "end": end_date})
    sequences.append(seq)
    save_sequences(
        sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
    )


def add_timespan(
    sequence_name, start_date, end_date, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Add a time span to a sequence; all expenses in [start_date, end_date] will be included."""
    if not start_date or not end_date:
        raise ValueError("Start and end date are required.")
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == sequence_name:
            span = {"start": start_date, "end": end_date}
            if span not in seq["time_spans"]:
                seq["time_spans"].append(span)
            save_sequences(
                sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
            )
            return
    raise ValueError(f"Sequence '{sequence_name}' not found.")


def remove_timespan(
    sequence_name, start_date, end_date, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Remove a time span from a sequence. start_date and end_date must match an existing span exactly."""
    if not start_date or not end_date:
        raise ValueError("Start and end date are required.")
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == sequence_name:
            span = {"start": start_date, "end": end_date}
            if span in seq["time_spans"]:
                seq["time_spans"].remove(span)
                save_sequences(
                    sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
                )
                return
            raise ValueError(f"No time span {start_date} to {end_date} in sequence '{sequence_name}'.")
    raise ValueError(f"Sequence '{sequence_name}' not found.")


def parse_indices_string(s):
    """Parse a string like '1,5,16-21' into a list of integers [1, 5, 16, 17, 18, 19, 20, 21]."""
    if not s or not str(s).strip():
        return []
    out = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                low, high = int(a.strip()), int(b.strip())
                if low <= high:
                    out.extend(range(low, high + 1))
                else:
                    out.extend(range(high, low + 1))
            except ValueError:
                pass
        else:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return sorted(set(out))


def add_expenses_to_sequence(
    sequence_name, expense_indices, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Add individual expense indices to a sequence."""
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == sequence_name:
            existing = set(seq["expense_indices"])
            for idx in expense_indices:
                if idx not in existing:
                    seq["expense_indices"].append(idx)
                    existing.add(idx)
            seq["expense_indices"].sort()
            save_sequences(
                sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
            )
            return
    raise ValueError(f"Sequence '{sequence_name}' not found.")


def remove_expense_from_sequence(
    sequence_name, index, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Remove a single expense from a sequence (add to exclude list)."""
    remove_expenses_from_sequence(
        sequence_name, [index], sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
    )


def remove_expenses_from_sequence(
    sequence_name, indices, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Remove multiple expenses from a sequence (add to exclude list)."""
    if not indices:
        raise ValueError("At least one index is required.")
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == sequence_name:
            for index in indices:
                if index not in seq["exclude_indices"]:
                    seq["exclude_indices"].append(index)
            seq["exclude_indices"].sort()
            save_sequences(
                sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
            )
            return
    raise ValueError(f"Sequence '{sequence_name}' not found.")


def rename_sequence(old_name, new_name, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False):
    """Rename a sequence."""
    if not new_name or not str(new_name).strip():
        raise ValueError("New name is required.")
    new_name = str(new_name).strip()
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == old_name:
            seq["name"] = new_name
            save_sequences(
                sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
            )
            return
    raise ValueError(f"Sequence '{old_name}' not found.")


def set_sequence_category(
    sequence_name, category, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Set the main display category for a sequence (used in Charts as 'Category - SequenceName')."""
    sequences = load_sequences(sequence_file=sequence_file, base_dir=base_dir)
    for seq in sequences:
        if seq["name"] == sequence_name:
            seq["category"] = (category or "").strip() if category else ""
            save_sequences(
                sequences, sequence_file=sequence_file, base_dir=base_dir, allow_write=allow_write
            )
            return
    raise ValueError(f"Sequence '{sequence_name}' not found.")


def get_sequence_expense_indices(seq, df):
    """Return set of dataframe indices that belong to this sequence (time_spans + expense_indices - exclude_indices)."""
    if df.empty:
        return set()
    in_set = set()
    for idx in seq.get("expense_indices", []):
        if idx in df.index:
            in_set.add(idx)
    for span in seq.get("time_spans", []):
        try:
            start = pd.to_datetime(span["start"])
            end = pd.to_datetime(span["end"])
            mask = (df["Booking Date"] >= start) & (df["Booking Date"] <= end)
            in_set.update(df.loc[mask].index.tolist())
        except Exception:
            pass
    in_set -= set(seq.get("exclude_indices", []))
    return in_set


def apply_sequences_to_df(df, sequences=None, base_dir=None):
    """Set Display Category to 'Category - SequenceName' for each expense that belongs to a sequence."""
    if df.empty:
        return df

    if sequences is None:
        sequences = load_sequences(base_dir=base_dir)

    df = df.copy()
    df["Display Category"] = df["Category"].copy()

    for seq in sequences:
        seq_name = seq["name"]
        indices = get_sequence_expense_indices(seq, df)
        if indices:
            display_cat = seq.get("category") or None
            for idx in indices:
                if idx in df.index:
                    cat = display_cat or df.at[idx, "Category"]
                    df.at[idx, "Display Category"] = f"{cat} - {seq_name}"

    return df


def sequence_expenses_df(df, sequence_name, sequences=None, base_dir=None, display_currency="EUR"):
    """Return expenses in one sequence with amounts in the selected display currency."""
    amt_col = currency_conv.pick_amount_column(df, display_currency)
    amount_label = currency_conv.amount_axis_label(display_currency)
    base_cols = ["Index", "Partner Name", "Booking Date", "Category"]
    if df.empty:
        out_cols = base_cols + ["Currency", amount_label]
        return pd.DataFrame(columns=out_cols)
    if sequences is None:
        sequences = load_sequences(base_dir=base_dir)
    seq = next((s for s in sequences if s["name"] == sequence_name), None)
    if not seq:
        out_cols = base_cols + ["Currency", amount_label]
        return pd.DataFrame(columns=out_cols)
    indices = get_sequence_expense_indices(seq, df)
    rows = []
    for idx in indices:
        if idx not in df.index:
            continue
        row = df.loc[idx]
        r = {
            "Index": idx,
            "Partner Name": row["Partner Name"],
            "Booking Date": row["Booking Date"],
            "Category": row["Category"],
        }
        if "Currency" in df.columns:
            r["Currency"] = row["Currency"]
        if "Source" in df.columns:
            r["Source"] = row["Source"]
        r[amount_label] = row[amt_col]
        rows.append(r)
    if not rows:
        out_cols = base_cols + ["Currency", amount_label]
        if "Source" in df.columns:
            out_cols.insert(2, "Source")
        return pd.DataFrame(columns=out_cols)
    return pd.DataFrame(rows).sort_values("Booking Date")


def sequences_expenses_df(df, sequences=None, base_dir=None):
    """Return a DataFrame of all sequence members: Sequence, Index, Partner Name, Currency, Amount (EUR) converted, Booking Date, Category."""
    amt_col = "Amount (EUR) converted" if not df.empty and "Amount (EUR) converted" in df.columns else "Amount (EUR)"
    if df.empty:
        cols = ["Sequence", "Index", "Partner Name", "Booking Date", "Category"]
        if amt_col == "Amount (EUR) converted":
            cols.insert(4, "Currency")
            cols.insert(5, "Amount (EUR) converted")
        else:
            cols.insert(4, "Amount (EUR)")
        return pd.DataFrame(columns=cols)

    if sequences is None:
        sequences = load_sequences(base_dir=base_dir)

    rows = []
    for seq in sequences:
        indices = get_sequence_expense_indices(seq, df)
        for idx in indices:
            if idx not in df.index:
                continue
            row = df.loc[idx]
            r = {
                "Sequence": seq["name"],
                "Index": idx,
                "Partner Name": row["Partner Name"],
                "Booking Date": row["Booking Date"],
                "Category": row["Category"],
            }
            if "Currency" in df.columns:
                r["Currency"] = row["Currency"]
            if "Source" in df.columns:
                r["Source"] = row["Source"]
            r["Amount (EUR) converted" if amt_col == "Amount (EUR) converted" else "Amount (EUR)"] = row[amt_col]
            rows.append(r)

    if not rows:
        cols = ["Sequence", "Index", "Partner Name", "Booking Date", "Category"]
        if amt_col == "Amount (EUR) converted":
            cols.insert(4, "Currency")
            cols.insert(5, "Amount (EUR) converted")
        else:
            cols.insert(4, "Amount (EUR)")
        if not df.empty and "Source" in df.columns:
            cols.insert(3, "Source")
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    return out.sort_values(["Sequence", "Booking Date"])


# Legacy API compatibility (used by notebook / existing code)
def assign_expenses_to_sequence(
    sequence_name, expense_indices, sequence_file=SEQUENCE_FILE, base_dir=None, *, allow_write=False
):
    """Assign expense indices to an existing sequence (adds to sequence)."""
    add_expenses_to_sequence(
        sequence_name,
        expense_indices,
        sequence_file=sequence_file,
        base_dir=base_dir,
        allow_write=allow_write,
    )
