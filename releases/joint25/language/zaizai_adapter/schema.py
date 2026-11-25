"""Shared protocol schemas for cl-dialogue-candidate-v1 and PCGM outcomes.

This module defines the handoff contract emitted by the Chinese-to-CL adapter.
The adapter ONLY emits read-only candidates and proposals; it holds zero write
authority over PCGM facts, memory, or retractions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import json

BASELINE_SHA256 = "9e456752f08769fb3757c21665587c847ec3104a87be7b4fb306bee892af2f31"
CANDIDATE_SCHEMA = "cl-dialogue-candidate-v1"
OUTCOME_SCHEMA = "pcgm-reasoned-outcome-v1"
PROOF_SCHEMA = "cl-proof-v1"
LEXICON_SCHEMA = "cl-lexicon-sense-v1"
SOURCE_OBS_SCHEMA = "cl-source-observation-v1"


def char_span_to_utf8_span(text: str, char_start: int, char_end: int) -> tuple[int, int]:
    """Convert Python str character indices to UTF-8 half-open byte offsets."""
    if char_start < 0 or char_end < char_start or char_end > len(text):
        raise ValueError(f"Invalid character span [{char_start}, {char_end}) for len={len(text)}")
    byte_start = len(text[:char_start].encode("utf-8"))
    byte_end = byte_start + len(text[char_start:char_end].encode("utf-8"))
    return byte_start, byte_end


@dataclass
class InputSpan:
    start: int  # UTF-8 byte start (inclusive)
    end: int    # UTF-8 byte end (exclusive)
    kind: str
    raw_bytes_utf8: Optional[str] = None
    normalized: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "kind": self.kind,
        }
        if self.raw_bytes_utf8 is not None:
            d["raw_bytes_utf8"] = self.raw_bytes_utf8
        if self.normalized is not None:
            d["normalized"] = self.normalized
        return d


@dataclass
class AlternativeCandidate:
    candidate_id: str
    goal: Optional[Dict[str, Any]]
    variables: List[Dict[str, Any]] = field(default_factory=list)
    sense_ids: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)
    premises: List[Dict[str, Any]] = field(default_factory=list)
    dispatch_target: str = "none"
    candidate_source: str = "deterministic_grammar"
    polarity: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "goal": self.goal,
            "variables": self.variables,
            "sense_ids": self.sense_ids,
            "source_refs": self.source_refs,
            "premises": self.premises,
            "dispatch_target": self.dispatch_target,
            "candidate_source": self.candidate_source,
        }
        if self.polarity is not None:
            d["polarity"] = self.polarity
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class MissingItem:
    kind: str
    detail: str
    span: Optional[Dict[str, int]] = None
    candidate_ids: List[str] = field(default_factory=list)
    utterance_ids: List[str] = field(default_factory=list)
    clarification_question: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "kind": self.kind,
            "detail": self.detail,
        }
        if self.span is not None:
            d["span"] = self.span
        if self.candidate_ids:
            d["candidate_ids"] = self.candidate_ids
        if self.utterance_ids:
            d["utterance_ids"] = self.utterance_ids
        if self.clarification_question is not None:
            d["clarification_question"] = self.clarification_question
        return d


@dataclass
class DialogueCandidateRecord:
    case_id: str
    utterance_id: str
    session_id: str
    turn_id: str
    locale: str
    raw_text: str
    input_spans: List[InputSpan]
    intent: str
    lexicon_version: str
    disambiguation: str  # "unique" | "ambiguous" | "needs_clarification" | "not_applicable" | "rejected"
    alternatives: List[AlternativeCandidate] = field(default_factory=list)
    missing: List[MissingItem] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)
    baseline_sha256: str = BASELINE_SHA256
    schema: str = CANDIDATE_SCHEMA
    retract_target_id: Optional[str] = None
    ref_utterance_id: Optional[str] = None
    attribution: Optional[Dict[str, Any]] = None
    idempotent_replay: bool = False
    write_authority: str = "none_proposal_only"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "schema": self.schema,
            "case_id": self.case_id,
            "utterance_id": self.utterance_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "locale": self.locale,
            "raw_text": self.raw_text,
            "baseline_sha256": self.baseline_sha256,
            "input_spans": [s.to_dict() for s in self.input_spans],
            "intent": self.intent,
            "lexicon_version": self.lexicon_version,
            "disambiguation": self.disambiguation,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "missing": [m.to_dict() for m in self.missing],
            "source_refs": self.source_refs,
            "write_authority": self.write_authority,
        }
        if self.retract_target_id is not None:
            d["retract_target_id"] = self.retract_target_id
        if self.ref_utterance_id is not None:
            d["ref_utterance_id"] = self.ref_utterance_id
        if self.attribution is not None:
            d["attribution"] = self.attribution
        if self.idempotent_replay:
            d["idempotent_replay"] = True
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
