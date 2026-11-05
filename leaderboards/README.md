# Leaderboards

Static, repository-owned views generated from normalized benchmark summaries.
They are evidence indexes, not raw-data stores or deployment approvals.

## DGX Spark

- Source: [`../benchmarks/results/dgx-spark.json`](../benchmarks/results/dgx-spark.json)
- Output: [`dgx-spark.html`](dgx-spark.html)
- Generator: [`build.py`](build.py)

From the repository root:

```bash
python3 leaderboards/build.py
python3 leaderboards/build.py --check
```

The generated page works as a local file and through a static HTTP server. For
example:

```bash
python3 -m http.server 18080 --bind 127.0.0.1
```

Then open `http://127.0.0.1:18080/leaderboards/dgx-spark.html`.

Only records in the same `comparison_group` may receive a rank. Quick and smoke
records remain explicitly separate from future standard characterization runs.

## Google Sheets summary (optional)

[`build_sheet.py`](build_sheet.py) turns the same results, plus the Nemotron
characterization preview record, into a Korean summary spreadsheet with key
findings, per-group leaders, the run table, comparison groups, and a glossary.
The repository JSON stays the source of truth. The spreadsheet is a generated,
one-way view: each refresh replaces its generated tabs and discards edits made
in the spreadsheet. Change the layout in `build_sheet.py` instead.

The key findings are written by hand in `build_sheet.py`, and each one encodes
the comparison its sentence claims. `--check` fails when a referenced run
disappears or new data contradicts a claim; update the text in that case.

```bash
python3 leaderboards/build_sheet.py --check
python3 leaderboards/build_sheet.py --output artifacts/sheet-requests.json
```

Publishing **writes to Google Drive**. Run it only with permission to change the
target spreadsheet. It calls the authenticated `gws` (Google Workspace CLI)
with the spreadsheets scope; select the account with `gws`'s own configuration
outside the repository, and do not commit spreadsheet IDs or account settings.

```bash
python3 leaderboards/build_sheet.py --create "DGX Spark LLM 서빙 실험 요약"
python3 leaderboards/build_sheet.py --spreadsheet-id "$SHEET_ID"
```

A refresh fills new staging tabs first and swaps them in at the end, so a failed
run leaves the previous tabs in place. The spreadsheet link stays the same, but
the generated tabs get new tab IDs (`gid`). Other tabs are left untouched;
formulas in them that point at generated tabs break on refresh.
