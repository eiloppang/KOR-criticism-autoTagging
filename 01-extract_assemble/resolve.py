"""
extract_assemble/resolve.py
전역(global) 인물 role 해소 — 라벨 JSON(doc)을 받아 in-place로 role을 통일한다.

문제: 문장 단위 라벨링은 한 인물의 진짜 역할을 모름 → 문장마다 role이 다르거나 비고,
      외국 이론가를 scholar로 다는 등 정답(외국인→foreigner) 관행과 어긋남.

해법: 모든 persName 언급을 '이름'으로 묶어 인물당 role을 하나로 확정해 일괄 적용.
  - 라틴 표기(예: '마크 피셔(Mark Fisher)')가 한 번이라도 보이면 → 외국인 → foreigner
  - 아니면 그 인물의 다수결 role (빈 값/불일치 해소)

조립 전에 호출하면 되고, 라벨 재조립이라 API가 필요 없다.
"""
from __future__ import annotations

import json
import re
from collections import Counter

_PAREN = re.compile(r"[(（【\[].*?[)）】\]]")
_LATIN = re.compile(r"[A-Za-z]")


def _person_key(text: str) -> str:
    """인물 식별 키: 괄호(라틴 표기 등) 제거 + 한글만 → '마크 피셔(Mark Fisher)'=='마크 피셔'."""
    t = _PAREN.sub("", text or "")
    return re.sub(r"[^가-힣]", "", t)


def _iter_person_spans(doc: dict):
    for sec in doc.get("sections", []):
        for para in sec.get("paragraphs", []):
            for sent in para:
                for sp in sent.get("spans", []):
                    if sp.get("tag") == "persName":
                        yield sp


def resolve_person_roles(doc: dict) -> dict:
    """doc의 persName role을 인물 단위로 통일(in-place). 반환: 통계 dict."""
    groups: dict[str, dict] = {}
    for sp in _iter_person_spans(doc):
        text = sp.get("text", "")
        key = _person_key(text)
        if not key:
            continue
        g = groups.setdefault(key, {"foreign": False, "roles": Counter()})
        role = (sp.get("attrs") or {}).get("role", "").strip()
        if _LATIN.search(text) or "foreigner" in role:
            g["foreign"] = True
        if role:
            g["roles"][" ".join(sorted(role.split()))] += 1

    # 인물별 canonical role 결정
    canon: dict[str, str] = {}
    for key, g in groups.items():
        if g["foreign"]:
            canon[key] = "foreigner"
        elif g["roles"]:
            canon[key] = g["roles"].most_common(1)[0][0]
        else:
            canon[key] = ""

    # 모든 언급에 적용
    changed = 0
    for sp in _iter_person_spans(doc):
        key = _person_key(sp.get("text", ""))
        c = canon.get(key)
        if not c:
            continue
        sp.setdefault("attrs", {})
        if sp["attrs"].get("role") != c:
            changed += 1
        sp["attrs"]["role"] = c

    return {"persons": len(canon),
            "foreign": sum(1 for v in canon.values() if v == "foreigner"),
            "changed_mentions": changed}


# ── 따옴표 인용 보강 (결정론적, quote recall) ─────────────────────

_QUOTE_PATS = [re.compile(r"[“\"]([^“”\"]{2,}?)[”\"]"),   # 큰따옴표
               re.compile(r"[‘]([^‘’]{2,}?)[’]")]           # 작은따옴표(곡선)


def _all_sentences(doc: dict):
    for sec in doc.get("sections", []):
        for para in sec.get("paragraphs", []):
            yield from para


def add_quote_spans(doc: dict) -> int:
    """
    문장의 따옴표("…"/'…') 안 구절을 quote로 자동 태깅(in-place). 내용만(따옴표 제외).
    이미 태깅된 span과 겹치면 건너뜀. genre/type은 기존 LLM quote의 다수결을 따름.
    """
    from collections import Counter
    gc, tc = Counter(), Counter()
    for s in _all_sentences(doc):
        for sp in s.get("spans", []):
            if sp.get("tag") == "quote":
                a = sp.get("attrs") or {}
                if a.get("genre"):
                    gc[a["genre"]] += 1
                if a.get("type"):
                    tc[a["type"]] += 1
    genre = gc.most_common(1)[0][0] if gc else "poet"
    qtype = tc.most_common(1)[0][0] if tc else "direct"

    added = 0
    for s in _all_sentences(doc):
        text = s.get("text", "")
        spans = s.setdefault("spans", [])
        for pat in _QUOTE_PATS:
            for m in pat.finditer(text):
                content = m.group(1).strip()
                if len(content) < 2:
                    continue
                # 기존 span과 텍스트가 겹치면 스킵 (중복 방지)
                if any(content in (sp.get("text") or "") or (sp.get("text") or "") in content
                       for sp in spans):
                    continue
                spans.append({"text": content, "tag": "quote",
                              "attrs": {"genre": genre, "type": qtype}})
                added += 1
    return added


# ── LLM 기반 전역 인물 role 해소 (권장) ───────────────────────────

_ROLE_SYSTEM = """다음은 한 한국 문학비평문에 등장하는 인물 이름 목록(JSON 배열)이다.
각 인물의 역할(role)을 정해 JSON으로만 답하라.

허용값: critic novelist poet playwright essayist translator childrenauthor scholar foreigner writer other
규칙:
- 외국(한국인이 아닌) 이론가·철학자·문인·비평가는 'foreigner' 하나로 한다.
- 한국 시인은 'poet', 비평가/평론가는 'critic', 학자/연구자는 'scholar', 번역가는 'translator'.
- 판단이 어려우면 'other'.

출력 형식(JSON only, 설명 금지): {"roles": {"이름": "role", ...}}"""


def resolve_person_roles_llm(doc: dict, provider) -> dict:
    """
    전체 인물 이름을 LLM에 한 번에 주고 role을 받아 통일(in-place).
    외국인은 LLM 판단(foreigner)으로, 그 외는 LLM 우선·문장단위 다수결 보완.
    API 1회.
    """
    # 표면형별 문장단위 role 다수결 수집
    per_text: dict[str, Counter] = {}
    for sp in _iter_person_spans(doc):
        t = sp.get("text", "").strip()
        if not t:
            continue
        role = (sp.get("attrs") or {}).get("role", "").strip()
        c = per_text.setdefault(t, Counter())
        if role:
            c[" ".join(sorted(role.split()))] += 1

    names = sorted(per_text)
    if not names:
        return {"persons": 0, "foreign": 0, "changed_mentions": 0}

    raw = provider.generate_tei(json.dumps(names, ensure_ascii=False), _ROLE_SYSTEM)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    llm_roles = json.loads(m.group(0)).get("roles", {}) if m else {}

    # canonical 결정: 외국인=LLM, 그외=LLM 우선·다수결 보완
    canon: dict[str, str] = {}
    for t in names:
        lr = (llm_roles.get(t) or "").strip()
        if "foreigner" in lr:
            canon[t] = "foreigner"
        elif lr:
            canon[t] = lr
        elif per_text[t]:
            canon[t] = per_text[t].most_common(1)[0][0]
        else:
            canon[t] = ""

    changed = 0
    for sp in _iter_person_spans(doc):
        t = sp.get("text", "").strip()
        c = canon.get(t)
        if not c:
            continue
        sp.setdefault("attrs", {})
        if sp["attrs"].get("role") != c:
            changed += 1
        sp["attrs"]["role"] = c

    return {"persons": len(canon),
            "foreign": sum(1 for v in canon.values() if v == "foreigner"),
            "changed_mentions": changed}
