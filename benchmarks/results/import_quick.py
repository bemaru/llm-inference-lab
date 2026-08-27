#!/usr/bin/env python3
"""Normalize one canonical Quick result into a repository run set."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "benchmarks" / "results" / "dgx-spark.json"


def require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def count_checks(checks: dict[str, Any], prefix: str) -> dict[str, int]:
    matching = [value for key, value in checks.items() if key == prefix or key.startswith(f"{prefix}_")]
    return {
        "passed": sum(1 for value in matching if value.get("passed") is True),
        "attempts": len(matching),
    }


def normalize(result_path: Path, descriptor: dict[str, Any]) -> dict[str, Any]:
    raw_bytes = result_path.read_bytes()
    result = require_object(json.loads(raw_bytes), "result")
    if result.get("schema_version") != "openai-compatible-quick/v1":
        raise ValueError("unsupported result schema_version")
    if result.get("metadata_status") != "provided":
        raise ValueError("a normalized run requires provided metadata")
    if descriptor.get("id") != result.get("run_id"):
        raise ValueError("descriptor id must match result run_id")

    metadata = require_object(result.get("metadata"), "result.metadata")
    model_artifact = require_object(metadata.get("model_artifact"), "metadata.model_artifact")
    serving = require_object(metadata.get("serving"), "metadata.serving")
    speculative = require_object(serving.get("speculative"), "metadata.serving.speculative")
    settings = require_object(speculative.get("settings"), "metadata.serving.speculative.settings")
    performance = require_object(result.get("performance"), "result.performance")
    streaming = require_object(performance.get("streaming_single_user"), "performance.streaming_single_user")
    closed_loop = require_object(performance.get("closed_loop"), "performance.closed_loop")
    snapshot = require_object(result.get("resource_snapshot"), "result.resource_snapshot")
    host_memory = require_object(snapshot.get("host_memory"), "resource_snapshot.host_memory")
    checks = require_object(result.get("checks"), "result.checks")

    if "error" in streaming or "error" in closed_loop:
        raise ValueError("performance sections with errors cannot be normalized")
    if descriptor.get("status") == "pass" and result.get("passed") is not True:
        raise ValueError("a failed source result cannot be normalized with pass status")

    process_memory = sum(
        float(item["used_memory_mib"])
        for item in snapshot.get("accelerator_processes", [])
        if item.get("used_memory_mib") is not None
    )
    available_bytes = host_memory.get("available_bytes")
    host_available_gib = None if available_bytes is None else round(available_bytes / (1024**3), 3)
    source_hash = hashlib.sha256(raw_bytes).hexdigest()

    presentation = require_object(descriptor.get("model"), "descriptor.model")
    artifact_policy = require_object(descriptor.get("artifact"), "descriptor.artifact")
    provenance = require_object(descriptor.get("provenance"), "descriptor.provenance")
    stream_ttft = require_object(streaming.get("ttft_s"), "streaming.ttft_s")
    stream_tpot = require_object(streaming.get("tpot_ms"), "streaming.tpot_ms")
    stream_e2e = require_object(streaming.get("e2e_s"), "streaming.e2e_s")
    stream_decode = require_object(streaming.get("decode_tps"), "streaming.decode_tps")

    return {
        "id": result["run_id"],
        "observed_on": result["started_at"][:10],
        "comparison_group": descriptor["comparison_group"],
        "status": descriptor["status"],
        "promotion": descriptor["promotion"],
        "eligible_for_ranking": bool(descriptor["eligible_for_ranking"]),
        "model": presentation,
        "artifact": {
            "publisher": artifact_policy["publisher"],
            "model_id": model_artifact["id"],
            "revision": model_artifact["revision"],
            "quantization": model_artifact["quantization"],
            "license": artifact_policy["license"],
            "commercial_use": artifact_policy["commercial_use"],
        },
        "serving": {
            "engine": serving["engine"],
            "version": serving["version"],
            "image": serving["image"],
            "image_digest": serving["image_digest"],
            "profile": serving["command_profile"],
            "options": serving["options"],
            "speculative": {
                "mode": speculative["mode"],
                "draft_model": speculative["draft_model"],
                "num_tokens": settings.get("num_draft_tokens"),
                "acceptance_pct": None,
            },
        },
        "validation": {
            "api": "pass" if checks.get("models", {}).get("passed") else "fail",
            "chat": "pass" if checks.get("chat", {}).get("passed") else "fail",
            "tool_simple": count_checks(checks, "tool_simple"),
            "tool_nested": count_checks(checks, "tool_nested"),
            "tool_large_surface": count_checks(checks, "tool_large_surface"),
            "answer_quality": descriptor.get("answer_quality", "not_run"),
        },
        "metrics": {
            "ttft_p50_ms": round(stream_ttft["p50"] * 1000, 3),
            "ttft_p95_ms": round(stream_ttft["p95"] * 1000, 3),
            "tpot_p50_ms": stream_tpot["p50"],
            "e2e_p50_s": stream_e2e["p50"],
            "single_user_decode_tps_p50": stream_decode["p50"],
            "aggregate_output_tps": closed_loop["aggregate_output_tps"],
            "concurrency": closed_loop["concurrency"],
            "request_throughput_rps": closed_loop["requests_per_s"],
            "accelerator_process_memory_mib": round(process_memory, 3),
            "host_available_memory_gib": host_available_gib,
        },
        "notes": descriptor["notes"],
        "provenance": {
            "measurement_scope": provenance["measurement_scope"],
            "result_sha256": source_hash,
        },
    }


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as temporary:
        temporary.write(serialized)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    descriptor = json.loads(args.record.read_text(encoding="utf-8"))
    entry = normalize(args.result, descriptor)
    if args.dry_run:
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    data = json.loads(args.data.read_text(encoding="utf-8"))
    if entry["comparison_group"] not in data["comparison_groups"]:
        raise ValueError(f"unknown comparison group: {entry['comparison_group']}")
    data["runs"] = [run for run in data["runs"] if run["id"] != entry["id"]]
    data["runs"].append(entry)
    data["observed_through"] = max(data["observed_through"], entry["observed_on"])
    write_json_atomic(args.data, data)
    print(f"Upserted {entry['id']} into {args.data.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
