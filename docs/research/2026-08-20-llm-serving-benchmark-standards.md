# LLM Serving Benchmark Standards

- Date: 2026-08-20
- Mode: external standards research
- Scope: project-independent LLM endpoint serving and performance measurement
- Status: research snapshot; recheck on the MLPerf Endpoints v1.0 release

## Question

What can currently be called a standard method for serving and benchmarking an LLM endpoint, and which parts are formal standards, de facto interfaces, emerging conventions, or implementation tools?

## Summary

As of the research date, there is no single universal standard covering arbitrary models, serving APIs, quality evaluation, performance measurement, and observability together.

The most defensible structure is:

1. Use MLPerf Inference for formal, fixed-workload system comparison.
2. Use the newer MLPerf Endpoints methodology for live endpoint characterization.
3. Treat OpenAI-compatible APIs as a de facto generative inference interface, not an independent open standard.
4. Treat AIPerf, Inference Perf, and `vllm bench serve` as benchmark implementations or diagnostic tools, not standards themselves.
5. Use an accuracy gate before comparing performance and select an operating point from a performance curve rather than ranking systems by a single peak throughput number.

## Standards Landscape

| Area | Current role | Practical interpretation |
|---|---|---|
| MLPerf Inference v6.0 | Mature formal inference benchmark | Use its reproducibility, quality, scenario, and claim rules for official comparable results. |
| MLPerf Endpoints v0.7 | Emerging API-native endpoint benchmark | The closest current standard for characterizing a deployed LLM endpoint under varying load. |
| OpenAI-compatible API | De facto generative API | Useful interoperability contract, but not a vendor-neutral standards-body specification. |
| KServe V2 protocol | Standardized predictive inference data plane | Strong for health, metadata, and tensor inference; generative serving generally uses OpenAI-compatible routes. |
| OpenTelemetry GenAI conventions | Emerging observability convention | Useful naming direction, but the GenAI metric conventions remain in Development status and should be version-pinned. |
| AIPerf / Inference Perf | Benchmark tools | Suitable for internal and custom workloads when the workload and metric contract is explicit. |
| `vllm bench serve` | Engine-local diagnostic | Suitable for vLLM regression and tuning, not a cross-industry standard result by itself. |

## Standard Endpoint Characterization

MLPerf Endpoints v0.7 represents a serving system as a performance curve instead of one peak number.

For a formal characterization:

- Treat the deployed endpoint as the System Under Test (SUT).
- Keep the model, endpoint, and serving software stack consistent along a curve.
- Measure at least 7 and at most 32 operating points.
- Run every operating point for at least 600 seconds.
- Use a fixed concurrency at each point and vary concurrency across points.
- Validate accuracy for every materially distinct serving configuration.
- Report the relationship among:
  - system output tokens per second,
  - output tokens per second per user,
  - TTFT p95,
  - concurrency.

The decision point is the highest-capacity point that still meets the required user interactivity, TTFT, reliability, and quality constraints. Comparing each system at its most flattering peak is not a valid operating-point comparison.

## Complementary Load Scenarios

The endpoint curve does not remove the need for other scenarios.

### Poisson Open-Loop

MLPerf Inference Server and Interactive scenarios use Poisson arrivals and determine the maximum request rate supported under benchmark-specific tail-latency constraints. This remains useful for queueing behavior, overload, and admission-control validation.

### Offline

Offline maximum throughput is appropriate for batch processing. It should not be used as the headline result for an interactive endpoint.

### Short Regression

Short request-count runs and repeated fixed-seed runs are useful for smoke tests and regression detection. They are not substitutes for a sustained endpoint characterization run.

## Quality and Comparison Boundary

Performance and quality runs should be separate but use equivalent serving behavior.

- A quantization, sampling, reasoning, speculative decoding, MTP, tokenizer, or chat-template change can require renewed quality validation.
- Same-model comparisons can evaluate hardware and runtime efficiency after meeting the same accuracy threshold.
- Different-model comparisons require a common task-quality threshold or a quality-performance Pareto view.
- Raw throughput alone must not rank models with materially different quality.

Official MLPerf names apply only when the relevant rules, workloads, result structure, review, and submission requirements are satisfied. Other results should be labeled, for example:

> MLPerf Endpoints-derived / custom workload / unverified

## Metric Contract

Metric names are not fully standardized across benchmark tools, so every result needs an explicit measurement point and formula.

| Metric | Required meaning |
|---|---|
| TTFT | Client request issuance to receipt of the first generated token; do not substitute first byte or an empty stream chunk. |
| TTFB / TTFC | First response byte or chunk; report separately from TTFT. |
| TPOT | Per-request decode time amortized over output tokens after the first token. |
| ITL | Observed gap between streamed output events; it can diverge from TPOT with speculative decoding or multi-token chunks. |
| E2E latency | Client request issuance to final response completion. |
| System TPS | Total generated output tokens divided by the measurement interval. |
| Interactivity | Generated output tokens per second per active user or request. |
| Reliability | Attempted, successful, failed, timed out, cancelled, and retried requests. |
| Tokens | Actual input, output, reasoning, cached, and truncated token distributions when available. |

The benchmark also needs resource-boundary evidence such as host and accelerator memory, utilization, temperature, and power. Power results must state whether they cover only the accelerator or the complete SUT.

## Reproducibility Requirements

At minimum, preserve:

- hardware topology and client/server placement,
- OS, driver, firmware, runtime, and benchmark tool versions,
- container image digest and source revision,
- model artifact, quantization, tokenizer, and chat-template revisions,
- complete server and benchmark configurations,
- dataset version, checksum, and input/output length distributions,
- random seeds, warm-up, duration, concurrency or arrival-rate schedule,
- per-request records, aggregate results, accuracy results, and error categories,
- network boundary and client overhead validation.

Benchmark-specific behavior, input detection, hidden retries, response caching, or special-casing that cannot apply to a long-running production service invalidates a fair comparison.

## Tool Roles

| Need | Suitable tool |
|---|---|
| Formal MLPerf comparison or submission | MLPerf Endpoints harness or MLPerf Inference LoadGen under the applicable rules |
| Custom endpoint curve | MLCommons Endpoints harness with an explicit custom/unverified label |
| SLO and goodput exploration | AIPerf |
| Vendor-neutral trace and Kubernetes-oriented workloads | Inference Perf |
| vLLM tuning and regression diagnosis | `vllm bench serve` |

Tool selection should remain replaceable. A benchmark result is comparable only when workload generation, measurement points, formulas, SUT boundary, and quality gates remain equivalent.

## Practical Implication for This Lab

The lab should maintain two benchmark tiers:

1. Quick/regression: short runs for smoke and change detection.
2. Standard characterization: a sustained multi-point endpoint curve with an accuracy gate.

The durable methodology decision belongs in an ADR. Executable metric and artifact requirements belong in `benchmarks/`, while dated measurements belong in `run-logs/` or ignored raw artifact storage.

## Sources

- [MLPerf Endpoints](https://mlcommons.org/benchmarks/endpoints/)
- [MLPerf Endpoints v0.7 foundation release](https://mlcommons.org/2026/07/mlperf-endpoints-v0-7-release/)
- [MLCommons Endpoints harness](https://github.com/mlcommons/endpoints)
- [MLPerf Inference rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)
- [MLPerf Inference reference implementation](https://github.com/mlcommons/inference)
- [KServe Data Plane protocols](https://kserve.github.io/website/docs/concepts/architecture/data-plane)
- [OpenTelemetry GenAI metrics](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/gen-ai/gen-ai-metrics.md)
- [AIPerf metrics reference](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference)
- [Kubernetes SIG Inference Perf](https://github.com/kubernetes-sigs/inference-perf)
- [vLLM benchmark metric definitions](https://docs.vllm.ai/en/latest/benchmarking/cli/)

## Review Triggers

Revisit this snapshot when any of the following occurs:

- MLPerf Endpoints v1.0 is released.
- MLPerf changes endpoint normalization, quality, power, or workload rules materially.
- OpenTelemetry GenAI semantic conventions become Stable.
- The lab adopts a public or externally reviewed benchmark publication process.
