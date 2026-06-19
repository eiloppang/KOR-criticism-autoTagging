"""
experiments/build_analysis_report.py
태깅 출력 TEI/XML 하나를 분석하여 독립 실행형 HTML 리포트를 생성한다.

내용
  - 요약 카드 (개체 총수, 분량 커버리지, 섹션, 글자수)
  - 분량 분석 (원문 대비 커버리지 + 섹션 존재)
  - 개체 통계 (유형별 막대, 주요 인물/작품/용어, 역할·해석 분포)
  - 파이프라인 구성 + 이번 작업의 수정 내역 (문서)

사용
  python -m experiments.build_analysis_report \
      --xml 문제점/비평문아웃풋2.xml --source 비평문/성현아.txt \
      --out report/성현아_분석.html
"""
from __future__ import annotations

import argparse
import html
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import coverage as cov  # noqa: E402
from core import extractor  # noqa: E402

PALETTE = {
    "persons": "#4C72B0", "works": "#DD8452", "orgs": "#55A868",
    "concepts": "#C44E52", "quotes": "#8172B3", "interpretations": "#937860",
    "dates": "#DA8BC3",
}
TYPE_LABEL = {
    "persons": "인물 persName", "works": "작품 title", "orgs": "기관 orgName",
    "concepts": "용어 term", "quotes": "인용 quote",
    "interpretations": "해석 interp", "dates": "날짜 date",
}


def esc(s) -> str:
    return html.escape(str(s))


def bar(label, value, maxval, color="#4C72B0", suffix=""):
    pct = (value / maxval * 100) if maxval else 0
    return (
        f'<div class="bar-row"><span class="bar-label">{esc(label)}</span>'
        f'<span class="bar-track"><span class="bar-fill" style="width:{pct:.1f}%;'
        f'background:{color}"></span></span>'
        f'<span class="bar-val">{esc(value)}{esc(suffix)}</span></div>'
    )


def table(headers, rows):
    h = "".join(f"<th>{esc(x)}</th>" for x in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>"
    return f'<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>'


def analyze(xml_path: Path, source_path: Path | None):
    xml = xml_path.read_text(encoding="utf-8")
    dfs = extractor.extract_all(xml)

    # 유형별 개체 수 (고유/총빈도)
    type_stats = {}
    for key in TYPE_LABEL:
        df = dfs.get(key)
        if df is None or df.empty:
            type_stats[key] = (0, 0)
            continue
        uniq = len(df)
        total = int(df["frequency"].sum()) if "frequency" in df else len(df)
        type_stats[key] = (uniq, total)

    # 인물: 이름으로 묶어 진짜 빈도 + 역할 집합
    persons = dfs["persons"]
    person_rows, role_counter = [], Counter()
    if not persons.empty:
        g = persons.groupby("name").agg(
            freq=("frequency", "sum"),
            roles=("role", lambda s: " ".join(x for x in s if x)),
        ).reset_index()
        for _, row in g.iterrows():
            roleset = sorted(set(t for t in str(row["roles"]).split() if t))
            for r in roleset:
                role_counter[r] += 1
            person_rows.append((row["name"], int(row["freq"]), " ".join(roleset)))
        person_rows.sort(key=lambda x: -x[1])

    # 작품
    works = dfs["works"]
    work_rows = []
    if not works.empty:
        g = works.groupby("title").agg(
            freq=("frequency", "sum"),
            type=("type", lambda s: next((x for x in s if x), "")),
            level=("level", lambda s: next((x for x in s if x), "")),
        ).reset_index()
        for _, row in g.iterrows():
            work_rows.append((row["title"], int(row["freq"]), row["level"], row["type"]))
        work_rows.sort(key=lambda x: -x[1])

    # 용어
    concepts = dfs["concepts"]
    concept_rows = []
    if not concepts.empty:
        g = concepts.groupby("term").agg(freq=("frequency", "sum")).reset_index()
        concept_rows = sorted(
            [(r["term"], int(r["freq"])) for _, r in g.iterrows()], key=lambda x: -x[1])

    # 해석 가치 분포
    interp = dfs["interpretations"]
    interp_counter = Counter()
    if not interp.empty:
        for v in interp["value"]:
            interp_counter[v or "(미지정)"] += 1

    # 분량 커버리지
    cov_rep = None
    sections = []
    if source_path and source_path.exists():
        src = source_path.read_text(encoding="utf-8")
        cov_rep = cov.coverage(src, xml)
        out_norm = cov._norm(cov._body_text(xml))
        for name in ["분노 없이도", "나란히 노동자인 이들", "돌파 아닌 묘파", "번지기 위해"]:
            sections.append((name, cov._norm(name) in out_norm))

    return {
        "xml_chars": len(xml),
        "body_chars": len(cov._norm(cov._body_text(xml))),
        "type_stats": type_stats,
        "person_rows": person_rows,
        "work_rows": work_rows,
        "concept_rows": concept_rows,
        "role_counter": role_counter,
        "interp_counter": interp_counter,
        "coverage": cov_rep,
        "sections": sections,
    }


CSS = """
:root{--bg:#f7f7fb;--card:#fff;--ink:#1f2430;--mut:#6b7280;--line:#e6e8ef;--accent:#4C72B0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font-family:'Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif;line-height:1.6}
.wrap{max-width:980px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px;color:#333}
.sub{color:var(--mut);font-size:13px;margin-bottom:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card .num{font-size:26px;font-weight:700;color:var(--accent)}
.card .lab{font-size:12px;color:var(--mut)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:12px 0}
.bar-row{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:13px}
.bar-label{width:160px;flex:none;color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{flex:1;background:#eef0f6;border-radius:6px;height:16px;overflow:hidden}
.bar-fill{display:block;height:100%;border-radius:6px}
.bar-val{width:54px;flex:none;text-align:right;color:#555;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:12px}
td:nth-child(2){font-variant-numeric:tabular-nums}
.ok{color:#1a7f37;font-weight:700}.no{color:#c4351c;font-weight:700}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:720px){.cols{grid-template-columns:1fr}.bar-label{width:110px}}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:10px 0;font-size:13px}
.step{background:#eef2fb;border:1px solid #d6e0f5;border-radius:8px;padding:7px 11px;font-weight:600}
.arr{color:#9aa3b2;font-weight:700}
.tag{display:inline-block;background:#eef0f6;border-radius:5px;padding:1px 7px;font-size:12px;color:#444;margin:1px}
code{background:#f0f1f5;padding:1px 6px;border-radius:5px;font-size:12.5px}
.note{font-size:12.5px;color:var(--mut);margin-top:6px}
"""


def build_html(xml_name, data) -> str:
    ts = data["type_stats"]
    total_uniq = sum(u for u, _ in ts.values())
    total_all = sum(t for _, t in ts.values())
    cov_rep = data["coverage"]

    # 요약 카드
    cards = [
        ("개체 (고유)", f"{total_uniq:,}", "persName·title·term 등"),
        ("개체 (총 등장)", f"{total_all:,}", "빈도 합산"),
        ("본문 글자", f"{data['body_chars']:,}", "정규화 기준"),
    ]
    if cov_rep:
        cards.insert(0, ("문장 커버리지",
                        f"{cov_rep['sentence_ratio']*100:.1f}%",
                        f"{cov_rep['covered']}/{cov_rep['n_sentences']} 문장"))
    cards_html = "".join(
        f'<div class="card"><div class="num">{esc(n)}</div>'
        f'<div class="lab">{esc(l)}<br>{esc(s)}</div></div>'
        for l, n, s in cards
    )

    # 분량 섹션
    cov_html = ""
    if cov_rep:
        secrows = "".join(
            f'<tr><td>{esc(name)}</td><td>'
            f'{"<span class=ok>포함 ✓</span>" if ok else "<span class=no>누락 ✗</span>"}'
            f'</td></tr>'
            for name, ok in data["sections"]
        )
        cov_html = f"""
        <div class="panel">
          {bar("문장 커버리지", round(cov_rep['sentence_ratio']*100,1), 100, "#55A868", "%")}
          {bar("글자 커버리지", round(cov_rep['char_ratio']*100,1), 100, "#4C72B0", "%")}
          <div class="note">원문 {cov_rep['src_chars']:,}자 → 출력 본문 {cov_rep['out_chars']:,}자.
          누락 의심 {cov_rep['missing']}건은 대부분 각주 번호·메타(제목/이메일)·잡음 줄로 인한 오탐.</div>
          <h3>4개 섹션 존재 확인</h3>
          <table><thead><tr><th>섹션</th><th>출력 내 존재</th></tr></thead><tbody>{secrows}</tbody></table>
        </div>"""

    # 유형별 막대
    maxtype = max((t for _, t in ts.values()), default=1)
    type_bars = "".join(
        bar(TYPE_LABEL[k], ts[k][1], maxtype, PALETTE[k])
        for k in TYPE_LABEL
    )

    # 주요 인물/작품/용어
    persons_tbl = table(["인물", "등장", "역할(role)"], data["person_rows"][:15]) \
        if data["person_rows"] else "<p class=note>없음</p>"
    works_tbl = table(["작품", "등장", "level", "type"], data["work_rows"][:15]) \
        if data["work_rows"] else "<p class=note>없음</p>"
    concepts_tbl = table(["용어", "등장"], data["concept_rows"][:15]) \
        if data["concept_rows"] else "<p class=note>없음</p>"

    # 역할 분포
    rc = data["role_counter"]
    maxrole = max(rc.values(), default=1)
    role_bars = "".join(
        bar(r, c, maxrole, "#4C72B0", "명")
        for r, c in rc.most_common()
    ) or "<p class=note>없음</p>"

    # 해석 분포
    ic = data["interp_counter"]
    interp_color = {"affirmative": "#55A868", "neutral": "#999", "critical": "#C44E52"}
    maxint = max(ic.values(), default=1)
    interp_bars = "".join(
        bar(k, v, maxint, interp_color.get(k, "#8172B3"))
        for k, v in ic.most_common()
    ) or "<p class=note>없음</p>"

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>성현아 비평문 태깅 분석</title>
<style>{CSS}</style></head>
<body><div class="wrap">

<h1>성현아 비평문 — TEI 태깅 분석 리포트</h1>
<div class="sub">대상: <code>{esc(xml_name)}</code> · 한국문학비평 TEI 자동 태깅 (KorCritTEI)</div>
<div class="cards">{cards_html}</div>

<h2>1. 분량 검증</h2>
<p class="sub">원문이 빠짐없이 태그됐는지 — 문장·글자 커버리지와 4개 섹션 존재 확인</p>
{cov_html}

<h2>2. 개체 통계</h2>
<div class="panel">
  <h3>유형별 태깅 개체 (총 등장 횟수)</h3>
  {type_bars}
</div>
<div class="cols">
  <div class="panel"><h3>역할(role) 분포 — 인물 수</h3>{role_bars}</div>
  <div class="panel"><h3>해석(interp) 가치 분포</h3>{interp_bars}</div>
</div>

<h2>3. 주요 개체</h2>
<div class="panel"><h3>인물 (등장 빈도순)</h3>{persons_tbl}
<div class="note">※ id가 인물별로 통일되기 전이라 본 표는 <b>이름 기준</b>으로 합산함.</div></div>
<div class="cols">
  <div class="panel"><h3>작품</h3>{works_tbl}</div>
  <div class="panel"><h3>용어·개념</h3>{concepts_tbl}</div>
</div>

<h2>4. 파이프라인 구성</h2>
<div class="panel">
<div class="flow">
  <span class="step">입력 텍스트</span><span class="arr">→</span>
  <span class="step">AdaptiveChunker<br>청크 분할(5,000자)</span><span class="arr">→</span>
  <span class="step">DictionaryMatcher<br>사전 매칭</span><span class="arr">→</span>
  <span class="step">LLM Provider<br>Gemini/Claude/Ollama</span>
</div>
<div class="flow">
  <span class="arr">→</span>
  <span class="step">_merge_body_divs<br>청크 병합</span><span class="arr">→</span>
  <span class="step">_finalize_tei<br>헤더 재구성·id 통일</span><span class="arr">→</span>
  <span class="step">validate_xml<br>XSD 검증</span><span class="arr">→</span>
  <span class="step">extractor<br>개체 추출·CSV</span>
</div>
<p class="note">LLM Provider는 공통 인터페이스(<code>LLMProvider.generate_tei</code>)로 교체 가능.
첫 청크는 완전한 TEI 문서, 이후 청크는 <code>text&gt;body&gt;div</code>만 출력 후 병합.</p>
</div>

<h3>비교 실험을 위한 3개 태깅 모드</h3>
<div class="panel">
{table(["모드", "구성", "용도"], [
  ["schema_only (1단계)", "스키마+규칙만, 사전·예시 제거", "zero-shot 기준선"],
  ["pipeline (2단계)", "사전매칭+내장예시+청킹+후처리", "현재 설계 시스템"],
  ["few_shot (4단계)", "수작업 정답을 예시로 주입(ICL)", "'학습' 효과 측정"],
])}
<p class="note">정답(gold) 대비 <code>core/evaluation.py</code>가 태그별 정밀도/재현율/F1을 느슨·엄격 두 수준으로 채점.
Claude는 파인튜닝 불가 → <b>Few-shot In-Context Learning</b>으로 '학습' 구현.</p>
</div>

<h2>5. 이번 작업의 수정 내역</h2>
<div class="panel">
<h3>버그 수정</h3>
{table(["파일", "문제", "수정"], [
  ["extractor._parse", "중복 xml:id → 파싱 거부(개체명·시각화 탭 다운)", "collect_ids=False 파서"],
  ["extractor._text_content", "이름에 조사 섞임(신해욱의→)", "itertext()로 꼬리말 제외"],
  ["experiment_tab", "위젯 키와 세션 키 충돌(StreamlitAPIException)", "exp_gold → exp_gold_xml"],
])}
<h3>신규 도구</h3>
{table(["모듈", "역할"], [
  ["core/evaluation.py", "두 TEI 비교 → 태그별 P/R/F1 (느슨/엄격)"],
  ["core/coverage.py", "원문 대비 분량 누락 검사(문장 커버리지)"],
  ["core/cleanup.py", "정답 초안 정리: id 통일·잡음 제거·낫표 정리"],
  ["ui/experiment_tab.py", "화면에서 3모드 비교 실행"],
  ["experiments/run_comparison.py", "CLI 비교 실험 드라이버"],
])}
<div class="note">미해결: 청크 경계에서 간헐적 분량 손실(실행마다 다를 수 있음) — '태깅 후 자동 분량검사→재태깅' 안전장치 검토 중.
id 파편화(최백규 다수 id)는 <code>core/cleanup.py</code>로 통일 예정.</div>
</div>

<div class="sub" style="margin-top:30px">생성: <code>experiments/build_analysis_report.py</code> · KorCritTEI</div>
</div></body></html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--xml", default="문제점/비평문아웃풋2.xml")
    p.add_argument("--source", default="비평문/성현아.txt")
    p.add_argument("--out", default="report/성현아_분석.html")
    args = p.parse_args()

    xml_path = Path(args.xml)
    source_path = Path(args.source) if args.source else None
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = analyze(xml_path, source_path)
    html_str = build_html(xml_path.name, data)
    out_path.write_text(html_str, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"리포트 생성: {out_path}  ({len(html_str):,} bytes)")


if __name__ == "__main__":
    main()
