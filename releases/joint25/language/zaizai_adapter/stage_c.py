"""Stage C: Multi-turn session context, anaphora disambiguation, non-destructive
corrections, targeted vs ambiguous retraction, idempotency, restart recovery,
and per-turn lexicon version pinning.

Key invariants:
- Recency != unique referent: when multiple candidate entities exist in session
  context, anaphora ("那它呢", "那它能读吗") keeps ALL viable alternatives and
  emits a minimal distinguishing question instead of picking the latest entity.
- Corrections create new records with `ref_utterance_id` edges; historical raw
  text bytes are NEVER overwritten or erased.
- Retraction with multiple matching records for the same entity & sense MUST NOT
  batch-retract or attach `retract_target_id`; it sets `disambiguation =
  "needs_clarification"` and `missing` with `ambiguous_retraction_target` +
  candidate/utterance IDs and asks only "要撤回哪条".
- Exact replay of `(session_id, turn_id, raw_text)` returns the exact prior
  result (`idempotent_replay=True`). Same `(session_id, turn_id)` with different
  `raw_text` is REJECTED (no silent overwrite).
- Restart recovery restores sessions AND per-turn `lexicon_version` so newer
  lexicon versions NEVER silently reinterpret older turns (D16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import re

from .lexicon import Lexicon, LexiconRegistry
from .schema import (
    AlternativeCandidate,
    BASELINE_SHA256,
    DialogueCandidateRecord,
    InputSpan,
    MissingItem,
)
from .stage_a import StageAResult, analyze_stage_a
from .stage_b import StageBResult, analyze_stage_b


_EXPLICIT_UTT_ID_RE = re.compile(r"\b((?:u|hu|obs_)[a-zA-Z0-9_]+|c\d+)\b")


@dataclass
class TurnHistoryEntry:
    utterance_id: str
    turn_id: str
    raw_text: str
    lexicon_version: str
    record_dict: Dict[str, Any]
    active: bool = True
    entity_symbols: List[str] = field(default_factory=list)
    predicate_senses: List[str] = field(default_factory=list)


@dataclass
class SessionState:
    session_id: str
    lexicon_version: str
    turns: Dict[str, TurnHistoryEntry] = field(default_factory=dict)  # keyed by turn_id
    turn_order: List[str] = field(default_factory=list)
    candidate_entities: List[Dict[str, Any]] = field(default_factory=list)
    active_focus: Optional[Dict[str, Any]] = None
    last_pending_retraction: Optional[List[Dict[str, str]]] = None
    last_pending_query_predicate: Optional[str] = None
    last_pending_query_sense_id: Optional[str] = None
    last_pending_query_polarity: str = "positive"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "lexicon_version": self.lexicon_version,
            "turn_order": self.turn_order,
            "turns": {
                tid: {
                    "utterance_id": e.utterance_id,
                    "turn_id": e.turn_id,
                    "raw_text": e.raw_text,
                    "lexicon_version": e.lexicon_version,
                    "record_dict": e.record_dict,
                    "active": e.active,
                    "entity_symbols": e.entity_symbols,
                    "predicate_senses": e.predicate_senses,
                }
                for tid, e in self.turns.items()
            },
            "candidate_entities": self.candidate_entities,
            "active_focus": self.active_focus,
            "last_pending_retraction": self.last_pending_retraction,
            "last_pending_query_predicate": self.last_pending_query_predicate,
            "last_pending_query_sense_id": self.last_pending_query_sense_id,
            "last_pending_query_polarity": self.last_pending_query_polarity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        st = cls(
            session_id=data["session_id"],
            lexicon_version=data["lexicon_version"],
            turn_order=list(data.get("turn_order", [])),
            candidate_entities=list(data.get("candidate_entities", [])),
            active_focus=data.get("active_focus"),
            last_pending_retraction=data.get("last_pending_retraction"),
            last_pending_query_predicate=data.get("last_pending_query_predicate"),
            last_pending_query_sense_id=data.get("last_pending_query_sense_id"),
            last_pending_query_polarity=data.get("last_pending_query_polarity", "positive"),
        )
        for tid, raw_e in data.get("turns", {}).items():
            st.turns[tid] = TurnHistoryEntry(
                utterance_id=raw_e["utterance_id"],
                turn_id=raw_e["turn_id"],
                raw_text=raw_e["raw_text"],
                lexicon_version=raw_e["lexicon_version"],
                record_dict=raw_e["record_dict"],
                active=raw_e.get("active", True),
                entity_symbols=list(raw_e.get("entity_symbols", [])),
                predicate_senses=list(raw_e.get("predicate_senses", [])),
            )
        return st


class DialogueAdapter:
    """Stateful Chinese-to-CL dialogue adapter implementing Stages A, B, and C."""

    def __init__(
        self,
        registry: LexiconRegistry,
        default_lexicon_version: str,
        baseline_sha256: str = BASELINE_SHA256,
    ) -> None:
        self.registry = registry
        self.default_lexicon_version = default_lexicon_version
        self.baseline_sha256 = baseline_sha256
        # Validate default lexicon exists immediately (fail-closed)
        self.registry.get(default_lexicon_version)
        self.sessions: Dict[str, SessionState] = {}

    def _get_or_create_session(self, session_id: str, lex_version: str) -> SessionState:
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(
                session_id=session_id,
                lexicon_version=lex_version,
            )
        return self.sessions[session_id]

    def save_state(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "zaizai-adapter-state-v1",
            "baseline_sha256": self.baseline_sha256,
            "default_lexicon_version": self.default_lexicon_version,
            "sessions": {sid: s.to_dict() for sid, s in self.sessions.items()},
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_state(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        self.sessions = {
            sid: SessionState.from_dict(sdata)
            for sid, sdata in data.get("sessions", {}).items()
        }

    def get_historical_turn(self, session_id: str, turn_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a historical turn's frozen interpretation under its original lexicon version (D16)."""
        session = self.sessions.get(session_id)
        if not session or turn_id not in session.turns:
            return None
        return dict(session.turns[turn_id].record_dict)

    def process_utterance(
        self,
        raw_text: str,
        *,
        case_id: str = "ad-hoc",
        utterance_id: str = "u1",
        session_id: str = "s1",
        turn_id: str = "t1",
        locale: str = "zh-CN",
        lexicon_version: Optional[str] = None,
    ) -> DialogueCandidateRecord:
        active_lex_version = lexicon_version or self.default_lexicon_version
        lexicon = self.registry.get(active_lex_version)  # fail-closed if missing/invalid
        session = self._get_or_create_session(session_id, active_lex_version)

        # D11: Idempotency & overwrite rejection on same (session_id, turn_id)
        if turn_id in session.turns:
            prev = session.turns[turn_id]
            if prev.raw_text == raw_text:
                # Exact resend -> return exact prior result with idempotent_replay=True
                d = dict(prev.record_dict)
                return DialogueCandidateRecord(
                    case_id=d["case_id"],
                    utterance_id=d["utterance_id"],
                    session_id=d["session_id"],
                    turn_id=d["turn_id"],
                    locale=d["locale"],
                    raw_text=d["raw_text"],
                    input_spans=[InputSpan(**sp) for sp in d["input_spans"]],
                    intent=d["intent"],
                    lexicon_version=d["lexicon_version"],
                    disambiguation=d["disambiguation"],
                    alternatives=[AlternativeCandidate(**a) for a in d["alternatives"]],
                    missing=[MissingItem(**m) for m in d["missing"]],
                    source_refs=list(d.get("source_refs", [])),
                    baseline_sha256=d["baseline_sha256"],
                    retract_target_id=d.get("retract_target_id"),
                    ref_utterance_id=d.get("ref_utterance_id"),
                    attribution=d.get("attribution"),
                    idempotent_replay=True,
                )
            # Same turn_id with DIFFERENT raw_text -> reject silent overwrite!
            return DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=raw_text,
                input_spans=[],
                intent="rejected_turn_conflict",
                lexicon_version=active_lex_version,
                disambiguation="rejected",
                alternatives=[],
                missing=[
                    MissingItem(
                        kind="turn_id_conflict",
                        detail=(
                            f"Turn '{turn_id}' in session '{session_id}' already exists with different raw_text "
                            f"(existing utterance_id={prev.utterance_id}). Silent overwrite is forbidden."
                        ),
                        utterance_ids=[prev.utterance_id],
                        clarification_question=(
                            f"轮次 {turn_id} 已有不同原句记录（{prev.utterance_id}），不允许覆盖；"
                            "请分配新的 turn_id 或发送一条修正记录。"
                        ),
                    )
                ],
                source_refs=[f"utterance:{utterance_id}", f"conflict_with:{prev.utterance_id}"],
                baseline_sha256=self.baseline_sha256,
            )

        # Stage A & Stage B
        stage_a = analyze_stage_a(raw_text)
        stage_b = analyze_stage_b(stage_a, utterance_id, lexicon)

        all_spans = sorted(
            stage_a.spans + stage_b.extra_spans,
            key=lambda s: (s.start, s.end, s.kind),
        )
        source_refs = [f"utterance:{utterance_id}"]
        if stage_a.injection_detected:
            source_refs.append("guard:prompt_injection_inert")

        record: DialogueCandidateRecord

        # --- Stage C Branch 1: Retraction (D10) ---
        if stage_b.intent == "retraction":
            record = self._handle_retraction(
                session=session,
                stage_a=stage_a,
                stage_b=stage_b,
                all_spans=all_spans,
                case_id=case_id,
                utterance_id=utterance_id,
                turn_id=turn_id,
                locale=locale,
                lexicon=lexicon,
                source_refs=source_refs,
            )

        # --- Stage C Branch 2: Correction / Sense Disambiguation (D06) ---
        elif stage_b.intent == "correction":
            record = self._handle_correction(
                session=session,
                stage_a=stage_a,
                stage_b=stage_b,
                all_spans=all_spans,
                case_id=case_id,
                utterance_id=utterance_id,
                turn_id=turn_id,
                locale=locale,
                lexicon=lexicon,
                source_refs=source_refs,
            )

        # --- Stage C Branch 3: Anaphora resolution (D05 & D14) ---
        elif (
            stage_b.uses_anaphora
            and not stage_b.entities
            and not stage_b.alternatives
            and (stage_b.predicates or stage_b.intent == "query_conflict_status")
        ):
            record = self._handle_anaphora(
                session=session,
                stage_a=stage_a,
                stage_b=stage_b,
                all_spans=all_spans,
                case_id=case_id,
                utterance_id=utterance_id,
                turn_id=turn_id,
                locale=locale,
                lexicon=lexicon,
                source_refs=source_refs,
            )

        # --- Stage C Branch 4: Default direct record ---
        else:
            record = DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=raw_text,
                input_spans=all_spans,
                intent=stage_b.intent,
                lexicon_version=lexicon.version,
                disambiguation=stage_b.disambiguation,
                alternatives=stage_b.alternatives,
                missing=stage_b.missing,
                source_refs=source_refs,
                baseline_sha256=self.baseline_sha256,
                attribution=stage_a.speaker_attribution,
            )

        # Persist turn into session history (immutable raw_text & pinned lexicon_version)
        ent_syms: List[str] = []
        for ent in stage_b.entities:
            if ent.senses:
                for s in ent.senses:
                    ent_syms.append(s.canonical)
                    self._register_candidate_entity(session, s.canonical, s.sense_id, ent.surface, utterance_id)
            elif ent.novel_symbol:
                ent_syms.append(ent.novel_symbol)
                self._register_candidate_entity(session, ent.novel_symbol, None, ent.surface, utterance_id)

        pred_senses = [p.sense_id for p in stage_b.predicates]
        if len(ent_syms) == 1 and stage_b.intent in ("query", "assertion", "correction"):
            session.active_focus = {
                "symbol": ent_syms[0],
                "utterance_id": utterance_id,
            }

        session.turns[turn_id] = TurnHistoryEntry(
            utterance_id=utterance_id,
            turn_id=turn_id,
            raw_text=raw_text,
            lexicon_version=lexicon.version,
            record_dict=record.to_dict(),
            active=True,
            entity_symbols=ent_syms,
            predicate_senses=pred_senses,
        )
        session.turn_order.append(turn_id)
        return record

    def _register_candidate_entity(
        self,
        session: SessionState,
        symbol: str,
        sense_id: Optional[str],
        surface: str,
        utterance_id: str,
    ) -> None:
        for existing in session.candidate_entities:
            if existing["symbol"] == symbol:
                existing["last_utterance_id"] = utterance_id
                return
        session.candidate_entities.append(
            {
                "symbol": symbol,
                "sense_id": sense_id,
                "surface": surface,
                "last_utterance_id": utterance_id,
            }
        )

    def _handle_anaphora(
        self,
        *,
        session: SessionState,
        stage_a: StageAResult,
        stage_b: StageBResult,
        all_spans: List[InputSpan],
        case_id: str,
        utterance_id: str,
        turn_id: str,
        locale: str,
        lexicon: Lexicon,
        source_refs: List[str],
    ) -> DialogueCandidateRecord:
        candidates = list(session.candidate_entities)
        polarity = "negative" if stage_b.negated else "positive"

        # Special handling for "另一个呢" -> exclude current active focus if known
        if stage_b.anaphora_token in ("另一个", "另外那份") and session.active_focus:
            candidates = [c for c in candidates if c["symbol"] != session.active_focus["symbol"]]

        # Determine predicate (from current turn or previous query predicate)
        pred_canonical = stage_b.predicates[0].canonical if stage_b.predicates else session.last_pending_query_predicate
        pred_sid = stage_b.predicates[0].sense_id if stage_b.predicates else session.last_pending_query_sense_id

        if stage_b.intent == "query_conflict_status":
            if session.active_focus and pred_canonical:
                sym = session.active_focus["symbol"]
                cand = AlternativeCandidate(
                    candidate_id="c1",
                    goal={
                        "predicate": pred_canonical,
                        "polarity": "positive",
                        "arguments": [{"type": "sym", "value": sym}],
                    },
                    variables=[],
                    sense_ids=[pred_sid] if pred_sid else [],
                    source_refs=source_refs + [f"focus:{session.active_focus['utterance_id']}"],
                    premises=[],
                    dispatch_target="read-channel:proof",
                    polarity="positive",
                    metadata={"preserve_conflict_branches": True},
                )
                return DialogueCandidateRecord(
                    case_id=case_id,
                    utterance_id=utterance_id,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    locale=locale,
                    raw_text=stage_a.raw_text,
                    input_spans=all_spans,
                    intent="query",
                    lexicon_version=lexicon.version,
                    disambiguation="unique",
                    alternatives=[cand],
                    missing=[],
                    source_refs=source_refs,
                    baseline_sha256=self.baseline_sha256,
                )

        if not candidates:
            return DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session.session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=stage_a.raw_text,
                input_spans=all_spans,
                intent="query",
                lexicon_version=lexicon.version,
                disambiguation="needs_clarification",
                alternatives=[],
                missing=[
                    MissingItem(
                        kind="missing_referent",
                        detail=f"Anaphora '{stage_b.anaphora_token}' has no candidate entity in session context.",
                        clarification_question=f"请问「{stage_b.anaphora_token}」指的是哪一个具体对象？",
                    )
                ],
                source_refs=source_refs,
                baseline_sha256=self.baseline_sha256,
            )

        # Remember predicate for potential follow-up disambiguation turn (D06)
        if pred_canonical:
            session.last_pending_query_predicate = pred_canonical
            session.last_pending_query_sense_id = pred_sid
            session.last_pending_query_polarity = polarity

        # Build an alternative for EVERY viable candidate (never pick recency blindly!)
        alts: List[AlternativeCandidate] = []
        for idx, c in enumerate(candidates, start=1):
            sids = ([pred_sid] if pred_sid else []) + ([c["sense_id"]] if c.get("sense_id") else [])
            refs = list(source_refs) + [f"context_entity:{c['last_utterance_id']}"]
            for s in sids:
                refs.append(f"lexicon:{lexicon.version}#{s}")
            alts.append(
                AlternativeCandidate(
                    candidate_id=f"c{idx}",
                    goal={
                        "predicate": pred_canonical or "unknown",
                        "polarity": polarity,
                        "arguments": [{"type": "sym", "value": c["symbol"]}],
                    },
                    variables=[],
                    sense_ids=sids,
                    source_refs=refs,
                    premises=[],
                    dispatch_target="read-channel:proof" if len(candidates) == 1 else "none",
                    polarity=polarity,
                    metadata={"surface": c["surface"]},
                )
            )

        if len(alts) == 1:
            return DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session.session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=stage_a.raw_text,
                input_spans=all_spans,
                intent="query",
                lexicon_version=lexicon.version,
                disambiguation="unique",
                alternatives=alts,
                missing=[],
                source_refs=source_refs,
                baseline_sha256=self.baseline_sha256,
            )

        # Multiple candidates -> ambiguous, MUST ask minimal distinguishing question
        choices_str = " 还是 ".join(f"{c['surface']}({c['symbol']})" for c in candidates)
        return DialogueCandidateRecord(
            case_id=case_id,
            utterance_id=utterance_id,
            session_id=session.session_id,
            turn_id=turn_id,
            locale=locale,
            raw_text=stage_a.raw_text,
            input_spans=all_spans,
            intent="query",
            lexicon_version=lexicon.version,
            disambiguation="ambiguous",
            alternatives=alts,
            missing=[
                MissingItem(
                    kind="ambiguous_referent",
                    detail=f"Anaphora '{stage_b.anaphora_token}' matches {len(candidates)} candidate entities; recency is not treated as unique referent.",
                    candidate_ids=[a.candidate_id for a in alts],
                    clarification_question=f"请问「{stage_b.anaphora_token}」指的是 {choices_str}？",
                )
            ],
            source_refs=source_refs,
            baseline_sha256=self.baseline_sha256,
        )

    def _handle_correction(
        self,
        *,
        session: SessionState,
        stage_a: StageAResult,
        stage_b: StageBResult,
        all_spans: List[InputSpan],
        case_id: str,
        utterance_id: str,
        turn_id: str,
        locale: str,
        lexicon: Lexicon,
        source_refs: List[str],
    ) -> DialogueCandidateRecord:
        # Handle "我指 X，不是 Y" (D06): split around "不是" so excluded entity is not chosen
        uv = stage_a.unquoted_view
        pos_part = re.split(r"[,，]?\s*不是", uv, maxsplit=1)[0]
        chosen_entity = None
        for ent in stage_b.entities:
            if ent.char_start < len(pos_part):
                chosen_entity = ent
                break

        prev_utt_id = (
            session.turns[session.turn_order[-1]].utterance_id if session.turn_order else None
        )

        if chosen_entity is None:
            return DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session.session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=stage_a.raw_text,
                input_spans=all_spans,
                intent="correction",
                lexicon_version=lexicon.version,
                disambiguation="needs_clarification",
                alternatives=[],
                missing=[
                    MissingItem(
                        kind="missing_correction_target",
                        detail="Could not identify the intended target entity/sense in the correction.",
                        clarification_question="请指明您更正后的具体对象或义项。",
                    )
                ],
                source_refs=source_refs,
                baseline_sha256=self.baseline_sha256,
                ref_utterance_id=prev_utt_id,
            )

        sym = chosen_entity.senses[0].canonical if chosen_entity.senses else (chosen_entity.novel_symbol or chosen_entity.surface)
        ent_sid = chosen_entity.senses[0].sense_id if chosen_entity.senses else None
        session.active_focus = {"symbol": sym, "utterance_id": utterance_id}

        pred = session.last_pending_query_predicate or "focus"
        pred_sid = session.last_pending_query_sense_id
        sids = ([pred_sid] if pred_sid else []) + ([ent_sid] if ent_sid else [])
        cand = AlternativeCandidate(
            candidate_id="c1",
            goal={
                "predicate": pred,
                "polarity": session.last_pending_query_polarity,
                "arguments": [{"type": "sym", "value": sym}],
            },
            variables=[],
            sense_ids=sids,
            source_refs=source_refs
            + ([f"supersedes:{prev_utt_id}"] if prev_utt_id else [])
            + [f"lexicon:{lexicon.version}#{s}" for s in sids],
            premises=[],
            dispatch_target="read-channel:proof" if pred != "focus" else "none",
            polarity=session.last_pending_query_polarity,
            metadata={"non_destructive_correction": True},
        )
        return DialogueCandidateRecord(
            case_id=case_id,
            utterance_id=utterance_id,
            session_id=session.session_id,
            turn_id=turn_id,
            locale=locale,
            raw_text=stage_a.raw_text,
            input_spans=all_spans,
            intent="correction",
            lexicon_version=lexicon.version,
            disambiguation="unique",
            alternatives=[cand],
            missing=[],
            source_refs=source_refs,
            baseline_sha256=self.baseline_sha256,
            ref_utterance_id=prev_utt_id,
        )

    def _handle_retraction(
        self,
        *,
        session: SessionState,
        stage_a: StageAResult,
        stage_b: StageBResult,
        all_spans: List[InputSpan],
        case_id: str,
        utterance_id: str,
        turn_id: str,
        locale: str,
        lexicon: Lexicon,
        source_refs: List[str],
    ) -> DialogueCandidateRecord:
        # 1. Check if user explicitly named an utterance_id / record_id (e.g., "撤回 u1")
        explicit_m = _EXPLICIT_UTT_ID_RE.search(stage_a.unquoted_view)
        if explicit_m:
            target_id = explicit_m.group(1)
            # Find matching active turn
            matched_entry = None
            for tid in session.turn_order:
                ent = session.turns[tid]
                if ent.active and ent.utterance_id == target_id:
                    matched_entry = ent
                    break
            if matched_entry is not None:
                matched_entry.active = False
                session.last_pending_retraction = None
                cand = AlternativeCandidate(
                    candidate_id="c1",
                    goal={
                        "predicate": "retract_proposal",
                        "polarity": "positive",
                        "arguments": [{"type": "record_id", "value": target_id}],
                    },
                    variables=[],
                    sense_ids=[],
                    source_refs=source_refs + [f"retract_target:{target_id}"],
                    premises=[],
                    dispatch_target="proposal:withdraw",
                    metadata={"requires_core_authorization": True},
                )
                return DialogueCandidateRecord(
                    case_id=case_id,
                    utterance_id=utterance_id,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    locale=locale,
                    raw_text=stage_a.raw_text,
                    input_spans=all_spans,
                    intent="retraction",
                    lexicon_version=lexicon.version,
                    disambiguation="unique",
                    alternatives=[cand],
                    missing=[],
                    source_refs=source_refs,
                    baseline_sha256=self.baseline_sha256,
                    retract_target_id=target_id,
                )

        # 2. Otherwise collect all active assertion/observation turns in session
        active_obs = [
            session.turns[tid]
            for tid in session.turn_order
            if session.turns[tid].active
            and session.turns[tid].record_dict.get("intent") == "assertion"
        ]

        # Group by (entity_symbols, predicate_senses) matching the most recent observation
        if not active_obs:
            return DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session.session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=stage_a.raw_text,
                input_spans=all_spans,
                intent="retraction",
                lexicon_version=lexicon.version,
                disambiguation="needs_clarification",
                alternatives=[],
                missing=[
                    MissingItem(
                        kind="missing_retraction_target",
                        detail="No active assertion/observation record exists in this session to retract.",
                        clarification_question="当前会话中没有可撤回的已登记记录，请确认记录编号。",
                    )
                ],
                source_refs=source_refs,
                baseline_sha256=self.baseline_sha256,
            )

        latest = active_obs[-1]
        same_group = [
            e
            for e in active_obs
            if e.entity_symbols == latest.entity_symbols
            and e.predicate_senses == latest.predicate_senses
        ]

        if len(same_group) == 1:
            target = same_group[0]
            target.active = False
            cand = AlternativeCandidate(
                candidate_id="c1",
                goal={
                    "predicate": "retract_proposal",
                    "polarity": "positive",
                    "arguments": [{"type": "record_id", "value": target.utterance_id}],
                },
                variables=[],
                sense_ids=target.predicate_senses,
                source_refs=source_refs + [f"retract_target:{target.utterance_id}"],
                premises=[],
                dispatch_target="proposal:withdraw",
                metadata={"requires_core_authorization": True},
            )
            return DialogueCandidateRecord(
                case_id=case_id,
                utterance_id=utterance_id,
                session_id=session.session_id,
                turn_id=turn_id,
                locale=locale,
                raw_text=stage_a.raw_text,
                input_spans=all_spans,
                intent="retraction",
                lexicon_version=lexicon.version,
                disambiguation="unique",
                alternatives=[cand],
                missing=[],
                source_refs=source_refs,
                baseline_sha256=self.baseline_sha256,
                retract_target_id=target.utterance_id,
            )

        # Multiple records for same entity & sense -> ACC-17 / D10: MUST NOT batch-retract!
        alts: List[AlternativeCandidate] = []
        cand_ids: List[str] = []
        utt_ids: List[str] = []
        for idx, entry in enumerate(same_group, start=1):
            cid = f"c{idx}"
            cand_ids.append(cid)
            utt_ids.append(entry.utterance_id)
            alts.append(
                AlternativeCandidate(
                    candidate_id=cid,
                    goal={
                        "predicate": "retract_proposal",
                        "polarity": "positive",
                        "arguments": [{"type": "record_id", "value": entry.utterance_id}],
                    },
                    variables=[],
                    sense_ids=entry.predicate_senses,
                    source_refs=source_refs + [f"candidate_record:{entry.utterance_id}"],
                    premises=[],
                    dispatch_target="none",
                    metadata={"raw_text": entry.raw_text, "turn_id": entry.turn_id},
                )
            )
        session.last_pending_retraction = [
            {"candidate_id": cid, "utterance_id": uid}
            for cid, uid in zip(cand_ids, utt_ids)
        ]
        listing = " / ".join(f"{cid}({uid})" for cid, uid in zip(cand_ids, utt_ids))
        return DialogueCandidateRecord(
            case_id=case_id,
            utterance_id=utterance_id,
            session_id=session.session_id,
            turn_id=turn_id,
            locale=locale,
            raw_text=stage_a.raw_text,
            input_spans=all_spans,
            intent="retraction",
            lexicon_version=lexicon.version,
            disambiguation="needs_clarification",
            alternatives=alts,
            missing=[
                MissingItem(
                    kind="ambiguous_retraction_target",
                    detail=(
                        f"Multiple records ({len(same_group)}) match the same entity & sense; "
                        "batch retraction is forbidden and no retract_target_id is attached."
                    ),
                    candidate_ids=cand_ids,
                    utterance_ids=utt_ids,
                    clarification_question=f"要撤回哪条？候选记录：{listing}",
                )
            ],
            source_refs=source_refs,
            baseline_sha256=self.baseline_sha256,
            retract_target_id=None,  # Explicitly omitted when ambiguous!
        )
