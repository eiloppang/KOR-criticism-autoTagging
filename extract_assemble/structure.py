"""
extract_assemble/structure.py
원문 텍스트 → div/p/s 골격(annotated_doc, spans는 빈 상태)으로 분해한다. LLM 불필요.

  - 섹션: "N. 제목" 형태의 heading 줄로 분할 (앞부분은 introduction)
  - 문단: 빈 줄로 분할 (없으면 섹션당 1문단)
  - 문장: core.coverage 의 한국어 문장 분리 재사용

원문을 '그대로' 문장에 담으므로 분량이 보존된다(태그는 이후 annotate가 채움).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_HEAD = re.compile(r"^\s*(\d+)\.\s+\S")
# 종결부호(. ! ?) 뒤가 '문장 시작'(공백·한글·여는따옴표)일 때만 분할.
# → naver.com 같은 내부 마침표는 안 끊음. 줄바꿈은 분할 기준이 아님.
_SENT_SPLIT = re.compile(r"(?<=[.!?])(?=[\s가-힣“”‘’\"'(])")
SENTS_PER_PARA = 8


def _reflow(lines: list[str]) -> str:
    """
    PDF 줄바꿈은 대부분 단어 중간(모↵색)에서 일어나므로, 줄을 공백 없이 이어붙여
    원래 문장을 복원한다. (줄 안의 공백은 보존, 줄바꿈만 제거)
    """
    return "".join(ln.strip() for ln in lines)


def _split_sentences(block: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(block) if s.strip()]


def _paragraphs(block_lines: list[str]) -> list[list[dict]]:
    """줄들을 재결합→문장 분리→SENTS_PER_PARA개씩 문단으로 묶는다."""
    sents = _split_sentences(_reflow(block_lines))
    if not sents:
        return [[]]
    paras = []
    for i in range(0, len(sents), SENTS_PER_PARA):
        paras.append([{"text": s, "spans": []} for s in sents[i:i + SENTS_PER_PARA]])
    return paras


def build_structure(text: str, title: str = "", author: str = "") -> dict:
    """원문 → annotated_doc 골격 (spans 비어 있음)."""
    lines = text.splitlines()

    # 섹션 분할: heading 줄 인덱스 수집
    sections: list[dict] = []
    cur_head = None
    cur_type = "introduction"   # 첫 heading 이전 = 서론
    buf: list[str] = []

    def flush():
        if buf or cur_head:
            sections.append({
                "head": cur_head,
                "type": cur_type,
                "paragraphs": _paragraphs(buf),
            })

    for ln in lines:
        if _HEAD.match(ln.strip()):
            flush()
            buf = []
            cur_head = ln.strip()
            cur_type = "section"
        else:
            buf.append(ln)
    flush()

    if not sections:
        sections = [{"head": None, "type": "body", "paragraphs": _paragraphs(lines)}]

    return {"title": title or "미상", "author": author or "미상", "sections": sections}


# ── 자체 시연: 성현아 원문 → 골격 → (빈 태그) 조립 → 검증 + 분량 ──

def _demo():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from extract_assemble.assemble import assemble, validate
    from core import coverage as cov

    src = (ROOT / "비평문" / "성현아.txt").read_text(encoding="utf-8")
    doc = build_structure(src, title="자본주의에 대처하는 우리의 자세", author="성현아")
    nsec = len(doc["sections"])
    nsent = sum(len(p) for s in doc["sections"] for p in s["paragraphs"])
    print(f"골격: 섹션 {nsec}개, 문장 {nsent}개")
    print("섹션 head:", [s["head"] for s in doc["sections"]])

    xml = assemble(doc)
    ok, errs = validate(xml)
    print(f"\n조립 XSD 검증(태그 없이 골격만): {'✅ 통과' if ok else '❌ '+str(len(errs))+'건'}")
    for e in errs[:5]:
        print("  ", e)

    c = cov.coverage(src, xml)
    print(f"분량: 문장 {c['sentence_ratio']*100:.1f}%, 글자 {c['char_ratio']*100:.1f}%")


if __name__ == "__main__":
    _demo()
