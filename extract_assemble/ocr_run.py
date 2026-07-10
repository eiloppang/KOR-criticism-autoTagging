"""
extract_assemble/ocr_run.py
스캔(이미지) PDF를 OCR로 텍스트화한 뒤 태깅해 mirea_results/ 에 저장.

  pymupdf로 페이지를 이미지로 렌더 → EasyOCR(한국어)로 텍스트 인식 → v2 파이프라인
  (텍스트 레이어가 없어 pdfplumber·pymupdf 모두 한글이 안 나오는 PDF가 대상)

사용
  python -m extract_assemble.ocr_run --limit 10     # 스캔 PDF 10편
  python -m extract_assemble.ocr_run --limit 1 --ocr-only   # OCR만(태깅 X) 점검

주의: CPU OCR은 페이지당 수~수십 초. 품질은 스캔 상태에 따라 오류가 섞일 수 있음.
"""
from __future__ import annotations

import argparse
import json
import os
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
OCRDIR = ROOT / "mirea_results" / "_ocr_txt"   # OCR 원문 보관(검수용)
_READER = None


def _hangul(s: str) -> int:
    return sum(1 for c in s if "가" <= c <= "힣")


def reader():
    global _READER
    if _READER is None:
        import easyocr
        _READER = easyocr.Reader(["ko", "en"], gpu=False)
    return _READER


def is_scanned(pdf: Path) -> bool:
    """텍스트 레이어 없음: pdfplumber·pymupdf 모두 한글이 거의 없음."""
    try:
        with pdfplumber.open(pdf) as d:
            h1 = "\n".join((d.pages[i].extract_text() or "")
                           for i in range(min(2, len(d.pages))))
    except Exception:
        return False
    if _hangul(h1) > 100:
        return False
    try:
        fd = fitz.open(pdf)
        h2 = "".join(fd[i].get_text() for i in range(min(2, len(fd))))
        fd.close()
    except Exception:
        return False
    return _hangul(h2) < 100      # CID(=pymupdf 한글 많음)는 제외


def ocr_pdf(pdf: Path, dpi: int = 200, log=print) -> str:
    fd = fitz.open(pdf)
    n = len(fd)
    parts = []
    for i in range(n):
        pix = fd[i].get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
        lines = reader().readtext(png, detail=0, paragraph=True)
        parts.append("\n".join(lines))
        if (i + 1) % 3 == 0 or i + 1 == n:
            log(f"    OCR {i+1}/{n}p", )
    fd.close()
    return "\n".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--ocr-only", action="store_true")
    p.add_argument("--model", default="claude-sonnet-4-6")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUTDIR.mkdir(exist_ok=True)
    OCRDIR.mkdir(parents=True, exist_ok=True)
    provider = None
    if not args.ocr_only:
        from core.providers import ClaudeProvider
        key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        provider = ClaudeProvider(api_key=key, model=args.model)

    def log(m):
        print(m, flush=True)

    done = 0
    for pdf in sorted((ROOT / "mirae").glob("*.pdf")):
        if done >= args.limit:
            break
        name = _safe(pdf.stem)
        out_xml = OUTDIR / f"{name}_v2.xml"
        if out_xml.exists():
            continue
        if not is_scanned(pdf):
            continue

        done += 1
        t0 = time.time()
        log(f"\n[{done}] {pdf.stem[:50]}")
        # OCR (이미 OCR 텍스트가 있으면 재사용)
        ocr_txt = OCRDIR / f"{name}.txt"
        if ocr_txt.exists():
            text = ocr_txt.read_text(encoding="utf-8")
            log(f"  OCR 텍스트 재사용 ({len(text):,}자)")
        else:
            text = ocr_pdf(pdf, dpi=args.dpi, log=log)
            ocr_txt.write_text(text, encoding="utf-8")
            log(f"  OCR 완료 {len(text):,}자 ({time.time()-t0:.0f}s)")

        if _hangul(text) < 300:
            log("  ⚠️ OCR 한글 너무 적음 → 건너뜀(스캔 품질 불량 의심)")
            continue
        if args.ocr_only:
            continue

        title, author = _meta(pdf.stem)
        doc = S.build_structure(text, title=title, author=author)
        nsent = sum(len(pa) for s in doc["sections"] for pa in s["paragraphs"])
        log(f"  문장 {nsent} → 라벨링")
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
        log(f"  ✅ 저장 ({time.time()-t0:.0f}s) XSD {'OK' if not nondate else 'X'} "
            f"분량 {c['char_ratio']*100:.0f}%")

    log(f"\n총 {done}편 처리.")


if __name__ == "__main__":
    main()
