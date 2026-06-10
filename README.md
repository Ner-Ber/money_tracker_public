# Money Tracker (public template)

Personal expense tracking with a CSV pipeline, trip **sequences**, asset snapshots, and an interactive **Dash** dashboard. This repository is a sanitized template: it ships with **fictional demo data** and only a reference **N26 CSV reader**. Bank- and broker-specific parsers are intentionally omitted so you can add your own formats without exposing private account details.

## Quick start

```bash
git clone <your-public-repo-url>
cd money_tracker_public
pip install -r requirements.txt
python -m money_tracker.dashboard
```

Open http://127.0.0.1:8050 — the dashboard loads demo transactions from `csv_files/n26/demo_transactions.csv`.

Optional helper script (repo-only, no Google Drive paths):

```bash
bash scripts/start_local_dev.sh
```

## What you get out of the box

| Included | Purpose |
|----------|---------|
| `csv_files/n26/demo_transactions.csv` | Fictional N26-shaped export |
| `mappings.txt`, `category_mapping.txt` | Partner normalization and categories |
| `permitted_categories.txt` | Allowed category labels |
| `assets.json` | Two demo assets (checking + savings) |
| `assets_log.json` | Fictional balance snapshots (checking anchor + savings history) |
| `sequences.json` | Sample trip sequence |
| `exchange_rates.json` | FX rates for multi-currency views |

## Configuration (`.env`)

The app runs **without** a `.env` file. Copy the template when you want optional features:

```bash
cp .env.example .env
```

| Variable | Required for | Notes |
|----------|--------------|-------|
| `GEMINI_API_KEY` | AI auto-categorization | [Google AI Studio](https://aistudio.google.com/apikey) |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `REPORT_EMAIL_TO` | Email reports | [Gmail app password](https://support.google.com/accounts/answer/185833) |
| `MONEY_TRACKER_*` | Custom paths / server | See `.env.example` |

If a feature needs a missing or placeholder value, the UI and API raise clear errors pointing you to `.env.example`.

## Adding your banks and asset reports

Format-specific code lives in dedicated modules — the rest of the app stays unchanged.

### Checking / expense CSV exports

1. Add `money_tracker/sources/readers/<bank>.py` (implement `BankReader.read`).
2. If needed, add `money_tracker/sources/<bank>_format.py` to map columns to the [canonical schema](money_tracker/sources/schema.py) (N26 export is the reference shape).
3. Register the reader in `money_tracker/sources/registry.py`.
4. Copy `sources.yaml.example` → `sources.yaml` and set `reader:` per folder under `csv_files/`.
5. Drop your exports in `csv_files/<source_id>/`.

See [docs/dev-multi-source.md](docs/dev-multi-source.md).

### Asset balance reports (PDF, Excel, …)

1. Add `money_tracker/assets/parsers/<format>.py`.
2. Register in `money_tracker/assets/parsers/registry.py`.
3. Point each asset at a parser in `assets.json`.

See [docs/adding-parsers.md](docs/adding-parsers.md).

## Project layout

```
csv_files/           # Bank CSV exports (subfolder per source_id)
asset_reports/       # Balance/holdings reports for asset parsers
assets.json          # Asset registry
mappings.txt         # Partner name normalization
category_mapping.txt # Partner → category
sequences.json       # Trip / event sequences
money_tracker/       # Application code
  sources/           # CSV readers + loader
  assets/            # Asset engine + report parsers
  dashboard.py       # Dash UI entry point
```

## Dashboard features

- **Charts** — filter by date, category, and period (week/month).
- **Sequences** — group expenses into trips or events.
- **Assets** — track balances; bank accounts can follow CSV transaction totals.
- **Reports** — export PDF or email HTML summary (email requires `.env`).

## PDF export on Linux/WSL

WeasyPrint may need native libraries:

```bash
conda install -c conda-forge pango cairo gdk-pixbuf2
# or: sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0
```

## Tests

```bash
PYTHONPATH=.:tests pytest tests -q -k "not browser"
```

## Private vs public workflow

Keep your real exports, account numbers, and institution-specific parsers in a **private** repository. Publish sanitized changes to this public template (separate repo or filtered mirror) — branches alone cannot hide data on a public remote.
