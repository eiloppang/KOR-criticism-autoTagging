"""
extract_assemble/run.py
v2 추출-조립 파이프라인 드라이버.

  원문 → structure(골격) → annotate(LLM 라벨) → assemble(유효 TEI) → 검증·저장

사용
  python -m extract_assemble.run --input 비평문/성현아.txt --out extract_assemble/out/성현아_v2.xml
  python -m extract_assemble.run --input 비평문/성현아.txt --out ... --limit 30   # 앞 30문장만(저렴 테스트)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core.providers import ClaudeProvider  # noqa: E402
from extract_assemble import annotate as A  # noqa: E402
from extract_assemble import structure as S  # noqa: E402
from extract_assemble.assemble import assemble, validate  # noqa: E402


def _limit_doc(doc: dict, limit: int) -> dict:
    """앞 limit 문장만 남긴 골격 반환 (저렴 테스트용)."""
    kept, out_secs = 0, []
    for sec in doc["sections"]:
        new_paras = []
        for para in sec["paragraphs"]:
            if kept >= limit:
                break
            take = para[:max(0, limit - kept)]
            kept += len(take)
            if take:
                new_paras.append(take)
        if new_paras:
            out_secs.append({**sec, "paragraphs": new_paras})
        if kept >= limit:
            break
    return {**doc, "sections": out_secs}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="비평문/성현아.txt")
    p.add_argument("--out", default="extract_assemble/out/성현아_v2.xml")
    p.add_argument("--title", default="자본주의에 대처하는 우리의 자세")
    p.add_argument("--author", default="성현아")
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--batch-size", type=int, default=12)
    p.add_argument("--limit", type=int, default=0, help="앞 N문장만(0=전체)")
    p.add_argument("--from-json", default=None,
                   help="저장된 라벨 JSON에서 재조립(LLM 호출 없음)")
    p.add_argument("--no-date", action="store_true", help="인라인 date 제외(완전 무결 XSD)")
    p.add_argument("--no-resolve", action="store_true", help="전역 인물 role 해소 끄기")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    text = Path(args.input).read_text(encoding="utf-8")

    if args.from_json:
        doc = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        print(f"라벨 JSON 로드: {args.from_json} (LLM 호출 없이 재조립)")
    else:
        doc = S.build_structure(text, title=args.title, author=args.author)
        if args.limit:
            doc = _limit_doc(doc, args.limit)
        nsent = sum(len(pa) for s in doc["sections"] for pa in s["paragraphs"])
        print(f"골격: 섹션 {len(doc['sections'])}, 문장 {nsent}  → LLM 라벨링 시작")
        key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        provider = ClaudeProvider(api_key=key, model=args.model)
        A.annotate_doc(doc, provider, batch_size=args.batch_size,
                       progress=lambda m: print("  ", m, flush=True))
        # 라벨 JSON 저장 → 이후 정책 변경 시 API 없이 재조립
        json_path = Path(args.out).with_suffix(".labels.json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        print(f"라벨 저장: {json_path}")

    if not args.no_resolve:
        from extract_assemble.resolve import add_quote_spans, resolve_person_roles_llm
        key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        prov = ClaudeProvider(api_key=key, model=args.model)
        st = resolve_person_roles_llm(doc, prov)
        print(f"전역 인물 role 해소(LLM): {st['persons']}명(외국인 {st['foreign']}), "
              f"{st['changed_mentions']}개 언급 통일")
        nq = add_quote_spans(doc)
        print(f"따옴표 인용 보강: {nq}개 추가")

    xml = assemble(doc, allow_date=not args.no_date, source_text=text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")

    ok, errs = validate(xml)
    date_errs = [e for e in errs if "}date'" in e or "date" in e.lower()]
    other = [e for e in errs if e not in date_errs]
    print(f"\n저장: {args.out} ({len(xml):,}자)")
    print(f"XSD 검증: date 외 위반 {len(other)}건 " + ("✅" if not other else "❌"))
    print(f"          (date 인라인 {len(date_errs)}건 = 정답과 동일한 알려진 스키마 공백)")
    for e in other[:8]:
        print("  ", e)

    # 분량 확인
    from core import coverage as cov
    c = cov.coverage(text if not args.limit else cov._body_text(xml), xml)
    if not args.limit:
        print(f"분량: 문장 {c['sentence_ratio']*100:.1f}%, 글자 {c['char_ratio']*100:.1f}%")


if __name__ == "__main__":
    main()
