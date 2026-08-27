# YYYY-MM-DD Engine Model Run

## Summary

- Engine:
- Engine version:
- Model:
- Quantization / format:
- Hardware:
- Result:
- Classification: quick | baseline | regression | soak

## Goal

Describe what this run is trying to validate.

## Environment

```text
OS:
Driver:
CUDA:
Container image:
Runtime:
Model artifact:
Tokenizer revision:
Benchmark tool:
Client location / network path:
```

## Command

```bash
# sanitized command here
```

## API Smoke

```bash
curl http://127.0.0.1:<port>/health
curl http://127.0.0.1:<port>/v1/models
```

## Measurements

| Metric | Value |
| --- | --- |
| startup time | |
| TTFT p50 / p95 / p99 | |
| TTFO p50 / p95 / p99 | |
| ITL/TPOT p50 / p95 / p99 | |
| E2E latency p50 / p95 / p99 | |
| output throughput | |
| per-user output throughput | |
| request throughput / goodput | |
| success / error / timeout | |
| input / output / reasoning tokens | |
| KV-cache peak / prefix-cache hit | |
| host memory | |
| accelerator memory / utilization | |
| temperature / power | |
| swap | |

## Workload

| Item | Value |
|---|---|
| input/output distribution | |
| reasoning / streaming | |
| concurrency or request rate | |
| arrival pattern | |
| warm-up | |
| requests or duration | |
| runs / confidence interval | |
| random seed | |

## Findings

-

## Follow-Ups

-
