# Ollama

Notes for Ollama and GGUF-based local LLM serving.

Use this area to compare practical memory and operational differences against vLLM or SGLang using Hugging Face checkpoints.

## Gemma4 26B-A4B Q4_K_M on DGX Spark

The single-node profile uses a host-cached Ollama model and binds the API to the
remote loopback. Credentials and SSH aliases are not stored in this repository.

```bash
DOCKER_HOST=ssh://your-host \
OLLAMA_MODELS=/home/your-user/.ollama \
docker compose \
  -f engines/ollama/docker-compose.single-node.yml \
  --profile gemma4-q4-k-m up -d --pull never \
  ollama-gemma4-26b-q4-k-m
```

Verify the cached model and loaded context:

```bash
DOCKER_HOST=ssh://your-host docker exec ollama-gemma4-26b-q4-k-m ollama list
DOCKER_HOST=ssh://your-host docker exec ollama-gemma4-26b-q4-k-m ollama ps
```

The measured profile uses:

- `gemma4:26b-a4b-it-q4_K_M`;
- Ollama `0.23.1` with 32K context and two parallel request slots;
- one loaded model, 30-minute keep-alive, and Flash Attention;
- OpenAI-compatible `reasoning_effort=none` requests.

Stop only this profile with:

```bash
DOCKER_HOST=ssh://your-host \
OLLAMA_MODELS=/home/your-user/.ollama \
docker compose \
  -f engines/ollama/docker-compose.single-node.yml \
  --profile gemma4-q4-k-m stop ollama-gemma4-26b-q4-k-m
```

See [normalized results](../../benchmarks/results/README.md)
for the exact workload, compatibility boundary, and measurements.
