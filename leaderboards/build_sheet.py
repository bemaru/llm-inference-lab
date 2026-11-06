#!/usr/bin/env python3
"""Build the Korean DGX Spark summary spreadsheet and publish it to Google Sheets.

The repository JSON stays the source of truth. The spreadsheet is a generated,
one-way view: a refresh replaces the generated tabs, so edits made directly in
the spreadsheet are overwritten.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leaderboards.build import DEFAULT_DATA, validate_data  # noqa: E402

PREVIEW_RECORD = ROOT / "benchmarks" / "results" / "records" / "20260822-nemotron35-curve-preview01.json"
REPO_URL = "github.com/bemaru/llm-inference-lab"
MAX_ROW = 200  # run-table formulas scan rows 2..MAX_ROW
BATCH_BYTES = 100_000  # keeps each gws --json argument under the OS per-argument limit

TITLES = {"summary": "요약", "runs": "실행기록", "groups": "비교그룹", "terms": "용어설명"}
ORDER = ("summary", "runs", "groups", "terms")
STAGING = " (갱신 중)"
SPREADSHEET_PROPERTIES = {"locale": "ko_KR", "timeZone": "Asia/Seoul"}
BODY_FONT_SIZE = 11  # set per cell: the API accepts but ignores defaultFormat changes
FORMULA_ERRORS = {"#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#ERROR!", "#NUM!", "#NULL!"}

STATUS = {"pass": "통과", "partial": "부분 통과", "blocked": "실행 불가"}
PROMOTION = {"advance": "다음 단계", "control": "비교 기준", "reference": "참고",
             "reject": "탈락", "blocked": "실행 불가", "historical": "과거 기록"}
SPEC = {"off": "끔", "mtp": "MTP", "external-draft": "외부 draft 모델"}
QUALITY = {"not_run": "미측정"}
CLASS = {"quick": "Quick", "smoke": "Smoke", "characterization-preview": "Characterization 예비"}
CLASS_ORDER = {"quick": 0, "characterization-preview": 1}
LEVEL = {"directional": "방향성 비교", "not_comparable": "비교 불가", "not_ranked": "순위 제외"}

# The preview record has no group definition in dgx-spark.json; these values
# restate the record and benchmarks/results/README.md.
PREVIEW_GROUP_ID = "dgx-spark-characterization-preview-2026-08"
PREVIEW_GROUP = {
    "label": "Nemotron 동시성별 지속 부하 예비 측정 · 2026-08-22",
    "classification": "characterization-preview",
    "comparison_level": "not_ranked",
    "workload": "DGX Spark localhost vLLM NVFP4 DSpark, 동시성 1~32 사이 7개 고정 지점, 지점당 60초, 1회 반복",
    "limitations": ["1회 반복, 지점당 60초 예비 측정이며 표준 순위 대상이 아닙니다.",
                    "한국어 답변 품질은 평가하지 않았습니다."],
}
PREVIEW_C2 = re.compile(r"Concurrency 2 produced .*? at ([0-9.]+) output tok/s")

# (header, width in pixels); widths follow the layout tuned by hand in the published sheet.
RUN_COLUMNS = [
    ("실행 ID", 420), ("측정일", 82), ("비교 그룹", 303), ("판정", 90), ("상태", 90), ("순위 대상", 53), ("그룹 내 순위", 67),
    ("모델", 230), ("구조", 80), ("총 파라미터 (B)", 64), ("활성 파라미터 (B)", 64), ("양자화", 212), ("엔진", 61),
    ("엔진 버전", 160), ("추측 디코딩", 98), ("draft 수락률 (%)", 64), ("처리량 C2 (tok/s)", 67),
    ("단일 사용자 decode p50 (tok/s)", 94), ("TTFT p50 (ms)", 60), ("TTFT p95 (ms)", 60), ("TPOT p50 (ms)", 63),
    ("E2E p50 (s)", 52), ("요청 처리량 (req/s)", 68), ("GPU 프로세스 메모리 (MiB)", 76), ("GPU 프로세스 메모리 (GiB)", 76),
    ("GPU 메모리 할당 비율", 80), ("동시 시퀀스 상한", 64), ("호스트 여유 메모리 (GiB)", 64), ("Tool calling 통과", 63),
    ("Tool calling 시도", 63), ("답변 품질", 52), ("비고", 494), ("result_sha256", 517),
    ("source_record_sha256", 522), ("그룹·순위 키", 319),
]
RUN_HEADERS = [name for name, _ in RUN_COLUMNS]
RUN_NUMBER_FORMATS = {
    "처리량 C2 (tok/s)": "0.0", "단일 사용자 decode p50 (tok/s)": "0.0", "TTFT p50 (ms)": "0",
    "TTFT p95 (ms)": "0", "TPOT p50 (ms)": "0.0", "E2E p50 (s)": "0.00", "요청 처리량 (req/s)": "0.000",
    "GPU 프로세스 메모리 (MiB)": "#,##0", "GPU 프로세스 메모리 (GiB)": "0.0",
    "draft 수락률 (%)": "0.00", "GPU 메모리 할당 비율": "0.00",
}
RUN_NUMERIC = [
    "총 파라미터 (B)", "활성 파라미터 (B)", "draft 수락률 (%)", "처리량 C2 (tok/s)",
    "단일 사용자 decode p50 (tok/s)", "TTFT p50 (ms)", "TTFT p95 (ms)", "TPOT p50 (ms)", "E2E p50 (s)",
    "요청 처리량 (req/s)", "GPU 프로세스 메모리 (MiB)", "GPU 프로세스 메모리 (GiB)", "GPU 메모리 할당 비율",
    "동시 시퀀스 상한", "호스트 여유 메모리 (GiB)", "Tool calling 통과", "Tool calling 시도",
]
RUN_CENTERED = ["판정", "상태", "순위 대상", "그룹 내 순위"]
RUN_CLIPPED = ["모델", "양자화", "엔진 버전", "비고"]
RUN_FOLDED = ("result_sha256", "그룹·순위 키")

Holds = Callable[[float, float], bool]
# Each finding compares one metric between run A and run B. `holds` restates
# the sentence's claim so --check fails when new data contradicts the text.
FINDINGS: list[tuple[str, str, str, str, Holds]] = [
    ("후보 1순위는 Nemotron 3.5 Lightning(NVFP4 + DSpark, vLLM)입니다. Quick 처리량이 2위 Qwen3.6 MTP의 2배가 넘고 "
     "tool calling 18/18을 통과했습니다. 모델 카드 지원 언어에 한국어가 없어 한국어 품질 검증이 다음 단계입니다.",
     "20260821-qwen36-nvfp4-mtp-n3", "20260821-nemotron35-nvfp4-dspark-n3", "처리량 C2 (tok/s)",
     lambda a, b: b / a > 2),
    ("Quick 수치는 실제보다 낙관적입니다. 같은 Nemotron 구성의 지속 부하 예비 측정에서 동시성 2 처리량은 Quick의 절반 수준이었습니다. "
     "Quick의 반복 토큰 출력이 draft 수락률을 99%대로 높입니다. workload가 달라 직접 비교는 아닙니다.",
     "20260821-nemotron35-nvfp4-dspark-n3", "20260822-nemotron35-curve-preview01", "처리량 C2 (tok/s)",
     lambda a, b: b / a < 0.6),
    ("활성 파라미터가 약 3B인 MoE 모델이 dense 27B보다 단일 사용자 decode가 몇 배 빠릅니다. "
     "엔진 버전과 양자화가 달라 통제된 비교는 아닙니다.",
     "20260821-qwen38-fp8-mtp-n3", "20260821-qwen36-nvfp4-mtp-n3", "단일 사용자 decode p50 (tok/s)",
     lambda a, b: b / a > 3),
    ("Qwen3.6에서 MTP를 켜면 단일 사용자 decode가 2배 이상 빨라졌습니다.",
     "20260821-qwen36-nvfp4-mtp-off", "20260821-qwen36-nvfp4-mtp-n3", "단일 사용자 decode p50 (tok/s)",
     lambda a, b: b / a >= 2),
    ("대신 Qwen3.6 MTP는 GPU 메모리를 22 GiB 넘게 더 썼습니다.",
     "20260821-qwen36-nvfp4-mtp-off", "20260821-qwen36-nvfp4-mtp-n3", "GPU 프로세스 메모리 (GiB)",
     lambda a, b: b - a > 22),
    ("EXAONE 4.5는 MTP를 켜면 draft 수락률이 0.09%에 그쳐 오히려 느려졌습니다. MTP 효과는 모델마다 측정해야 합니다.",
     "20260821-exaone45-awq-mtp-off", "20260821-exaone45-awq-mtp-n3", "처리량 C2 (tok/s)",
     lambda a, b: b < a),
    ("Gemma4 NVFP4에서 max_num_seqs를 2에서 4로만 바꿔도 처리량이 약 20% 늘었고 메모리 증가는 30 MiB였습니다.",
     "20260825-gemma4-26b-a4b-nvfp4-vllm-baseline02", "20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-quick01",
     "처리량 C2 (tok/s)", lambda a, b: 1.15 < b / a < 1.25),
    ("eager에서 compiled(CUDA Graphs)로 바꾸면 처리량은 조금 더 올랐습니다.",
     "20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-quick01", "20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-compiled-quick01",
     "처리량 C2 (tok/s)", lambda a, b: b > a),
    ("하지만 compiled의 TTFT p95는 eager seq4보다 낮아지지 않았습니다. 표본이 3개라 p95는 최댓값과 같습니다.",
     "20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-quick01", "20260825-gemma4-26b-a4b-nvfp4-vllm-seq4-compiled-quick01",
     "TTFT p95 (ms)", lambda a, b: b >= a),
]
RISK_FINDING = ("가장 큰 리스크는 속도가 아니라 모델과 런타임의 호환성입니다. Gemma4 NVFP4는 vLLM 0.27.1에서 서버가 뜨지 않았고, "
                "EXAONE은 중첩 tool call이 6번 모두 실패했고, DFlash2의 초기 66.8 tok/s는 재측정에서 재현되지 않았습니다.")
UNKNOWN_TEXT = [
    "이 repo의 실행은 속도와 API 동작만 측정했고, 한국어를 포함한 답변 품질은 측정하지 않았습니다. "
    "제품 연동 품질 평가(eval)는 이 repo 범위가 아니며 각 제품 저장소에서 관리합니다.",
    "모든 측정이 1회이고, 지속 부하 측정은 Nemotron 예비 측정 1건뿐입니다. 해당 서빙 프로필"
    "(nemotron35-lightning-nvfp4-vllm-dspark)의 max_num_seqs가 2라서 동시 시퀀스 3개 이상의 용량은 측정되지 않았습니다.",
]
TERMS = [
    ("처리량 C2 (tok/s)", "동시에 요청 2개를 보내는 closed-loop 측정에서 서버가 낸 초당 출력 토큰 수. Quick 그룹의 순위 기준입니다."),
    ("단일 사용자 decode p50 (tok/s)", "요청 하나만 보낼 때 첫 토큰 이후 초당 생성 토큰 수의 중앙값. 사용자 한 명이 체감하는 출력 속도입니다."),
    ("TTFT", "Time to First Token. 요청을 보낸 뒤 첫 토큰을 받기까지 걸린 시간입니다."),
    ("TPOT", "Time per Output Token. 첫 토큰을 제외한 출력 토큰 하나당 생성 시간입니다."),
    ("p50 / p95", "측정값의 중앙값과 95번째 백분위 값. Quick은 표본이 3개라 p95가 최댓값과 같습니다."),
    ("추측 디코딩 (speculative decoding)", "작은 draft 모델이나 추가 헤드가 토큰 여러 개를 미리 제안하고 본 모델이 한 번에 검증하는 방식입니다."),
    ("MTP", "Multi-Token Prediction. 모델에 내장된 추가 헤드로 다음 토큰들을 제안하는 추측 디코딩 방식입니다."),
    ("DSpark / DFlash2", "별도 draft 모델을 쓰는 추측 디코딩 구성입니다."),
    ("draft 수락률", "제안된 draft 토큰 중 본 모델이 받아들인 비율. 높을수록 추측 디코딩 효과가 큽니다. 반복 토큰 출력에서는 비정상적으로 높게 나옵니다."),
    ("MoE / 활성 파라미터", "Mixture of Experts. 전체 파라미터 중 토큰마다 일부(활성 파라미터)만 계산에 씁니다. 30B-A3B는 전체 30B, 활성 3B입니다."),
    ("NVFP4", "NVIDIA의 4비트 부동소수점 양자화 형식. DGX Spark(GB10)에서는 네이티브 FP4 연산이 아니라 Marlin weight-only 경로로 실행됩니다."),
    ("max_num_seqs", "vLLM 스케줄러가 한 번에 처리하는 최대 시퀀스 수. 클라이언트 동시성과는 다른 서버 설정입니다."),
    ("eager / compiled", "eager는 연산을 그때그때 실행하고, compiled는 vLLM 컴파일과 CUDA Graphs로 실행 경로를 미리 만들어 둡니다."),
    ("Quick", "후보를 빠르게 거르기 위한 짧은 측정. 방향성만 보여 주며 배포 권고가 아닙니다."),
    ("Smoke", "서버가 뜨고 API가 응답하는지만 확인한 기록. 성능 비교 대상이 아닙니다."),
    ("Characterization", "동시성을 바꿔 가며 지속 부하에서의 처리량과 지연을 재는 측정. 기본 일정은 약 210분입니다."),
    ("비교 그룹", "같은 workload와 측정 조건으로 잰 실행 묶음. 순위는 같은 그룹 안에서만 매깁니다."),
    ("판정", "다음 단계(advance), 비교 기준(control), 참고(reference), 탈락(reject), 실행 불가(blocked), 과거 기록(historical)."),
    ("상태", "통과(pass), 부분 통과(partial: 일부 검증 실패), 실행 불가(blocked: 서버가 API 준비 전에 중단)."),
    ("result_sha256 / source_record_sha256", "원본 측정 파일의 해시. 수치가 어떤 원본에서 나왔는지 식별하며, 원본 파일 자체는 Git 밖에 보관합니다."),
]


# --- Cell formats -----------------------------------------------------------

def rgb(hex_color: str) -> dict[str, float]:
    return {key: int(hex_color[i:i + 2], 16) / 255 for key, i in (("red", 0), ("green", 2), ("blue", 4))}


EDGE = {"style": "SOLID", "color": rgb("BFBFBF")}
BOX = {"borders": {"top": EDGE, "bottom": EDGE, "left": EDGE, "right": EDGE}}
HEADER = {"textFormat": {"bold": True, "fontSize": 10}, "backgroundColor": rgb("DCE6F1"),
          "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", **BOX}
BODY = {"verticalAlignment": "TOP", **BOX}
WRAP = {"wrapStrategy": "WRAP"}
WRAP_TOP = {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}
CLIP = {"wrapStrategy": "CLIP"}
RIGHT = {"horizontalAlignment": "RIGHT"}
CENTER = {"horizontalAlignment": "CENTER"}
MUTED = {"textFormat": {"foregroundColor": rgb("666666"), "fontSize": 10}}
TITLE = {"textFormat": {"bold": True, "fontSize": 14}}
SECTION = {"textFormat": {"bold": True, "fontSize": 12}}


def number(pattern: str) -> dict[str, Any]:
    return {"numberFormat": {"type": "NUMBER", "pattern": pattern}}


def merge_formats(*parts: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        for key, value in part.items():
            if key == "textFormat":
                merged[key] = {**merged.get(key, {}), **value}
            else:
                merged[key] = value
    return merged


def format_fields(fmt: dict[str, Any]) -> str:
    paths = []
    for key, value in fmt.items():
        if key == "textFormat":
            paths.extend(f"userEnteredFormat.textFormat.{sub}" for sub in value)
        else:
            paths.append(f"userEnteredFormat.{key}")
    return ",".join(paths)


def char_px(width: float) -> int:
    return int(width * 7 + 5)


# --- Grid helpers -----------------------------------------------------------

A1_RANGE = re.compile(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$")


def col_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return index - 1


def col_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def grid_range(sheet_id: int, a1: str) -> dict[str, int]:
    match = A1_RANGE.match(a1)
    if not match:
        raise ValueError(f"unsupported range: {a1}")
    c0, r0 = col_index(match[1]), int(match[2]) - 1
    c1, r1 = (col_index(match[3]), int(match[4]) - 1) if match[3] else (c0, r0)
    return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1 + 1,
            "startColumnIndex": c0, "endColumnIndex": c1 + 1}


def user_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, (int, float)):
        return {"numberValue": value}
    if isinstance(value, str) and value.startswith("="):
        return {"formulaValue": value}
    return {"stringValue": str(value)}


def dimension(sheet_id: int, axis: str, start: int, end: int, pixels: int) -> dict[str, Any]:
    return {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": axis, "startIndex": start, "endIndex": end},
        "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}


@dataclass
class Tab:
    title: str
    widths: list[int]  # pixels per column
    frozen: tuple[int, int] = (0, 0)  # rows, columns
    cells: dict[tuple[int, int], Any] = field(default_factory=dict)
    notes: dict[tuple[int, int], str] = field(default_factory=dict)
    formats: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    row_heights: dict[int, int] = field(default_factory=dict)  # 1-based row -> pixels
    merges: list[str] = field(default_factory=list)
    filter: str | None = None
    checkboxes: list[str] = field(default_factory=list)
    folded_columns: tuple[int, int] | None = None  # 0-based, end exclusive

    def put(self, a1: str, value: Any, note: str | None = None) -> None:
        cell = grid_range(0, a1)
        key = (cell["startRowIndex"], cell["startColumnIndex"])
        if value is not None:
            self.cells[key] = value
        if note:
            self.notes[key] = note

    def put_row(self, row: int, values: list[Any], first_col: str = "A") -> None:
        start = col_index(first_col)
        for offset, value in enumerate(values):
            self.put(f"{col_letter(start + offset)}{row}", value)

    def fmt(self, a1: str, *parts: dict[str, Any]) -> None:
        self.formats.append((a1, merge_formats(*parts)))

    def used_rows(self) -> int:
        return max(row for row, _ in [*self.cells, *self.notes]) + 1

    def properties(self, sheet_id: int, index: int) -> dict[str, Any]:
        return {"sheetId": sheet_id, "title": self.title, "index": index, "gridProperties": {
            "rowCount": max(self.used_rows() + 20, MAX_ROW), "columnCount": len(self.widths) + 2,
            "frozenRowCount": self.frozen[0], "frozenColumnCount": self.frozen[1]}}

    def requests(self, sheet_id: int) -> list[dict[str, Any]]:
        rows = []
        for r in range(self.used_rows()):
            values = []
            for c in range(len(self.widths)):
                cell: dict[str, Any] = {}
                if (r, c) in self.cells:
                    cell["userEnteredValue"] = user_value(self.cells[(r, c)])
                if (r, c) in self.notes:
                    cell["note"] = self.notes[(r, c)]
                values.append(cell)
            rows.append({"values": values})
        reqs: list[dict[str, Any]] = [{"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
            "rows": rows, "fields": "userEnteredValue,note"}}]
        body_font = {"textFormat": {"fontSize": BODY_FONT_SIZE}}
        used = f"A1:{col_letter(len(self.widths) - 1)}{self.used_rows()}"
        reqs.append({"repeatCell": {"range": grid_range(sheet_id, used), "cell": {"userEnteredFormat": body_font},
                                    "fields": format_fields(body_font)}})
        for a1 in self.merges:
            reqs.append({"mergeCells": {"range": grid_range(sheet_id, a1), "mergeType": "MERGE_ALL"}})
        for a1, fmt in self.formats:
            reqs.append({"repeatCell": {"range": grid_range(sheet_id, a1),
                                        "cell": {"userEnteredFormat": fmt}, "fields": format_fields(fmt)}})
        for index, pixels in enumerate(self.widths):
            reqs.append(dimension(sheet_id, "COLUMNS", index, index + 1, pixels))
        for row, pixels in sorted(self.row_heights.items()):
            reqs.append(dimension(sheet_id, "ROWS", row - 1, row, pixels))
        if self.filter:
            reqs.append({"setBasicFilter": {"filter": {"range": grid_range(sheet_id, self.filter)}}})
        for a1 in self.checkboxes:
            reqs.append({"setDataValidation": {"range": grid_range(sheet_id, a1),
                                               "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}})
        if self.folded_columns:
            span = {"sheetId": sheet_id, "dimension": "COLUMNS",
                    "startIndex": self.folded_columns[0], "endIndex": self.folded_columns[1]}
            reqs.append({"addDimensionGroup": {"range": span}})
            reqs.append({"updateDimensionGroup": {"dimensionGroup": {"range": span, "depth": 1, "collapsed": True},
                                                  "fields": "collapsed"}})
        return reqs


# --- Source data ------------------------------------------------------------

def notes_text(notes: list[str]) -> str:
    return "\n".join(f"- {note}" for note in notes)


def preview_c2_tps(preview: dict[str, Any]) -> float | None:
    for note in preview.get("notes", []):
        match = PREVIEW_C2.search(note)
        if match:
            return float(match[1])
    return None


def run_row(run: dict[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics", {})
    serving = run["serving"]
    options = serving.get("options", {})
    speculative = serving.get("speculative") or {}
    validation = run.get("validation", {})
    tools = [validation[key] for key in ("tool_simple", "tool_nested", "tool_large_surface")
             if isinstance(validation.get(key), dict)]
    attempts = sum(tool["attempts"] for tool in tools)
    passed = sum(tool["passed"] for tool in tools)
    provenance = run.get("provenance", {})
    return {
        "실행 ID": run["id"], "측정일": run["observed_on"], "비교 그룹": run["comparison_group"],
        "판정": PROMOTION.get(run.get("promotion"), run.get("promotion")),
        "상태": STATUS.get(run["status"], run["status"]), "순위 대상": bool(run["eligible_for_ranking"]),
        "모델": run["model"]["display_name"], "구조": run["model"].get("architecture"),
        "총 파라미터 (B)": run["model"].get("total_parameters_b"),
        "활성 파라미터 (B)": run["model"].get("active_parameters_b"),
        "양자화": run["artifact"].get("quantization"), "엔진": serving["engine"], "엔진 버전": serving.get("version"),
        "추측 디코딩": SPEC.get(speculative.get("mode"), speculative.get("mode")),
        "draft 수락률 (%)": speculative.get("acceptance_pct"),
        "처리량 C2 (tok/s)": metrics.get("aggregate_output_tps"),
        "단일 사용자 decode p50 (tok/s)": metrics.get("single_user_decode_tps_p50"),
        "TTFT p50 (ms)": metrics.get("ttft_p50_ms"), "TTFT p95 (ms)": metrics.get("ttft_p95_ms"),
        "TPOT p50 (ms)": metrics.get("tpot_p50_ms"), "E2E p50 (s)": metrics.get("e2e_p50_s"),
        "요청 처리량 (req/s)": metrics.get("request_throughput_rps"),
        "GPU 프로세스 메모리 (MiB)": metrics.get("accelerator_process_memory_mib"),
        "GPU 메모리 할당 비율": options.get("gpu_memory_utilization", options.get("mem_fraction_static")),
        "동시 시퀀스 상한": options.get("max_num_seqs", options.get("max_running_requests", options.get("num_parallel"))),
        "호스트 여유 메모리 (GiB)": metrics.get("host_available_memory_gib"),
        "Tool calling 통과": passed if attempts else None,
        "Tool calling 시도": attempts if attempts else None,
        "답변 품질": QUALITY.get(validation.get("answer_quality"), validation.get("answer_quality")),
        "비고": notes_text(run.get("notes", [])),
        "result_sha256": provenance.get("result_sha256"),
        "source_record_sha256": provenance.get("source_record_sha256"),
    }


def preview_row(preview: dict[str, Any]) -> dict[str, Any]:
    run_id = preview["id"]
    return {
        "실행 ID": run_id, "측정일": f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}",
        "비교 그룹": preview["comparison_group"], "판정": PROMOTION[preview["promotion"]],
        "상태": STATUS[preview["status"]], "순위 대상": False,
        "모델": preview["model"]["display_name"], "구조": preview["model"]["architecture"],
        "총 파라미터 (B)": preview["model"]["total_parameters_b"],
        "활성 파라미터 (B)": preview["model"]["active_parameters_b"],
        # Engine and draft mode come from the record's measurement_scope.
        "엔진": "vLLM", "추측 디코딩": SPEC["external-draft"],
        # The record keeps this operating point only in its notes.
        "처리량 C2 (tok/s)": preview_c2_tps(preview),
        "답변 품질": QUALITY.get(preview["answer_quality"], preview["answer_quality"]),
        "비고": notes_text(preview["notes"] + [
            "처리량 C2 값은 이 기록의 notes에 적힌 동시성 2 지점 값입니다. Quick과 workload가 달라 순위에 넣지 않습니다."]),
        "result_sha256": preview["provenance"]["result_sha256"],
        "source_record_sha256": preview["provenance"]["source_record_sha256"],
    }


def ordered_groups(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    groups = {**data["comparison_groups"], PREVIEW_GROUP_ID: PREVIEW_GROUP}
    return sorted(groups.items(), key=lambda item: CLASS_ORDER.get(item[1]["classification"], 2))


def is_ranked(row: dict[str, Any]) -> bool:
    return row["순위 대상"] and row["상태"] == STATUS["pass"]


def build_rows(data: dict[str, Any], preview: dict[str, Any]) -> list[dict[str, Any]]:
    order = [group_id for group_id, _ in ordered_groups(data)]
    rows = [run_row(run) for run in data["runs"]] + [preview_row(preview)]

    def sort_key(row: dict[str, Any]) -> tuple[int, int, float]:
        tps = row.get("처리량 C2 (tok/s)")
        return order.index(row["비교 그룹"]), 0 if is_ranked(row) else 1, -(tps if tps is not None else -1)

    return sorted(rows, key=sort_key)


def metric_value(rows: list[dict[str, Any]], run_id: str, metric: str) -> float | None:
    row = next((row for row in rows if row["실행 ID"] == run_id), None)
    if row is None:
        return None
    if metric == "GPU 프로세스 메모리 (GiB)":
        mib = row.get("GPU 프로세스 메모리 (MiB)")
        return mib / 1024 if mib is not None else None
    return row.get(metric)


def check_inputs(data: dict[str, Any], preview: dict[str, Any]) -> list[str]:
    """Return problems that would make the generated spreadsheet wrong or stale."""
    errors = []
    if preview.get("comparison_group") != PREVIEW_GROUP_ID:
        errors.append(f"preview record group is {preview.get('comparison_group')!r}, expected {PREVIEW_GROUP_ID!r}")
        return errors
    if preview_c2_tps(preview) is None:
        errors.append("preview record notes no longer state the concurrency 2 throughput")
    rows = build_rows(data, preview)
    if len(rows) + 1 > MAX_ROW:
        errors.append(f"{len(rows)} runs exceed the formula range; raise MAX_ROW")
    for number_, (_, run_a, run_b, metric, holds) in enumerate(FINDINGS, start=1):
        if metric not in RUN_HEADERS:
            errors.append(f"finding {number_}: unknown metric {metric!r}")
            continue
        a, b = metric_value(rows, run_a, metric), metric_value(rows, run_b, metric)
        if a is None or b is None:
            missing = run_a if a is None else run_b
            errors.append(f"finding {number_}: {missing} has no {metric!r} value")
        elif not holds(a, b):
            errors.append(f"finding {number_} no longer holds: {metric} A={a} B={b}; update its text")
    if any(row["답변 품질"] != QUALITY["not_run"] for row in rows):
        errors.append("a run now has answer quality results; update the '아직 모르는 것' text")
    return errors


# --- Spreadsheet layout -----------------------------------------------------

def build_tabs(data: dict[str, Any], preview: dict[str, Any], source: str, suffix: str = "") -> dict[str, Tab]:
    """Lay out every tab; `suffix` is appended to tab titles and the formulas that reference them."""
    titles = {key: title + suffix for key, title in TITLES.items()}
    runs_ref = f"'{titles['runs']}'"
    groups_ref = f"'{titles['groups']}'"
    rows = build_rows(data, preview)
    groups = ordered_groups(data)
    col = {name: col_letter(i) for i, name in enumerate(RUN_HEADERS)}
    last_col = col_letter(len(RUN_HEADERS) - 1)
    last_run_row = len(rows) + 1

    def run_range(name: str) -> str:
        return f"{runs_ref}!${col[name]}$2:${col[name]}${MAX_ROW}"

    # 실행기록
    runs = Tab(titles["runs"], [width for _, width in RUN_COLUMNS], frozen=(1, 1))
    runs.put_row(1, RUN_HEADERS)
    for i, row in enumerate(rows, start=2):
        values = []
        for name in RUN_HEADERS:
            if name == "그룹 내 순위":
                c = {key: col[key] for key in ("비교 그룹", "순위 대상", "상태", "처리량 C2 (tok/s)")}
                values.append(
                    f'=IF(AND({c["순위 대상"]}{i}=TRUE,{c["상태"]}{i}="{STATUS["pass"]}"),'
                    f'COUNTIFS(${c["비교 그룹"]}$2:${c["비교 그룹"]}${MAX_ROW},{c["비교 그룹"]}{i},'
                    f'${c["순위 대상"]}$2:${c["순위 대상"]}${MAX_ROW},TRUE,'
                    f'${c["상태"]}$2:${c["상태"]}${MAX_ROW},"{STATUS["pass"]}",'
                    f'${c["처리량 C2 (tok/s)"]}$2:${c["처리량 C2 (tok/s)"]}${MAX_ROW},">"&{c["처리량 C2 (tok/s)"]}{i})+1,"")')
            elif name == "GPU 프로세스 메모리 (GiB)":
                mib = f'{col["GPU 프로세스 메모리 (MiB)"]}{i}'
                values.append(f'=IF({mib}="","",{mib}/1024)')
            elif name == "그룹·순위 키":
                values.append(f'={col["비교 그룹"]}{i}&"#"&{col["그룹 내 순위"]}{i}')
            else:
                values.append(row.get(name))
        runs.put_row(i, values)
    runs.put("A1", "실행 ID", note=(
        f"{source}. 원본 파일: benchmarks/results/dgx-spark.json (runs {len(data['runs'])}건), "
        f"{PREVIEW_RECORD.relative_to(ROOT).as_posix()}. 상태·판정·추측 디코딩 값은 한국어로 바꿔 적었고 "
        "측정값은 바꾸지 않았습니다. 빈 칸은 미측정이며 0이 아닙니다."))
    runs.put(f'{col["처리량 C2 (tok/s)"]}1', "처리량 C2 (tok/s)", note=(
        "동시성 2에서 closed-loop 요청 4건을 보냈을 때의 초당 출력 토큰 수. Quick 그룹의 순위 기준입니다."))
    runs.put(f'{col["GPU 메모리 할당 비율"]}1', "GPU 메모리 할당 비율", note=(
        "vLLM gpu_memory_utilization, SGLang mem_fraction_static. "
        "GPU 프로세스 메모리는 모델 자체보다 이 설정의 영향을 크게 받습니다."))
    runs.put(f'{col["동시 시퀀스 상한"]}1', "동시 시퀀스 상한",
             note="vLLM max_num_seqs, SGLang max_running_requests, Ollama num_parallel")
    runs.fmt(f"A1:{last_col}1", HEADER)
    runs.fmt("A1", CENTER)
    runs.fmt(f"A2:{last_col}{last_run_row}", BODY)
    for name, pattern in RUN_NUMBER_FORMATS.items():
        runs.fmt(f"{col[name]}2:{col[name]}{last_run_row}", number(pattern))
    for name in RUN_CLIPPED:
        runs.fmt(f"{col[name]}2:{col[name]}{last_run_row}", CLIP)
    for name in RUN_NUMERIC:
        runs.fmt(f"{col[name]}1", RIGHT)
    for name in RUN_CENTERED:
        runs.fmt(f"{col[name]}1:{col[name]}{last_run_row}", CENTER)
    runs.row_heights.update({row: 24 for row in range(2, last_run_row + 1)})
    runs.filter = f"A1:{last_col}{last_run_row}"
    runs.checkboxes.append(f'{col["순위 대상"]}2:{col["순위 대상"]}{last_run_row}')
    runs.folded_columns = (RUN_HEADERS.index(RUN_FOLDED[0]), RUN_HEADERS.index(RUN_FOLDED[1]) + 1)

    # 비교그룹
    group_tab = Tab(titles["groups"], [char_px(w) for w in (34, 34, 12, 12, 45, 70, 9, 11)], frozen=(1, 1))
    group_tab.put_row(1, ["그룹 ID", "이름", "분류", "비교 수준", "Workload", "한계", "실행 수", "순위 대상 실행 수"])
    group_row = {}
    for i, (group_id, group) in enumerate(groups, start=2):
        group_row[group_id] = i
        group_tab.put_row(i, [
            group_id, group["label"], CLASS.get(group["classification"], group["classification"]),
            LEVEL.get(group["comparison_level"], group["comparison_level"]), group["workload"],
            notes_text(group["limitations"]),
            f'=COUNTIF({run_range("비교 그룹")},A{i})',
            f'=COUNTIFS({run_range("비교 그룹")},A{i},{run_range("그룹 내 순위")},">0")'])
    group_tab.put("A1", "그룹 ID", note=(
        f"{source}. dgx-spark.json의 comparison_groups에서 가져왔습니다. characterization 예비 그룹은 "
        "dgx-spark.json에 없어 preview 기록과 benchmarks/results/README.md 설명으로 채웠습니다."))
    group_tab.fmt("A1:H1", HEADER)
    group_tab.fmt(f"A2:H{len(groups) + 1}", BODY, WRAP)

    # 요약
    summary = Tab(titles["summary"], [char_px(w) for w in (5, 60, 26, 26, 22, 10, 10, 9, 9)])
    summary.put("A1", "DGX Spark LLM 서빙 실험 요약")
    summary.fmt("A1", TITLE)
    summary.put("A2", "이 repo는 DGX Spark(GB10, 128 GiB 통합 메모리) 한 대에서 어떤 오픈 모델을 어떤 엔진과 설정으로 "
                      "서빙할지 고르기 위한 서빙 레시피, 측정 도구, 검토된 측정 결과를 모아 둔 곳입니다.")
    summary.put("A3", f"{source}. 이 시트는 repo 데이터로 다시 만들어지므로 여기서 고친 내용은 다음 갱신 때 사라집니다. "
                      "모든 수치는 1회 측정이고 답변 품질은 이 repo에서 측정하지 않았습니다. 같은 비교 그룹 안에서만 순위를 비교합니다.")
    for row in (2, 3):
        summary.merges.append(f"A{row}:I{row}")
        summary.fmt(f"A{row}", WRAP_TOP)
    summary.row_heights.update({2: 36, 3: 52})

    summary.put("A5", "그룹별 1위")
    summary.fmt("A5", SECTION)
    summary.put_row(6, ["비교 그룹", "1위 모델", "처리량 C2 (tok/s)", "순위 대상 실행 수"], first_col="B")
    summary.fmt("B6:E6", HEADER)
    summary.fmt("D6:E6", RIGHT)
    ranked_groups = [group_id for group_id, _ in groups
                     if any(is_ranked(row) and row["비교 그룹"] == group_id for row in rows)]
    key_range = run_range("그룹·순위 키")
    for r, group_id in enumerate(ranked_groups, start=7):
        gi = group_row[group_id]
        leader = f"MATCH({groups_ref}!A{gi}&\"#1\",{key_range},0)"
        summary.put_row(r, [
            f"={groups_ref}!B{gi}",
            f'=IFERROR(INDEX({run_range("모델")},{leader}),"순위 없음")',
            f'=IFERROR(INDEX({run_range("처리량 C2 (tok/s)")},{leader}),"")',
            f"={groups_ref}!H{gi}"], first_col="B")
    leader_end = 6 + len(ranked_groups)
    summary.fmt(f"B7:E{leader_end}", BODY, WRAP)
    summary.fmt(f"D7:D{leader_end}", number("0.0"))

    findings_title = leader_end + 2
    head = findings_title + 2
    summary.put(f"A{findings_title}", "핵심 발견")
    summary.fmt(f"A{findings_title}", SECTION)
    summary.put(f"A{findings_title + 1}", "실행 A와 B의 값은 '실행기록' 탭에서 실행 ID와 지표 이름으로 찾아옵니다. "
                                          "지표 칸에는 '실행기록' 탭의 열 이름을 그대로 씁니다.")
    summary.merges.append(f"A{findings_title + 1}:I{findings_title + 1}")
    summary.put_row(head, ["#", "발견", "실행 A", "실행 B", "지표", "A 값", "B 값", "B/A (배)", "B−A"])
    summary.fmt(f"A{head}:I{head}", HEADER)
    summary.fmt(f"F{head}:I{head}", RIGHT)
    look = f"{runs_ref}!$A$1:${last_col}${MAX_ROW}"
    for n, (text, run_a, run_b, metric, _) in enumerate(FINDINGS, start=1):
        r = head + n

        def lookup(id_col: str, row: int = r) -> str:
            return (f"=INDEX({look},MATCH({id_col}{row},{runs_ref}!$A$1:$A${MAX_ROW},0),"
                    f"MATCH($E{row},{runs_ref}!$A$1:${last_col}$1,0))")

        summary.put_row(r, [n, text, run_a, run_b, metric, lookup("C"), lookup("D"),
                            f'=IF(F{r}=0,"",G{r}/F{r})', f"=G{r}-F{r}"])
    risk = head + len(FINDINGS) + 1
    summary.put_row(risk, [len(FINDINGS) + 1, RISK_FINDING, None, None, "통과하지 못한 실행 수",
                           f'=COUNTIF({run_range("상태")},"{STATUS["partial"]}")'
                           f'+COUNTIF({run_range("상태")},"{STATUS["blocked"]}")'])
    summary.fmt(f"A{head + 1}:I{risk}", BODY, WRAP)
    summary.fmt(f"F{head + 1}:G{risk - 1}", number("0.0"))
    summary.fmt(f"H{head + 1}:H{risk - 1}", number('0.00"x"'))
    summary.fmt(f"I{head + 1}:I{risk - 1}", number("+0.0;-0.0;0"))
    summary.fmt(f"C{head + 1}:D{risk}", CLIP, MUTED)

    unknown = risk + 2
    summary.put(f"A{unknown}", "아직 모르는 것")
    summary.fmt(f"A{unknown}", SECTION)
    summary.put_row(unknown + 1, ["전체 실행 수", None, None, f"=COUNTA({run_range('실행 ID')})"], first_col="B")
    summary.put_row(unknown + 2, [
        "답변 품질을 측정한 실행 수", None, None,
        f'=COUNTIFS({run_range("실행 ID")},"<>",{run_range("답변 품질")},"<>{QUALITY["not_run"]}")'], first_col="B")
    for offset, text in enumerate(UNKNOWN_TEXT, start=3):
        row = unknown + offset
        summary.put(f"B{row}", text)
        summary.merges.append(f"B{row}:I{row}")
        summary.fmt(f"B{row}", WRAP_TOP)
        summary.row_heights[row] = 36

    # 용어설명
    terms = Tab(titles["terms"], [char_px(32), char_px(100)])
    terms.put_row(1, ["용어", "뜻"])
    for i, (term, meaning) in enumerate(TERMS, start=2):
        terms.put_row(i, [term, meaning])
    terms.fmt("A1:B1", HEADER)
    terms.fmt(f"A2:B{len(TERMS) + 1}", BODY, WRAP)

    return {"summary": summary, "runs": runs, "groups": group_tab, "terms": terms}


def content_requests(tabs: dict[str, Tab], sheet_ids: dict[str, int]) -> list[dict[str, Any]]:
    return [request for key in ORDER for request in tabs[key].requests(sheet_ids[key])]


def chunk(requests: list[dict[str, Any]], limit: int = BATCH_BYTES) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = [[]]
    size = 0
    for request in requests:
        piece = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
        if piece > limit:
            raise ValueError(f"single request is {piece} bytes; split it")
        if batches[-1] and size + piece > limit:
            batches.append([])
            size = 0
        batches[-1].append(request)
        size += piece
    return batches


# --- Publishing through the gws CLI -----------------------------------------

def gws(*args: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    command = ["gws", *args]
    if body is not None:
        command += ["--json", json.dumps(body, ensure_ascii=False, separators=(",", ":"))]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stdout.strip() or result.stderr.strip())[-2000:]
        raise RuntimeError(f"gws {' '.join(args[:3])} failed: {detail}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def batch_update(spreadsheet_id: str, requests: list[dict[str, Any]]) -> None:
    params = json.dumps({"spreadsheetId": spreadsheet_id})
    for batch in chunk(requests):
        gws("sheets", "spreadsheets", "batchUpdate", "--params", params, body={"requests": batch})


def create(title: str, tabs: dict[str, Tab]) -> str:
    sheet_ids = {key: index for index, key in enumerate(ORDER)}
    body = {"properties": {"title": title, **SPREADSHEET_PROPERTIES},
            "sheets": [{"properties": tabs[key].properties(sheet_ids[key], sheet_ids[key])} for key in ORDER]}
    spreadsheet_id = gws("sheets", "spreadsheets", "create", body=body)["spreadsheetId"]
    batch_update(spreadsheet_id, content_requests(tabs, sheet_ids))
    return spreadsheet_id


def refresh(spreadsheet_id: str, build: Callable[[str], dict[str, Tab]]) -> None:
    """Fill staging tabs first, then swap them in, so a failed run leaves the old tabs intact."""
    meta = gws("sheets", "spreadsheets", "get", "--params", json.dumps(
        {"spreadsheetId": spreadsheet_id, "fields": "sheets.properties.sheetId,sheets.properties.title"}))
    existing = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in meta.get("sheets", [])}
    tabs = build(STAGING)
    free = (n for n in range(1_000_000) if n not in existing.values())
    sheet_ids = {key: next(free) for key in ORDER}

    setup: list[dict[str, Any]] = [{"deleteSheet": {"sheetId": existing[TITLES[key] + STAGING]}}
                                   for key in ORDER if TITLES[key] + STAGING in existing]
    for key in ORDER:
        properties = tabs[key].properties(sheet_ids[key], 0)
        del properties["index"]  # staging tabs go after the existing ones
        setup.append({"addSheet": {"properties": properties}})
    setup.append({"updateSpreadsheetProperties": {
        "properties": SPREADSHEET_PROPERTIES, "fields": "locale,timeZone"}})
    batch_update(spreadsheet_id, setup)
    batch_update(spreadsheet_id, content_requests(tabs, sheet_ids))

    swap: list[dict[str, Any]] = [{"deleteSheet": {"sheetId": existing[TITLES[key]]}}
                                  for key in ORDER if TITLES[key] in existing]
    swap += [{"updateSheetProperties": {"properties": {"sheetId": sheet_ids[key], "title": TITLES[key], "index": i},
                                        "fields": "title,index"}} for i, key in enumerate(ORDER)]
    batch_update(spreadsheet_id, swap)


def formula_errors(spreadsheet_id: str) -> list[str]:
    params = {"spreadsheetId": spreadsheet_id, "ranges": [f"'{TITLES[key]}'" for key in ORDER]}
    result = gws("sheets", "spreadsheets", "values", "batchGet", "--params", json.dumps(params))
    found = []
    for value_range in result.get("valueRanges", []):
        for r, row in enumerate(value_range.get("values", []), start=1):
            for c, value in enumerate(row):
                if value in FORMULA_ERRORS:
                    found.append(f"{value_range['range'].split('!')[0]}!{col_letter(c)}{r} {value}")
    return found


# --- Command line -----------------------------------------------------------

def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def source_line(data_path: Path, today: dt.date) -> str:
    commit = git("rev-parse", "--short", "HEAD") or "알 수 없음"
    dirty = git("status", "--porcelain", "--", str(data_path.parent))
    suffix = " + 커밋 전 변경" if dirty else ""
    return f"원본: {REPO_URL}, commit {commit}{suffix}, {today.isoformat()} 생성 (leaderboards/build_sheet.py)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate inputs and findings without network access")
    mode.add_argument("--output", type=Path, help="write the Sheets API requests as JSON for review")
    mode.add_argument("--spreadsheet-id", help="replace the generated tabs of an existing spreadsheet")
    mode.add_argument("--create", metavar="TITLE", help="create a new spreadsheet in the gws account's Drive")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--preview", type=Path, default=PREVIEW_RECORD)
    args = parser.parse_args(argv)

    data = json.loads(args.data.read_text(encoding="utf-8"))
    preview = json.loads(args.preview.read_text(encoding="utf-8"))
    errors = validate_data(data) or check_inputs(data, preview)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    source = source_line(args.data.resolve(), dt.date.today())

    def build(suffix: str = "") -> dict[str, Tab]:
        return build_tabs(data, preview, source, suffix)

    tabs = build()
    runs = len(data["runs"]) + 1
    if args.check:
        requests = content_requests(tabs, {key: i for i, key in enumerate(ORDER)})
        print(f"OK: {runs} runs, {len(FINDINGS)} findings hold, {len(requests)} requests in {len(chunk(requests))} batches")
        return 0
    if args.output:
        sheet_ids = {key: i for i, key in enumerate(ORDER)}
        payload = {"sheets": [tabs[key].properties(sheet_ids[key], sheet_ids[key]) for key in ORDER],
                   "requests": content_requests(tabs, sheet_ids)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
        return 0

    try:
        if args.create:
            spreadsheet_id = create(args.create, tabs)
        else:
            spreadsheet_id = args.spreadsheet_id
            refresh(spreadsheet_id, build)
        problems = formula_errors(spreadsheet_id)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    if problems:
        print(f"error: published {url} but found formula errors:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    print(f"Published {runs} runs to {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
