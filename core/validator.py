"""
core/validator.py
XSD 스키마(korean-critique-schema.xsd) 기반 TEI XML 검증 모듈.

스키마 알려진 제약:
  - SentenceType(<s>)에 <date>가 정의되어 있지 않음.
    본문 내 날짜 태깅은 스키마 미포함이므로 검증 시 오류로 보고됨.
  - teiHeader: fileDesc + encodingDesc 모두 필수.
  - sourceDesc: biblStruct 또는 bibl 필요 (plain <p> 불가).
"""
from pathlib import Path

from lxml import etree


SCHEMA_PATH = Path(__file__).parent.parent / "korean-critique-schema.xsd"

# 스키마 객체 캐시 (모듈 로드 당 1회만 파싱)
_schema_cache: etree.XMLSchema | None = None


def _load_schema() -> tuple[etree.XMLSchema | None, str]:
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache, ""
    try:
        doc = etree.parse(str(SCHEMA_PATH))
        _schema_cache = etree.XMLSchema(doc)
        return _schema_cache, ""
    except Exception as e:
        return None, f"스키마 로딩 실패: {e}"


def parse_xml(xml_string: str) -> tuple[etree._Element | None, str]:
    """
    XML 문자열을 파싱한다.

    Returns:
        (root_element, "") 성공 시
        (None, error_message) 실패 시
    """
    try:
        root = etree.fromstring(xml_string.encode("utf-8"))
        return root, ""
    except etree.XMLSyntaxError as e:
        return None, f"XML 구문 오류: {e}"


def check_wellformed(xml_string: str) -> tuple[bool, list[str]]:
    """
    XSD 검증 없이 XML 형식(well-formedness)만 검사한다.

    Returns:
        (is_wellformed, errors)
    """
    _, err = parse_xml(xml_string)
    if err:
        return False, [err]
    return True, []


def validate_xml(xml_string: str) -> tuple[bool, list[str]]:
    """
    korean-critique-schema.xsd 기반으로 XML을 검증한다.

    검증 순서:
      1. XML 형식(well-formedness) 검사
      2. XSD 스키마 적합성 검사

    Returns:
        (is_valid, errors): 유효 여부와 오류 메시지 목록
        오류 메시지 형식: "[LEVEL] 줄 N: 메시지"

    Note:
        <date> 인라인 태깅은 현재 스키마 SentenceType에 미정의.
        검증 오류가 발생해도 추출/저장은 계속 진행 가능.
    """
    root, parse_err = parse_xml(xml_string)
    if root is None:
        return False, [parse_err]

    schema, schema_err = _load_schema()
    if schema is None:
        return False, [schema_err]

    is_valid = schema.validate(root)
    errors = [
        f"[{err.level_name}] 줄 {err.line}: {err.message}"
        for err in schema.error_log
    ]
    return is_valid, errors
