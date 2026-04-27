import re

from .providers.base import LLMProvider


class AdaptiveChunker:
    """
    글자 수 기반 청킹.
    - chunk_size 글자 단위, 단락 경계 존중
    - \n\n 우선 분할 → 단락이 너무 크면 \n → 그래도 크면 문장 경계에서 강제 분할
    - 각 청크에 이전 청크의 마지막 overlap_paragraphs 단락을 context로 제공
    """

    def __init__(
        self,
        provider: LLMProvider,
        chunk_size: int = 5000,
        overlap_paragraphs: int = 3,
    ):
        self.chunk_size = chunk_size
        self.overlap_paragraphs = overlap_paragraphs

    def _split_into_units(self, text: str) -> list[str]:
        """
        텍스트를 의미 단위(단락/줄)로 분리하고,
        여전히 chunk_size를 초과하는 단위는 문장 경계에서 강제 분할한다.
        """
        # 1차: \n\n 기준
        units = [p.strip() for p in text.split("\n\n") if p.strip()]

        # \n\n이 없거나 전부 한 덩어리라면 \n 기준으로 재분리
        if len(units) <= 1 and units and len(units[0]) > self.chunk_size:
            units = [p.strip() for p in text.split("\n") if p.strip()]

        # 여전히 chunk_size 초과 단위는 문장 경계에서 강제 분할
        result = []
        for unit in units:
            if len(unit) <= self.chunk_size:
                result.append(unit)
            else:
                # 마침표·물음표·느낌표·줄바꿈 뒤에서 분리
                sentences = re.split(r"(?<=[.!?。\n])\s+", unit)
                buf = ""
                for sent in sentences:
                    if buf and len(buf) + len(sent) > self.chunk_size:
                        result.append(buf.strip())
                        buf = sent
                    else:
                        buf = (buf + " " + sent).strip() if buf else sent
                if buf:
                    result.append(buf.strip())

        return [u for u in result if u]

    def chunk_text(self, text: str) -> list[dict]:
        """
        Returns: list of {"text": ..., "index": ..., "context": ...}
          - text: 이 청크에서 실제 태깅할 텍스트
          - context: 이전 청크 마지막 N 단락 (첫 청크는 None, 참고용)
        """
        units = self._split_into_units(text)
        total_len = sum(len(u) for u in units)

        if total_len <= self.chunk_size:
            return [{"text": text.strip(), "index": 0, "context": None}]

        # 단위들을 chunk_size 이하로 묶기
        chunks_units: list[list[str]] = []
        current: list[str] = []
        current_len = 0

        for unit in units:
            if current and current_len + len(unit) > self.chunk_size:
                chunks_units.append(current)
                current = []
                current_len = 0
            current.append(unit)
            current_len += len(unit)

        if current:
            chunks_units.append(current)

        # context = 이전 청크의 마지막 N 단위
        result = []
        for i, units_grp in enumerate(chunks_units):
            context = None
            if i > 0:
                prev = chunks_units[i - 1]
                context = "\n\n".join(prev[-self.overlap_paragraphs:])
            result.append({
                "text": "\n\n".join(units_grp),
                "index": i,
                "context": context,
            })

        return result
