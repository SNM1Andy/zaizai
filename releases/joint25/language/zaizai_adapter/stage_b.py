"""Stage B: Composable grammar, sense resolution, type/arity/unit checking.

Key invariants:
- Surface form is separated from computation: "一加一", "1＋1", "两个一相加",
  "42＋九十九＝？" all compose to `qty_add(a, b, $result)` with `$result`
  explicitly unbound (NEVER pre-filled with the answer).
- Predicates are never guessed or invented outside the active lexicon.
- Ambiguous senses are preserved as distinct alternatives rather than collapsed
  by a confidence score.
- Unit/dimension mismatches (e.g., 2 kg vs 2 pieces) are flagged explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re

from .lexicon import Lexicon, SenseEntry
from .schema import AlternativeCandidate, InputSpan, MissingItem, char_span_to_utf8_span
from .stage_a import StageAResult, TypedLiteral, parse_chinese_nonneg_int


@dataclass
class ExtractedEntity:
    surface: str
    char_start: int
    char_end: int
    byte_start: int
    byte_end: int
    senses: List[SenseEntry]  # empty if novel entity
    novel_symbol: Optional[str] = None


@dataclass
class StageBResult:
    intent: str
    disambiguation: str
    alternatives: List[AlternativeCandidate] = field(default_factory=list)
    missing: List[MissingItem] = field(default_factory=list)
    extra_spans: List[InputSpan] = field(default_factory=list)
    entities: List[ExtractedEntity] = field(default_factory=list)
    predicates: List[SenseEntry] = field(default_factory=list)
    uses_anaphora: bool = False
    anaphora_token: Optional[str] = None
    negated: bool = False


_ADD_WORDS_RE = re.compile(r"(\+|加上|加|相加|之和|的和)")
_MULTIPLICATIVE_ADD_RE = re.compile(r"([两二2])\s*个\s*([零〇一二两兩三四五六七八九十百千万\d]+)\s*(?:相加|加在一起|合起来)")
_EQ_QUERY_RE = re.compile(r"(等于几|等于多少|是多少|是几|= *\?|结果是多少|一共多少|合起来是多少|相加是多少)")
_ANAPHORA_RE = re.compile(r"(那它|它|那个|那份|这份|另一个|另外那份|它们)")
_NEGATION_RE = re.compile(r"(不能|不可|无法|不是|没|未|不)")
_NOVEL_ENTITY_RE = re.compile(r"([甲乙丙丁戊己庚辛壬癸A-Za-z0-9_]+(?:架|柜|箱|盒|册|卷|库|仓|号|档案|文档|节点|样本))")
_IDENTITY_RE = re.compile(r"(是不是同一个|是否为同一个|是不是同一份|是不是一回事|是不是相等|是否等价|是不是一样|同一个副本)")
_CONFLICT_QUERY_RE = re.compile(r"(到底有没有|到底能不能|到底是不是|究竟有没有|究竟能不能)")


def _extract_entities(raw_text: str, unquoted_view: str, lexicon: Lexicon) -> List[ExtractedEntity]:
    """Match known lexicon entities first (longest-first), then novel compositional entities."""
    found: List[ExtractedEntity] = []
    occupied = [False] * len(raw_text)

    # 1. Lexicon entities (longest surface first)
    for surface, entries in lexicon.surface_forms_by_length(kind="entity"):
        start_idx = 0
        while True:
            idx = unquoted_view.find(surface, start_idx)
            if idx == -1:
                break
            end_idx = idx + len(surface)
            if not any(occupied[idx:end_idx]):
                b_s, b_e = char_span_to_utf8_span(raw_text, idx, end_idx)
                found.append(
                    ExtractedEntity(
                        surface=raw_text[idx:end_idx],
                        char_start=idx,
                        char_end=end_idx,
                        byte_start=b_s,
                        byte_end=b_e,
                        senses=entries,
                    )
                )
                for p in range(idx, end_idx):
                    occupied[p] = True
            start_idx = end_idx

    # 2. Novel compositional entities not in lexicon (D18)
    for m in _NOVEL_ENTITY_RE.finditer(unquoted_view):
        s, e = m.start(1), m.end(1)
        if any(occupied[s:e]):
            continue
        surf = raw_text[s:e]
        b_s, b_e = char_span_to_utf8_span(raw_text, s, e)
        found.append(
            ExtractedEntity(
                surface=surf,
                char_start=s,
                char_end=e,
                byte_start=b_s,
                byte_end=b_e,
                senses=[],
                novel_symbol=f"sym_{surf}",
            )
        )
        for p in range(s, e):
            occupied[p] = True

    found.sort(key=lambda x: x.char_start)
    return found


def _extract_predicates(
    raw_text: str, unquoted_view: str, lexicon: Lexicon
) -> Tuple[List[SenseEntry], List[InputSpan]]:
    """Find predicate senses present in unquoted_view."""
    preds: List[SenseEntry] = []
    spans: List[InputSpan] = []
    occupied = [False] * len(raw_text)

    for surface, entries in lexicon.surface_forms_by_length(kind="predicate"):
        idx = unquoted_view.find(surface)
        if idx != -1:
            end_idx = idx + len(surface)
            if not any(occupied[idx:end_idx]):
                b_s, b_e = char_span_to_utf8_span(raw_text, idx, end_idx)
                spans.append(
                    InputSpan(
                        start=b_s,
                        end=b_e,
                        kind="predicate",
                        raw_bytes_utf8=raw_text[idx:end_idx],
                    )
                )
                preds.extend(entries)
                for p in range(idx, end_idx):
                    occupied[p] = True
    return preds, spans


def _try_compose_bounded_addition(
    stage_a: StageAResult, utterance_id: str, lexicon: Lexicon
) -> Optional[StageBResult]:
    """Compose two-operand non-negative integer addition with UNBOUND $result."""
    uv = stage_a.unquoted_view

    # Pattern 1: "两个一相加" -> 1 + 1
    mm = _MULTIPLICATIVE_ADD_RE.search(uv)
    operands: Optional[Tuple[int, int]] = None
    if mm:
        operand = parse_chinese_nonneg_int(mm.group(2))
        if operand is not None:
            operands = (operand, operand)

    # Pattern 2: "<num1> +/加/加上 <num2>"
    if operands is None and _ADD_WORDS_RE.search(uv):
        nat_lits = [l for l in stage_a.literals if l.kind == "nat"]
        if len(nat_lits) == 2:
            operands = (int(nat_lits[0].value), int(nat_lits[1].value))

    if operands is None:
        return None

    add_senses = lexicon.lookup_surface("加", kind="operator")
    sense_ids = [s.sense_id for s in add_senses] or ["demo.qty_add.1"]
    a_val, b_val = operands

    cand = AlternativeCandidate(
        candidate_id="c1",
        goal={
            "predicate": "qty_add",
            "polarity": "positive",
            "arguments": [
                {"type": "nat", "value": a_val},
                {"type": "nat", "value": b_val},
                {"type": "var", "name": "$result", "expected_type": "nat"},
            ],
        },
        variables=[{"name": "$result", "type": "nat", "bound": False}],
        sense_ids=sense_ids,
        source_refs=[
            f"utterance:{utterance_id}",
            f"lexicon:{lexicon.version}#{sense_ids[0]}",
        ],
        premises=[],
        dispatch_target="solver:qty_add",
        polarity="positive",
        metadata={
            "note": "Result variable is intentionally unbound; must be solved by native qty_add, never prefilled.",
            "old_ground_proof_compatible": False,
        },
    )
    return StageBResult(
        intent="query",
        disambiguation="unique",
        alternatives=[cand],
        missing=[],
    )


def _try_compose_unit_equivalence(
    stage_a: StageAResult, utterance_id: str, lexicon: Lexicon
) -> Optional[StageBResult]:
    """Check equivalence queries over typed quantities (D12)."""
    qty_lits = [l for l in stage_a.literals if l.kind == "quantity"]
    if (
        len(qty_lits) >= 2
        and "同一个" not in stage_a.unquoted_view
        and "同一份" not in stage_a.unquoted_view
        and _IDENTITY_RE.search(stage_a.unquoted_view)
    ):
        q1, q2 = qty_lits[0], qty_lits[1]
        if q1.dimension != q2.dimension:
            return StageBResult(
                intent="query",
                disambiguation="needs_clarification",
                alternatives=[],
                missing=[
                    MissingItem(
                        kind="unit_dimension_mismatch",
                        detail=(
                            f"Cannot prove equivalence between incompatible dimensions: "
                            f"{q1.value} {q1.unit} ({q1.dimension}) vs "
                            f"{q2.value} {q2.unit} ({q2.dimension}); default unit conversion is forbidden."
                        ),
                        clarification_question=(
                            f"「{q1.raw_text}」（{q1.dimension}）与「{q2.raw_text}」（{q2.dimension}）"
                            f"类型不同，无法直接判定等价；是否提供了明确的换算规则（例如每件重量）？"
                        ),
                    )
                ],
            )
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal={
                "predicate": "qty_equiv",
                "polarity": "positive",
                "arguments": [
                    {"type": "quantity", "value": q1.value, "unit": q1.unit, "dimension": q1.dimension},
                    {"type": "quantity", "value": q2.value, "unit": q2.unit, "dimension": q2.dimension},
                ],
            },
            variables=[],
            sense_ids=["demo.qty_equiv.1"],
            source_refs=[f"utterance:{utterance_id}", f"lexicon:{lexicon.version}#demo.qty_equiv.1"],
            premises=[],
            dispatch_target="solver:qty_equiv",
            polarity="positive",
        )
        return StageBResult(intent="query", disambiguation="unique", alternatives=[cand])
    return None


def analyze_stage_b(
    stage_a: StageAResult,
    utterance_id: str,
    lexicon: Lexicon,
) -> StageBResult:
    """Run Stage B composable grammar & type checking."""
    uv = stage_a.unquoted_view
    raw = stage_a.raw_text

    # 1. Quoted literal material (D15): never convert to command/write/retraction
    if stage_a.modality == "quoted_material":
        return StageBResult(
            intent="quoted_material",
            disambiguation="not_applicable",
            alternatives=[],
            missing=[],
        )

    # 2. Expressive self-report vs evaluation (D13)
    if stage_a.modality in ("expressive_self_report", "expressive_evaluation"):
        speaker = "user" if stage_a.modality == "expressive_self_report" else "user_about_agent"
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal=None,
            variables=[],
            sense_ids=[],
            source_refs=[f"utterance:{utterance_id}"],
            premises=[],
            dispatch_target="none",
            metadata={
                "speech_act": stage_a.modality,
                "speaker_role": speaker,
                "provable_fact": False,
            },
        )
        return StageBResult(
            intent=stage_a.modality,
            disambiguation="not_applicable",
            alternatives=[cand],
            missing=[],
        )

    # 3. Negation of prior negative assertion (D07)
    if stage_a.modality == "negation_of_assertion":
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal=None,
            variables=[],
            sense_ids=[],
            source_refs=[f"utterance:{utterance_id}"],
            premises=[],
            dispatch_target="none",
            metadata={
                "epistemic_stance": "UNKNOWN",
                "rejects_negative_assertion": True,
                "note": "User disavows negative claim and reports lack of knowledge; MUST NOT emit negative goal.",
            },
        )
        return StageBResult(
            intent="epistemic_clarification",
            disambiguation="unique",
            alternatives=[cand],
            missing=[],
        )

    # 4. Bounded arithmetic composition (D01, D02, D03, etc.)
    arith = _try_compose_bounded_addition(stage_a, utterance_id, lexicon)
    if arith is not None:
        return arith

    # 5. Typed unit equivalence (D12)
    unit_eq = _try_compose_unit_equivalence(stage_a, utterance_id, lexicon)
    if unit_eq is not None:
        return unit_eq

    # 6. Extract entities, predicates, anaphora
    entities = _extract_entities(raw, uv, lexicon)
    predicates, pred_spans = _extract_predicates(raw, uv, lexicon)
    extra_spans: List[InputSpan] = list(pred_spans)
    for ent in entities:
        extra_spans.append(
            InputSpan(
                start=ent.byte_start,
                end=ent.byte_end,
                kind="entity" if ent.senses else "novel_entity",
                raw_bytes_utf8=ent.surface,
            )
        )

    ana_m = _ANAPHORA_RE.search(uv)
    uses_anaphora = ana_m is not None
    anaphora_token = ana_m.group(1) if ana_m else None
    if ana_m:
        b_s, b_e = char_span_to_utf8_span(raw, ana_m.start(1), ana_m.end(1))
        extra_spans.append(
            InputSpan(
                start=b_s,
                end=b_e,
                kind="anaphora",
                raw_bytes_utf8=raw[ana_m.start(1) : ana_m.end(1)],
            )
        )

    # 7. Quotation with reported speaker (D09)
    if stage_a.modality == "quotation":
        quoted_inner = stage_a.quotes[0].inner_text if stage_a.quotes else uv
        q_entities = _extract_entities(quoted_inner, quoted_inner, lexicon)
        q_preds, _ = _extract_predicates(quoted_inner, quoted_inner, lexicon)
        q_neg = bool(_NEGATION_RE.search(quoted_inner))
        q_goal = None
        sense_ids: List[str] = []
        if q_preds and q_entities:
            p = q_preds[0]
            e = q_entities[0]
            e_val = e.senses[0].canonical if e.senses else e.novel_symbol
            sense_ids = [p.sense_id] + ([e.senses[0].sense_id] if e.senses else [])
            q_goal = {
                "predicate": p.canonical,
                "polarity": "negative" if q_neg else "positive",
                "arguments": [{"type": "sym", "value": e_val}],
            }
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal=q_goal,
            variables=[],
            sense_ids=sense_ids,
            source_refs=[f"utterance:{utterance_id}"],
            premises=[],
            dispatch_target="none",
            polarity="negative" if q_neg else "positive",
            metadata={
                "reported_claim_only": True,
                "admissible_as_user_observation": False,
                "quoted_text": quoted_inner,
            },
        )
        return StageBResult(
            intent="quotation",
            disambiguation="unique" if q_goal else "needs_clarification",
            alternatives=[cand],
            missing=[],
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
        )

    # 8. Conditional (D08): "如果校对完成，我就借出"
    if stage_a.modality == "conditional":
        parts = re.split(r"[，,]\s*(?:我)?(?:就|则|那么|才)|(?:就|则|那么|才)", uv, maxsplit=1)
        cond_text = parts[0] if parts else uv
        cons_text = parts[1] if len(parts) > 1 else ""
        cond_preds, _ = _extract_predicates(cond_text, cond_text, lexicon)
        cons_preds, _ = _extract_predicates(cons_text, cons_text, lexicon)
        target_sym = (
            entities[0].senses[0].canonical
            if entities and entities[0].senses
            else (entities[0].novel_symbol if entities else "$target")
        )
        premises_list: List[Dict[str, Any]] = []
        sense_ids = []
        if cond_preds:
            premises_list.append(
                {
                    "predicate": cond_preds[0].canonical,
                    "polarity": "positive",
                    "arguments": [{"type": "sym", "value": target_sym}],
                    "status": "unproven_condition",
                }
            )
            sense_ids.append(cond_preds[0].sense_id)
        cons_goal = None
        if cons_preds:
            cons_goal = {
                "predicate": cons_preds[0].canonical,
                "polarity": "positive",
                "arguments": [{"type": "sym", "value": target_sym}],
            }
            sense_ids.append(cons_preds[0].sense_id)
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal=cons_goal,
            variables=[{"name": "$target", "type": "sym", "bound": False}] if target_sym == "$target" else [],
            sense_ids=sense_ids,
            source_refs=[f"utterance:{utterance_id}"]
            + [f"lexicon:{lexicon.version}#{sid}" for sid in sense_ids],
            premises=premises_list,
            dispatch_target="none",
            polarity="positive",
            metadata={
                "conditional": True,
                "premise_asserted_as_fact": False,
                "action_executed": False,
            },
        )
        return StageBResult(
            intent="conditional",
            disambiguation="unique" if cons_goal and premises_list else "needs_clarification",
            alternatives=[cand],
            missing=[],
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
            uses_anaphora=uses_anaphora,
            anaphora_token=anaphora_token,
        )

    # 9. Cardinality vs identity query (D17): "架上有两份，但它们都是同一个副本吗？"
    if _IDENTITY_RE.search(uv) and ("副本" in uv or "两份" in uv or "它们" in uv):
        qty_lits = [l for l in stage_a.literals if l.kind == "quantity"]
        count_val = qty_lits[0].value if qty_lits else None
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal={
                "predicate": "same_copy",
                "polarity": "positive",
                "arguments": [
                    {"type": "var", "name": "$copy_a", "expected_type": "sym"},
                    {"type": "var", "name": "$copy_b", "expected_type": "sym"},
                ],
            },
            variables=[
                {"name": "$copy_a", "type": "sym", "bound": False},
                {"name": "$copy_b", "type": "sym", "bound": False},
            ],
            sense_ids=["demo.same_copy.1"],
            source_refs=[f"utterance:{utterance_id}", f"lexicon:{lexicon.version}#demo.same_copy.1"],
            premises=[{"cardinality_mentioned": count_val}] if count_val is not None else [],
            dispatch_target="none",
            polarity="positive",
            metadata={
                "distinguishes_cardinality_from_identity": True,
                "common_sense_guessing_forbidden": True,
            },
        )
        return StageBResult(
            intent="query",
            disambiguation="needs_clarification",
            alternatives=[cand],
            missing=[
                MissingItem(
                    kind="missing_entity_reference",
                    detail="Count (2 copies) is distinct from copy identity; concrete copy identifiers are missing.",
                    clarification_question="请指明要比较哪两份具体副本（例如它们的编号或来源记录），才能核查它们是否为同一副本。",
                )
            ],
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
            uses_anaphora=uses_anaphora,
            anaphora_token=anaphora_token,
        )

    # 10. Retraction / Correction / Conflict-status pass-through to Stage C
    if stage_a.modality in ("retraction", "correction"):
        return StageBResult(
            intent=stage_a.modality,
            disambiguation="needs_clarification",
            alternatives=[],
            missing=[],
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
            uses_anaphora=uses_anaphora,
            anaphora_token=anaphora_token,
        )

    if _CONFLICT_QUERY_RE.search(uv) and not predicates:
        return StageBResult(
            intent="query_conflict_status",
            disambiguation="needs_clarification",
            alternatives=[],
            missing=[],
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
            uses_anaphora=True,
            anaphora_token=anaphora_token,
        )

    # 11. Composable predicate(entity) composition
    negated = bool(_NEGATION_RE.search(uv)) and not ("能不能" in uv or "是不是" in uv or "有没有" in uv)
    polarity = "negative" if negated else "positive"

    if predicates and entities:
        # Build Cartesian product of predicate senses x entity senses (preserving ambiguity!)
        alts: List[AlternativeCandidate] = []
        cid_num = 1
        for pred in predicates:
            for ent in entities:
                ent_options: List[Tuple[str, Optional[str]]] = (
                    [(s.canonical, s.sense_id) for s in ent.senses]
                    if ent.senses
                    else [(ent.novel_symbol or ent.surface, None)]
                )
                for sym_val, ent_sid in ent_options:
                    if len(pred.arg_types) != 1:
                        continue
                    sids = [pred.sense_id] + ([ent_sid] if ent_sid else [])
                    refs = [f"utterance:{utterance_id}"] + [
                        f"lexicon:{lexicon.version}#{s}" for s in sids
                    ]
                    alts.append(
                        AlternativeCandidate(
                            candidate_id=f"c{cid_num}",
                            goal={
                                "predicate": pred.canonical,
                                "polarity": polarity,
                                "arguments": [{"type": pred.arg_types[0], "value": sym_val}],
                            },
                            variables=[],
                            sense_ids=sids,
                            source_refs=refs,
                            premises=[],
                            dispatch_target="read-channel:proof" if stage_a.modality == "query" else "proposal:observe",
                            polarity=polarity,
                            metadata={"novel_entity": ent_sid is None},
                        )
                    )
                    cid_num += 1
        disamb = "unique" if len(alts) == 1 else ("ambiguous" if len(alts) > 1 else "needs_clarification")
        missing: List[MissingItem] = []
        if len(alts) > 1:
            missing.append(
                MissingItem(
                    kind="ambiguous_sense_or_entity",
                    detail=f"Multiple valid interpretations ({len(alts)}) under lexicon {lexicon.version}.",
                    candidate_ids=[a.candidate_id for a in alts],
                    clarification_question="存在多种可行解释，请确认您指的是哪一项："
                    + " / ".join(
                        f"{a.candidate_id}:{a.goal['predicate']}({a.goal['arguments'][0]['value']})"
                        for a in alts
                        if a.goal
                    ),
                )
            )
        return StageBResult(
            intent="query" if stage_a.modality == "query" else "assertion",
            disambiguation=disamb,
            alternatives=alts,
            missing=missing,
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
            uses_anaphora=uses_anaphora,
            anaphora_token=anaphora_token,
            negated=negated,
        )

    # 12. Predicate present, entity missing -> may be resolved by Stage C anaphora
    if predicates and not entities:
        return StageBResult(
            intent="query" if stage_a.modality == "query" else "assertion",
            disambiguation="needs_clarification",
            alternatives=[],
            missing=[
                MissingItem(
                    kind="missing_argument",
                    detail=f"Predicate '{predicates[0].canonical}' requires 1 argument of type {predicates[0].arg_types}.",
                    clarification_question="请指明您询问或陈述的具体对象。",
                )
            ],
            extra_spans=extra_spans,
            entities=entities,
            predicates=predicates,
            uses_anaphora=uses_anaphora,
            anaphora_token=anaphora_token,
            negated=negated,
        )

    # 13. Entities present (e.g., introducing candidates or unknown predicate) -> D05 setup or D18 unknown sense
    if entities and not predicates:
        # Check if it's an introduction of entities ("这里有甲架和乙架两份资料") vs unknown predicate query
        if stage_a.modality == "query":
            return StageBResult(
                intent="query",
                disambiguation="needs_clarification",
                alternatives=[],
                missing=[
                    MissingItem(
                        kind="unknown_sense",
                        detail="No known predicate sense matched in the active lexicon; refusing to invent a predicate.",
                        clarification_question="当前词典中未找到该问题对应的谓词义项，请换用已登记的表达或补充词义定义。",
                    )
                ],
                extra_spans=extra_spans,
                entities=entities,
                predicates=[],
                uses_anaphora=uses_anaphora,
                anaphora_token=anaphora_token,
            )
        return StageBResult(
            intent="context_introduction",
            disambiguation="not_applicable",
            alternatives=[],
            missing=[],
            extra_spans=extra_spans,
            entities=entities,
            predicates=[],
        )

    # 14. Completely unparsed / unknown concept
    return StageBResult(
        intent=stage_a.modality,
        disambiguation="needs_clarification",
        alternatives=[],
        missing=[
            MissingItem(
                kind="unknown_sense",
                detail="No supported predicate, arithmetic operator, or known entity matched in active lexicon.",
                clarification_question="当前受限词典无法解析该句的逻辑目标，请补充具体对象与可核查属性。",
            )
        ],
        extra_spans=extra_spans,
        entities=entities,
        predicates=predicates,
    )
