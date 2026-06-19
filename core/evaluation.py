"""
core/evaluation.py
두 TEI/XML 태깅 결과를 비교하여 태그별 정밀도/재현율/F1을 계산하는 평가 엔진.

용도
----
- 정답(gold, 수작업 태깅) 대비 예측(pred, 자동 태깅)의 정확도 측정  → score()
- 정답이 없을 때 두 모드의 일치도(agreement) 측정              → score() 를
  한쪽을 기준(reference)으로 삼아 호출 (F1은 대칭이라 어느 쪽을 기준으로 둬도 동일)

핵심 아이디어
-------------
core/extractor.py 의 extract_all() 이 이미 TEI에서 개체(인물·작품·기관·용어·
인용·해석·날짜)를 속성과 함께 뽑아낸다. 이를 그대로 재사용하여 각 XML을
"개체 집합"으로 바꾼 뒤, 다중집합(Counter) 교집합으로 TP/FP/FN을 센다.

두 가지 채점 수준
-----------------
- lenient (느슨): 태그 종류 + 텍스트만 일치하면 정답
- strict  (엄격): 텍스트 + 핵심 속성(role/level/type/value 등)까지 일치해야 정답

엄격 점수는 "개체를 찾았는가"가 아니라 "속성까지 올바르게 분류했는가"를 측정한다.
느슨 점수와 엄격 점수의 차이가 곧 '속성 분류 오류율'을 의미한다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


# ── 개체 유형별 채점 설정 ─────────────────────────────────────────
#
#   tag        : 채점 대상 TEI 인라인 태그(local-name). //tei:text 하위만 본다.
#   attr_names : 엄격 채점에서 추가로 일치해야 하는 TEI 속성명
#   set_attrs  : 공백 구분 복수값을 순서 무시 집합으로 비교할 속성 (예: role)
#
# 텍스트는 element.itertext() 로 추출 → 태그 안 내용만, 꼬리말(tail) 제외.
# 채점에서 제외하는 속성: xml:id, ref, source (보조/서지 정보)

@dataclass(frozen=True)
class _TypeSpec:
    label: str
    tag: str
    attr_names: tuple[str, ...] = ()
    set_attrs: tuple[str, ...] = ()


TYPE_SPECS: dict[str, _TypeSpec] = {
    "persons":         _TypeSpec("인물(persName)", "persName", ("role",), set_attrs=("role",)),
    "works":           _TypeSpec("작품(title)",    "title",    ("level", "type")),
    "orgs":            _TypeSpec("기관(orgName)",  "orgName"),
    "concepts":        _TypeSpec("용어(term)",     "term",     ("type",)),
    "quotes":          _TypeSpec("인용(quote)",    "quote",    ("type", "genre")),
    "interpretations": _TypeSpec("해석(interp)",   "interp",   ("value", "ana")),
    "dates":           _TypeSpec("날짜(date)",     "date",     ("when",)),
}


# ── 정규화 ────────────────────────────────────────────────────────

def _norm_text(s: str) -> str:
    """비교용 텍스트 정규화: 앞뒤 공백·따옴표 제거, 내부 공백 1칸으로 축약."""
    s = (s or "").strip().strip('"“”‘’\'')
    s = re.sub(r"\s+", " ", s)
    return s


def _norm_attr(value: str, is_set: bool) -> str:
    """속성값 정규화. 집합 속성(role 등)은 공백 분리 후 정렬하여 순서 무시 비교."""
    value = (value or "").strip()
    if is_set:
        tokens = sorted(t for t in value.split() if t)
        return " ".join(tokens)
    return _norm_text(value)


# ── XML → 개체 다중집합 ───────────────────────────────────────────

def extract_annotations(xml_string: str, strict: bool = False) -> dict[str, Counter]:
    """
    TEI/XML 문자열을 개체 유형별 다중집합으로 변환한다.
    //tei:text 하위의 인라인 태그만 보며(teiHeader 제외), 텍스트는 itertext()로
    태그 안 내용만 추출(꼬리말 제외)한다.

    Returns
    -------
    {유형키: Counter[record]}  — record는 비교 키 튜플
        lenient: (정규화_텍스트,)
        strict : (정규화_텍스트, 속성1, 속성2, ...)

    Raises
    ------
    ValueError : XML 파싱 실패 시
    """
    from lxml import etree

    # collect_ids=False: xml:id 중복(프로젝트 _dedup_xml_ids가 같은 인물에 같은 id를
    # 부여 → XML ID 고유성 위반)에도 파싱 가능하게 한다. 평가는 ID를 보지 않는다.
    parser = etree.XMLParser(collect_ids=False, recover=False)
    try:
        root = etree.fromstring(xml_string.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"XML 파싱 실패: {e}") from e

    out: dict[str, Counter] = {}
    for key, spec in TYPE_SPECS.items():
        counter: Counter = Counter()
        for el in root.xpath(f"//tei:text//tei:{spec.tag}", namespaces=NS):
            text = _norm_text("".join(el.itertext()))
            if not text:
                continue
            if strict:
                attrs = tuple(
                    _norm_attr(el.get(a, ""), a in spec.set_attrs)
                    for a in spec.attr_names
                )
                record = (text, *attrs)
            else:
                record = (text,)
            counter[record] += 1
        out[key] = counter

    return out


# ── 채점 ──────────────────────────────────────────────────────────

@dataclass
class TypeScore:
    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    fp_items: list = field(default_factory=list)   # 예측에만 있음 (오탐)
    fn_items: list = field(default_factory=list)   # 정답에만 있음 (누락)

    @property
    def gold_total(self) -> int:
        return self.tp + self.fn

    @property
    def pred_total(self) -> int:
        return self.tp + self.fp

    @property
    def precision(self) -> float:
        return self.tp / self.pred_total if self.pred_total else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.gold_total if self.gold_total else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _score_counters(gold: Counter, pred: Counter, label: str) -> TypeScore:
    """다중집합 교집합으로 TP/FP/FN을 센다."""
    inter = gold & pred  # 다중집합 교집합: 각 record에 대해 min(count)
    tp = sum(inter.values())
    score = TypeScore(label=label, tp=tp,
                      fp=sum(pred.values()) - tp,
                      fn=sum(gold.values()) - tp)
    # 오탐/누락 항목 목록 (검수용)
    for record, cnt in (pred - gold).items():
        score.fp_items.extend([record] * cnt)
    for record, cnt in (gold - pred).items():
        score.fn_items.extend([record] * cnt)
    return score


def score(gold_xml: str, pred_xml: str, strict: bool = False) -> dict[str, TypeScore]:
    """
    정답 XML 대비 예측 XML을 채점한다.

    Parameters
    ----------
    gold_xml : 기준이 되는 TEI/XML (수작업 정답, 또는 비교 기준 모드)
    pred_xml : 채점 대상 TEI/XML (자동 태깅 결과)
    strict   : True면 속성까지 일치해야 정답으로 인정

    Returns
    -------
    {유형키: TypeScore, "__micro__": TypeScore}
        __micro__ : 전체 유형을 합산한 마이크로 평균
    """
    gold_ann = extract_annotations(gold_xml, strict=strict)
    pred_ann = extract_annotations(pred_xml, strict=strict)

    results: dict[str, TypeScore] = {}
    micro = TypeScore(label="전체(micro)")

    for key, spec in TYPE_SPECS.items():
        s = _score_counters(gold_ann.get(key, Counter()),
                            pred_ann.get(key, Counter()),
                            spec.label)
        results[key] = s
        micro.tp += s.tp
        micro.fp += s.fp
        micro.fn += s.fn

    results["__micro__"] = micro
    return results


# ── 리포트 ────────────────────────────────────────────────────────

def to_dataframe(results: dict[str, TypeScore]) -> pd.DataFrame:
    """채점 결과를 표(DataFrame)로 변환한다."""
    rows = []
    order = list(TYPE_SPECS.keys()) + ["__micro__"]
    for key in order:
        s = results.get(key)
        if s is None:
            continue
        rows.append({
            "유형": s.label,
            "정답수": s.gold_total,
            "예측수": s.pred_total,
            "TP": s.tp,
            "FP": s.fp,
            "FN": s.fn,
            "정밀도": round(s.precision, 3),
            "재현율": round(s.recall, 3),
            "F1": round(s.f1, 3),
        })
    return pd.DataFrame(rows)


def format_markdown(results: dict[str, TypeScore], title: str = "채점 결과") -> str:
    """채점 결과를 마크다운 표 문자열로 변환한다. tabulate 미설치 시 일반 표로 폴백."""
    df = to_dataframe(results)
    try:
        body = df.to_markdown(index=False)
    except ImportError:
        body = df.to_string(index=False)
    return f"### {title}\n\n" + body


# ── 자체 시연 (정답 없이 엔진 작동 확인용) ────────────────────────

_DEMO_GOLD = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>데모</title><author>미상</author></titleStmt>
  <publicationStmt><p>x</p></publicationStmt><sourceDesc><p>x</p></sourceDesc></fileDesc></teiHeader>
  <text><body><div type="body">
    <p><s><persName xml:id="p-kim" role="novelist critic">김동인</persName>은
    <date when="1919">1919년</date>
    <title xml:id="t-changjo" level="j" type="coterie">창조</title>를 창간하고
    <term type="movement">자연주의</term>를 주창했다.</s>
    <s><persName xml:id="p-lee" role="novelist">이광수</persName>의
    <term type="concept">계몽주의</term>를
    <interp value="critical" ana="문학관">반박했다</interp>.</s></p></div></body></text>
</TEI>"""

# 예측: 이광수의 role 누락(novelist→없음), 창조의 type 오류(coterie→journal),
#       자연주의 누락, '근대'(orgName 오탐) 추가
_DEMO_PRED = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>데모</title><author>미상</author></titleStmt>
  <publicationStmt><p>x</p></publicationStmt><sourceDesc><p>x</p></sourceDesc></fileDesc></teiHeader>
  <text><body><div type="body">
    <p><s><persName xml:id="p-kim" role="novelist critic">김동인</persName>은
    <date when="1919">1919년</date>
    <title xml:id="t-changjo" level="j" type="journal">창조</title>를 창간했다.</s>
    <s><persName xml:id="p-lee">이광수</persName>의
    <term type="concept">계몽주의</term>를
    <interp value="critical" ana="문학관">반박했다</interp>.</s></p></div></body></text>
</TEI>"""


def _demo() -> None:
    import sys
    try:  # Windows cp949 콘솔에서도 한글·기호 출력되도록 UTF-8 강제
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 60)
    print("평가 엔진 자체 시연 - 합성 정답 vs 합성 예측")
    print("=" * 60)
    print("\n[느슨(lenient) — 태그+텍스트만 일치]")
    print(format_markdown(score(_DEMO_GOLD, _DEMO_PRED, strict=False), "느슨 채점"))
    print("\n[엄격(strict) — 속성까지 일치]")
    res = score(_DEMO_GOLD, _DEMO_PRED, strict=True)
    print(format_markdown(res, "엄격 채점"))
    print("\n[검수용 — 누락(FN)·오탐(FP) 항목]")
    for key, s in res.items():
        if s.fn_items or s.fp_items:
            print(f"  · {s.label}: 누락={s.fn_items} 오탐={s.fp_items}")


if __name__ == "__main__":
    _demo()
