# MLflow Benchmark Handoff Design

## Status

- Date: 2026-08-30
- Scope: `llm-inference-lab` benchmark registry and the sanitized handoff to
  product evaluation repositories
- Decision owner: repository maintainer

## Context

`llm-inference-lab` keeps reviewed serving profiles and benchmark summaries in
Git while the shared MLflow experiment stores queryable `serving-recipe` and
`measurement` runs. Product repositories such as EDR1 may then project their
aggregate product-evaluation results into the same experiment and link them to
an exact serving recipe.

The current repository publisher is a generic, non-idempotent import client. It
does not create the shared registry's recipe/measurement hierarchy and does not
emit a machine-readable handoff. As observed on 2026-08-30, the shared
`dgx-spark-llm-inference` experiment contains 7 `serving-recipe` runs, 12
`measurement` runs, and 3 `product-evaluation` runs.

Historical identity cannot be reconstructed by hashing today's sanitized
profile. For example, the stored Gemma eager-seq4 recipe identifies profile
SHA-256 `4c948052...`, while the current public profile bytes hash to
`a7677555...`. The historical ID remains valid evidence of the bytes used at
publication time; the current file is a different sanitized projection.

## Goals

1. Audit existing recipe/measurement relationships without rewriting or
   deleting historical runs.
2. Export a sanitized handoff for an existing valid relationship while
   preserving the stored historical identity.
3. Publish future serving recipes and measurements idempotently.
4. Emit one stable handoff contract that a product repository can consume when
   creating its own aggregate evaluation projection.
5. Keep remote writes explicit, reviewable, and independent of the benchmark
   clients and static leaderboard.

## Non-goals

- Automatically change an EDR1 checkpoint, report, or projection manifest.
- Copy prompts, responses, traces, Tool arguments, item scores, or annotations.
- Recalculate, replace, or normalize historical recipe IDs.
- Delete or merge repeated measurements merely because they share a recipe.
- Move shared MLflow deployment, authentication, backup, or retention ownership
  into this repository.
- Publish to a remote MLflow server without an explicit `--apply` operation.

## Approaches considered

### Extend the generic import publisher

This would overload `publish_record.py`, whose contract intentionally supports
arbitrary reviewed imports. Recipe identity, parent-child relationships, and
read-back reconciliation are stricter concerns and would make the generic
publisher harder to understand. This approach is rejected.

### Recompute every recipe ID from the current profile

This is simple but corrupts provenance when a profile was later sanitized or
otherwise changed. It would also break existing product-evaluation links. This
approach is rejected.

### Add a dedicated benchmark registry synchronizer

The selected approach adds a focused CLI and pure contract module. Existing
runs are read-only audit/backfill inputs. Future runs use content identities,
idempotent lookup, explicit apply, and verified read-back.

## Architecture

### Pure contract module

`tracking/mlflow/benchmark_registry.py` owns deterministic, server-independent
behavior:

- validate a serving profile and normalized benchmark record;
- compute future recipe and measurement identities;
- flatten the reviewed fields used as MLflow params/tags/metrics;
- validate a stored recipe/measurement relationship;
- build `serving-benchmark-handoff/v1` output;
- classify current-profile provenance as `exact`, `historical-drift`, or
  `unavailable` without changing the stored recipe ID.

The module does not import MLflow and is covered by ordinary unit tests.

`tracking/mlflow/serving-benchmark-handoff.schema.json` defines the exact
machine-readable output contract. The pure module validates its own output
against the same required fields without adding a runtime JSON Schema
dependency.

### MLflow adapter and CLI

`tracking/mlflow/scripts/sync_benchmark.py` owns MLflow I/O and exposes three
subcommands:

```text
sync_benchmark.py audit
sync_benchmark.py export --recipe-run-id ID --measurement-run-id ID [--output PATH]
sync_benchmark.py publish --profile PATH --run-set PATH --run-id ID [--apply] [--output PATH]
```

`audit` and `export` are read-only. `publish` is dry-run by default and performs
remote mutation only with `--apply`. Credentials, tracking URI, and certificate
configuration remain outside Git.

### Existing generic publisher

`tracking/mlflow/scripts/publish_record.py` remains available for its documented
generic import use. The new benchmark registry CLI does not silently change its
behavior.

## Identity rules

### Future serving recipes

For newly published recipes:

```text
recipe.id = "sha256:" + sha256(profile file bytes)
```

The stored `recipe.profile_sha256` is the digest without the prefix. Profile
bytes are hashed before contacting MLflow and uploaded as reviewed evidence.
Changing any profile byte creates a new recipe identity; it never updates an
existing recipe.

### Future measurements

The measurement identity is a SHA-256 of canonical JSON containing exactly:

```json
{
  "benchmark_run_id": "<normalized run id>",
  "recipe_id": "sha256:<profile digest>",
  "result_sha256": "<raw benchmark result digest>"
}
```

The canonical JSON uses UTF-8, sorted keys, no insignificant whitespace, and no
NaN/Infinity values. The resulting value is stored as `measurement.id` with the
`sha256:` prefix.

Records without `provenance.result_sha256` cannot be newly published by this
contract. Historical MLflow measurements without `measurement.id` remain valid
legacy evidence when their stored relationship passes audit.

## Handoff contract

The sanitized output contains no credentials, endpoint URL, private host path,
raw response, or product-evaluation data:

```json
{
  "schema_version": "serving-benchmark-handoff/v1",
  "experiment": "dgx-spark-llm-inference",
  "recipe": {
    "id": "sha256:<stored profile digest>",
    "run_id": "<finished serving-recipe run id>",
    "profile_path": "benchmarks/openai-compatible/profiles/example.json",
    "profile_sha256": "<stored profile digest>",
    "profile_state": "exact"
  },
  "measurement": {
    "id": "sha256:<measurement digest>",
    "run_id": "<finished measurement run id>",
    "benchmark_run_id": "<normalized run id>",
    "result_sha256": "<raw result digest>"
  },
  "model": {
    "id": "<model artifact id>",
    "revision": "<immutable revision>",
    "quantization": "<quantization description>"
  },
  "serving": {
    "engine": "<normalized engine name>",
    "version": "<runtime version>"
  }
}
```

JSON `null`, not the string `"null"`, represents unavailable legacy fields.
Consumers use `recipe.id` as the linking key. MLflow run IDs are supporting
provenance, not a substitute for the recipe identity.

The CLI writes the handoff to standard output by default. When `--output` is
given, it resolves the destination beneath the repository root; the recommended
location is `artifacts/handoffs/`, which remains outside Git. A reviewed,
sanitized example may be committed separately, but the CLI never commits or
copies a handoff into another repository.

## Existing-data audit and backfill

The first implementation audits every `serving-recipe` and `measurement` run in
the selected experiment. It reports these states:

- `linked`: both runs are `FINISHED`; parent run, recipe ID, model ID, and
  serving engine agree;
- `historical-profile-drift`: the relationship is linked, but the current file
  at `recipe.profile_path` hashes differently from the stored
  `recipe.profile_sha256`;
- `profile-unavailable`: the relationship is linked, but the recorded profile
  path is not present in the current checkout;
- `unlinked-measurement`: the measurement lacks a recipe parent;
- `conflict`: stored identity fields disagree or a recipe ID resolves to more
  than one recipe run;
- `non-finished`: either selected run is not `FINISHED`.

`linked`, `historical-profile-drift`, and `profile-unavailable` relationships
may be exported. Drift/unavailability is retained in `recipe.profile_state` and
the stored historical digest is preserved. Conflicts, unlinked measurements,
and non-finished runs fail closed.

Repeated measurements linked to the same recipe are not duplicates by
definition. Each is retained unless an independent evidence review proves that
two run IDs represent the same accidental publication. This feature performs no
deletion.

## New publication flow

1. Load one reviewed profile, select exactly one `--run-id` from the normalized
   `--run-set`, and validate both inputs.
2. Require the run's model artifact and serving fields to agree with the
   profile and require `provenance.result_sha256`.
3. Compute `recipe.id` and `measurement.id` locally.
4. In dry-run mode, print the proposed identities, params, metrics, tags, and
   handoff preview without contacting MLflow.
5. With `--apply`, resolve the experiment and look up the exact identities.
6. Reuse exactly one matching, `FINISHED` recipe/measurement; create the missing
   run; reject duplicates, conflicts, and non-finished matches.
7. Store the measurement as a child of the recipe and verify all invariant
   fields by reading both runs back.
8. Emit the consumable handoff only after successful read-back.
9. Reapplying the same inputs is a no-op and returns the same run IDs.

If creation fails after a run exists, the adapter marks that new run `FAILED`
and does not emit a consumable handoff.

## Product-repository boundary

The product repository remains the owner of its evaluation checkpoint, report,
history, and projection manifest. It may consume the handoff by copying only
the model, serving, recipe, and supporting run identities into a reviewed
projection manifest. It must independently verify that the endpoint used for
evaluation matches the selected handoff.

This first phase does not write to EDR1. EDR1-side draft generation and CI
dry-run/reconciliation are a separate change after this contract is implemented
and reviewed.

## Error handling and safety

- All workspace paths are resolved beneath the repository root.
- Profile and record JSON must be objects with required scalar fields.
- Finite numeric validation applies before metrics are constructed.
- Read-only commands never create experiments or runs.
- `--apply` is required for every remote mutation.
- A mismatched existing identity is an error, never an update.
- Stored historical hashes are never replaced by current sanitized hashes.
- Output redacts MLflow credentials and omits tracking/public URLs.
- Raw benchmark artifacts remain outside Git and are not uploaded unless a
  separately reviewed publication contract explicitly names them.

## Testing

Unit tests cover deterministic identities, profile/record agreement, handoff
serialization, historical drift, legacy-null handling, relationship conflicts,
and non-finite metrics. Adapter tests use a fake store to prove dry-run purity,
idempotent reuse, create/read-back behavior, parent linkage, and failure
handling. Existing local publisher tests continue to pass.

Live shared-MLflow verification is a separately authorized operation:

1. run `audit` and review counts/statuses;
2. export one historical-drift Gemma relationship without mutation;
3. dry-run one current profile/record pair;
4. publish only after reviewing the dry-run and obtaining explicit approval;
5. reapply and verify a no-op with identical run IDs.

## Documentation

`tracking/mlflow/README.md` documents the new registry workflow, distinguishes
it from the generic importer, and shows the product handoff boundary.
`benchmarks/results/README.md` explains that a reviewed normalized result and
profile are the publication inputs, while raw result data stays outside Git.
