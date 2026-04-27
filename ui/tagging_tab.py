import streamlit as st
import pdfplumber
import io

from core.tagger import tag_text
from core.extractor import extract_all


def render(provider, chunk_size: int = 5000, dict_matcher=None) -> None:
    """Tab 1: 텍스트 입력 → 자동 태깅 → XML 결과 확인 및 다운로드"""

    # ── 1. 텍스트 입력 ──────────────────────────────────────────
    st.subheader("1. 비평텍스트 입력")

    col_left, col_right = st.columns([1, 2], gap="medium")

    with col_left:
        uploaded = st.file_uploader(
            "PDF 또는 TXT 파일 업로드",
            type=["pdf", "txt"],
            help="PDF 파일 또는 UTF-8 / CP949 인코딩 텍스트 파일 (200KB 이내 권장)",
        )
        file_text: str | None = None
        if uploaded is not None:
            if uploaded.name.lower().endswith(".pdf"):
                try:
                    with pdfplumber.open(io.BytesIO(uploaded.read())) as pdf:
                        pages = [page.extract_text() or "" for page in pdf.pages]
                    file_text = "\n".join(pages).strip()
                    if not file_text:
                        st.error("PDF에서 텍스트를 추출할 수 없습니다. 스캔 이미지 PDF는 지원하지 않습니다.")
                    else:
                        st.success(f"PDF 로드 완료 — {len(pdf.pages)}페이지 / {len(file_text):,} 글자")
                except Exception as e:
                    st.error(f"PDF 읽기 실패: {e}")
            else:
                raw = uploaded.read()
                for enc in ("utf-8", "utf-8-sig", "cp949"):
                    try:
                        file_text = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if file_text is None:
                    st.error("파일 인코딩을 인식할 수 없습니다 (UTF-8 / CP949 권장).")
                else:
                    st.success(f"파일 로드 완료 — {len(file_text):,} 글자")

    with col_right:
        placeholder = file_text if file_text else ""
        typed_text = st.text_area(
            "직접 입력 (파일 업로드 시 내용이 표시됨)",
            value=placeholder,
            height=280,
            placeholder="비평 텍스트를 여기에 붙여넣거나 왼쪽에서 파일을 업로드하세요.",
            key="tagging_text_area",
        )

    # 최종 입력 결정: 텍스트 영역 우선 (사용자가 편집 가능), 비어 있으면 파일
    input_text = typed_text.strip() or (file_text or "").strip()

    if input_text:
        est_tokens = int(len(input_text) * 0.5)
        st.caption(f"입력 크기: {len(input_text):,} 글자 | 추정 토큰: ~{est_tokens:,}")

    st.divider()

    # ── 2. 태깅 실행 ────────────────────────────────────────────
    st.subheader("2. 자동 태깅 실행")

    btn_col, info_col = st.columns([1, 3], gap="small")

    with btn_col:
        disabled = not input_text or provider is None
        run_btn = st.button(
            "태깅 실행",
            type="primary",
            disabled=disabled,
            use_container_width=True,
        )

    with info_col:
        if provider is None:
            st.warning("사이드바에서 LLM Provider를 설정하세요.")
        elif not input_text:
            st.info("위에서 텍스트를 입력하거나 파일을 업로드하세요.")

    if run_btn:
        from core.chunker import AdaptiveChunker

        # 청크 수 미리 계산 (진행바 표시용)
        preview_chunks = AdaptiveChunker(provider, chunk_size=chunk_size).chunk_text(input_text)
        total_chunks = len(preview_chunks)

        status_box = st.status(
            f"태깅 준비 중... (총 {total_chunks}개 청크)",
            expanded=True,
        )
        progress_bar = status_box.progress(0)
        chunk_log = status_box.empty()

        def on_progress(i: int, total: int, chunk_len: int):
            pct = int(i / total * 100)
            progress_bar.progress(pct)
            chunk_log.markdown(
                f"**청크 {i + 1} / {total}** 처리 중 &nbsp;|&nbsp; {chunk_len:,} 글자"
            )

        # 사전 매칭 수행
        dict_context = ""
        if dict_matcher is not None and dict_matcher.entry_count > 0:
            fuzzy_threshold = st.session_state.get("dict_fuzzy_threshold", 85)
            matches = dict_matcher.match(input_text, fuzzy_threshold=fuzzy_threshold)
            dict_context = dict_matcher.format_for_prompt(matches)
            if matches:
                status_box.write(f"사전 매칭: {len(matches)}개 엔티티 발견")

        try:
            xml_output, warnings = tag_text(
                input_text, provider, chunk_size=chunk_size,
                progress_callback=on_progress,
                dict_context=dict_context,
            )
        except Exception as e:
            status_box.update(label=f"태깅 실패: {e}", state="error")
            st.error(f"태깅 실패: {e}")
            return

        progress_bar.progress(100)
        chunk_log.markdown(f"**완료** — {total_chunks}개 청크 처리")
        status_box.update(
            label=f"태깅 완료 — {total_chunks}개 청크 처리",
            state="complete",
            expanded=False,
        )

        # 결과 및 개체명 캐시 저장
        st.session_state["xml_output"] = xml_output
        st.session_state["dataframes"] = None  # 다음 탭 접근 시 재추출
        try:
            st.session_state["dataframes"] = extract_all(xml_output)
        except Exception:
            pass

        # 경고 분류 표시
        xsd_errors = [w for w in warnings if w.startswith("[")]
        other_warns = [w for w in warnings if not w.startswith("[")]

        for w in other_warns:
            st.warning(w)

        if xsd_errors:
            st.warning(f"XSD 검증 오류 {len(xsd_errors)}건 발생 (XML 다운로드는 가능)")
            with st.expander("XSD 오류 상세 보기"):
                for err in xsd_errors:
                    st.code(err, language="text")
        else:
            st.success("태깅 완료 — XSD 스키마 검증 통과")

    # ── 3. 결과 표시 ────────────────────────────────────────────
    xml_output = st.session_state.get("xml_output")
    if not xml_output:
        return

    st.divider()
    st.subheader("3. XML 결과")

    st.caption(
        f"출력: {len(xml_output):,} 글자 | {xml_output.count(chr(10)):,} 줄"
    )

    st.download_button(
        "XML 다운로드 (output.xml)",
        data=xml_output.encode("utf-8"),
        file_name="output.xml",
        mime="application/xml",
    )

    st.code(xml_output, language="xml", line_numbers=True)
