#!/usr/bin/env python3
"""Dependency-free OpenAI-compatible correctness and quick performance check."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import csv
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any
import uuid


SCHEMA_VERSION = "openai-compatible-quick/v1"
BENCHMARK_VERSION = "1.0"
METADATA_ENV = "LLM_BENCHMARK_METADATA_B64"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_run_id(model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")[:64] or "model"
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{slug}-{uuid.uuid4().hex[:8]}"


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", run_id):
        raise ValueError("run ID must contain only letters, numbers, dot, underscore, colon, or hyphen")
    return run_id


def validate_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a JSON object")
    required_sections = {
        "hardware",
        "model_artifact",
        "serving",
        "software",
        "execution",
        "provenance",
    }
    missing = sorted(required_sections - metadata.keys())
    if missing:
        raise ValueError(f"metadata is missing required sections: {', '.join(missing)}")
    for section in required_sections:
        if not isinstance(metadata[section], dict):
            raise ValueError(f"metadata.{section} must be a JSON object")
    return metadata


def load_metadata(path: Path | None) -> dict[str, Any] | None:
    encoded = os.environ.get(METADATA_ENV)
    if path is not None and encoded:
        raise ValueError(f"use either --metadata-file or {METADATA_ENV}, not both")
    if path is not None:
        return validate_metadata(json.loads(path.read_text(encoding="utf-8")))
    if encoded:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8")
        return validate_metadata(json.loads(raw))
    return None


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(serialized)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def nullable_number(value: str) -> float | None:
    normalized = value.strip()
    if not normalized or normalized in {"N/A", "[N/A]", "Not Supported"}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def nvidia_smi_rows(query: str) -> list[list[str]]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            f"--query-{query}",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return list(csv.reader(line for line in completed.stdout.splitlines() if line.strip()))


def capture_resource_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "captured_at": utc_now(),
        "host_memory": None,
        "accelerators": [],
        "accelerator_processes": [],
        "errors": [],
    }
    try:
        meminfo: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            fields = value.strip().split()
            if fields:
                meminfo[key] = int(fields[0]) * 1024
        snapshot["host_memory"] = {
            "total_bytes": meminfo.get("MemTotal"),
            "available_bytes": meminfo.get("MemAvailable"),
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic collection must not discard the benchmark
        snapshot["errors"].append(f"host_memory: {type(exc).__name__}: {str(exc)[:300]}")

    try:
        rows = nvidia_smi_rows("gpu=index,name,driver_version,utilization.gpu,temperature.gpu")
        snapshot["accelerators"] = [
            {
                "index": int(row[0].strip()),
                "name": row[1].strip(),
                "driver_version": row[2].strip(),
                "utilization_pct": nullable_number(row[3]),
                "temperature_c": nullable_number(row[4]),
            }
            for row in rows
            if len(row) >= 5
        ]
    except Exception as exc:  # noqa: BLE001 - diagnostic collection must not discard the benchmark
        snapshot["errors"].append(f"accelerators: {type(exc).__name__}: {str(exc)[:300]}")

    try:
        rows = nvidia_smi_rows("compute-apps=pid,process_name,used_memory")
        snapshot["accelerator_processes"] = [
            {
                "pid": int(row[0].strip()),
                "process_name": row[1].strip(),
                "used_memory_mib": nullable_number(row[2]),
            }
            for row in rows
            if len(row) >= 3
        ]
    except Exception as exc:  # noqa: BLE001 - diagnostic collection must not discard the benchmark
        snapshot["errors"].append(f"accelerator_processes: {type(exc).__name__}: {str(exc)[:300]}")
    return snapshot


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 3)


def summarize(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": round(statistics.median(values), 3) if values else None,
        "p95": percentile(values, 0.95),
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }


class Client:
    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="GET" if payload is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def stream(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        first_content_at: float | None = None
        content: list[str] = []
        usage: dict[str, Any] = {}
        finish_reason: str | None = None
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        if first_content_at is None:
                            first_content_at = time.perf_counter()
                        content.append(delta["content"])
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
        ended = time.perf_counter()
        if first_content_at is None:
            raise AssertionError("stream returned no content")
        completion_tokens = int(usage.get("completion_tokens", 0))
        e2e = ended - started
        ttft = first_content_at - started
        decode_seconds = max(e2e - ttft, 1e-9)
        return {
            "ttft_s": round(ttft, 3),
            "e2e_s": round(e2e, 3),
            "completion_tokens": completion_tokens,
            "output_tps_e2e": round(completion_tokens / e2e, 3),
            "decode_tps": round(max(completion_tokens - 1, 0) / decode_seconds, 3),
            "tpot_ms": round(1000 * decode_seconds / max(completion_tokens - 1, 1), 3),
            "finish_reason": finish_reason,
            "content_chars": len("".join(content)),
        }


def chat_payload(model: str, prompt: str, max_tokens: int, *, stream: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": stream,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def parse_tool_call(response: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
    choice = response["choices"][0]
    calls = choice["message"].get("tool_calls") or []
    if len(calls) != 1:
        content = choice["message"].get("content")
        raise AssertionError(f"expected one tool call, got {len(calls)}; content={content!r}")
    function = calls[0]["function"]
    return function["name"], json.loads(function["arguments"]), choice.get("finish_reason")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="unused")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--stream-runs", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--concurrent-requests", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--tool-runs", type=int, default=1)
    parser.add_argument("--run-id", help="stable run identifier; generated when omitted")
    parser.add_argument(
        "--metadata-file",
        type=Path,
        help="JSON metadata matching the metadata contract in result.schema.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="atomically write the complete JSON result; {run_id} is expanded",
    )
    parser.add_argument(
        "--performance-prompt-profile",
        choices=("repeated-word", "sequential-integers"),
        default="repeated-word",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high"),
        help="set the OpenAI-compatible reasoning_effort field when supported",
    )
    parser.add_argument(
        "--omit-chat-template-kwargs",
        action="store_true",
        help="omit the vLLM-specific chat_template_kwargs request field",
    )
    args = parser.parse_args()

    started_at = utc_now()
    started_perf = time.perf_counter()
    run_id = validate_run_id(args.run_id) if args.run_id else default_run_id(args.model)
    metadata = load_metadata(args.metadata_file)

    client = Client(args.base_url, args.api_key, args.timeout)

    def make_chat_payload(prompt: str, max_tokens: int, *, stream: bool = False) -> dict[str, Any]:
        payload = chat_payload(args.model, prompt, max_tokens, stream=stream)
        if args.omit_chat_template_kwargs:
            payload.pop("chat_template_kwargs", None)
        if args.reasoning_effort is not None:
            payload["reasoning_effort"] = args.reasoning_effort
        return payload

    results: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": None,
        "elapsed_s": None,
        "benchmark": {
            "name": "openai-compatible-quick-check",
            "version": BENCHMARK_VERSION,
            "implementation": "benchmarks/openai-compatible/quick_check.py",
        },
        "base_url": args.base_url,
        "model": args.model,
        "classification": "quick",
        "metadata_status": "provided" if metadata is not None else "not_provided",
        "metadata": metadata,
        "request_settings": {
            "warmup": args.warmup,
            "stream_runs": args.stream_runs,
            "concurrency": args.concurrency,
            "concurrent_requests": args.concurrent_requests,
            "max_tokens": args.max_tokens,
            "tool_runs": args.tool_runs,
            "performance_prompt_profile": args.performance_prompt_profile,
            "reasoning_effort": args.reasoning_effort,
            "chat_template_kwargs": not args.omit_chat_template_kwargs,
        },
        "checks": {},
        "performance": {},
        "resource_snapshot": None,
    }
    failures: list[str] = []

    def check(name: str, operation: Any) -> None:
        started = time.perf_counter()
        try:
            value = operation()
            results["checks"][name] = {
                "passed": True,
                "elapsed_s": round(time.perf_counter() - started, 3),
                **(value or {}),
            }
        except Exception as exc:  # noqa: BLE001 - report all provider failures
            failures.append(name)
            results["checks"][name] = {
                "passed": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
            }

    def models_check() -> dict[str, Any]:
        response = client.request("/models")
        model_ids = [item["id"] for item in response["data"]]
        if args.model not in model_ids:
            raise AssertionError("served model ID is absent")
        return {"model_ids": model_ids}

    check("models", models_check)

    def chat_check() -> dict[str, Any]:
        response = client.request(
            "/chat/completions",
            make_chat_payload("분석 준비 완료라고 한국어 한 문장으로 답해줘.", 64),
        )
        choice = response["choices"][0]
        content = choice["message"].get("content") or ""
        if not content.strip() or choice.get("finish_reason") != "stop":
            raise AssertionError(f"incomplete chat response: {choice!r}")
        return {
            "finish_reason": choice["finish_reason"],
            "content": content,
            "usage": response.get("usage"),
        }

    check("chat", chat_check)

    performance_prompts = {
        "repeated-word": (
            "Output the word benchmark repeatedly, separated by one space. "
            "Do not add punctuation, numbering, explanation, or any other word. "
            "Continue until the output limit."
        ),
        "sequential-integers": (
            "Write positive integers in ascending order starting from 1, separated by one space. "
            "Do not add punctuation, headings, explanation, or any other text. "
            "Continue until the output limit."
        ),
    }
    performance_prompt = performance_prompts[args.performance_prompt_profile]
    try:
        for _ in range(args.warmup):
            client.request(
                "/chat/completions",
                make_chat_payload(performance_prompt, min(args.max_tokens, 64)),
            )

        stream_samples = [
            client.stream(
                "/chat/completions",
                make_chat_payload(performance_prompt, args.max_tokens, stream=True),
            )
            for _ in range(args.stream_runs)
        ]
        results["performance"]["streaming_single_user"] = {
            "samples": stream_samples,
            "ttft_s": summarize([item["ttft_s"] for item in stream_samples]),
            "e2e_s": summarize([item["e2e_s"] for item in stream_samples]),
            "decode_tps": summarize([item["decode_tps"] for item in stream_samples]),
            "tpot_ms": summarize([item["tpot_ms"] for item in stream_samples]),
        }
    except Exception as exc:  # noqa: BLE001 - preserve benchmark failures in the result artifact
        failures.append("streaming_single_user")
        results["performance"]["streaming_single_user"] = {
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
        }

    try:
        concurrent_started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            concurrent_responses = list(
                executor.map(
                    lambda _: client.request(
                        "/chat/completions",
                        make_chat_payload(performance_prompt, args.max_tokens),
                    ),
                    range(args.concurrent_requests),
                )
            )
        concurrent_elapsed = time.perf_counter() - concurrent_started
        concurrent_output_tokens = sum(
            int(response.get("usage", {}).get("completion_tokens", 0))
            for response in concurrent_responses
        )
        results["performance"]["closed_loop"] = {
            "concurrency": args.concurrency,
            "requests": args.concurrent_requests,
            "wall_time_s": round(concurrent_elapsed, 3),
            "completion_tokens": concurrent_output_tokens,
            "aggregate_output_tps": round(concurrent_output_tokens / concurrent_elapsed, 3),
            "requests_per_s": round(args.concurrent_requests / concurrent_elapsed, 3),
            "finish_reasons": [response["choices"][0].get("finish_reason") for response in concurrent_responses],
        }
    except Exception as exc:  # noqa: BLE001 - preserve benchmark failures in the result artifact
        failures.append("closed_loop")
        results["performance"]["closed_loop"] = {
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
        }

    simple_schema = {
        "type": "object",
        "properties": {"pid": {"type": "integer"}},
        "required": ["pid"],
        "additionalProperties": False,
    }

    def simple_tool_check() -> dict[str, Any]:
        payload = make_chat_payload(
            "PID 1234를 조사해. 반드시 get_process_details 도구를 호출해.",
            128,
        )
        payload.update(
            {
                "tools": [tool("get_process_details", "PID로 프로세스 정보를 조회한다.", simple_schema)],
                "tool_choice": "auto",
            }
        )
        name, arguments, finish_reason = parse_tool_call(client.request("/chat/completions", payload))
        if name != "get_process_details" or arguments != {"pid": 1234}:
            raise AssertionError(f"unexpected tool call: {name} {arguments}")
        return {"tool": name, "arguments": arguments, "finish_reason": finish_reason}

    for index in range(args.tool_runs):
        name = "tool_simple" if args.tool_runs == 1 else f"tool_simple_{index + 1:02d}"
        check(name, simple_tool_check)

    nested_schema = {
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string"},
                    "time_range": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                    "severities": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["host", "time_range", "severities"],
                "additionalProperties": False,
            },
            "limit": {"type": "integer"},
        },
        "required": ["filters", "limit"],
        "additionalProperties": False,
    }
    expected_nested = {
        "filters": {
            "host": "pc-001",
            "time_range": {"start": "2026-08-20T00:00:00Z", "end": "2026-08-21T00:00:00Z"},
            "severities": ["high", "critical"],
        },
        "limit": 25,
    }

    def nested_tool_check() -> dict[str, Any]:
        payload = make_chat_payload(
            "pc-001의 2026-08-20T00:00:00Z부터 2026-08-21T00:00:00Z까지 high와 critical 이벤트 25개를 조회해. 반드시 search_detection_events 도구를 호출해.",
            256,
        )
        payload.update(
            {
                "tools": [tool("search_detection_events", "예제 이벤트를 검색한다.", nested_schema)],
                "tool_choice": "auto",
            }
        )
        name, arguments, finish_reason = parse_tool_call(client.request("/chat/completions", payload))
        if name != "search_detection_events" or arguments != expected_nested:
            raise AssertionError(f"unexpected nested tool call: {name} {arguments}")
        return {"tool": name, "arguments": arguments, "finish_reason": finish_reason}

    for index in range(args.tool_runs):
        name = "tool_nested" if args.tool_runs == 1 else f"tool_nested_{index + 1:02d}"
        check(name, nested_tool_check)

    def large_tool_surface_check() -> dict[str, Any]:
        decoys = [
            tool(
                f"lookup_signal_{index:02d}",
                f"보안 신호 종류 {index:02d}를 조회한다.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
            for index in range(31)
        ]
        target_schema = {
            "type": "object",
            "properties": {
                "hostname": {"type": "string"},
                "include_isolated": {"type": "boolean"},
            },
            "required": ["hostname", "include_isolated"],
            "additionalProperties": False,
        }
        payload = make_chat_payload(
            "host example-host-07의 위험도를 격리 단말 포함으로 조회해. 반드시 fetch_endpoint_risk 도구를 호출해.",
            256,
        )
        payload.update(
            {
                "tools": decoys
                + [tool("fetch_endpoint_risk", "예제 호스트의 위험도를 조회한다.", target_schema)],
                "tool_choice": "auto",
            }
        )
        name, arguments, finish_reason = parse_tool_call(client.request("/chat/completions", payload))
        expected = {"hostname": "example-host-07", "include_isolated": True}
        if name != "fetch_endpoint_risk" or arguments != expected:
            raise AssertionError(f"unexpected large-surface tool call: {name} {arguments}")
        return {
            "tool_count": len(payload["tools"]),
            "tool": name,
            "arguments": arguments,
            "finish_reason": finish_reason,
        }

    for index in range(args.tool_runs):
        name = "tool_large_surface" if args.tool_runs == 1 else f"tool_large_surface_{index + 1:02d}"
        check(name, large_tool_surface_check)

    results["passed"] = not failures
    results["failures"] = failures
    results["resource_snapshot"] = capture_resource_snapshot()
    results["completed_at"] = utc_now()
    results["elapsed_s"] = round(time.perf_counter() - started_perf, 3)
    if args.output is not None:
        output_path = Path(str(args.output).replace("{run_id}", run_id))
        write_json_atomic(output_path, results)
        print(f"Wrote {output_path}", file=sys.stderr)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"fatal_http_error": exc.code, "body": error_body[:2000]}, ensure_ascii=False, indent=2))
        sys.exit(2)
