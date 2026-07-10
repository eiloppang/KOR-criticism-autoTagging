"""
extract_assemble/corpus_analyze.py
mirea_results/ 의 태깅된 비평문 코퍼스를 종합 분석한다.

  ① 코퍼스 통계  — 인물·개념·작품·매체 빈도(총언급/등장 글 수), 역할 분포
  ② 담론 네트워크 — 인물 공동출현(essay 단위) + 비평가→시인 — Gephi용 CSV
  ③ 시간 추이    — 연도별 핵심 개념 빈도
  ⑤ 엔티티 정규화 — 괄호·따옴표·약칭 통합(창작과비평/《창비》→창비 등)

산출물 (mirea_results/_analysis/)
  corpus_dashboard.html         종합 대시보드
  persons.csv / concepts.csv / works.csv / orgs.csv   빈도표
  net_nodes.csv / net_edges.csv      인물 공동출현 네트워크(Gephi)
  critic_poet_edges.csv              비평가→시인 네트워크(Gephi)
  concept_by_year.csv                연도별 개념 빈도

사용
  python -m extract_assemble.corpus_analyze
"""
from __future__ import annotations

import csv
import html
import itertools
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import extractor  # noqa: E402

INDIR = ROOT / "mirea_results"
OUTDIR = INDIR / "_analysis"

# 약칭·변이형 통합
_ALIAS = {
    "창작과비평": "창비", "문지": "문학과지성사", "문학과지성": "문학과지성사",
    "문동": "문학동네", "문사": "문학과사회", "민음": "민음사",
    "랜덤하우스 중앙": "랜덤하우스중앙",
}
_PAREN = re.compile(r"[(（【\[][^)）】\]]*[)）】\]]")
_PUNCT = re.compile(r"[《》〈〉「」『』<>·,\.\s]")


def canon(text: str) -> str:
    t = _PAREN.sub("", text or "")
    t = _PUNCT.sub("", t)
    return _ALIAS.get(t, t)


def year_of(stem: str) -> int | None:
    yrs = re.findall(r"((?:19|20)\d{2})", stem)
    return int(yrs[-1]) if yrs else None


def esc(s):
    return html.escape(str(s))


# ── 집계 ──────────────────────────────────────────────────────────

def analyze():
    files = sorted(INDIR.glob("*_v2.xml"))
    total = {k: Counter() for k in ("persons", "concepts", "works", "orgs")}
    docf = {k: Counter() for k in ("persons", "concepts", "works", "orgs")}
    roles = defaultdict(Counter)        # person → role tokens
    cooc = Counter()                    # (a,b) 인물 공동출현(글 수)
    critic_poet = Counter()             # (critic, poet) → 언급수
    concept_year = defaultdict(Counter)  # year → concept counts
    year_docs = Counter()
    essays = []

    COLS = {"persons": "name", "works": "title", "concepts": "term", "orgs": "name"}

    for x in files:
        stem = x.stem.replace("_v2", "")
        author = canon(stem.split("_")[0])
        yr = year_of(stem)
        dfs = extractor.extract_all(x.read_text(encoding="utf-8"))
        essays.append((stem, author, yr))
        if yr:
            year_docs[yr] += 1

        persons_here = set()
        poets_here = Counter()
        for k, col in COLS.items():
            df = dfs.get(k)
            if df is None or df.empty:
                continue
            seen = set()
            for _, row in df.iterrows():
                name = canon(str(row.get(col, "")))
                if len(name) < 2:
                    continue
                freq = int(row.get("frequency", 1))
                total[k][name] += freq
                seen.add(name)
                if k == "persons":
                    persons_here.add(name)
                    rl = str(row.get("role", "")).split()
                    for r in rl:
                        roles[name][r] += 1
                    if "poet" in rl:
                        poets_here[name] += freq
                if k == "concepts" and yr:
                    concept_year[yr][name] += freq
            for name in seen:
                docf[k][name] += 1

        # 공동출현(글 단위): 등장 글 수가 많은 인물 위주 → 잡음 줄이려 글당 상위 인물만
        for a, b in itertools.combinations(sorted(persons_here), 2):
            cooc[(a, b)] += 1
        # 비평가→시인
        for poet, c in poets_here.items():
            if poet != author:
                critic_poet[(author, poet)] += c

    return dict(files=files, essays=essays, total=total, docf=docf, roles=roles,
                cooc=cooc, critic_poet=critic_poet, concept_year=concept_year,
                year_docs=year_docs)


# ── CSV 출력 ──────────────────────────────────────────────────────

def write_csvs(d):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for k, fname in [("persons", "persons"), ("concepts", "concepts"),
                     ("works", "works"), ("orgs", "orgs")]:
        with open(OUTDIR / f"{fname}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["entity", "total_mentions", "doc_freq"])
            for name, c in d["total"][k].most_common():
                w.writerow([name, c, d["docf"][k][name]])

    # 네트워크 노드/엣지 (등장 글 2편+ 인물, 공동출현 2+)
    keep = {n for n, c in d["docf"]["persons"].items() if c >= 2}
    with open(OUTDIR / "net_nodes.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Id", "Label", "mentions", "doc_freq", "main_role"])
        for n in keep:
            mr = d["roles"][n].most_common(1)[0][0] if d["roles"][n] else ""
            w.writerow([n, n, d["total"]["persons"][n], d["docf"]["persons"][n], mr])
    with open(OUTDIR / "net_edges.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Target", "Weight", "Type"])
        for (a, b), wt in d["cooc"].most_common():
            if wt >= 2 and a in keep and b in keep:
                w.writerow([a, b, wt, "Undirected"])
    with open(OUTDIR / "critic_poet_edges.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Target", "Weight", "Type"])
        for (c, p), wt in d["critic_poet"].most_common():
            w.writerow([c, p, wt, "Directed"])
    # 연도별 개념
    with open(OUTDIR / "concept_by_year.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "concept", "count"])
        for yr in sorted(d["concept_year"]):
            for term, c in d["concept_year"][yr].most_common(20):
                w.writerow([yr, term, c])


# ── HTML 대시보드 ─────────────────────────────────────────────────

def _bar_table(counter, docf, title, color, n=15, unit="회"):
    rows = counter.most_common(n)
    mx = rows[0][1] if rows else 1
    out = [f'<h3>{esc(title)}</h3><table>',
           '<tr><th>항목</th><th>총언급</th><th>글수</th><th></th></tr>']
    for name, c in rows:
        pct = c / mx * 100
        out.append(
            f'<tr><td>{esc(name)}</td><td class=n>{c}</td>'
            f'<td class=n>{docf[name]}</td>'
            f'<td class=barc><span class=bar style="width:{pct:.0f}%;background:{color}"></span></td></tr>')
    return "".join(out) + "</table>"


def build_html(d):
    essays = d["essays"]
    yrs = sorted(y for y in d["year_docs"])
    span = f"{yrs[0]}~{yrs[-1]}" if yrs else "-"
    tot_ent = sum(sum(d["total"][k].values()) for k in d["total"])

    # 역할 분포
    rolec = Counter()
    for n, rc in d["roles"].items():
        for r in rc:
            rolec[r] += 1

    # 연도별 핵심 개념 추이 (headline 6개)
    head = ["미래파", "서정", "서정시", "환상", "주체", "타자"]
    yr_rows = ""
    for yr in yrs:
        cc = d["concept_year"][yr]
        cells = "".join(f'<td class=n>{cc.get(h,0)}</td>' for h in head)
        top = ", ".join(t for t, _ in cc.most_common(4))
        yr_rows += (f'<tr><td>{yr}</td><td class=n>{d["year_docs"][yr]}</td>'
                    f'{cells}<td style="font-size:11px;color:#555">{esc(top)}</td></tr>')

    # 네트워크 상위 (공동출현 / 비평가→시인)
    cooc_rows = "".join(
        f'<tr><td>{esc(a)} — {esc(b)}</td><td class=n>{w}</td></tr>'
        for (a, b), w in d["cooc"].most_common(15) if w >= 2)
    cp_rows = "".join(
        f'<tr><td>{esc(c)} → {esc(p)}</td><td class=n>{w}</td></tr>'
        for (c, p), w in d["critic_poet"].most_common(15))

    role_rows = "".join(f'<span class=chip>{esc(r)} {c}</span>' for r, c in rolec.most_common())

    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>미래파 비평 코퍼스 분석</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f6fa;color:#1f2430;
font-family:'Malgun Gothic',system-ui,sans-serif;font-size:13.5px;line-height:1.55}}
.wrap{{max-width:1180px;margin:0 auto;padding:22px}}
h1{{font-size:22px;margin:0 0 2px}}.sub{{color:#6b7280;font-size:12.5px;margin-bottom:14px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}}
.card{{background:#fff;border:1px solid #e5e7ef;border-radius:10px;padding:12px 16px}}
.card .n{{font-size:22px;font-weight:800;color:#4C72B0}}.card .l{{font-size:11px;color:#888}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:780px){{.cols{{grid-template-columns:1fr}}}}
.panel{{background:#fff;border:1px solid #e5e7ef;border-radius:10px;padding:14px 16px;margin:10px 0}}
h2{{font-size:16px;margin:22px 0 6px;border-bottom:2px solid #e5e7ef;padding-bottom:4px}}
h3{{font-size:13.5px;margin:10px 0 6px;color:#333}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{text-align:left;padding:4px 7px;border-bottom:1px solid #eef0f5}}
th{{color:#888;font-weight:600;font-size:11px}}
td.n{{text-align:right;font-variant-numeric:tabular-nums;width:46px}}
td.barc{{width:34%}}.bar{{display:block;height:11px;border-radius:5px}}
.chip{{display:inline-block;background:#eef0f6;border-radius:11px;padding:2px 9px;margin:2px;font-size:11.5px}}
.note{{font-size:11.5px;color:#888;margin-top:6px}}
</style></head><body><div class=wrap>
<h1>미래파 비평 코퍼스 — 종합 분석</h1>
<div class=sub>{len(essays)}편 · {span} · 정규화 후 집계 · 네트워크는 Gephi용 CSV 동봉</div>
<div class=cards>
 <div class=card><div class=n>{len(essays)}</div><div class=l>비평문</div></div>
 <div class=card><div class=n>{tot_ent:,}</div><div class=l>총 개체 태깅</div></div>
 <div class=card><div class=n>{len(d['total']['persons']):,}</div><div class=l>고유 인물</div></div>
 <div class=card><div class=n>{len(d['total']['concepts']):,}</div><div class=l>고유 개념어</div></div>
 <div class=card><div class=n>{span}</div><div class=l>연도 범위</div></div>
</div>

<h2>① 코퍼스 통계</h2>
<div class=cols>
 <div class=panel>{_bar_table(d['total']['persons'], d['docf']['persons'], '인물 TOP', '#A14B6A')}</div>
 <div class=panel>{_bar_table(d['total']['concepts'], d['docf']['concepts'], '개념어 TOP', '#3F7A4E')}</div>
 <div class=panel>{_bar_table(d['total']['works'], d['docf']['works'], '작품·문헌 TOP', '#6A4BA1')}</div>
 <div class=panel>{_bar_table(d['total']['orgs'], d['docf']['orgs'], '기관·매체 TOP', '#2E6E9E')}</div>
</div>
<div class=panel><h3>인물 역할 분포 (고유 인물 기준)</h3>{role_rows}</div>

<h2>② 담론 네트워크 <span style="font-size:12px;color:#888">(Gephi용 CSV: net_edges.csv, critic_poet_edges.csv)</span></h2>
<div class=cols>
 <div class=panel><h3>인물 공동출현 TOP (같은 글에 함께 등장한 글 수)</h3>
   <table><tr><th>인물쌍</th><th>글수</th></tr>{cooc_rows}</table></div>
 <div class=panel><h3>비평가 → 시인 TOP (누가 누구를 논했나)</h3>
   <table><tr><th>비평가 → 시인</th><th>언급</th></tr>{cp_rows}</table></div>
</div>
<div class=note>net_nodes.csv/net_edges.csv 를 Gephi로 열면 미래파 담론 관계망을 시각화할 수 있습니다.</div>

<h2>③ 시간 추이 (연도별 핵심 개념 빈도)</h2>
<div class=panel><table>
<tr><th>연도</th><th>글수</th><th>미래파</th><th>서정</th><th>서정시</th><th>환상</th><th>주체</th><th>타자</th><th>그 해 상위 개념</th></tr>
{yr_rows}</table>
<div class=note>concept_by_year.csv 에 연도별 상위 20개 개념 전체.</div></div>

<div class=sub style="margin-top:24px">생성: extract_assemble/corpus_analyze.py</div>
</div></body></html>"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    d = analyze()
    write_csvs(d)
    (OUTDIR / "corpus_dashboard.html").write_text(build_html(d), encoding="utf-8")
    print(f"분석 완료 — {len(d['files'])}편")
    print(f"  대시보드: {OUTDIR / 'corpus_dashboard.html'}")
    print(f"  CSV: persons/concepts/works/orgs, net_nodes/net_edges, "
          f"critic_poet_edges, concept_by_year ({OUTDIR})")
    print(f"\n  인물 TOP5: " + ", ".join(f"{n}({c})" for n, c in d['total']['persons'].most_common(5)))
    print(f"  개념 TOP5: " + ", ".join(f"{n}({c})" for n, c in d['total']['concepts'].most_common(5)))


if __name__ == "__main__":
    main()
