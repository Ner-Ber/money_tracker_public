# Multi-source CSV loading

This note describes how to add **checking-account CSV exports** to the expense pipeline.

## Folder layout

```
csv_files/
  n26/       # N26 exports (included: demo_transactions.csv)
  other/     # fallback until you add a bank-specific reader
```

Flat `csv_files/*.csv` still works: all root-level files are treated as `source_id=n26`.

## Configuration

Copy [`sources.yaml.example`](../sources.yaml.example) to `sources.yaml` in the repo root to override reader assignments per folder.

## Adding a new bank

1. Add `money_tracker/sources/readers/<bank>.py` implementing `BankReader.read`.
2. If the export is not already N26-shaped, add `money_tracker/sources/<bank>_format.py` to map columns (see `money_tracker/sources/schema.py` for required fields).
3. Register the reader in `money_tracker/sources/registry.py` (`_BUILTIN_READERS` and `_DEFAULT_SOURCE_READERS`).
4. Set `reader: <bank>` for the source folder in `sources.yaml`.
5. Add tests under `tests/test_sources_<bank>.py` with fixture CSVs in `tests/fixtures/csv/`.

The bundled **N26 reader** is the reference implementation — it reads the export as-is with `pd.read_csv`. Use it as a template for simple formats.

## Settlement deduplication

If you link a credit-card source to a checking account and need to hide duplicate settlement rows, implement logic in `money_tracker/settlement_filter.py` (stub in this template).

Send a sample export (headers + a few rows, encoding/delimiter) when implementing a new reader.
