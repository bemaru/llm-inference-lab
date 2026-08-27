# ADR 0002: Use MLflow for optional experiment tracking

- Status: Proposed
- Date: 2026-08-21
- Updated: 2026-08-28

## Context

Benchmark configurations and reviewed aggregate results fit well in Git.
Per-run metadata and larger artifacts benefit from a searchable experiment
registry, but the benchmark tools should remain usable without one.

## Decision

Use MLflow as an optional experiment-tracking integration. Keep code, schemas,
and curated result records in Git. Publish explicitly selected run metadata
and artifacts to an authorized tracking server; keep raw application traces
and credentials outside the public repository.

Keep the publishing client and a loopback-only development example here.
An existing tracking server does not require a local MLflow stack. Shared
hosting, authentication, storage, backups, and production deployment belong
in the server owner's operations repository.

## Consequences

- Benchmark results and the static leaderboard do not require MLflow.
- Artifact publication is explicit; users must review what they upload.
- Source hashes connect published artifacts to the selected input files.
- The supplied manifest uploads a result-set artifact, not per-run comparison
  metrics. Per-run field mapping and target-server verification are separate
  integration work; the repository does not automatically synchronize results.

## References

- [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/)
- [Tracking integration and local example](../../tracking/mlflow/README.md)
