from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Mapping
import unittest

from tracking.mlflow import benchmark_registry as registry


class IdentityTests(unittest.TestCase):
    def test_recipe_identity_hashes_exact_bytes(self) -> None:
        profile_bytes = b'{"a":1}\n'

        identity, digest = registry.recipe_identity(profile_bytes)

        self.assertEqual(identity, f"sha256:{digest}")
        self.assertEqual(digest, hashlib.sha256(profile_bytes).hexdigest())

    def test_measurement_identity_uses_canonical_json(self) -> None:
        result_sha256 = "f" * 64

        value = registry.measurement_identity(
            "run-1", "sha256:abc", result_sha256
        )

        canonical = (
            b'{"benchmark_run_id":"run-1","recipe_id":"sha256:abc",'
            b'"result_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffff'
            b'ffffffffffffffff"}'
        )
        expected = hashlib.sha256(canonical).hexdigest()
        self.assertEqual(value, f"sha256:{expected}")

    def test_measurement_identity_rejects_invalid_result_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "result_sha256"):
            registry.measurement_identity("run-1", "sha256:abc", "not-a-digest")


class PublicationInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.profile = {
            "model_artifact": {
                "id": "publisher/model",
                "revision": "immutable-revision",
                "quantization": "NVFP4",
            },
            "serving": {
                "engine": "vLLM",
                "version": "1.2.3",
                "command_profile": "engines/vllm/example#candidate",
            },
        }
        self.run = {
            "id": "run-1",
            "comparison_group": "group-1",
            "artifact": {
                "model_id": "publisher/model",
                "revision": "immutable-revision",
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
                "host_available_memory_gib": None,
            },
            "provenance": {"result_sha256": "a" * 64},
        }
        self._write_inputs()

    def _write_inputs(self) -> None:
        (self.root / "profile.json").write_text(
            json.dumps(self.profile), encoding="utf-8"
        )
        (self.root / "runs.json").write_text(
            json.dumps({"runs": [self.run]}, allow_nan=True), encoding="utf-8"
        )

    def _load(self) -> registry.PublicationInputs:
        return registry.load_publication_inputs(
            self.root, "profile.json", "runs.json", "run-1"
        )

    def test_loads_matching_profile_and_builds_reviewed_payload(self) -> None:
        inputs = self._load()

        payload = registry.publication_payload(inputs)

        self.assertEqual(payload.recipe_tags["registry.role"], "serving-recipe")
        self.assertEqual(payload.measurement_tags["registry.role"], "measurement")
        self.assertEqual(payload.recipe_params["model.id"], "publisher/model")
        self.assertEqual(payload.recipe_params["serving.engine"], "vllm")
        self.assertEqual(payload.measurement_params["benchmark.run_id"], "run-1")
        self.assertEqual(
            payload.measurement_metrics,
            {
                "latency.ttft_p95_ms": 123.0,
                "throughput.aggregate_output_tps": 45.5,
            },
        )

    def test_rejects_each_profile_run_disagreement(self) -> None:
        cases = (
            ("artifact", "model_id", "other-model", "model id"),
            ("artifact", "revision", "other-revision", "model revision"),
            ("artifact", "quantization", "FP8", "quantization"),
            ("serving", "engine", "SGLang", "serving engine"),
            ("serving", "version", "9.9", "serving version"),
            ("serving", "profile", "other-profile", "serving profile"),
        )
        for section, key, value, message in cases:
            with self.subTest(section=section, key=key):
                original = self.run[section][key]
                self.run[section][key] = value
                self._write_inputs()
                with self.assertRaisesRegex(ValueError, message):
                    self._load()
                self.run[section][key] = original

    def test_rejects_missing_result_digest(self) -> None:
        self.run["provenance"] = {"source_record_sha256": "b" * 64}
        self._write_inputs()

        with self.assertRaisesRegex(ValueError, "result_sha256"):
            self._load()

    def test_rejects_duplicate_run_id(self) -> None:
        (self.root / "runs.json").write_text(
            json.dumps({"runs": [self.run, self.run]}), encoding="utf-8"
        )

        with self.assertRaisesRegex(ValueError, "exactly one run"):
            self._load()

    def test_rejects_path_escape(self) -> None:
        with self.assertRaisesRegex(ValueError, "escapes repository root"):
            registry.load_publication_inputs(
                self.root, "../profile.json", "runs.json", "run-1"
            )

    def test_rejects_non_object_json(self) -> None:
        (self.root / "profile.json").write_text("[]", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "profile must be a JSON object"):
            self._load()

    def test_rejects_non_finite_metric(self) -> None:
        self.run["metrics"]["ttft_p95_ms"] = math.inf
        self._write_inputs()

        with self.assertRaisesRegex(ValueError, "ttft_p95_ms is not finite"):
            self._load()


class _StoredRunFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.profile_path = "profiles/example.json"
        profile_file = self.root / self.profile_path
        profile_file.parent.mkdir(parents=True)
        profile_file.write_bytes(b'{"reviewed":true}\n')
        self.profile_digest = hashlib.sha256(profile_file.read_bytes()).hexdigest()
        self.recipe = registry.StoredRun(
            run_id="recipe-run",
            status="FINISHED",
            params={
                "recipe.profile_path": self.profile_path,
                "recipe.profile_sha256": self.profile_digest,
                "model.id": "publisher/model",
                "model.revision": "revision-1",
                "model.quantization": "NVFP4",
                "serving.engine": "vllm",
                "serving.version": "1.2.3",
            },
            tags={
                "registry.role": "serving-recipe",
                "recipe.id": f"sha256:{self.profile_digest}",
            },
            metrics={},
        )
        self.measurement = registry.StoredRun(
            run_id="measurement-run",
            status="FINISHED",
            params={
                "benchmark.run_id": "benchmark-run",
                "evidence.result_sha256": "b" * 64,
                "model.id": "publisher/model",
                "model.revision": "revision-1",
                "model.quantization": "NVFP4",
                "serving.engine": "vllm",
                "serving.version": "1.2.3",
            },
            tags={
                "registry.role": "measurement",
                "measurement.id": f"sha256:{'c' * 64}",
                "recipe.id": f"sha256:{self.profile_digest}",
                "recipe.parent_run_id": "recipe-run",
            },
            metrics={"latency.ttft_p95_ms": 123.0},
        )

    def _replace(
        self, run: registry.StoredRun, *, status: str | None = None,
        params: Mapping[str, str] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> registry.StoredRun:
        return registry.StoredRun(
            run_id=run.run_id,
            status=status if status is not None else run.status,
            params=params if params is not None else run.params,
            tags=tags if tags is not None else run.tags,
            metrics=run.metrics,
        )


class RelationshipTests(_StoredRunFixture):

    def test_classifies_exact_link(self) -> None:
        result = registry.classify_relationship(
            self.recipe, self.measurement, self.root
        )

        self.assertEqual(result.status, "linked")
        self.assertEqual(result.profile_state, "exact")
        self.assertEqual(result.recipe_id, self.recipe.tags["recipe.id"])

    def test_preserves_historical_digest_on_profile_drift(self) -> None:
        (self.root / self.profile_path).write_text("changed", encoding="utf-8")

        result = registry.classify_relationship(
            self.recipe, self.measurement, self.root
        )

        self.assertEqual(result.status, "historical-profile-drift")
        self.assertEqual(result.profile_state, "historical-drift")
        self.assertEqual(result.recipe_id, self.recipe.tags["recipe.id"])

    def test_classifies_missing_profile_without_rewriting_identity(self) -> None:
        (self.root / self.profile_path).unlink()

        result = registry.classify_relationship(
            self.recipe, self.measurement, self.root
        )

        self.assertEqual(result.status, "profile-unavailable")
        self.assertEqual(result.profile_state, "unavailable")
        self.assertEqual(result.recipe_id, self.recipe.tags["recipe.id"])

    def test_rejects_unlinked_measurement(self) -> None:
        tags = dict(self.measurement.tags)
        tags.pop("recipe.parent_run_id")

        result = registry.classify_relationship(
            self.recipe, self._replace(self.measurement, tags=tags), self.root
        )

        self.assertEqual(result.status, "unlinked-measurement")
        self.assertFalse(result.exportable)

    def test_rejects_conflicting_identity_model_or_engine(self) -> None:
        cases = (
            ("tag", "recipe.id", "sha256:other"),
            ("param", "model.id", "other-model"),
            ("param", "serving.engine", "sglang"),
        )
        for location, key, value in cases:
            with self.subTest(location=location, key=key):
                params = dict(self.measurement.params)
                tags = dict(self.measurement.tags)
                (tags if location == "tag" else params)[key] = value
                result = registry.classify_relationship(
                    self.recipe,
                    self._replace(self.measurement, params=params, tags=tags),
                    self.root,
                )
                self.assertEqual(result.status, "conflict")
                self.assertFalse(result.exportable)

    def test_rejects_non_finished_pair(self) -> None:
        result = registry.classify_relationship(
            self.recipe,
            self._replace(self.measurement, status="RUNNING"),
            self.root,
        )

        self.assertEqual(result.status, "non-finished")
        self.assertFalse(result.exportable)

    def test_accepts_standard_mlflow_parent_tag(self) -> None:
        tags = dict(self.measurement.tags)
        tags["mlflow.parentRunId"] = tags.pop("recipe.parent_run_id")

        result = registry.classify_relationship(
            self.recipe, self._replace(self.measurement, tags=tags), self.root
        )

        self.assertEqual(result.status, "linked")


class HandoffTests(_StoredRunFixture):
    def test_builds_sanitized_handoff_from_stored_values(self) -> None:
        relationship = registry.classify_relationship(
            self.recipe, self.measurement, self.root
        )

        handoff = registry.build_handoff(
            "dgx-spark-llm-inference",
            self.recipe,
            self.measurement,
            relationship.profile_state,
        )

        registry.validate_handoff(handoff)
        self.assertEqual(handoff["schema_version"], "serving-benchmark-handoff/v1")
        self.assertEqual(handoff["recipe"]["profile_state"], "exact")
        self.assertEqual(handoff["model"]["id"], "publisher/model")
        serialized = json.dumps(handoff)
        self.assertNotIn("tracking_uri", serialized)
        self.assertNotIn("artifact_uri", serialized)

    def test_legacy_measurement_fields_use_json_null(self) -> None:
        params = dict(self.measurement.params)
        params.pop("benchmark.run_id")
        params.pop("evidence.result_sha256")
        tags = dict(self.measurement.tags)
        tags.pop("measurement.id")
        legacy = self._replace(self.measurement, params=params, tags=tags)

        handoff = registry.build_handoff(
            "dgx-spark-llm-inference", self.recipe, legacy, "exact"
        )

        registry.validate_handoff(handoff)
        self.assertIsNone(handoff["measurement"]["id"])
        self.assertIsNone(handoff["measurement"]["benchmark_run_id"])
        self.assertIsNone(handoff["measurement"]["result_sha256"])

    def test_validation_rejects_extra_or_private_fields(self) -> None:
        handoff = registry.build_handoff(
            "dgx-spark-llm-inference", self.recipe, self.measurement, "exact"
        )
        handoff["tracking_uri"] = "https://private.invalid"

        with self.assertRaisesRegex(ValueError, "unexpected handoff fields"):
            registry.validate_handoff(handoff)

    def test_schema_matches_contract_version_and_is_closed(self) -> None:
        schema_path = (
            Path(__file__).parents[1] / "serving-benchmark-handoff.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "serving-benchmark-handoff/v1",
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
