"""
core/coverage.py
태깅 출력이 원문을 빠짐없이 포함하는지(분량 누락 여부) 검사하는 모듈.

원리
----
시스템 프롬프트는 '요약·생략 금지, 모든 문장 포함'을 요구하지만 LLM은 청크 경계에서
내용을 흘릴 수 있다. 이 모듈은 원문 평문과 태그 출력의 본문 텍스트(//tei:text)를
문장 단위로 대조하여:
  - 문장 커버리지(%) — 원문 문장 중 출력에 들어간 비율
  - 글자 커버리지(%) — 정규화 길이 비교
  - 누락 문장 목록 — 실제로 빠진 부분(검수용)
을 반환한다.

사용
  from core.coverage import coverage, format_coverage
  rep = coverage(source_text, tagged_xml)
  print(format_coverage(rep))

  # CLI
  python -m core.coverage 원문.txt 태그출력.xml
"""
from __future__ import annotations

import re

NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# 매칭 시 무시할 기호(태깅 과정에서 이동/제거될 수 있는 표기)
_STRIP_MARKS = "「」『』《》〈〉\"'“”‘’()（）[]"
_WS = re.compile(r"\s+")


def _norm(s: str, strip_marks: bool = False) -> str:
    s = _WS.sub("", s)
    if strip_marks:
        s = s.translate(str.maketrans("", "", _STRIP_MARKS))
    return s


def _split_sentences(text: str) -> list[str]:
    """원문을 문장 단위로 분할. 한국어 종결('다.') + 일반 문장부호 + 줄바꿈 기준."""
    # 종결어미/문장부호 뒤에서 분할
    parts = re.split(r"(?<=다\.)\s+|(?<=[.!?。])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _body_text(tagged_xml: str) -> str:
    """태그 출력의 //tei:text 본문 텍스트만 추출(teiHeader 제외)."""
    from lxml import etree

    parser = etree.XMLParser(collect_ids=False)
    root = etree.fromstring(tagged_xml.encode("utf-8"), parser=parser)
    texts = root.xpath("//tei:text", namespaces=NS)
    return "".join("".join(t.itertext()) for t in texts)


def coverage(source_text: str, tagged_xml: str, min_len: int = 6) -> dict:
    """
    원문 대비 태그 출력의 분량 커버리지를 계산한다.

    Parameters
    ----------
    min_len : 이 글자수 미만의 짧은 조각은 매칭 검사에서 제외(노이즈 방지)

    Returns
    -------
    dict: n_sentences, covered, missing, sentence_ratio,
          src_chars, out_chars, char_ratio, missing_sentences
    """
    out_text = _body_text(tagged_xml)
    out_norm = _norm(out_text)
    out_norm_marks = _norm(out_text, strip_marks=True)

    sentences = _split_sentences(source_text)
    checked = [s for s in sentences if len(_norm(s)) >= min_len]

    missing: list[str] = []
    for s in checked:
        n = _norm(s)
        if n in out_norm:
            continue
        # 표기기호 제거 후 재시도 (태깅이 「」 등을 옮긴 경우)
        nm = _norm(s, strip_marks=True)
        if nm and nm in out_norm_marks:
            continue
        missing.append(s)

    covered = len(checked) - len(missing)
    src_chars = len(_norm(source_text))
    out_chars = len(out_norm)

    return {
        "n_sentences": len(checked),
        "covered": covered,
        "missing": len(missing),
        "sentence_ratio": covered / len(checked) if checked else 0.0,
        "src_chars": src_chars,
        "out_chars": out_chars,
        "char_ratio": out_chars / src_chars if src_chars else 0.0,
        "missing_sentences": missing,
    }


def format_coverage(rep: dict, max_show: int = 30) -> str:
    lines = [
        "=== 분량 커버리지 ===",
        f"문장 커버리지: {rep['covered']}/{rep['n_sentences']} "
        f"({rep['sentence_ratio']*100:.1f}%)",
        f"글자 길이: 원문 {rep['src_chars']:,} → 출력 {rep['out_chars']:,} "
        f"({rep['char_ratio']*100:.1f}%)",
    ]
    if rep["missing_sentences"]:
        lines.append(f"\n누락 의심 문장 {rep['missing']}건 (앞 {max_show}건):")
        for s in rep["missing_sentences"][:max_show]:
            disp = s if len(s) <= 80 else s[:80] + "…"
            lines.append(f"  ✗ {disp}")
        if rep["missing"] > max_show:
            lines.append(f"  … 외 {rep['missing'] - max_show}건")
    else:
        lines.append("\n✅ 누락 문장 없음 — 원문이 모두 출력에 포함됨")
    return "\n".join(lines)


# ── CLI / 자체 시연 ───────────────────────────────────────────────

def _demo() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    source = ("김동인은 창조를 창간했다. 그는 자연주의를 주창했다. "
              "이광수의 계몽주의를 비판했다. 이는 중요한 사건이었다.")
    # 3번째 문장(이광수 비판)을 누락시킨 출력
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
 <teiHeader><fileDesc><titleStmt><title>t</title><author>미상</author></titleStmt>
 <publicationStmt><p>x</p></publicationStmt><sourceDesc><p>x</p></sourceDesc></fileDesc></teiHeader>
 <text><body><div type="body"><p>
   <s><persName xml:id="p-k">김동인</persName>은 <title xml:id="t-c" level="j" type="coterie">창조</title>를 창간했다.</s>
   <s>그는 <term type="movement">자연주의</term>를 주창했다.</s>
   <s>이는 중요한 사건이었다.</s>
 </p></div></body></text></TEI>"""
    print(format_coverage(coverage(source, xml)))


def _main() -> None:
    import sys
    if len(sys.argv) == 3:
        from pathlib import Path
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        src = Path(sys.argv[1]).read_text(encoding="utf-8")
        xml = Path(sys.argv[2]).read_text(encoding="utf-8")
        print(format_coverage(coverage(src, xml)))
    else:
        _demo()


if __name__ == "__main__":
    _main()
