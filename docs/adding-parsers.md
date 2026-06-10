# Adding asset report parsers

Asset parsers read files from `asset_reports/` and append balance snapshots to `assets_log.json`.

## Steps

1. **Create a parser module** — `money_tracker/assets/parsers/<name>.py`

   Export one or more functions that accept a file path and return a dict:

   ```python
   def parse_pdf(path: str) -> dict[str, object] | None:
       ...
       return {
           "value": 12345.67,
           "currency": "EUR",
           "as_of": "2025-10-31",
       }
   ```

   Use `parse_xlsx` for Excel exports. Return `None` when the file does not match.

2. **Register the parser** — `money_tracker/assets/parsers/registry.py`

   Add entries to `PARSERS`, `PARSER_EXTENSIONS`, and `PARSER_LABELS`.

3. **Wire assets** — edit `assets.json`

   ```json
   {
     "id": "my_broker",
     "name": "My Brokerage",
     "type": "brokerage",
     "currency": "USD",
     "parser": "my_broker_xlsx"
   }
   ```

   Bank accounts that use both CSV transactions and periodic PDF statements should set `expense_source_id` to the CSV source folder id.

4. **Add tests** — `tests/test_assets_parsers_<name>.py` with a redacted fixture under `tests/fixtures/reports/`.

5. **Drop reports** in `asset_reports/` — the engine picks them up on dashboard startup or via the Assets tab.

## Parameterized parsers

When one PDF layout covers many accounts (different fund or account numbers), register separate parser ids with `functools.partial` in the registry, each binding the account-specific constants.

## Public template

This repository ships with an **empty parser registry**. Demo assets in `assets.json` derive checking balances from CSV transactions only; add parsers when you connect real report files.
