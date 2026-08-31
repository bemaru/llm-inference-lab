"""Pure contracts for the reviewed MLflow benchmark registry."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


METRIC_KEYS = {
    "ttft_p50_ms": "latency.ttft_p50_ms",
    "ttft_p95_ms": "latency.ttft_p95_ms",
    "tpot_p50_ms": "latency.tpot_p50_ms",
    "e2e_p50_s": "latency.e2e_p50_s",
    "single_user_decode_tps_p50": "throughput.single_user_decode_tps_p50",
    "aggregate_output_tps": "throughput.aggregate_output_tps",
    "concurrency": "requests.concurrent",
    "request_throughput_rps": "throughput.requests_per_s",
    "accelerator_process_memory_mib": "resource.accelerator_process_memory_mib",
    "host_available_memory_gib": "resource.host_available_memory_gib",
}


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


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    status: str
    params: Mapping[str, str]
    tags: Mapping[str, str]
    metrics: Mapping[str, float]


@dataclass(frozen=True)
class RelationshipResult:
    status: str
    profile_state: str | None
    recipe_id: str | None

    @property
    def exportable(self) -> bool:
        return self.status in {
            "linked",
            "historical-profile-drift",
            "profile-unavailable",
        }


def require_sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def recipe_identity(profile_bytes: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(profile_bytes).hexdigest()
    return f"sha256:{digest}", digest


def measurement_identity(
    benchmark_run_id: str, recipe_id: str, result_sha256: str
) -> str:
    payload = {
        "benchmark_run_id": benchmark_run_id,
        "recipe_id": recipe_id,
        "result_sha256": require_sha256(result_sha256, "result_sha256"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _resolve_file(repository_root: Path, relative_path: str, name: str) -> Path:
    root = repository_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{name} path escapes repository root: {relative_path}") from error
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _load_object(path: Path, name: str) -> Mapping[str, Any]:
    return _as_mapping(json.loads(path.read_text(encoding="utf-8")), name)


def _nested(value: Mapping[str, Any], key: str, name: str) -> Mapping[str, Any]:
    return _as_mapping(value.get(key), name)


def _normalized_engine(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("serving engine must be a non-empty string")
    return value.strip().lower()


def _scalar_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return str(value)


def _require_agreement(
    profile_value: Any, run_value: Any, name: str, *, normalize: bool = False
) -> None:
    left = _normalized_engine(profile_value) if normalize else profile_value
    right = _normalized_engine(run_value) if normalize else run_value
    if left != right:
        raise ValueError(f"{name} does not agree between profile and run")


def load_publication_inputs(
    repository_root: Path,
    profile_path: str,
    run_set_path: str,
    run_id: str,
) -> PublicationInputs:
    profile_file = _resolve_file(repository_root, profile_path, "profile")
    run_set_file = _resolve_file(repository_root, run_set_path, "run set")
    profile_bytes = profile_file.read_bytes()
    profile = _as_mapping(json.loads(profile_bytes.decode("utf-8")), "profile")
    run_set = _load_object(run_set_file, "run set")

    runs = run_set.get("runs")
    if not isinstance(runs, list):
        raise ValueError("run set runs must be a JSON array")
    matches = [item for item in runs if isinstance(item, dict) and item.get("id") == run_id]
    if len(matches) != 1:
        raise ValueError(f"run set must contain exactly one run with id {run_id}")
    run = matches[0]

    profile_artifact = _nested(profile, "model_artifact", "profile model_artifact")
    run_artifact = _nested(run, "artifact", "run artifact")
    profile_serving = _nested(profile, "serving", "profile serving")
    run_serving = _nested(run, "serving", "run serving")

    _require_agreement(profile_artifact.get("id"), run_artifact.get("model_id"), "model id")
    _require_agreement(
        profile_artifact.get("revision"), run_artifact.get("revision"), "model revision"
    )
    _require_agreement(
        profile_artifact.get("quantization"),
        run_artifact.get("quantization"),
        "quantization",
    )
    _require_agreement(
        profile_serving.get("engine"),
        run_serving.get("engine"),
        "serving engine",
        normalize=True,
    )
    _require_agreement(
        profile_serving.get("version"), run_serving.get("version"), "serving version"
    )
    _require_agreement(
        profile_serving.get("command_profile"),
        run_serving.get("profile"),
        "serving profile",
    )

    provenance = _nested(run, "provenance", "run provenance")
    result_sha256 = provenance.get("result_sha256")
    if not isinstance(result_sha256, str):
        raise ValueError("run provenance.result_sha256 is required")
    require_sha256(result_sha256, "result_sha256")

    metrics = _nested(run, "metrics", "run metrics")
    for source_key in METRIC_KEYS:
        raw_value = metrics.get(source_key)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"metric {source_key} must be numeric")
        if not math.isfinite(float(raw_value)):
            raise ValueError(f"metric {source_key} is not finite")

    return PublicationInputs(
        profile_path=Path(profile_path).as_posix(),
        profile=profile,
        profile_bytes=profile_bytes,
        run_set_path=Path(run_set_path).as_posix(),
        run=run,
    )


def publication_payload(inputs: PublicationInputs) -> PublicationPayload:
    profile_artifact = _nested(inputs.profile, "model_artifact", "profile model_artifact")
    profile_serving = _nested(inputs.profile, "serving", "profile serving")
    run_metrics = _nested(inputs.run, "metrics", "run metrics")
    provenance = _nested(inputs.run, "provenance", "run provenance")
    run_id = str(inputs.run["id"])
    result_sha256 = require_sha256(
        str(provenance["result_sha256"]), "result_sha256"
    )
    recipe_id, profile_sha256 = recipe_identity(inputs.profile_bytes)
    measurement_id_value = measurement_identity(run_id, recipe_id, result_sha256)

    common_params = {
        "model.id": _scalar_text(profile_artifact.get("id")),
        "model.revision": _scalar_text(profile_artifact.get("revision")),
        "model.quantization": _scalar_text(profile_artifact.get("quantization")),
        "serving.engine": _normalized_engine(profile_serving.get("engine")),
        "serving.version": _scalar_text(profile_serving.get("version")),
    }
    recipe_params = {
        **common_params,
        "recipe.profile_path": inputs.profile_path,
        "recipe.profile_sha256": profile_sha256,
    }
    recipe_tags = {
        "registry.role": "serving-recipe",
        "recipe.id": recipe_id,
        "review.status": "reviewed",
    }
    measurement_params = {
        **common_params,
        "benchmark.run_id": run_id,
        "evidence.result_sha256": result_sha256,
        "recipe.id": recipe_id,
        "measurement.id": measurement_id_value,
    }
    measurement_tags = {
        "registry.role": "measurement",
        "recipe.id": recipe_id,
        "measurement.id": measurement_id_value,
        "review.status": "reviewed",
        "comparison_group": _scalar_text(inputs.run.get("comparison_group")),
    }
    measurement_metrics = {
        destination: float(run_metrics[source])
        for source, destination in METRIC_KEYS.items()
        if run_metrics.get(source) is not None
    }
    return PublicationPayload(
        recipe_id=recipe_id,
        profile_sha256=profile_sha256,
        measurement_id=measurement_id_value,
        recipe_params=recipe_params,
        recipe_tags=recipe_tags,
        measurement_params=measurement_params,
        measurement_tags=measurement_tags,
        measurement_metrics=measurement_metrics,
    )


def stored_value(run: StoredRun, key: str) -> str | None:
    value = run.tags.get(key)
    if value is None:
        value = run.params.get(key)
    if value is None or value == "null":
        return None
    return str(value)


def _relationship_conflicts(recipe: StoredRun, measurement: StoredRun) -> bool:
    recipe_id = stored_value(recipe, "recipe.id")
    measurement_recipe_id = stored_value(measurement, "recipe.id")
    if recipe_id is None or recipe_id != measurement_recipe_id:
        return True
    profile_sha256 = stored_value(recipe, "recipe.profile_sha256")
    try:
        if profile_sha256 is None or require_sha256(
            profile_sha256, "recipe.profile_sha256"
        ) != recipe_id.removeprefix("sha256:"):
            return True
    except ValueError:
        return True
    for key in ("model.id", "serving.engine"):
        recipe_value = stored_value(recipe, key)
        measurement_value = stored_value(measurement, key)
        if recipe_value is None or measurement_value is None:
            return True
        if key == "serving.engine":
            if recipe_value.strip().lower() != measurement_value.strip().lower():
                return True
        elif recipe_value != measurement_value:
            return True
    return False


def classify_relationship(
    recipe: StoredRun, measurement: StoredRun, repository_root: Path
) -> RelationshipResult:
    recipe_id = stored_value(recipe, "recipe.id")
    if recipe.status != "FINISHED" or measurement.status != "FINISHED":
        return RelationshipResult("non-finished", None, recipe_id)
    if stored_value(recipe, "registry.role") != "serving-recipe":
        return RelationshipResult("conflict", None, recipe_id)
    if stored_value(measurement, "registry.role") != "measurement":
        return RelationshipResult("conflict", None, recipe_id)

    parent_run_id = stored_value(measurement, "recipe.parent_run_id")
    if parent_run_id is None:
        parent_run_id = stored_value(measurement, "mlflow.parentRunId")
    if parent_run_id is None:
        return RelationshipResult("unlinked-measurement", None, recipe_id)
    if parent_run_id != recipe.run_id or _relationship_conflicts(recipe, measurement):
        return RelationshipResult("conflict", None, recipe_id)

    profile_path = stored_value(recipe, "recipe.profile_path")
    profile_sha256 = stored_value(recipe, "recipe.profile_sha256")
    if profile_path is None or profile_sha256 is None:
        return RelationshipResult("conflict", None, recipe_id)
    try:
        profile_file = _resolve_file(repository_root, profile_path, "stored profile")
    except (FileNotFoundError, ValueError):
        return RelationshipResult("profile-unavailable", "unavailable", recipe_id)
    current_digest = hashlib.sha256(profile_file.read_bytes()).hexdigest()
    if current_digest != profile_sha256:
        return RelationshipResult(
            "historical-profile-drift", "historical-drift", recipe_id
        )
    return RelationshipResult("linked", "exact", recipe_id)


def _nullable_stored_value(run: StoredRun, key: str) -> str | None:
    return stored_value(run, key)


def build_handoff(
    experiment: str,
    recipe: StoredRun,
    measurement: StoredRun,
    profile_state: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "serving-benchmark-handoff/v1",
        "experiment": experiment,
        "recipe": {
            "id": _nullable_stored_value(recipe, "recipe.id"),
            "run_id": recipe.run_id,
            "profile_path": _nullable_stored_value(recipe, "recipe.profile_path"),
            "profile_sha256": _nullable_stored_value(
                recipe, "recipe.profile_sha256"
            ),
            "profile_state": profile_state,
        },
        "measurement": {
            "id": _nullable_stored_value(measurement, "measurement.id"),
            "run_id": measurement.run_id,
            "benchmark_run_id": _nullable_stored_value(
                measurement, "benchmark.run_id"
            ),
            "result_sha256": _nullable_stored_value(
                measurement, "evidence.result_sha256"
            ),
        },
        "model": {
            "id": _nullable_stored_value(recipe, "model.id"),
            "revision": _nullable_stored_value(recipe, "model.revision"),
            "quantization": _nullable_stored_value(recipe, "model.quantization"),
        },
        "serving": {
            "engine": _nullable_stored_value(recipe, "serving.engine"),
            "version": _nullable_stored_value(recipe, "serving.version"),
        },
    }


def _require_exact_fields(
    value: Mapping[str, Any], required: set[str], name: str
) -> None:
    actual = set(value)
    if actual != required:
        unexpected = sorted(actual - required)
        missing = sorted(required - actual)
        raise ValueError(
            f"unexpected {name} fields; missing={missing}, unexpected={unexpected}"
        )


def _require_non_empty_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_text(value, name)


def _require_identity(value: Any, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    text = _require_non_empty_text(value, name)
    if not text.startswith("sha256:"):
        raise ValueError(f"{name} must use sha256 identity")
    require_sha256(text.removeprefix("sha256:"), name)


def validate_handoff(value: Mapping[str, Any]) -> None:
    handoff = _as_mapping(value, "handoff")
    _require_exact_fields(
        handoff,
        {"schema_version", "experiment", "recipe", "measurement", "model", "serving"},
        "handoff",
    )
    if handoff["schema_version"] != "serving-benchmark-handoff/v1":
        raise ValueError("unsupported handoff schema_version")
    _require_non_empty_text(handoff["experiment"], "experiment")

    recipe = _as_mapping(handoff["recipe"], "recipe")
    _require_exact_fields(
        recipe,
        {"id", "run_id", "profile_path", "profile_sha256", "profile_state"},
        "recipe",
    )
    _require_identity(recipe["id"], "recipe.id")
    _require_non_empty_text(recipe["run_id"], "recipe.run_id")
    profile_path = _require_optional_text(recipe["profile_path"], "recipe.profile_path")
    if profile_path is not None:
        candidate = Path(profile_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("recipe.profile_path must be repository-relative")
    profile_sha256 = _require_non_empty_text(
        recipe["profile_sha256"], "recipe.profile_sha256"
    )
    require_sha256(profile_sha256, "recipe.profile_sha256")
    if recipe["profile_state"] not in {"exact", "historical-drift", "unavailable"}:
        raise ValueError("invalid recipe.profile_state")

    measurement = _as_mapping(handoff["measurement"], "measurement")
    _require_exact_fields(
        measurement,
        {"id", "run_id", "benchmark_run_id", "result_sha256"},
        "measurement",
    )
    _require_identity(measurement["id"], "measurement.id", nullable=True)
    _require_non_empty_text(measurement["run_id"], "measurement.run_id")
    _require_optional_text(measurement["benchmark_run_id"], "measurement.benchmark_run_id")
    result_sha256 = _require_optional_text(
        measurement["result_sha256"], "measurement.result_sha256"
    )
    if result_sha256 is not None:
        require_sha256(result_sha256, "measurement.result_sha256")

    model = _as_mapping(handoff["model"], "model")
    _require_exact_fields(model, {"id", "revision", "quantization"}, "model")
    _require_non_empty_text(model["id"], "model.id")
    _require_optional_text(model["revision"], "model.revision")
    _require_optional_text(model["quantization"], "model.quantization")

    serving = _as_mapping(handoff["serving"], "serving")
    _require_exact_fields(serving, {"engine", "version"}, "serving")
    _require_non_empty_text(serving["engine"], "serving.engine")
    _require_optional_text(serving["version"], "serving.version")
