import streamlit as st
import plotly.express as px

from core.extractor import extract_all

_COLOR_MAP = {
    "affirmative": "#2ecc71",
    "neutral":     "#95a5a6",
    "critical":    "#e74c3c",
}


def render() -> None:
    """Tab 3: 시각화"""
    st.subheader("시각화")

    # 캐시된 dataframes 재사용, 없으면 추출
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
            st.error(f"데이터 추출 오류: {e}")
            return

    viz = st.selectbox(
        "차트 선택",
        [
            "개체 유형별 수량",
            "인물별 등장 빈도",
            "해석/평가 태도 분포",
            "분석 기준별 태도 분포",
            "네트워크 그래프 (구현 예정)",
            "타임라인 (구현 예정)",
        ],
    )

    if viz == "개체 유형별 수량":
        _chart_entity_counts(dataframes)
    elif viz == "인물별 등장 빈도":
        _chart_person_frequency(dataframes)
    elif viz == "해석/평가 태도 분포":
        _chart_interp_pie(dataframes)
    elif viz == "분석 기준별 태도 분포":
        _chart_interp_by_ana(dataframes)
    else:
        st.info(f"'{viz}'은 향후 구현 예정입니다.")


# ── 차트 함수 ─────────────────────────────────────────────────────

def _chart_entity_counts(dataframes: dict) -> None:
    st.markdown("#### 개체 유형별 수량")
    label_map = {
        "persons": "인물", "works": "작품", "orgs": "기관",
        "concepts": "용어", "quotes": "인용문",
        "interpretations": "해석/평가", "dates": "날짜",
    }
    data = {v: len(dataframes[k]) for k, v in label_map.items() if len(dataframes[k]) > 0}
    if not data:
        st.warning("데이터가 없습니다.")
        return
    fig = px.bar(
        x=list(data.keys()),
        y=list(data.values()),
        labels={"x": "개체 유형", "y": "건수"},
        color=list(data.keys()),
        color_discrete_sequence=px.colors.qualitative.Set2,
        text_auto=True,
    )
    fig.update_layout(showlegend=False, xaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)


def _chart_person_frequency(dataframes: dict) -> None:
    st.markdown("#### 인물별 등장 빈도 (상위 20명)")
    df = dataframes.get("persons")
    if df is None or df.empty:
        st.warning("인물(persName) 데이터가 없습니다.")
        return
    if "frequency" not in df.columns or df["frequency"].max() <= 1:
        st.info("동일 인물이 2회 이상 등장하지 않아 빈도 차트를 표시할 수 없습니다.")
        st.dataframe(df[["name", "role"]].head(20), hide_index=True)
        return
    top = df.sort_values("frequency", ascending=False).head(20)
    fig = px.bar(
        top,
        x="name", y="frequency",
        color="role",
        labels={"name": "인물명", "frequency": "등장 횟수", "role": "역할"},
        text_auto=True,
    )
    fig.update_xaxes(tickangle=-30, title=None)
    st.plotly_chart(fig, use_container_width=True)


def _chart_interp_pie(dataframes: dict) -> None:
    st.markdown("#### 비평 태도 분포 (interp @value)")
    df = dataframes.get("interpretations")
    if df is None or df.empty:
        st.warning("해석/평가(interp) 데이터가 없습니다.")
        return
    counts = df["value"].value_counts().reset_index()
    counts.columns = ["태도", "건수"]
    fig = px.pie(
        counts,
        names="태도",
        values="건수",
        hole=0.45,
        color="태도",
        color_discrete_map=_COLOR_MAP,
    )
    fig.update_traces(textposition="outside", textinfo="percent+label")
    st.plotly_chart(fig, use_container_width=True)


def _chart_interp_by_ana(dataframes: dict) -> None:
    st.markdown("#### 분석 기준(ana)별 비평 태도")
    df = dataframes.get("interpretations")
    if df is None or df.empty or "ana" not in df.columns:
        st.warning("해석/평가(interp) 데이터가 없습니다.")
        return
    grouped = df.groupby(["ana", "value"]).size().reset_index(name="건수")
    if grouped.empty:
        st.warning("데이터가 부족합니다.")
        return
    fig = px.bar(
        grouped,
        x="ana", y="건수",
        color="value",
        barmode="stack",
        labels={"ana": "분석 기준", "value": "태도"},
        color_discrete_map=_COLOR_MAP,
    )
    fig.update_xaxes(title=None)
    st.plotly_chart(fig, use_container_width=True)
