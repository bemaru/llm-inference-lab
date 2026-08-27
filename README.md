# LLM Inference Lab

LLM serving experiments, OpenAI-compatible endpoint benchmarks, and curated
performance records. The examples focus on single-node inference, including
DGX Spark / GB10 configurations.

## Start here

- [Benchmark workflow](benchmarks/openai-compatible/README.md): Quick checks and
  sustained endpoint characterization.
- [DGX Spark leaderboard](leaderboards/README.md): a static view of comparable
  measurements, with explicit limitations.
- [Normalized results](benchmarks/results/README.md): reviewed aggregate records
  and source hashes.
- [Local MLflow](tracking/mlflow/README.md): optional experiment metadata and
  artifact tracking.

## Serving examples

- [vLLM](engines/vllm/README.md)
- [SGLang](engines/sglang/README.md)
- [Ollama](engines/ollama/README.md)
- [SparkRun](engines/sparkrun/README.md)
- [DGX Spark host and tunnel setup](hardware/dgx-spark/README.md)

Supply your own host, model access, cache paths, and credentials. Check the
upstream model and runtime terms before using or redistributing their artifacts.
Model weights, raw prompts/responses, credentials, and host-specific execution
logs are not included.

## Reading the results

The retained measurements are Quick checks or characterization previews, not
deployment recommendations or official MLPerf results. Compare only records
within the same comparison group. Throughput and tool-schema pass rates do not
establish answer quality.

Only normalized aggregates are retained here. Source hashes identify the
underlying evidence; they do not make unavailable raw runs independently
reproducible. Re-running requires your own compatible endpoint.

## Local checks

From the repository root, without starting a model server:

```bash
python3 -m unittest discover -s benchmarks/openai-compatible/tests -p 'test_*.py'
python3 -m unittest discover -s leaderboards -p 'test_*.py'
bash tracking/mlflow/tests/local_client_test.sh
python3 leaderboards/build.py --check
```

See also [design decisions](docs/adr/README.md),
[research notes](docs/research/README.md), and the
[run-log template](templates/run-log.md).
