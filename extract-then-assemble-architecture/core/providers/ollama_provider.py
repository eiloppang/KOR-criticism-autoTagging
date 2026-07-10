import os

import requests
from dotenv import load_dotenv

from .base import LLMProvider

load_dotenv()


class OllamaProvider(LLMProvider):
    """Ollama 로컬 — 완전 무료 (오프라인 사용 가능).

    .env에서 기본값을 읽는다:
        OLLAMA_BASE_URL=http://localhost:11434   (생략 시 기본값)
        OLLAMA_MODEL=qwen3:8b                   (생략 시 기본값)
    생성자 인자로 직접 전달하면 .env보다 우선한다.
    """

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:8b")
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def generate_tei(self, text: str, schema_prompt: str) -> str:
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": schema_prompt + "\n\n" + text,
                "stream": False,
            },
            timeout=300,
        )
        response.raise_for_status()
        return response.json()["response"]

    def get_max_tokens(self) -> int:
        return 32_000  # qwen3:8b 기본값 (모델별 상이)
