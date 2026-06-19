import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="KorCritTEI",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── 사이드바 ──────────────────────────────────────────────────────

def _build_provider():
    """사이드바 UI를 그리고 설정된 LLM Provider 객체를 반환. 설정 미완료 시 None."""
    from core.providers import GeminiProvider, OllamaProvider, ClaudeProvider

    with st.sidebar:
        st.title("KorCritTEI")
        st.caption("한국문학비평 TEI 자동 태거")
        st.divider()
        st.subheader("LLM 설정")

        provider_name = st.radio(
            "Provider",
            ["Gemini API", "Claude API", "Ollama (로컬)"],
            help="Gemini: 무료 티어 이용 가능 / Claude: Anthropic API / Ollama: 로컬 GPU 필요",
        )

        provider = None

        # ── Gemini ──────────────────────────────────────────────
        if provider_name == "Gemini API":
            api_key = st.text_input(
                "API Key",
                value=os.getenv("GEMINI_API_KEY", ""),
                type="password",
                placeholder="AIza...",
            )
            model = st.selectbox(
                "모델",
                ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
                help="gemini-2.0-flash: 빠르고 무료 티어 적합",
            )
            if api_key:
                try:
                    provider = GeminiProvider(api_key=api_key, model=model)
                    st.success(f"준비 완료 — `{model}`")
                except Exception as e:
                    st.error(f"초기화 오류: {e}")
            else:
                st.warning(".env 또는 위 입력란에 API Key를 입력하세요.")

        # ── Claude ──────────────────────────────────────────────
        elif provider_name == "Claude API":
            api_key = st.text_input(
                "API Key",
                value=os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY", ""),
                type="password",
                placeholder="sk-ant-...",
            )
            model = st.selectbox(
                "모델",
                ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
                index=0,
                help="claude-sonnet-4-6: 기본 권장",
            )
            if api_key:
                try:
                    provider = ClaudeProvider(api_key=api_key, model=model)
                    st.success(f"준비 완료 — `{model}`")
                except Exception as e:
                    st.error(f"초기화 오류: {e}")
            else:
                st.warning(".env(ANTHROPIC_API_KEY) 또는 위 입력란에 API Key를 입력하세요.")

        # ── Ollama ──────────────────────────────────────────────
        else:
            base_url = st.text_input(
                "서버 URL",
                value=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            )
            model = st.selectbox(
                "모델",
                ["qwen3:8b", "qwen3.5:9b", "exaone3.5:7.8b"],
                index=0,
                help="설치된 모델만 사용 가능",
            )

            if st.button("연결 확인", use_container_width=True):
                _ping_ollama(base_url)

            provider = OllamaProvider(model=model, base_url=base_url)
            st.info(f"모델: `{model}`")

        st.divider()
        chunk_size = st.slider(
            "청크 크기 (글자 수)",
            min_value=2000,
            max_value=10000,
            value=5000,
            step=500,
            help="긴 텍스트를 이 크기로 분할하여 순차 처리합니다.",
        )

        st.divider()
        st.subheader("사전 매칭")
        dict_matcher = _build_dict_matcher()

        st.caption("스키마: `korean-critique-schema.xsd`")

    return provider, chunk_size, dict_matcher


def _build_dict_matcher():
    """
    사이드바 사전 매칭 섹션을 그리고 DictionaryMatcher를 반환.
    dict/ 폴더의 기본 사전을 자동 로드하고, 사용자가 추가 CSV를 업로드할 수 있다.
    """
    from core.dictionary_matcher import DictionaryMatcher, load_default_matcher

    # 세션에 캐시 — 파일 목록이 바뀔 때만 재로드
    cache_key = "dict_matcher"

    use_dict = st.checkbox(
        "사전 매칭 사용",
        value=True,
        help="비평텍스트에서 인물·용어를 사전과 매칭하여 LLM 프롬프트에 참고자료로 추가합니다.",
    )

    if not use_dict:
        st.session_state.pop(cache_key, None)
        return None

    # ── 기본 사전 자동 로드 ──────────────────────────────────────────
    default_dict_dir = Path(__file__).parent / "dict"
    auto_loaded = default_dict_dir.exists()

    uploaded_files = st.file_uploader(
        "추가 사전 CSV 업로드 (선택)",
        type=["csv"],
        accept_multiple_files=True,
        help="국어국문학자료사전.csv / 문학비평용어사전.csv / 한국현대문학대사전.csv 형식의 CSV",
    )

    # 업로드 파일 이름 목록으로 캐시 키 구분
    upload_names = tuple(f.name for f in (uploaded_files or []))
    cache_tag = (auto_loaded, upload_names)

    if st.session_state.get(f"{cache_key}_tag") != cache_tag:
        matcher = DictionaryMatcher()
        total = 0
        if auto_loaded:
            total += matcher.load_from_dir(default_dict_dir)
        if uploaded_files:
            total += matcher.load_from_uploaded(uploaded_files)
        st.session_state[cache_key] = matcher
        st.session_state[f"{cache_key}_tag"] = cache_tag
        st.session_state[f"{cache_key}_count"] = total

    matcher = st.session_state.get(cache_key)
    count = st.session_state.get(f"{cache_key}_count", 0)

    if matcher and count:
        st.success(f"사전 로드 완료 — {count:,}개 엔트리")
    elif not auto_loaded and not uploaded_files:
        st.info("dict/ 폴더가 없습니다. CSV를 직접 업로드하세요.")

    fuzzy_threshold = st.slider(
        "유사도 임계값",
        min_value=70,
        max_value=100,
        value=85,
        step=5,
        help="RapidFuzz 유사도 컷오프. 높을수록 정확 매칭만 허용.",
    )
    st.session_state["dict_fuzzy_threshold"] = fuzzy_threshold

    return matcher


def _ping_ollama(base_url: str) -> None:
    import requests
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m["name"] for m in resp.json().get("models", [])]
        with st.sidebar:
            st.success("연결 성공")
            if names:
                st.caption("설치된 모델: " + ", ".join(names[:6]))
    except Exception as e:
        with st.sidebar:
            st.error(f"연결 실패: {e}")


# ── 메인 ──────────────────────────────────────────────────────────

provider, chunk_size, dict_matcher = _build_provider()

st.title("KorCritTEI — 한국문학비평 TEI 자동 태거")
st.caption("비평텍스트 → TEI/XML 자동 태깅 | XSD 스키마 검증 | 개체명 추출 · CSV 변환")

from ui import data_tab, experiment_tab, tagging_tab, viz_tab

tab1, tab2, tab3, tab4 = st.tabs(
    ["📝 XML 태깅", "📊 개체명 데이터", "📈 시각화", "🧪 모드 비교 실험"]
)

with tab1:
    tagging_tab.render(provider, chunk_size, dict_matcher=dict_matcher)

with tab2:
    data_tab.render()

with tab3:
    viz_tab.render()

with tab4:
    experiment_tab.render(provider, chunk_size, dict_matcher=dict_matcher)
