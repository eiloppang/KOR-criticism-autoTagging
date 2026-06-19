"""v1/v2/v2.1 출력을 정답 대비 채점 비교. (Korean 경로 안전하게 파일에서 읽음)"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import evaluation as ev  # noqa: E402
from core import coverage as cov  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

gold = next(ROOT.glob("자본주의*.xml")).read_text(encoding="utf-8")
files = {
    "v1":   next(ROOT.glob("문제점/*아웃풋3.xml")),
    "v2":   next(ROOT.glob("extract_assemble/*/*_v2.xml")),
    "v2.1": next(ROOT.glob("extract_assemble/*/*_v2_1.xml")),
}


def hard(s):
    s = re.sub(r"[「」『』《》〈〉\"'“”‘’]", "", s or "")
    return re.sub(r"\s+", "", re.sub(r"\d", "", s))


def f1(xml):
    o = ev._norm_text
    ev._norm_text = hard
    r = ev.score(gold, xml, strict=False)
    ev._norm_text = o
    return {k: r[k].f1 for k in list(ev.TYPE_SPECS) + ["__micro__"]}


data = {n: f1(p.read_text(encoding="utf-8")) for n, p in files.items()}

print(f'{"태그":<16}{"v1":>8}{"v2":>8}{"v2.1":>8}')
for k, sp in ev.TYPE_SPECS.items():
    print(f"  {sp.label:<14}" + "".join(f"{data[n][k]*100:7.1f}%" for n in files))
print(f'  {"전체 micro":<14}' + "".join(f'{data[n]["__micro__"]*100:7.1f}%' for n in files))

# 개체 수
print("\n개체 수 (정답 / v1 / v2 / v2.1):")
anns = {"정답": ev.extract_annotations(gold)}
for n, p in files.items():
    anns[n] = ev.extract_annotations(p.read_text(encoding="utf-8"))
for k, sp in ev.TYPE_SPECS.items():
    print(f"  {sp.label:<14}" + " / ".join(f"{sum(anns[n][k].values()):>3}"
                                           for n in ["정답", "v1", "v2", "v2.1"]))

src = (ROOT / "비평문" / "성현아.txt").read_text(encoding="utf-8")
print("\n분량(글자):", end=" ")
for n, p in files.items():
    c = cov.coverage(src, p.read_text(encoding="utf-8"))
    print(f"{n} {c['char_ratio']*100:.0f}%", end="  ")
print()
