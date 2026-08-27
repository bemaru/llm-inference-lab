# Qwen

Serving notes and retained DGX Spark measurements for Qwen3.6 and Qwen3.8.

## Serving recipes

- [Qwen3.6 35B-A3B NVFP4 on vLLM](../../engines/vllm/README.md#qwen36-35b-a3b-nvfp4-baseline):
  separate MTP-off and MTP-on profiles, with 32K context, two sequences, FP8 KV
  cache, and thinking disabled in the recorded baseline.
- [Qwen3.8 27B FP8 on vLLM](../../engines/vllm/README.md#candidate-profiles).
- [Qwen3.8 27B NVFP4 on SGLang](../../engines/sglang/README.md#qwen38-27b-nvfp4-speculative-recipes):
  MTP, DSpark, and DFlash2 recipes.

## Recorded comparisons

The [normalized result set](../../benchmarks/results/dgx-spark.json) retains
these Quick measurements from **2026-08-21**:

- **Qwen3.6 MTP off/on:** both configurations were measured. MTP increased
  synthetic decode performance and accelerator memory allocation in these runs.
- **Qwen3.8 FP8 and NVFP4:** records cover vLLM and SGLang configurations, not
  a controlled quantization-only comparison.
- **SGLang speculative modes:** DSpark and DFlash2 had different output lengths
  and finish reasons, so their runs are excluded from output-throughput ranking.

These small synthetic runs do not establish answer quality or sustained
capacity. Use the [comparison rules](../../benchmarks/results/README.md) and
recorded revisions, runtime settings, and workload before comparing results.
