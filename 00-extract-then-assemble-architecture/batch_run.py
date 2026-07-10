"""
extract_assemble/batch_run.py
mirae/ 의 '정상(텍스트 레이어 정상)' PDF들을 일괄 태깅해 mirea_results/ 에 저장.

  - pdfplumber로 추출 → 한글이 충분하면 '정상'으로 판정(스캔·CID는 건너뜀)
  - 각 편: structure → annotate(LLM) → 인물 role 해소 → 따옴표 인용 보강 → assemble
  - 한 편 끝나는 대로 XML·라벨 저장(중단 시 진행분 보존), 이미 있으면 건너뜀(이어하기)

사용
  python -m extract_assemble.batch_run                 # 전체
  python -m extract_assemble.batch_run --limit 3       # 앞 3편만(테스트)
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

import pdfplumber  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core import coverage as cov  # noqa: E402
from core.providers import ClaudeProvider  # noqa: E402
from extract_assemble import annotate as A  # noqa: E402
from extract_assemble import assemble as ASM  # noqa: E402
from extract_assemble import resolve as R  # noqa: E402
from extract_assemble import structure as S  # noqa: E402

OUTDIR = ROOT / "mirea_results"
TXTDIR = ROOT / "비평문"


def _hangul(s: str) -> int:
    return sum(1 for c in s if "가" <= c <= "힣")


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", name)[:60].strip()


def _meta(stem: str):
    parts = stem.split("_")
    author = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else stem
    return title, author


def extract(pdf: Path) -> str:
    with pdfplumber.open(pdf) as d:
        return "\n".join((pg.extract_text() or "") for pg in d.pages)


def process_one(pdf: Path, provider, log) -> dict | None:
    name = _safe(pdf.stem)
    out_xml = OUTDIR / f"{name}_v2.xml"
    if out_xml.exists():
        log(f"  이미 있음 → 건너뜀: {out_xml.name}")
        return {"name": name, "skipped": True}

    text = extract(pdf)
    if _hangul(text) < 800:
        log(f"  정상 아님(한글 {_hangul(text)}) → 건너뜀")
        return None

    (TXTDIR / f"{name}.txt").write_text(text, encoding="utf-8")
    title, author = _meta(pdf.stem)
    doc = S.build_structure(text, title=title, author=author)
    nsent = sum(len(pa) for s in doc["sections"] for pa in s["paragraphs"])
    log(f"  추출 {len(text):,}자, 문장 {nsent} → 라벨링")

    A.annotate_doc(doc, provider, progress=lambda m: None)
    R.resolve_person_roles_llm(doc, provider)
    R.add_quote_spans(doc)
    xml = ASM.assemble(doc, allow_date=True, source_text=text)

    out_xml.write_text(xml, encoding="utf-8")
    (OUTDIR / f"{name}_v2.labels.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    ok, errs = ASM.validate(xml)
    nondate = [e for e in errs if "date" not in e.lower()]
    c = cov.coverage(text, xml)
    return {"name": name, "sent": nsent, "xsd_ok": not nondate,
            "cov": c["char_ratio"], "chars": len(xml)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default="claude-sonnet-4-6")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUTDIR.mkdir(exist_ok=True)
    pdfs = sorted((ROOT / "mirae").glob("*.pdf"))
    key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    provider = ClaudeProvider(api_key=key, model=args.model)

    def log(m):
        print(m, flush=True)

    done, results = 0, []
    for i, pdf in enumerate(pdfs, 1):
        if args.limit and done >= args.limit:
            break
        # 빠른 사전판정(앞 2p)으로 스캔/CID 건너뛰기
        try:
            with pdfplumber.open(pdf) as d:
                head = "\n".join((d.pages[j].extract_text() or "")
                                 for j in range(min(2, len(d.pages))))
        except Exception:
            continue
        if _hangul(head) < 150:
            continue  # 스캔·CID → 정상 16개 대상 아님

        done += 1
        t0 = time.time()
        log(f"\n[{done}] {pdf.stem[:55]}")
        try:
            r = process_one(pdf, provider, log)
            if r and not r.get("skipped"):
                log(f"  ✅ 저장 ({time.time()-t0:.0f}s) "
                    f"XSD {'OK' if r['xsd_ok'] else 'X'} 분량 {r['cov']*100:.0f}%")
            if r:
                results.append(r)
        except Exception as e:
            log(f"  ❌ 실패: {e}")

    log("\n=== 완료 요약 ===")
    for r in results:
        if r.get("skipped"):
            continue
        log(f"  {r['name'][:45]:<46} 문장 {r.get('sent','-')} "
            f"XSD {'OK' if r.get('xsd_ok') else 'X'} 분량 {r.get('cov',0)*100:.0f}%")


if __name__ == "__main__":
    main()
