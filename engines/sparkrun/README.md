# SparkRun

This directory contains the versioned serving lifecycle definitions for the
DGX Spark. SparkRun controls model launch, status, logs, and stop operations;
the benchmark runners, MLflow records, and published leaderboard remain the
measurement system of record.

## Boundaries

- Recipes and this wrapper are committed to Git.
- Active cluster configuration belongs under `~/.config/sparkrun/` on the WSL
  control machine.
- Tokens and other secrets must not appear in recipes, cluster YAML, or Git.
- Model and runtime caches remain on the DGX Spark.
- Do not run `sparkrun setup wizard` on the shared host. It may configure SSH
  mesh, sudoers, earlyoom, and ConnectX-7 settings that are outside this pilot.
- The existing Compose profile remains the rollback path until a SparkRun
  launch passes parity checks.

## Version

The wrapper pins SparkRun `0.3.5` and Python `3.12`, then runs it through
`uvx`:

```bash
./engines/sparkrun/sparkrun --version
```

## Local cluster configuration

Create the WSL-local cluster definition without invoking the setup wizard:

```bash
./engines/sparkrun/sparkrun cluster create dgx-spark-lab \
  --hosts your-host \
  --cache-dir /home/your-user/.cache/huggingface \
  --transfer-mode delegated \
  --executor docker \
  -o privileged=false \
  -o auto_remove=false
```

The generated file is
`~/.config/sparkrun/clusters/dgx-spark-lab.yaml`. The sanitized
`cluster.example.yaml` documents the intended settings. Runtime cache settings
may be copied from the example after confirming the remote path.

If a Hugging Face token is required, keep it in a mode-`0600` local env file
and reference it only from the local cluster definition:

```yaml
env:
  HF_TOKEN: ${HF_TOKEN}
env_file: /home/your-user/.config/sparkrun/dgx-spark.env
```

## Validation

These commands are local/read-only with respect to the running DGX workload:

```bash
recipe=engines/sparkrun/recipes/nemotron35-lightning-30b-a3b-nvfp4-vllm-dspark.yaml

./engines/sparkrun/sparkrun recipe validate "$recipe"
./engines/sparkrun/sparkrun recipe show "$recipe"
./engines/sparkrun/sparkrun run --dry-run \
  --cluster dgx-spark-lab \
  "$recipe"
```

Schedule a real launch in an approved maintenance window. Before cutover, preserve `docker inspect`, `/health`, `/v1/models`,
and host-memory evidence. Stop only the exact existing Nemotron container,
launch this recipe, then repeat chat, tool-call, reasoning, memory, and
performance parity checks.

## Ownership

| Concern | System of record |
| --- | --- |
| Model launch configuration and lifecycle | SparkRun recipe |
| Generic container inspection | Portainer |
| Host metrics | DGX Dashboard |
| Benchmark run metadata and artifacts | MLflow |
| Application traces and quality evaluation | Separate trace/evaluation store |
| Approved comparative results | Static leaderboard |

SparkRun's own benchmark features are not used as the canonical benchmark
pipeline. Each benchmark record should instead include the recipe path and Git
blob hash so the serving configuration remains traceable.
