import io
import zipfile

import streamlit as st

from core.extractor import extract_all

_LABELS: dict[str, str] = {
    "persons":         "인물 (persName)",
    "works":           "작품 (title)",
    "orgs":            "기관 (orgName)",
    "concepts":        "용어/개념 (term)",
    "quotes":          "인용문 (quote)",
    "interpretations": "해석/평가 (interp)",
    "dates":           "날짜 (date)",
}


def render() -> None:
    """Tab 2: 추출된 개체명 데이터 테이블 + CSV 다운로드"""
    st.subheader("추출된 개체명 데이터")

    # tagging_tab에서 미리 추출한 dataframes 재사용, 없으면 즉석 추출
    dataframes = st.session_state.get("dataframes")
    if dataframes is None:
        xml_output = st.session_state.get("xml_output")
        if not xml_output:
            st.info("먼저 'XML 태깅' 탭에서 태깅을 실행해주세요.")
            return
        try:
            dataframes = extract_all(xml_output)
            st.session_state["dataframes"] = dataframes
        except Exception as e:
            st.error(f"추출 오류: {e}")
            return

    non_empty = {k: df for k, df in dataframes.items() if not df.empty}
    if not non_empty:
        st.warning("추출된 개체가 없습니다. XML 내용을 확인해주세요.")
        return

    # ── 요약 메트릭 ─────────────────────────────────────────────
    metric_cols = st.columns(len(non_empty))
    for i, (key, df) in enumerate(non_empty.items()):
        label_short = _LABELS[key].split(" ")[0]
        metric_cols[i].metric(label_short, f"{len(df)}건")

    st.divider()

    # ── 전체 ZIP 다운로드 ────────────────────────────────────────
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, df in non_empty.items():
            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            zf.writestr(f"{key}.csv", csv_bytes)

    st.download_button(
        "전체 CSV 한꺼번에 다운로드 (ZIP)",
        data=zip_buf.getvalue(),
        file_name="entities.zip",
        mime="application/zip",
    )

    st.divider()

    # ── 개체 유형별 테이블 ───────────────────────────────────────
    for key, label in _LABELS.items():
        df = dataframes.get(key)
        if df is None or df.empty:
            continue
        expanded = key in ("persons", "works")
        with st.expander(f"{label} — {len(df)}건", expanded=expanded):
            st.dataframe(df, use_container_width=True, hide_index=True)
            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                f"{key}.csv 다운로드",
                data=csv_bytes,
                file_name=f"{key}.csv",
                mime="text/csv",
                key=f"dl_csv_{key}",
            )
