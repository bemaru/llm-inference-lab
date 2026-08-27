#!/usr/bin/env python3
"""Build the static DGX Spark leaderboard from normalized benchmark results."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "benchmarks" / "results" / "dgx-spark.json"
DEFAULT_OUTPUT = ROOT / "leaderboards" / "dgx-spark.html"


def validate_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")

    groups = data.get("comparison_groups")
    runs = data.get("runs")
    if not isinstance(groups, dict) or not groups:
        errors.append("comparison_groups must be a non-empty object")
        groups = {}
    if not isinstance(runs, list) or not runs:
        errors.append("runs must be a non-empty array")
        return errors

    seen: set[str] = set()
    metric_names = (
        "ttft_p50_ms",
        "ttft_p95_ms",
        "tpot_p50_ms",
        "e2e_p50_s",
        "single_user_decode_tps_p50",
        "aggregate_output_tps",
        "concurrency",
        "request_throughput_rps",
        "accelerator_process_memory_mib",
        "host_available_memory_gib",
    )
    tool_names = ("tool_simple", "tool_nested", "tool_large_surface")

    for index, run in enumerate(runs):
        prefix = f"runs[{index}]"
        run_id = run.get("id")
        if not isinstance(run_id, str) or not run_id:
            errors.append(f"{prefix}.id must be a non-empty string")
            continue
        if run_id in seen:
            errors.append(f"duplicate run id: {run_id}")
        seen.add(run_id)

        group_id = run.get("comparison_group")
        if group_id not in groups:
            errors.append(f"{run_id}: unknown comparison_group {group_id!r}")

        metrics = run.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{run_id}: metrics must be an object")
            metrics = {}
        for metric in metric_names:
            if metric not in metrics:
                errors.append(f"{run_id}: missing metric {metric}")
                continue
            value = metrics[metric]
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                errors.append(f"{run_id}: metric {metric} must be a non-negative number or null")

        if run.get("eligible_for_ranking"):
            if run.get("status") != "pass":
                errors.append(f"{run_id}: a ranked run must have pass status")
            if metrics.get("aggregate_output_tps") is None:
                errors.append(f"{run_id}: a ranked run needs aggregate_output_tps")

        validation = run.get("validation")
        if not isinstance(validation, dict):
            errors.append(f"{run_id}: validation must be an object")
            validation = {}
        for tool_name in tool_names:
            result = validation.get(tool_name)
            if not isinstance(result, dict):
                errors.append(f"{run_id}: missing {tool_name} result")
                continue
            passed = result.get("passed")
            attempts = result.get("attempts")
            if not isinstance(passed, int) or not isinstance(attempts, int):
                errors.append(f"{run_id}: {tool_name} counts must be integers")
            elif passed < 0 or attempts < 0 or passed > attempts:
                errors.append(f"{run_id}: invalid {tool_name} pass count")

        provenance = run.get("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
        hashes = [provenance[key] for key in ("result_sha256", "source_record_sha256") if key in provenance]
        if not hashes or any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) for value in hashes):
            errors.append(f"{run_id}: provenance hash must be a SHA-256 hex digest")
        if not isinstance(provenance.get("measurement_scope"), str) or not provenance["measurement_scope"].strip():
            errors.append(f"{run_id}: measurement_scope must be a non-empty string")

    return errors


def render(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__LEADERBOARD_DATA__", payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail when the generated HTML is stale")
    args = parser.parse_args()

    data_path = args.data.resolve()
    output_path = args.output.resolve()
    data = json.loads(data_path.read_text(encoding="utf-8"))
    errors = validate_data(data)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    rendered = render(data)
    if args.check:
        if not output_path.is_file():
            print(f"error: generated file is missing: {output_path}", file=sys.stderr)
            return 1
        if output_path.read_text(encoding="utf-8") != rendered:
            print(f"error: generated file is stale: {output_path}", file=sys.stderr)
            return 1
        print(f"OK: {len(data['runs'])} runs; generated HTML is current")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {output_path.relative_to(ROOT)} from {data_path.relative_to(ROOT)}")
    return 0


TEMPLATE = r'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>DGX Spark 모델 서빙 벤치마크</title>
  <style>
    :root {
      --paper: #f3f5f7;
      --panel: #ffffff;
      --panel-strong: #ffffff;
      --ink: #202830;
      --muted: #66717d;
      --rule: #d9dfe5;
      --rule-strong: #aeb8c2;
      --cobalt: #315f8c;
      --teal: #2d6a57;
      --orange: #9a5b2e;
      --violet: #655b86;
      --steel: #737e88;
      --navy: #243b55;
      --shadow: 0 8px 24px rgba(32, 48, 64, .055);
      --display: "Aptos Display", "Segoe UI", "Noto Sans KR", sans-serif;
      --body: "Aptos", "Segoe UI", "Noto Sans KR", sans-serif;
      --data: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: var(--body);
      line-height: 1.55;
    }

    a { color: var(--cobalt); }
    button, input, select { font: inherit; }
    button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible,
    [tabindex="0"]:focus-visible {
      outline: 3px solid rgba(49, 95, 140, .32);
      outline-offset: 2px;
    }

    .shell { max-width: 1480px; margin: 0 auto; padding: 24px 28px 64px; }
    .method-strip {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 16px;
      padding: 11px 16px;
      border: 1px solid var(--rule);
      border-top: 3px solid var(--navy);
      background: var(--panel);
      color: var(--muted);
      font-size: 13px;
    }
    .method-strip .method-mark { color: var(--ink); font-weight: 650; }
    .method-strip .method-separator { color: var(--rule-strong); }

    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(360px, .55fr);
      gap: 42px;
      align-items: center;
      margin-top: 14px;
      padding: 34px 36px;
      border: 1px solid var(--rule);
      background: var(--panel);
    }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }
    h1 {
      max-width: 900px;
      margin: 0;
      font: 650 clamp(34px, 4vw, 52px)/1.18 var(--display);
      letter-spacing: -.025em;
      word-break: keep-all;
    }
    .hero-copy {
      max-width: 780px;
      margin: 16px 0 0;
      color: var(--muted);
      font-size: 16px;
      word-break: keep-all;
    }
    .hero-meta {
      border-left: 1px solid var(--rule);
      padding: 0 0 0 28px;
    }
    .hero-meta dl { margin: 0; }
    .hero-meta div {
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 12px;
      padding: 9px 0;
      border-bottom: 1px solid var(--rule);
    }
    .hero-meta dt {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .hero-meta dd { margin: 0; font-weight: 650; }

    .warning {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 14px;
      align-items: start;
      margin: 18px 0 30px;
      padding: 15px 18px;
      border: 1px solid #cdd7e0;
      border-left: 4px solid var(--cobalt);
      background: #f7f9fb;
    }
    .warning strong {
      color: var(--navy);
      font-size: 13px;
      font-weight: 700;
    }
    .warning p { margin: 0; color: #4f5b66; }

    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: end;
      margin: 38px 0 14px;
    }
    .section-head h2 {
      margin: 0;
      font: 650 clamp(24px, 2.5vw, 32px)/1.2 var(--display);
      letter-spacing: -.015em;
    }
    .section-head p { max-width: 660px; margin: 0; color: var(--muted); }

    .plot-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(340px, .55fr);
      border: 1px solid var(--rule);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .plot-panel { min-width: 0; padding: 24px; border-right: 1px solid var(--rule); }
    .plot-caption {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    #tradeoffPlot { display: block; width: 100%; min-height: 390px; }
    .plot-empty { fill: var(--muted); font: 14px var(--body); }
    .axis-label { fill: var(--muted); font: 11px var(--data); }
    .point-label { fill: var(--ink); font: 650 11px var(--body); pointer-events: none; }
    .plot-point { cursor: pointer; transition: transform .18s ease, opacity .18s ease; transform-box: fill-box; transform-origin: center; }
    .plot-point:hover, .plot-point.is-selected { transform: scale(1.18); }
    .plot-point.is-dimmed { opacity: .24; }

    .detail-panel { padding: 26px; background: #fbfcfd; }
    .detail-panel h3 {
      margin: 0 0 6px;
      font: 650 25px/1.15 var(--display);
      letter-spacing: -.02em;
    }
    .detail-kicker { margin: 0 0 20px; color: var(--muted); font: 12px var(--data); }
    .badge-row { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 18px; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 25px;
      padding: 4px 7px;
      border: 1px solid currentColor;
      border-radius: 3px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }
    .badge.advance, .badge.pass { color: var(--teal); background: rgba(45, 106, 87, .07); }
    .badge.control { color: var(--cobalt); background: rgba(49, 95, 140, .07); }
    .badge.reference { color: var(--violet); background: rgba(101, 91, 134, .07); }
    .badge.reject, .badge.partial { color: var(--orange); background: rgba(154, 91, 46, .07); }
    .badge.blocked, .badge.historical { color: var(--steel); background: rgba(110, 125, 141, .08); }
    .detail-list { margin: 0; }
    .detail-list > div { padding: 10px 0; border-top: 1px solid var(--rule); }
    .detail-list dt { margin-bottom: 4px; color: var(--muted); font-size: 11px; font-weight: 650; }
    .detail-list dd { margin: 0; overflow-wrap: anywhere; }
    .mono { font-family: var(--data); font-size: .88em; }
    .options {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .option {
      padding: 4px 6px;
      background: var(--paper);
      border: 1px solid var(--rule);
      font: 11px var(--data);
    }
    .detail-notes { margin: 12px 0 0; padding-left: 18px; color: var(--muted); }
    .detail-notes li + li { margin-top: 6px; }

    .toolbar {
      display: grid;
      grid-template-columns: minmax(220px, 1.2fr) repeat(3, minmax(150px, .55fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .control { display: grid; gap: 5px; }
    .control label { color: var(--muted); font-size: 11px; font-weight: 650; }
    .control input, .control select {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      color: var(--ink);
      background: var(--panel-strong);
      padding: 8px 10px;
    }

    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--rule);
      background: var(--panel-strong);
      box-shadow: var(--shadow);
    }
    table { width: 100%; min-width: 1160px; border-collapse: collapse; }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      padding: 12px 10px;
      border-bottom: 1px solid var(--rule-strong);
      color: var(--muted);
      background: #eef1f4;
      text-align: right;
      font-size: 11px;
      font-weight: 650;
      white-space: nowrap;
    }
    th:nth-child(-n+4), th:last-child { text-align: left; }
    td { padding: 14px 10px; border-bottom: 1px solid var(--rule); text-align: right; vertical-align: middle; }
    td:nth-child(-n+4), td:last-child { text-align: left; }
    tbody tr { cursor: pointer; transition: background .15s ease; }
    tbody tr:hover, tbody tr.is-selected { background: #f1f5f8; }
    tbody tr:last-child td { border-bottom: 0; }
    .rank { font: 700 16px var(--data); color: var(--cobalt); }
    .config-name { display: block; font-weight: 720; }
    .config-meta { display: block; margin-top: 4px; color: var(--muted); font: 11px/1.45 var(--data); }
    .metric { font: 650 13px var(--data); white-space: nowrap; }
    .metric.best { color: var(--teal); font-weight: 800; }
    .source-link { font: 12px var(--data); white-space: nowrap; }
    .empty-row { padding: 32px; color: var(--muted); text-align: center !important; }
    .table-note { margin: 12px 2px 0; color: var(--muted); font-size: 13px; }

    .method-card {
      margin-top: 28px;
      padding: 20px 22px;
      border: 1px solid var(--rule);
      border-left: 4px solid var(--cobalt);
      background: var(--panel);
    }
    .method-card h2 { margin: 0 0 10px; font: 700 22px var(--display); }
    .method-card ul { margin: 0; padding-left: 20px; color: var(--muted); }
    .method-card li + li { margin-top: 5px; }
    footer { margin-top: 34px; padding-top: 16px; border-top: 1px solid var(--rule-strong); color: var(--muted); font: 11px var(--data); }

    @media (max-width: 1050px) {
      .hero, .plot-grid { grid-template-columns: 1fr; }
      .plot-panel { border-right: 0; border-bottom: 1px solid var(--rule); }
      .toolbar { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 650px) {
      .shell { padding: 12px 10px 44px; }
      .hero { padding: 24px 20px; }
      h1 { font-size: clamp(30px, 9vw, 40px); }
      .hero-meta { border-left: 0; border-top: 1px solid var(--rule); padding: 18px 0 0; }
      .warning { grid-template-columns: 1fr; gap: 6px; }
      .toolbar { grid-template-columns: 1fr; }
      .section-head { display: block; }
      .section-head p { margin-top: 10px; }
      .plot-panel, .detail-panel { padding: 16px; }
      #tradeoffPlot { min-height: 310px; }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      *, *::before, *::after { transition-duration: .001ms !important; animation-duration: .001ms !important; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <div class="method-strip" aria-label="측정 분류">
      <span class="method-mark">측정 구분: Quick benchmark</span>
      <span class="method-separator">•</span>
      <span>Custom workload</span>
      <span class="method-separator">•</span>
      <span>검증 상태: Unverified</span>
      <span class="method-separator">•</span>
      <span id="observedThrough">기준일 —</span>
    </div>

    <header class="hero">
      <div>
        <h1>DGX Spark 모델 서빙 벤치마크</h1>
        <p class="hero-copy">동일 하드웨어에서 측정한 모델 체크포인트, 양자화, 런타임 및 서빙 옵션별 Quick benchmark 결과를 비교합니다. 각 결과는 검증 상태와 정규화 결과의 근거 해시을 함께 제공합니다.</p>
      </div>
      <aside class="hero-meta" aria-label="플랫폼 요약">
        <dl>
          <div><dt>측정 시스템</dt><dd id="platformName">—</dd></div>
          <div><dt>등록 구성</dt><dd id="recordCount">—</dd></div>
          <div><dt>순위 대상</dt><dd id="rankedCount">—</dd></div>
          <div><dt>Quick 1위</dt><dd id="leaderName">—</dd></div>
        </dl>
      </aside>
    </header>

    <div class="warning" role="note">
      <strong>결과 해석 시 유의사항</strong>
      <p>현재 순위는 단일 Quick benchmark의 방향성 결과입니다. 반복 토큰 출력은 speculative decoding에 유리하며, 답변 품질·application workflow·open-loop goodput은 아직 측정하지 않았습니다. 이 결과는 배포 결정 또는 공식 MLPerf 결과로 사용할 수 없습니다.</p>
    </div>

    <section aria-labelledby="tradeoffHeading">
      <div class="section-head">
        <div>
          <p class="eyebrow">운용 지표 비교</p>
          <h2 id="tradeoffHeading">TTFT 및 처리량 비교</h2>
        </div>
        <p>가로축은 TTFT p50, 세로축은 concurrency 2에서 측정한 aggregate output throughput입니다. 점 크기는 측정 후 accelerator process memory를 나타냅니다.</p>
      </div>
      <div class="plot-grid">
        <div class="plot-panel">
          <div class="plot-caption"><span id="plotGroupLabel">—</span><span>데이터 점을 선택하면 상세 조건을 확인할 수 있습니다.</span></div>
          <svg id="tradeoffPlot" viewBox="0 0 860 410" role="img" aria-label="TTFT와 aggregate output TPS 산점도"></svg>
        </div>
        <aside class="detail-panel" id="detailPanel" aria-live="polite"></aside>
      </div>
    </section>

    <section aria-labelledby="leaderboardHeading">
      <div class="section-head">
        <div>
          <p class="eyebrow">측정 결과</p>
          <h2 id="leaderboardHeading">서빙 구성별 비교</h2>
        </div>
        <p>순위는 현재 Quick 비교 그룹에서 API 및 Tool 검증 조건을 충족한 구성만 aggregate output throughput 기준으로 산정합니다.</p>
      </div>

      <div class="toolbar" aria-label="리더보드 필터">
        <div class="control">
          <label for="searchInput">검색</label>
          <input id="searchInput" type="search" placeholder="모델, 체크포인트, 양자화, 파서 검색">
        </div>
        <div class="control">
          <label for="groupFilter">비교 그룹</label>
          <select id="groupFilter"></select>
        </div>
        <div class="control">
          <label for="stageFilter">검토 상태</label>
          <select id="stageFilter">
            <option value="all">전체</option>
            <option value="advance">후속 검증 대상</option>
            <option value="control">비교 기준</option>
            <option value="reference">참고 모델</option>
            <option value="reject">후보 제외</option>
            <option value="blocked">호환성 문제</option>
            <option value="historical">과거 측정</option>
          </select>
        </div>
        <div class="control">
          <label for="sortBy">표시 순서</label>
          <select id="sortBy">
            <option value="rank">순위 / aggregate TPS</option>
            <option value="single">Single-user TPS 높은 순</option>
            <option value="ttft">TTFT 낮은 순</option>
            <option value="memory">메모리 사용량 낮은 순</option>
            <option value="model">모델 이름</option>
          </select>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>순위</th>
              <th>서빙 구성</th>
              <th>검토 상태</th>
              <th>Tool 검증</th>
              <th>Single-user<br>tok/s</th>
              <th>Aggregate C2<br>tok/s</th>
              <th>TTFT<br>p50</th>
              <th>E2E<br>p50</th>
              <th>가속기<br>메모리</th>
              <th>근거</th>
            </tr>
          </thead>
          <tbody id="leaderboardBody"></tbody>
        </table>
      </div>
      <p class="table-note" id="tableCount">—</p>
    </section>

    <section class="method-card" aria-labelledby="methodHeading">
      <h2 id="methodHeading">비교 조건 및 한계</h2>
      <ul id="methodLimitations"></ul>
    </section>

    <footer><span class="mono">benchmarks/results/dgx-spark.json</span>의 정규화된 결과를 기반으로 생성했습니다. 측정 조건과 한계는 각 결과에 기록하며, 근거 해시는 원본 실행 기록의 공개를 의미하지 않습니다.</footer>
  </main>

  <script id="leaderboard-data" type="application/json">__LEADERBOARD_DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('leaderboard-data').textContent);
    const runs = data.runs;
    const groups = data.comparison_groups;
    const currentGroup = Object.keys(groups)[0];
    const promotionLabels = {
      advance: '후속 검증 대상', control: '비교 기준', reference: '참고 모델',
      reject: '후보 제외', blocked: '호환성 문제', historical: '과거 측정'
    };
    const statusLabels = { pass: 'Quick 검증 통과', partial: '일부 항목 실패', blocked: 'API 준비 실패' };
    const comparisonLevelLabels = {
      directional: '방향성 비교', not_comparable: '직접 비교 불가', standard: '정식 비교'
    };
    const commercialUseLabels = {
      allowed: '상업적 사용 가능', not_allowed: '상업적 사용 불가', not_recorded: '실행 기록에 미기재'
    };
    const colors = {
      advance: '#2d6a57', control: '#315f8c', reference: '#655b86',
      reject: '#9a5b2e', blocked: '#737e88', historical: '#737e88'
    };
    const rankable = runs
      .filter(run => run.comparison_group === currentGroup && run.eligible_for_ranking && run.status === 'pass')
      .sort((a, b) => b.metrics.aggregate_output_tps - a.metrics.aggregate_output_tps);
    const ranks = Object.fromEntries(rankable.map((run, index) => [run.id, index + 1]));
    let selectedId = rankable[0]?.id || runs[0]?.id;

    const escapeHtml = value => String(value ?? '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
    const formatNumber = (value, digits = 1) => value == null ? '—' : Number(value).toLocaleString('en-US', { maximumFractionDigits: digits });
    const shortHash = value => value ? (value.length > 18 ? `${value.slice(0, 16)}…` : value) : '미기재';
    const specLabel = run => {
      const spec = run.serving.speculative;
      if (spec.mode === 'off') return 'Speculative decoding off';
      if (spec.mode === 'mtp') return `MTP n${spec.num_tokens}`;
      return `DSpark n${spec.num_tokens}`;
    };
    const toolSummary = run => {
      const parts = ['tool_simple', 'tool_nested', 'tool_large_surface'].map(key => run.validation[key]);
      const passed = parts.reduce((sum, item) => sum + item.passed, 0);
      const attempts = parts.reduce((sum, item) => sum + item.attempts, 0);
      return attempts ? `${passed}/${attempts}` : '미실행';
    };
    const toolPassed = run => {
      const keys = ['tool_simple', 'tool_nested', 'tool_large_surface'];
      return keys.every(key => run.validation[key].attempts > 0 && run.validation[key].passed === run.validation[key].attempts);
    };
    const provenanceHref = () => '../benchmarks/results/dgx-spark.json';

    function setupPage() {
      document.getElementById('observedThrough').textContent = `기준일 ${data.observed_through}`;
      document.getElementById('platformName').textContent = `${data.platform.display_name} / ${data.platform.accelerator}`;
      document.getElementById('recordCount').textContent = `${runs.length}개`;
      document.getElementById('rankedCount').textContent = `${rankable.length}개`;
      document.getElementById('leaderName').textContent = rankable[0]?.model.display_name || '—';

      const groupSelect = document.getElementById('groupFilter');
      groupSelect.innerHTML = `<option value="all">전체 비교 그룹</option>` +
        Object.entries(groups).map(([id, group]) => `<option value="${escapeHtml(id)}">${escapeHtml(group.label)}</option>`).join('');
      groupSelect.value = 'all';
      updateMethod();
      renderAll();
    }

    function filteredRuns() {
      const search = document.getElementById('searchInput').value.trim().toLowerCase();
      const group = document.getElementById('groupFilter').value;
      const stage = document.getElementById('stageFilter').value;
      const sort = document.getElementById('sortBy').value;
      const visible = runs.filter(run => {
        const searchable = JSON.stringify({
          model: run.model, artifact: run.artifact, serving: run.serving,
          status: run.status, promotion: run.promotion
        }).toLowerCase();
        return (!search || searchable.includes(search)) &&
          (group === 'all' || run.comparison_group === group) &&
          (stage === 'all' || run.promotion === stage);
      });
      const descendingMetric = field => (a, b) => (b.metrics[field] ?? -Infinity) - (a.metrics[field] ?? -Infinity);
      const ascendingMetric = field => (a, b) => (a.metrics[field] ?? Infinity) - (b.metrics[field] ?? Infinity);
      const sorters = {
        rank: (a, b) => (ranks[a.id] ?? 999) - (ranks[b.id] ?? 999) || descendingMetric('aggregate_output_tps')(a, b),
        single: descendingMetric('single_user_decode_tps_p50'),
        ttft: ascendingMetric('ttft_p50_ms'),
        memory: ascendingMetric('accelerator_process_memory_mib'),
        model: (a, b) => a.model.display_name.localeCompare(b.model.display_name)
      };
      return visible.sort(sorters[sort]);
    }

    function renderAll() {
      const visible = filteredRuns();
      if (!visible.some(run => run.id === selectedId)) selectedId = visible[0]?.id || selectedId;
      renderTable(visible);
      const plotRuns = document.getElementById('groupFilter').value === 'all'
        ? visible.filter(run => run.comparison_group === currentGroup)
        : visible;
      renderPlot(plotRuns);
      renderDetail(runs.find(run => run.id === selectedId));
    }

    function renderTable(visible) {
      const body = document.getElementById('leaderboardBody');
      const bestAggregate = Math.max(...visible.map(run => run.metrics.aggregate_output_tps ?? -Infinity));
      if (!visible.length) {
        body.innerHTML = '<tr><td class="empty-row" colspan="10">선택한 조건에 해당하는 기록이 없습니다.</td></tr>';
      } else {
        body.innerHTML = visible.map(run => {
          const metrics = run.metrics;
          const rank = ranks[run.id] ? `#${ranks[run.id]}` : '—';
          const toolClass = toolPassed(run) ? 'pass' : (run.validation.api === 'fail' ? 'blocked' : 'partial');
          const bestClass = metrics.aggregate_output_tps === bestAggregate && bestAggregate !== -Infinity ? ' best' : '';
          return `<tr data-id="${escapeHtml(run.id)}" class="${run.id === selectedId ? 'is-selected' : ''}" tabindex="0">
            <td><span class="rank">${rank}</span></td>
            <td><span class="config-name">${escapeHtml(run.model.display_name)}</span><span class="config-meta">${escapeHtml(run.artifact.quantization)} · ${escapeHtml(specLabel(run))}<br>${escapeHtml(run.serving.engine)} ${escapeHtml(run.serving.version)} · ${escapeHtml(comparisonLevelLabels[groups[run.comparison_group].comparison_level] || groups[run.comparison_group].comparison_level)}</span></td>
            <td><span class="badge ${escapeHtml(run.promotion)}">${escapeHtml(promotionLabels[run.promotion])}</span></td>
            <td><span class="badge ${toolClass}">${escapeHtml(toolSummary(run))}</span></td>
            <td><span class="metric">${formatNumber(metrics.single_user_decode_tps_p50, 3)}</span></td>
            <td><span class="metric${bestClass}">${formatNumber(metrics.aggregate_output_tps, 3)}</span></td>
            <td><span class="metric">${metrics.ttft_p50_ms == null ? '—' : `${formatNumber(metrics.ttft_p50_ms, 0)} ms`}</span></td>
            <td><span class="metric">${metrics.e2e_p50_s == null ? '—' : `${formatNumber(metrics.e2e_p50_s, 3)} s`}</span></td>
            <td><span class="metric">${metrics.accelerator_process_memory_mib == null ? '—' : `${formatNumber(metrics.accelerator_process_memory_mib / 1024, 1)} GiB`}</span></td>
            <td><a class="source-link" href="${escapeHtml(provenanceHref(run))}" target="_blank" rel="noreferrer">정규화 결과 ↗</a></td>
          </tr>`;
        }).join('');
      }
      document.getElementById('tableCount').textContent = `${visible.length} / ${runs.length}개 서빙 구성 표시 · 순위가 없는 기록은 직접 비교 불가, 검증 조건 미충족 또는 과거 측정입니다.`;
      body.querySelectorAll('tr[data-id]').forEach(row => {
        const activate = () => selectRun(row.dataset.id);
        row.addEventListener('click', event => { if (!event.target.closest('a')) activate(); });
        row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } });
      });
    }

    function renderPlot(visible) {
      const svg = document.getElementById('tradeoffPlot');
      const measured = visible.filter(run => run.metrics.ttft_p50_ms != null && run.metrics.aggregate_output_tps != null);
      if (!measured.length) {
        svg.innerHTML = '<text x="430" y="205" text-anchor="middle" class="plot-empty">선택한 비교 그룹에는 동일 기준으로 표시할 성능 측정값이 없습니다.</text>';
        return;
      }
      const width = 860, height = 410;
      const margin = { left: 70, right: 36, top: 26, bottom: 58 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      const xMax = Math.max(...measured.map(run => run.metrics.ttft_p50_ms)) * 1.12;
      const yMax = Math.max(...measured.map(run => run.metrics.aggregate_output_tps)) * 1.15;
      const x = value => margin.left + (value / xMax) * innerW;
      const y = value => margin.top + innerH - (value / yMax) * innerH;
      const grid = [];
      for (let i = 0; i <= 4; i++) {
        const gx = margin.left + (innerW * i / 4);
        const gy = margin.top + (innerH * i / 4);
        grid.push(`<line x1="${gx}" y1="${margin.top}" x2="${gx}" y2="${margin.top + innerH}" stroke="#ced9e4" stroke-width="1"/>`);
        grid.push(`<text x="${gx}" y="${height - 25}" text-anchor="middle" class="axis-label">${Math.round(xMax * i / 4)} ms</text>`);
        grid.push(`<line x1="${margin.left}" y1="${gy}" x2="${margin.left + innerW}" y2="${gy}" stroke="#ced9e4" stroke-width="1"/>`);
        grid.push(`<text x="${margin.left - 12}" y="${gy + 4}" text-anchor="end" class="axis-label">${Math.round(yMax * (4 - i) / 4)}</text>`);
      }
      const points = measured.map(run => {
        const memory = run.metrics.accelerator_process_memory_mib ?? 40000;
        const radius = Math.max(7, Math.min(15, 7 + (memory - 30000) / 6000));
        const px = x(run.metrics.ttft_p50_ms);
        const py = y(run.metrics.aggregate_output_tps);
        const label = `${run.model.family} · ${specLabel(run)}`;
        const anchor = px > width * .73 ? 'end' : 'start';
        const labelX = anchor === 'end' ? px - radius - 7 : px + radius + 7;
        return `<g class="plot-point ${run.id === selectedId ? 'is-selected' : ''}" data-id="${escapeHtml(run.id)}" role="button" tabindex="0" aria-label="${escapeHtml(label)}, TTFT ${run.metrics.ttft_p50_ms} ms, aggregate ${run.metrics.aggregate_output_tps} tokens per second">
          <circle cx="${px}" cy="${py}" r="${radius}" fill="${colors[run.promotion]}" fill-opacity=".82" stroke="#ffffff" stroke-width="3"/>
          <text x="${labelX}" y="${py + 4}" text-anchor="${anchor}" class="point-label">${escapeHtml(label)}</text>
        </g>`;
      }).join('');
      svg.innerHTML = `${grid.join('')}
        <text x="${margin.left + innerW / 2}" y="${height - 3}" text-anchor="middle" class="axis-label">TTFT p50 (ms, 낮을수록 우수)</text>
        <text x="15" y="${margin.top + innerH / 2}" text-anchor="middle" transform="rotate(-90 15 ${margin.top + innerH / 2})" class="axis-label">Aggregate output throughput (tok/s, 높을수록 우수)</text>
        ${points}`;
      svg.querySelectorAll('.plot-point').forEach(point => {
        const activate = () => selectRun(point.dataset.id);
        point.addEventListener('click', activate);
        point.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } });
      });
    }

    function renderDetail(run) {
      const panel = document.getElementById('detailPanel');
      if (!run) {
        panel.innerHTML = '<p>표시할 기록이 없습니다.</p>';
        return;
      }
      const options = Object.entries(run.serving.options)
        .map(([key, value]) => `<span class="option">${escapeHtml(key)}=${escapeHtml(value)}</span>`).join('');
      panel.innerHTML = `
        <p class="eyebrow">선택한 서빙 구성</p>
        <h3>${escapeHtml(run.model.display_name)}</h3>
        <p class="detail-kicker">${escapeHtml(run.id)}</p>
        <div class="badge-row">
          <span class="badge ${escapeHtml(run.promotion)}">${escapeHtml(promotionLabels[run.promotion])}</span>
          <span class="badge ${escapeHtml(run.status)}">${escapeHtml(statusLabels[run.status])}</span>
          <span class="badge ${toolPassed(run) ? 'pass' : 'partial'}">Tool ${escapeHtml(toolSummary(run))}</span>
        </div>
        <dl class="detail-list">
          <div><dt>모델 아티팩트</dt><dd class="mono">${escapeHtml(run.artifact.model_id)}@${escapeHtml(shortHash(run.artifact.revision))}</dd></div>
          <div><dt>가중치 및 라이선스</dt><dd>${escapeHtml(run.artifact.quantization)}<br><span class="mono">${escapeHtml(run.artifact.license)} · ${escapeHtml(commercialUseLabels[run.artifact.commercial_use] || run.artifact.commercial_use)}</span></dd></div>
          <div><dt>런타임</dt><dd>${escapeHtml(run.serving.engine)} ${escapeHtml(run.serving.version)}<br><span class="mono">${escapeHtml(run.serving.image)} · ${escapeHtml(shortHash(run.serving.image_digest))}</span></dd></div>
          <div><dt>Speculative decoding</dt><dd>${escapeHtml(specLabel(run))}${run.serving.speculative.acceptance_pct == null ? '' : ` · draft acceptance ${formatNumber(run.serving.speculative.acceptance_pct, 3)}%`}</dd></div>
          <div><dt>서빙 옵션</dt><dd><div class="options">${options}</div></dd></div>
          <div><dt>비교 그룹</dt><dd>${escapeHtml(groups[run.comparison_group].label)}<br><span class="mono">${escapeHtml(comparisonLevelLabels[groups[run.comparison_group].comparison_level] || groups[run.comparison_group].comparison_level)}</span></dd></div>
          <div><dt>근거</dt><dd><a href="${escapeHtml(provenanceHref(run))}" target="_blank" rel="noreferrer">정규화 결과 ↗</a></dd></div>
        </dl>
        <ul class="detail-notes">${run.notes.map(note => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`;
    }

    function selectRun(id) {
      selectedId = id;
      renderAll();
    }

    function updateMethod() {
      const groupId = document.getElementById('groupFilter').value;
      if (groupId === 'all') {
        document.getElementById('plotGroupLabel').textContent = '순위 비교 그룹만 시각화';
        document.getElementById('methodLimitations').innerHTML = [
          '전체 목록에는 workload와 런타임 조건이 다른 실행 기록이 함께 표시됩니다.',
          '순위와 성능 그래프는 OpenAI-compatible Quick 비교 그룹에만 적용하며, 다른 그룹의 수치는 해당 그룹 안에서만 해석해야 합니다.'
        ].map(item => `<li>${escapeHtml(item)}</li>`).join('');
        return;
      }
      const group = groups[groupId];
      document.getElementById('plotGroupLabel').textContent = group.label;
      document.getElementById('methodLimitations').innerHTML = group.limitations.map(item => `<li>${escapeHtml(item)}</li>`).join('');
    }

    ['searchInput', 'groupFilter', 'stageFilter', 'sortBy'].forEach(id => {
      const element = document.getElementById(id);
      element.addEventListener(id === 'searchInput' ? 'input' : 'change', () => {
        if (id === 'groupFilter') updateMethod();
        renderAll();
      });
    });

    setupPage();
  </script>
</body>
</html>
'''


if __name__ == "__main__":
    raise SystemExit(main())
