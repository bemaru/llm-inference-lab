# Gemma 4: Scheduler Settings and Execution Mode

[Project overview](../../README.md) | [프로젝트 개요](../../README.ko.md)

[English](#english) | [한국어](#한국어)

## English

**Question:** with the same model artifact and runtime, what changes when
`max_num_seqs` increases from 2 to 4, then `enforce_eager` is disabled?

The following retained runs were measured on **2026-08-25**, using Gemma 4
26B-A4B NVFP4 on DGX Spark, vLLM
`0.19.2rc1.dev134+gfe9c3d6c5.cu130`, and the same pinned model revision and
container image. NVFP4 here uses the **Marlin weight-only path**, not native
FP4 compute.

The table reports output token throughput and Time to First Token (TTFT).
The compiled configuration enables vLLM compilation and CUDA Graphs.

| Configuration | `max_num_seqs` | `enforce_eager` | Output token throughput (tokens/s, C2) | TTFT p95 (ms, C1) |
|---|---:|---|---:|---:|
| [Eager seq2](records/20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02.json) | 2 | `true` | 34.033 | 122 |
| [Eager seq4](records/20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-quick01.json) | 4 | `true` | 40.948 | 101 |
| [Compiled + CUDA Graphs (seq4)](records/20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-compiled-quick01.json) | 4 | `false` | 42.189 | 106 |

**Conditions:** sequential-integer output, 256-token limit, one retained Quick
run per row. Output token throughput uses **4 closed-loop requests at concurrency
2 (C2)**. TTFT uses **3 single-request streaming samples (C1)**. The server's
`max_num_seqs` limits the sequences processed per scheduler iteration; it is
not the client's request concurrency.

TTFT is observed at the benchmark client, with prefix caching enabled in all
three recorded configurations. The client repeats a synthetic prompt; cache-hit
rates and cache resets are not documented in the public summaries, so this is
not a verified cold-cache comparison.

**Observation:** Eager seq4 has higher output token throughput than Eager seq2
in these records. Compiled + CUDA Graphs (seq4) increases throughput slightly
further, but its recorded TTFT p95 is not lower than Eager seq4. These small
samples do not establish a statistically significant ranking, sustained
capacity, or answer quality.

See the [normalized result set](dgx-spark.json) for exact
metrics, revisions, source hashes, and comparison groups. The linked row
descriptors explain what each run represents. A p95 from only three samples
is not a robust estimate of tail latency.

With the [client's nearest-rank calculation](../openai-compatible/quick_check.py),
p95 for three samples equals the largest observed sample.

## 한국어

**질문:** 같은 모델 아티팩트와 런타임에서 `max_num_seqs`를 2에서 4로 늘리고,
이후 `enforce_eager`를 비활성화하면 무엇이 달라지는가?

아래는 **2026-08-25**에 DGX Spark에서 측정한 Gemma 4 26B-A4B NVFP4 결과입니다.
vLLM `0.19.2rc1.dev134+gfe9c3d6c5.cu130`과 동일하게 고정한 모델 리비전·컨테이너
이미지를 사용했습니다. 여기서 NVFP4 실행 경로는 네이티브 FP4 연산이 아닌
**Marlin 가중치 전용(weight-only) 경로**입니다.

표에는 출력 토큰 처리량과 첫 토큰 지연시간(Time to First Token, TTFT)을
표시합니다. 컴파일 구성은 vLLM 컴파일과 CUDA Graphs를 함께 사용합니다.

| 구성 | `max_num_seqs` | `enforce_eager` | 출력 토큰 처리량 (tokens/s, C2) | TTFT p95 (ms, C1) |
|---|---:|---|---:|---:|
| [Eager seq2](records/20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02.json) | 2 | `true` | 34.033 | 122 |
| [Eager seq4](records/20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-quick01.json) | 4 | `true` | 40.948 | 101 |
| [Compiled + CUDA Graphs (seq4)](records/20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-compiled-quick01.json) | 4 | `false` | 42.189 | 106 |

**조건:** 순차 정수 출력 프롬프트, 출력 한도 256토큰, 행마다 보존된 Quick 실행
1회입니다. 출력 토큰 처리량은 **요청 동시성 2(C2)에서 closed-loop 요청 4건**으로,
TTFT는 **단일 요청 스트리밍 표본 3회(C1)**로 측정했습니다.
서버의 `max_num_seqs`는 스케줄러의 한 처리 단계(iteration)에서 처리할
최대 시퀀스 수이며, 클라이언트의 요청 동시성과는 다른 설정입니다.

TTFT는 벤치마크 클라이언트에서 관측한 값이며, 세 구성 모두 prefix caching이
활성화된 것으로 기록되어 있습니다. 클라이언트는 합성 프롬프트를 반복 사용하지만,
공개 요약에는 캐시 적중률과 초기화 여부가 기록되어 있지 않으므로 캐시가 비어 있는
상태(cold cache)를 통제한 비교로 해석할 수는 없습니다.

**관찰:** 이 기록에서는 Eager seq4의 출력 토큰 처리량이 Eager seq2보다 높습니다.
Compiled + CUDA Graphs (seq4)는 처리량이 조금 더 높지만, 기록된 TTFT p95는
Eager seq4보다 낮지 않습니다.
이 작은 표본으로 통계적으로 유의한 순위, 지속 부하 수용량, 답변 품질까지
판단할 수는 없습니다.

정확한 지표·리비전·원본 해시·비교 그룹은
[정규화 결과](dgx-spark.json)에서 확인할 수 있습니다.
각 행의 링크는 해당 실행을 설명하는 기록입니다. 특히 표본 3개의 p95는
꼬리 지연시간을 안정적으로 추정하기에 충분하지 않습니다.

[클라이언트의 nearest-rank 계산 방식](../openai-compatible/quick_check.py)에서는
표본이 3개일 때 p95가 관측된 최댓값과 같습니다.
