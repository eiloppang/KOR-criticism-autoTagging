# extract-then-assemble-architecture (추출-후-조립 아키텍처, v2)

미태깅 비평문(.docx/.txt)을 XSD 스키마에 **구조적으로 유효한** TEI-XML로 자동 태깅하는
파이프라인에서 **실제로 쓰인 코드 파일들만** 모아둔 폴더입니다.
(원본은 `extract_assemble/`·`core/` 에 그대로 있고, 이 폴더는 그 사본입니다.)

핵심 아이디어: **LLM은 XML을 만들지 않는다.** LLM은 "어디가 무엇인가"(의미 라벨)만 내고,
**코드가 원문을 그대로 둔 채 태그만 끼워** 유효한 TEI를 조립한다 → 분량 손실·구조 위반 불가.

## 편당 처리 순서 (각 단계가 돌리는 코드)

| # | 단계 | 파일 / 함수 | 코드·LLM | 하는 일 |
|---|------|------------|:---:|------|
| 1 | 구조화 | `structure.py` · `build_structure` | 코드 | 원문 → `div`/`p`/`s`(섹션·문단·문장) 골격. 분량 100% 보존 |
| 2 | 라벨링 | `annotate.py` · `annotate_doc` | **LLM** | 문장마다 개체 span JSON(persName·title·date 등). **병목** |
| 3 | 인물 해소 | `resolve.py` · `resolve_person_roles_llm` | **LLM** | 인물명 role(비평가/시인 등) 판정 |
| 4 | 인용 보강 | `resolve.py` · `add_quote_spans` | 코드 | 따옴표 인용 구간을 span으로 보강 |
| 5 | 조립 | `assemble.py` · `assemble` | 코드 | 골격+라벨 → 유효 TEI. `schema_rules.py`로 enum 스냅·`xml:id` 유일화·중첩 방지·date 정책 강제 |
| 6 | 검증 | `assemble.py` · `validate` | 코드 | XSD 스키마 검증(0 오류 확인) |
| 7 | 분량 | `core/coverage.py` · `coverage` | 코드 | 원문 대비 분량 보존율 측정 |

## 파일 목록
- `structure.py` — 1단계 골격화
- `annotate.py` — 2단계 문장 라벨링 (LLM)
- `resolve.py` — 3단계 인물 role 해소(LLM) + 4단계 인용 보강
- `assemble.py` — 5·6단계 TEI 조립 + XSD 검증
- `schema_rules.py` — `assemble`이 쓰는 스키마 강제 규칙(enum·id·중첩·date)
- `core/coverage.py` — 7단계 분량 보존율
- `core/providers/` — LLM 인터페이스. 실제 사용: `claude_provider.py`(Claude). `base.py`=공통 인터페이스, gemini/ollama=교체 가능 백엔드
- `mitae_run.py` — **드라이버**: `미태깅/미태깅` → `미태깅_결과` 로 위 7단계를 순차 실행
- `batch_run.py` — mirae PDF용 드라이버. `mitae_run.py`가 `_meta`(제목·저자 파싱)·`_safe`(파일명 정리)를 여기서 가져옴

## 실행 (원본 패키지 기준)
```bash
python -m extract_assemble.mitae_run          # 미처리분 전체
python -m extract_assemble.mitae_run --force   # 이미 있어도 다시
```
> 이 사본 폴더는 **참조·문서용**입니다. 실행은 원본 `extract_assemble/` 패키지에서 하세요
> (import 경로가 `extract_assemble.*`·`core.*` 로 잡혀 있음).
