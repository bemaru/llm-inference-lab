# MLOps, LLMOps, and LLM Inference Scope

- Date: 2026-08-29
- Mode: external terminology review
- Scope: positioning model-serving and benchmark work without overstating its operational scope
- Status: research snapshot; revisit when the lab takes on broader lifecycle automation

## Question

Which term most accurately describes work that selects LLM artifacts and
quantizations, configures serving engines, measures latency and throughput, and
records reproducible benchmark conditions?

## Summary

The narrowest evidence-supported description for this lab's current work is
**LLM inference engineering**, with model serving and performance benchmarking
as its concrete activities.

- **MLOps** covers the broader ML system lifecycle, including integration,
  testing, release, deployment, infrastructure, automation, and monitoring.
- **LLMOps** covers the production lifecycle of LLM-powered applications,
  including prompt management, tracing, evaluation, monitoring, gateways, and
  governance.
- **LLM inference engineering** is a descriptive work label for configuring and
  optimizing deployed inference systems and characterizing them with metrics
  such as TTFT, end-to-end latency, inter-token latency, and throughput.

Using an experiment tracker such as MLflow does not by itself make a serving
benchmark an MLOps or LLMOps implementation. The label should follow the
implemented lifecycle responsibility, not the category of an individual tool.

## Scope Comparison

| Term | Typical scope | Fit for this lab's current work |
|---|---|---|
| MLOps | End-to-end ML development and operations, commonly including CI/CD, training or retraining pipelines, deployment, and production monitoring | Too broad as the primary label |
| LLMOps | Lifecycle management for LLM applications, including prompts, evaluation, tracing, monitoring, gateways, and governance | Useful as a parent discipline, but broader than the benchmark work |
| LLM inference engineering | Model serving, runtime and quantization selection, resource tuning, load characterization, and latency-throughput analysis | Primary work label |

`LLM inference engineering` is not asserted here as a formal standards-body
taxonomy. It is the most precise descriptive label supported by the actual work
and by current vendor documentation that groups TTFT, end-to-end latency, ITL,
TPS, and concurrency under LLM inference benchmarking.

## Practical Implication for This Lab

- Describe the repository's serving and benchmark work as **LLM inference** or
  **LLM inference engineering**.
- Use **LLMOps** only as a broader capability category when application
  evaluation, tracing, prompt lifecycle, deployment, and monitoring are also in
  scope.
- Use **MLOps** as the primary label only when the implemented system includes
  broader ML lifecycle automation and operations.
- Treat DGX Spark, vLLM, SGLang, MLflow, and similar names as platforms or tools,
  not responsibility-area labels.

## Sources

- [Google Cloud: MLOps continuous delivery and automation pipelines](https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [MLflow: What is LLMOps?](https://mlflow.org/llmops/)
- [NVIDIA NIM: LLM latency-throughput benchmarking](https://docs.nvidia.com/nim/benchmarking/llm/latest/index.html)
- [NVIDIA NIM: LLM inference metrics](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)

## Review Triggers

Revisit this conclusion when the repository adds any of the following as a
maintained responsibility:

- automated model or pipeline delivery,
- training or continuous retraining,
- production prompt and trace management,
- continuous application-quality monitoring,
- gateway governance or model-access policy enforcement.
