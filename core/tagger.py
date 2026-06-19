import re
from pathlib import Path

from .chunker import AdaptiveChunker
from .providers.base import LLMProvider
from .validator import validate_xml


ROOT_DIR = Path(__file__).parent.parent
PROMPTS_DIR = ROOT_DIR / "prompts"
SCHEMA_PATH = ROOT_DIR / "korean-critique-schema.xsd"

# ── TEI 후처리 상수 ───────────────────────────────────────────────

_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_TEI_NS_URI = "http://www.tei-c.org/ns/1.0"

# 코드에서 고정 삽입하는 taxonomy — LLM이 생성하지 않도록 프롬프트에서 배제
_FIXED_CLASSDECL = """\
<classDecl xmlns="http://www.tei-c.org/ns/1.0">
  <taxonomy xml:id="tax-role">
    <desc>인물 역할 분류</desc>
    <category xml:id="critic"><catDesc>비평가</catDesc></category>
    <category xml:id="poet"><catDesc>시인</catDesc></category>
    <category xml:id="novelist"><catDesc>소설가</catDesc></category>
    <category xml:id="essayist"><catDesc>수필가</catDesc></category>
    <category xml:id="playwright"><catDesc>극작가</catDesc></category>
    <category xml:id="translator"><catDesc>번역가</catDesc></category>
    <category xml:id="childrenauthor"><catDesc>아동문학 작가</catDesc></category>
    <category xml:id="scholar"><catDesc>학자</catDesc></category>
    <category xml:id="foreigner"><catDesc>외국 문인</catDesc></category>
    <category xml:id="other"><catDesc>기타</catDesc></category>
  </taxonomy>
  <taxonomy xml:id="tax-interp">
    <desc>해석/평가 분류</desc>
    <category xml:id="affirmative"><catDesc>긍정적 평가</catDesc></category>
    <category xml:id="neutral"><catDesc>중립적 서술</catDesc></category>
    <category xml:id="critical"><catDesc>비판적 평가</catDesc></category>
  </taxonomy>
</classDecl>"""


# ── 프롬프트 조립 ─────────────────────────────────────────────────

def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _system_rules(include_builtin_example: bool = True) -> str:
    """
    시스템 규칙 텍스트를 로드한다.
    include_builtin_example=False면 프롬프트에 내장된 <few-shot-example> 블록을
    제거한다 (zero-shot / 스키마-only 모드용).
    """
    txt = _load_text(PROMPTS_DIR / "tei_system_prompt.txt")
    if not include_builtin_example:
        txt = re.sub(
            r"\n*<few-shot-example>.*?</few-shot-example>\s*",
            "\n",
            txt,
            flags=re.DOTALL,
        )
    return txt


def build_prompt(
    dict_context: str = "",
    few_shot: str = "",
    include_builtin_example: bool = True,
) -> str:
    """
    첫 번째 청크용 프롬프트:
    시스템 규칙 + XSD 스키마 → 완전한 TEI 문서(teiHeader 포함) 생성.

    Parameters
    ----------
    dict_context            : '[사전 매칭 참고자료]' 블록 (2단계 파이프라인)
    few_shot                : 수작업 정답 예시 블록 (4단계 few-shot ICL)
    include_builtin_example : False면 내장 예시 제거 (1단계 zero-shot)
    """
    system_rules = _system_rules(include_builtin_example)
    xsd_schema = _load_text(SCHEMA_PATH)
    dict_block = ("\n\n" + dict_context) if dict_context else ""
    few_shot_block = ("\n\n" + few_shot) if few_shot else ""
    return (
        system_rules
        + dict_block
        + few_shot_block
        + "\n\n<XSD_스키마>\n"
        + xsd_schema
        + "\n</XSD_스키마>\n"
        + "\n위 XSD 스키마를 엄격히 준수하여 입력 텍스트를 TEI/XML로 변환하라."
    )


def build_continuation_prompt(
    dict_context: str = "",
    few_shot: str = "",
    include_builtin_example: bool = True,
) -> str:
    """
    2번째 이후 청크용 프롬프트:
    teiHeader 없이 text > body > div 구조만 출력.
    """
    system_rules = _system_rules(include_builtin_example)
    xsd_schema = _load_text(SCHEMA_PATH)
    dict_block = ("\n\n" + dict_context) if dict_context else ""
    few_shot_block = ("\n\n" + few_shot) if few_shot else ""
    continuation_note = """

[후속 청크 출력 규칙]
이 텍스트는 긴 비평문의 후속 부분입니다. teiHeader는 이미 생성되었습니다.
- teiHeader를 출력하지 마라.
- 출력 구조는 다음을 정확히 따르라:
  <?xml version="1.0" encoding="UTF-8"?>
  <TEI xmlns="http://www.tei-c.org/ns/1.0">
    <text>
      <body>
        <div type="body">
          ...
        </div>
      </body>
    </text>
  </TEI>
- titleStmt, publicationStmt, sourceDesc, teiHeader 등을 절대 출력하지 마라.
- 태깅 규칙(persName, title, orgName, term, quote, interp, date)은 동일하게 적용한다.
"""
    return (
        system_rules
        + dict_block
        + few_shot_block
        + continuation_note
        + "\n\n<XSD_스키마>\n"
        + xsd_schema
        + "\n</XSD_스키마>\n"
        + "\n위 XSD 스키마를 엄격히 준수하여 입력 텍스트를 TEI/XML로 변환하라."
    )


# ── LLM 응답 후처리 ───────────────────────────────────────────────

def _strip_markdown_fences(text: str) -> str:
    """LLM이 출력한 마크다운 코드블록(```xml ... ```)을 제거한다."""
    text = re.sub(r"^```(?:xml)?\s*\n", "", text.strip())
    text = re.sub(r"\n```\s*$", "", text.strip())
    return text.strip()


def _extract_xml(text: str) -> str:
    """응답에서 XML 선언 이후의 순수 XML만 추출한다."""
    text = _strip_markdown_fences(text)
    # XML 선언 또는 <TEI 태그부터 시작
    match = re.search(r"(<\?xml[^>]*\?>|<TEI[\s>])", text)
    if match:
        return text[match.start():].strip()
    return text.strip()


# ── TEI 후처리 ────────────────────────────────────────────────────

def _dedup_xml_ids(tei_el) -> None:
    """
    persName / title / orgName 중 텍스트 내용이 같은 요소의 xml:id를
    첫 번째 등장한 id로 통일한다.

    중복 패턴: LLM이 청크마다 같은 인물을 p-kim, p-kim2, p-kim3 처럼
    숫자 접미사를 붙여 생성하는 경우를 포함한다.
    - 숫자 없는 id를 canonical로 우선 선택
    - 숫자 없는 id가 없으면 문서 순서상 첫 번째 id를 canonical로 사용
    """
    from collections import defaultdict

    NS = _TEI_NS_URI
    TAGS = [f"{{{NS}}}persName", f"{{{NS}}}title", f"{{{NS}}}orgName"]

    # Pass 1: (localname, 정규화_텍스트) → 등장한 xml:id 목록 (문서 순)
    text_to_ids: dict = defaultdict(list)
    for tag in TAGS:
        local = tag.split("}")[-1]
        for el in tei_el.iter(tag):
            xml_id = el.get(_XML_ID)
            if not xml_id:
                continue
            norm = "".join(el.itertext()).strip()
            key = (local, norm)
            if xml_id not in text_to_ids[key]:
                text_to_ids[key].append(xml_id)

    # canonical 결정: 숫자 미접미사 id 우선, 없으면 첫 번째
    text_to_canonical: dict = {}
    for key, ids in text_to_ids.items():
        clean = [i for i in ids if not re.search(r"\d+$", i)]
        text_to_canonical[key] = clean[0] if clean else ids[0]

    # Pass 2: 모든 대상 요소에 canonical id 적용
    for tag in TAGS:
        local = tag.split("}")[-1]
        for el in tei_el.iter(tag):
            norm = "".join(el.itertext()).strip()
            key = (local, norm)
            canonical = text_to_canonical.get(key)
            if canonical:
                el.set(_XML_ID, canonical)


def _extract_header_meta(header_el, NS: str) -> tuple[str, str]:
    """
    기존 teiHeader 요소에서 title, author 텍스트를 추출한다.
    요소가 없거나 값을 찾지 못하면 빈 문자열을 반환한다.
    """
    title, author = "", ""
    if header_el is None:
        return title, author
    title_el = header_el.find(f".//{{{NS}}}titleStmt/{{{NS}}}title")
    if title_el is not None:
        title = "".join(title_el.itertext()).strip()
    author_el = header_el.find(f".//{{{NS}}}titleStmt/{{{NS}}}author")
    if author_el is not None:
        author = "".join(author_el.itertext()).strip()
    return title, author


def _build_tei_header(title: str, author: str):
    """
    fileDesc + encodingDesc(고정 classDecl) 구조의 완전한 teiHeader를 생성한다.

    - titleStmt: LLM 첫 청크에서 추출한 title / author (없으면 '미상')
    - publicationStmt / sourceDesc: 고정 텍스트
    - encodingDesc > classDecl: tax-role / tax-interp 고정 taxonomy
    """
    from lxml import etree

    NS = _TEI_NS_URI
    header = etree.Element(f"{{{NS}}}teiHeader")

    # fileDesc
    file_desc = etree.SubElement(header, f"{{{NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{NS}}}title").text = title or "미상"
    etree.SubElement(title_stmt, f"{{{NS}}}author").text = author or "미상"
    pub = etree.SubElement(file_desc, f"{{{NS}}}publicationStmt")
    etree.SubElement(pub, f"{{{NS}}}p").text = "디지털 인문학 연구 목적"
    src = etree.SubElement(file_desc, f"{{{NS}}}sourceDesc")
    etree.SubElement(src, f"{{{NS}}}p").text = "입력 텍스트"

    # encodingDesc — 고정 classDecl
    enc = etree.SubElement(header, f"{{{NS}}}encodingDesc")
    enc.append(etree.fromstring(_FIXED_CLASSDECL.encode("utf-8")))

    return header


def _finalize_tei(xml_str: str) -> str:
    """
    단일 또는 병합된 TEI XML 문자열에 공통 후처리를 적용한다.

    1. 기존 teiHeader에서 title/author 추출 후 teiHeader 제거
    2. 고정 구조의 teiHeader 재구성하여 TEI 루트 첫 번째 자식으로 삽입
       (fileDesc + encodingDesc + 고정 classDecl — teiHeader 누락 시도 보장)
    3. xml:id 중복 통일
    4. 기본 네임스페이스 확보 (ns0: 접두사 방지)

    XML 파싱에 실패하면 원본 문자열을 그대로 반환한다.
    """
    from lxml import etree

    NS = _TEI_NS_URI
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
    except etree.XMLSyntaxError:
        return xml_str

    # 기존 teiHeader에서 메타 추출 후 제거 (LLM 생성 내용은 사용하지 않음)
    existing_header = root.find(f"{{{NS}}}teiHeader")
    title, author = _extract_header_meta(existing_header, NS)
    if existing_header is not None:
        root.remove(existing_header)

    # 고정 teiHeader를 TEI 루트의 첫 번째 자식으로 삽입
    root.insert(0, _build_tei_header(title, author))

    # xml:id 중복 통일
    _dedup_xml_ids(root)

    # 기본 네임스페이스가 없으면 루트 재구성 (ns0: 접두사 방지)
    if root.nsmap.get(None) != NS:
        new_root = etree.Element(root.tag, attrib=dict(root.attrib), nsmap={None: NS})
        for child in list(root):
            new_root.append(child)
        root = new_root

    etree.cleanup_namespaces(root)
    return etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    ).decode("utf-8")


# ── 청크 병합 ─────────────────────────────────────────────────────

def _merge_body_divs(chunk_xmls: list[str]) -> str:
    """
    청크별 TEI XML에서 body/div 내용을 추출하여
    하나의 완전한 TEI 문서로 병합한다.
    헤더는 첫 번째 청크의 것을 사용한다.
    """
    from lxml import etree

    NS = "http://www.tei-c.org/ns/1.0"
    merged_divs: list = []
    header_el = None
    parse_errors: list[str] = []

    for i, xml_str in enumerate(chunk_xmls):
        try:
            root = etree.fromstring(xml_str.encode("utf-8"))
        except etree.XMLSyntaxError as e:
            parse_errors.append(f"청크 {i} 파싱 실패: {e}")
            continue

        if header_el is None:
            header_el = root.find(f"{{{NS}}}teiHeader")

        body = root.find(f".//{{{NS}}}body")
        if body is not None:
            for div in body:
                merged_divs.append(div)

    # 새 TEI 문서 조립 — nsmap={None: NS}로 기본 네임스페이스 지정해 ns0: 접두사 제거
    tei = etree.Element(f"{{{NS}}}TEI", nsmap={None: NS})
    if header_el is not None:
        tei.append(header_el)
    text_el = etree.SubElement(tei, f"{{{NS}}}text")
    body_el = etree.SubElement(text_el, f"{{{NS}}}body")
    for div in merged_divs:
        body_el.append(div)

    xml_bytes = etree.tostring(tei, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return xml_bytes.decode("utf-8")


# ── XML 유효성 판정 ───────────────────────────────────────────────

def _is_xml_response(text: str) -> bool:
    """응답이 XML 형식으로 시작하는지 빠르게 판단한다."""
    stripped = text.strip()
    return stripped.startswith("<?xml") or stripped.startswith("<TEI")


_RETRY_PROMPT = """
이전 응답이 TEI/XML 형식이 아닙니다. 반드시 다음 규칙을 지켜 다시 출력하십시오.

[필수]
- 출력의 첫 줄: <?xml version="1.0" encoding="UTF-8"?>
- 출력의 둘째 줄: <TEI xmlns="http://www.tei-c.org/ns/1.0">
- 마지막 줄: </TEI>
- 입력 텍스트의 모든 문장을 생략 없이 포함해야 한다.
- 요약·설명·주석을 출력하지 마라. XML만 출력하라.

입력 텍스트:
"""


# ── 공개 API ──────────────────────────────────────────────────────

MAX_RETRIES = 2


def _call_with_retry(
    chunk_text: str,
    full_prompt: str,
    provider: LLMProvider,
    warnings: list[str],
    chunk_idx: int,
    context: str | None = None,
) -> str:
    """
    청크 하나에 대해 LLM을 호출하고, 응답이 XML이 아니면 재시도한다.
    context가 있으면 사용자 메시지 앞에 참고용 앞 단락을 첨부한다.
    MAX_RETRIES 초과 시 마지막 응답을 그대로 반환한다.
    """
    if context:
        user_text = (
            "[앞 단락 — 참고만 하고 태깅하지 말 것]\n"
            + context
            + "\n\n[아래 텍스트만 태깅하라]\n"
            + chunk_text
        )
    else:
        user_text = chunk_text

    raw = provider.generate_tei(user_text, full_prompt)
    result = _extract_xml(raw)

    for attempt in range(1, MAX_RETRIES + 1):
        if _is_xml_response(result):
            break
        label = f"청크 {chunk_idx}" if chunk_idx > 0 else ""
        warnings.append(
            f"{label} 응답이 XML이 아님 — 재시도 {attempt}/{MAX_RETRIES}"
        )
        retry_prompt = full_prompt + _RETRY_PROMPT + chunk_text
        raw = provider.generate_tei(user_text, retry_prompt)
        result = _extract_xml(raw)

    if not _is_xml_response(result):
        label = f"청크 {chunk_idx}" if chunk_idx > 0 else ""
        warnings.append(
            f"{label} {MAX_RETRIES}회 재시도 후에도 XML 응답 없음. "
            "응답을 그대로 사용합니다."
        )

    return result


def tag_text(
    text: str,
    provider: LLMProvider,
    chunk_size: int = 5000,
    progress_callback=None,
    dict_context: str = "",
    few_shot: str = "",
    include_builtin_example: bool = True,
) -> tuple[str, list[str]]:
    """
    비평텍스트를 TEI/XML로 변환하는 메인 파이프라인.

    1. 프롬프트 조립 (시스템 규칙 + [사전 매칭 참고자료] + XSD 스키마)
    2. 글자 수 기반 청킹 (기본 5000자, 단락 경계 존중)
    3. 첫 번째 청크: 완전한 TEI 문서(teiHeader 포함)
       2번째+ 청크: teiHeader 없이 text > body > div 만 출력
    4. 컨텍스트 주입: 이전 청크 마지막 단락을 참고용으로 첨부
    5. XML이 아니면 최대 MAX_RETRIES회 재시도
    6. 청크 병합 (teiHeader는 첫 청크 것 사용, div 순서대로 추가)
    7. XSD 검증

    Parameters
    ----------
    dict_context : DictionaryMatcher.format_for_prompt() 결과 문자열.
                   비어 있으면 사전 참고자료 없이 동작 (기존 동작).

    Returns:
        (xml_output, warnings): 생성된 XML 문자열과 경고/오류 목록
    """
    first_prompt = build_prompt(dict_context, few_shot, include_builtin_example)
    cont_prompt = build_continuation_prompt(dict_context, few_shot, include_builtin_example)
    chunker = AdaptiveChunker(provider, chunk_size=chunk_size)
    chunks = chunker.chunk_text(text)
    warnings: list[str] = []

    total = len(chunks)
    raw_results: list[str] = []
    for i, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(i, total, len(chunk["text"]))
        prompt = first_prompt if i == 0 else cont_prompt
        result = _call_with_retry(
            chunk["text"],
            prompt,
            provider,
            warnings,
            chunk_idx=i if total > 1 else 0,
            context=chunk.get("context"),
        )
        raw_results.append(result)

    if len(raw_results) == 1:
        xml_output = raw_results[0]
    else:
        warnings.append(f"텍스트가 {len(chunks)}개 청크로 분할 처리되었습니다.")
        try:
            xml_output = _merge_body_divs(raw_results)
        except Exception as e:
            warnings.append(f"청크 병합 중 오류 (원시 연결로 대체): {e}")
            xml_output = "\n".join(raw_results)

    # 공통 후처리: xml:id 중복 통일 + taxonomy 고정 삽입
    xml_output = _finalize_tei(xml_output)

    is_valid, validation_errors = validate_xml(xml_output)
    if not is_valid:
        warnings.extend(validation_errors)

    return xml_output, warnings
