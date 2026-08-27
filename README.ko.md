# LLM Inference Lab

[English](README.md) | 한국어

단일 노드 LLM 추론·서빙 환경에서 성능 벤치마킹, 서빙 설정 튜닝,
모델–런타임 호환성을 검증하는 실험 저장소입니다. 서빙 예제, OpenAI 호환
벤치마크 클라이언트, 검토된 성능 기록을 함께 관리하며, 현재 예제는
**DGX Spark / GB10**을 중심으로 구성되어 있습니다.

실험에서 확인하는 질문은 다음과 같습니다.

- 모델과 런타임 조합이 기동·스트리밍·도구 호출 스키마 검증을 통과하는가?
- 스케줄러 설정과 컴파일·CUDA Graphs 실행이 처리량·지연시간에 어떤 차이를 만드는가?
- 어떤 측정끼리 비교할 수 있으며, 각 결과의 근거는 무엇인가?

## 구조 한눈에 보기

![벤치마크가 사용자 추론 서버를 호출해 로컬 결과를 남기고, 검토한 Quick 결과만 공개 요약과 정적 리더보드로 연결되는 흐름](docs/assets/benchmark-workflow.svg)

원본 결과는 Git 밖에 보관합니다. 현재 결과 가져오기 도구(importer)는
선별·검토한 Quick(후보 선별 점검) 결과를 리더보드용으로 정규화합니다.
과거 smoke test(기본 동작 점검) 기록은 구분하여 순위에서 제외하고,
지속 부하 성능 측정(Characterization) 결과는 별도 흐름으로 관리합니다.
두 README는 같은 그림을 사용하고,
[Mermaid 원본은 영문 README 한 곳](README.md#architecture-at-a-glance)에서 관리합니다.

## 대표 실험: Gemma 4 스케줄러와 실행 모드

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
| [Eager seq2](benchmarks/results/records/20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02.json) | 2 | `true` | 34.033 | 122 |
| [Eager seq4](benchmarks/results/records/20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-quick01.json) | 4 | `true` | 40.948 | 101 |
| [Compiled + CUDA Graphs (seq4)](benchmarks/results/records/20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-compiled-quick01.json) | 4 | `false` | 42.189 | 106 |

**조건:** 순차 정수 출력 프롬프트, 출력 한도 256토큰, 행마다 보존된 Quick 실행
1회입니다. 출력 토큰 처리량은 **요청 동시성 2(C2)에서 closed-loop 요청 4건**으로,
TTFT는 **단일 요청 스트리밍 표본 3회(C1)**로 측정했습니다.
서버의 `max_num_seqs`는 스케줄러의 한 처리 단계(iteration)에서 처리할
최대 시퀀스 수이며, 클라이언트의 요청 동시성과는 다른 설정입니다.

**관찰:** 이 기록에서는 Eager seq4의 출력 토큰 처리량이 Eager seq2보다 높습니다.
Compiled + CUDA Graphs (seq4)는 처리량이 조금 더 높지만, 기록된 TTFT p95는
Eager seq4보다 낮지 않습니다.
이 작은 표본으로 통계적으로 유의한 순위, 지속 부하 수용량, 답변 품질까지
판단할 수는 없습니다.

정확한 지표·리비전·원본 해시·비교 그룹은
[정규화 결과](benchmarks/results/dgx-spark.json)에서 확인할 수 있습니다.
각 행의 링크는 해당 실행을 설명하는 기록입니다. 특히 표본 3개의 p95는
꼬리 지연시간을 안정적으로 추정하기에 충분하지 않습니다.

## 시작하기

### 기존 결과 살펴보기 — 모델 서버 불필요

- [리더보드 안내](leaderboards/README.md)를 읽고, 로컬 체크아웃의
  [`leaderboards/dgx-spark.html`](leaderboards/dgx-spark.html)을 브라우저로 엽니다.
  GitHub에서는 실행 화면이 아니라 HTML 소스가 표시됩니다.
- [정규화 결과와 데이터 계약](benchmarks/results/README.md)을 확인합니다.
- 같은 비교 그룹 안에서도 측정 조건이 호환되는 실행끼리 비교합니다.

### 자신의 추론 API 측정하기

Python 3와 이미 실행 중인 OpenAI 호환 API 엔드포인트가 필요합니다.
저장소 루트에서, 모델 이름을 실제 엔드포인트가 제공하는 이름으로 바꿔 실행합니다.

```bash
python3 benchmarks/openai-compatible/quick_check.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model your-served-model \
  --performance-prompt-profile sequential-integers
```

이 명령은 기존 엔드포인트를 호출하며, 모델 서버를 기동하거나 가중치를 내려받지
않습니다. 클라이언트는 Python 표준 라이브러리를 사용합니다. 런타임별 요청 옵션,
메타데이터, `--output` 사용법은
[벤치마크 가이드](benchmarks/openai-compatible/README.md)를 참고하세요.
비교 결과를 보존하기 전에는 실제 아티팩트·런타임·워크로드(입력·부하 조건)를 기록합니다.

Quick은 모델·런타임 후보를 선별하는 점검입니다. 지속 부하 성능 측정
(Characterization)은 별도 선택 작업이며, 기본 실행 일정은 워밍업(warm-up)을
제외하고 약 210분입니다.

## 서빙 예제

- [vLLM](engines/vllm/README.md) — 단일 노드 프로필과 스케줄러 설정
- [SGLang](engines/sglang/README.md) — 서빙과 추측 디코딩(speculative decoding) 예제
- [Ollama](engines/ollama/README.md) — 로컬 서빙 예제
- [SparkRun](engines/sparkrun/README.md) — DGX Spark 실행 예제
- [DGX Spark 구성](hardware/dgx-spark/README.md) — 호스트와 터널 설정

호스트, 모델 접근 권한, 캐시 경로, 자격 증명은 자신의 환경에 맞게 준비합니다.
모델·런타임 아티팩트를 사용하거나 재배포하기 전에 제공자의 이용·재배포 조건을 확인하세요.

## 결과를 읽을 때

- 보존된 측정은 Quick 점검, smoke test 또는 Characterization 예비 측정입니다.
  배포 권고나 공식 MLPerf 결과가 아닙니다.
- 처리량과 도구 호출 스키마 통과율은 답변 품질을 보장하지 않습니다.
  런타임이나 실행 모드가 바뀌면 해당 구성의 품질을 별도로 평가해야 합니다.
- 미측정·실행 차단 값은 0이 아니며, 서로 다른 워크로드를 하나의 순위로 묶지 않습니다.
- 원본 해시는 근거의 동일성을 식별하지만, 공개되지 않은 원본 실행을 독립적으로
  재현할 수 있게 해주지는 않습니다. 재측정에는 자신의 엔드포인트와 일치하는 조건이
  필요합니다.
- 모델 가중치, 원본 프롬프트·응답, 자격 증명, 호스트별 실행 로그는 포함하지 않습니다.

## 선택 사항: 실험 추적

[로컬 MLflow 예제](tracking/mlflow/README.md)는 실험 메타데이터와 아티팩트를
추적할 때 선택적으로 사용할 수 있습니다. 결과 열람, 벤치마크 클라이언트 실행,
리더보드 생성에 **필수는 아닙니다**. 정규화 결과의 데이터 계약도 특정 추적
시스템에 종속되지 않습니다.

## 로컬 검증

모델 서버를 시작하지 않고, 저장소 루트에서 실행합니다.

```bash
python3 -m unittest discover -s benchmarks/openai-compatible/tests -p 'test_*.py'
python3 -m unittest discover -s leaderboards -p 'test_*.py'
bash tracking/mlflow/tests/local_client_test.sh
python3 leaderboards/build.py --check
```

[설계 결정](docs/adr/README.md), [조사 기록](docs/research/README.md),
[실행 기록 템플릿](templates/run-log.md)도 참고할 수 있습니다.
이 개요는 두 언어로 제공하며, 상세 문서는 현재 영어와 한국어를 함께 사용합니다.
