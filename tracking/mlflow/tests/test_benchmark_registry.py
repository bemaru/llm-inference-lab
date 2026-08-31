from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tempfile
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


if __name__ == "__main__":
    unittest.main()
