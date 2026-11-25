"""Bounded read-only adapter.

Turns a pinned fixture into `cl-source-observation-v1` candidate records and a
separate failure list. Page text is data. It is not a command, a permission,
or a PCGM write. Live fetch is closed until a human wires it at deploy time.
"""

import hashlib
import json
from pathlib import Path

from .classify import (
    BASELINE_VERSION,
    FAILURE_SCHEMA,
    OBSERVATION_SCHEMA,
    confidence_basis,
    lineage_refs,
    lineage_status,
    permissions,
    record_to_source,
)

DEFAULT_MAX_BODY = 4096
DEFAULT_TIMEOUT_S = 2.0
DEFAULT_MAX_FIXTURE = 262144

# There is no upload call in this module. The checker reads this value.
UPLOAD_ATTEMPTS = 0

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "SOURCE"


class FixtureBoundError(ValueError):
    pass


class LiveFetchNotAuthorized(OSError):
    def __init__(self):
        super().__init__("live network fetch is not wired")


class TransportFailure(Exception):
    def __init__(self, kind, reason, detail=None):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason
        self.detail = detail


class Limits(object):
    def __init__(self, max_body_bytes=DEFAULT_MAX_BODY, timeout_s=DEFAULT_TIMEOUT_S,
                 max_fixture_bytes=DEFAULT_MAX_FIXTURE):
        self.max_body_bytes = max_body_bytes
        self.timeout_s = timeout_s
        self.max_fixture_bytes = max_fixture_bytes


class AdaptResult(object):
    def __init__(self, candidates, failures, sources, fetch_attempts):
        self.candidates = candidates
        self.failures = failures
        self.sources = sources
        self.fetch_attempts = fetch_attempts
        self.upload_attempts = UPLOAD_ATTEMPTS
        self.commands_executed = 0
        self.source_writes = 0


def digest_hex(body):
    """SHA-256 of the body bytes only."""
    return hashlib.sha256(body).hexdigest()


def dumps_line(obj):
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def candidate_bytes(candidates):
    return b"".join(dumps_line(row) for row in candidates)


def failure_bytes(failures):
    return b"".join(dumps_line(row) for row in failures)


def default_fetch(locator, timeout_s, max_bytes):
    """Closed network path. The locator is not opened and nothing is uploaded."""
    del locator, timeout_s, max_bytes
    raise LiveFetchNotAuthorized()


def load_fixture(path, max_bytes=DEFAULT_MAX_FIXTURE):
    raw = Path(path).read_bytes()
    if len(raw) > max_bytes:
        raise FixtureBoundError("fixture exceeds the byte bound")
    return json.loads(raw.decode("utf-8"))


def refuse_source_write(path):
    resolved = Path(path).resolve()
    root = SOURCE_ROOT.resolve()
    if resolved == root or root in resolved.parents:
        raise PermissionError("refusing to write under SOURCE")


def _hex64(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def schema_problem(record):
    if not isinstance(record.get("evidence_id"), str) or not record["evidence_id"]:
        return "evidence_id is missing"
    if not isinstance(record.get("source_id"), str) or not record["source_id"]:
        return "source_id is missing"
    if not isinstance(record.get("source_identifier"), str) or not record["source_identifier"]:
        return "source_identifier is missing"
    if record.get("polarity") not in ("supports", "opposes"):
        return "polarity is not supports or opposes"
    if not isinstance(record.get("endpoint_mismatch"), bool):
        return "endpoint_mismatch is not a boolean"
    replaced = record.get("supersedes")
    if not isinstance(replaced, list) or any(
        not isinstance(item, str) or not item for item in replaced
    ):
        return "supersedes is not a source_id array"
    derived = record.get("derived_from", None)
    if "derived_from" not in record:
        return "derived_from is missing"
    if derived is None:
        pass
    elif not isinstance(derived, list) or any(
        not isinstance(item, str) or not item for item in derived
    ):
        return "derived_from is neither a source_id array nor null"
    if "source_family_id" not in record:
        return "source_family_id is missing"
    family = record.get("source_family_id")
    if family is not None and not isinstance(family, str):
        return "source_family_id is not a string or null"
    if not isinstance(record.get("endpoint_scope"), str):
        return "endpoint_scope is missing"
    if not isinstance(record.get("canonical_locator"), str):
        return "canonical_locator is missing"
    if not isinstance(record.get("retrieved_at"), str) or not record["retrieved_at"]:
        return "retrieved_at is missing"
    status = record.get("review_status", "recorded")
    if status not in ("recorded", "withdrawn", "invalid"):
        return "review_status is outside the contract"
    transport = record.get("transport")
    if not isinstance(transport, dict) or not isinstance(transport.get("kind"), str):
        return "transport is missing"
    return None


def classify_transport_exception(exc):
    """Map a transport exception. The message text does not choose the kind."""
    if isinstance(exc, TimeoutError):
        return ("network_failure", "bounded read timed out", str(exc))
    if isinstance(exc, ConnectionError):
        return ("network_failure", "connection failed", str(exc))
    if isinstance(exc, OSError):
        text = str(exc) or "network read failed"
        return ("network_failure", text, text)
    return ("network_failure", "network read failed", str(exc))


def _fail(case, record, kind, reason, detail=None):
    row = {
        "baseline_version": BASELINE_VERSION,
        "candidate_emitted": False,
        "case_id": case.get("case_id"),
        "failure_kind": kind,
        "passed": False,
        "reason": reason,
        "schema": FAILURE_SCHEMA,
        "source_id": record.get("source_id"),
        "source_identifier": record.get("source_identifier"),
    }
    if detail:
        row["detail"] = detail
    return {"failure": row, "candidate": None, "source": None}


def extract_observation(body):
    """Parse a pinned CLSRC1 body. Values stay data; nothing is executed."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.startswith("CLSRC1\n"):
        return None
    fields = {}
    for line in text.split("\n")[1:]:
        if line == "":
            continue
        if "=" not in line:
            return None
        key, value = line.split("=", 1)
        if not key or key in fields:
            return None
        fields[key] = value
    for key in ("source_id", "polarity", "endpoint_scope", "family"):
        if not fields.get(key):
            return None
    if fields["polarity"] not in ("supports", "opposes"):
        return None
    return fields


def _raise_scripted_transport(error_class, message):
    if error_class == "timeout":
        raise TimeoutError(message)
    if error_class == "connection":
        raise ConnectionError(message)
    raise OSError(message)


def acquire(record, fetch, limits, fetch_counter):
    transport = record["transport"]
    kind = transport["kind"]
    if kind == "offline_citation":
        return ("citation", None)
    if kind == "bytes":
        hex_body = transport.get("body_hex")
        if (
            not isinstance(hex_body, str)
            or (len(hex_body) % 2)
            or any(char not in "0123456789abcdef" for char in hex_body)
        ):
            raise TransportFailure("extraction_failure", "body_hex is not valid hex")
        if len(hex_body) // 2 > limits.max_body_bytes:
            raise TransportFailure("input_bound", "body exceeds the byte bound")
        return ("bytes", bytes.fromhex(hex_body))
    if kind == "error":
        message = transport.get("message") or "transport error"
        try:
            _raise_scripted_transport(transport.get("error_class"), message)
        except OSError as exc:
            kind_name, reason, detail = classify_transport_exception(exc)
            raise TransportFailure(kind_name, reason, detail) from None
    if kind == "live":
        fetch_counter[0] += 1
        try:
            body = fetch(
                record.get("canonical_locator") or "",
                limits.timeout_s,
                limits.max_body_bytes,
            )
        except OSError as exc:
            kind_name, reason, detail = classify_transport_exception(exc)
            raise TransportFailure(kind_name, reason, detail) from None
        if not isinstance(body, (bytes, bytearray)):
            raise TransportFailure("extraction_failure", "live fetch did not return bytes")
        if len(body) > limits.max_body_bytes:
            raise TransportFailure("input_bound", "body exceeds the byte bound")
        return ("bytes", bytes(body))
    if kind == "unavailable":
        reason = transport.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise TransportFailure("extraction_failure", "unobtainable row missing a reason")
        raise TransportFailure("unobtainable", reason.strip())
    raise TransportFailure("extraction_failure", "transport kind is not supported")


def _case_problem(case):
    if not isinstance(case.get("case_id"), str) or not case["case_id"]:
        return "case_id is missing"
    if not isinstance(case.get("claim_id"), str) or not case["claim_id"]:
        return "claim_id is missing"
    if case.get("baseline_version") != BASELINE_VERSION:
        return "baseline_version is not the checked manifest digest"
    claim = case.get("claim")
    if not isinstance(claim, dict):
        return "claim is missing"
    if not isinstance(claim.get("proposition"), str) or not claim["proposition"]:
        return "claim is missing a proposition"
    if not isinstance(claim.get("scope"), str):
        return "claim is missing a scope"
    if not isinstance(case.get("non_public"), bool):
        return "non_public is not a boolean"
    label = case.get("label")
    if case["non_public"] is True and label != "synthetic":
        return "label does not match non_public"
    if case["non_public"] is False and label != "public_citation":
        return "label does not match non_public"
    if not isinstance(case.get("records"), list) or not case["records"]:
        return "records are missing"
    return None


def excerpt_ref(record):
    locator = record["canonical_locator"]
    source_id = record["source_id"]
    if locator:
        return locator + "#source_id=" + source_id
    return "#source_id=" + source_id


def to_candidate(case, record, digest, digest_null_reason):
    """Allowlisted candidate. Fixture-only fields such as page_text are dropped."""
    claim = case["claim"]
    row = {
        "baseline_version": BASELINE_VERSION,
        "candidate_only": True,
        "case_id": case["case_id"],
        "claim": {
            "polarity": record["polarity"],
            "proposition": claim["proposition"],
            "scope": claim["scope"],
        },
        "confidence_basis": confidence_basis(record),
        "derived_from": (
            list(record["derived_from"])
            if isinstance(record["derived_from"], list)
            else None
        ),
        "digest": digest,
        "endpoint_mismatch": record["endpoint_mismatch"],
        "endpoint_scope": record["endpoint_scope"],
        "excerpt_ref": excerpt_ref(record),
        "label": case["label"],
        "lineage_refs": lineage_refs(record),
        "lineage_status": lineage_status(record),
        "non_public": case["non_public"],
        "not_cl_proof": True,
        "pcgm_fact_write": False,
        "permissions": permissions(),
        "retrieved_at": record["retrieved_at"],
        "schema": OBSERVATION_SCHEMA,
        "source_id": record["source_id"],
        "source_identifier": record["source_identifier"],
        "supersedes": list(record["supersedes"]),
    }
    if digest is None:
        row["digest_null_reason"] = digest_null_reason
    return row


def decide_record(case, record, fetch, limits, fetch_counter):
    problem = _case_problem(case)
    if problem:
        kind = (
            "baseline_mismatch"
            if problem.startswith("baseline_version")
            else "extraction_failure"
        )
        return _fail(case, record, kind, problem)
    problem = schema_problem(record)
    if problem:
        return _fail(case, record, "extraction_failure", problem)
    if record.get("review_status", "recorded") == "withdrawn":
        return {
            "failure": None,
            "candidate": None,
            "source": record_to_source(case, record),
        }
    try:
        mode, body = acquire(record, fetch, limits, fetch_counter)
    except TransportFailure as exc:
        return _fail(case, record, exc.kind, exc.reason, exc.detail)

    if mode == "bytes":
        claimed = record.get("content_sha256")
        if claimed is not None and not _hex64(claimed):
            return _fail(
                case, record, "extraction_failure",
                "content_sha256 is not null or 64 hex chars",
            )
        declared = record["transport"].get("declared_length")
        if declared is not None and not isinstance(declared, int):
            return _fail(case, record, "extraction_failure", "declared_length is not an integer")
        actual = digest_hex(body)
        if claimed is not None and actual != claimed:
            if isinstance(declared, int) and len(body) < declared:
                reason = "truncated body does not match digest"
            else:
                reason = "bytes do not match claimed digest"
            # The shipped evaluator does not hash bytes. A mismatch is the
            # contract's invalid source, and review_status "invalid" is how
            # that evaluator keeps the row out of the family count.
            decision = _fail(case, record, "untrustworthy_content", reason)
            source = record_to_source(case, record)
            source["review_status"] = "invalid"
            decision["source"] = source
            return decision
        extracted = extract_observation(body)
        if extracted is None:
            return _fail(
                case, record, "extraction_failure",
                "body has no CLSRC1 observation header",
            )
        if extracted["source_id"] != record["source_id"]:
            return _fail(
                case, record, "extraction_failure",
                "extracted source_id does not match the envelope",
            )
        if extracted["polarity"] != record["polarity"]:
            return _fail(
                case, record, "extraction_failure",
                "extracted polarity does not match the envelope",
            )
        family = record.get("source_family_id") or ""
        if extracted["family"] != family:
            return _fail(
                case, record, "extraction_failure",
                "extracted family does not match the envelope",
            )
        digest = actual
        digest_null_reason = None
    else:
        claimed = record.get("content_sha256")
        if claimed is not None:
            return _fail(case, record, "untrustworthy_content", "digest claimed without bytes")
        reason = record.get("digest_null_reason")
        if not isinstance(reason, str) or not reason.strip():
            return _fail(case, record, "extraction_failure", "null digest has no reason")
        digest = None
        digest_null_reason = reason

    return {
        "failure": None,
        "candidate": to_candidate(case, record, digest, digest_null_reason),
        "source": record_to_source(case, record),
    }


def adapt_case(case, fetch=None, limits=None):
    """Adapt one fixture case. `fetch` defaults to the closed network path."""
    fetch = default_fetch if fetch is None else fetch
    limits = limits or Limits()
    fetch_counter = [0]
    candidates = []
    failures = []
    sources = []
    records = case.get("records")
    if not isinstance(records, list):
        records = [{}]
        case = dict(case)
        case["records"] = records
    for record in records:
        if not isinstance(record, dict):
            failures.append(_fail(
                case, {}, "extraction_failure", "record is not an object"
            )["failure"])
            continue
        decision = decide_record(case, record, fetch, limits, fetch_counter)
        if decision["failure"] is not None:
            failures.append(decision["failure"])
        if decision["candidate"] is not None:
            candidates.append(decision["candidate"])
        if decision["source"] is not None:
            sources.append(decision["source"])
    return AdaptResult(candidates, failures, sources, fetch_counter[0])
