#!/usr/bin/env python3
"""Sustained, fixed-concurrency characterization of an OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from quick_check import (
    capture_resource_snapshot,
    default_run_id,
    load_metadata,
    utc_now,
    validate_run_id,
    write_json_atomic,
)


SCHEMA_VERSION = "openai-compatible-characterization/v1"
BENCHMARK_VERSION = "1.0"
DEFAULT_POINTS = (1, 2, 4, 8, 16, 24, 32)
DEFAULT_DURATION_S = 600.0
DEFAULT_REPETITIONS = 3
T_CRITICAL_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 6) if values else None,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "min": round(min(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
    }


def mean_ci95(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "lower": None, "upper": None, "method": "student-t"}
    mean = statistics.fmean(values)
    if len(values) == 1:
        lower = upper = mean
    else:
        critical = T_CRITICAL_95.get(len(values) - 1, 1.96)
        margin = critical * statistics.stdev(values) / math.sqrt(len(values))
        lower, upper = mean - margin, mean + margin
    return {
        "count": len(values),
        "mean": round(mean, 6),
        "lower": round(lower, 6),
        "upper": round(upper, 6),
        "method": "student-t",
    }


def parse_points(value: str) -> tuple[int, ...]:
    try:
        points = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("concurrency points must be comma-separated integers") from exc
    if not points or any(point < 1 for point in points) or len(set(points)) != len(points):
        raise argparse.ArgumentTypeError("concurrency points must be unique positive integers")
    return points


def load_workload(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("schema_version") != "openai-compatible-workload/v1":
        raise ValueError("unsupported workload schema_version")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("workload.cases must be a non-empty array")
    case_ids: set[str] = set()
    expanded: list[dict[str, Any]] = []
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("every workload case needs a unique non-empty id")
        case_ids.add(case_id)
        prompt = case.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"workload case {case_id!r} needs a non-empty prompt")
        padding = case.get("padding")
        if padding is not None:
            text = padding.get("text")
            repetitions = padding.get("repetitions")
            if not isinstance(text, str) or not text or not isinstance(repetitions, int) or repetitions < 1:
                raise ValueError(f"workload case {case_id!r} has invalid padding")
            prompt = (text * repetitions) + "\n\n" + prompt
        max_tokens = case.get("max_tokens")
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError(f"workload case {case_id!r} needs positive max_tokens")
        expanded.append(
            {
                "id": case_id,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": float(case.get("temperature", 0)),
            }
        )
    manifest = {key: value for key, value in document.items() if key != "cases"}
    manifest["case_count"] = len(expanded)
    return manifest, expanded, hashlib.sha256(raw).hexdigest()


class StreamClient:
    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        first_content_at: float | None = None
        content_chars = 0
        usage: dict[str, Any] | None = None
        finish_reason: str | None = None
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        if first_content_at is None:
                            first_content_at = time.perf_counter()
                        content_chars += len(content)
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
        ended = time.perf_counter()
        if first_content_at is None:
            raise ValueError("stream returned no content")
        if usage is None:
            raise ValueError("stream did not return usage; include_usage is required")
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int) or output_tokens < 1:
            raise ValueError("stream returned invalid prompt/completion token usage")
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = details.get("reasoning_tokens", 0)
        if not isinstance(reasoning_tokens, int):
            reasoning_tokens = 0
        e2e_s = ended - started
        ttft_s = first_content_at - started
        decode_s = max(ended - first_content_at, 0.0)
        token_intervals = max(output_tokens - 1, 0)
        return {
            "e2e_s": round(e2e_s, 6),
            "ttft_s": round(ttft_s, 6),
            "tpot_ms": round(1000 * decode_s / token_intervals, 6) if token_intervals else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "finish_reason": finish_reason,
            "content_chars": content_chars,
        }


def make_payload(
    model: str,
    case: dict[str, Any],
    reasoning_effort: str | None,
    include_chat_template_kwargs: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": case["prompt"]}],
        "temperature": case["temperature"],
        "max_tokens": case["max_tokens"],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if include_chat_template_kwargs:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def summarize_point(records: list[dict[str, Any]], concurrency: int, wall_time_s: float) -> dict[str, Any]:
    successes = [record for record in records if record["status"] == "success"]
    total_output_tokens = sum(record["output_tokens"] for record in successes)
    finish_reasons: dict[str, int] = {}
    errors: dict[str, int] = {}
    for record in successes:
        reason = record["finish_reason"] or "null"
        finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
    for record in records:
        if record["status"] == "error":
            error_type = record["error_type"]
            errors[error_type] = errors.get(error_type, 0) + 1
    system_tps = total_output_tokens / wall_time_s if wall_time_s else 0.0
    return {
        "request_count": len(records),
        "success_count": len(successes),
        "error_count": len(records) - len(successes),
        "success_rate": round(len(successes) / len(records), 6) if records else 0.0,
        "total_input_tokens": sum(record["input_tokens"] for record in successes),
        "total_output_tokens": total_output_tokens,
        "total_reasoning_tokens": sum(record["reasoning_tokens"] for record in successes),
        "system_output_tps": round(system_tps, 6),
        "output_tps_per_user": round(system_tps / concurrency, 6),
        "requests_per_s": round(len(successes) / wall_time_s, 6) if wall_time_s else 0.0,
        "ttft_s": distribution([record["ttft_s"] for record in successes]),
        "e2e_s": distribution([record["e2e_s"] for record in successes]),
        "tpot_ms": distribution([record["tpot_ms"] for record in successes if record["tpot_ms"] is not None]),
        "input_tokens": distribution([float(record["input_tokens"]) for record in successes]),
        "output_tokens": distribution([float(record["output_tokens"]) for record in successes]),
        "finish_reasons": finish_reasons,
        "errors": errors,
    }


def run_point(
    *,
    client: StreamClient,
    model: str,
    cases: list[dict[str, Any]],
    seed: int,
    repetition: int,
    concurrency: int,
    duration_s: float,
    reasoning_effort: str | None,
    include_chat_template_kwargs: bool,
) -> tuple[list[dict[str, Any]], float]:
    start_event = threading.Event()
    deadline = [0.0]

    def worker(worker_id: int) -> list[dict[str, Any]]:
        generator = random.Random(seed + repetition * 1_000_003 + concurrency * 10_007 + worker_id)
        local_records: list[dict[str, Any]] = []
        sequence = 0
        start_event.wait()
        while time.perf_counter() < deadline[0]:
            case = cases[generator.randrange(len(cases))]
            request_started = time.perf_counter()
            record: dict[str, Any] = {
                "request_id": f"r{repetition:02d}-c{concurrency:03d}-w{worker_id:03d}-n{sequence:06d}",
                "repetition": repetition,
                "concurrency": concurrency,
                "worker": worker_id,
                "sequence": sequence,
                "case_id": case["id"],
                "started_offset_s": None,
                "status": "error",
                "e2e_s": None,
                "ttft_s": None,
                "tpot_ms": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "finish_reason": None,
                "content_chars": 0,
                "error_type": None,
                "error": None,
            }
            record["started_offset_s"] = round(request_started - (deadline[0] - duration_s), 6)
            try:
                sample = client.stream(
                    make_payload(model, case, reasoning_effort, include_chat_template_kwargs)
                )
                record.update(sample)
                record["status"] = "success"
            except Exception as exc:  # noqa: BLE001 - request failures are benchmark observations
                record["e2e_s"] = round(time.perf_counter() - request_started, 6)
                record["error_type"] = type(exc).__name__
                if isinstance(exc, urllib.error.HTTPError):
                    record["error"] = f"HTTP {exc.code}: {exc.reason}"
                else:
                    record["error"] = str(exc)[:500]
            local_records.append(record)
            sequence += 1
        return local_records

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker, worker_id) for worker_id in range(concurrency)]
        measurement_started = time.perf_counter()
        deadline[0] = measurement_started + duration_s
        start_event.set()
        records = [record for future in futures for record in future.result()]
        wall_time_s = time.perf_counter() - measurement_started
    records.sort(key=lambda item: (item["started_offset_s"], item["worker"], item["sequence"]))
    return records, wall_time_s


def compliance_checks(
    *,
    points: tuple[int, ...],
    duration_s: float,
    repetitions: int,
    metadata: dict[str, Any] | None,
    quality_gate_ref: str | None,
) -> dict[str, bool]:
    return {
        "operating_point_count_7_to_32": 7 <= len(points) <= 32,
        "duration_at_least_600_s": duration_s >= 600,
        "repetitions_at_least_3": repetitions >= 3,
        "metadata_provided": metadata is not None,
        "quality_gate_declared": bool(quality_gate_ref),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="unused")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--workload", type=Path, default=Path(__file__).with_name("workloads") / "standard-v1.json")
    parser.add_argument("--concurrency-points", type=parse_points, default=DEFAULT_POINTS)
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--warmup-requests", type=int, default=2)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--quality-gate-ref")
    parser.add_argument("--run-id")
    parser.add_argument("--metadata-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print-result", action="store_true", help="print the complete result even when --output is used")
    parser.add_argument("--allow-nonstandard", action="store_true")
    parser.add_argument("--reasoning-effort", choices=("none", "low", "medium", "high"))
    parser.add_argument("--omit-chat-template-kwargs", action="store_true")
    args = parser.parse_args()

    if args.duration_s <= 0 or args.repetitions < 1 or args.warmup_requests < 0:
        parser.error("duration, repetitions, and warmup values are out of range")

    started_at = utc_now()
    started_perf = time.perf_counter()
    run_id = validate_run_id(args.run_id) if args.run_id else default_run_id(args.model)
    metadata = load_metadata(args.metadata_file)
    workload_manifest, cases, workload_sha256 = load_workload(args.workload)
    seed = args.seed if args.seed is not None else int(workload_manifest.get("random_seed", 20260821))
    preflight_checks = compliance_checks(
        points=args.concurrency_points,
        duration_s=args.duration_s,
        repetitions=args.repetitions,
        metadata=metadata,
        quality_gate_ref=args.quality_gate_ref,
    )
    preflight_compliant = all(preflight_checks.values())
    if not preflight_compliant and not args.allow_nonstandard:
        failed = ", ".join(name for name, passed in preflight_checks.items() if not passed)
        parser.error(f"non-standard configuration ({failed}); use --allow-nonstandard for a preview")

    client = StreamClient(args.base_url, args.api_key, args.timeout)
    include_chat_template_kwargs = not args.omit_chat_template_kwargs
    for index in range(args.warmup_requests):
        case = cases[index % len(cases)]
        client.stream(make_payload(args.model, case, args.reasoning_effort, include_chat_template_kwargs))

    point_runs: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    for repetition in range(1, args.repetitions + 1):
        for concurrency in args.concurrency_points:
            print(
                f"repetition={repetition}/{args.repetitions} concurrency={concurrency} duration_s={args.duration_s:g}",
                file=sys.stderr,
                flush=True,
            )
            resource_before = capture_resource_snapshot()
            records, wall_time_s = run_point(
                client=client,
                model=args.model,
                cases=cases,
                seed=seed,
                repetition=repetition,
                concurrency=concurrency,
                duration_s=args.duration_s,
                reasoning_effort=args.reasoning_effort,
                include_chat_template_kwargs=include_chat_template_kwargs,
            )
            resource_after = capture_resource_snapshot()
            summary = summarize_point(records, concurrency, wall_time_s)
            point_runs.append(
                {
                    "repetition": repetition,
                    "concurrency": concurrency,
                    "scheduled_duration_s": args.duration_s,
                    "measured_duration_s": round(wall_time_s, 6),
                    "summary": summary,
                    "resource_before": resource_before,
                    "resource_after": resource_after,
                }
            )
            all_records.extend(records)

    curve: list[dict[str, Any]] = []
    for concurrency in args.concurrency_points:
        repetitions = [point for point in point_runs if point["concurrency"] == concurrency]
        curve.append(
            {
                "concurrency": concurrency,
                "repetitions": len(repetitions),
                "system_output_tps_ci95": mean_ci95(
                    [point["summary"]["system_output_tps"] for point in repetitions]
                ),
                "output_tps_per_user_ci95": mean_ci95(
                    [point["summary"]["output_tps_per_user"] for point in repetitions]
                ),
                "ttft_p95_s_ci95": mean_ci95(
                    [
                        point["summary"]["ttft_s"]["p95"]
                        for point in repetitions
                        if point["summary"]["ttft_s"]["p95"] is not None
                    ]
                ),
                "success_rate_ci95": mean_ci95(
                    [point["summary"]["success_rate"] for point in repetitions]
                ),
            }
        )

    successful_records = [record for record in all_records if record["status"] == "success"]
    execution_checks = {
        "every_point_has_success": all(point["summary"]["success_count"] > 0 for point in point_runs),
        "request_usage_complete": all(record["output_tokens"] > 0 for record in successful_records),
    }
    compliant = preflight_compliant and all(execution_checks.values())
    result = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_s": round(time.perf_counter() - started_perf, 6),
        "benchmark": {
            "name": "openai-compatible-endpoint-characterization",
            "version": BENCHMARK_VERSION,
            "implementation": "benchmarks/openai-compatible/characterize.py",
            "methodology_label": "MLPerf Endpoints-derived / custom workload / unverified",
        },
        "base_url": args.base_url,
        "model": args.model,
        "classification": "standard-characterization" if compliant else "characterization-preview",
        "metadata_status": "provided" if metadata is not None else "not_provided",
        "metadata": metadata,
        "quality_gate_ref": args.quality_gate_ref,
        "workload": {
            **workload_manifest,
            "path": str(args.workload),
            "sha256": workload_sha256,
            "seed": seed,
        },
        "request_settings": {
            "concurrency_points": list(args.concurrency_points),
            "duration_s": args.duration_s,
            "repetitions": args.repetitions,
            "warmup_requests": args.warmup_requests,
            "reasoning_effort": args.reasoning_effort,
            "chat_template_kwargs": include_chat_template_kwargs,
            "stream": True,
            "include_usage": True,
            "load_mode": "closed-loop-fixed-concurrency",
        },
        "compliance": {
            "preflight": preflight_checks,
            "execution": execution_checks,
            "compliant": compliant,
        },
        "curve": curve,
        "point_runs": point_runs,
        "requests": all_records,
        "passed": all(execution_checks.values()),
    }
    if args.output is not None:
        output_path = Path(str(args.output).replace("{run_id}", run_id))
        write_json_atomic(output_path, result)
        print(f"Wrote {output_path}", file=sys.stderr)
    if args.output is None or args.print_result:
        printable = result
    else:
        printable = {
            "run_id": run_id,
            "classification": result["classification"],
            "passed": result["passed"],
            "compliant": result["compliance"]["compliant"],
            "curve": result["curve"],
        }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (urllib.error.URLError, ValueError, OSError) as exc:
        print(json.dumps({"fatal_error": type(exc).__name__, "error": str(exc)[:2000]}, ensure_ascii=False))
        sys.exit(2)
