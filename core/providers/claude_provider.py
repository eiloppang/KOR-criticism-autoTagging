from .base import LLMProvider


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API — 종량제"""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model

    def generate_tei(self, text: str, schema_prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=schema_prompt,
            messages=[{"role": "user", "content": text}],
        )
        return message.content[0].text

    def get_max_tokens(self) -> int:
        return 200_000  # Claude Sonnet 4.6
