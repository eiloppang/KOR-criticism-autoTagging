"""
experiments/run_comparison.py
1·2·4단계 태깅 모드 비교 실험 드라이버.

세 모드
-------
  schema_only : (1단계) 스키마+규칙만. 사전·내장예시·few-shot 전부 제거 = zero-shot
  pipeline    : (2단계) 현재 설계된 전체 파이프라인 (사전매칭+내장예시+청킹+후처리)
  few_shot    : (4단계) 수작업 정답을 few-shot 예시로 주입 (In-Context Learning)

채점
----
  --gold 지정 시 : 각 모드를 정답 대비 채점 (정밀도/재현율/F1, 느슨+엄격)
  --gold 미지정  : 모드 간 일치도(agreement)만 계산 (정답이 생기면 같은 코드로 정확도 산출)

사용 예
-------
  # 1) 모드 실행 + 정답 채점 (비평문 B를 테스트, 비평문 A 정답을 few-shot 학습 소스로)
  python -m experiments.run_comparison run \
      --input 비평문/critiqueB.txt --provider gemini \
      --few-shot-source gold/critiqueA.tei.xml \
      --gold gold/critiqueB.tei.xml

  # 2) 정답 없이 모드만 실행 (지금 단계 — 모드 간 일치도만)
  python -m experiments.run_comparison run --input 비평문/critiqueB.txt --provider gemini

  # 3) 이미 만들어둔 두 XML을 오프라인 채점 (API 불필요)
  python -m experiments.run_comparison score --gold a.xml --pred b.xml
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import evaluation, tagger  # noqa: E402

MODES = ["schema_only", "pipeline", "few_shot"]
FUZZY_THRESHOLD = 85


# ── Provider 구성 ────────────────────────────────────────────────

def build_provider(name: str, model: str | None = None):
    """이름으로 LLM Provider를 만든다. API 키는 .env / 환경변수에서 읽는다."""
    from core.providers import ClaudeProvider, GeminiProvider, OllamaProvider

    name = name.lower()
    if name == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY 환경변수가 필요합니다.")
        return GeminiProvider(api_key=key, model=model or "gemini-2.0-flash")
    if name == "claude":
        key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 필요합니다.")
        return ClaudeProvider(api_key=key, model=model or "claude-sonnet-4-6")
    if name == "ollama":
        return OllamaProvider(
            model=model or "qwen3:8b",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    raise ValueError(f"알 수 없는 provider: {name}")


# ── few-shot 예시 생성 (수작업 정답 → 프롬프트 블록) ──────────────

def build_few_shot_from_gold(gold_xml: str, n_examples: int = 2) -> str:
    """
    수작업 정답 TEI/XML에서 문단 몇 개를 골라 '입력(평문) → 출력(태깅)' 예시 블록을 만든다.
    이 블록이 4단계 few-shot In-Context Learning 의 '학습 신호'가 된다.

    ※ 컨닝 방지: 여기 넣는 정답은 '테스트 대상이 아닌' 다른 비평문의 정답이어야 한다.
    """
    from lxml import etree

    root = etree.fromstring(gold_xml.encode("utf-8"))
    paras = root.xpath("//tei:text//tei:p", namespaces=evaluation.NS)[:n_examples]
    if not paras:
        return ""

    import re

    blocks = []
    for i, p in enumerate(paras, 1):
        plain = re.sub(r"\s+", " ", "".join(p.itertext())).strip()
        snippet = etree.tostring(p, pretty_print=True, encoding="unicode").strip()
        blocks.append(f"[예시 {i}]\n입력:\n{plain}\n\n출력:\n{snippet}")

    body = "\n\n".join(blocks)
    return (
        "<수작업-정답-예시>\n"
        "아래는 사람이 직접 태깅한 정답 예시이다. 이 태깅 기준·범위·스타일을 학습하여 "
        "동일하게 적용하라.\n\n"
        f"{body}\n"
        "</수작업-정답-예시>"
    )


# ── 모드 실행 ────────────────────────────────────────────────────

def run_mode(mode: str, text: str, provider, dict_matcher, few_shot: str,
             chunk_size: int) -> tuple[str, list[str]]:
    """한 모드로 태깅을 실행하고 (xml, warnings)를 반환한다."""
    if mode == "schema_only":
        return tagger.tag_text(text, provider, chunk_size,
                              dict_context="", few_shot="",
                              include_builtin_example=False)
    if mode == "pipeline":
        dict_context = ""
        if dict_matcher is not None:
            matches = dict_matcher.match(text, fuzzy_threshold=FUZZY_THRESHOLD)
            dict_context = dict_matcher.format_for_prompt(matches)
        return tagger.tag_text(text, provider, chunk_size,
                              dict_context=dict_context, few_shot="",
                              include_builtin_example=True)
    if mode == "few_shot":
        return tagger.tag_text(text, provider, chunk_size,
                              dict_context="", few_shot=few_shot,
                              include_builtin_example=False)
    raise ValueError(f"알 수 없는 모드: {mode}")


# ── 리포트 작성 ──────────────────────────────────────────────────

def _scored_dataframe(results: dict, mode: str, match: str):
    df = evaluation.to_dataframe(results)
    df.insert(0, "모드", mode)
    df.insert(1, "채점", match)
    return df


def _write_report(out_dir: Path, lines: list[str], frames: list) -> None:
    import pandas as pd

    report = "\n".join(lines)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined.to_csv(out_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    print(f"\n리포트: {out_dir / 'report.md'}")
    print(f"지표 CSV: {out_dir / 'metrics.csv'}")


# ── run 서브커맨드 ───────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    text = Path(args.input).read_text(encoding="utf-8")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    provider = build_provider(args.provider, args.model)

    # 사전 매처 (pipeline 모드용)
    dict_matcher = None
    try:
        from core.dictionary_matcher import load_default_matcher
        dict_matcher = load_default_matcher(ROOT / "dict")
    except Exception as e:
        print(f"[경고] 사전 로드 실패 — pipeline 모드는 사전 없이 실행: {e}")

    # few-shot 학습 소스
    few_shot = ""
    if args.few_shot_source:
        gold_src = Path(args.few_shot_source).read_text(encoding="utf-8")
        few_shot = build_few_shot_from_gold(gold_src, n_examples=args.few_shot_examples)

    gold_xml = Path(args.gold).read_text(encoding="utf-8") if args.gold else None

    # 실행할 모드 결정 (few_shot 소스 없으면 few_shot 모드 건너뜀)
    modes = list(MODES)
    if not few_shot and "few_shot" in modes:
        modes.remove("few_shot")
        print("[안내] --few-shot-source 미지정 → few_shot(4단계) 모드 건너뜀.")

    lines = [
        "# 태깅 모드 비교 리포트",
        f"- 생성: {datetime.now().isoformat(timespec='seconds')}",
        f"- 입력: `{args.input}`  |  provider: `{args.provider}`  |  모델: `{args.model or '기본'}`",
        f"- 정답(gold): `{args.gold or '없음 — 모드 간 일치도만 측정'}`",
        "",
    ]

    # 각 모드 실행 → XML 저장
    outputs: dict[str, str] = {}
    for mode in modes:
        print(f"\n▶ 모드 실행: {mode}")
        try:
            xml, warnings = run_mode(mode, text, provider, dict_matcher, few_shot,
                                    args.chunk_size)
        except Exception as e:
            print(f"  [오류] {mode} 실행 실패: {e}")
            lines.append(f"## {mode}\n\n실행 실패: {e}\n")
            continue
        path = out_dir / f"{mode}.xml"
        path.write_text(xml, encoding="utf-8")
        outputs[mode] = xml
        print(f"  저장: {path}  (경고 {len(warnings)}건)")

    frames: list = []

    # 채점
    if gold_xml is not None:
        lines.append("## 정답 대비 채점\n")
        for mode, xml in outputs.items():
            for match, strict in [("느슨", False), ("엄격", True)]:
                res = evaluation.score(gold_xml, xml, strict=strict)
                frames.append(_scored_dataframe(res, mode, match))
                lines.append(evaluation.format_markdown(res, f"{mode} — {match}"))
                lines.append("")
    elif len(outputs) >= 2:
        lines.append("## 모드 간 일치도 (정답 없음)\n")
        lines.append("> 정답이 없어 '정확도'가 아닌 두 모드의 합치 정도를 봅니다. "
                     "기준 모드를 정답 자리에 두고 F1을 계산합니다(F1은 대칭).\n")
        names = list(outputs)
        ref = "pipeline" if "pipeline" in outputs else names[0]
        for mode in names:
            if mode == ref:
                continue
            res = evaluation.score(outputs[ref], outputs[mode], strict=False)
            frames.append(_scored_dataframe(res, f"{ref}↔{mode}", "느슨"))
            lines.append(evaluation.format_markdown(res, f"{ref} ↔ {mode} (일치도, 느슨)"))
            lines.append("")

    _write_report(out_dir, lines, frames)


# ── score 서브커맨드 (오프라인) ──────────────────────────────────

def cmd_score(args: argparse.Namespace) -> None:
    gold = Path(args.gold).read_text(encoding="utf-8")
    pred = Path(args.pred).read_text(encoding="utf-8")
    for match, strict in [("느슨", False), ("엄격", True)]:
        res = evaluation.score(gold, pred, strict=strict)
        print(evaluation.format_markdown(res, f"{Path(args.pred).name} ({match})"))
        print()


# ── 엔트리포인트 ─────────────────────────────────────────────────

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="태깅 모드 비교 실험")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="모드 실행 + 채점")
    p_run.add_argument("--input", required=True, help="비평문 평문 텍스트 파일(.txt)")
    p_run.add_argument("--provider", default="gemini", help="gemini | claude | ollama")
    p_run.add_argument("--model", default=None, help="모델명 (생략 시 provider 기본값)")
    p_run.add_argument("--gold", default=None, help="정답 TEI/XML (있으면 정확도 채점)")
    p_run.add_argument("--few-shot-source", default=None,
                       help="few-shot 학습용 정답 TEI/XML (테스트와 다른 비평문)")
    p_run.add_argument("--few-shot-examples", type=int, default=2,
                       help="few-shot 예시 문단 수 (기본 2)")
    p_run.add_argument("--chunk-size", type=int, default=5000)
    p_run.add_argument("--out", default=str(ROOT / "experiments" / "out"))
    p_run.set_defaults(func=cmd_run)

    p_score = sub.add_parser("score", help="두 XML 오프라인 채점")
    p_score.add_argument("--gold", required=True)
    p_score.add_argument("--pred", required=True)
    p_score.set_defaults(func=cmd_score)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
