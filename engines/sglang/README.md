# SGLang

Serving recipes and benchmark evidence for SGLang.

## Qwen3.8 27B NVFP4 speculative recipes

`scripts/serve-qwen38-27b-nvfp4` provides the three DGX Spark recipes verified
on 2026-08-21: MTP, DSpark, and DFlash2. It pins the target and draft revisions,
the released base-image digest, context length, cache types, CPU affinity, and
the concurrency-two capacity used in the Quick comparison.

```bash
export DOCKER_HOST=ssh://your-host
engines/sglang/scripts/serve-qwen38-27b-nvfp4 mtp
engines/sglang/scripts/serve-qwen38-27b-nvfp4 dspark
engines/sglang/scripts/serve-qwen38-27b-nvfp4 dflash2
```

Only one recipe may bind DGX Spark port 8000 at a time. The script does not
replace an existing named container. Stop and remove the exact recipe
container before starting it again:

```bash
DOCKER_HOST=ssh://your-host docker stop llm-lab-sglang-qwen38-nvfp4-mtp
DOCKER_HOST=ssh://your-host docker rm llm-lab-sglang-qwen38-nvfp4-mtp
```

The MTP and DSpark modes use the released ARM64 image digest recorded in the
serving script. DFlash2 requires a locally built image because the tested
implementation was not present in that image. Build it on DGX Spark from the
pinned community integration repository:

```bash
ssh your-host
git clone https://github.com/MiaAI-Lab/Qwen3.8-27B-SGLang-DGX-Spark \
  /tmp/qwen38-dflash-c90d8c34
git -C /tmp/qwen38-dflash-c90d8c34 checkout \
  c90d8c34cf795185ee8de736b7ded9bca3fe0de1
docker pull \
  lmsysorg/sglang@sha256:3c0abdf41ef22de9d7a859dc16ed71eae69452e36c91f071a25e60c85a6d1fc6
docker tag \
  lmsysorg/sglang@sha256:3c0abdf41ef22de9d7a859dc16ed71eae69452e36c91f071a25e60c85a6d1fc6 \
  lmsysorg/sglang:qwen38-27b
/tmp/qwen38-dflash-c90d8c34/patch/build-dflash2-image.sh --full
```

The build overlays upstream SGLang commit
`c14312a66420b75ca9a11bf1817c4db1fa26b097` and the repository's NVFP4 head
patch. Review the external repository and patch before rebuilding.

Run the common Quick check from the repository root after the health endpoint
responds:

```bash
ssh your-host python3 - \
  --base-url http://127.0.0.1:8000/v1 \
  --model qwen3.8-27b-nvfp4-sglang-dflash2 \
  --timeout 300 --warmup 2 --stream-runs 3 \
  --concurrency 2 --concurrent-requests 4 \
  --max-tokens 256 --tool-runs 6 \
  < benchmarks/openai-compatible/quick_check.py
```

Change the served model suffix to `mtp` or `dspark` for the other modes. See
[normalized results](../../benchmarks/results/README.md)
for the measured results and interpretation limits.
