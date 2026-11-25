"""Stage D: Four-valued proof aggregation, source-independence deduplication,
technical-error vs semantic-UNKNOWN separation, and mechanical rendering.

Key invariants:
- Four-valued truth depends strictly on positive and negative proof support:
    POSITIVE = positive support AND no negative support
    NEGATIVE = negative support AND no positive support
    CONFLICT = BOTH positive and negative support
    UNKNOWN  = NEITHER positive nor negative support
- Absence of proof is NEVER converted to NEGATIVE.
- Technical errors (TIMEOUT, ENGINE_UNAVAILABLE, UNPARSED, MISSING_PROOF_ENTRY)
  are kept strictly distinct from semantic UNKNOWN and NEGATIVE.
- Same-origin reprints (`origin_source_id`) are deduplicated before counting
  independent corroborating sources (compatible with Grok's cl-source-observation-v1).
- Presentation layer mechanically renders PCGM output without LLM truth-guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .schema import OUTCOME_SCHEMA, PROOF_SCHEMA

VALID_FOUR_VALUES = ("POSITIVE", "NEGATIVE", "CONFLICT", "UNKNOWN")
TECHNICAL_ERROR_STATUSES = ("TIMEOUT", "ENGINE_UNAVAILABLE", "UNPARSED", "MISSING_PROOF_ENTRY")


def aggregate_four_value(has_positive: bool, has_negative: bool) -> str:
    """Exact four-valued lattice aggregation (positive & negative channels independent)."""
    if has_positive and has_negative:
        return "CONFLICT"
    if has_positive:
        return "POSITIVE"
    if has_negative:
        return "NEGATIVE"
    return "UNKNOWN"


def combine_four_values(a: str, b: str) -> str:
    """Combine two four-valued states via independent positive/negative channel union.

    UNKNOWN + POSITIVE -> POSITIVE
    UNKNOWN + NEGATIVE -> NEGATIVE
    POSITIVE + NEGATIVE -> CONFLICT
    """
    pos = (a in ("POSITIVE", "CONFLICT")) or (b in ("POSITIVE", "CONFLICT"))
    neg = (a in ("NEGATIVE", "CONFLICT")) or (b in ("NEGATIVE", "CONFLICT"))
    return aggregate_four_value(pos, neg)


def deduplicate_reprint_sources(observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deduplicate same-origin reprints per Grok's cl-source-observation-v1 contract.

    Multiple reprints sharing the same `origin_source_id` count as 1 independent
    source, never N independent corroborations.
    """
    seen_origins: Set[str] = set()
    independent: List[Dict[str, Any]] = []
    reprints_collapsed: List[str] = []

    for obs in observations:
        origin = obs.get("origin_source_id") or obs.get("source_id")
        if not origin:
            continue
        if origin in seen_origins:
            reprints_collapsed.append(obs.get("source_id", origin))
            continue
        seen_origins.add(origin)
        independent.append(obs)

    return {
        "independent_count": len(independent),
        "independent_observations": independent,
        "reprints_collapsed": reprints_collapsed,
    }


def project_cl_proof_v1(proof_payload: Dict[str, Any], case_id: str = "ad-hoc") -> Dict[str, Any]:
    """Project native `cl-proof-v1` (results[].positive / .negative) into `pcgm-reasoned-outcome-v1`."""
    if proof_payload.get("schema") not in (PROOF_SCHEMA, None):
        raise ValueError(f"Unexpected proof schema: {proof_payload.get('schema')}")

    results = proof_payload.get("results", [])
    if not results:
        return {
            "schema": OUTCOME_SCHEMA,
            "case_id": case_id,
            "state_revision": proof_payload.get("state_revision"),
            "goal": proof_payload.get("goal"),
            "status": "MISSING_PROOF_ENTRY",
            "positive_proof": None,
            "negative_proof": None,
            "missing": ["No result entry returned by native proof channel."],
            "question_ticket": None,
            "effect_receipt": None,
        }

    entry = results[0]
    pos = entry.get("positive")
    neg = entry.get("negative")
    has_pos = bool(pos and pos.get("proved", bool(pos)))
    has_neg = bool(neg and neg.get("proved", bool(neg)))

    status = aggregate_four_value(has_pos, has_neg)
    return {
        "schema": OUTCOME_SCHEMA,
        "case_id": case_id,
        "state_revision": proof_payload.get("state_revision"),
        "goal": entry.get("goal", proof_payload.get("goal")),
        "status": status,
        "positive_proof": pos if has_pos else None,
        "negative_proof": neg if has_neg else None,
        "missing": entry.get("missing", []),
        "question_ticket": entry.get("question_ticket"),
        "effect_receipt": entry.get("effect_receipt"),
    }


def render_reasoned_outcome(outcome: Dict[str, Any]) -> str:
    """Mechanically render a `pcgm-reasoned-outcome-v1` object into Chinese.

    Never invents truth values, never collapses CONFLICT to a boolean, and keeps
    technical errors strictly separate from semantic UNKNOWN/NEGATIVE.
    """
    status = outcome.get("status", "UNKNOWN")
    goal = outcome.get("goal")
    goal_str = str(goal) if goal is not None else "（未指定目标）"

    if status in TECHNICAL_ERROR_STATUSES:
        reason = outcome.get("error_detail") or "; ".join(outcome.get("missing", [])) or status
        return f"【技术状态：{status}】未能完成原生求证（不等于否定结论）。目标：{goal_str}；原因：{reason}"

    if status == "POSITIVE":
        return f"【结论：POSITIVE（正向已证）】目标 {goal_str} 有正向证明支持，无反向证明。依据：{outcome.get('positive_proof')}"

    if status == "NEGATIVE":
        return f"【结论：NEGATIVE（反向已证）】目标 {goal_str} 有反向证明支持，无正向证明。依据：{outcome.get('negative_proof')}"

    if status == "CONFLICT":
        return (
            f"【结论：CONFLICT（正反证据冲突）】目标 {goal_str} 同时存在正向与反向支持，已保留双方依据，不擅自取舍。"
            f"\n- 正向依据：{outcome.get('positive_proof')}"
            f"\n- 反向依据：{outcome.get('negative_proof')}"
        )

    if status == "UNKNOWN":
        missing = outcome.get("missing") or []
        ticket = outcome.get("question_ticket")
        parts = [f"【结论：UNKNOWN（证据不足）】目标 {goal_str} 当前既无正向证明也无反向证明（不视为否定）。"]
        if missing:
            parts.append(f"缺失前提：{missing}")
        if ticket:
            parts.append(f"已登记问询票：{ticket}")
        return " ".join(parts)

    return f"【未识别状态：{status}】目标：{goal_str}"
