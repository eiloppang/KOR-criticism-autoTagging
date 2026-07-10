# KorCritTEI — 한국문학비평 TEI 자동 태깅

한국 현대시 **비평문**을 `korean-critique-schema.xsd`(TEI 기반) 스키마에
**구조적으로 유효한** TEI-XML로 자동 변환한다.
핵심 엔진은 [`extract_assemble/`](extract_assemble/) 의 **추출-후-조립(extract-then-assemble)** 파이프라인이다.

> 이 README는 프로젝트의 태깅 엔진인 **`extract_assemble`** 를 설명한다.

---

## 1. 핵심 아이디어 — "추출 후 조립"

**LLM은 XML을 만들지 않는다.** LLM은 문장 안에서 "어디가 무엇인가"(의미 라벨)만 판단하고,
**태그 삽입과 문서 조립은 전부 코드가** 한다.

```
LLM       : 문장은 그대로 두고, 그 안의 부분 문자열만 지목  (persName·title·date …)
코드(파이프라인) : 원문을 한 글자도 바꾸지 않고 태그만 끼워 유효한 TEI로 조립·검증
```

### 왜 이렇게 하나

- **분량 손실 방지** — 원문이 LLM의 입력·출력 길이 한계를 넘어서면 문장 누락·절단(truncation)이나
  없는 내용을 지어내는 **할루시네이션**이 생겨 분석 대상 자체가 훼손된다.
  코드가 원문을 재생성하지 않고 태그만 삽입하므로 **분량이 100% 보존**된다.
- **구조 위반 불가** — 조립기가 스키마 규칙(허용 태그·enum·id·중첩)을 강제하며 문서를 만들기 때문에
  XSD 위반이 **애초에 발생하지 않는다.**

---

## 2. 처리 흐름

```
원문 텍스트
  │
  ├─ structure.py   (코드)  원문 → div/p/s 골격(섹션·문단·문장)     ← 분량 100% 보존
  ├─ annotate.py    (LLM)   각 문장 → 개체 span 라벨 JSON            ← 병목(문장당 LLM)
  ├─ resolve.py     (LLM+코드) 인물 role 전역 통일 + 따옴표 인용 보강
  ├─ assemble.py    (코드)  골격 + 라벨 → 유효 TEI 조립 (schema_rules 강제)
  └─ validate       (코드)  XSD 검증 → 0 오류 보장
```

각 편의 결과: `<이름>_v2.xml`(최종 TEI) + `<이름>_v2.labels.json`(중간 라벨).

---

## 3. 파일별 역할

### ① 파이프라인 코어
| 파일 | 코드/LLM | 역할 |
|------|:---:|------|
| `structure.py` | 코드 | 원문 → 섹션(`div`)·문단(`p`)·문장(`s`) 골격. "N. 제목" heading·빈 줄·한국어 문장분리 기준. **분량 보존** |
| `annotate.py` | **LLM** | 문장별 개체 span 라벨 JSON 추출(persName·title·term·interp 등). few-shot, 문단 단위 배치 |
| `resolve.py` | LLM+코드 | 인물 role **전역 통일**(라틴 표기→foreigner, 그 외 다수결) + 따옴표 인용 span 보강 |
| `assemble.py` | 코드 | 골격+라벨 → 완전한 `teiHeader`와 본문을 갖춘 유효 TEI 조립 및 XSD 검증 |
| `schema_rules.py` | 코드 | `assemble`이 쓰는 스키마 강제 규칙(enum 스냅·id 유일화·중첩 방지·date 정책) |

### ② 입력별 드라이버 (실행 진입점)
| 파일 | 입력 | 출력 |
|------|------|------|
| `run.py` | 단일 텍스트 파일(`--input`) | 지정 경로(`--out`). `--limit`로 앞 N문장만 저렴 테스트 |
| `batch_run.py` | `mirae/`의 **정상 PDF**(텍스트 레이어 OK) | `mirea_results/` |
| `ocr_run.py` | **스캔(이미지) PDF** — EasyOCR로 텍스트화 | `mirea_results/` (+ `_ocr_txt/`) |
| `cid_run.py` | **CID 폰트 PDF**(띄어쓰기 소실) — kiwipiepy로 복원 | `mirea_results/` |
| `docx_run.py` | 루트·`mirae/`의 `.docx` | `mirea_results/` |
| `mitae_run.py` | `미태깅/미태깅/`의 `.docx`·`.txt` | `미태깅_결과/` |

> 드라이버는 공통으로 **출력이 이미 있으면 건너뛴다**(이어하기). 중단돼도 완료분은 보존된다.

### ③ 검증·분석 도구
| 파일 | 역할 |
|------|------|
| `check_complete.py` | 출력 TEI에 원문 텍스트가 빠짐없이 들어갔는지(실제 텍스트 기준) 검증 |
| `compare_html.py` | 정답(A) vs 자동(B) TEI를 문장 단위로 정렬해 좌우 비교 HTML 생성 |
| `corpus_analyze.py` | 태깅된 코퍼스 종합 분석(빈도·담론 네트워크·시간 추이) → `_analysis/` 대시보드·CSV |
| `평가_성현아.py` | 성현아 편을 gold 대비 채점해 논문 F1 재현(표기 정규화 후 다중집합 P/R/F1) |

---

## 4. 출력물

```
mirea_results/  또는  미태깅_결과/
├─ <이름>_v2.xml           최종 TEI (XSD 유효)
├─ <이름>_v2.labels.json   중간 라벨(문장별 span) — 재조립·디버깅용
└─ _txt/ · _ocr_txt/       추출/OCR 원문(검수용)
```

---

## 5. 스키마 강제 지점 (`schema_rules.py`)

v1(생성-후-수리)에서 발생하던 위반들을 v2는 **구조적으로 원천 차단**한다.

| 위반 유형 | v2의 강제 방식 |
|---|---|
| `<date>` in `<s>` | 코드가 `s` 안에 date를 애초에 안 넣음(정책: 텍스트 유지) |
| 중복 `xml:id` | 첫 등장만 `xml:id`, 반복은 `ref="#id"` → 항상 유일 |
| interp/quote/title 중첩 | span 겹침 시 **비중첩만 선택** → simpleContent 위반 불가 |
| 속성 enum 위반 | role/level/type/value/genre를 허용값으로 **스냅**, 아니면 제거 |
| 필수 속성/헤더 누락 | 기본값 채움 + `teiHeader` 완전 조립 |

---

## 6. 라벨 JSON 계약 (LLM 출력)

LLM은 **문장 텍스트를 절대 바꾸지 않고**, 그 안의 부분 문자열(span)만 지목한다.

```json
{"text": "김동인은 1919년 창조를 창간했다.",
 "spans": [
   {"text": "김동인", "tag": "persName", "attrs": {"role": "novelist critic"}},
   {"text": "1919년", "tag": "date",     "attrs": {"when": "1919"}},
   {"text": "창조",   "tag": "title",    "attrs": {"level": "j", "type": "coterie"}}
 ]}
```

---

## 7. 설치 & 실행

```bash
pip install -r requirements.txt
```

`.env` (루트)에 LLM 키를 설정한다:

```ini
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
```

실행 예시:

```bash
# 단일 텍스트 한 편
python -m extract_assemble.run --input 비평문/성현아.txt --out extract_assemble/out/성현아_v2.xml

# 미태깅 폴더 일괄 (docx/txt → 미태깅_결과)
python -m extract_assemble.mitae_run          # 미처리분만
python -m extract_assemble.mitae_run --force   # 이미 있어도 다시

# 정상 PDF 일괄
python -m extract_assemble.batch_run --limit 3
```

---

## 8. 평가

정답(gold)이 있는 **성현아** 편에 한해 자동 태깅 정확도를 산출한다.

```bash
python -m extract_assemble.평가_성현아
```

느슨(텍스트) / 엄격(텍스트+속성) 두 기준의 P/R/F1을 낸다.
비교 전 공백·낫표/따옴표·각주 번호를 정규화해 마크업 관행 차이가 점수를 왜곡하지 않게 한다.

---

## 규칙

- `korean-critique-schema.xsd` 는 협업자가 설계한 것으로 **절대 수정하지 않는다.**
- XML 출력은 반드시 해당 스키마에 대해 **검증**한다(0 오류).
- LLM Provider는 공통 인터페이스(`core/providers/`)로 **교체 가능**하다(Claude/Gemini/Ollama).
