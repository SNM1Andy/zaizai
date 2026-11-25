"""Minimal runnable CLI for the Zaizai Chinese-to-CL dialogue adapter.

Supports:
- Single utterance mode (`--utterance "..."`)
- JSONL multi-turn session mode (`--jsonl input.jsonl`)
- Persistent session state for restart recovery (`--state state.json`)
- Versioned lexicon loading (`--lexicon path.json --lexicon-version dev-fixture-1`)
- Mechanical rendering of `pcgm-reasoned-outcome-v1` (`--render-outcome outcome.json`)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .lexicon import LexiconRegistry, LexiconVersionError
from .stage_c import DialogueAdapter
from .stage_d import render_reasoned_outcome


def _default_fixture_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures"


def build_registry(lexicon_paths: List[str], allow_candidate_layer: bool = False) -> LexiconRegistry:
    reg = LexiconRegistry()
    if not lexicon_paths:
        fdir = _default_fixture_dir()
        for fname in ("lexicon_dev_v1.json", "lexicon_dev_v2.json"):
            p = fdir / fname
            if p.exists():
                reg.register_file(p, allow_candidate_layer=allow_candidate_layer)
    else:
        for lp in lexicon_paths:
            reg.register_file(lp, allow_candidate_layer=allow_candidate_layer)
    return reg


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zaizai-adapter",
        description="Chinese -> cl-dialogue-candidate-v1 standalone adapter (read-only candidate emitter).",
    )
    parser.add_argument("--utterance", type=str, help="Single Chinese utterance to parse.")
    parser.add_argument("--jsonl", type=str, help="Path to input JSONL file of utterances/turns.")
    parser.add_argument("--out", type=str, help="Optional output JSONL path (defaults to stdout).")
    parser.add_argument("--state", type=str, help="Optional JSON state file for restart recovery.")
    parser.add_argument("--lexicon", action="append", default=[], help="Path to cl-lexicon-sense-v1 JSON file.")
    parser.add_argument("--lexicon-version", type=str, default="dev-fixture-1", help="Active lexicon version.")
    parser.add_argument("--case-id", type=str, default="cli-01")
    parser.add_argument("--utterance-id", type=str, default="u1")
    parser.add_argument("--session-id", type=str, default="s1")
    parser.add_argument("--turn-id", type=str, default="t1")
    parser.add_argument("--render-outcome", type=str, help="Path to pcgm-reasoned-outcome-v1 JSON to render.")

    args = parser.parse_args(argv)

    if args.render_outcome:
        data = json.loads(Path(args.render_outcome).read_text(encoding="utf-8"))
        print(render_reasoned_outcome(data))
        return 0

    try:
        reg = build_registry(args.lexicon)
        adapter = DialogueAdapter(reg, default_lexicon_version=args.lexicon_version)
    except LexiconVersionError as exc:
        print(f"LEXICON_VERSION_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.state:
        adapter.load_state(args.state)

    outputs: List[str] = []

    if args.utterance is not None:
        rec = adapter.process_utterance(
            args.utterance,
            case_id=args.case_id,
            utterance_id=args.utterance_id,
            session_id=args.session_id,
            turn_id=args.turn_id,
            lexicon_version=args.lexicon_version,
        )
        outputs.append(rec.to_json())
    elif args.jsonl:
        lines = Path(args.jsonl).read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            rec = adapter.process_utterance(
                item["raw_text"],
                case_id=item.get("case_id", f"row-{idx:03d}"),
                utterance_id=item.get("utterance_id", f"u{idx}"),
                session_id=item.get("session_id", "s1"),
                turn_id=item.get("turn_id", f"t{idx}"),
                locale=item.get("locale", "zh-CN"),
                lexicon_version=item.get("lexicon_version", args.lexicon_version),
            )
            outputs.append(rec.to_json())
    else:
        parser.error("Provide --utterance, --jsonl, or --render-outcome.")

    if args.state:
        adapter.save_state(args.state)

    result_text = "\n".join(outputs) + ("\n" if outputs else "")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(result_text, encoding="utf-8")
    else:
        sys.stdout.write(result_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
