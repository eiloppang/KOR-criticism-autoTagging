# 한국문학 비평텍스트 XML 자동 태깅 앱 개발 문서 (v2)

## 개발자 정보
- **개발자**: 박사과정 연구원
- **소속**: 한국학중앙연구원 인문정보학 / 디지털인문학
- **프로젝트명**: Korean Literary Criticism TEI Auto-Tagger (KorCritTEI)
- **작성일**: 2026년 2월 (v2 개정: 2026년 3월)

---

## 1. 프로젝트 개요

### 1.1 배경 및 필요성

한국 근현대 문학비평 텍스트의 디지털 인문학적 분석을 위해서는 체계적인 XML/TEI 인코딩이 필수적이다. 그러나 비평텍스트는 일반적으로 분량이 길고, 인물명(persName), 작품명(title), 기관명(orgName), 철학적 용어(term), 인용문(quote) 등 다양한 개체명이 밀집되어 있어 수작업 태깅에 상당한 시간과 노동이 소요된다.

본 프로젝트는 LLM(Large Language Model) 기반의 자동 태깅 시스템을 구축하여:
1. 비평텍스트의 기본 XML/TEI 구조 자동 생성
2. 개체명(Named Entity) 자동 인식 및 추출
3. 추출된 데이터의 CSV 변환 및 데이터베이스 구축
4. HTML 기반 시각화 웹사이트 제공

### 1.2 개발 목표

| 단계 | 목표 | 산출물 |
|------|------|--------|
| 1단계 | 비평텍스트 자동 XML 태깅 | TEI/XML 파일 |
| 2단계 | 개체명 추출 및 DB 구축 | CSV 데이터셋 |
| 3단계 | 웹 기반 시각화 | HTML 인터랙티브 사이트 |

### 1.3 v2 주요 변경 사항

| 항목 | v1 (2026.02) | v2 (2026.03) |
|------|-------------|-------------|
| 개발 환경 | Flask/FastAPI 서버 + Claude API | Claude Code (개발) + 모듈화된 LLM 백엔드 (배포) |
| 청킹 기본값 | max_tokens=8,000 | max_tokens=30,000 (단문은 청킹 불요) |
| LLM 백엔드 | Claude API 단일 | 교체 가능 설계 (Gemini / Ollama / Claude API) |
| 프론트엔드 | React/Vue.js | Streamlit (프로토타입·배포 겸용) |
| 프롬프트 | 기본 5종 개체명 | + `<interp>` 해석/평가 태깅, `<date>` 날짜 태깅 추가 |
| 배포 | Heroku/AWS | Streamlit Cloud (무료) / HuggingFace Spaces |
| 예상 기간 | 15주 | 4–6주 (Claude Code 활용) |

---

## 2. 기술 설계

### 2.1 XSD 스키마 분석

제공된 `korean-critique-schema.xsd`는 TEI P5 기반의 한국문학비평 전용 스키마로, 다음의 핵심 요소를 포함한다. **본 스키마는 협업 연구자가 설계한 것이며, 수정 없이 그대로 사용한다.**

#### 2.1.1 인라인 개체명 요소
```xml
<!-- 인물명 -->
<persName role="critic poet" ref="URI">김동인</persName>

<!-- 작품명 -->
<title level="a" type="novel">무정</title>

<!-- 기관명 -->
<orgName ref="URI">창조사</orgName>

<!-- 용어/개념 -->
<term type="movement">자연주의</term>

<!-- 인용문 -->
<quote type="direct" genre="critic" source="문장지 1939년 3월호">...</quote>

<!-- 해석/평가 (v2 추가) -->
<interp value="critical" ana="문체">부정적 평가 내용</interp>

<!-- 날짜 (v2 추가) -->
<date when="1919">1919년</date>
```

#### 2.1.2 역할(Role) 분류 체계
- `critic` (비평가)
- `novelist` (소설가)
- `poet` (시인)
- `playwright` (극작가)
- `essayist` (수필가)
- `translator` (번역가)
- `childrenauthor` (아동문학 작가)
- `scholar` (학자)
- `foreigner` (외국 문인)
- `other` (기타)

#### 2.1.3 해석/평가(Interp) 분류 체계 (v2 추가)
- `affirmative` (긍정적 해석/찬동)
- `neutral` (중립적 언급)
- `critical` (비판적/부정적 평가)

#### 2.1.4 문서 구조
```
TEI
├── teiHeader (메타데이터)
│   ├── fileDesc (서지정보)
│   │   ├── titleStmt (제목/저자/책임)
│   │   ├── publicationStmt (출판정보)
│   │   └── sourceDesc (원본출처)
│   └── encodingDesc (인코딩 방침)
│       ├── editorialDecl (편집원칙)
│       ├── tagsDecl (태그사용내역)
│       └── classDecl (분류체계)
└── text
    ├── front (서문, 목차) [선택]
    ├── body (본문: div > p > s) [필수]
    └── back (미주, 참고문헌) [선택]
```

### 2.2 시스템 아키텍처 (v2 개정)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit 사용자 인터페이스                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ 텍스트 입력 │  │ 설정 패널  │  │ 결과 다운로드/시각화    │  │
│  │ (파일/직접) │  │ (LLM/청크) │  │ (XML/CSV/HTML)         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       전처리 모듈                                │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ 텍스트 정규화  │→│ 시맨틱 청킹     │→│ 메타데이터 추출│  │
│  │ (줄바꿈, 특수) │  │ (단락/문장 단위)│  │ (제목, 저자)   │  │
│  └─────────────────┘  └──────────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│               LLM 처리 모듈 (교체 가능 설계)                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              LLM Provider (선택 가능)                    │   │
│  │  • Google Gemini API (무료 티어 — 배포 기본값)          │   │
│  │  • Ollama 로컬 (완전 무료 — 오프라인 사용)             │   │
│  │  • Anthropic Claude API (고품질 — 종량제)               │   │
│  │                                                         │   │
│  │  공통 인터페이스: XSD 스키마 + 태깅 지침 + 텍스트 청크  │   │
│  │  공통 출력: 구조화된 TEI/XML                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐   │
│  │ NER 태깅     │  │ 역할 분류    │  │ 인용문 분석      │   │
│  └───────────────┘  └───────────────┘  └───────────────────┘   │
│  ┌───────────────┐  ┌───────────────┐                          │
│  │ 해석 태깅    │  │ 날짜 태깅    │  ← v2 추가               │
│  └───────────────┘  └───────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      후처리 및 병합 모듈                         │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────────┐  │
│  │ 청크 병합   │→│ XML 검증     │→│ ID/ref 정규화      │  │
│  │ (오버랩 처리)│  │ (XSD 기반)   │  │ (중복 제거)        │  │
│  └──────────────┘  └───────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      데이터 추출 모듈                            │
│  ┌───────────────────┐  ┌─────────────────────────────────┐    │
│  │ XPath/XSLT 쿼리  │→│ CSV 생성                       │    │
│  │ (개체명별 추출)   │  │ (인물/작품/기관/용어 테이블)   │    │
│  └───────────────────┘  └─────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      시각화 모듈                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ 네트워크 그래프│  │ 타임라인    │  │ 인터랙티브 필터   │    │
│  │ (D3.js)      │  │ (Timeline.js)│  │ (검색, 정렬)      │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 LLM 백엔드 교체 가능 설계 (v2 신규)

비용과 배포 환경에 따라 LLM 백엔드를 자유롭게 교체할 수 있도록 공통 인터페이스를 설계한다.

#### 2.3.1 Provider 비교

| Provider | 비용 | 품질 | 컨텍스트 | 배포 적합성 | 비고 |
|----------|------|------|----------|------------|------|
| Google Gemini API | 무료 티어 존재 | 상 | 1M 토큰 | 높음 (배포 기본값) | 무료 한도 내 소규모 사용 적합 |
| Ollama 로컬 | 완전 무료 | 모델별 상이 | 모델별 상이 | 중간 (로컬 전용) | GPU 필요, 오프라인 사용 가능 |
| Claude API | 종량제 | 최상 | 200K 토큰 | 높음 | 고품질 필요 시 |

#### 2.3.2 공통 인터페이스 설계
```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """LLM 백엔드 공통 인터페이스"""
    
    @abstractmethod
    def generate_tei(self, text: str, schema_prompt: str) -> str:
        """비평텍스트를 TEI/XML로 변환"""
        pass
    
    @abstractmethod
    def get_max_tokens(self) -> int:
        """해당 Provider의 최대 컨텍스트 크기 반환"""
        pass

class GeminiProvider(LLMProvider):
    """Google Gemini API — 배포 기본값 (무료 티어)"""
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
    
    def generate_tei(self, text, schema_prompt):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        response = model.generate_content(schema_prompt + "\n\n" + text)
        return response.text
    
    def get_max_tokens(self):
        return 1_000_000  # Gemini 2.0 Flash

class OllamaProvider(LLMProvider):
    """Ollama 로컬 — 완전 무료"""
    def __init__(self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
    
    def generate_tei(self, text, schema_prompt):
        import requests
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": schema_prompt + "\n\n" + text, "stream": False}
        )
        return response.json()["response"]
    
    def get_max_tokens(self):
        return 32_000  # qwen3:8b 기본값

class ClaudeProvider(LLMProvider):
    """Anthropic Claude API — 종량제"""
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model
    
    def generate_tei(self, text, schema_prompt):
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=schema_prompt,
            messages=[{"role": "user", "content": text}]
        )
        return message.content[0].text
    
    def get_max_tokens(self):
        return 200_000  # Claude Sonnet 4.6
```

### 2.4 긴 텍스트 처리 전략 (청킹 솔루션, v2 개정)

비평텍스트의 길이가 LLM의 컨텍스트 윈도우를 초과할 경우를 대비한 청킹(Chunking) 전략. **v2에서는 대부분의 LLM이 100K+ 토큰을 지원하므로, 일반적인 비평문(~20,000자)은 청킹 없이 처리 가능하다.** 장편 비평이나 Ollama 로컬 모델 사용 시에만 청킹이 필요하다.

#### 2.4.1 청킹 방식 비교

| 방식 | 장점 | 단점 | 적합 상황 |
|------|------|------|-----------|
| **청킹 불요** | 문맥 완전 보존, 구현 불요 | 토큰 비용 높음 | 단문 비평 + Gemini/Claude |
| **시맨틱 청킹** | 의미 단위 보존 | 불균등 크기 | 비평/학술 텍스트 |
| **오버랩 청킹** | 연속성 유지 | 처리량 증가 | 긴 서사 텍스트 |
| **하이브리드** | 균형잡힌 접근 | 복잡한 구현 | 다양한 텍스트 |

#### 2.4.2 권장 전략: 적응형 청킹

```python
class AdaptiveChunker:
    """Provider의 컨텍스트 크기에 따라 자동으로 청킹 여부를 결정"""
    
    def __init__(self, provider: LLMProvider, overlap_sentences: int = 3):
        self.max_tokens = provider.get_max_tokens()
        self.overlap = overlap_sentences
        # 프롬프트 + 출력 여유분을 위해 입력은 최대 컨텍스트의 40%로 제한
        self.input_limit = int(self.max_tokens * 0.4)
    
    def needs_chunking(self, text: str) -> bool:
        """청킹 필요 여부 판단"""
        estimated_tokens = len(text) * 0.5  # 한국어: 글자당 ~0.5토큰 추정
        return estimated_tokens > self.input_limit
    
    def chunk_text(self, text: str) -> list[dict]:
        if not self.needs_chunking(text):
            return [{'text': text, 'index': 0, 'overlap_start': None}]
        
        # 시맨틱 오버랩 청킹
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for para in paragraphs:
            para_tokens = int(len(para) * 0.5)
            
            if current_tokens + para_tokens > self.input_limit:
                chunks.append({
                    'text': '\n\n'.join(current_chunk),
                    'index': len(chunks),
                    'overlap_start': self._get_overlap(current_chunk)
                })
                current_chunk = current_chunk[-self.overlap:]
                current_tokens = sum(int(len(p) * 0.5) for p in current_chunk)
            
            current_chunk.append(para)
            current_tokens += para_tokens
        
        if current_chunk:
            chunks.append({
                'text': '\n\n'.join(current_chunk),
                'index': len(chunks),
                'overlap_start': None
            })
        
        return chunks
    
    def _get_overlap(self, chunk_list):
        return '\n\n'.join(chunk_list[-self.overlap:]) if len(chunk_list) >= self.overlap else None
```

#### 2.4.3 사용자 설정 옵션

| 설정 항목 | 기본값 | 범위 | 설명 |
|-----------|--------|------|------|
| `auto_chunk` | true | boolean | 자동 청킹 여부 (Provider별 자동 판단) |
| `max_chunk_size` | Provider별 자동 | 2,000-100,000 | 청크당 최대 토큰 수 |
| `overlap_ratio` | 10% | 0-30% | 청크 간 오버랩 비율 |
| `split_unit` | paragraph | sentence/paragraph/section | 분할 기본 단위 |
| `preserve_quotes` | true | boolean | 인용문 분리 방지 |

### 2.5 LLM 프롬프트 설계 (v2 개정)

#### 2.5.1 시스템 프롬프트
```xml
<s>
당신은 한국 근현대 문학비평 전문 XML 인코더입니다.
제공된 XSD 스키마에 따라 비평텍스트를 TEI/XML로 변환합니다.

<규칙>
1. 인물명(persName): 비평가, 작가, 철학자 등 모든 인명에 태그
   - role 속성: critic, novelist, poet, playwright, essayist, translator, 
     childrenauthor, scholar, foreigner, other
   - role은 복수 지정 가능 (공백 구분): role="critic novelist"
2. 작품명(title): 소설, 시, 희곡, 비평문 등
   - level 속성: m(단행본), a(수록작), j(저널)
   - type 속성: novel, poem, play, critic, essay, translation, children, 
     contribution, foreign, journal, newspaper, coterie, publication, other
3. 기관명(orgName): 문학단체, 출판사, 학교, 잡지사
4. 용어(term): 문예사조, 철학개념, 비평용어
   - type 속성: movement, concept, 또는 구체적 분류
5. 인용문(quote): 직접인용, 간접인용, 작품인용 구분
   - type: direct, indirect, paraphrase, contribution, criticism, review, commentary
   - genre: critic, novel, poet, play, essay, translation, children, contribution, foreign, other
6. 해석/평가(interp): 비평적 판단이 드러나는 구절에 태그 (v2 추가)
   - value: affirmative(긍정), neutral(중립), critical(비판)
   - ana 속성 필수: 분석 기준 (예: "문체", "사상", "미학")
7. 날짜(date): 연도, 날짜 등 시간 표현 (v2 추가)
   - when 속성: 기계가독 형식 (예: when="1919", when="1919-02-01")
</규칙>

<출력형식>
- 반드시 유효한 XML 형식으로 출력
- 네임스페이스: xmlns="http://www.tei-c.org/ns/1.0"
- 각 개체에 고유 xml:id 부여 (예: p-leekwangsu, t-mujung)
- XML 선언으로 시작: <?xml version="1.0" encoding="UTF-8"?>
- 주석, 설명, 마크다운 서식 절대 포함 금지
</출력형식>
</s>
```

#### 2.5.2 태깅 예시 (Few-shot, v2 개정)
```xml
<example>
<input>
김동인은 1919년 창조를 창간하면서 자연주의 문학론을 주창하였다.
그는 "소설작법"에서 "예술은 일체의 목적의식에서 해방되어야 한다"고 주장했다.
이는 당시 이광수의 계몽주의적 문학관에 대한 직접적인 반박이었다.
</input>

<output>
<p>
  <s><persName xml:id="p-kimdongin" role="novelist critic">김동인</persName>은 
  <date when="1919">1919년</date> 
  <title xml:id="t-changjo" level="j" type="coterie">창조</title>를 창간하면서 
  <term type="movement">자연주의</term> 문학론을 주창하였다.</s>
  <s>그는 <title level="a" type="critic">소설작법</title>에서 
  <quote type="direct" source="소설작법">"예술은 일체의 목적의식에서 해방되어야 한다"</quote>고 
  주장했다.</s>
  <s>이는 당시 <persName xml:id="p-leekwangsu" role="novelist">이광수</persName>의 
  <term type="concept">계몽주의</term>적 문학관에 대한 
  <interp value="critical" ana="문학관">직접적인 반박</interp>이었다.</s>
</p>
</output>
</example>
```

---

## 3. 개체명 추출 및 CSV 변환

### 3.1 추출 대상 개체 유형

| 개체 유형 | XML 요소 | CSV 컬럼 |
|-----------|----------|----------|
| 인물 | `<persName>` | id, name, role, ref, context |
| 작품 | `<title>` | id, title, level, type, ref, context |
| 기관 | `<orgName>` | id, name, ref, context |
| 용어 | `<term>` | id, term, type, context |
| 인용문 | `<quote>` | id, text, type, genre, source |
| 해석 | `<interp>` | id, text, value, ana | ← v2 추가
| 날짜 | `<date>` | id, text, when | ← v2 추가

### 3.2 CSV 스키마

#### 3.2.1 persons.csv
```csv
id,name,role,ref,frequency,context
p-leekwangsu,이광수,"novelist,critic",https://viaf.org/123,15,"무정의 작가"
p-nietzsche,니체,foreigner,https://viaf.org/456,8,"차라투스트라 저자"
```

#### 3.2.2 works.csv
```csv
id,title,level,type,creator,ref,frequency,context
t-mujung,무정,m,novel,p-leekwangsu,,12,"한국 최초의 근대소설"
t-changjo,창조,j,coterie,,"https://ko.wikipedia.org/wiki/창조",5,"1919년 창간 동인지"
```

#### 3.2.3 concepts.csv
```csv
id,term,type,related_person,frequency,context
c-naturalism,자연주의,movement,p-zola,7,"19세기 프랑스 발원"
c-artforart,예술지상주의,concept,,4,"미적 자율성 강조"
```

#### 3.2.4 interpretations.csv (v2 추가)
```csv
id,text,value,ana,related_person,related_work,context
i-001,직접적인 반박,critical,문학관,p-kimdongin,,"김동인의 이광수 비판"
i-002,탁월한 서사적 성취,affirmative,문체,,t-mujung,"무정에 대한 평가"
```

### 3.3 XPath 추출 쿼리

```python
from lxml import etree

ns = {'tei': 'http://www.tei-c.org/ns/1.0'}

# persons 추출
for pn in tree.xpath('//tei:persName', namespaces=ns):
    person = {
        'id': pn.get('{http://www.w3.org/XML/1998/namespace}id', ''),
        'name': pn.text or '',
        'role': pn.get('role', ''),
        'ref': pn.get('ref', '')
    }

# interpretations 추출 (v2 추가)
for interp in tree.xpath('//tei:interp', namespaces=ns):
    interpretation = {
        'text': interp.text or '',
        'value': interp.get('value', ''),
        'ana': interp.get('ana', '')
    }
```

---

## 4. 웹 기반 시각화

### 4.1 시각화 유형

#### 4.1.1 네트워크 그래프
- **목적**: 인물-작품-개념 간 관계망 시각화
- **기술**: D3.js Force-Directed Graph 또는 Streamlit 내장 그래프
- **인터랙션**: 노드 클릭 시 상세정보, 필터링, 줌

#### 4.1.2 타임라인
- **목적**: 비평 담론의 시간적 전개
- **기술**: Plotly Timeline 또는 Vis.js
- **데이터**: 출판연도, 인물활동기, 사조유행기

#### 4.1.3 통계 대시보드
- **목적**: 개체별 빈도, 공기어(co-occurrence) 분석
- **기술**: Plotly, Streamlit Charts

#### 4.1.4 해석 태도 분포 (v2 추가)
- **목적**: 비평가별/시기별 긍정·중립·비판 태도 비율 시각화
- **기술**: Plotly Stacked Bar Chart

### 4.2 Streamlit 기반 통합 UI (v2 개정)

v1에서는 별도의 React/Vue.js 프론트엔드를 설계했으나, 배포 편의성과 개발 속도를 고려하여 Streamlit으로 통합한다.

```python
import streamlit as st

st.set_page_config(page_title="KorCritTEI", layout="wide")

# 사이드바: 설정
with st.sidebar:
    st.header("설정")
    provider = st.selectbox("LLM 선택", ["Gemini (무료)", "Ollama (로컬)", "Claude API"])
    api_key = st.text_input("API Key", type="password") if provider != "Ollama (로컬)" else None

# 메인: 탭 구성
tab1, tab2, tab3 = st.tabs(["XML 태깅", "데이터 테이블", "시각화"])

with tab1:
    text_input = st.text_area("비평텍스트 입력", height=300)
    uploaded = st.file_uploader("또는 파일 업로드", type=["txt", "docx"])
    if st.button("자동 태깅 실행"):
        # LLM 호출 → XML 생성
        result_xml = process_text(text_input, provider)
        st.code(result_xml, language="xml")
        st.download_button("XML 다운로드", result_xml, "output.xml")

with tab2:
    # CSV 데이터 테이블
    st.dataframe(persons_df)
    st.download_button("CSV 다운로드", csv_data, "entities.csv")

with tab3:
    # D3.js 네트워크 그래프 (Streamlit components)
    st.components.v1.html(network_html, height=600)
```

---

## 5. 기술 스택 및 도구 (v2 개정)

### 5.1 개발 환경
| 구성요소 | 기술 | 용도 |
|----------|------|------|
| 에이전트 코딩 | Claude Code (VS Code 확장) | 코드 생성, 리팩토링, 테스트 |
| 에디터 | VS Code + Copilot (Opus 4.6) | 세부 편집, 인라인 자동완성 |
| 버전관리 | Git + GitHub | 소스코드 관리, 협업 |

### 5.2 앱 백엔드
| 구성요소 | 기술 | 용도 |
|----------|------|------|
| UI + 서버 | Streamlit | 올인원 웹 앱 (프론트+백엔드) |
| LLM 연동 | 교체 가능 Provider 모듈 | TEI 자동 생성 |
| XML 처리 | lxml, xmlschema | 검증, 파싱, 변환 |
| 데이터 | pandas | CSV 생성, 데이터 조작 |

### 5.3 시각화
| 구성요소 | 기술 | 용도 |
|----------|------|------|
| 그래프 | Plotly, streamlit-agraph | 네트워크, 차트 |
| 테이블 | Streamlit DataFrames | 정렬, 필터, 검색 |
| 커스텀 | streamlit-components (D3.js) | 고급 인터랙티브 시각화 |

### 5.4 배포
| 환경 | 비용 | 적합 상황 |
|------|------|-----------|
| **Streamlit Cloud** | 무료 (퍼블릭 앱) | 소규모 공유·데모 — **기본 추천** |
| **HuggingFace Spaces** | 무료 (Streamlit 지원) | 학술 커뮤니티 공유 |
| GitHub Pages | 무료 | 정적 시각화 결과물만 배포 시 |
| 자체 서버 | 유지비 발생 | 대규모·프라이빗 사용 |

---

## 6. 개발 일정 (v2 개정)

Claude Code를 활용한 탄력적 일정. 각 단계의 산출물이 확보되면 다음 단계로 즉시 이동한다.

| 단계 | 산출물 | 비고 |
|------|--------|------|
| 1. 프롬프트 설계 및 Provider 모듈 | 프롬프트 템플릿, LLM 인터페이스 코드 | Claude Code로 빠르게 구현 |
| 2. 청킹 + 태깅 파이프라인 | Python 모듈 (전처리→LLM→후처리) | 적응형 청킹 포함 |
| 3. XML 검증 및 CSV 추출 | 검증 스크립트, XPath 추출기 | XSD 기반 lxml 검증 |
| 4. Streamlit 앱 통합 | 동작하는 웹 앱 | 태깅+테이블+다운로드 |
| 5. 시각화 구현 | 네트워크/타임라인/통계 | Plotly + D3.js |
| 6. 배포 및 문서화 | Streamlit Cloud 배포, README | 사용자 가이드 포함 |

---

## 7. 비용 구조 (v2 신규)

| 항목 | 개발 단계 | 배포 후 사용 |
|------|----------|-------------|
| Claude Code | Pro 구독 내 포함 (추가 비용 없음) | — (개발 전용) |
| Gemini API | 테스트용 무료 | **무료 티어 내 사용 (기본값)** |
| Ollama | 완전 무료 (로컬) | 완전 무료 (로컬 전용) |
| Claude API | — | 종량제 (고품질 필요 시) |
| Streamlit Cloud | — | **무료 (퍼블릭 앱)** |
| 도메인 | — | 선택 사항 |

**결론: Gemini 무료 티어 + Streamlit Cloud 조합으로 배포 시 추가 비용 0원.**

---

## 8. 향후 확장 가능성

1. **LOD 연동 (즉시 적용 가능)**: 국립중앙도서관 LOD 권위 데이터베이스와 Jaro-Winkler/RapidFuzz 매칭을 통한 persName ref 자동 부여 — 이미 검증된 파이프라인 보유
2. **다국어 지원**: 일본어, 중국어 비평텍스트 확장
3. **협업 기능**: 다중 사용자 어노테이션, 버전 관리
4. **모델 파인튜닝**: 한국문학 특화 NER 모델 학습
5. **VillainScope 연계**: 기존 캐릭터 분석 데이터셋과 인물 데이터 통합 가능성

---

*본 문서는 2026년 3월 기준 최신 기술 동향을 반영하여 개정되었습니다. v1(2026.02) 대비 개발 환경, LLM 백엔드, 배포 전략, 프롬프트 설계가 전면 업데이트되었습니다.*
