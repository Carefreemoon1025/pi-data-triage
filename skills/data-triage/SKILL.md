---
name: data-triage
description: Profile a CSV or CSV.gz dataset — row/column counts, per-column dtype, missing values, numeric distributions, top categories, and suspicious-column flags — as one JSON object. Use when the user uploads or points at a CSV and needs exploratory data analysis before modeling, cleaning, or feature engineering.
---

# data-triage

Compute a deterministic, pandas-based data profile for a CSV file and return it as a single JSON object.

## Run it

```bash
python3 skills/data-triage/scripts/profile.py --input sample_data/co2-emissions-per-capita.csv.gz
```

Use the project interpreter so pandas resolves:

```bash
<repo>/.venv/bin/python skills/data-triage/scripts/profile.py --input <path.csv[.gz]>
```

All arguments:

| Flag | Meaning |
|---|---|
| `--input <path>` | Required. `.csv` or `.csv.gz` (gzip is detected by magic number, not extension). |
| `--output <path>` | Also write the same JSON object to this file. |
| `--separator <char>` | Field separator. Default `,`. Use `;` or `\t` for other dialects. |
| `--encoding <name>` | Text encoding. Default `utf-8`. |
| `--no-header` | Treat the first row as data instead of column names. |
| `--max-rows <N>` | Cap profiled rows. Omit, or pass `0`/`all`, to profile every row. |

`--max-rows` defaults to **no limit**. Passing a positive integer caps the read and marks `load.truncated` true.

## Output

stdout carries exactly one JSON object. Human-readable status lines go to stderr, so stdout is always safe to pipe.

```json
{"ok": true,
 "dataset": {"name": "co2-emissions-per-capita.csv.gz", "size_bytes": 211235, "fingerprint": "<sha256>"},
 "load": {"loaded_rows": 26509, "row_limit": null, "truncated": false, "notices": []},
 "profile": {"rows": 26509, "columns": 4, "duplicate_rows": 0,
   "numeric_summary": {"<col>": {"min": 0.0, "p25": 0.17, "median": 1.02, "mean": 3.82, "p75": 4.33, "max": 782.74}},
   "categorical_top_values": {"<col>": [["<value>", 230]]},
   "columns_profile": [{"name": "<col>", "dtype": "float64", "non_null_count": 26509,
     "null_count": 0, "null_pct": 0.0, "unique_count": 26025,
     "sample_values": ["..."], "notes": ["..."], "numeric_summary": null, "top_values": []}],
   "suspicious_columns": [],
   "details": {"duplicate_rows_present": false}}}
```

- `dataset.fingerprint` — sha256 of the **decompressed** CSV bytes. Same content, same hash, regardless of gzip level.
- `dataset.size_bytes` — size of the file on disk (the compressed size for `.csv.gz`).
- `load.notices` — `{"level", "code", "message"}` entries from the loader; codes are `row_limit` (truncated) and `large_file` (≥5 MB input).
- `profile.numeric_summary` — one entry per numeric column, with `min`, `p25`, `median`, `mean`, `p75`, `max`.
- `profile.columns_profile` — one entry per column, in file order.
- `profile.suspicious_columns` — the subset of `columns_profile` whose `notes` is non-empty. Read `notes` first; it flags high missingness (≥40% null), constant values, identifier-like columns, high-cardinality categoricals, datetime text stored as string, and extreme numeric ranges.
- `profile.categorical_top_values` — the 5 most frequent values per non-numeric column.

Values are UTF-8, not ASCII-escaped, so Unicode column names such as `CO₂ emissions per capita` appear literally.

## Exit codes

`0` success · `2` usage error (bad or missing arguments, file not found) · `3` load failure (parse, encoding, gzip, empty file) · `4` column or parameter mismatch · `5` missing dependency · `1` unexpected.

On any non-zero exit, stdout still holds `{"ok": false, "error": {"code", "message", "hint"}}`. Read `error.hint` for the next step.

| `error.code` | Fix |
|---|---|
| `input_not_found` | Check the path; pass an existing `.csv`/`.csv.gz`. |
| `invalid_arguments`, `invalid_max_rows`, `invalid_separator` | Fix the command line. |
| `csv_parse_error` | Wrong dialect — retry with `--separator`. |
| `encoding_error` | Retry with `--encoding gbk` (or `latin-1`). |
| `gzip_error` | The `.gz` is corrupt or truncated. |
| `empty_file` | The file has no data rows. |
| `missing_dependency` | Run with `<repo>/.venv/bin/python`. |
| `unexpected_error` | Report the traceback; retry with a smaller `--max-rows`. |

## Notes

- Rows are read with `CsvLoadOptions(max_rows=...)` set explicitly, so no silent 5000-row truncation; check `load.truncated` before drawing conclusions.
- Profiling is pure pandas — no model calls, no network, deterministic across runs.
- The `.gz` is decompressed fully in memory before parsing. For very large compressed inputs, use `--max-rows` and expect a `large_file` notice.
