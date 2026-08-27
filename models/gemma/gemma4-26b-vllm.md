# Gemma4 26B on vLLM

## Current Baseline

Model: `google/gemma-4-26B-A4B-it`

Known working Docker image on CUDA 13 / DGX Spark-class hardware:

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

Next validation should focus on:

- FP4/NVFP4 or other quantized Gemma4 variants
- whether a newer vLLM image removes the need for `--enforce-eager`
- concurrency and context-length sensitivity
- SGLang or TensorRT-LLM comparison if Gemma4 support is mature enough
