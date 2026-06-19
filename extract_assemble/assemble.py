"""
extract_assemble/assemble.py
골격(섹션/문단/문장) + 라벨(span) → 유효한 TEI 문서로 조립하고 XSD 검증한다.

조립기가 구조를 만들므로 스키마 위반이 '구조적으로' 발생하지 않는다:
  - teiHeader: respStmt/sourceDesc(bibl)/encodingDesc(editorialDecl·tagsDecl·classDecl) 완비
  - 본문: div>p>s, s 안엔 허용 인라인만(date 제외), 비중첩, enum 스냅, id 유일

annotated_doc 형식:
  {"title": str, "author": str,
   "sections": [{"head": str|None, "type": "introduction"|"section"|...,
                 "paragraphs": [[{"text": s, "spans": [...]}, ...], ...]}]}
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from . import schema_rules as R

NS = R.NS
XML_ID = R.XML_ID
# v5 스키마: date를 SentenceType에 포함, DateType에 from/to, interp/quote mixed 등
SCHEMA_PATH = (Path(__file__).resolve().parent / "xsd"
               / "ver2-korean-critique-schema-v5.xsd")


def _E(parent, tag, text=None, **attrs):
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        el.text = text
    for k, v in attrs.items():
        el.set(k, v)
    return el


# ── 고정 taxonomy (RoleEnum / InterpValueEnum) ───────────────────

def _build_classdecl(parent):
    cd = _E(parent, "classDecl")
    tax_r = _E(cd, "taxonomy")
    tax_r.set(XML_ID, "tax-role")
    for rid, desc in [("critic", "비평가"), ("novelist", "소설가"), ("poet", "시인"),
                      ("playwright", "극작가"), ("essayist", "수필가"),
                      ("translator", "번역가"), ("childrenauthor", "아동문학가"),
                      ("scholar", "학자"), ("foreigner", "외국 문인"), ("other", "기타")]:
        cat = _E(tax_r, "category")
        cat.set(XML_ID, "role-" + rid)
        _E(cat, "catDesc", desc)
    tax_i = _E(cd, "taxonomy")
    tax_i.set(XML_ID, "tax-interp")
    for vid, desc in [("affirmative", "긍정"), ("neutral", "중립"), ("critical", "비판")]:
        cat = _E(tax_i, "category")
        cat.set(XML_ID, "interp-" + vid)
        _E(cat, "catDesc", desc)


def _build_header(parent, title: str, author: str):
    th = _E(parent, "teiHeader")
    fd = _E(th, "fileDesc")
    ts = _E(fd, "titleStmt")
    _E(ts, "title", title or "미상")
    _E(ts, "author", author or "미상")
    rs = _E(ts, "respStmt")
    _E(rs, "resp", "TEI 인코딩")
    _E(rs, "name", "KorCritTEI 추출-조립 파이프라인")
    pub = _E(fd, "publicationStmt")
    _E(pub, "p", "디지털 인문학 연구 목적")
    sd = _E(fd, "sourceDesc")
    _E(sd, "bibl", "입력 비평텍스트", type="other")
    ed = _E(th, "encodingDesc")
    edl = _E(ed, "editorialDecl")
    _E(edl, "p", "원문을 보존하고 인라인 태그만 삽입함. 구조는 코드가 조립함.")
    td = _E(ed, "tagsDecl")
    _E(td, "namespace")  # 이 스키마의 namespace는 name 속성을 받지 않음
    _build_classdecl(ed)


# ── 본문 조립 ─────────────────────────────────────────────────────

def assemble(annotated_doc: dict, allow_date: bool = True,
             source_text: str | None = None) -> str:
    """
    annotated_doc → TEI 문자열. allow_date=True면 인라인 date 포함(정답 관행).
    source_text를 주면 시 인용(genre=poet)을 원문 행 기준 lg/l 운문 구조로 조립.
    """
    tei = etree.Element(f"{{{NS}}}TEI", nsmap={None: NS})
    _build_header(tei, annotated_doc.get("title", ""), annotated_doc.get("author", ""))

    text_el = _E(tei, "text")
    body = _E(text_el, "body")
    ids = R.IdAllocator()

    sections = annotated_doc.get("sections") or []
    if not sections:
        sections = [{"head": None, "type": "body", "paragraphs": [[]]}]

    for sec in sections:
        div = _E(body, "div")
        dtype = sec.get("type", "section")
        div.set("type", dtype if dtype in R.DIV_TYPE else "section")
        if sec.get("head"):
            _E(div, "head", sec["head"])
        paras = sec.get("paragraphs") or []
        if not paras:
            paras = [[]]
        for para in paras:
            p_el = _E(div, "p")
            for sent in para:
                s_el = R.build_sentence(sent.get("text", ""), sent.get("spans", []),
                                        ids, allow_date=allow_date,
                                        source_text=source_text)
                p_el.append(s_el)
            if len(p_el) == 0 and not (p_el.text or "").strip():
                # 빈 문단 방지 (div는 p|div|list 최소 1 필요하므로 빈 p라도 허용됨)
                pass

    etree.cleanup_namespaces(tei)
    return etree.tostring(tei, pretty_print=True, xml_declaration=True,
                          encoding="UTF-8").decode("utf-8")


def validate(xml_str: str) -> tuple[bool, list[str]]:
    """조립 결과를 XSD로 검증. (ids 유일하므로 일반 파서로 충분)"""
    schema = etree.XMLSchema(etree.parse(str(SCHEMA_PATH)))
    root = etree.fromstring(xml_str.encode("utf-8"))
    ok = schema.validate(root)
    return ok, [f"줄{e.line}: {e.message}" for e in schema.error_log]


# ── 자체 시연 (API 불필요) — 까다로운 케이스로 유효성 증명 ─────────

_DEMO = {
    "title": "데모 비평",
    "author": "성현아",
    "sections": [
        {"head": "1. 서론", "type": "introduction", "paragraphs": [[
            {"text": "김동인은 1919년 창조를 창간했다.",
             "spans": [
                 {"text": "김동인", "tag": "persName", "attrs": {"role": "novelist critic"}},
                 {"text": "1919년", "tag": "date", "attrs": {"when": "1919"}},   # date→s에서 제외
                 {"text": "창조", "tag": "title", "attrs": {"level": "j", "type": "coterie"}},
             ]},
            {"text": "김동인의 자연주의는 이광수를 비판했다.",
             "spans": [
                 {"text": "김동인", "tag": "persName", "attrs": {"role": "novelist"}},  # 반복→ref
                 {"text": "자연주의", "tag": "term", "attrs": {"type": "movement"}},
                 {"text": "이광수", "tag": "persName", "attrs": {"role": "poetry"}},  # 잘못된 role→제거
                 {"text": "이광수를 비판했다", "tag": "interp",
                  "attrs": {"value": "critical"}},   # ana 누락→기본값, 단 이광수와 겹침→비중첩 처리
             ]},
        ]]},
    ],
}


def _demo():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    xml = assemble(_DEMO)
    ok, errs = validate(xml)
    print("=" * 56)
    print(f"조립 결과 XSD 검증: {'✅ 통과 (0 오류)' if ok else '❌ 실패'}")
    print("=" * 56)
    if errs:
        for e in errs:
            print("  ", e)
    print("\n[조립된 XML]\n")
    print(xml)


if __name__ == "__main__":
    _demo()
