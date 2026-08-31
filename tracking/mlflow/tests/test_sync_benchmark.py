from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest

from tracking.mlflow import benchmark_registry as registry
from tracking.mlflow.scripts import sync_benchmark as cli


class FakeStore:
    def __init__(
        self,
        runs: list[registry.StoredRun] | None = None,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.runs = list(runs or [])
        self.fail_on = fail_on
        self.create_calls: list[tuple[str, str | None]] = []
        self.failed_run_ids: list[str] = []
        self.list_calls = 0
        self.read_overrides: dict[str, registry.StoredRun] = {}

    def list_runs(self, experiment: str) -> list[registry.StoredRun]:
        self.list_calls += 1
        return list(self.runs)

    def find_by_identity(
        self, experiment: str, role: str, key: str, value: str
    ) -> list[registry.StoredRun]:
        return [
            run
            for run in self.runs
            if registry.stored_value(run, "registry.role") == role
            and registry.stored_value(run, key) == value
        ]

    def create_recipe(
        self,
        experiment: str,
        payload: registry.PublicationPayload,
        profile_path: Path,
    ) -> registry.StoredRun:
        run = registry.StoredRun(
            run_id="recipe-created",
            status="RUNNING" if self.fail_on == "recipe" else "FINISHED",
            params=dict(payload.recipe_params),
            tags=dict(payload.recipe_tags),
            metrics={},
        )
        self.runs.append(run)
        self.create_calls.append(("recipe", None))
        if self.fail_on == "recipe":
            raise cli.RunCreationError(run.run_id, "recipe creation failed")
        return run

    def create_measurement(
        self,
        experiment: str,
        payload: registry.PublicationPayload,
        parent_run_id: str,
    ) -> registry.StoredRun:
        tags = dict(payload.measurement_tags)
        tags["recipe.parent_run_id"] = parent_run_id
        tags["mlflow.parentRunId"] = parent_run_id
        run = registry.StoredRun(
            run_id="measurement-created",
            status="RUNNING" if self.fail_on == "measurement" else "FINISHED",
            params=dict(payload.measurement_params),
            tags=tags,
            metrics=dict(payload.measurement_metrics),
        )
        self.runs.append(run)
        self.create_calls.append(("measurement", parent_run_id))
        if self.fail_on == "measurement":
            raise cli.RunCreationError(run.run_id, "measurement creation failed")
        return run

    def read_run(self, run_id: str) -> registry.StoredRun:
        if run_id in self.read_overrides:
            return self.read_overrides[run_id]
        return next(run for run in self.runs if run.run_id == run_id)

    def mark_failed(self, run_id: str) -> None:
        self.failed_run_ids.append(run_id)
        for index, run in enumerate(self.runs):
            if run.run_id == run_id:
                self.runs[index] = registry.StoredRun(
                    run_id=run.run_id,
                    status="FAILED",
                    params=run.params,
                    tags=run.tags,
                    metrics=run.metrics,
                )
                return


class _CliFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        profile = {
            "model_artifact": {
                "id": "publisher/model",
                "revision": "revision-1",
                "quantization": "NVFP4",
            },
            "serving": {
                "engine": "vLLM",
                "version": "1.2.3",
                "command_profile": "engines/vllm/example#candidate",
            },
        }
        run = {
            "id": "benchmark-run",
            "comparison_group": "group-1",
            "artifact": {
                "model_id": "publisher/model",
                "revision": "revision-1",
                "quantization": "NVFP4",
            },
            "serving": {
                "engine": "vLLM",
                "version": "1.2.3",
                "profile": "engines/vllm/example#candidate",
            },
            "metrics": {
                "ttft_p95_ms": 123.0,
                "aggregate_output_tps": 45.5,
            },
            "provenance": {"result_sha256": "a" * 64},
        }
        (self.root / "profile.json").write_text(
            json.dumps(profile), encoding="utf-8"
        )
        (self.root / "runs.json").write_text(
            json.dumps({"runs": [run]}), encoding="utf-8"
        )

    def args(self, *, apply: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            repository_root=self.root,
            experiment="dgx-spark-llm-inference",
            profile="profile.json",
            run_set="runs.json",
            run_id="benchmark-run",
            apply=apply,
            output=None,
        )

    def publication(self) -> tuple[
        registry.PublicationInputs, registry.PublicationPayload
    ]:
        inputs = registry.load_publication_inputs(
            self.root, "profile.json", "runs.json", "benchmark-run"
        )
        return inputs, registry.publication_payload(inputs)

    def stored_pair(self) -> tuple[registry.StoredRun, registry.StoredRun]:
        _, payload = self.publication()
        recipe = registry.StoredRun(
            run_id="recipe-existing",
            status="FINISHED",
            params=dict(payload.recipe_params),
            tags=dict(payload.recipe_tags),
            metrics={},
        )
        measurement_tags = dict(payload.measurement_tags)
        measurement_tags["recipe.parent_run_id"] = recipe.run_id
        measurement = registry.StoredRun(
            run_id="measurement-existing",
            status="FINISHED",
            params=dict(payload.measurement_params),
            tags=measurement_tags,
            metrics=dict(payload.measurement_metrics),
        )
        return recipe, measurement


class PublishDryRunTests(_CliFixture):

    def test_publish_dry_run_never_constructs_store(self) -> None:
        result = cli.publish_command(
            self.args(),
            store_factory=lambda: self.fail("store contacted during dry-run"),
        )

        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["recipe"]["action"], "propose")
        self.assertEqual(result["measurement"]["action"], "propose")
        self.assertIsNone(result["handoff_preview"]["recipe"]["run_id"])
        self.assertIsNone(result["handoff_preview"]["measurement"]["run_id"])


class PublishApplyTests(_CliFixture):
    def test_apply_reuses_exact_finished_pair(self) -> None:
        recipe, measurement = self.stored_pair()
        store = FakeStore([recipe, measurement])

        result = cli.publish_command(self.args(apply=True), lambda: store)

        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["recipe"]["action"], "reuse")
        self.assertEqual(result["measurement"]["action"], "reuse")
        self.assertEqual(result["handoff"]["recipe"]["run_id"], recipe.run_id)
        self.assertEqual(store.create_calls, [])

    def test_apply_creates_missing_pair_with_parent_linkage(self) -> None:
        store = FakeStore()

        result = cli.publish_command(self.args(apply=True), lambda: store)

        self.assertEqual(result["recipe"]["action"], "create")
        self.assertEqual(result["measurement"]["action"], "create")
        self.assertEqual(
            store.create_calls,
            [("recipe", None), ("measurement", "recipe-created")],
        )
        measurement = store.read_run("measurement-created")
        self.assertEqual(
            measurement.tags["mlflow.parentRunId"], "recipe-created"
        )

    def test_apply_rejects_duplicate_identity(self) -> None:
        recipe, measurement = self.stored_pair()
        duplicate = registry.StoredRun(
            run_id="recipe-duplicate",
            status=recipe.status,
            params=recipe.params,
            tags=recipe.tags,
            metrics=recipe.metrics,
        )
        store = FakeStore([recipe, duplicate, measurement])

        with self.assertRaisesRegex(ValueError, "multiple serving-recipe"):
            cli.publish_command(self.args(apply=True), lambda: store)

    def test_apply_rejects_read_back_conflict(self) -> None:
        store = FakeStore()
        _, payload = self.publication()
        bad_tags = dict(payload.measurement_tags)
        bad_tags["recipe.id"] = f"sha256:{'f' * 64}"
        bad_tags["recipe.parent_run_id"] = "recipe-created"
        store.read_overrides["measurement-created"] = registry.StoredRun(
            run_id="measurement-created",
            status="FINISHED",
            params=dict(payload.measurement_params),
            tags=bad_tags,
            metrics=dict(payload.measurement_metrics),
        )

        with self.assertRaisesRegex(ValueError, "read-back relationship is conflict"):
            cli.publish_command(self.args(apply=True), lambda: store)

    def test_apply_marks_failed_created_run(self) -> None:
        store = FakeStore(fail_on="measurement")

        with self.assertRaisesRegex(RuntimeError, "measurement creation failed"):
            cli.publish_command(self.args(apply=True), lambda: store)

        self.assertEqual(store.failed_run_ids, ["measurement-created"])


class AuditAndExportTests(_CliFixture):
    def test_audit_is_read_only_and_flags_duplicate_recipe_identity(self) -> None:
        recipe, measurement = self.stored_pair()
        duplicate = registry.StoredRun(
            run_id="recipe-duplicate",
            status=recipe.status,
            params=recipe.params,
            tags=recipe.tags,
            metrics=recipe.metrics,
        )
        store = FakeStore([recipe, duplicate, measurement])
        args = argparse.Namespace(
            repository_root=self.root,
            experiment="dgx-spark-llm-inference",
        )

        result = cli.audit_command(args, store)

        self.assertEqual(result["counts"]["conflict"], 1)
        self.assertEqual(store.create_calls, [])
        self.assertEqual(store.list_calls, 1)

    def test_export_emits_valid_handoff_for_linked_pair(self) -> None:
        recipe, measurement = self.stored_pair()
        store = FakeStore([recipe, measurement])
        args = argparse.Namespace(
            repository_root=self.root,
            experiment="dgx-spark-llm-inference",
            recipe_run_id=recipe.run_id,
            measurement_run_id=measurement.run_id,
            output=None,
        )

        result = cli.export_command(args, store)

        registry.validate_handoff(result)
        self.assertEqual(result["recipe"]["run_id"], recipe.run_id)

    def test_export_rejects_non_exportable_pair(self) -> None:
        recipe, measurement = self.stored_pair()
        running = registry.StoredRun(
            run_id=measurement.run_id,
            status="RUNNING",
            params=measurement.params,
            tags=measurement.tags,
            metrics=measurement.metrics,
        )
        store = FakeStore([recipe, running])
        args = argparse.Namespace(
            repository_root=self.root,
            experiment="dgx-spark-llm-inference",
            recipe_run_id=recipe.run_id,
            measurement_run_id=running.run_id,
            output=None,
        )

        with self.assertRaisesRegex(ValueError, "relationship is non-finished"):
            cli.export_command(args, store)


class OutputTests(_CliFixture):
    def test_write_result_rejects_path_escape(self) -> None:
        with self.assertRaisesRegex(ValueError, "escapes repository root"):
            cli.write_result(self.root, "../handoff.json", {"ok": True})

    def test_write_result_creates_reviewable_json(self) -> None:
        output = cli.write_result(
            self.root, "artifacts/handoffs/example.json", {"z": 1, "a": 2}
        )

        self.assertEqual(
            output, self.root / "artifacts" / "handoffs" / "example.json"
        )
        self.assertEqual(output.read_text(encoding="utf-8"), '{\n  "a": 2,\n  "z": 1\n}\n')


if __name__ == "__main__":
    unittest.main()
