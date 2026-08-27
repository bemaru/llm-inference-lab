# Gemma

Serving notes and retained DGX Spark measurements for Gemma 4 26B-A4B.

## Serving notes

- [Historical BF16 API smoke on vLLM](gemma4-26b-vllm.md) — a functionality
  baseline from 2026-05-01, not the current optimized configuration.
- [NVFP4 vLLM profile](../../engines/vllm/README.md#candidate-profiles) — the
  recorded GB10 path uses Marlin weight-only quantization, not native FP4 compute.
- [Q4_K_M on Ollama](../../engines/ollama/README.md#gemma4-26b-a4b-q4_k_m-on-dgx-spark).

## Recorded comparisons

The [scheduler and execution-mode comparison](../../benchmarks/results/gemma4-scheduler.md)
covers NVFP4 eager seq2, eager seq4, and compiled seq4 measurements from
**2026-08-25**, including the small-sample limitations.

The [normalized result set](../../benchmarks/results/dgx-spark.json) also retains
an earlier blocked NVFP4 configuration and the Ollama Quick run. Compatibility
is specific to the recorded artifact and runtime; a later passing configuration
does not erase an earlier failure. The historical BF16 smoke is unranked and
must not be compared directly with these Quick results.
