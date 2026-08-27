# Benchmarks

재현 가능한 LLM 추론 benchmark 설정, 실행 도구와 결과 집계 규칙을 관리한다.

## 기본 원칙

- 기능과 품질 gate를 통과한 구성만 성능 baseline으로 사용한다.
- MLPerf의 정확도·시나리오 분리 원칙을 참고하되 공식 대상 모델과 절차가 아니면 MLPerf 결과라고 표기하지 않는다.
- interactive streaming, closed-loop concurrency, open-loop request rate를 서로 다른 결과로 관리한다.
- quick run은 도구와 경향 확인용이며 baseline으로 승격하지 않는다.
- client 관측값과 inference server metric을 함께 보존한다.

## 필수 실행 정보

- hardware topology와 accelerator 수
- OS, driver, firmware, runtime과 benchmark tool version
- model ID, artifact ID, quantization format과 tokenizer revision
- server command와 reasoning·cache·scheduler 설정
- input/output token 분포, streaming, concurrency 또는 arrival rate
- warm-up, 요청 수 또는 측정 시간, 반복 횟수, random seed
- 실행 위치와 network path

## 필수 metric

| 구분 | Metric |
|---|---|
| Latency | TTFT, TTFO, ITL/TPOT, end-to-end latency의 p50·p90·p95·p99 |
| Throughput | output tokens/s, requests/s, per-user tokens/s, SLA goodput |
| Tokens | 실제 input, output, reasoning token 분포와 truncation 비율 |
| Scheduler | running/waiting request, queue, concurrency |
| Cache | KV-cache usage, prefix-cache hit/query |
| Resource | host·accelerator memory, utilization, temperature, power |
| Reliability | success, length-stop, error, timeout, cancel, abort |
| Quality | rubric score, pass rate, critical failure category |

## 측정 규칙

- cold start와 warm steady state를 분리한다.
- TTFT·TTFO·ITL은 streaming 요청으로 측정한다.
- closed-loop는 concurrency 포화 특성을, open-loop는 Poisson request rate와 SLA goodput을 측정한다.
- 정식 baseline은 동일 seed로 profile run 3회 이상과 95% 신뢰구간을 기록한다.
- 평균만으로 판정하지 않고 tail latency와 실패율을 함께 본다.
- tunnel을 거친 end-to-end 결과와 server localhost 결과를 직접 비교 가능한 동일 계층의 수치로 취급하지 않는다.
- power는 측정 경계가 장치인지 전체 시스템인지 명시한다.

모델별 설정과 rubric은 각 하위 디렉터리에서 관리하고, raw artifact는 git에 커밋하지 않는다.

## 공통 도구

- [OpenAI-compatible quick check](openai-compatible/README.md): 기본 생성, streaming 처리량과 Tool Calling 후보 선별
- [OpenAI-compatible endpoint characterization](openai-compatible/README.md#standard-characterization): 7개 이상 고정 동시성 지점의 지속 부하 curve 측정

## 결과와 리더보드

- [`results/run-set.schema.json`](results/run-set.schema.json): 모델 artifact,
  양자화, runtime, 서빙 옵션, 검증 gate와 metric을 함께 기록하는 결과 계약
- [`results/dgx-spark.json`](results/dgx-spark.json): DGX Spark의 정규화된
  Quick·smoke 결과와 원본 근거 SHA-256
- [`../leaderboards/dgx-spark.html`](../leaderboards/dgx-spark.html): 같은
  comparison group 안에서만 순위를 부여하는 정적 HTML 리더보드

```bash
python3 leaderboards/build.py
python3 leaderboards/build.py --check
```

HTML은 projection이고, `results/*.json`에서 재생성한다. 비공개 실행 기록은
복제하지 않으며 근거의 SHA-256만 남긴다. Quick 결과는 정식 baseline이나 배포 결정으로 승격하지 않는다.
개별 원본은 `artifacts/`에 저장하고 `results/import_quick.py`로 검토된 run을
정규화한 뒤 HTML을 재생성한다.
