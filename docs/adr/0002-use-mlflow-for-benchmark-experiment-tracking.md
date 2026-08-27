# ADR 0002: Use MLflow for optional local experiment tracking

- Status: Proposed
- Date: 2026-08-21

## Context

Benchmark configurations and reviewed aggregate results fit well in Git.
Per-run metadata and larger artifacts benefit from a searchable experiment
registry, but the benchmark tools should remain usable without one.

## Decision

Use an optional local MLflow stack. Keep code, schemas, and curated result
records in Git. Store explicitly selected run artifacts in MLflow; keep raw
application traces and credentials outside the public repository.

The local stack binds to loopback and is for development. Shared hosting,
authentication, backups, and production deployment are outside this setup.

## Consequences

- Benchmark results and the static leaderboard do not require MLflow.
- Artifact publication is explicit; users must review what they upload.
- Source hashes connect published artifacts to the selected input files.

## References

- [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/)
- [Local setup](../../tracking/mlflow/README.md)
