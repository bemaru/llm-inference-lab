# Qwen

Qwen-specific serving notes.

Initial focus:

- Qwen3.6 35B-A3B NVFP4 on DGX Spark
- Qwen 27B FP8 serving
- reasoning mode behavior and serving settings
- memory and throughput comparison against Gemma-class models

The first Qwen3.6 NVFP4 run is an MTP-off baseline. The current profile uses 32K context, two sequences, FP8 KV cache, Marlin MoE, FlashInfer attention, and thinking disabled. MTP is evaluated later as a single-variable change.
