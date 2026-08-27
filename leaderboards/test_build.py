from __future__ import annotations

import json
import hashlib
import importlib.util
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from leaderboards.build import DEFAULT_DATA, validate_data


class LeaderboardValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(Path(DEFAULT_DATA).read_text(encoding="utf-8"))

    def test_retained_results_are_valid(self) -> None:
        self.assertEqual([], validate_data(self.data))

    def test_hash_only_provenance_is_accepted(self) -> None:
        data = deepcopy(self.data)
        data["runs"] = [data["runs"][0]]
        data["runs"][0]["provenance"] = {
            "measurement_scope": "local endpoint",
            "source_record_sha256": "a" * 64,
        }
        self.assertEqual([], validate_data(data))

    def test_invalid_provenance_hash_is_rejected(self) -> None:
        data = deepcopy(self.data)
        data["runs"][0]["provenance"] = {
            "measurement_scope": "local endpoint",
            "source_record_sha256": "not-a-sha256",
        }
        self.assertTrue(any("provenance hash" in error for error in validate_data(data)))

    def test_quick_import_keeps_hash_provenance_without_private_paths(self) -> None:
        root = Path(DEFAULT_DATA).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("import_quick", root / "benchmarks/results/import_quick.py")
        importer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(importer)
        descriptor = deepcopy(self.data["runs"][0])
        descriptor["provenance"] = {"measurement_scope": "local endpoint"}
        raw = {
            "schema_version": "openai-compatible-quick/v1",
            "metadata_status": "provided", "run_id": descriptor["id"],
            "started_at": "2026-08-21T00:00:00Z", "passed": True,
            "metadata": {
                "model_artifact": {"id": "example/model", "revision": "test", "quantization": "test"},
                "serving": {
                    "engine": "example", "version": "test", "image": "example/image",
                    "image_digest": None, "command_profile": "test", "options": {},
                    "speculative": {"mode": "off", "draft_model": None, "settings": {}},
                },
            },
            "performance": {
                "streaming_single_user": {
                    "ttft_s": {"p50": 1, "p95": 2}, "tpot_ms": {"p50": 1},
                    "e2e_s": {"p50": 1}, "decode_tps": {"p50": 1},
                },
                "closed_loop": {"aggregate_output_tps": 1, "concurrency": 1, "requests_per_s": 1},
            },
            "resource_snapshot": {"host_memory": {}}, "checks": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "private-result.json"
            result_path.write_text(json.dumps(raw), encoding="utf-8")
            normalized = importer.normalize(result_path, descriptor)
            self.assertEqual({
                "measurement_scope": "local endpoint",
                "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            }, normalized["provenance"])


if __name__ == "__main__":
    unittest.main()
