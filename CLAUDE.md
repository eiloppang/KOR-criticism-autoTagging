# KorCritTEI - 한국문학비평 TEI 자동 태깅 앱

## 프로젝트 개요
비평텍스트를 XSD 스키마 기반으로 TEI-XML 자동 변환하는 Streamlit 앱

## 기술 스택
- Python, Streamlit, lxml
- LLM: Gemini API (기본) / Ollama / Claude API (교체 가능)
- 시각화: Plotly, D3.js

## 핵심 파일
- korean-critique-schema.xsd: TEI 스키마 (수정 금지)
- 개발 문서: korean_critique_tagging_app_development_v2.md
- 비평문: 비평문\자본주의에 대처하는 우리의 자세 - 최백규와 최지인이 노동과 우울을 그리는 방식에 대하여 (성현아, 창비 2021 여름).pdf, 비평문\휴머니즘의 외부와 열림의 존재론(신해욱론)-김주원(2021 창비 신인평론).pdf

## 규칙
- XSD 스키마는 협업자가 설계한 것이므로 절대 수정하지 않음
- XML 출력은 반드시 해당 스키마에 대해 검증할 것
- LLM Provider는 공통 인터페이스로 교체 가능하게 설계
