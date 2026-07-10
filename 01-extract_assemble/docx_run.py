"""
extract_assemble/docx_run.py
.docx 비평문을 태깅해 mirea_results/ 에 저장. (출력이 이미 있으면 건너뜀)

  python-docx로 본문 추출 → v2 파이프라인(구조→라벨→인물해소→인용보강→조립)

사용
  python -m extract_assemble.docx_run            # 루트+mirae의 모든 docx 중 미처리분
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core import coverage as cov  # noqa: E402
from core.providers import ClaudeProvider  # noqa: E402
from extract_assemble import annotate as A  # noqa: E402
from extract_assemble import assemble as ASM  # noqa: E402
from extract_assemble import resolve as R  # noqa: E402
from extract_assemble import structure as S  # noqa: E402
from extract_assemble.batch_run import _meta, _safe  # noqa: E402

OUTDIR = ROOT / "mirea_results"
TXTDIR = ROOT / "비평문"


def _hangul(s: str) -> int:
    return sum(1 for c in s if "가" <= c <= "힣")


def extract_docx(p: Path) -> str:
    d = Document(str(p))
    return "\n".join(par.text for par in d.paragraphs if par.text.strip())


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUTDIR.mkdir(exist_ok=True)
    key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    provider = ClaudeProvider(api_key=key, model="claude-sonnet-4-6")

    docs = sorted(set(ROOT.glob("*.docx")) | set((ROOT / "mirae").glob("*.docx")))
    done = 0
    for dp in docs:
        name = _safe(dp.stem)
        out_xml = OUTDIR / f"{name}_v2.xml"
        if out_xml.exists():
            print(f"이미 있음 → 건너뜀: {name[:45]}", flush=True)
            continue
        text = extract_docx(dp)
        if _hangul(text) < 300:
            print(f"한글 부족 → 건너뜀: {name[:45]}", flush=True)
            continue
        done += 1
        t0 = time.time()
        TXTDIR.joinpath(f"{name}.txt").write_text(text, encoding="utf-8")
        title, author = _meta(dp.stem)
        doc = S.build_structure(text, title=title, author=author)
        nsent = sum(len(pa) for s in doc["sections"] for pa in s["paragraphs"])
        print(f"\n[{done}] {dp.stem[:50]}\n  {len(text):,}자, 문장 {nsent} → 라벨링",
              flush=True)
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
