"""
core/cleanup.py
태깅 출력 TEI/XML을 정답(gold) 초안 수준으로 정리하는 후처리 모듈.

적용 규칙 (문제점/성현아-태깅-문제점.md 의 P1~P3)
  P1: 같은 인물/작품 id 통일 (텍스트 기준) + persName role 순서 정렬
      → 최백규 13개 id → 1개, 양경언 음역 3종 → 1개 (방식 A: 같은 id로 통일)
  P2: 잡음 제거
      - 인용문 내용이 생략부호/구두점뿐인 것 ('(…)' 등) → 제거
      - 소셜 공유버튼 텍스트('FacebookTwitterKakaoLine' 등) 줄 제거
  P3: 작품 제목 낫표(「」『』) 제거 (텍스트만 남기고 표기기호 제외)

사용
  from core.cleanup import clean_tagging
  cleaned_xml, report = clean_tagging(xml_string)

  # CLI
  python -m core.cleanup 입력.xml 출력.xml
"""
from __future__ import annotations

import re

from .tagger import _dedup_xml_ids

NS = "http://www.tei-c.org/ns/1.0"

# 생략부호·구두점뿐인 인용 (내용 없음) — 비어 있지 않되 글자가 없음
_ELLIPSIS_ONLY = re.compile(r"^[\s()\[\]…·.\-—~]*$")
# 소셜 공유버튼/메타 잡음 줄
_SOCIAL_JUNK = re.compile(
    r"^(Facebook|Twitter|Kakao(Story|Talk)?|Line|Band|Share|URL\s*복사|공유하기|좋아요)+$",
    re.IGNORECASE,
)
_TITLE_BRACKETS = "「」『』"


def _strip_chars(el, chars: str) -> bool:
    """요소 내부 텍스트(자식 텍스트·꼬리말 포함, 단 el 자신의 tail 제외)에서 chars를 제거."""
    trans = str.maketrans("", "", chars)
    changed = False
    if el.text and any(c in el.text for c in chars):
        el.text = el.text.translate(trans); changed = True
    for child in el.iterdescendants():
        if child.text and any(c in child.text for c in chars):
            child.text = child.text.translate(trans); changed = True
        if child.tail and any(c in child.tail for c in chars):
            child.tail = child.tail.translate(trans); changed = True
    return changed


def _el_text(el) -> str:
    return "".join(el.itertext()).strip()


def clean_tagging(xml_string: str) -> tuple[str, dict]:
    """
    태깅 XML을 정리하여 (정리된_xml, 리포트dict)를 반환한다.
    리포트: 각 규칙으로 처리한 건수.
    """
    from lxml import etree

    parser = etree.XMLParser(collect_ids=False)
    root = etree.fromstring(xml_string.encode("utf-8"), parser=parser)

    report = {
        "noise_quotes_removed": 0,
        "social_lines_removed": 0,
        "titles_debracketed": 0,
        "roles_normalized": 0,
        "empty_nodes_pruned": 0,
    }

    # ── P3: 제목 낫표 제거 (dedup 전에 해야 같은 제목이 합쳐짐) ──
    for title in root.iter(f"{{{NS}}}title"):
        if _strip_chars(title, _TITLE_BRACKETS):
            report["titles_debracketed"] += 1

    # ── P2a: 잡음 인용(생략부호뿐) 제거 ──
    for quote in list(root.iter(f"{{{NS}}}quote")):
        if _ELLIPSIS_ONLY.match(_el_text(quote)):
            parent = quote.getparent()
            if parent is not None:
                parent.remove(quote)
                report["noise_quotes_removed"] += 1

    # ── P2b: 소셜 공유버튼 줄 제거 ──
    for s in list(root.iter(f"{{{NS}}}s")):
        if len(s) == 0 and _SOCIAL_JUNK.match(_el_text(s)):
            parent = s.getparent()
            if parent is not None:
                parent.remove(s)
                report["social_lines_removed"] += 1

    # ── 빈 노드 정리 (잡음 제거로 비워진 s/p) ──
    for tag in ("s", "p"):
        for el in list(root.iter(f"{{{NS}}}{tag}")):
            if len(el) == 0 and not (el.text and el.text.strip()):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
                    report["empty_nodes_pruned"] += 1

    # ── P1a: persName role 순서 정렬 (집합 동일, 표기만 통일) ──
    for pers in root.iter(f"{{{NS}}}persName"):
        role = pers.get("role")
        if role:
            normed = " ".join(sorted(t for t in role.split() if t))
            if normed != role:
                pers.set("role", normed)
                report["roles_normalized"] += 1

    # ── P1b: id 통일 (텍스트 기준; 방식 A = 같은 id로 통일) ──
    _dedup_xml_ids(root)

    # 기본 네임스페이스 확보 후 직렬화
    if root.nsmap.get(None) != NS:
        new_root = etree.Element(root.tag, attrib=dict(root.attrib), nsmap={None: NS})
        for child in list(root):
            new_root.append(child)
        root = new_root
    etree.cleanup_namespaces(root)
    cleaned = etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    ).decode("utf-8")
    return cleaned, report


def _format_report(report: dict) -> str:
    return "\n".join(
        f"  · {k}: {v}" for k, v in report.items()
    )


# ── CLI / 자체 시연 ───────────────────────────────────────────────

_DEMO = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
 <teiHeader><fileDesc><titleStmt><title>데모</title><author>미상</author></titleStmt>
 <publicationStmt><p>x</p></publicationStmt><sourceDesc><p>x</p></sourceDesc></fileDesc></teiHeader>
 <text><body><div type="body">
  <p><s><persName xml:id="p-choi" role="poet">최백규</persName>의
     <title xml:id="t-a" level="a" type="poem">「장마철」</title>.</s>
   <s><persName xml:id="p-choi2" role="poet">최백규</persName>는
     <title xml:id="t-a2" level="a" type="poem">장마철</title>를 썼다.</s>
   <s><persName xml:id="p-yang1" role="critic">양경언</persName>과
     <persName xml:id="p-yang2" role="critic">양경언</persName>.</s>
   <s><quote type="direct" genre="poet" source="장마철">(…)</quote></s>
   <s>FacebookTwitterKakaoLine</s>
   <s><persName xml:id="p-fisher" role="foreigner scholar">마크 피셔</persName>와
     <persName xml:id="p-fisher2" role="scholar foreigner">마크 피셔</persName>.</s></p>
 </div></body></text></TEI>"""


def _demo() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from core import evaluation

    cleaned, report = clean_tagging(_DEMO)
    print("=== 정리 리포트 ===")
    print(_format_report(report))
    print("\n=== 정리 전/후 개체 (인물·작품) ===")
    for label, xml in [("전", _DEMO), ("후", cleaned)]:
        ann = evaluation.extract_annotations(xml, strict=True)
        pers = ann["persons"]; works = ann["works"]
        print(f"[{label}] 인물 {len(pers)}종 {sum(pers.values())}회, 작품 {len(works)}종 {sum(works.values())}회")
    print("\n=== 정리 후 id 확인 ===")
    from lxml import etree
    r = etree.fromstring(cleaned.encode("utf-8"),
                         parser=etree.XMLParser(collect_ids=False))
    XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
    for pers in r.iter(f"{{{NS}}}persName"):
        print(f"  {pers.get(XML_ID)}  role={pers.get('role')!r}  {(''.join(pers.itertext())).strip()}")
    for ti in r.iter(f"{{{NS}}}title"):
        if ti.getparent().tag.endswith("titleStmt"):
            continue
        print(f"  {ti.get(XML_ID)}  title={(''.join(ti.itertext())).strip()!r}")


def _main() -> None:
    import sys
    if len(sys.argv) == 3:
        from pathlib import Path
        src, dst = Path(sys.argv[1]), Path(sys.argv[2])
        cleaned, report = clean_tagging(src.read_text(encoding="utf-8"))
        dst.write_text(cleaned, encoding="utf-8")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(f"정리 완료: {src} → {dst}")
        print(_format_report(report))
    else:
        _demo()


if __name__ == "__main__":
    _main()
