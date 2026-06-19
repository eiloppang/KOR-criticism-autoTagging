"""
extract_assemble/schema_rules.py
korean-critique-schema.xsd 를 코드로 강제하는 규칙 모음.

  - 각 태그의 enum 허용값 (XSD에서 그대로 옮김)
  - clean_attrs(): 속성을 허용값으로 스냅, 위반 제거, 필수 보강
  - IdAllocator: xml:id 유일화 (첫 등장 xml:id, 반복 ref="#id")
  - build_sentence(): 문장+span → <s> 조립 (중첩 방지, date 정책)
"""
from __future__ import annotations

import functools
import re
from lxml import etree

NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


# ── enum 허용값 (XSD 그대로) ──────────────────────────────────────
ROLE = {"critic", "novelist", "poet", "playwright", "essayist",
        "translator", "childrenauthor", "scholar", "foreigner", "writer", "other"}
TITLE_LEVEL = {"m", "a", "j"}
TITLE_TYPE = {"critic", "novel", "poem", "play", "essay", "translation",
              "children", "contribution", "foreign", "other",
              "journal", "newspaper", "coterie", "publication"}
QUOTE_TYPE = {"direct", "indirect", "paraphrase", "contribution",
              "criticism", "review", "commentary"}
QUOTE_GENRE = {"critic", "novel", "poet", "play", "essay", "translation",
               "children", "contribution", "foreign", "other"}
INTERP_VALUE = {"affirmative", "neutral", "critical"}
DIV_TYPE = {"contents", "introduction", "body", "conclusion", "section",
            "argument", "criticism", "review", "editorial", "column",
            "interview", "notes"}

# <s> 안에 허용되는 인라인 태그 (★ date 없음 — 스키마 미정의)
ALLOWED_IN_S = {"persName", "title", "orgName", "term", "quote",
                "interp", "note", "ref", "lb"}

# 라틴 음역 prefix
ID_PREFIX = {"persName": "p", "title": "t", "orgName": "org"}


def _snap(value: str, allowed: set, default: str | None = None) -> str | None:
    """value가 허용값이면 그대로, 아니면 default(없으면 None=속성 제거)."""
    v = (value or "").strip()
    return v if v in allowed else default


def _date_attrs(surface: str, when_hint: str) -> dict:
    """
    날짜 표면형으로 when / from·to 결정 (v5 DateType).
      'N0년대'(10년대) → from/to (예: 2010년대 → from=2010 to=2019)
      단일 연도        → when   (예: 2015년 → when=2015)
    """
    m = re.search(r"(\d{4})\s*년\s*대", surface)
    if m:
        base = int(m.group(1)) - int(m.group(1)) % 10
        return {"from": str(base), "to": str(base + 9)}
    m = re.search(r"\d{4}", surface) or re.search(r"\d{4}", when_hint or "")
    if m:
        return {"when": m.group(0)}
    return {"when": when_hint} if when_hint else {}


def clean_attrs(tag: str, attrs: dict, surface: str = "") -> dict:
    """
    태그별로 속성을 스키마 허용값으로 정제한다. (xml:id/ref는 IdAllocator가 별도 처리)
    위반 속성은 제거하고, 필수 속성(interp/@ana)은 기본값으로 보강한다.
    surface: 해당 요소의 표면 텍스트(date의 when/from·to 판단에 사용).
    """
    a = {k: str(v).strip() for k, v in (attrs or {}).items() if str(v).strip()}
    out: dict = {}

    if tag == "persName":
        roles = [t for t in a.get("role", "").split() if t in ROLE]
        if roles:
            out["role"] = " ".join(dict.fromkeys(roles))  # 중복 제거, 순서 보존
    elif tag == "title":
        lv = _snap(a.get("level", ""), TITLE_LEVEL)
        ty = _snap(a.get("type", ""), TITLE_TYPE)
        if lv:
            out["level"] = lv
        if ty:
            out["type"] = ty
    elif tag == "term":
        if a.get("type"):
            out["type"] = a["type"]  # term/@type 은 자유 문자열
    elif tag == "quote":
        ty = _snap(a.get("type", ""), QUOTE_TYPE)
        ge = _snap(a.get("genre", ""), QUOTE_GENRE)
        if ty:
            out["type"] = ty
        if ge:
            out["genre"] = ge
        if a.get("source"):
            out["source"] = a["source"]
        # ana 는 IDREFS(실존 id 참조)라야 유효 → 임의 문자열 금지: 생략
    elif tag == "interp":
        val = _snap(a.get("value", ""), INTERP_VALUE)
        if val:
            out["value"] = val
        out["ana"] = a.get("ana") or "기타"  # ★ 필수
    elif tag == "date":
        out.update(_date_attrs(surface, a.get("when", "")))
    # orgName: 추가 속성 없음
    return out


class IdAllocator:
    """
    (태그, 정규화 텍스트) 단위로 xml:id를 유일하게 발급.
    첫 등장 → xml:id 부여. 반복 → ref="#firstid" (xml:id 없음) → ID 고유성 보장.
    persName/title/orgName 만 id 대상.
    """

    def __init__(self):
        self._canonical: dict[tuple, str] = {}
        self._used: set[str] = set()

    def _slug(self, tag: str, text: str) -> str:
        base = re.sub(r"[^a-z0-9]", "", text.lower()) or "x"
        cand = f"{ID_PREFIX.get(tag, 'x')}-{base[:24]}"
        i, uniq = 2, cand
        while uniq in self._used:
            uniq = f"{cand}{i}"
            i += 1
        self._used.add(uniq)
        return uniq

    def assign(self, tag: str, text: str) -> dict:
        """반환: {'xml:id': id} (첫 등장) 또는 {'ref': '#id'} (반복) 또는 {}."""
        if tag not in ID_PREFIX:
            return {}
        key = (tag, re.sub(r"\s+", "", text))
        if key in self._canonical:
            return {"ref": "#" + self._canonical[key]}
        new_id = self._slug(tag, text)
        self._canonical[key] = new_id
        return {XML_ID: new_id}


def _resolve_spans(text: str, spans: list[dict], allowed: set) -> list[dict]:
    """
    각 span의 문자 위치를 찾고, 겹치는 span은 제거(비중첩만) → 중첩 위반 방지.
    allowed 에 없는 태그는 제외(텍스트로 남김).
    """
    placed = []
    cursor_used = []  # (start,end) 점유 구간
    # 문서 순서 유지하되, 텍스트 등장 위치로 정렬
    located = []
    search_from: dict[str, int] = {}
    for sp in spans:
        tag = sp.get("tag", "")
        frag = (sp.get("text") or "").strip()
        if tag not in allowed or not frag:
            continue
        start = text.find(frag, search_from.get(frag, 0))
        if start < 0:
            continue
        end = start + len(frag)
        search_from[frag] = end
        located.append((start, end, sp))
    located.sort(key=lambda x: (x[0], -(x[1] - x[0])))  # 시작 빠른·긴 것 우선
    for start, end, sp in located:
        if any(not (end <= s or start >= e) for s, e in cursor_used):
            continue  # 겹침 → 버림(비중첩 보장)
        cursor_used.append((start, end))
        placed.append((start, end, sp))
    placed.sort(key=lambda x: x[0])
    return placed


# ── 시 인용 → 운문(lg/l) 구조 복원 ───────────────────────────────
# structure 단계에서 PDF 줄바꿈을 없앴으므로, 원문에서 행 위치를 되찾아 분리한다.

_ELLIPSIS = re.compile(r"^[(（\[]?\s*(?:…+|⋯+|\.{2,})\s*[)）\]]?$")


@functools.lru_cache(maxsize=2)
def _source_index(source: str):
    """원문의 (공백 제거 문자열, 각 문자→원문 위치 map)."""
    nospace, posmap = [], []
    for i, ch in enumerate(source):
        if not ch.isspace():
            nospace.append(ch)
            posmap.append(i)
    return "".join(nospace), tuple(posmap)


def _recover_lines(surface: str, source: str) -> list[str] | None:
    """인용 표면형을 원문에서 찾아, 원문 줄바꿈으로 나눈 행 목록을 반환."""
    nospace, posmap = _source_index(source)
    key = re.sub(r"\s", "", surface)
    if not key:
        return None
    j = nospace.find(key)
    if j < 0:
        return None
    s, e = posmap[j], posmap[j + len(key) - 1]
    return source[s:e + 1].split("\n")


def _build_quote_verse(quote_el, surface: str, source: str) -> bool:
    """시 인용(여러 행)을 <lg type="stanza"><l>…</l></lg> 로 채운다. 단행이면 False."""
    lines = _recover_lines(surface, source)
    if not lines:
        return False
    real = [ln.strip() for ln in lines if ln.strip()]
    if len(real) <= 1:
        return False
    for ln in real:
        if _ELLIPSIS.match(ln):
            note = etree.SubElement(quote_el, f"{{{NS}}}note")
            note.set("type", "ellipsis")
            note.text = ln
        else:
            lg = etree.SubElement(quote_el, f"{{{NS}}}lg")
            lg.set("type", "stanza")
            etree.SubElement(lg, f"{{{NS}}}l").text = ln
    return True


def build_sentence(text: str, spans: list[dict], ids: IdAllocator,
                   allow_date: bool = True, source_text: str | None = None):
    """
    문장 텍스트 + span 라벨 → <s> 요소. 텍스트는 보존, 태그만 삽입.

    allow_date=True: 정답 관행대로 <date when="">를 인라인으로 단다. 단 현 XSD는
    SentenceType에 date를 정의하지 않아 'date 한정' 검증 경고가 남는다(알려진 공백).
    allow_date=False: date를 텍스트로만 남겨 완전 무결 XSD를 원할 때.
    """
    s_el = etree.Element(f"{{{NS}}}s")
    allowed = ALLOWED_IN_S | ({"date"} if allow_date else set())
    placed = _resolve_spans(text, spans, allowed)

    last = 0
    prev_el = None

    def add_text(chunk):
        nonlocal prev_el
        if not chunk:
            return
        if prev_el is None:
            s_el.text = (s_el.text or "") + chunk
        else:
            prev_el.tail = (prev_el.tail or "") + chunk

    for start, end, sp in placed:
        add_text(text[last:start])
        tag = sp["tag"]
        surface = text[start:end]
        el = etree.SubElement(s_el, f"{{{NS}}}{tag}")
        id_attrs = ids.assign(tag, surface)
        # 정답 관행: persName은 첫 등장(xml:id)만 role, 반복(ref)은 참조만.
        # title/orgName은 반복에도 level/type 유지(정답이 그러함).
        drop_attrs = "ref" in id_attrs and tag == "persName"
        attrs = {} if drop_attrs else clean_attrs(tag, sp.get("attrs", {}), surface=surface)
        # 시 인용(genre=poet, 여러 행)은 lg/l 운문 구조로, 그 외엔 평문
        verse = (tag == "quote" and source_text and attrs.get("genre") == "poet"
                 and _build_quote_verse(el, surface, source_text))
        if not verse:
            el.text = surface
        for k, v in attrs.items():
            el.set(k, v)
        for k, v in id_attrs.items():
            el.set(k, v)
        prev_el = el
        last = end
    add_text(text[last:])
    return s_el
