"""
ui/experiment_tab.py
Tab 4: 태깅 모드 비교 실험 (1·2·4단계) — 화면에서 실행·비교.

  schema_only : (1단계) 스키마+규칙만 = zero-shot
  pipeline    : (2단계) 현재 설계 파이프라인 (사전매칭+내장예시+후처리)
  few_shot    : (4단계) 수작업 정답을 예시로 주입 (정답 소스 업로드 시에만)

정답(gold) 업로드 시 → 진짜 정확도(P/R/F1). 미업로드 시 → 모드 간 일치도.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from core import evaluation
from core.tagger import tag_text

ROOT = Path(__file__).resolve().parent.parent
CRITIQUE_DIR = ROOT / "비평문"

MODE_LABELS = {
    "schema_only": "1단계 · zero-shot (스키마만)",
    "pipeline":    "2단계 · 설계 파이프라인",
    "few_shot":    "4단계 · few-shot 학습",
}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _build_few_shot(gold_xml: str, n: int = 2) -> str:
    """정답 TEI에서 '입력→출력' few-shot 예시 블록 생성."""
    import re

    from lxml import etree
    parser = etree.XMLParser(collect_ids=False)
    root = etree.fromstring(gold_xml.encode("utf-8"), parser=parser)
    paras = root.xpath("//tei:text//tei:p", namespaces=evaluation.NS)[:n]
    if not paras:
        return ""
    blocks = []
    for i, p in enumerate(paras, 1):
        plain = re.sub(r"\s+", " ", "".join(p.itertext())).strip()
        snippet = etree.tostring(p, pretty_print=True, encoding="unicode").strip()
        blocks.append(f"[예시 {i}]\n입력:\n{plain}\n\n출력:\n{snippet}")
    return (
        "<수작업-정답-예시>\n사람이 직접 태깅한 정답 예시이다. 이 태깅 기준·범위·스타일을 "
        "학습하여 동일하게 적용하라.\n\n" + "\n\n".join(blocks) + "\n</수작업-정답-예시>"
    )


def _run_mode(mode, text, provider, dict_matcher, few_shot, chunk_size, on_progress):
    """한 모드 실행 → (xml, warnings)."""
    if mode == "schema_only":
        kw = dict(dict_context="", few_shot="", include_builtin_example=False)
    elif mode == "pipeline":
        dc = ""
        if dict_matcher is not None and getattr(dict_matcher, "entry_count", 0) > 0:
            ft = st.session_state.get("dict_fuzzy_threshold", 85)
            dc = dict_matcher.format_for_prompt(
                dict_matcher.match(text, fuzzy_threshold=ft))
        kw = dict(dict_context=dc, few_shot="", include_builtin_example=True)
    else:  # few_shot
        kw = dict(dict_context="", few_shot=few_shot, include_builtin_example=False)
    return tag_text(text, provider, chunk_size=chunk_size,
                    progress_callback=on_progress, **kw)


def render(provider, chunk_size: int = 5000, dict_matcher=None) -> None:
    st.subheader("태깅 모드 비교 실험")
    st.caption("같은 텍스트에 zero-shot / 파이프라인 / few-shot 을 돌려 정확도(또는 일치도)를 비교합니다.")

    # ── 1. 입력 텍스트 ──────────────────────────────────────────
    st.markdown("##### 1. 입력 비평문")
    txt_files = sorted(CRITIQUE_DIR.glob("*.txt"))
    options = ["(직접 입력/업로드)"] + [f.name for f in txt_files]
    pick = st.selectbox("비평문 선택", options,
                        help="비평문/ 폴더에서 추출된 .txt. 없으면 업로드/붙여넣기.")

    input_text = ""
    if pick != "(직접 입력/업로드)":
        input_text = (CRITIQUE_DIR / pick).read_text(encoding="utf-8")
        st.success(f"{pick} — {len(input_text):,} 글자")
    else:
        up = st.file_uploader("TXT 업로드", type=["txt"], key="exp_txt")
        if up:
            input_text = _decode(up.read())
        input_text = st.text_area("또는 직접 입력", value=input_text, height=160,
                                  key="exp_text_area").strip()

    # ── 2. 옵션 ─────────────────────────────────────────────────
    st.markdown("##### 2. 옵션")
    c1, c2 = st.columns(2)
    with c1:
        gold_up = st.file_uploader(
            "정답(gold) TEI/XML — 업로드 시 진짜 정확도 채점",
            type=["xml"], key="exp_gold")
    with c2:
        fs_up = st.file_uploader(
            "few-shot 학습 소스 TEI/XML — 업로드 시 4단계 모드 추가",
            type=["xml"], key="exp_fewshot",
            help="컨닝 방지를 위해 테스트와 다른 비평문의 정답을 넣으세요.")

    gold_xml = _decode(gold_up.read()) if gold_up else None
    few_shot = _build_few_shot(_decode(fs_up.read())) if fs_up else ""

    modes = ["schema_only", "pipeline"]
    if few_shot:
        modes.append("few_shot")

    st.caption("실행 모드: " + " · ".join(MODE_LABELS[m] for m in modes))

    # ── 3. 실행 ─────────────────────────────────────────────────
    disabled = not input_text or provider is None
    if provider is None:
        st.warning("사이드바에서 LLM Provider를 설정하세요.")
    run = st.button("비교 실험 실행", type="primary", disabled=disabled,
                    use_container_width=True)

    if run:
        from core.chunker import AdaptiveChunker
        total_chunks = len(AdaptiveChunker(provider, chunk_size=chunk_size).chunk_text(input_text))
        outputs: dict[str, str] = {}
        warns_all: dict[str, list] = {}

        status = st.status(f"실행 중 — {len(modes)}개 모드 × {total_chunks}청크", expanded=True)
        bar = status.progress(0)
        log = status.empty()

        for mi, mode in enumerate(modes):
            def on_progress(i, total, clen, _mode=mode, _mi=mi):
                done = (_mi * total) + i
                bar.progress(int(done / (len(modes) * total) * 100))
                log.markdown(f"**{MODE_LABELS[_mode]}** — 청크 {i+1}/{total} ({clen:,}자)")
            try:
                xml, warns = _run_mode(mode, input_text, provider, dict_matcher,
                                       few_shot, chunk_size, on_progress)
            except Exception as e:
                status.update(label=f"{mode} 실패: {e}", state="error")
                st.error(f"{MODE_LABELS[mode]} 실행 실패: {e}")
                return
            outputs[mode] = xml
            warns_all[mode] = warns

        bar.progress(100)
        status.update(label="완료", state="complete", expanded=False)
        st.session_state["exp_outputs"] = outputs
        st.session_state["exp_gold_xml"] = gold_xml
        st.session_state["exp_warns"] = warns_all

    # ── 4. 결과 ─────────────────────────────────────────────────
    outputs = st.session_state.get("exp_outputs")
    if not outputs:
        return
    gold_xml = st.session_state.get("exp_gold_xml")

    st.divider()
    st.markdown("##### 3. 결과")

    # 개체 수 요약
    count_rows = []
    for mode, xml in outputs.items():
        try:
            ann = evaluation.extract_annotations(xml, strict=False)
        except ValueError as e:
            st.error(f"{mode} 결과 파싱 실패: {e}")
            continue
        row = {"모드": MODE_LABELS[mode]}
        for k, spec in evaluation.TYPE_SPECS.items():
            row[spec.label] = sum(ann[k].values())
        count_rows.append(row)
    if count_rows:
        st.markdown("**모드별 태깅 개체 수**")
        st.dataframe(pd.DataFrame(count_rows), hide_index=True, use_container_width=True)

    # 채점 표
    frames = []
    if gold_xml is not None:
        st.markdown("**정답 대비 정확도 (P/R/F1)**")
        for mode, xml in outputs.items():
            for match, strict in [("느슨", False), ("엄격", True)]:
                res = evaluation.score(gold_xml, xml, strict=strict)
                df = evaluation.to_dataframe(res)
                df.insert(0, "모드", MODE_LABELS[mode]); df.insert(1, "채점", match)
                frames.append(df)
        # 핵심 요약: 모드별 전체 micro F1
        st.markdown("**전체 micro F1 비교**")
        mcols = st.columns(len(outputs))
        for col, (mode, xml) in zip(mcols, outputs.items()):
            f_le = evaluation.score(gold_xml, xml, strict=False)["__micro__"].f1
            f_st = evaluation.score(gold_xml, xml, strict=True)["__micro__"].f1
            col.metric(MODE_LABELS[mode], f"{f_le:.3f}", f"엄격 {f_st:.3f}",
                       delta_color="off")
    elif len(outputs) >= 2:
        st.info("정답(gold) 미업로드 → '정확도'가 아닌 모드 간 일치도. 정답을 올리면 같은 화면에서 진짜 정확도가 나옵니다.")
        ref = "pipeline" if "pipeline" in outputs else list(outputs)[0]
        for mode in outputs:
            if mode == ref:
                continue
            res = evaluation.score(outputs[ref], outputs[mode], strict=False)
            df = evaluation.to_dataframe(res)
            df.insert(0, "비교", f"{MODE_LABELS[ref]} ↔ {MODE_LABELS[mode]}")
            frames.append(df)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        st.dataframe(combined, hide_index=True, use_container_width=True)
        st.download_button("지표 CSV 다운로드", combined.to_csv(index=False).encode("utf-8-sig"),
                           "metrics.csv", "text/csv")

    # 각 모드 XML
    st.markdown("**모드별 출력 XML**")
    for mode, xml in outputs.items():
        with st.expander(f"{MODE_LABELS[mode]} — {len(xml):,}자"):
            st.download_button(f"{mode}.xml 다운로드", xml.encode("utf-8"),
                               f"{mode}.xml", "application/xml", key=f"dl_{mode}")
            st.code(xml, language="xml", line_numbers=True)
