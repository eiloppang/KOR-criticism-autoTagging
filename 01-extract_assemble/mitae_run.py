"""
extract_assemble/mitae_run.py
'미태깅/미태깅' 폴더의 비평문(.docx/.txt)을 태깅해 '미태깅_결과'에 저장.

  docx_run.py 와 동일한 v2 파이프라인(구조→라벨→인물해소→인용보강→조립)을
  입력=미태깅/미태깅, 출력=미태깅_결과 로 돌린다. (출력이 이미 있으면 건너뜀)

사용
  python -m extract_assemble.mitae_run              # 미처리분 전체
  python -m extract_assemble.mitae_run --force      # 이미 있어도 다시
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

INDIR = ROOT / "미태깅" / "미태깅"
OUTDIR = ROOT / "미태깅_결과"
TXTDIR = OUTDIR / "_txt"   # 추출 원문 보관(검수용)


def _hangul(s: str) -> int:
    return sum(1 for c in s if "가" <= c <= "힣")


def extract_docx(p: Path) -> str:
    d = Document(str(p))
    return "\n".join(par.text for par in d.paragraphs if par.text.strip())


def extract_text(p: Path) -> str:
    if p.suffix.lower() == ".docx":
        return extract_docx(p)
    return p.read_text(encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="출력이 있어도 다시 태깅")
    p.add_argument("--model", default="claude-sonnet-4-6")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    OUTDIR.mkdir(exist_ok=True)
    TXTDIR.mkdir(parents=True, exist_ok=True)
    key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    provider = ClaudeProvider(api_key=key, model=args.model)

    files = sorted(
        f for f in INDIR.iterdir()
        if f.is_file() and f.suffix.lower() in (".docx", ".txt")
    )
    print(f"대상 {len(files)}편 (입력: {INDIR})", flush=True)

    done, results = 0, []
    for f in files:
        name = _safe(f.stem)
        out_xml = OUTDIR / f"{name}_v2.xml"
        if out_xml.exists() and not args.force:
            print(f"이미 있음 → 건너뜀: {name[:45]}", flush=True)
            continue

        try:
            text = extract_text(f)
        except Exception as e:
            print(f"  ❌ 추출 실패: {name[:40]} — {e}", flush=True)
            continue
        if _hangul(text) < 300:
            print(f"한글 부족 → 건너뜀: {name[:45]}", flush=True)
            continue

        done += 1
        t0 = time.time()
        (TXTDIR / f"{name}.txt").write_text(text, encoding="utf-8")
        title, author = _meta(f.stem)
        doc = S.build_structure(text, title=title, author=author)
        nsent = sum(len(pa) for s in doc["sections"] for pa in s["paragraphs"])
        print(f"\n[{done}] {f.stem[:50]}\n  {len(text):,}자, 문장 {nsent} → 라벨링",
              flush=True)
        try:
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
            results.append((name, not nondate, c["char_ratio"]))
        except Exception as e:
            print(f"  ❌ 실패: {name[:40]} — {e}", flush=True)

    print(f"\n=== 완료 요약 ({done}편 시도) ===", flush=True)
    for name, xsd_ok, ratio in results:
        print(f"  {name[:45]:<46} XSD {'OK' if xsd_ok else 'X'} 분량 {ratio*100:.0f}%",
              flush=True)


if __name__ == "__main__":
    main()
