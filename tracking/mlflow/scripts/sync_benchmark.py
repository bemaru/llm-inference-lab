#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mlflow-skinny==3.13.0",
# ]
# ///
"""Synchronize reviewed benchmark recipes and measurements with MLflow."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Protocol


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tracking.mlflow import benchmark_registry as registry


DEFAULT_EXPERIMENT = "dgx-spark-llm-inference"


class RunCreationError(RuntimeError):
    def __init__(self, run_id: str, message: str) -> None:
        super().__init__(message)
        self.run_id = run_id


class RegistryStore(Protocol):
    def list_runs(self, experiment: str) -> list[registry.StoredRun]: ...

    def find_by_identity(
        self, experiment: str, role: str, key: str, value: str
    ) -> list[registry.StoredRun]: ...

    def create_recipe(
        self,
        experiment: str,
        payload: registry.PublicationPayload,
        profile_path: Path,
    ) -> registry.StoredRun: ...

    def create_measurement(
        self,
        experiment: str,
        payload: registry.PublicationPayload,
        parent_run_id: str,
    ) -> registry.StoredRun: ...

    def read_run(self, run_id: str) -> registry.StoredRun: ...

    def mark_failed(self, run_id: str) -> None: ...


def _publication_preview(
    experiment: str,
    inputs: registry.PublicationInputs,
    payload: registry.PublicationPayload,
) -> dict[str, Any]:
    return {
        "schema_version": "serving-benchmark-handoff/v1",
        "experiment": experiment,
        "recipe": {
            "id": payload.recipe_id,
            "run_id": None,
            "profile_path": inputs.profile_path,
            "profile_sha256": payload.profile_sha256,
            "profile_state": "exact",
        },
        "measurement": {
            "id": payload.measurement_id,
            "run_id": None,
            "benchmark_run_id": payload.measurement_params["benchmark.run_id"],
            "result_sha256": payload.measurement_params[
                "evidence.result_sha256"
            ],
        },
        "model": {
            "id": payload.recipe_params["model.id"],
            "revision": payload.recipe_params["model.revision"],
            "quantization": payload.recipe_params["model.quantization"],
        },
        "serving": {
            "engine": payload.recipe_params["serving.engine"],
            "version": payload.recipe_params["serving.version"],
        },
    }


def publish_command(
    args: argparse.Namespace,
    store_factory: Callable[[], RegistryStore],
) -> dict[str, Any]:
    root = Path(args.repository_root).resolve()
    inputs = registry.load_publication_inputs(
        root, args.profile, args.run_set, args.run_id
    )
    payload = registry.publication_payload(inputs)
    preview = _publication_preview(args.experiment, inputs, payload)
    if not args.apply:
        return {
            "mode": "dry-run",
            "experiment": args.experiment,
            "recipe": {
                "id": payload.recipe_id,
                "action": "propose",
                "params": dict(payload.recipe_params),
                "tags": dict(payload.recipe_tags),
            },
            "measurement": {
                "id": payload.measurement_id,
                "action": "propose",
                "params": dict(payload.measurement_params),
                "tags": dict(payload.measurement_tags),
                "metrics": dict(payload.measurement_metrics),
            },
            "handoff_preview": preview,
        }

    store = store_factory()
    recipe_matches = store.find_by_identity(
        args.experiment,
        "serving-recipe",
        "recipe.id",
        payload.recipe_id,
    )
    recipe = _single_match(recipe_matches, "serving-recipe", payload.recipe_id)
    recipe_action = "reuse"
    if recipe is None:
        recipe_action = "create"
        try:
            recipe = store.create_recipe(
                args.experiment, payload, (root / inputs.profile_path).resolve()
            )
        except RunCreationError as error:
            store.mark_failed(error.run_id)
            raise RuntimeError(str(error)) from error
    else:
        _verify_stored_run(
            recipe,
            payload.recipe_params,
            payload.recipe_tags,
            {},
            "serving-recipe",
        )

    measurement_matches = store.find_by_identity(
        args.experiment,
        "measurement",
        "measurement.id",
        payload.measurement_id,
    )
    measurement = _single_match(
        measurement_matches, "measurement", payload.measurement_id
    )
    measurement_action = "reuse"
    if measurement is None:
        measurement_action = "create"
        try:
            measurement = store.create_measurement(
                args.experiment, payload, recipe.run_id
            )
        except RunCreationError as error:
            store.mark_failed(error.run_id)
            raise RuntimeError(str(error)) from error
    else:
        _verify_stored_run(
            measurement,
            payload.measurement_params,
            payload.measurement_tags,
            payload.measurement_metrics,
            "measurement",
        )

    recipe_read_back = store.read_run(recipe.run_id)
    measurement_read_back = store.read_run(measurement.run_id)
    relationship = registry.classify_relationship(
        recipe_read_back, measurement_read_back, root
    )
    if not relationship.exportable:
        raise ValueError(f"read-back relationship is {relationship.status}")
    handoff = registry.build_handoff(
        args.experiment,
        recipe_read_back,
        measurement_read_back,
        relationship.profile_state,
    )
    registry.validate_handoff(handoff)
    return {
        "mode": "apply",
        "experiment": args.experiment,
        "recipe": {
            "id": payload.recipe_id,
            "run_id": recipe_read_back.run_id,
            "action": recipe_action,
        },
        "measurement": {
            "id": payload.measurement_id,
            "run_id": measurement_read_back.run_id,
            "action": measurement_action,
        },
        "handoff": handoff,
    }


def _single_match(
    matches: list[registry.StoredRun], role: str, identity: str
) -> registry.StoredRun | None:
    if len(matches) > 1:
        raise ValueError(f"multiple {role} runs match identity {identity}")
    return matches[0] if matches else None


def _verify_stored_run(
    run: registry.StoredRun,
    expected_params: Any,
    expected_tags: Any,
    expected_metrics: Any,
    role: str,
) -> None:
    if run.status != "FINISHED":
        raise ValueError(f"matching {role} run {run.run_id} is not FINISHED")
    for key, expected in expected_params.items():
        if run.params.get(key) != expected:
            raise ValueError(f"matching {role} run conflicts on param {key}")
    for key, expected in expected_tags.items():
        if run.tags.get(key) != expected:
            raise ValueError(f"matching {role} run conflicts on tag {key}")
    for key, expected in expected_metrics.items():
        actual = run.metrics.get(key)
        if actual is None or not math.isclose(float(actual), float(expected)):
            raise ValueError(f"matching {role} run conflicts on metric {key}")


def audit_command(
    args: argparse.Namespace, store: RegistryStore
) -> dict[str, Any]:
    root = Path(args.repository_root).resolve()
    runs = store.list_runs(args.experiment)
    recipes = {
        run.run_id: run
        for run in runs
        if registry.stored_value(run, "registry.role") == "serving-recipe"
    }
    measurements = [
        run
        for run in runs
        if registry.stored_value(run, "registry.role") == "measurement"
    ]
    recipe_identity_counts: dict[str, int] = {}
    for recipe in recipes.values():
        recipe_id = registry.stored_value(recipe, "recipe.id")
        if recipe_id is not None:
            recipe_identity_counts[recipe_id] = recipe_identity_counts.get(recipe_id, 0) + 1

    counts = {
        "linked": 0,
        "historical-profile-drift": 0,
        "profile-unavailable": 0,
        "unlinked-measurement": 0,
        "conflict": 0,
        "non-finished": 0,
    }
    relationships: list[dict[str, Any]] = []
    for measurement in measurements:
        parent_id = registry.stored_value(measurement, "recipe.parent_run_id")
        if parent_id is None:
            parent_id = registry.stored_value(measurement, "mlflow.parentRunId")
        recipe = recipes.get(parent_id or "")
        measurement_recipe_id = registry.stored_value(measurement, "recipe.id")
        if recipe is None:
            result = registry.RelationshipResult(
                "unlinked-measurement", None, measurement_recipe_id
            )
        elif (
            measurement_recipe_id is not None
            and recipe_identity_counts.get(measurement_recipe_id, 0) > 1
        ):
            result = registry.RelationshipResult(
                "conflict", None, measurement_recipe_id
            )
        else:
            result = registry.classify_relationship(recipe, measurement, root)
        counts[result.status] += 1
        relationships.append(
            {
                "recipe_run_id": recipe.run_id if recipe is not None else None,
                "measurement_run_id": measurement.run_id,
                "recipe_id": result.recipe_id,
                "status": result.status,
                "profile_state": result.profile_state,
                "exportable": result.exportable,
            }
        )
    return {
        "mode": "audit",
        "experiment": args.experiment,
        "run_counts": {
            "serving-recipe": len(recipes),
            "measurement": len(measurements),
        },
        "counts": counts,
        "relationships": relationships,
    }


def export_command(
    args: argparse.Namespace, store: RegistryStore
) -> dict[str, Any]:
    root = Path(args.repository_root).resolve()
    recipe = store.read_run(args.recipe_run_id)
    measurement = store.read_run(args.measurement_run_id)
    recipe_id = registry.stored_value(recipe, "recipe.id")
    matching_recipes = [
        run
        for run in store.list_runs(args.experiment)
        if registry.stored_value(run, "registry.role") == "serving-recipe"
        and registry.stored_value(run, "recipe.id") == recipe_id
    ]
    if len(matching_recipes) > 1:
        raise ValueError(f"duplicate recipe.id {recipe_id} in experiment")
    if not matching_recipes or matching_recipes[0].run_id != recipe.run_id:
        raise ValueError("selected recipe run is not in the experiment")
    relationship = registry.classify_relationship(recipe, measurement, root)
    if not relationship.exportable:
        raise ValueError(f"relationship is {relationship.status}")
    handoff = registry.build_handoff(
        args.experiment, recipe, measurement, relationship.profile_state
    )
    registry.validate_handoff(handoff)
    return handoff


def write_result(
    repository_root: Path, relative_path: str, value: Any
) -> Path:
    root = repository_root.resolve()
    output = (root / relative_path).resolve()
    try:
        output.relative_to(root)
    except ValueError as error:
        raise ValueError(f"output path escapes repository root: {relative_path}") from error
    if output.exists() and output.is_dir():
        raise ValueError(f"output path is a directory: {relative_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


class MlflowStore:
    def __init__(self, tracking_uri: str) -> None:
        from mlflow import MlflowClient
        from mlflow.entities import Metric, Param, RunTag

        self.client = MlflowClient(tracking_uri=tracking_uri)
        self.Metric = Metric
        self.Param = Param
        self.RunTag = RunTag

    @staticmethod
    def _stored(run: Any) -> registry.StoredRun:
        return registry.StoredRun(
            run_id=run.info.run_id,
            status=run.info.status,
            params=dict(run.data.params),
            tags=dict(run.data.tags),
            metrics={key: float(value) for key, value in run.data.metrics.items()},
        )

    def _experiment_id(self, experiment: str, *, create: bool) -> str | None:
        existing = self.client.get_experiment_by_name(experiment)
        if existing is not None:
            return existing.experiment_id
        if not create:
            return None
        return self.client.create_experiment(experiment)

    def list_runs(self, experiment: str) -> list[registry.StoredRun]:
        experiment_id = self._experiment_id(experiment, create=False)
        if experiment_id is None:
            return []
        return [
            self._stored(run)
            for run in self.client.search_runs(
                experiment_ids=[experiment_id], max_results=50000
            )
        ]

    def find_by_identity(
        self, experiment: str, role: str, key: str, value: str
    ) -> list[registry.StoredRun]:
        return [
            run
            for run in self.list_runs(experiment)
            if registry.stored_value(run, "registry.role") == role
            and registry.stored_value(run, key) == value
        ]

    def _create(
        self,
        experiment: str,
        run_name: str,
        params: Any,
        tags: Any,
        metrics: Any,
        *,
        artifact: Path | None = None,
    ) -> registry.StoredRun:
        experiment_id = self._experiment_id(experiment, create=True)
        if experiment_id is None:
            raise RuntimeError("failed to resolve MLflow experiment")
        created = self.client.create_run(
            experiment_id, tags={"mlflow.runName": run_name}
        )
        run_id = created.info.run_id
        try:
            timestamp = int(time.time() * 1000)
            self.client.log_batch(
                run_id,
                params=[self.Param(key, value) for key, value in params.items()],
                tags=[self.RunTag(key, value) for key, value in tags.items()],
                metrics=[
                    self.Metric(key, float(value), timestamp, 0)
                    for key, value in metrics.items()
                ],
            )
            if artifact is not None:
                self.client.log_artifact(run_id, str(artifact), artifact_path="evidence")
            self.client.set_terminated(run_id, status="FINISHED")
        except Exception as error:
            raise RunCreationError(run_id, str(error)) from error
        return self.read_run(run_id)

    def create_recipe(
        self,
        experiment: str,
        payload: registry.PublicationPayload,
        profile_path: Path,
    ) -> registry.StoredRun:
        return self._create(
            experiment,
            f"recipe/{payload.recipe_id.removeprefix('sha256:')[:12]}",
            payload.recipe_params,
            payload.recipe_tags,
            {},
            artifact=profile_path,
        )

    def create_measurement(
        self,
        experiment: str,
        payload: registry.PublicationPayload,
        parent_run_id: str,
    ) -> registry.StoredRun:
        tags = dict(payload.measurement_tags)
        tags["recipe.parent_run_id"] = parent_run_id
        tags["mlflow.parentRunId"] = parent_run_id
        return self._create(
            experiment,
            f"measurement/{payload.measurement_params['benchmark.run_id']}",
            payload.measurement_params,
            tags,
            payload.measurement_metrics,
        )

    def read_run(self, run_id: str) -> registry.StoredRun:
        return self._stored(self.client.get_run(run_id))

    def mark_failed(self, run_id: str) -> None:
        self.client.set_terminated(run_id, status="FAILED")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit, export, or publish reviewed benchmark registry records"
    )
    parser.add_argument("--repository-root", default=str(REPOSITORY_ROOT))
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    parser.add_argument(
        "--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("audit")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--recipe-run-id", required=True)
    export_parser.add_argument("--measurement-run-id", required=True)
    export_parser.add_argument("--output")

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--profile", required=True)
    publish_parser.add_argument("--run-set", required=True)
    publish_parser.add_argument("--run-id", required=True)
    publish_parser.add_argument("--apply", action="store_true")
    publish_parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repository_root).resolve()

    def store_factory() -> RegistryStore:
        if not args.tracking_uri:
            raise ValueError("tracking URI is required for this command")
        return MlflowStore(args.tracking_uri)

    if args.command == "publish":
        result = publish_command(args, store_factory)
        output_value = result.get("handoff", result)
    elif args.command == "audit":
        result = audit_command(args, store_factory())
        output_value = result
    else:
        result = export_command(args, store_factory())
        output_value = result

    if getattr(args, "output", None):
        output_path = write_result(root, args.output, output_value)
        print(json.dumps({"output": str(output_path.relative_to(root))}, sort_keys=True))
    else:
        print(json.dumps(output_value, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
