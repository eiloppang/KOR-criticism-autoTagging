"""
dictionary_matcher.py
─────────────────────
한국문학비평 TEI 자동 태거용 사전 매칭 모듈.

CSV 사전 3종(국어국문학자료사전, 문학비평용어사전, 한국현대문학대사전)을 로드하고,
입력 비평텍스트에서 headword / aliases를 매칭하여 LLM 프롬프트에 삽입할
'[사전 매칭 참고자료]' 블록을 생성한다.

의존: pandas, rapidfuzz (pip install rapidfuzz pandas)
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import IO

import pandas as pd

try:
    from rapidfuzz import fuzz, process as rf_process
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False


# ── 상수 ──────────────────────────────────────────────────────────────

DICT_FILENAMES = [
    "국어국문학자료사전.csv",
    "문학비평용어사전.csv",
    "한국현대문학대사전.csv",
]

# 사람으로 판단하는 컬럼 — 하나라도 값이 있으면 인물 엔트리
_PERSON_COLS = {"gender", "birth_year", "death_year"}

# 프롬프트에 포함할 definition 최대 글자 수
_DEF_MAX = 200

# 매칭 결과 최대 항목 수 (프롬프트 과부하 방지)
_MATCH_LIMIT = 30


# ── 내부 유틸 ─────────────────────────────────────────────────────────

def _is_person(row: dict) -> bool:
    """birth_year, death_year, gender 중 하나라도 채워져 있으면 인물."""
    return any(str(row.get(c, "")).strip() for c in _PERSON_COLS)


def _parse_aliases(raw: str | float) -> list[str]:
    """aliases 컬럼 값을 리스트로 분리. 세미콜론 또는 쉼표 구분."""
    if not raw or (isinstance(raw, float)):
        return []
    return [a.strip() for a in re.split(r"[;,]", str(raw)) if a.strip()]


def _short_def(raw: str | float) -> str:
    """definition을 _DEF_MAX 글자로 잘라 반환."""
    if not raw or isinstance(raw, float):
        return ""
    text = str(raw).strip().replace("\n", " ")
    return text[:_DEF_MAX] + ("…" if len(text) > _DEF_MAX else "")


def _load_csv(source: str | Path | IO[bytes]) -> pd.DataFrame:
    """
    단일 CSV 파일을 DataFrame으로 읽는다.
    BOM(utf-8-sig) 처리 포함. 파일 경로 또는 BytesIO 모두 허용.
    """
    if isinstance(source, (str, Path)):
        return pd.read_csv(source, encoding="utf-8-sig", dtype=str, low_memory=False)
    # Streamlit UploadedFile / BytesIO
    raw = source.read()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 인코딩을 인식할 수 없습니다 (UTF-8 / CP949 권장).")


# ── 공개 클래스 ───────────────────────────────────────────────────────

class DictionaryMatcher:
    """
    사전 CSV를 로드하고 비평텍스트에서 엔티티를 매칭하는 클래스.

    사용 예::
        matcher = DictionaryMatcher()
        matcher.load_from_dir("dict/")          # 또는 load_from_uploaded(files)
        matches = matcher.match(text, fuzzy_threshold=85)
        prompt_block = matcher.format_for_prompt(matches)
    """

    def __init__(self) -> None:
        # 각 항목: {"headword", "aliases": [...], "source", "is_person", ...메타}
        self._entries: list[dict] = []
        # 검색 키 → entry 인덱스 (headword + 각 alias 포함)
        self._key_to_idx: dict[str, int] = {}
        # 검색 키 목록 (rapidfuzz process용)
        self._all_keys: list[str] = []

    # ── 로딩 ──────────────────────────────────────────────────────────

    def load_from_dir(self, dict_dir: str | Path) -> int:
        """
        dict_dir 아래 DICT_FILENAMES 파일들을 자동 로드.
        존재하지 않는 파일은 건너뜀.
        반환: 로드된 엔트리 총 수
        """
        dict_dir = Path(dict_dir)
        loaded = 0
        for fname in DICT_FILENAMES:
            fp = dict_dir / fname
            if fp.exists():
                source_name = fp.stem
                df = _load_csv(fp)
                loaded += self._ingest_dataframe(df, source_name)
        self._rebuild_index()
        return loaded

    def load_from_uploaded(self, uploaded_files: list) -> int:
        """
        Streamlit UploadedFile 리스트를 수신해 로드.
        반환: 로드된 엔트리 총 수
        """
        loaded = 0
        for uf in uploaded_files:
            source_name = Path(uf.name).stem
            df = _load_csv(uf)
            loaded += self._ingest_dataframe(df, source_name)
        self._rebuild_index()
        return loaded

    def clear(self) -> None:
        self._entries.clear()
        self._key_to_idx.clear()
        self._all_keys.clear()

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # ── 매칭 ──────────────────────────────────────────────────────────

    def match(
        self,
        text: str,
        fuzzy_threshold: int = 85,
        use_fuzzy: bool = True,
    ) -> list[dict]:
        """
        text에서 사전 headword / alias와 매칭되는 엔티티를 반환.

        Parameters
        ----------
        text : 비평텍스트 전문
        fuzzy_threshold : RapidFuzz 유사도 컷오프 (0~100). 기본 85.
        use_fuzzy : False면 완전 일치(substring) 매칭만 수행.

        Returns
        -------
        list[dict] — 발견된 엔트리 목록 (중복 제거, 매칭 점수 포함)
        """
        if not self._entries:
            return []

        found_idx: dict[int, float] = {}  # entry_idx → best score

        # 1) 완전 일치 (부분 문자열 검색)
        for key, idx in self._key_to_idx.items():
            if key in text:
                found_idx[idx] = max(found_idx.get(idx, 0), 100.0)

        # 2) 퍼지 매칭 (rapidfuzz 있을 때만)
        if use_fuzzy and _HAS_RAPIDFUZZ:
            tokens = _tokenize_korean(text)
            for token in tokens:
                if len(token) < 2:
                    continue
                results = rf_process.extractOne(
                    token,
                    self._all_keys,
                    scorer=fuzz.ratio,
                    score_cutoff=fuzzy_threshold,
                )
                if results:
                    matched_key, score, _ = results
                    idx = self._key_to_idx[matched_key]
                    found_idx[idx] = max(found_idx.get(idx, 0), score)

        # 엔트리 조립 (점수 내림차순 정렬)
        results = []
        for idx, score in sorted(found_idx.items(), key=lambda x: -x[1]):
            entry = dict(self._entries[idx])
            entry["_score"] = score
            results.append(entry)

        return results[:_MATCH_LIMIT]

    # ── 프롬프트 포맷 ─────────────────────────────────────────────────

    def format_for_prompt(self, matches: list[dict]) -> str:
        """
        match() 결과를 LLM 프롬프트에 삽입할 텍스트 블록으로 변환.

        인물: birth_year, era, field 포함
        용어: definition 포함
        """
        if not matches:
            return ""

        persons = [m for m in matches if m["is_person"]]
        terms = [m for m in matches if not m["is_person"]]

        lines: list[str] = ["[사전 매칭 참고자료]"]
        lines.append(
            "아래는 비평텍스트에서 발견된 인물 및 용어의 사전 정보입니다. "
            "태깅 시 ref 속성, 개체 유형 판별, 설명 정확도 향상에 활용하세요."
        )

        if persons:
            lines.append("\n## 인물")
            for m in persons:
                hw = m["headword"]
                aliases = ", ".join(m["aliases"]) if m["aliases"] else ""
                birth = m.get("birth_year", "")
                death = m.get("death_year", "")
                era = m.get("era", "")
                field = m.get("field", "")
                url = m.get("url", "")

                parts = [f"**{hw}**"]
                if aliases:
                    parts.append(f"(별칭: {aliases})")
                life = ""
                if birth or death:
                    life = f"{birth or '?'}~{death or '?'}"
                    parts.append(life)
                if era:
                    parts.append(f"시대: {era}")
                if field:
                    parts.append(f"분야: {field}")
                if url:
                    parts.append(f"ref: {url}")
                lines.append("- " + " | ".join(parts))

        if terms:
            lines.append("\n## 용어·개념")
            for m in terms:
                hw = m["headword"]
                aliases = ", ".join(m["aliases"]) if m["aliases"] else ""
                definition = _short_def(m.get("definition", ""))
                url = m.get("url", "")

                parts = [f"**{hw}**"]
                if aliases:
                    parts.append(f"(별칭: {aliases})")
                if definition:
                    parts.append(definition)
                if url:
                    parts.append(f"ref: {url}")
                lines.append("- " + " | ".join(parts))

        return "\n".join(lines)

    # ── 내부 메서드 ───────────────────────────────────────────────────

    def _ingest_dataframe(self, df: pd.DataFrame, source: str) -> int:
        """DataFrame 한 개를 _entries에 추가. 추가된 수를 반환."""
        added = 0
        for _, row in df.iterrows():
            headword = str(row.get("headword", "")).strip()
            if not headword or headword.lower() == "nan":
                continue
            r = row.to_dict()
            entry = {
                "headword": headword,
                "aliases": _parse_aliases(r.get("aliases")),
                "is_person": _is_person(r),
                "source": source,
                "gender": str(r.get("gender", "")).strip(),
                "birth_year": str(r.get("birth_year", "")).strip(),
                "death_year": str(r.get("death_year", "")).strip(),
                "birthplace": str(r.get("birthplace", "")).strip(),
                "era": str(r.get("era", "")).strip(),
                "field": str(r.get("field", "")).strip(),
                "definition": r.get("definition", ""),
                "related_orgs": str(r.get("related_orgs", "")).strip(),
                "related_persons": str(r.get("related_persons", "")).strip(),
                "url": str(r.get("url", "")).strip(),
            }
            # "nan" 문자열 정리
            for k in ("gender", "birth_year", "death_year", "birthplace", "era", "field",
                      "related_orgs", "related_persons", "url"):
                if entry[k].lower() == "nan":
                    entry[k] = ""
            self._entries.append(entry)
            added += 1
        return added

    def _rebuild_index(self) -> None:
        """headword + aliases 전부를 키로 인덱스 재구축."""
        self._key_to_idx.clear()
        self._all_keys.clear()
        for idx, entry in enumerate(self._entries):
            keys = [entry["headword"]] + entry["aliases"]
            for key in keys:
                if key and key not in self._key_to_idx:
                    self._key_to_idx[key] = idx
                    self._all_keys.append(key)


# ── 한국어 토크나이저 (경량) ──────────────────────────────────────────

def _tokenize_korean(text: str) -> list[str]:
    """
    공백 및 구두점으로 분리한 토큰 목록 반환.
    퍼지 매칭에 사용하며, 2글자 미만 토큰은 match()에서 걸러진다.
    """
    tokens = re.split(r"[\s\u3000.,!?·;:\"'「」『』【】《》〈〉()\[\]{}\-–—/\\|]+", text)
    return [t for t in tokens if t]


# ── 편의 함수 ─────────────────────────────────────────────────────────

def load_default_matcher(dict_dir: str | Path | None = None) -> DictionaryMatcher:
    """
    프로젝트 루트의 dict/ 폴더를 자동 탐지하여 DictionaryMatcher를 반환.
    dict_dir을 명시하면 해당 경로를 사용.
    """
    if dict_dir is None:
        dict_dir = Path(__file__).parent.parent / "dict"
    m = DictionaryMatcher()
    m.load_from_dir(dict_dir)
    return m
