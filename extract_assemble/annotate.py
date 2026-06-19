"""
extract_assemble/annotate.py
(LLM 단계) 골격의 각 문장 → 개체 span 라벨 JSON 추출.

LLM은 문장 텍스트를 바꾸지 않고, 그 안의 '부분 문자열'을 태그로 지목만 한다.
구조·검증은 코드(structure/assemble)가 담당하므로 LLM 실수는 라벨 품질에만 영향.

개선(v2.1):
  - few-shot 예시로 라벨 밀도·스타일 학습
  - interp는 '판단 문장 전체' + 적극 태깅, term은 비평 개념어까지(과태깅 주의)
  - 문단 단위 배치(같은 문단 문장끼리만 묶어 문맥 유지)
"""
from __future__ import annotations

import json
import re

ANNOTATE_SYSTEM = """너는 한국 근현대 문학비평 TEI 태깅 보조자다.
입력으로 '같은 문단의 연속된 문장 목록'(JSON)을 받고, 각 문장에서 발견되는 개체를
라벨링한 JSON'만' 출력한다. 문장 텍스트는 절대 바꾸지 말고, 각 span의 text는 그 문장
안의 '정확한 부분 문자열'이어야 한다. 문단 전체 맥락을 고려해 판단하라.

[태그와 허용 속성값]
- persName : 실명 인물. attrs.role = 공백 복수 가능
    critic novelist poet playwright essayist translator childrenauthor scholar foreigner other
- title    : 작품·저작·잡지명(낫표 「」는 빼고 제목만). attrs.level = m|a|j ,
    attrs.type = critic|novel|poem|play|essay|translation|children|contribution|foreign|other|
                 journal|newspaper|coterie|publication
- orgName  : 기관·단체·출판사·잡지사
- term     : 비평 개념어. 사조·철학개념뿐 아니라 이 비평이 분석 대상으로 반복하는 핵심어
    (분노, 노동, 노동자, 계급, 우울, 자본주의, 신자유주의, 젊은 시인들 등)도 등장마다 태깅.
    단 일상적 서술어·일반 명사는 제외하고 '비평이 개념으로 사유하는 말'만. attrs.type = concept|movement
- quote    : 인용 구절(따옴표·시 인용). attrs.type = direct|indirect|paraphrase|criticism|review|commentary,
    attrs.genre = critic|novel|poet|play|essay|foreign|other , attrs.source = 출처(알 때)
- interp   : 비평가의 가치판단(평가·동의·비판·의문). 판단이 보이면 적극적으로 태깅하고 놓치지 마라.
    범위는 술어구가 아니라 '판단이 담긴 문장 전체'. attrs.value = affirmative|neutral|critical,
    attrs.ana = 판단 기준(미학·사상·문학관·사회 등)
- date     : 연도·날짜. attrs.when = ISO(예: 1919, 2020년대→2020)

[예시]
입력: {"sentences":[
  {"i":0,"text":"박상수는 '몰락하는 시대감각' 속 젊은 시인들의 분노가 약해졌다고 진단한다."},
  {"i":1,"text":"이러한 진단은 타당해 보이며 동의할 만하다."},
  {"i":2,"text":"최지인의 「코러스」는 노동을 자아실현과 분리한다."}
]}
출력: {"results":[
  {"i":0,"spans":[
    {"text":"박상수","tag":"persName","attrs":{"role":"critic"}},
    {"text":"몰락하는 시대감각","tag":"quote","attrs":{"type":"indirect","genre":"critic"}},
    {"text":"젊은 시인들","tag":"term","attrs":{"type":"concept"}},
    {"text":"분노","tag":"term","attrs":{"type":"concept"}}
  ]},
  {"i":1,"spans":[
    {"text":"이러한 진단은 타당해 보이며 동의할 만하다.","tag":"interp","attrs":{"value":"affirmative","ana":"사회"}}
  ]},
  {"i":2,"spans":[
    {"text":"최지인","tag":"persName","attrs":{"role":"poet"}},
    {"text":"코러스","tag":"title","attrs":{"level":"a","type":"poem"}},
    {"text":"노동","tag":"term","attrs":{"type":"concept"}}
  ]}
]}

[출력 규칙] JSON only, 설명·코드블록 금지. 입력의 모든 i에 결과를 빠짐없이. span 없으면 "spans":[]."""


def _strip_json(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    return m.group(0) if m else t


def _paragraph_batches(doc: dict, max_sents: int):
    """같은 문단 문장끼리만 묶어 배치 생성. (문단이 크면 max_sents로 분할)"""
    for sec in doc.get("sections", []):
        for para in sec.get("paragraphs", []):
            for i in range(0, len(para), max_sents):
                yield para[i:i + max_sents]


def annotate_doc(doc: dict, provider, batch_size: int = 12,
                 progress=None) -> dict:
    """doc(골격)의 각 문장에 spans를 채워 반환한다(in-place)."""
    batches = list(_paragraph_batches(doc, batch_size))
    total = sum(len(b) for b in batches)
    done = 0

    for batch in batches:
        payload = {"sentences": [{"i": i, "text": s["text"]}
                                 for i, s in enumerate(batch)]}
        user = json.dumps(payload, ensure_ascii=False)
        try:
            raw = provider.generate_tei(user, ANNOTATE_SYSTEM)
            data = json.loads(_strip_json(raw))
            by_i = {r["i"]: r.get("spans", []) for r in data.get("results", [])}
            for i, s in enumerate(batch):
                s["spans"] = by_i.get(i, [])
        except Exception as e:
            for s in batch:
                s["spans"] = []
            if progress:
                progress(f"배치 라벨 실패: {e}")
        done += len(batch)
        if progress:
            progress(f"라벨링 {done}/{total} 문장")

    return doc
