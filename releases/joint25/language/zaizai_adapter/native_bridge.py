"""Reference native Linux CLI bridge for CL / PCGM (adapter-side only).

IMPORTANT:
In this sandbox environment, the native Linux C++20 binaries (`cl`, `pcgm-alpha`,
`pcgm-beta`) and source tree are NOT present. This module constructs exact CLI
invocations and stdin payloads matching Section 5 of the specification so that
integrators with the Linux baseline can run them directly. It NEVER fabricates
native binary output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schema import DialogueCandidateRecord


def build_read_channel_proof_request(
    record: DialogueCandidateRecord,
    correlation_id: str = "p",
) -> Optional[str]:
    """Build a read-only `proof` stdin line for `./pcgm-alpha --read-channel STATE`.

    Only unique, ground-atom queries with `dispatch_target == 'read-channel:proof'`
    are eligible. Open-variable queries (e.g., qty_add with $result) are NEVER
    forced into the old ground-atom proof endpoint.
    """
    if record.disambiguation != "unique" or len(record.alternatives) != 1:
        return None
    cand = record.alternatives[0]
    if cand.dispatch_target != "read-channel:proof" or not cand.goal:
        return None
    if cand.variables:
        return None  # Open variables must NOT be sent to ground-atom proof

    pred = cand.goal["predicate"]
    args = [str(a["value"]) for a in cand.goal.get("arguments", [])]
    pol_prefix = "!" if cand.goal.get("polarity") == "negative" else ""
    atom = f"{pol_prefix}{pred}({', '.join(args)})"
    return f"{correlation_id} proof {atom}\n"


def build_basic_arithmetic_request(record: DialogueCandidateRecord) -> Optional[str]:
    """Build stdin line for the bounded arithmetic entry `./pcgm-alpha --ask-basic-arithmetic`."""
    if record.disambiguation != "unique" or len(record.alternatives) != 1:
        return None
    cand = record.alternatives[0]
    if cand.dispatch_target != "solver:qty_add":
        return None
    return f"{record.raw_text}\n"


def build_structured_chat_focus_request(record: DialogueCandidateRecord) -> Optional[str]:
    """Build a read-only `:chat SESSION TURN focus GOAL` line for `./pcgm-alpha --resume STATE`."""
    if record.disambiguation != "unique" or len(record.alternatives) != 1:
        return None
    cand = record.alternatives[0]
    if cand.dispatch_target != "read-channel:proof" or not cand.goal or cand.variables:
        return None
    pred = cand.goal["predicate"]
    args = [str(a["value"]) for a in cand.goal.get("arguments", [])]
    atom = f"{pred}({', '.join(args)})"
    return f":chat {record.session_id} {record.turn_id} focus {atom}\n"


def describe_native_interface_status() -> Dict[str, Any]:
    """Document which native interfaces exist vs. are proposed contracts."""
    return {
        "existing_native_interfaces": [
            "./cl check <file.cl>",
            "./pcgm-alpha --init-managed <file.cl> STATE",
            "./pcgm-alpha --read-channel STATE  (commands: proof, question, question_feed, storage)",
            "./pcgm-alpha --resume STATE        (:chat SESSION TURN focus GOAL|why|status|need|clear)",
            "./pcgm-alpha --ask-basic-arithmetic (bounded non-negative 2-operand integer addition)",
        ],
        "proposed_handoff_contracts": [
            "cl-dialogue-candidate-v1 (adapter output -> core intake)",
            "pcgm-reasoned-outcome-v1 (core output -> adapter mechanical renderer)",
        ],
        "core_only_responsibilities": [
            "Fact persistence, observation writes (:observe), and withdrawal execution (:withdraw)",
            "Question ticket creation, freeze-sheet verification, and crash reconciliation",
            "Authoritative proof evaluation and four-valued state revision",
        ],
        "native_executed_in_this_delivery": False,
    }
