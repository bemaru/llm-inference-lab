# vLLM

Serving recipes, benchmark notes, and troubleshooting records for vLLM.

Initial focus:

- Gemma4 serving on CUDA 13 / DGX Spark-class hardware
- Qwen FP8 serving
- memory sizing with `--gpu-memory-utilization`, context length, and concurrency
- OpenAI-compatible API smoke tests

## Files

- [docker-compose.single-node.yml](docker-compose.single-node.yml)
- [.env.example](.env.example)

## Qwen3.6 35B-A3B NVFP4 Baseline

The `qwen36-nvfp4` profile is the initial MTP-off correctness baseline for a single DGX Spark. It pins vLLM `v0.24.0-ubuntu2404`, limits the first characterization to 32K context and two sequences, disables thinking by default, and exposes the OpenAI-compatible API on port `8000`.

```bash
cp .env.example .env
# Set HF_CACHE to the host cache path, then run:
docker compose --env-file .env -f docker-compose.single-node.yml \
  --profile qwen36-nvfp4 up -d vllm-qwen36-35b-a3b-nvfp4
```

When the repository is local but the Docker daemon is on Spark, use Docker's SSH transport. `HF_CACHE` is evaluated as a path on the remote host.

```bash
DOCKER_HOST=ssh://SSH_TARGET \
HF_CACHE=/remote/path/to/huggingface-cache \
docker compose -f engines/vllm/docker-compose.single-node.yml \
  --profile qwen36-nvfp4 up -d vllm-qwen36-35b-a3b-nvfp4
```

MTP is intentionally absent from the baseline profile. Use the separate MTP-on
A/B profile below after checking chat, streaming, and tool calling on your runtime.

After that gate passes, stop the baseline and start the NVIDIA-recommended MTP
`n3` profile on the same port. All other serving controls remain unchanged.

```bash
DOCKER_HOST=ssh://SSH_TARGET \
HF_CACHE=/remote/path/to/huggingface-cache \
docker compose -f engines/vllm/docker-compose.single-node.yml \
  --profile qwen36-nvfp4 stop vllm-qwen36-35b-a3b-nvfp4

DOCKER_HOST=ssh://SSH_TARGET \
HF_CACHE=/remote/path/to/huggingface-cache \
docker compose -f engines/vllm/docker-compose.single-node.yml \
  --profile qwen36-nvfp4-mtp up -d vllm-qwen36-35b-a3b-nvfp4-mtp
```

The MTP profile follows the model card's speculative configuration: three MTP
tokens with the speculative MoE backend set to Triton. Compare it with the
MTP-off run using the same client workload; do not mix their results.

Both configurations have retained Quick measurements; see the
[Qwen recorded comparisons](../../models/qwen/README.md#recorded-comparisons).
Recheck the baseline when the artifact, runtime, or serving settings change.

## Candidate Profiles

The current candidate set uses port `8000`, so run only one service at a time.

| Profile | Service | Intended use |
| --- | --- | --- |
| `nemotron35-nvfp4-candidate` | `vllm-nemotron35-lightning-nvfp4-candidate` | NVFP4 + DSpark n3 comparison |
| `qwen38-fp8-candidate` | `vllm-qwen38-27b-fp8-candidate` | dense quality reference |
| `exaone45-awq-candidate` | `vllm-exaone45-33b-awq-candidate` | non-commercial Korean benchmark reference |
| `gemma4-nvfp4-candidate` | `vllm-gemma4-26b-a4b-nvfp4-candidate` | Gemma comparison; NVFP4 Marlin, compiled seq4, MTP off, digest pinned |

For example, start the Nemotron profile from the repository root:

```bash
DOCKER_HOST=ssh://SSH_TARGET \
HF_CACHE=/remote/path/to/huggingface-cache \
docker compose -p llm-inference-lab \
  -f engines/vllm/docker-compose.single-node.yml \
  --profile nemotron35-nvfp4-candidate up -d --pull never \
  vllm-nemotron35-lightning-nvfp4-candidate
```

Wait for `GET http://127.0.0.1:8000/health` on the target host before running
the repository Quick check. See [normalized results](../../benchmarks/results/README.md)
for retained measurements and limitations.

The Gemma profile binds to loopback by default and serves the canonical model
name. Set host, port, cache path, and scheduler limits explicitly for your host.
Keep speculative decoding and scheduler changes separate when comparing runs.
