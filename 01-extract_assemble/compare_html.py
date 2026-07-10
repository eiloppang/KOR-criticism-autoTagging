"""
extract_assemble/compare_html.py
두 TEI/XML(정답 A vs 자동 B)을 '문장 단위로 정렬'해 좌우로 비교하는 HTML 생성.

  - 두 문서의 문장을 평문 텍스트로 정렬(difflib) → 같은 내용이 같은 행에 놓임
  - 행마다 차이 분류:
      동일 · 속성만 다름(같은 태그, 다른 role/type 등) · 태그 구조 다름 · 한쪽에만 존재
  - 상단: 행 통계 + 태그별 A/B 개수, 범례(클릭 토글), 동기 스크롤은 단일 표라 불필요
  - 속성이 다른 행은 그 차이를 작은 줄로 표기 (예: date A[from/to] vs B[when])

사용:
  python -m extract_assemble.compare_html
  python -m extract_assemble.compare_html --gold <A.xml> --pred <B.xml> --out extract_assemble/비교.html
"""
from __future__ import annotations

import argparse
import difflib
import html
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent

NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": NS}

# 색상 + 표시할 핵심 속성(차이 비교 대상)
ENTITY = {
    "persName": ("#A14B6A", "인물", ("role",)),
    "term":     ("#3F7A4E", "개념어", ("type",)),
    "quote":    ("#B07A2A", "인용", ("type", "genre")),
    "title":    ("#6A4BA1", "작품·문헌", ("level", "type")),
    "date":     ("#2E6E9E", "연도", ("when", "from", "to")),
    "interp":   ("#9E2E2E", "해석", ("value", "ana")),
    "orgName":  ("#5A7A2E", "기관", ()),
    "note":     ("#777777", "각주", ()),
}
COUNT_TAGS = list(ENTITY) + ["l", "lg"]  # 통계에 포함


def esc(s) -> str:
    return html.escape(str(s or ""))


def _qn(el) -> str:
    return etree.QName(el).localname


def _hard(s: str) -> str:
    """정렬 키용: 공백·숫자·따옴표·낫표 제거 → 문장 매칭률 최대화."""
    s = re.sub(r"[「」『』《》〈〉\"'“”‘’]", "", s or "")
    return re.sub(r"\s+", "", re.sub(r"\d", "", s))


def _light(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _rel_attrs(tag: str, el) -> tuple:
    keys = ENTITY.get(tag, ("", "", ()))[2]
    vals = []
    for k in keys:
        v = (el.get(k) or "").strip()
        if k == "role":
            v = " ".join(sorted(v.split()))
        vals.append(f"{k}={v}" if v else "")
    return tuple(v for v in vals if v)


# ── 본문 → 정렬 단위(문장) 목록 ───────────────────────────────────

def _section_of(el) -> str | None:
    node = el.getparent()
    while node is not None:
        if _qn(node) == "div":
            h = node.find(f"{{{NS}}}head")
            if h is not None and (h.text or "").strip():
                return h.text.strip()
        node = node.getparent()
    return None


def render_inline(el) -> str:
    parts = []
    if el.text:
        parts.append(esc(el.text))
    for ch in el:
        tag = _qn(ch)
        inner = render_inline(ch)
        if tag in ENTITY:
            attrs = " ".join(f"{_qn_attr(k)}={v}" for k, v in ch.attrib.items()
                             if _qn_attr(k) != "id")
            parts.append(f'<span class="tg t-{tag}" title="{esc(attrs)}">{inner}'
                         f'<sup class="lbl">{tag.lower()}</sup></span>')
        elif tag == "lb":
            parts.append("<br>")
        elif tag == "l":   # 운문 행 → 줄바꿈
            parts.append(inner + "<br>")
        else:  # lg 등 컨테이너는 투명 처리
            parts.append(inner)
        if ch.tail:
            parts.append(esc(ch.tail))
    return "".join(parts)


def _qn_attr(k: str) -> str:
    return etree.QName(k).localname if "}" in k else k


def extract_units(root) -> list[dict]:
    """
    정렬 단위: <s> 를 문서 순서로. <s>는 내부의 quote/lg/l을 통째로 포함하므로
    그 안의 <l>은 따로 뽑지 않는다(중복·quote 맥락 손실 방지). <s> 밖의 <l>만 보강.
    """
    units = []
    for el in root.xpath("//tei:text//tei:s | //tei:text//tei:l[not(ancestor::tei:s)]",
                         namespaces=NSMAP):
        plain = "".join(el.itertext())
        recs = []
        for d in el.iter():
            t = _qn(d)
            if t in ENTITY:
                recs.append((t, _light("".join(d.itertext())), _rel_attrs(t, d)))
        units.append({
            "key": _hard(plain),
            "html": render_inline(el),
            "recs": recs,
            "sec": _section_of(el),
        })
    return units


# ── 정렬 + 행 분류 ────────────────────────────────────────────────

def classify(a: dict | None, b: dict | None):
    if a is None or b is None:
        return "only", []
    a_struct = Counter((t, txt) for t, txt, _ in a["recs"])
    b_struct = Counter((t, txt) for t, txt, _ in b["recs"])
    if a_struct != b_struct:
        return "struct", []
    # 같은 (태그,텍스트) 집합 → 속성 비교
    a_at = {(t, txt): at for t, txt, at in a["recs"]}
    b_at = {(t, txt): at for t, txt, at in b["recs"]}
    diffs = []
    for key in a_at:
        if a_at[key] != b_at.get(key):
            diffs.append((key[0], key[1], a_at[key], b_at.get(key, ())))
    if diffs:
        return "attr", diffs
    return "same", []


def align(A: list[dict], B: list[dict]) -> list[tuple]:
    sm = difflib.SequenceMatcher(None, [u["key"] for u in A], [u["key"] for u in B],
                                 autojunk=False)
    rows = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                rows.append((A[i1 + k], B[j1 + k]))
        elif op == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                a = A[i1 + k] if i1 + k < i2 else None
                b = B[j1 + k] if j1 + k < j2 else None
                rows.append((a, b))
        elif op == "delete":
            for k in range(i1, i2):
                rows.append((A[k], None))
        elif op == "insert":
            for k in range(j1, j2):
                rows.append((None, B[k]))
    return rows


# ── HTML ──────────────────────────────────────────────────────────

STATUS = {
    "same":   ("동일", "#cfd4dc"),
    "attr":   ("속성만 다름", "#E0A82E"),
    "struct": ("태그 구조 다름", "#C4351C"),
    "only":   ("한쪽에만", "#3B82C4"),
}


def _attr_diff_line(diffs) -> str:
    bits = []
    for tag, txt, a_at, b_at in diffs[:4]:
        a_s = " ".join(a_at) or "—"
        b_s = " ".join(b_at) or "—"
        bits.append(f'<b class="t-{tag}-fg">{esc(tag)}</b> "{esc(txt[:18])}" · '
                    f'A[{esc(a_s)}] vs B[{esc(b_s)}]')
    return " &nbsp;|&nbsp; ".join(bits)


def build(A_xml, B_xml, A_name, B_name) -> str:
    A = extract_units(etree.fromstring(A_xml.encode("utf-8"),
                                       parser=etree.XMLParser(collect_ids=False)))
    B = extract_units(etree.fromstring(B_xml.encode("utf-8"),
                                       parser=etree.XMLParser(collect_ids=False)))
    rows = align(A, B)

    # 통계
    stat = Counter()
    cur_sec = None
    body = []
    for a, b in rows:
        sec = (a or b or {}).get("sec")
        if sec != cur_sec:
            cur_sec = sec
            body.append(f'<div class="secrow">{esc(sec or "(머리말 없음)")}</div>')
        status, diffs = classify(a, b)
        stat[status] += 1
        _, color = STATUS[status]
        left = a["html"] if a else '<span class="empty">— 없음 —</span>'
        right = b["html"] if b else '<span class="empty">— 없음 —</span>'
        sub = (f'<div class="subdiff">차이 · {_attr_diff_line(diffs)}</div>'
               if status == "attr" else "")
        body.append(
            f'<div class="row" style="border-left:5px solid {color}">'
            f'<div class="cell a">{left}</div><div class="cell b">{right}</div>{sub}</div>'
        )

    # 태그별 A/B 개수
    def counts(units):
        c = Counter()
        for u in units:
            for t, _, _ in u["recs"]:
                c[t] += 1
        return c
    ca, cb = counts(A), counts(B)
    chips = "".join(
        f'<span class="chip" style="color:{ENTITY.get(t,("#666",))[0]}">'
        f'{t} <b>A {ca.get(t,0)}·B {cb.get(t,0)}</b></span>'
        for t in COUNT_TAGS if ca.get(t) or cb.get(t)
    )
    # 상단 통계 숫자
    statbar = "".join(
        f'<div class="stat"><div class="n" style="color:{c}">{stat.get(k,0)}</div>'
        f'<div class="l">{lbl}</div></div>'
        for k, (lbl, c) in STATUS.items()
    )
    statbar = (f'<div class="stat"><div class="n">{len(rows)}</div>'
               f'<div class="l">정렬된 행</div></div>') + statbar

    legend = "".join(
        f'<span data-t="{t}" style="background:{c}">{t} <i>{ko}</i></span>'
        for t, (c, ko, _) in ENTITY.items()
    )
    fg = "".join(f".t-{t}-fg{{color:{c}}}\n.t-{t}{{background:{c}1f;box-shadow:inset 0 -2px 0 {c}}}\n"
                 f".hide-{t} .t-{t}{{background:none;box-shadow:none}}\n"
                 f".hide-{t} .t-{t} .lbl{{display:none}}\n" for t, (c, _, _) in ENTITY.items())

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>정답 vs v2 — 문장 정렬 비교</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#eef0f4;color:#1f2430;font-family:'Malgun Gothic',system-ui,sans-serif;font-size:14px}}
.bar{{position:sticky;top:0;background:#e7e9ef;border-bottom:1px solid #d4d7e0;padding:10px 16px;z-index:5}}
.stats{{display:flex;gap:22px;align-items:flex-end;flex-wrap:wrap}}
.stat .n{{font-size:22px;font-weight:800}} .stat .l{{font-size:11px;color:#666}}
.chips{{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}}
.chip{{background:#fff;border:1px solid #d4d7e0;border-radius:14px;padding:3px 9px;font-size:11.5px}}
.legend{{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}}
.legend span{{cursor:pointer;color:#fff;border-radius:13px;padding:2px 9px;font-size:11.5px;user-select:none}}
.legend span i{{font-style:normal;opacity:.85}}
.legend span.off{{opacity:.32;text-decoration:line-through}}
.hdr{{display:grid;grid-template-columns:1fr 1fr;gap:0;background:#fff;border-bottom:2px solid #d4d7e0;
 font-weight:700;font-size:12.5px}}
.hdr div{{padding:8px 14px;border-left:5px solid transparent}}
.secrow{{background:#dfe3ea;font-weight:700;padding:7px 16px;font-size:13.5px;margin-top:2px}}
.row{{display:grid;grid-template-columns:1fr 1fr;background:#fff;border-bottom:1px solid #eceef3}}
.row .cell{{padding:8px 14px;line-height:1.95}}
.row .cell.a{{border-right:1px solid #eceef3}}
.subdiff{{grid-column:1/3;background:#fff7e6;border-top:1px dashed #e0c068;
 padding:4px 16px;font-size:11.5px;color:#7a5a10}}
.empty{{color:#bbb;font-style:italic}}
.tg{{border-radius:3px;padding:0 1px}}
.lbl{{font-size:8.5px;opacity:.7;margin-left:1px;font-weight:700}}
{fg}
</style></head><body>
<div class="bar">
  <div class="stats">{statbar}<div class="chips">{chips}</div></div>
  <div class="legend">{legend}</div>
</div>
<div class="hdr"><div>A · {esc(A_name)}</div><div>B · {esc(B_name)}</div></div>
{''.join(body)}
<script>
document.querySelectorAll('.legend span').forEach(s=>s.addEventListener('click',()=>{{
 s.classList.toggle('off');document.body.classList.toggle('hide-'+s.dataset.t);}}));
</script>
</body></html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gold", default=None)
    p.add_argument("--pred", default=None)
    p.add_argument("--out", default="extract_assemble/비교_정답_vs_v2.html")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    gold = Path(args.gold) if args.gold else next(ROOT.glob("자본주의*.xml"))
    pred = Path(args.pred) if args.pred else next(ROOT.glob("extract_assemble/*/3-*_v2.xml"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    htmlstr = build(gold.read_text(encoding="utf-8"), pred.read_text(encoding="utf-8"),
                    gold.name, pred.name)
    out.write_text(htmlstr, encoding="utf-8")
    print(f"비교 HTML 생성: {out} ({len(htmlstr):,} bytes)")
    print(f"  A 정답: {gold.name}\n  B v2  : {pred.name}")


if __name__ == "__main__":
    main()
