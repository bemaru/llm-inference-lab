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
