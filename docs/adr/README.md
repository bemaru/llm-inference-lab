# Architecture Decision Records

Architecturally significant technical decisions and their trade-offs for this lab.

Use an ADR for durable choices that affect system boundaries, interfaces, dependencies, quality attributes, or benchmark methodology. Keep experiment results, temporary settings, and routine operational notes elsewhere.

## Convention

- Use `NNNN-title-with-dashes.md` for decision records.
- Start with `proposed`; change to `accepted` only after review.
- Record context, considered options, outcome, consequences, and confirmation.
- Preserve accepted decisions. Replace a changed decision with a new record that marks the old one as superseded.
- Keep external evidence in `docs/research/` and link to it instead of copying the full research into an ADR.

Use [adr-template.md](adr-template.md) when creating an ADR.

## Records

- [ADR-0001: Use an MLPerf Endpoints-derived methodology for LLM serving benchmarks](0001-use-mlperf-endpoints-derived-benchmark-methodology.md) — proposed
- [ADR-0002: Use MLflow for optional local experiment tracking](0002-use-mlflow-for-benchmark-experiment-tracking.md) — proposed
