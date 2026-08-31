# MLflow Benchmark Registry Synchronizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a testable, idempotent MLflow registry synchronizer that audits recipe/measurement links, exports a sanitized handoff, and publishes reviewed benchmark pairs only with explicit `--apply`.

**Architecture:** A pure Python contract module validates public profile and run-set inputs, computes stable identities, maps reviewed fields, classifies stored relationships, and emits the handoff contract without importing MLflow. A thin CLI adapter translates MLflow entities into the pure contract, keeps `audit` and `export` read-only, and keeps `publish` disconnected from MLflow unless `--apply` is present.

**Tech Stack:** Python 3.10+, standard library, `unittest`, `mlflow-skinny==3.13.0` only in the CLI process

**Spec:** `docs/superpowers/specs/2026-08-30-mlflow-benchmark-handoff-design.md`

## Global Constraints

- Existing MLflow runs are never rewritten, normalized, merged, or deleted.
- Future recipe IDs hash exact profile bytes; historical stored IDs and hashes remain unchanged.
- Future measurement IDs hash canonical JSON of benchmark run ID, recipe ID, and `provenance.result_sha256`.
- `audit` and `export` are read-only; `publish` is disconnected dry-run unless `--apply` is supplied.
- Output excludes credentials, URLs, private paths, raw prompts/responses, traces, item scores, and product-evaluation data.
- Every output path resolves beneath the repository root; generated handoffs remain ignored under `artifacts/handoffs/`.
- The first phase does not write to EDR1.

---

### Task 1: Deterministic identities and reviewed input validation

**Files:**
- Create: `tracking/mlflow/benchmark_registry.py`
- Create: `tracking/mlflow/tests/test_benchmark_registry.py`

**Interfaces:**
- Produces: `load_publication_inputs(repository_root: Path, profile_path: str, run_set_path: str, run_id: str) -> PublicationInputs`
- Produces: `recipe_identity(profile_bytes: bytes) -> tuple[str, str]`
- Produces: `measurement_identity(benchmark_run_id: str, recipe_id: str, result_sha256: str) -> str`
- Produces: `publication_payload(inputs: PublicationInputs) -> PublicationPayload`

- [x] **Step 1: Write failing identity tests**

```python
def test_recipe_identity_hashes_exact_bytes(self):
    identity, digest = registry.recipe_identity(b'{"a":1}\n')
    self.assertEqual(identity, f"sha256:{digest}")
    self.assertEqual(digest, hashlib.sha256(b'{"a":1}\n').hexdigest())

def test_measurement_identity_uses_canonical_json(self):
    value = registry.measurement_identity("run-1", "sha256:abc", "f" * 64)
    expected = hashlib.sha256(
        b'{"benchmark_run_id":"run-1","recipe_id":"sha256:abc","result_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}'
    ).hexdigest()
    self.assertEqual(value, f"sha256:{expected}")
```

- [x] **Step 2: Run tests and verify the module-missing failure**

Run: `python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v`

Expected: FAIL because `tracking.mlflow.benchmark_registry` does not exist.

- [x] **Step 3: Implement exact-byte and canonical identities**

```python
def recipe_identity(profile_bytes: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(profile_bytes).hexdigest()
    return f"sha256:{digest}", digest

def measurement_identity(benchmark_run_id: str, recipe_id: str, result_sha256: str) -> str:
    payload = {
        "benchmark_run_id": benchmark_run_id,
        "recipe_id": recipe_id,
        "result_sha256": require_sha256(result_sha256, "result_sha256"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
```

- [x] **Step 4: Write failing input-agreement tests**

Tests create temporary profile and run-set JSON and assert rejection when model ID, revision, quantization, engine, version, or profile reference differs; they also assert rejection of missing `provenance.result_sha256`, duplicate run IDs, path escape, non-object JSON, and non-finite metrics.

- [x] **Step 5: Run the new tests and verify validation failures**

Run: `python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v`

Expected: FAIL because `load_publication_inputs` and `publication_payload` are absent.

- [x] **Step 6: Implement immutable dataclasses and validation**

```python
@dataclass(frozen=True)
class PublicationInputs:
    profile_path: str
    profile: Mapping[str, Any]
    profile_bytes: bytes
    run_set_path: str
    run: Mapping[str, Any]

@dataclass(frozen=True)
class PublicationPayload:
    recipe_id: str
    profile_sha256: str
    measurement_id: str
    recipe_params: Mapping[str, str]
    recipe_tags: Mapping[str, str]
    measurement_params: Mapping[str, str]
    measurement_tags: Mapping[str, str]
    measurement_metrics: Mapping[str, float]
```

The loader resolves both paths beneath `repository_root`, requires JSON objects, selects exactly one run ID, compares profile `model_artifact` and `serving` fields with run `artifact` and `serving`, and maps only finite, non-null metrics.

- [x] **Step 7: Run Task 1 tests until green**

Run: `python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v`

Expected: all Task 1 tests PASS.

- [x] **Step 8: Commit Task 1**

```bash
git add tracking/mlflow/benchmark_registry.py tracking/mlflow/tests/test_benchmark_registry.py
git commit -m "feat: add benchmark registry contract"
```

### Task 2: Stored relationship classification and handoff schema

**Files:**
- Modify: `tracking/mlflow/benchmark_registry.py`
- Modify: `tracking/mlflow/tests/test_benchmark_registry.py`
- Create: `tracking/mlflow/serving-benchmark-handoff.schema.json`

**Interfaces:**
- Consumes: `PublicationPayload`
- Produces: `StoredRun`, `RelationshipResult`, `classify_relationship(...) -> RelationshipResult`
- Produces: `build_handoff(experiment: str, recipe: StoredRun, measurement: StoredRun, profile_state: str) -> dict[str, Any]`
- Produces: `validate_handoff(value: Mapping[str, Any]) -> None`

- [x] **Step 1: Write failing relationship tests**

```python
def test_relationship_preserves_historical_digest_on_profile_drift(self):
    result = registry.classify_relationship(recipe, measurement, root)
    self.assertEqual(result.status, "historical-profile-drift")
    self.assertEqual(result.profile_state, "historical-drift")
    self.assertEqual(result.recipe_id, recipe.tags["recipe.id"])
```

Add cases for `linked`, `profile-unavailable`, `unlinked-measurement`, `conflict`, duplicate recipe IDs, and `non-finished`.

- [x] **Step 2: Run the relationship tests and verify missing-interface failure**

Run: `python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v`

Expected: FAIL because stored-run classification is absent.

- [x] **Step 3: Implement fail-closed relationship classification**

`StoredRun` contains `run_id`, `status`, `params`, `tags`, and `metrics`. Field access reads exact future keys while accepting `mlflow.parentRunId` as the parent-link alias. Exportable statuses are exactly `linked`, `historical-profile-drift`, and `profile-unavailable`.

- [x] **Step 4: Add the handoff JSON Schema and failing contract tests**

The schema requires `schema_version` with the exact value `serving-benchmark-handoff/v1`, plus `experiment`, `recipe`, `measurement`, `model`, and `serving`; it disallows additional properties, permits JSON null for legacy revision/quantization/version values, and constrains identity/hash formats.

- [x] **Step 5: Run tests and verify missing handoff builder failure**

Run: `python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v`

Expected: FAIL because `build_handoff` and `validate_handoff` are absent.

- [x] **Step 6: Implement and validate sanitized handoff output**

The builder copies only stored recipe and measurement identities plus model/serving values. It never copies MLflow tracking URI, artifact URI, endpoint, hostname, local absolute path, or arbitrary tags.

- [x] **Step 7: Run Task 2 tests until green**

Run: `python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v`

Expected: all Task 1 and Task 2 tests PASS.

- [x] **Step 8: Commit Task 2**

```bash
git add tracking/mlflow/benchmark_registry.py tracking/mlflow/serving-benchmark-handoff.schema.json tracking/mlflow/tests/test_benchmark_registry.py
git commit -m "feat: add benchmark handoff contract"
```

### Task 3: MLflow adapter and explicit CLI workflow

**Files:**
- Create: `tracking/mlflow/scripts/sync_benchmark.py`
- Create: `tracking/mlflow/tests/test_sync_benchmark.py`

**Interfaces:**
- Consumes: pure registry contract from Tasks 1 and 2
- Produces: `RegistryStore` protocol with `list_runs`, `find_by_identity`, `create_recipe`, `create_measurement`, `read_run`, and `mark_failed`
- Produces: CLI subcommands `audit`, `export`, and `publish`

- [x] **Step 1: Write a fake store and failing dry-run test**

```python
def test_publish_dry_run_never_constructs_store(self):
    result = cli.publish_command(args, store_factory=lambda: self.fail("store contacted"))
    self.assertEqual(result["mode"], "dry-run")
    self.assertIn("handoff_preview", result)
```

- [x] **Step 2: Run the CLI tests and verify script-missing failure**

Run: `python3 -m unittest tracking.mlflow.tests.test_sync_benchmark -v`

Expected: FAIL because `sync_benchmark.py` does not exist.

- [x] **Step 3: Implement argparse and disconnected dry-run publication**

The script adds a PEP 723 dependency block for `mlflow-skinny==3.13.0`, injects the repository root into `sys.path`, and imports MLflow only inside `MlflowStore`. `publish` loads and validates local inputs before deciding whether `--apply` permits store construction.

- [x] **Step 4: Write failing audit/export and idempotency tests**

Tests assert that audit never creates runs, export rejects non-exportable relationships, apply reuses one exact FINISHED identity, duplicate/conflicting identities fail, a missing pair is created with parent linkage, read-back mismatch fails closed, and a newly created run is marked FAILED when publication raises.

- [x] **Step 5: Run tests and verify adapter behavior is absent**

Run: `python3 -m unittest tracking.mlflow.tests.test_sync_benchmark -v`

Expected: FAIL on unimplemented store workflows.

- [x] **Step 6: Implement the store workflows and MLflow translation**

`MlflowStore` searches the configured experiment without creating it for `audit` or `export`. Apply mode creates the experiment only when publication requires it, writes exact params/tags/metrics, sets `mlflow.parentRunId` and `recipe.parent_run_id`, uploads the reviewed profile beneath `evidence`, terminates new runs, and reads them back before building a consumable handoff.

- [x] **Step 7: Add repository-contained output resolution**

Standard output is the default. `--output` resolves under the repository root, rejects escapes and directories, creates only the selected parent directory, and writes UTF-8 JSON with sorted keys and a final newline.

- [x] **Step 8: Run Task 3 tests until green**

Run: `python3 -m unittest tracking.mlflow.tests.test_sync_benchmark -v`

Expected: all CLI tests PASS without contacting MLflow.

- [x] **Step 9: Commit Task 3**

```bash
git add tracking/mlflow/scripts/sync_benchmark.py tracking/mlflow/tests/test_sync_benchmark.py
git commit -m "feat: add MLflow benchmark synchronizer"
```

### Task 4: Documentation, dry-run evidence, and full regression

**Files:**
- Modify: `tracking/mlflow/README.md`
- Modify: `benchmarks/results/README.md`

**Interfaces:**
- Documents: generic importer versus registry synchronizer, dry-run/apply boundary, handoff consumer boundary, and local-only output location

- [x] **Step 1: Document the exact commands**

```bash
uv run --locked --script tracking/mlflow/scripts/sync_benchmark.py publish \
  --profile benchmarks/openai-compatible/profiles/gemma4-26b-a4b-nvfp4-vllm-dspark.json \
  --run-set benchmarks/results/dgx-spark.json \
  --run-id 20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02
```

Document that adding `--apply` contacts and may mutate MLflow, while `audit` and `export` contact MLflow read-only.

- [x] **Step 2: Run the disconnected dry-run**

Run the command above without `MLFLOW_TRACKING_URI` and without `--apply`.

Expected: valid proposed identities and handoff preview; no network or MLflow import requirement.

- [x] **Step 3: Run all MLflow and repository checks**

```bash
python3 -m unittest tracking.mlflow.tests.test_benchmark_registry -v
python3 -m unittest tracking.mlflow.tests.test_sync_benchmark -v
python3 -m unittest discover -s benchmarks/openai-compatible/tests -p 'test_*.py'
python3 -m unittest discover -s leaderboards -p 'test_*.py'
bash tracking/mlflow/tests/local_client_test.sh
python3 leaderboards/build.py --check
```

Expected: every command exits zero and the generated leaderboard remains current.

- [x] **Step 4: Review disclosure and scope**

Run `git diff --check` and scan changed files for credentials, internal endpoints, private host/user paths, raw prompts/responses, and product-specific evaluation data. Confirm generated handoffs remain outside Git.

- [x] **Step 5: Commit documentation**

```bash
git add tracking/mlflow/README.md benchmarks/results/README.md docs/superpowers/plans/2026-08-31-mlflow-benchmark-sync.md
git commit -m "docs: explain benchmark registry workflow"
```
