# extract_assemble — 추출-후-조립 아키텍처 (v2)

스키마(`korean-critique-schema.xsd`)를 **구조적으로 보장**하는 태깅 파이프라인.
LLM이 XML을 만들지 않고 **의미 라벨만** 내고, 코드가 **원문에 태그를 끼워 유효한 TEI를 조립**한다.

## 왜 v2인가 (v1 = 생성-후-수리의 한계)
- v1: LLM이 완전한 TEI/XML 생성 → 코드가 수리. **본문을 LLM이 다시 토해내므로 분량 누락·truncation 위험**, 구조 위반은 사후 추측 교정.
- v2: LLM은 "어디가 무엇인가"만 판단 → 코드가 **원문을 그대로 두고 태그만 삽입**. 분량 손실 불가, 구조 위반 불가.

## 처리 흐름
```
원문 텍스트
  │
  ├─ structure.py   (코드)  원문 → div/p/s 골격 (섹션·문단·문장)  ← 분량 100% 보존
  │
  ├─ annotate.py    (LLM)   각 문장 → 개체 라벨 JSON
  │                          [{text, tag, attrs}]  (XML 아님)
  │
  ├─ assemble.py    (코드)  골격 + 라벨 → 유효한 TEI 조립
  │     ├─ schema_rules: enum 스냅, interp/@ana 보강, date 정책, 중첩 방지
  │     └─ id 유일화 (첫 등장 xml:id, 반복 ref="#id")
  │
  └─ validate       XSD 검증 → 0 오류 보장
```

## 스키마 강제 지점 (schema_rules.py)
| 위반 유형 (v1에서 56건) | v2의 강제 방식 |
|---|---|
| `<date>` in `<s>` (22) | 코드가 `s` 안에 date를 **애초에 안 넣음** (정책: 텍스트로 유지 / 별도 기록) |
| 중복 xml:id (17) | 첫 등장만 `xml:id`, 반복은 `ref="#id"` → 항상 유일 |
| interp/quote/title 중첩 (17) | span 겹침 시 코드가 **비중첩만 선택** → simpleContent 위반 불가 |
| 속성 enum 위반 | role/level/type/value/genre를 **허용값으로 스냅**, 아니면 제거 |
| interp/@ana 누락 | 필수라 없으면 기본값 채움 |
| 헤더 누락(respStmt 등) | 코드가 완전한 teiHeader **고정 조립** |

## 모듈
- `schema_rules.py` — enum 집합·속성 정제·id 할당·문장 조립(중첩 방지·date 정책)
- `structure.py` — 원문 → 섹션/문단/문장 골격 (LLM 불필요)
- `assemble.py` — 골격 + 라벨 → 유효 TEI + XSD 검증
- `annotate.py` — (LLM) 문장 → 라벨 JSON  ※ 추후
- `run.py` — CLI 드라이버  ※ 추후

## 라벨(JSON) 형식 — LLM 출력 계약
```json
{"text": "김동인은 1919년 창조를 창간했다.",
 "spans": [
   {"text": "김동인", "tag": "persName", "attrs": {"role": "novelist critic"}},
   {"text": "1919년", "tag": "date", "attrs": {"when": "1919"}},
   {"text": "창조", "tag": "title", "attrs": {"level": "j", "type": "coterie"}}
 ]}
```
LLM은 **문장 텍스트는 절대 바꾸지 않고**, 그 안의 부분 문자열(span)만 지목한다.
