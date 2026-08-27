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
