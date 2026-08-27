# LLM Inference Lab

[English](README.md) | 한국어

단일 노드 LLM 추론을 위한 서빙 설정, 벤치마크 클라이언트, 측정 결과를
관리하는 저장소입니다.

서빙 예제를 실행하고, OpenAI 호환 엔드포인트를 점검하거나, 기록된 성능 비교를
살펴볼 수 있습니다. 현재 프로필과 결과는 **DGX Spark / GB10**을 중심으로
구성되어 있습니다.

[빠른 시작](#빠른-시작) · [문서](#문서) · [벤치마크 결과](#벤치마크-결과)

## 주요 기능

- **서빙 설정** — vLLM·SGLang·Ollama 예제와 SparkRun 실행 레시피
- **API 호환성 점검** — 모델 조회, 텍스트 생성, 스트리밍, 도구 호출 스키마 검증
- **성능 측정** — 첫 토큰 지연시간(TTFT), 첫 토큰을 제외한 출력 토큰당 생성
  시간(TPOT), 출력 처리량 측정과 별도의 지속 부하 측정 도구
- **설정 비교** — 스케줄러 제한, eager/compiled 실행, 양자화, 추측 디코딩 설정
- **추적 가능한 결과** — 원본 해시·비교 그룹이 포함된 검토 결과와 버전이 있는
  JSON에서 생성하는 정적 리더보드

## 구조 한눈에 보기

![서빙 설정과 사용자 실행 서버, API·성능 측정 도구, 검토 결과와 리더보드로 구성된 프로젝트 개요](docs/assets/project-overview.svg)

점선 상자의 엔드포인트는 사용자가 준비하고 실행합니다. 실제 가동 현황이 아닌
저장소 구성도입니다. 현재 importer는 검토한 Quick 결과만 정규화하며,
과거 smoke 기록은 순위에서 제외하고 지속 부하 결과는 별도로 관리합니다.
[상세 근거 흐름](benchmarks/results/README.md#evidence-flow)과
[공통 그림의 Mermaid 원본](README.md#architecture-at-a-glance)을 참고하세요.

## 빠른 시작

### 준비 사항

- 아래 절차에 사용할 Python 3와 Git. Quick 클라이언트는 Python 표준
  라이브러리만 사용하므로 별도 Python 패키지를 설치할 필요가 없습니다.
- 모델 조회, 스트리밍 토큰 사용량을 반환하는 Chat Completions, 도구 호출을
  지원하는 실행 중인 엔드포인트
- 예제 명령을 실행할 Bash 호환 셸(Linux 또는 WSL 등)

모델 서버부터 시작해야 한다면 [서빙 가이드](#문서)를 선택하세요.
기록된 결과를 살펴보는 데는 서버가 필요하지 않습니다.

### 엔드포인트 점검

저장소를 복제한 뒤 `your-served-model`을 엔드포인트가 제공하는 실제 모델
이름으로 바꿔 실행합니다.

```bash
git clone https://github.com/bemaru/llm-inference-lab.git
cd llm-inference-lab

python3 benchmarks/openai-compatible/quick_check.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model your-served-model \
  --performance-prompt-profile sequential-integers
```

점검 결과와 성능 지표가 JSON으로 출력됩니다. 종료 코드가 0이 아니면 점검
실패 또는 실행 오류입니다. 기존 엔드포인트를 호출하는 명령이며, 모델 서버를
기동하거나 가중치를 내려받지는 않습니다.

기본 요청에는 vLLM의 `chat_template_kwargs`가 포함됩니다. 이 필드를 받지
않는 서버에서는 `--omit-chat-template-kwargs`와 해당 런타임의
reasoning(생각 모드) 제어 옵션을 사용합니다.
[런타임별 실행 예제](benchmarks/openai-compatible/README.md#quick-check)를 참고하세요.

`--output`으로 보고서를 저장하고, `--metadata-file`로 실제 아티팩트·런타임·
워크로드를 기록한 뒤 비교 결과로 보존합니다. 원본 보고서에는 응답과 호스트
정보가 포함될 수 있으므로 Git 밖에 보관합니다.

Quick은 후보 선별용 점검입니다. [지속 부하 성능 측정(Characterization)](benchmarks/openai-compatible/README.md#standard-characterization)은
별도의 선택 작업이며, 기본 실행 일정은 워밍업을 제외하고 약 210분입니다.

## 문서

| 하려는 일 | 가이드 |
|---|---|
| 모델 서버 실행 | [vLLM](engines/vllm/README.md) · [SGLang](engines/sglang/README.md) · [Ollama](engines/ollama/README.md) · [SparkRun](engines/sparkrun/README.md) |
| 모델별 주의사항 확인 | [Gemma](models/gemma/README.md) · [Qwen](models/qwen/README.md) |
| DGX Spark 준비 | [호스트·터널 설정](hardware/dgx-spark/README.md) |
| 엔드포인트 측정 | [벤치마크 클라이언트](benchmarks/openai-compatible/README.md) · [측정 규칙](benchmarks/README.md) |
| 결과 확인·가져오기 | [결과 스키마·비교 규칙](benchmarks/results/README.md) · [리더보드 안내](leaderboards/README.md) |
| 실험 기록 작성 | [실행 기록 템플릿](templates/run-log.md) |
| 설계 배경 확인 | [설계 결정](docs/adr/README.md) · [조사 기록](docs/research/README.md) |
| 실험 추적(선택) | [MLflow 연동·로컬 예제](tracking/mlflow/README.md) |

호스트, 모델 접근 권한, 캐시 경로, 자격 증명은 자신의 환경에 맞게 준비합니다.
모델·런타임 아티팩트를 사용하거나 재배포하기 전에 제공자의 이용·재배포 조건을
확인하세요. MLflow는 클라이언트 실행, 결과 열람, 리더보드 생성에 필수가
아닙니다. 실험 기록 연동은 이 저장소에서, 공유 서버의 배포·인증·백업은
서버 소유자의 운영 저장소에서 관리합니다. 상세 가이드는 현재 영어와 한국어를
함께 사용합니다.

## 벤치마크 결과

[DGX Spark 결과 모음](benchmarks/results/dgx-spark.json)에는 검토된 Quick·smoke
기록이 있습니다. 아래 사례는 서로 다른 질문을 다루며, 모든 모델·런타임을
하나의 순위로 비교한 결과가 아닙니다.

| 실험 | 기록에서 확인한 내용 | 근거 |
|---|---|---|
| Gemma 4 스케줄러·실행 모드 | 시퀀스 제한과 eager/compiled 실행을 비교했습니다. 처리량이 높아져도 TTFT가 항상 낮아지지는 않았습니다. | [비교 해설과 측정 조건](benchmarks/results/gemma4-scheduler.md#한국어) |
| Qwen3.6 MTP on/off | 합성 출력의 디코딩 성능 상승과 가속기 메모리 할당 증가를 함께 관찰했습니다. | [Quick 기록](benchmarks/results/dgx-spark.json) |
| SGLang MTP·DSpark·DFlash2 | DSpark/DFlash2 기록은 생성 토큰 수와 종료 사유가 달라 출력 처리량 순위에서 제외했습니다. | [기록](benchmarks/results/dgx-spark.json) · [실행 구성](engines/sglang/README.md#qwen38-27b-nvfp4-speculative-recipes) |
| 모델–런타임 호환성 | EXAONE 4.5 AWQ의 중첩 도구 호출 실패는 부분 통과로 구분했고, 별도의 실행 차단 기록도 보존했습니다. | [Quick·smoke 기록](benchmarks/results/dgx-spark.json) |
| Nemotron 동시성별 부하 | 요청 동시성 1~32의 7개 지점에서 각각 60초씩 1회 측정했습니다. 지속 부하 기준선 측정을 완료한 결과가 아닌 예비 측정입니다. | [별도 예비 측정 기록](benchmarks/results/records/20260822-nemotron35-curve-preview01.json) |

시각적으로 비교하려면 로컬 체크아웃의
[`leaderboards/dgx-spark.html`](leaderboards/dgx-spark.html)을 브라우저로 엽니다.
GitHub에서는 실행 화면이 아니라 HTML 소스가 표시됩니다.
[리더보드 안내](leaderboards/README.md)를 참고하세요.

### 해석 시 주의사항

- 같은 비교 그룹 안에서도 측정 조건이 호환되는 실행끼리 비교합니다.
  Quick·smoke·예비 측정은 배포 권고나 공식 MLPerf 결과가 아닙니다.
- 처리량과 도구 호출 스키마 통과율은 답변 품질을 보장하지 않습니다.
  런타임이나 실행 설정을 바꾸면 해당 구성의 품질을 별도로 평가해야 합니다.
- 미측정·실행 차단 값은 0이 아닙니다. 원본 해시는 근거의 동일성을 식별하지만,
  공개되지 않은 원본 실행에 접근할 수 있게 해주지는 않습니다.
- 재측정에는 자신의 엔드포인트와 일치하는 조건이 필요합니다. 모델 가중치,
  원본 프롬프트·응답, 자격 증명, 호스트별 실행 로그는 포함하지 않습니다.

## 로컬 검증

저장소 루트에서 모델 서버를 시작하지 않고 실행합니다. MLflow 클라이언트
테스트는 모의 도구(mock)를 사용하며, MLflow 서비스를 시작하거나 접속하지 않습니다.

```bash
python3 -m unittest discover -s benchmarks/openai-compatible/tests -p 'test_*.py'
python3 -m unittest discover -s leaderboards -p 'test_*.py'
bash tracking/mlflow/tests/local_client_test.sh
python3 leaderboards/build.py --check
```
