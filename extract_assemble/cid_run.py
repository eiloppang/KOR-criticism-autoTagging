"""
extract_assemble/cid_run.py
CID 폰트 PDF(텍스트는 정확하나 띄어쓰기 소실)를 태깅해 mirea_results/ 에 저장.

  pymupdf 추출 → 공백 전부 제거 → kiwipiepy로 띄어쓰기 복원 → 기존 파이프라인
  (pdfplumber는 (cid:) 토큰만 나오므로 pymupdf 사용)

사용
  python -m extract_assemble.cid_run            # 전체 CID PDF
  python -m extract_assemble.cid_run --dry      # 추출·구조만(API 없이 점검)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # pymupdf  # noqa: E402
import pdfplumber  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core import coverage as cov  # noqa: E402
from extract_assemble import annotate as A  # noqa: E402
from extract_assemble import assemble as ASM  # noqa: E402
from extract_assemble import resolve as R  # noqa: E402
from extract_assemble import structure as S  # noqa: E402
from extract_assemble.batch_run import _meta, _safe  # noqa: E402

OUTDIR = ROOT / "mirea_results"
TXTDIR = ROOT / "비평문"
_KIWI = None


def _hangul(s: str) -> int:
    return sum(1 for c in s if "가" <= c <= "힣")


def kiwi():
    global _KIWI
    if _KIWI is None:
        from kiwipiepy import Kiwi
        _KIWI = Kiwi()
    return _KIWI


def is_cid(pdf: Path) -> bool:
    """pdfplumber로는 한글이 거의 없는데 pymupdf로는 한글이 나오는 PDF = CID."""
    try:
        with pdfplumber.open(pdf) as d:
            head = "\n".join((d.pages[i].extract_text() or "")
                             for i in range(min(2, len(d.pages))))
    except Exception:
        return False
    if _hangul(head) > 150:
        return False                       # 정상 텍스트
    try:
        fd = fitz.open(pdf)
        fh = "".join(fd[i].get_text() for i in range(min(2, len(fd))))
        fd.close()
    except Exception:
        return False
    return _hangul(fh) > 150               # pymupdf로는 한글 나옴 → CID


def extract_cid(pdf: Path) -> str:
    """pymupdf 추출 → 공백 전부 제거(불완전) → kiwi 띄어쓰기 복원."""
    fd = fitz.open(pdf)
    raw = "\n".join(fd[i].get_text() for i in range(len(fd)))
    fd.close()
    nospace = re.sub(r"\s+", "", raw)
    return kiwi().space(nospace)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="추출·구조만(LLM 없이)")
    p.add_argument("--model", default="claude-sonnet-4-6")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUTDIR.mkdir(exist_ok=True)
    provider = None
    if not args.dry:
        from core.providers import ClaudeProvider
        key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        provider = ClaudeProvider(api_key=key, model=args.model)

    done = 0
    for pdf in sorted((ROOT / "mirae").glob("*.pdf")):
        if not is_cid(pdf):
            continue
        name = _safe(pdf.stem)
        out_xml = OUTDIR / f"{name}_v2.xml"
        if out_xml.exists():
            print(f"이미 있음 → 건너뜀: {name}", flush=True)
            continue
        done += 1
        t0 = time.time()
        text = extract_cid(pdf)
        title, author = _meta(pdf.stem)
        doc = S.build_structure(text, title=title, author=author)
        nsent = sum(len(pa) for s in doc["sections"] for pa in s["paragraphs"])
        print(f"\n[{done}] {pdf.stem[:50]}\n  복원 {len(text):,}자, 문장 {nsent}",
              flush=True)
        if args.dry:
            print(f"  (dry) 앞 100자: {text[:100]}", flush=True)
            continue
        TXTDIR.joinpath(f"{name}.txt").write_text(text, encoding="utf-8")
        A.annotate_doc(doc, provider, progress=lambda m: None)
        R.resolve_person_roles_llm(doc, provider)
        R.add_quote_spans(doc)
        xml = ASM.assemble(doc, allow_date=True, source_text=text)
        out_xml.write_text(xml, encoding="utf-8")
        OUTDIR.joinpath(f"{name}_v2.labels.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        ok, errs = ASM.validate(xml)
        nondate = [e for e in errs if "date" not in e.lower()]
        c = cov.coverage(text, xml)
        print(f"  ✅ 저장 ({time.time()-t0:.0f}s) XSD {'OK' if not nondate else 'X'} "
              f"분량 {c['char_ratio']*100:.0f}%", flush=True)

    print(f"\n총 {done}편 처리.", flush=True)


if __name__ == "__main__":
    main()
