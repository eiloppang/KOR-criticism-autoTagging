from .base import LLMProvider


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API — 종량제"""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model

    def generate_tei(self, text: str, schema_prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        # 5,000자 청크를 빽빽하게 태깅하면 출력이 8K 토큰을 쉽게 넘겨 응답이
        # 중간에 잘리고(→ 깨진 XML → 병합 시 청크 드롭 → 분량 손실) 발생한다.
        # Sonnet 4.x는 64K 출력까지 지원하므로 넉넉히 16K로 둔다.
        message = client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=schema_prompt,
            messages=[{"role": "user", "content": text}],
        )
        return message.content[0].text

    def get_max_tokens(self) -> int:
        return 200_000  # Claude Sonnet 4.6
