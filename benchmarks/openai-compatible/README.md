# OpenAI-Compatible Benchmark Clients

아래 명령은 저장소 루트에서 실행한다. metadata 파일은 로컬 환경에 맞게 준비한다.

## Quick Check

OpenAI-compatible endpoint의 기본 생성, streaming 지연·처리량과 Tool Calling을
외부 Python 패키지 없이 빠르게 검증한다. 이 결과는 후보 선별용 `quick` 실행이며,
정식 baseline이나 MLPerf 결과가 아니다.

서버와 같은 호스트에서 실행하는 예:

```bash
python3 benchmarks/openai-compatible/quick_check.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model qwen3.6-35b-a3b-nvfp4
```

기본 검증 범위:

- 모델 조회와 reasoning-off chat
- 2회 warm-up 후 streaming 3회 TTFT, TPOT, decode TPS
- concurrency 2 closed-loop aggregate output TPS
- 단순, 중첩, 32개 도구 표면의 Tool Calling

도구 호출 안정성을 반복 확인할 때는 `--tool-runs 5`처럼 횟수를 지정한다.

런타임별 비표준 필드를 통제해야 할 때는 명시적으로 기록한다. Ollama처럼
OpenAI-compatible `reasoning_effort`를 지원하지만 vLLM 전용
`chat_template_kwargs`를 받지 않는 엔진은 다음과 같이 실행한다.

```bash
python3 benchmarks/openai-compatible/quick_check.py \
  --base-url http://127.0.0.1:11434/v1 \
  --model gemma4:26b-a4b-it-q4_K_M \
  --reasoning-effort none \
  --omit-chat-template-kwargs \
  --performance-prompt-profile sequential-integers
```

기본 `repeated-word` 성능 프롬프트와 다른 프로필은 동일 비교 그룹에 섞지
않는다. 출력 JSON의 `request_settings`에 실제 요청 조건이 포함된다.

## 결과 보존

[`result.schema.json`](result.schema.json)은 개별 Quick 실행의 원본 결과 계약이다.
`--output`은 완료 여부와 측정값을 하나의 JSON 문서로 원자적으로 저장한다.
`{run_id}`는 실제 실행 ID로 치환된다.
실행 종료 시 `/proc/meminfo`와 `nvidia-smi`에서 호스트 메모리, accelerator 상태와
compute process 메모리 스냅샷도 함께 기록한다.

```bash
python3 benchmarks/openai-compatible/quick_check.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model served-model-name \
  --run-id 20260821-example-quick \
  --metadata-file metadata.json \
  --output 'artifacts/quick/{run_id}/result.json'
```

재현 가능한 실행으로 보존할 때는
[`metadata.example.json`](metadata.example.json)을 복사해 하드웨어, 모델 artifact,
서빙 image와 옵션, software 및 Git provenance를 실제 값으로 채운다. metadata가
없어도 임시 진단은 실행할 수 있지만 결과의 `metadata_status`는
`not_provided`가 된다.

DGX Spark에서 실행하고 JSON은 로컬에 보존하려면 wrapper를 사용한다.

```bash
benchmarks/openai-compatible/run-remote \
  --host your-host \
  --metadata-file /path/to/metadata.json \
  --output artifacts/quick/20260821-example-quick/result.json \
  -- \
  --base-url http://127.0.0.1:8000/v1 \
  --model served-model-name \
  --run-id 20260821-example-quick \
  --timeout 300 --warmup 2 --stream-runs 3 \
  --concurrency 2 --concurrent-requests 4 \
  --max-tokens 256 --tool-runs 6
```

`artifacts/`의 원본에는 응답 내용이 포함될 수 있으므로 Git에서 제외한다.
검토된 수치와 provenance만 `benchmarks/results/dgx-spark.json`으로 정규화해
리더보드 입력으로 사용한다.

## Standard Characterization

[`characterize.py`](characterize.py)는 OpenAI-compatible endpoint를 대상으로
고정 동시성 operating-point curve를 측정한다. 기본값은 다음 저장소 정책을
충족하도록 설정되어 있다.

- 동시성 7개 지점: `1,2,4,8,16,24,32`
- 지점당 600초
- 전체 curve 3회 반복
- streaming TTFT, E2E, TPOT 및 실제 input/output/reasoning token 기록
- system output TPS, 사용자당 output TPS, 성공률과 반복 간 95% 신뢰구간 집계

기본 실행은 warm-up을 제외하고 약 210분이 필요하다. 모델·양자화·runtime·서빙
옵션은 실행 중 변경하지 않는다. 정식 분류에는 metadata와 해당 구성의 품질 gate
근거가 필요하다.

```bash
python3 benchmarks/openai-compatible/characterize.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model served-model-name \
  --metadata-file metadata.json \
  --quality-gate-ref docs/or-result-id \
  --run-id 20260822-example-standard \
  --output 'artifacts/characterization/{run_id}/result.json'
```

Spark localhost에서 client를 실행하고 결과를 현재 저장소로 회수할 때는 wrapper를
사용한다. 원격 인자에는 `--output`을 넣지 않는다.

```bash
benchmarks/openai-compatible/run-characterization-remote \
  --host your-host \
  --metadata-file metadata.json \
  --output artifacts/characterization/20260822-example-standard/result.json \
  -- \
  --base-url http://127.0.0.1:8000/v1 \
  --model served-model-name \
  --quality-gate-ref docs/or-result-id \
  --run-id 20260822-example-standard
```

실행기와 endpoint의 호환성만 짧게 확인할 때는 비표준 조건임을 명시한다.
이 결과는 `characterization-preview`로 기록되며 정식 baseline이 아니다.

```bash
python3 benchmarks/openai-compatible/characterize.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model served-model-name \
  --concurrency-points 1,2 \
  --duration-s 10 \
  --repetitions 1 \
  --allow-nonstandard \
  --output 'artifacts/characterization/{run_id}/result.json'
```

기본 workload는
[`workloads/standard-v1.json`](workloads/standard-v1.json)에 고정하며, 원본의
SHA-256과 seed를 결과에 기록한다. prompt와 생성 내용은 결과에 저장하지 않는다.
개별 요청에는 case ID, 토큰 수, 지연, 종료 사유와 오류만 남긴다.
`--output`을 사용하면 stdout에는 요약만 출력한다. 전체 결과를 stdout에도
출력해야 할 때만 `--print-result`를 추가한다.

결과 계약은 [`characterization.schema.json`](characterization.schema.json)이다.
표기는 `MLPerf Endpoints-derived / custom workload / unverified`이며 공식 MLPerf
결과를 의미하지 않는다. open-loop Poisson 및 offline 측정은 별도 track으로
관리한다.
