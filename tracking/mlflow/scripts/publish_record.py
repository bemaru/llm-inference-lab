#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mlflow-skinny==3.13.0",
# ]
# ///
"""Publish one provenance-preserving import manifest to MLflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

from mlflow import MlflowClient
from mlflow.entities import Metric, Param, RunTag


def as_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def scalar_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


def resolve_workspace_file(workspace: Path, relative_path: str) -> Path:
    candidate = (workspace / relative_path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as error:
        raise ValueError(f"path escapes workspace: {relative_path}") from error
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workspace", default="/workspace")
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"))
    parser.add_argument("--public-uri", default="")
    args = parser.parse_args()

    if not args.tracking_uri:
        raise ValueError("tracking URI is required")

    workspace = Path(args.workspace).resolve()
    manifest_path = resolve_workspace_file(workspace, args.manifest)
    manifest = as_mapping(
        json.loads(manifest_path.read_text(encoding="utf-8")), "manifest"
    )

    if manifest.get("schema_version") != "mlflow-import/v1":
        raise ValueError("unsupported schema_version")

    experiment_name = str(manifest["experiment"])
    run_name = str(manifest["run_name"])
    source_relative = str(manifest["source_artifact"])
    source_path = resolve_workspace_file(workspace, source_relative)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

    raw_params = as_mapping(manifest.get("params", {}), "params")
    raw_metrics = as_mapping(manifest.get("metrics", {}), "metrics")
    raw_tags = as_mapping(manifest.get("tags", {}), "tags")

    metrics: list[Metric] = []
    timestamp = int(time.time() * 1000)
    for key, raw_value in raw_metrics.items():
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"metric {key} is not finite")
        metrics.append(Metric(str(key), value, timestamp, 0))

    params = [Param(str(key), scalar_text(value)) for key, value in raw_params.items()]
    params.append(Param("evidence.source_sha256", source_sha256))

    tags = [RunTag(str(key), scalar_text(value)) for key, value in raw_tags.items()]
    tags.extend(
        [
            RunTag("mlflow.runName", run_name),
            RunTag("import.schema_version", str(manifest["schema_version"])),
            RunTag("evidence.source_path", source_relative),
        ]
    )

    client = MlflowClient(tracking_uri=args.tracking_uri)
    experiment = client.get_experiment_by_name(experiment_name)
    experiment_id = (
        experiment.experiment_id
        if experiment is not None
        else client.create_experiment(experiment_name)
    )
    created_run = client.create_run(experiment_id, tags={"mlflow.runName": run_name})
    run_id = created_run.info.run_id

    try:
        client.log_batch(run_id, metrics=metrics, params=params, tags=tags)
        client.log_artifact(run_id, str(source_path), artifact_path="evidence")
        client.log_artifact(run_id, str(manifest_path), artifact_path="metadata")
        client.set_terminated(run_id, status="FINISHED")
    except Exception:
        client.set_terminated(run_id, status="FAILED")
        raise

    result = {
        "status": "ok",
        "experiment": experiment_name,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "source_artifact": source_relative,
        "source_sha256": source_sha256,
    }
    if args.public_uri:
        result["run_url"] = (
            f"{args.public_uri.rstrip('/')}/#/experiments/{experiment_id}/runs/{run_id}"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
