import os

from dotenv import load_dotenv
from google import genai

from .base import LLMProvider

load_dotenv()


class GeminiProvider(LLMProvider):
    """Google Gemini API — 배포 기본값 (무료 티어).

    .env에서 기본값을 읽는다:
        GEMINI_API_KEY=...
        GEMINI_MODEL=gemini-2.0-flash   (생략 시 기본값)
    생성자 인자로 직접 전달하면 .env보다 우선한다.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY가 설정되지 않았습니다. "
                ".env 파일 또는 생성자 인자(api_key=)로 전달하세요."
            )
        self._client = genai.Client(api_key=self.api_key)

    def generate_tei(self, text: str, schema_prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=schema_prompt + "\n\n" + text,
        )
        return response.text

    def get_max_tokens(self) -> int:
        return 1_000_000  # Gemini 2.0 Flash
