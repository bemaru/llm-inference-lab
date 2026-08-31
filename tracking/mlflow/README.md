# MLflow integration

Optional experiment tracking for reviewed benchmark records. Git keeps code,
schemas, and curated results; MLflow can store run metadata and explicitly
selected artifacts. The benchmark clients and static leaderboard work without
MLflow, and there is no automatic synchronization between them.

This directory owns the publishing client and a local development example.
Shared-server deployment, authentication, storage, and backups belong in the
server owner's operations repository.

## Use an existing tracking server

The Python publisher accepts `--tracking-uri` or `MLFLOW_TRACKING_URI`; it does
not require the local Compose stack. It uses `mlflow-skinny==3.13.0` and requires
`uv` with Python 3.10 or later. Configure the server's approved authentication
outside the repository; do not put credentials in URLs, manifests, or Git.

The following command **creates a run and uploads files**. Run it only with
permission to publish to the target experiment, after reviewing the manifest
and its source artifact. From the repository root, replace the example URL:

```bash
export MLFLOW_TRACKING_URI="https://mlflow.example.com"
uv run --locked --script tracking/mlflow/scripts/publish_record.py \
  --workspace . \
  --manifest tracking/mlflow/imports/example.json
```

Use the Python entry point for an existing server. The `publish.sh` wrapper
instead discovers the local Compose port and overrides `MLFLOW_TRACKING_URI`.
Compatibility and authenticated publication must be verified against your
target server; the local tests below do not establish either.

## What gets recorded

- One manifest creates one run with its `params`, `metrics`, and `tags`. The
  publisher uploads both `source_artifact` and the manifest, and records the
  source file's SHA-256.
- [The example manifest](imports/example.json) attaches the complete normalized
  result set with an empty `metrics` object. It does **not** turn each result
  into a separate run or populate throughput/TTFT comparison charts. Per-run
  metric mapping needs separately reviewed manifests.
- Repeating the command creates another run; publication is not idempotent.
  It creates the named experiment if one does not already exist.
- Manifest and source paths must resolve inside the workspace. The publisher
  checks structure, paths, and finite metric values, not disclosure safety.
  Use reviewed, sanitized inputs; never copy private raw reports or credentials
  into this repository merely to publish them.

## Benchmark registry workflow

The dedicated registry synchronizer is stricter than the generic importer. It
links one reviewed serving profile to one normalized benchmark run, computes
content identities locally, and emits a sanitized
`serving-benchmark-handoff/v1` contract for a product repository to consume.

Run a disconnected dry-run from the repository root. This command does not
need `MLFLOW_TRACKING_URI`, import MLflow, contact a server, or create a run:

```bash
uv run --locked --script tracking/mlflow/scripts/sync_benchmark.py publish \
  --profile benchmarks/openai-compatible/profiles/gemma4-26b-a4b-nvfp4-vllm-dspark.json \
  --run-set benchmarks/results/dgx-spark.json \
  --run-id 20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02
```

The dry-run prints the proposed recipe and measurement identities, reviewed
params/tags/metrics, and a handoff preview with null MLflow run IDs. The recipe
identity hashes the exact profile bytes. The measurement identity hashes
canonical JSON containing the benchmark run ID, recipe ID, and retained raw
result SHA-256.

The following commands contact an existing server. `audit` and `export` are
read-only; they do not create an experiment or a run:

```bash
export MLFLOW_TRACKING_URI="https://mlflow.example.com"
uv run --locked --script tracking/mlflow/scripts/sync_benchmark.py audit
uv run --locked --script tracking/mlflow/scripts/sync_benchmark.py export \
  --recipe-run-id RECIPE_RUN_ID \
  --measurement-run-id MEASUREMENT_RUN_ID \
  --output artifacts/handoffs/example.json
```

`audit` classifies links as `linked`, `historical-profile-drift`,
`profile-unavailable`, `unlinked-measurement`, `conflict`, or `non-finished`.
Export preserves stored historical identities and fails closed for non-exportable
relationships.

Publication mutates the configured server only when `--apply` is present:

```bash
uv run --locked --script tracking/mlflow/scripts/sync_benchmark.py publish \
  --profile benchmarks/openai-compatible/profiles/gemma4-26b-a4b-nvfp4-vllm-dspark.json \
  --run-set benchmarks/results/dgx-spark.json \
  --run-id 20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02 \
  --apply \
  --output artifacts/handoffs/gemma4-baseline.json
```

Review the dry-run and obtain explicit publication approval before adding
`--apply`. Reapplying identical inputs reuses exactly one matching FINISHED
recipe/measurement pair; duplicate identities, conflicting fields,
non-finished runs, and read-back mismatches are errors.

Output files must remain below the repository root. The recommended
`artifacts/handoffs/` location is ignored by Git. A handoff contains model,
serving, recipe, and supporting run identities only; it does not contain raw
responses, traces, per-item evaluation data, credentials, or tracking URLs.
The product repository remains responsible for its evaluation checkpoint,
report, history, and projection manifest.

## Optional local development example

Skip this section when using an existing server. The Compose example runs
MLflow 3.13.0 and PostgreSQL on loopback for development, not as a shared or
production service. It is not a required part of the lab workflow.

Requires Docker Compose and `uv`. These commands start services; the smoke and
publish steps create test data in that local instance:

```bash
cp tracking/mlflow/.env.example tracking/mlflow/.env
tracking/mlflow/scripts/start.sh
tracking/mlflow/scripts/status.sh
tracking/mlflow/scripts/smoke.sh
tracking/mlflow/scripts/publish.sh tracking/mlflow/imports/example.json
tracking/mlflow/scripts/stop.sh
```

Use the local URL printed by the scripts. Do not expose the development stack
to an untrusted network. Stopping preserves the Docker volumes.

## Local checks without a server

```bash
bash tracking/mlflow/tests/local_client_test.sh
```

This checks wrapper behavior using temporary stubs. It does not start Docker,
contact a tracking server, or verify a real upload.

See [the tracking decision](../../docs/adr/0002-use-mlflow-for-benchmark-experiment-tracking.md).
