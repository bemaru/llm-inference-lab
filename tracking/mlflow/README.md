# Local MLflow

Optional local experiment tracking with MLflow 3.13.0 and PostgreSQL. Git keeps
the curated records; MLflow can keep run metadata and explicitly selected
artifacts. This loopback-only stack is a development setup, not a shared or
production service.

## Start and verify

Requires Docker Compose and `uv`. From the repository root:

```bash
cp tracking/mlflow/.env.example tracking/mlflow/.env
tracking/mlflow/scripts/start.sh
tracking/mlflow/scripts/status.sh
tracking/mlflow/scripts/smoke.sh
```

Use the local URL printed by the scripts. Do not expose the development stack
to an untrusted network.

## Publish a reviewed record

```bash
tracking/mlflow/scripts/publish.sh tracking/mlflow/imports/example.json
```

The example publishes the normalized result set as an artifact. The publisher
records its SHA-256 and validates the record before sending it. Review the
selected artifact and metadata before publishing; local raw results can contain
endpoint addresses, prompts, and responses.

```bash
tracking/mlflow/scripts/stop.sh
bash tracking/mlflow/tests/local_client_test.sh
```

Stopping preserves the Docker volumes. The client test uses temporary stubs and
does not start Docker or contact a tracking server.

See [the tracking decision](../../docs/adr/0002-use-mlflow-for-benchmark-experiment-tracking.md).
