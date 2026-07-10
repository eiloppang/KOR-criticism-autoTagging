"""v2.1 출력에 원문 텍스트가 빠짐없이 들어갔는지 검증 (줄 수 아닌 실제 텍스트 기준)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import coverage as cov  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

src = next(ROOT.glob("비평문/성현아.txt")).read_text(encoding="utf-8")
v21 = next(ROOT.glob("extract_assemble/*/*_v2_1.xml")).read_text(encoding="utf-8")
gold = next(ROOT.glob("자본주의*.xml")).read_text(encoding="utf-8")

src_n = cov._norm(src)
v21_body = cov._norm(cov._body_text(v21))
gold_body = cov._norm(cov._body_text(gold))

print("=== 정규화 글자 수 (공백 제거) ===")
print(f"  원문         : {len(src_n):,}")
print(f"  v2.1 본문    : {len(v21_body):,}")
print(f"  정답 본문    : {len(gold_body):,}")
print()

c = cov.coverage(src, v21)
print("=== v2.1 분량 (원문 대비) ===")
print(f"  글자 커버리지: {c['char_ratio']*100:.1f}%")
print(f"  문장 커버리지: {c['sentence_ratio']*100:.1f}%  ({c['covered']}/{c['n_sentences']})")
print()

if c["missing_sentences"]:
    print(f"=== 빠진(또는 미일치) 문장 {c['missing']}건 ===")
    for s in c["missing_sentences"]:
        print("  ✗", (s[:90] + "…") if len(s) > 90 else s)
else:
    print("✅ 원문의 모든 문장이 v2.1에 포함됨 — 빠진 것 없음")

# 줄 수 비교 (왜 다른지 설명용)
print()
print("=== 줄 수 (포맷 차이일 뿐) ===")
print(f"  정답 줄 수 : {gold.count(chr(10))+1}")
print(f"  v2.1 줄 수 : {v21.count(chr(10))+1}")
print(f"  정답 date 태그 수 : {gold.count('<date')}  (v2.1은 스키마 준수로 0)")
