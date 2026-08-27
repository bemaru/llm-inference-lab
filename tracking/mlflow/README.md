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
