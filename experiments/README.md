# 태깅 정확도 비교 실험 (5단계)

LLM 자동 태깅의 정확도를 **세 가지 방식**으로 측정·비교하는 실험 프레임워크.
정답(수작업 태깅)이 생기면 코드 수정 없이 진짜 정확도가 산출되도록 설계되었다.

## 다섯 단계 ↔ 구현

| 단계 | 내용 | 구현 위치 |
|---|---|---|
| 1. zero-shot | 스키마+규칙만 (사전·예시 제거) | 모드 `schema_only` |
| 2. 설계 파이프라인 | 사전매칭+내장예시+청킹+후처리 (현재 시스템) | 모드 `pipeline` |
| 3. 수작업 정답 + 채점기 | 정답 TEI를 기준으로 P/R/F1 계산 | `core/evaluation.py` |
| 4. few-shot 학습 | 수작업 정답을 프롬프트 예시로 주입 (ICL) | 모드 `few_shot` |
| 5. 3단 비교 | 1·2·4를 같은 텍스트에 돌려 정답 대비 채점 | `experiments/run_comparison.py` |

## "학습"에 대하여 (4단계)

- **Claude는 파인튜닝 불가** → **Few-shot In-Context Learning** 을 쓴다.
- 모델 가중치를 바꾸는 게 아니라, **수작업 정답 예시를 프롬프트에 넣어** 모델이
  그 태깅 기준·스타일을 모방하게 한다. `generate_tei()` 호출 그대로라 Gemini·Claude·
  Ollama 어디서나 동일하게 작동한다.
- ⚠️ **컨닝 방지**: few-shot 예시로 쓴 텍스트를 테스트하면 점수가 부풀려진다.
  비평문 2개를 써서 **하나는 예시용(`--few-shot-source`), 다른 하나는 테스트용(`--input`)**
  으로 분리한다.

## 채점 방식 (`core/evaluation.py`)

`extract_annotations()` 가 TEI를 개체 다중집합으로 바꾸고, 다중집합 교집합으로
TP/FP/FN을 센다. 두 수준:

- **느슨(lenient)**: 태그 종류 + 텍스트만 일치 → "개체를 찾았는가"
- **엄격(strict)**: 텍스트 + 핵심 속성(role/level/type/value/when 등)까지 일치 → "올바르게 분류했는가"

느슨과 엄격의 **격차 = 속성 분류 오류율**.

엔진 단독 확인(API·정답 불필요):
```
python -m core.evaluation
```

## 실행

```bash
# 지금 단계 (정답 없음) — 모드만 실행, 모드 간 일치도 측정
python -m experiments.run_comparison run --input 비평문/B.txt --provider gemini

# 정답이 생긴 뒤 — 진짜 정확도 채점
python -m experiments.run_comparison run \
    --input 비평문/B.txt --provider gemini \
    --few-shot-source gold/A.tei.xml \
    --gold gold/B.tei.xml

# 이미 만든 두 XML 오프라인 채점 (API 불필요)
python -m experiments.run_comparison score --gold gold/B.tei.xml --pred out/pipeline.xml
```

출력: `experiments/out/{모드}.xml`, `report.md`(마크다운 표), `metrics.csv`.

## 정답(gold)을 나중에 올리는 방법 ← 핵심

평가 엔진은 정답을 **인자**로 받으므로, 지금은 비워두고 나중에 채우면 된다.

1. 비평문 1개를 **TEI/XML로 손 태깅** (`korean-critique-schema.xsd` 형식, 같은 인라인 태그
   persName/title/orgName/term/quote/interp/date 사용).
   - 빠른 방법: `pipeline` 모드로 초안을 뽑은 뒤 사람이 **교정**하면 처음부터 하는 것보다 훨씬 빠르다.
2. 그 파일을 `gold/` 폴더에 두고 `--gold`(테스트 대상) / `--few-shot-source`(다른 비평문) 로 지정.
3. **코드 수정 0** — 같은 `score()` 가 즉시 진짜 P/R/F1을 계산한다.

> 정답이 없으면 '정확도'(맞췄는가)는 측정 불가하고 '일치도'(모드끼리 합치하는가)만
> 볼 수 있다. 5단계 검증의 전제는 정답 1건이다.
