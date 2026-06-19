"""
extract_assemble/평가_성현아.py
성현아 비평문 자동 태깅을 정답(gold) 대비 채점하여 논문 〈표 2〉의 F1을 재현한다.
(정답이 있는 성현아에 한함. 김주원은 정답 부재로 정확도 산출 대상이 아니다.)

채점 방식
  - core.evaluation 의 다중집합 P/R/F1 사용 (느슨=텍스트, 엄격=텍스트+속성)
  - 비교 전 '표기 정규화'를 적용해 마크업 관행 차이가 점수를 왜곡하지 않게 함:
      · 공백 제거
      · 낫표·따옴표(「」『』《》〈〉 " " ' ') 제거  → 정답은 따옴표를 태그 밖에 두므로
      · 인라인 각주 참조 숫자 제거                → 본문에 섞인 각주 번호 노이즈 제거
    (속성값(role/type/when 등)은 별도로 비교되며 정규화 대상이 아니다.)

사용
  python -m extract_assemble.평가_성현아                       # 최신 성현아 출력 자동 탐색
  python -m extract_assemble.평가_성현아 --pred <파일.xml>
  python -m extract_assemble.평가_성현아 --raw                 # 정규화 없이(원자료) 채점
  python -m extract_assemble.평가_성현아 --md report/성현아_F1.md   # 마크다운 표 저장
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import evaluation as ev  # noqa: E402

_MARKS = re.compile(r"[「」『』《》〈〉\"'“”‘’]")


def _normalize(s: str) -> str:
    """
    표기 정규화: 공백·낫표·따옴표 제거 + 인라인 각주 참조 숫자(1~3자리) 제거.
    연도 등 4자리 숫자는 보존하여 날짜 개체가 손실되지 않게 한다.
    """
    s = _MARKS.sub("", s or "")
    s = re.sub(r"(?<!\d)\d{1,3}(?!\d)", "", s)   # 각주번호만 제거, 연도(4자리) 보존
    return re.sub(r"\s+", "", s)


def score_all(gold_xml: str, pred_xml: str, normalize: bool = True):
    """느슨·엄격 채점 결과(dict) 두 개를 반환."""
    orig = ev._norm_text
    if normalize:
        ev._norm_text = _normalize
    try:
        lenient = ev.score(gold_xml, pred_xml, strict=False)
        strict = ev.score(gold_xml, pred_xml, strict=True)
    finally:
        ev._norm_text = orig
    return lenient, strict


def table_rows(lenient, strict):
    rows = []
    for k, spec in ev.TYPE_SPECS.items():
        rows.append((spec.label, lenient[k], strict[k]))
    rows.append(("전체(micro)", lenient["__micro__"], strict["__micro__"]))
    return rows


def print_console(rows):
    print(f'{"개체 유형":<16}{"정답":>5}{"예측":>5}{"느슨P":>7}{"느슨R":>7}'
          f'{"느슨F1":>8}{"엄격F1":>8}')
    print("-" * 56)
    for label, le, st in rows:
        print(f"{label:<16}{le.gold_total:>5}{le.pred_total:>5}"
              f"{le.precision*100:>6.1f}%{le.recall*100:>6.1f}%"
              f"{le.f1*100:>7.1f}%{st.f1*100:>7.1f}%")


def to_markdown(rows) -> str:
    out = ["| 개체 유형 | 느슨 F1 | 엄격 F1 |", "|---|--:|--:|"]
    for label, le, st in rows:
        bold = "**" if label.startswith("전체") else ""
        out.append(f"| {bold}{label}{bold} | {bold}{le.f1*100:.1f}%{bold} "
                   f"| {bold}{st.f1*100:.1f}%{bold} |")
    return "\n".join(out)


# 〈표 3〉 후처리 규칙 누적 ablation — 동일 라벨(성현아_v2_1.labels.json)에서
# 조립 정책만 누적한 출력들. 같은 의미판단 위의 통제 비교(방법 3.3).
_STAGES = [
    ("조립 기본 (날짜 포함)", "3-성현아_v2.xml"),
    ("+ 인물 역할 전역 해소", "4-성현아_v2.xml"),
    ("+ 따옴표 인용 보강", "7-성현아_v2.xml"),
]


def run_ablation(gold_xml: str, normalize: bool = True):
    print(f'{"단계":<26}{"느슨 F1":>9}{"엄격 F1":>9}')
    print("-" * 44)
    md = ["| 단계 | 느슨 F1 | 엄격 F1 |", "|---|--:|--:|"]
    for label, fname in _STAGES:
        hits = list(ROOT.glob(f"extract_assemble/*/{fname}"))
        if not hits:
            print(f"{label:<26}{'(파일 없음)':>18}")
            continue
        le, st = score_all(gold_xml, hits[0].read_text(encoding="utf-8"), normalize)
        lf, sf = le["__micro__"].f1 * 100, st["__micro__"].f1 * 100
        last = label.startswith("+ 따옴표")
        print(f"{label:<26}{lf:>8.1f}%{sf:>8.1f}%")
        b = "**" if last else ""
        md.append(f"| {label} | {b}{lf:.1f}%{b} | {b}{sf:.1f}%{b} |")
    return "\n".join(md)


def main():
    p = argparse.ArgumentParser(description="성현아 자동 태깅 F1 채점")
    p.add_argument("--ablation", action="store_true",
                   help="후처리 규칙 누적 기여(〈표 3〉) 산출")
    p.add_argument("--gold", default=None, help="정답 TEI/XML (기본: 자본주의*.xml)")
    p.add_argument("--pred", default=None,
                   help="채점 대상 XML (기본: extract_assemble/결과/7-*_v2.xml)")
    p.add_argument("--raw", action="store_true", help="표기 정규화 없이 채점")
    p.add_argument("--md", default=None, help="마크다운 표를 저장할 경로")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    gold_path = Path(args.gold) if args.gold else next(ROOT.glob("자본주의*.xml"))
    gold_xml = gold_path.read_text(encoding="utf-8")

    if args.ablation:
        print(f"정답 : {gold_path.name}")
        print(f"정규화: {'미적용(raw)' if args.raw else '표기통일'}\n")
        md = run_ablation(gold_xml, normalize=not args.raw)
        if args.md:
            Path(args.md).write_text(md, encoding="utf-8")
            print(f"\n마크다운 표 저장: {args.md}")
        return

    pred_path = (Path(args.pred) if args.pred
                 else sorted(ROOT.glob("extract_assemble/*/*-성현아_v2.xml"))[-1])

    lenient, strict = score_all(gold_xml, pred_path.read_text(encoding="utf-8"),
                                normalize=not args.raw)
    rows = table_rows(lenient, strict)

    print(f"정답 : {gold_path.name}")
    print(f"대상 : {pred_path.name}")
    print(f"정규화: {'미적용(raw)' if args.raw else '표기통일(공백·낫표·따옴표·각주숫자)'}\n")
    print_console(rows)

    if args.md:
        out = Path(args.md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(to_markdown(rows), encoding="utf-8")
        print(f"\n마크다운 표 저장: {out}")


if __name__ == "__main__":
    main()
