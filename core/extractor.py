"""
core/extractor.py
완성된 TEI-XML에서 개체명을 XPath로 추출하여 pandas DataFrame / CSV로 변환.

v2 3절 CSV 스키마:
  persons.csv         id, name, role, ref, frequency, context
  works.csv           id, title, level, type, creator, ref, frequency, context
  orgs.csv            id, name, ref, frequency, context
  concepts.csv        id, term, type, related_person, frequency, context
  quotes.csv          id, text, type, genre, source, context
  interpretations.csv id, text, value, ana, related_person, related_work, context
  dates.csv           id, text, when, context
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from lxml import etree


NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI_NS = "http://www.tei-c.org/ns/1.0"


# ── 내부 헬퍼 ────────────────────────────────────────────────────

def _xml_id(el: etree._Element) -> str:
    return el.get(f"{{{XML_NS}}}id", "")


def _text_content(el: etree._Element) -> str:
    """혼합 콘텐츠 요소의 전체 텍스트를 반환 (자식 요소 텍스트 포함)."""
    return (etree.tostring(el, method="text", encoding="unicode") or "").strip()


def _s_context(el: etree._Element, max_chars: int = 120) -> str:
    """가장 가까운 <s> 조상의 순수 텍스트를 반환. 없으면 부모 요소 텍스트."""
    node = el.getparent()
    while node is not None:
        if etree.QName(node.tag).localname == "s":
            text = etree.tostring(node, method="text", encoding="unicode")
            return text[:max_chars].replace("\n", " ").strip()
        node = node.getparent()
    parent = el.getparent()
    if parent is None:
        return ""
    text = etree.tostring(parent, method="text", encoding="unicode")
    return text[:max_chars].replace("\n", " ").strip()


def _sibling_ids_in_s(el: etree._Element, local_tag: str) -> str:
    """같은 <s> 안에 있는 특정 태그 요소들의 xml:id를 공백으로 연결하여 반환."""
    node = el.getparent()
    while node is not None:
        if etree.QName(node.tag).localname == "s":
            ids = [
                _xml_id(sib)
                for sib in node.iter(f"{{{TEI_NS}}}{local_tag}")
                if sib is not el and _xml_id(sib)
            ]
            return " ".join(ids)
        node = node.getparent()
    return ""


def _deduplicate_with_frequency(
    rows: list[dict], id_col: str = "id"
) -> list[dict]:
    """
    xml:id가 있는 행은 같은 id끼리 묶어 frequency를 계산하고 첫 번째 행만 유지.
    xml:id가 없는 행은 frequency=1로 그대로 유지.
    """
    from collections import Counter

    id_counts: Counter = Counter()
    for row in rows:
        key = row.get(id_col, "")
        if key:
            id_counts[key] += 1

    seen_ids: set[str] = set()
    result: list[dict] = []
    for row in rows:
        key = row.get(id_col, "")
        if key:
            if key in seen_ids:
                continue
            seen_ids.add(key)
            result.append({**row, "frequency": id_counts[key]})
        else:
            result.append({**row, "frequency": 1})
    return result


# ── 개체별 추출 함수 ─────────────────────────────────────────────

def extract_persons(tree: etree._Element) -> pd.DataFrame:
    """
    persName 추출 → persons.csv
    컬럼: id, name, role, ref, frequency, context
    """
    rows = []
    # body 내 persName만 추출 (teiHeader의 author 제외)
    for el in tree.xpath("//tei:text//tei:persName", namespaces=NS):
        rows.append({
            "id":      _xml_id(el),
            "name":    _text_content(el),
            "role":    el.get("role", ""),
            "ref":     el.get("ref", ""),
            "context": _s_context(el),
        })
    rows = _deduplicate_with_frequency(rows)
    cols = ["id", "name", "role", "ref", "frequency", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def extract_works(tree: etree._Element) -> pd.DataFrame:
    """
    title 추출 → works.csv
    컬럼: id, title, level, type, creator, ref, frequency, context
    creator = 같은 <s> 안에 있는 persName의 xml:id (첫 번째)
    """
    rows = []
    for el in tree.xpath("//tei:text//tei:title", namespaces=NS):
        # 같은 <s> 안의 첫 번째 persName id를 creator로
        creator_ids = _sibling_ids_in_s(el, "persName")
        creator = creator_ids.split()[0] if creator_ids else ""
        rows.append({
            "id":      _xml_id(el),
            "title":   _text_content(el),
            "level":   el.get("level", ""),
            "type":    el.get("type", ""),
            "creator": creator,
            "ref":     el.get("ref", ""),
            "context": _s_context(el),
        })
    rows = _deduplicate_with_frequency(rows)
    cols = ["id", "title", "level", "type", "creator", "ref", "frequency", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def extract_orgs(tree: etree._Element) -> pd.DataFrame:
    """
    orgName 추출 → orgs.csv
    컬럼: id, name, ref, frequency, context
    """
    rows = []
    for el in tree.xpath("//tei:text//tei:orgName", namespaces=NS):
        rows.append({
            "id":      _xml_id(el),
            "name":    _text_content(el),
            "ref":     el.get("ref", ""),
            "context": _s_context(el),
        })
    rows = _deduplicate_with_frequency(rows)
    cols = ["id", "name", "ref", "frequency", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def extract_concepts(tree: etree._Element) -> pd.DataFrame:
    """
    term 추출 → concepts.csv
    컬럼: id, term, type, related_person, frequency, context
    related_person = 같은 <s> 안의 persName xml:id 목록 (공백 구분)
    """
    rows = []
    for el in tree.xpath("//tei:text//tei:term", namespaces=NS):
        rows.append({
            "id":             _xml_id(el),
            "term":           _text_content(el),
            "type":           el.get("type", ""),
            "related_person": _sibling_ids_in_s(el, "persName"),
            "context":        _s_context(el),
        })
    rows = _deduplicate_with_frequency(rows)
    cols = ["id", "term", "type", "related_person", "frequency", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def extract_quotes(tree: etree._Element) -> pd.DataFrame:
    """
    quote 추출 → quotes.csv
    컬럼: id, text, type, genre, source, context
    """
    rows = []
    for el in tree.xpath("//tei:text//tei:quote", namespaces=NS):
        rows.append({
            "id":      _xml_id(el),
            "text":    _text_content(el),
            "type":    el.get("type", ""),
            "genre":   el.get("genre", ""),
            "source":  el.get("source", ""),
            "context": _s_context(el),
        })
    cols = ["id", "text", "type", "genre", "source", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def extract_interpretations(tree: etree._Element) -> pd.DataFrame:
    """
    interp 추출 → interpretations.csv
    컬럼: id, text, value, ana, related_person, related_work, context
    related_person = 같은 <s> 안의 persName xml:id
    related_work   = 같은 <s> 안의 title xml:id
    """
    rows = []
    for el in tree.xpath("//tei:text//tei:interp", namespaces=NS):
        rows.append({
            "id":             _xml_id(el),
            "text":           _text_content(el),
            "value":          el.get("value", ""),
            "ana":            el.get("ana", ""),
            "related_person": _sibling_ids_in_s(el, "persName"),
            "related_work":   _sibling_ids_in_s(el, "title"),
            "context":        _s_context(el),
        })
    cols = ["id", "text", "value", "ana", "related_person", "related_work", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def extract_dates(tree: etree._Element) -> pd.DataFrame:
    """
    date 추출 → dates.csv  (본문 <s> 내부 한정, teiHeader 제외)
    컬럼: id, text, when, context
    """
    rows = []
    for el in tree.xpath("//tei:text//tei:date", namespaces=NS):
        rows.append({
            "id":      _xml_id(el),
            "text":    _text_content(el),
            "when":    el.get("when", ""),
            "context": _s_context(el),
        })
    cols = ["id", "text", "when", "context"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


# ── 공개 API ─────────────────────────────────────────────────────

def extract_all(xml_string: str) -> dict[str, pd.DataFrame]:
    """
    TEI XML 문자열에서 모든 개체명을 추출하여 DataFrame dict로 반환한다.

    Keys: persons, works, orgs, concepts, quotes, interpretations, dates
    """
    root, err = _parse(xml_string)
    if root is None:
        raise ValueError(f"XML 파싱 실패: {err}")
    return {
        "persons":         extract_persons(root),
        "works":           extract_works(root),
        "orgs":            extract_orgs(root),
        "concepts":        extract_concepts(root),
        "quotes":          extract_quotes(root),
        "interpretations": extract_interpretations(root),
        "dates":           extract_dates(root),
    }


def to_csv(
    dataframes: dict[str, pd.DataFrame],
    output_dir: Path | str,
) -> dict[str, Path]:
    """
    DataFrame dict를 CSV 파일로 저장한다.

    Args:
        dataframes: extract_all()의 반환값
        output_dir: 저장할 디렉터리 경로

    Returns:
        {이름: 저장된 파일 경로} dict (빈 DataFrame은 저장 생략)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}
    for name, df in dataframes.items():
        if df.empty:
            continue
        path = output_dir / f"{name}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        saved[name] = path
    return saved


def _parse(xml_string: str) -> tuple[etree._Element | None, str]:
    try:
        return etree.fromstring(xml_string.encode("utf-8")), ""
    except etree.XMLSyntaxError as e:
        return None, str(e)
