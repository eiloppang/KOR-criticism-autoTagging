from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """
    LLM 백엔드 공통 인터페이스 (v2.3.2).

    구현체: GeminiProvider, OllamaProvider, ClaudeProvider
    교체 방법: 이 클래스를 상속하고 generate_tei / get_max_tokens를 구현한다.
    API 키와 모델명은 각 구현체에서 .env를 통해 기본값을 읽는다.
    """

    @abstractmethod
    def generate_tei(self, text: str, schema_prompt: str) -> str:
        """
        비평텍스트를 TEI/XML로 변환한다.

        Args:
            text: 원문 비평텍스트 (청크 단위)
            schema_prompt: XSD 스키마 기반 시스템 프롬프트

        Returns:
            TEI/XML 문자열
        """

    @abstractmethod
    def get_max_tokens(self) -> int:
        """
        해당 Provider의 최대 컨텍스트 크기(토큰)를 반환한다.
        AdaptiveChunker가 청킹 여부 판단에 사용한다.
        """
