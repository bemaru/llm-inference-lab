---
status: proposed
date: 2026-08-20
decision-makers:
  - repository owner
review-triggers:
  - MLPerf Endpoints v1.0 release
  - material change to endpoint benchmark normalization or quality rules
---

# Use an MLPerf Endpoints-derived methodology for LLM serving benchmarks

## Context and Problem Statement

LLM serving results are often reduced to a single peak tokens-per-second number even though throughput, per-user interactivity, first-token latency, concurrency, reliability, and model quality trade off against one another. The lab needs a durable method for promoting an experiment to a comparable serving baseline without claiming formal MLPerf compliance for custom models and workloads.

## Decision Drivers

- Reflect the behavior of a deployed API endpoint under sustained load.
- Compare systems at equivalent user-experience and quality constraints.
- Keep the method independent of one serving engine or benchmark client.
- Preserve fast feedback for development without presenting smoke results as formal baselines.
- Make published claims reproducible and correctly qualified.

## Considered Options

- Rank systems by one peak output-tokens-per-second result.
- Use only short, fixed-concurrency repeated runs.
- Use only an MLPerf Inference Server-style Poisson request-rate test.
- Use an MLPerf Endpoints-derived performance curve with complementary regression and Poisson tracks.

## Decision Outcome

Chosen option: **Use an MLPerf Endpoints-derived performance curve with complementary regression and Poisson tracks**, because it captures the capacity-versus-interactivity trade-off of a real endpoint while retaining fast diagnostics and overload testing.

The following policy applies to serving baselines:

1. The deployed endpoint is the System Under Test. The recorded boundary includes the model, quantization, tokenizer, chat template, serving runtime, material scheduler and decoding settings, API path, hardware, and network path.
2. A serving configuration must pass its declared quality gate before it can become a performance baseline. Every materially distinct configuration requires quality validation.
3. A standard characterization contains at least 7 concurrency operating points, with each point measured for at least 600 seconds.
4. Every point reports system output tokens/s, output tokens/s per user, TTFT p95, concurrency, actual token distributions, and reliability outcomes.
5. The selected operating point is the highest-capacity point that satisfies the declared quality, TTFT, interactivity, and reliability SLOs. Peak throughput alone is not the selection criterion.
6. A Poisson open-loop request-rate sweep is a complementary capacity and overload track. Offline throughput is reported separately and is not used as the headline interactive result.
7. Short fixed-seed or repeated runs remain valid for smoke and regression testing but cannot be promoted directly to standard characterization results.
8. The methodology is tool-neutral. The MLCommons Endpoints harness is the reference implementation; AIPerf, Inference Perf, or another client is acceptable only when it preserves the workload, SUT boundary, measurement definitions, and artifacts.
9. Different models are compared only after meeting a common task-quality threshold or by presenting a quality-performance Pareto view.
10. Results that did not follow an applicable official submission and review process must not be called MLPerf results. Custom runs use an explicit label such as `MLPerf Endpoints-derived / custom workload / unverified`.

### Consequences

- Good, because the result exposes the system throughput versus user-experience trade-off instead of hiding it behind one peak number.
- Good, because runtime, quantization, and MTP changes cannot win by silently reducing quality.
- Good, because benchmark clients and serving engines remain replaceable.
- Good, because short regression runs remain available for day-to-day iteration.
- Bad, because a standard characterization requires at least 70 minutes of measured runtime before warm-up, quality, Poisson, and repeated validation costs.
- Bad, because dashboards and result schemas must represent curves and operating-point constraints rather than one sortable TPS column.
- Bad, because official MLPerf comparability remains unavailable for unsupported models or custom workloads.

### Confirmation

An accepted baseline conforms to this decision when its evidence contains:

- a versioned SUT and workload manifest,
- an accuracy or task-quality result for each material configuration,
- at least 7 sustained concurrency points of at least 600 seconds each,
- per-request records and aggregate System TPS, per-user TPS, TTFT p95, and reliability metrics,
- the SLO and rationale used to select the operating point,
- an explicit official, derived, custom, and verification-status label.

`benchmarks/README.md` and future benchmark schemas are the living operational specification. This ADR records why that specification follows the endpoint-curve approach.

## Out of Scope

- Selecting one serving engine such as vLLM or SGLang
- Selecting one benchmark client such as AIPerf
- Selecting a model, quantization, or MTP configuration
- Defining the OpenAI-compatible API and tool-calling contract
- Defining workload-specific quality rubrics or product SLO values
- Claiming official MLPerf compliance

Those decisions can change independently and should be recorded separately when they become durable.

## More Information

- [Research: 2026-08-20 LLM serving benchmark standards](../research/2026-08-20-llm-serving-benchmark-standards.md)
- [MLPerf Endpoints](https://mlcommons.org/benchmarks/endpoints/)
- [MLCommons Endpoints harness](https://github.com/mlcommons/endpoints)
- [MLPerf Inference rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)
- [MADR template](https://adr.github.io/madr/decisions/adr-template.html)
