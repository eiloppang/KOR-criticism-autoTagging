"""
experiments/retag.py
단일 pipeline 모드로 재태깅하는 헬퍼 (before/after 비교용).

  python -m experiments.retag --input 비평문/성현아.txt --out 문제점/비평문아웃풋3.xml
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # 명시 경로 — find_dotenv 프레임 탐색 회피

from core import tagger  # noqa: E402
from core.dictionary_matcher import load_default_matcher  # noqa: E402
from core.providers import ClaudeProvider  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="비평문/성현아.txt")
    p.add_argument("--out", default="문제점/비평문아웃풋3.xml")
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--chunk-size", type=int, default=5000)
    p.add_argument("--no-dict", action="store_true")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    prov = ClaudeProvider(api_key=key, model=args.model)
    text = Path(args.input).read_text(encoding="utf-8")

    dict_context = ""
    if not args.no_dict:
        dm = load_default_matcher()
        dict_context = dm.format_for_prompt(dm.match(text, fuzzy_threshold=85))

    xml, warns = tagger.tag_text(
        text, prov, chunk_size=args.chunk_size,
        dict_context=dict_context, include_builtin_example=True,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"저장: {args.out} ({len(xml):,}자)")
    print("경고:", warns)


if __name__ == "__main__":
    main()
