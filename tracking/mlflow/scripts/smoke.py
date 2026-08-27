#!/usr/bin/env python3
"""Create and verify one MLflow run including a proxied artifact."""

from __future__ import annotations

import argparse
import json

from mlflow import MlflowClient
from mlflow.entities import Metric, Param, RunTag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracking-uri", default="http://127.0.0.1:5000")
    parser.add_argument("--public-uri", default="")
    args = parser.parse_args()

    client = MlflowClient(tracking_uri=args.tracking_uri)
    experiment_name = "llm-inference-lab-stack-validation"
    experiment = client.get_experiment_by_name(experiment_name)
    experiment_id = (
        experiment.experiment_id
        if experiment is not None
        else client.create_experiment(experiment_name)
    )
    created_run = client.create_run(
        experiment_id,
        tags={
            "mlflow.runName": "tracking-and-artifact-smoke",
            "validation.kind": "stack-smoke",
            "repository": "llm-inference-lab",
        },
    )
    run_id = created_run.info.run_id
    client.log_batch(
        run_id,
        metrics=[
            Metric("requests", 1, 0, 0),
            Metric("errors", 0, 0, 0),
            Metric("output_tokens_per_second", 1.0, 0, 0),
        ],
        params=[
            Param("sut.kind", "synthetic"),
            Param("serving.engine", "none"),
            Param("benchmark.profile", "smoke"),
        ],
        tags=[RunTag("validation.status", "writing-artifact")],
    )
    client.log_dict(
        run_id,
        {
            "schema_version": "validation/v1",
            "status": "ok",
            "purpose": "Verify PostgreSQL metadata and proxied artifact storage",
        },
        "validation/smoke.json",
    )
    client.set_tag(run_id, "validation.status", "ok")
    client.set_terminated(run_id, status="FINISHED")

    stored_run = client.get_run(run_id)
    artifacts = client.list_artifacts(run_id, "validation")
    artifact_paths = sorted(item.path for item in artifacts)
    if "validation/smoke.json" not in artifact_paths:
        raise RuntimeError(f"smoke artifact not found: {artifact_paths}")

    result = {
        "status": "ok",
        "run_id": run_id,
        "experiment_id": stored_run.info.experiment_id,
        "artifact_uri": stored_run.info.artifact_uri,
        "artifacts": artifact_paths,
    }
    if args.public_uri:
        result["run_url"] = (
            f"{args.public_uri.rstrip('/')}/#/experiments/"
            f"{stored_run.info.experiment_id}/runs/{run_id}"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
