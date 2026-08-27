# Gemma4 26B BF16 on vLLM

## Historical baseline — 2026-05-01

This page preserves the BF16 API smoke recorded as
`20260501-gemma4-bf16-smoke` in the
[normalized result set](../../benchmarks/results/dgx-spark.json). It is not the
current serving default or a Quick benchmark. See the
[Gemma guide](README.md) for later quantized profiles and measurements.

Model: `google/gemma-4-26B-A4B-it`

Docker image used in that CUDA 13 / DGX Spark-class measurement:

```text
vllm/vllm-openai:gemma4-cu130
```

Measured vLLM version from that image:

```text
0.18.2rc1.dev73+gdb7a17ecc
```

Conservative first-load options:

```bash
vllm serve google/gemma-4-26B-A4B-it \
  --host 0.0.0.0 \
  --port 8011 \
  --max-model-len 2048 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.60 \
  --enforce-eager \
  --limit-mm-per-prompt '{"image":0,"audio":0}'
```

## Observations

- Docker vLLM worked; no host Python vLLM install was required.
- BF16 loading is memory-heavy on unified-memory systems. In a co-located stack, reducing unrelated resident memory was required before the service reached API-ready state.
- Loading two safetensor shards took about 334 seconds in the measured run. End-to-end API readiness took about 7 minutes.
- vLLM logged `Model loading took 48.5 GiB memory`, with about `24.09 GiB` available for KV cache after load.
- Once API-ready, `/health`, `/v1/models`, and `/v1/chat/completions` succeeded.
- A small chat completion with 41 prompt tokens and 160 completion tokens took about `8.2s` total and logged about `16 tok/s` generation throughput.

## Interpretation

Gemma4 26B BF16 can run through vLLM on DGX Spark-class hardware, but it is not a comfortable default for a shared host when other memory-heavy services are running. Treat BF16 as a functionality baseline, not an optimized operating mode.

## Follow-up records

NVFP4 and eager/compiled execution were subsequently measured on 2026-08-25.
See the [scheduler comparison](../../benchmarks/results/gemma4-scheduler.md)
for the exact model revision, runtime, workload, and retained results. Those
Quick runs are a separate evidence set, not an update to the BF16 numbers above.

Sustained-load behavior, context-length sensitivity, and answer quality require
separate evidence. This BF16 record does not establish SGLang or TensorRT-LLM
compatibility.
