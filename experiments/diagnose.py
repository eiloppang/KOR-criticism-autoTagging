"""
experiments/diagnose.py
정답(gold) 대비 태깅 출력을 채점하여 '무엇을 고칠지'가 보이는 진단 리포트를 만든다.

  - 태그별 정밀도/재현율/F1 (느슨·엄격)
  - 놓친 항목(FN): 정답엔 있는데 기계가 안 잡음 → "더 잡게" 보강 대상
  - 과태깅(FP): 기계만 있고 정답엔 없음 → "덜 잡게" 억제 대상
  - 느슨↔엄격 격차 = 속성(role/type/value) 오분류율

사용
  python -m experiments.diagnose --gold <정답.xml> --pred <기계.xml> --out report/평가진단.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import evaluation as ev  # noqa: E402

MAX_ITEMS = 30


def _pct(x):
    return f"{x*100:.1f}%"


def _table(score_dict, title):
    lines = [f"### {title}", "",
             "| 유형 | 정답 | 기계 | TP | FP | FN | 정밀도 | 재현율 | F1 |",
             "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    order = list(ev.TYPE_SPECS) + ["__micro__"]
    for k in order:
        s = score_dict.get(k)
        if not s:
            continue
        lines.append(
            f"| {s.label} | {s.gold_total} | {s.pred_total} | {s.tp} | {s.fp} | {s.fn} "
            f"| {_pct(s.precision)} | {_pct(s.recall)} | {_pct(s.f1)} |"
        )
    return "\n".join(lines)


def _items(records, n=MAX_ITEMS):
    out = []
    for r in records[:n]:
        text = r[0]
        attrs = " · ".join(a for a in r[1:] if a)
        disp = text if len(text) <= 70 else text[:70] + "…"
        out.append(f"`{disp}`" + (f" ({attrs})" if attrs else ""))
    extra = f"\n  …외 {len(records)-n}개" if len(records) > n else ""
    return ("、 ".join(out) or "—") + extra


def build(gold_xml: str, pred_xml: str) -> str:
    le = ev.score(gold_xml, pred_xml, strict=False)
    st = ev.score(gold_xml, pred_xml, strict=True)

    parts = [
        "# 평가 진단 리포트 — 정답(gold) 대비 기계 태깅",
        "",
        "- 정답: 사람이 손 태깅한 성현아 비평문",
        "- 기계: pipeline 모드 자동 태깅 (`비평문아웃풋2.xml`)",
        "- **느슨**: 태그+텍스트 일치 / **엄격**: 속성까지 일치",
        "",
        "## 1. 종합 점수",
        "",
        _table(le, "느슨 (개체를 찾았는가)"),
        "",
        _table(st, "엄격 (속성까지 맞췄는가)"),
        "",
        "> 느슨 대비 엄격 점수 하락폭 = role/type/value 등 **속성 오분류율**.",
        "",
        "## 2. 태그별 진단 (느슨 기준)",
        "",
    ]

    for k, spec in ev.TYPE_SPECS.items():
        s = le[k]
        parts.append(f"### {spec.label} — 정답 {s.gold_total} / 기계 {s.pred_total} "
                     f"(P {_pct(s.precision)} · R {_pct(s.recall)} · F1 {_pct(s.f1)})")
        parts.append(f"- **놓침(FN={s.fn})** 정답엔 있는데 기계가 안 잡음 → *더 잡게*:")
        parts.append(f"  {_items(s.fn_items)}")
        parts.append(f"- **과태깅(FP={s.fp})** 기계만 잡음, 정답엔 없음 → *덜 잡게/정리*:")
        parts.append(f"  {_items(s.fp_items)}")
        # 속성 오류: 엄격에서만 늘어난 FN
        attr_err = st[k].fn - s.fn
        if attr_err > 0:
            parts.append(f"- 속성 오류: 텍스트는 맞췄지만 속성 틀린 항목 ≈ **{attr_err}건**")
        parts.append("")

    return "\n".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gold", default=None)
    p.add_argument("--pred", default="문제점/비평문아웃풋2.xml")
    p.add_argument("--out", default="report/평가진단.md")
    args = p.parse_args()

    gold_path = Path(args.gold) if args.gold else next(Path(".").glob("자본주의*.xml"))
    pred_path = Path(args.pred)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    md = build(gold_path.read_text(encoding="utf-8"),
               pred_path.read_text(encoding="utf-8"))
    out_path.write_text(md, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"진단 리포트: {out_path}")
    print(f"정답: {gold_path.name}\n기계: {pred_path.name}")


if __name__ == "__main__":
    main()
