"""Pure source mapping and weight checks.

`family_result` calls the shipped evaluator on each use. Reprint weight,
withdrawal, and text fields do not open files and do not touch the network.
"""

from .shipped import shipped_module

BASELINE_VERSION = "9e456752f08769fb3757c21665587c847ec3104a87be7b4fb306bee892af2f31"
OBSERVATION_SCHEMA = "cl-source-observation-v1"
FAILURE_SCHEMA = "cl-source-observation-failure-v1"

# Fixed candidate permissions. Page text cannot add a tool, a write, or an upload.
CANDIDATE_PERMISSIONS = {
    "adopt_candidate": False,
    "execute": False,
    "read_public": True,
    "tool_grant": False,
    "upload": False,
    "write_facts": False,
    "write_pcgm": False,
}


def permissions():
    return dict(CANDIDATE_PERMISSIONS)


def family_result(sources):
    """Independent-family count and four-value from the shipped evaluator."""
    return shipped_module().evaluate(list(sources))


def record_to_source(case, record):
    """Map one fixture record onto the shipped evaluator's source object.

    `endpoint_scope` is stored as `scope`. The evaluator does not read words
    inside that field. `page_text` is not copied.
    """
    derived = record["derived_from"]
    if isinstance(derived, list):
        derived = list(derived)
    return {
        "evidence_id": record["evidence_id"],
        "claim_id": case["claim_id"],
        "stance": record["polarity"],
        "source_id": record["source_id"],
        "canonical_locator": record["canonical_locator"],
        "observed_at": record["retrieved_at"],
        "source_family_id": record["source_family_id"],
        "derived_from": derived,
        "content_sha256": record.get("content_sha256"),
        "scope": record["endpoint_scope"],
        "review_status": record.get("review_status", "recorded"),
        "supersedes": list(record["supersedes"]),
        "endpoint_mismatch": record["endpoint_mismatch"],
    }


def confidence_basis(record):
    """Why the row is a candidate. This is not a numeric score."""
    derived = record["derived_from"]
    family = record.get("source_family_id")
    if derived is None or family in (None, ""):
        return "unconfirmed_lineage"
    if isinstance(derived, list) and derived:
        return "reprint_lineage"
    return "family_root"


def lineage_refs(record):
    derived = record["derived_from"]
    if isinstance(derived, list):
        return list(derived)
    return []


def lineage_status(record):
    derived = record["derived_from"]
    family = record.get("source_family_id")
    if derived is None or family in (None, ""):
        return "unconfirmed"
    return "confirmed"


def without_reprints(sources):
    kept = []
    for source in sources:
        derived = source.get("derived_from")
        if isinstance(derived, list) and derived:
            continue
        kept.append(source)
    return kept


def reprint_weights(sources):
    """Family count with reprints, and the same set with reprint rows removed."""
    full = family_result(sources)
    base = family_result(without_reprints(sources))
    return {
        "with_reprints": full["count"],
        "without_reprints": base["count"],
        "unchanged": full["count"] == base["count"],
        "full": full,
        "base": base,
    }


def withdraw_record(cases, source_id):
    """Mark one source_id withdrawn. Other cases stay the same objects.

    Other records inside the affected case stay the same objects. The original
    cases are not mutated.
    """
    affected = []
    rewritten = []
    for case in cases:
        ids = [record["source_id"] for record in case["records"]]
        if source_id not in ids:
            rewritten.append(case)
            continue
        affected.append(case["case_id"])
        records = []
        for record in case["records"]:
            if record["source_id"] == source_id:
                copied = dict(record)
                copied["review_status"] = "withdrawn"
                records.append(copied)
            else:
                records.append(record)
        copied_case = dict(case)
        copied_case["records"] = records
        rewritten.append(copied_case)
    return affected, rewritten
