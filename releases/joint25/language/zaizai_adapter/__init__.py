"""Zaizai Chinese-to-CL Dialogue Adapter (standalone runnable handoff package)."""

from .schema import (
    BASELINE_SHA256,
    CANDIDATE_SCHEMA,
    OUTCOME_SCHEMA,
    PROOF_SCHEMA,
    DialogueCandidateRecord,
    char_span_to_utf8_span,
)
from .lexicon import Lexicon, LexiconRegistry, LexiconVersionError
from .stage_a import analyze_stage_a, parse_chinese_nonneg_int
from .stage_b import analyze_stage_b
from .stage_c import DialogueAdapter
from .stage_d import (
    aggregate_four_value,
    combine_four_values,
    deduplicate_reprint_sources,
    project_cl_proof_v1,
    render_reasoned_outcome,
)
from .native_bridge import (
    build_basic_arithmetic_request,
    build_read_channel_proof_request,
    build_structured_chat_focus_request,
    describe_native_interface_status,
)

__all__ = [
    "BASELINE_SHA256",
    "CANDIDATE_SCHEMA",
    "OUTCOME_SCHEMA",
    "PROOF_SCHEMA",
    "DialogueCandidateRecord",
    "char_span_to_utf8_span",
    "Lexicon",
    "LexiconRegistry",
    "LexiconVersionError",
    "analyze_stage_a",
    "parse_chinese_nonneg_int",
    "analyze_stage_b",
    "DialogueAdapter",
    "aggregate_four_value",
    "combine_four_values",
    "deduplicate_reprint_sources",
    "project_cl_proof_v1",
    "render_reasoned_outcome",
    "build_basic_arithmetic_request",
    "build_read_channel_proof_request",
    "build_structured_chat_focus_request",
    "describe_native_interface_status",
]
