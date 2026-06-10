# Instructions for AI agents

This file is for **AI coding agents** (Cursor, Copilot, Claude Code, etc.) helping a user adapt this repository to their personal finances.

## Your role

Guide the user from **demo data** to **their real banks and assets**. The application core is complete; your job is to collect samples, implement format-specific interpreters, wire configuration, and verify the dashboard loads real data.

Do **not** ask the user to modify `dashboard.py`, `data_loading.py`, or the canonical schema unless they need genuinely new fields.

## Phase 0 — Confirm environment

1. Ask which OS they use (Linux, macOS, WSL, Windows).
2. Confirm Python **3.9+** is available.
3. Run from repo root:

```bash
pip install -r requirements.txt
python -m money_tracker.dashboard
```

4. If port **8050** is in use, suggest:

```bash
MONEY_TRACKER_PORT=8051 python -m money_tracker.dashboard
```

5. Confirm they see demo data (12 transactions, ~€25.7k total assets) before replacing anything.

Optional features (only if the user wants them):

```bash
cp .env.example .env
# fill GEMINI_API_KEY, Gmail settings
```

## Phase 1 — Discover what they track

Ask structured questions and keep a checklist:

| Question | Why |
|----------|-----|
| Which **checking / card accounts** export CSV (or PDF) transaction history? | One reader per export format |
| Which **assets** do they track (checking, savings, brokerage, pension, crypto)? | `assets.json` entries |
| For each non-bank asset: what **report file** proves the balance (PDF statement, Excel export, portal download)? | One parser per report format |
| Which **currency** is each account in? | `assets.json` + `exchange_rates.json` |
| Do they use **multiple banks** or one card settled through a checking account? | May need `settlement_filter.py` later |

Tell the user: **redact account numbers and personal names** in samples shared with you; headers and 3–5 example rows are enough to build parsers.

## Phase 2 — Collect samples (required before coding)

Request **one sample per format**:

### Checking / expenses (transaction exports)

- [ ] CSV (or PDF) export from each bank/card source
- [ ] Note: delimiter, encoding (UTF-8?), date format, debit/credit column layout
- [ ] Where they will drop files: `csv_files/<source_id>/`

Example ask:

> “Please export last month from your bank as CSV and paste the header row plus 3 anonymized data rows (or attach a redacted file). Tell me the bank name and currency.”

### Asset balances (periodic reports)

- [ ] One **PDF or Excel** report per asset type (brokerage portfolio, pension statement, bank balance PDF, …)
- [ ] Which number on the page is the **total balance** and its **as-of date**
- [ ] Where they will drop files: `asset_reports/`

Example ask:

> “For each investment account, send one recent statement PDF (redacted). Point to the line that shows total value and the statement date.”

### Configuration (optional but helpful)

- [ ] Preferred **category list** (`permitted_categories.txt`)
- [ ] Any known **partner → category** mappings they already use

## Phase 3 — Implement interpreters

Changes stay in **dedicated modules** only.

### Transaction CSV readers

For each new bank export:

1. `money_tracker/sources/readers/<bank>.py` — implement `BankReader.read()`
2. `money_tracker/sources/<bank>_format.py` — map columns → [canonical schema](../money_tracker/sources/schema.py) (N26 export is the reference)
3. Register in `money_tracker/sources/registry.py`
4. Add `sources.yaml` entry: `reader: <bank>`
5. Add fixture + test: `tests/test_sources_<bank>.py`

See [dev-multi-source.md](dev-multi-source.md).

**N26-shaped exports** can reuse the bundled `N26Reader` with no new code.

### Asset report parsers

For each report format:

1. `money_tracker/assets/parsers/<format>.py` — `parse_pdf()` or `parse_xlsx()` returning `{value, currency, as_of}`
2. Register in `money_tracker/assets/parsers/registry.py`
3. Set `"parser": "<id>"` on the asset in `assets.json`
4. Bank assets with both CSV expenses and PDF statements need `"expense_source_id"` linking to the CSV folder id
5. Add test with redacted fixture under `tests/fixtures/reports/`

See [adding-parsers.md](adding-parsers.md).

### Settlement deduplication (only if needed)

If a credit-card CSV duplicates checking-account settlement rows, implement logic in `money_tracker/settlement_filter.py` (currently a no-op stub).

## Phase 4 — Wire user data

1. Replace demo files under `csv_files/` with their exports (keep folder-per-source layout).
2. Replace `assets.json` with their asset registry (start from `assets.json.example`).
3. Replace or append `assets_log.json` via dashboard **Assets** tab or report ingest.
4. Update `mappings.txt` / `category_mapping.txt` as they refine categories.
5. Copy `.env.example` → `.env` only for AI categorization or email reports.

## Phase 5 — Verify

```bash
PYTHONPATH=.:tests pytest tests -q -k "not browser"
python -m money_tracker.dashboard
```

Checklist for the user:

- [ ] Expenses tab shows their transactions (correct dates, amounts, partners)
- [ ] Assets tab shows non-zero balances from reports or projection
- [ ] Categories map as expected
- [ ] No load errors in the dashboard file list / console

## Module map (what to touch vs leave alone)

| User need | Modules to change |
|-----------|-------------------|
| New checking CSV format | `sources/readers/`, `sources/*_format.py`, `sources/registry.py`, `sources.yaml` |
| New card PDF pipeline | New `sources/*_format.py` + loader wiring (see private repo CAL pattern) |
| New asset report | `assets/parsers/`, `assets/parsers/registry.py`, `assets.json` |
| Card/checking duplicate rows | `settlement_filter.py` |
| Categories / partner names | `mappings.txt`, `category_mapping.txt` |
| FX | `exchange_rates.json` |
| Secrets | `.env` only (never commit) |

**Leave unchanged:** `dashboard.py`, `data_loading.py` orchestration, `sources/schema.py`, `sources/normalize.py`, `assets/engine.py` unless adding new cross-cutting fields.

## Communication tips

- Prefer **small PR-sized steps**: one bank reader, then one parser, then verify.
- When samples are ambiguous, ask for a second export month to confirm column stability.
- Warn before overwriting demo data — suggest backing up `csv_files/` and `assets.json`.
- Never commit `.env`, real CSVs, or unredacted PDFs to a public repository.

## Success criteria

The user can run `python -m money_tracker.dashboard`, see **their** expenses and asset totals, and future exports drop into `csv_files/` and `asset_reports/` without code changes.
