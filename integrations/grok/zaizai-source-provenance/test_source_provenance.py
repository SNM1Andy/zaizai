# -*- coding: utf-8 -*-
"""Structural checks for the shipped provenance contract, cases, expectations, and review.

Reads those four files from disk. Applies the contract's family and four-value
rules to each case and compares them with that case's expectation. Does not use
the zip seed as the oracle.
"""

from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
CONTRACT = ROOT / "source-provenance.contract.md"
CASES = ROOT / "evidence-cases.jsonl"
EXPECT = ROOT / "expected.jsonl"
REVIEW = ROOT / "review_report.md"

FIELDS = [
    "evidence_id",
    "claim_id",
    "stance",
    "source_id",
    "canonical_locator",
    "observed_at",
    "source_family_id",
    "derived_from",
    "content_sha256",
    "scope",
    "review_status",
    "supersedes",
    "endpoint_mismatch",
]
CLASSES = ["来源重复/同源遮掩", "独立正反证据/冲突", "撤回/更新/来源不明"]
FOUR = ["admitted", "invalid_source", "conflict", "unknown"]
SEED_IDS = ["dev-reprint", "dev-conflict", "dev-unknown-lineage"]
COUNTEREXAMPLES = ["新闻转载", "引述同一数据", "截屏转帖", "多时点同一机构记录"]
RULES = (
    "转载不增加独立证据",
    "冲突不被多数票压掉",
    "不能确认归属时结果保持未知",
    "撤掉一项只撤该项自己的来源",
)
NAMED_LOCATORS = (
    "https://www.bls.gov/news.release/pdf/prebmk.pdf",
    "https://pubmed.ncbi.nlm.nih.gov/39730229/",
)


def main() -> int:
    problems = []
    for path in (CONTRACT, CASES, EXPECT, REVIEW):
        if not path.is_file():
            problems.append("missing " + path.name)
    if problems:
        _report(problems)
        return 1

    contract = CONTRACT.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    case_text = CASES.read_text(encoding="utf-8")
    expect_text = EXPECT.read_text(encoding="utf-8")
    cases = _jsonl(CASES, problems, "cases")
    expects = _jsonl(EXPECT, problems, "expectations")
    if problems:
        _report(problems)
        return 1

    _contract(contract, problems)
    _cases(cases, expects, case_text, expect_text, problems)
    _review(review, problems)
    _note_words_do_not_trigger(problems)
    _report(problems)
    return 1 if problems else 0


def _jsonl(path, problems, label):
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            problems.append("%s line %d is not json: %s" % (label, n, exc))
    return rows


def _contract(text, problems):
    for field in FIELDS:
        if "`%s`" % field not in text:
            problems.append("contract missing field " + field)
    for phrase in (
        "same-family",
        "independent",
        "不明（unknown）",
        "unknown independence is not treated as independent",
        "credibility is not scored by domain count or by tone",
        "a content hash checks byte integrity only",
        "source family is what says whether support is independent",
        "a real conclusion stays with CL on already-admitted evidence and rules",
        "an external model may only supply materials and translations, and may not write facts, adopt a candidate, or take over execution",
        "不修改运行时",
        "最终事实判断",
        "判定不读 `scope` 里的词",
        "只认列表里的编号",
        "只认这个字段",
        "`scope` 里出现 `supersedes` 或 `endpoint_mismatch` 这两个词，都不触发",
        "不得算成新的独立证据",
        "转载自填的另一个",
        "不把旁边已经独立的家族拖成未知",
        "invalid source",
    ):
        if phrase not in text:
            problems.append("contract missing claim: " + phrase)
    if "域名个数" not in text or "语气" not in text:
        problems.append("contract does not refuse domain-count and tone scores")
    for name in COUNTEREXAMPLES:
        if name not in text:
            problems.append("contract missing counterexample " + name)
    for value in FOUR:
        if value not in text:
            problems.append("contract does not name four-value " + value)
    for seed in SEED_IDS:
        if seed not in text:
            problems.append("contract does not exclude seed " + seed)
    if "验收集" not in text and "不是本契约的验收" not in text:
        problems.append("contract does not say the seed is outside this acceptance set")


def evaluate(sources):
    """Return independent-family count and four-value under the contract rules."""
    invalid = []
    unknown = []
    usable = []
    for source in sources:
        if source.get("review_status") == "withdrawn":
            continue
        locator = (source.get("canonical_locator") or "").strip()
        if source.get("review_status") == "invalid" or locator == "":
            invalid.append(source)
            continue
        if source.get("endpoint_mismatch") is True:
            unknown.append(source)
            continue
        if source.get("source_family_id") in (None, "") or source.get("derived_from") is None:
            unknown.append(source)
            continue
        usable.append(source)

    by_id = {source["source_id"]: source for source in usable}

    def root_family(source, seen):
        if source["source_id"] in seen:
            return source["source_family_id"]
        seen = seen | {source["source_id"]}
        parents = source.get("derived_from") or []
        if parents:
            parent = by_id.get(parents[0])
            if parent is None:
                return None
            return root_family(parent, seen)
        return source["source_family_id"]

    families = {}
    lost_parent = []
    for source in usable:
        family = root_family(source, frozenset())
        if family is None:
            lost_parent.append(source)
            continue
        families.setdefault(family, []).append(source)

    resolved = {}
    for family, records in families.items():
        superseding = [row for row in records if row.get("supersedes")]
        if superseding:
            resolved[family] = superseding[-1]["stance"]
        else:
            stances = {row["stance"] for row in records}
            resolved[family] = "unresolved" if len(stances) > 1 else next(iter(stances))

    independent = {family: stance for family, stance in resolved.items() if stance != "unresolved"}
    unresolved = [family for family, stance in resolved.items() if stance == "unresolved"]
    if unresolved:
        four = "unknown"
    elif not independent:
        four = "invalid_source" if invalid and not unknown else "unknown"
    elif len(set(independent.values())) > 1:
        four = "conflict"
    else:
        four = "admitted"

    stance_rows = {}
    for family, stance in independent.items():
        stance_rows[stance] = stance_rows.get(stance, 0) + len(families[family])
    return {
        "count": 0 if unresolved else len(independent),
        "four": four,
        "stance_rows": stance_rows,
        "unresolved": unresolved,
        "lost_parent": lost_parent,
        "has_reprint": any(
            isinstance(source.get("derived_from"), list) and source.get("derived_from")
            for source in sources
        ),
    }


def _cases(cases, expects, case_text, expect_text, problems):
    if len(cases) < 30:
        problems.append("fewer than 30 cases: %d" % len(cases))
    for seed in SEED_IDS:
        if seed in case_text:
            problems.append("case file contains seed " + seed)
        if seed in expect_text:
            problems.append("expectation file contains seed " + seed)
    if '"four_value"' in case_text:
        problems.append("cases embed expectations")
    if '"sources"' in expect_text:
        problems.append("expectations embed case sources")

    by_id = {}
    class_count = {name: 0 for name in CLASSES}
    real = 0
    synthetic = 0
    for row in cases:
        cid = row.get("case_id")
        if not cid or cid in by_id:
            problems.append("bad or duplicate case_id: %s" % cid)
            continue
        by_id[cid] = row
        if row.get("fixture_only") is True or cid in SEED_IDS:
            problems.append("seed or fixture row counted in the set: " + cid)
        elif row.get("fixture_only") is not False:
            problems.append("%s fixture_only is not false" % cid)
        klass = row.get("case_class")
        if klass not in class_count:
            problems.append("%s has unknown class %s" % (cid, klass))
        else:
            class_count[klass] += 1
        kind = row.get("case_kind")
        if kind == "公开真实案例":
            real += 1
            _real_row(row, problems)
        elif kind == "合成边界测试":
            synthetic += 1
        else:
            problems.append("%s kind is neither real nor 合成边界测试" % cid)
        if "explanation" not in row or not str(row.get("explanation") or "").strip():
            problems.append("%s missing explanation" % cid)
        elif len(row["explanation"]) > 400:
            problems.append("%s explanation is long enough to be a full copy" % cid)
        blob = json.dumps(row, ensure_ascii=False)
        for bad in ("password", "api_key", "cesinfo@", "PressOffice@"):
            if bad in blob:
                problems.append("%s contains sensitive marker %s" % (cid, bad))
        seen_sources = set()
        known_ids = [source.get("source_id") for source in row.get("sources") or []]
        for source in row.get("sources") or []:
            for field in FIELDS:
                if field not in source:
                    problems.append("%s source missing %s" % (cid, field))
            if source.get("claim_id") != row.get("claim_id"):
                problems.append("%s source claim_id does not match the case" % cid)
            if source.get("stance") not in ("supports", "opposes"):
                problems.append("%s stance is not supports or opposes" % cid)
            if source.get("review_status") not in ("recorded", "withdrawn", "invalid"):
                problems.append("%s review_status is outside the contract" % cid)
            derived = source.get("derived_from")
            if derived is not None and not isinstance(derived, list):
                problems.append("%s derived_from is neither a list nor null" % cid)
            digest = source.get("content_sha256")
            if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
                problems.append("%s content_sha256 is not null or 64 hex chars" % cid)
            sid = source.get("source_id")
            if not sid or sid in seen_sources:
                problems.append("%s bad or duplicate source_id %s" % (cid, sid))
            seen_sources.add(sid)
            if not isinstance(source.get("endpoint_mismatch"), bool):
                problems.append("%s endpoint_mismatch is not a boolean" % cid)
            replaced = source.get("supersedes")
            if not isinstance(replaced, list) or any(not isinstance(item, str) or not item for item in replaced):
                problems.append("%s supersedes is not a list of source ids" % cid)
            else:
                for item in replaced:
                    if item not in known_ids:
                        problems.append("%s supersedes does not point at a source id: %s" % (cid, item))
                    if item == sid:
                        problems.append("%s supersedes points at itself" % cid)

    total = len(by_id)
    for name, n in class_count.items():
        if n < 8:
            problems.append("class %s has %d < 8" % (name, n))
        if total and n > total / 2:
            problems.append("class %s is more than half (%d/%d)" % (name, n, total))
    if real < 10:
        problems.append("public real cases %d < 10" % real)
    if synthetic + real != total:
        problems.append("kind counts do not add up")
    for locator in NAMED_LOCATORS:
        if locator not in case_text:
            problems.append("public cases omit named locator " + locator)

    exp_by = {}
    for row in expects:
        cid = row.get("case_id")
        if not cid or cid in exp_by:
            problems.append("bad or duplicate expectation id: %s" % cid)
            continue
        exp_by[cid] = row
        for key in ("dedupe", "four_value", "four_value_change", "withdrawal_recompute", "forbidden_actions"):
            if key not in row or row[key] in (None, "", []):
                problems.append("%s expectation missing %s" % (cid, key))
        if row.get("four_value") not in FOUR:
            problems.append("%s four_value not in the named four" % cid)
        withdraw = row.get("withdrawal_recompute") or ""
        if "撤掉一项只撤该项自己的来源" not in withdraw:
            problems.append("%s withdrawal does not keep to that item's own source" % cid)
        actions = row.get("forbidden_actions")
        if not isinstance(actions, list) or not actions:
            problems.append("%s forbidden_actions empty" % cid)
        else:
            for action in (
                "不得按域名个数打分",
                "不得按语气打分",
                "不得写入事实",
                "不得采纳候选",
                "不得接管执行",
            ):
                if action not in actions:
                    problems.append("%s forbidden_actions missing %s" % (cid, action))

    missing = sorted(set(by_id) - set(exp_by))
    extra = sorted(set(exp_by) - set(by_id))
    if missing:
        problems.append("cases without expectations: " + ",".join(missing))
    if extra:
        problems.append("expectations without cases: " + ",".join(extra))

    joined = json.dumps(list(exp_by.values()), ensure_ascii=False)
    for phrase in RULES:
        if phrase not in joined:
            problems.append("expectations do not state " + phrase)

    unequal_conflict = False
    saw_reprint_collapse = False
    saw_unknown_lineage = False
    for cid, case in by_id.items():
        exp = exp_by.get(cid)
        if exp is None:
            continue
        result = evaluate(case.get("sources") or [])
        if exp.get("independent_family_count") != result["count"]:
            problems.append(
                "%s independent_family_count %s disagrees with contract count %s"
                % (cid, exp.get("independent_family_count"), result["count"])
            )
        if exp.get("four_value") != result["four"]:
            problems.append(
                "%s four_value %s disagrees with contract four-value %s"
                % (cid, exp.get("four_value"), result["four"])
            )
        text = (exp.get("dedupe") or "") + (exp.get("four_value_change") or "")
        if result["has_reprint"]:
            if exp.get("reprint_does_not_add_independent_evidence") is not True:
                problems.append("%s reprint is counted as independent" % cid)
            if not isinstance(exp.get("independent_family_count"), int) or exp["independent_family_count"] >= len(case.get("sources") or []):
                problems.append("%s reprint increases the independent-family count" % cid)
            saw_reprint_collapse = True
        if result["four"] == "conflict":
            if "冲突不被多数票压掉" not in text:
                problems.append("%s conflict expectation lets a majority overrule it" % cid)
            if exp.get("conflict_is_not_overruled_by_majority") is not True:
                problems.append("%s conflict flag does not refuse a majority" % cid)
            rows = result["stance_rows"]
            if len(rows) >= 2 and max(rows.values()) != min(rows.values()):
                unequal_conflict = True
        if result["four"] == "unknown":
            if "不能确认归属时结果保持未知" not in text:
                problems.append("%s unknown expectation does not keep the result unknown" % cid)
        if result["four"] == "admitted" and exp.get("four_value") == "admitted":
            if any(
                source.get("source_family_id") in (None, "") or source.get("derived_from") is None
                for source in case.get("sources") or []
            ):
                if exp.get("unconfirmed_attribution_stays_unknown") is not True:
                    problems.append("%s promotes an unconfirmed record into the admitted family" % cid)
        lineage_unknown = any(
            source.get("source_family_id") in (None, "") or source.get("derived_from") is None
            for source in case.get("sources") or []
        )
        if lineage_unknown and result["four"] == "unknown":
            saw_unknown_lineage = True
            if exp.get("unconfirmed_attribution_stays_unknown") is not True:
                problems.append("%s unconfirmed attribution does not stay unknown" % cid)

    if not saw_reprint_collapse:
        problems.append("no expectation shows that a reprint does not add a family")
    if not unequal_conflict:
        problems.append("no conflict expectation keeps conflict against a larger side")
    if not saw_unknown_lineage:
        problems.append("no expectation keeps unknown when attribution is unconfirmed")
    if not any(row.get("four_value") == "invalid_source" for row in exp_by.values()):
        problems.append("invalid_source never appears in expectations")


def _note_words_do_not_trigger(problems):
    """Scope text that merely contains the field names must not change the four-value."""
    base = {
        "evidence_id": "probe",
        "claim_id": "probe",
        "canonical_locator": "https://example.com/probe",
        "observed_at": "2026-11-23T12:00:00Z",
        "content_sha256": None,
        "review_status": "recorded",
        "derived_from": [],
    }
    same_family = [
        dict(base, source_id="old", stance="supports", source_family_id="fam", scope="note mentions supersedes", supersedes=[], endpoint_mismatch=False),
        dict(base, source_id="other", stance="opposes", source_family_id="fam", scope="note mentions endpoint_mismatch", supersedes=[], endpoint_mismatch=False),
    ]
    got = evaluate(same_family)
    if got["four"] != "unknown" or got["count"] != 0:
        problems.append("scope wording was treated as supersedes or endpoint_mismatch")
    mismatched = [
        dict(base, source_id="death", stance="opposes", source_family_id="fam_death", scope="28-day mortality", supersedes=[], endpoint_mismatch=True),
        dict(base, source_id="viral", stance="supports", source_family_id="fam_viral", scope="viral load", supersedes=[], endpoint_mismatch=True),
    ]
    got = evaluate(mismatched)
    if got["four"] != "unknown" or got["count"] != 0:
        problems.append("endpoint_mismatch true did not exclude the records")
    replaced = [
        dict(base, source_id="bulletin_1", stance="supports", source_family_id="fam", scope="earlier bulletin", supersedes=[], endpoint_mismatch=False),
        dict(base, source_id="bulletin_2", stance="opposes", source_family_id="fam", derived_from=["bulletin_1"], scope="later bulletin that replaces bulletin_1", supersedes=["bulletin_1"], endpoint_mismatch=False),
    ]
    got = evaluate(replaced)
    if got["four"] != "admitted" or got["count"] != 1:
        problems.append("supersedes source id did not set the current stance")


def _real_row(row, problems):
    cid = row["case_id"]
    if "合成边界测试" in (row.get("explanation") or ""):
        problems.append("%s real case is also marked synthetic in the explanation" % cid)
    locs = []
    for source in row.get("sources") or []:
        loc = source.get("canonical_locator") or ""
        if loc.startswith("http://") or loc.startswith("https://"):
            locs.append(loc)
        if not source.get("observed_at"):
            problems.append("%s source missing observed_at" % cid)
    if not locs:
        problems.append("%s real case has no http(s) locator" % cid)
    if not row.get("observed_at"):
        problems.append("%s missing observed_at" % cid)
    if len((row.get("explanation") or "").strip()) < 20:
        problems.append("%s explanation too short to be an original note" % cid)


def _review(text, problems):
    for heading in ("## 来源表", "## 误判", "## 分歧", "## 已知限制"):
        if heading not in text:
            problems.append("review missing " + heading)
    if "evidence-cases.jsonl" not in text or "expected.jsonl" not in text:
        problems.append("review does not keep cases and expectations in separate files")
    if "另一种读法" not in text:
        problems.append("review does not record a disagreement")
    if "没有改写成一致" not in text and "不把分歧改写成一致" not in text:
        problems.append("review rewrites a disagreement into one agreed label")
    if "基准" not in text or "预期" not in text:
        problems.append("review does not say the delivery is the baseline and the expectations")
    if "不报告通过率" not in text:
        problems.append("review does not refuse a pass rate")
    if "成功条数" not in text and "成功计数" not in text:
        problems.append("review does not refuse a success count")
    if re.search(r"通过率\s*[:：为]?\s*\d", text):
        problems.append("review states a pass rate")
    if "PASS" in text:
        problems.append("review cites a PASS line")
    for seed in SEED_IDS:
        if seed not in text:
            problems.append("review does not exclude seed " + seed)
    if "fixture_only" not in text and "示意" not in text:
        problems.append("review does not mark the seed as non-acceptance")


def _report(problems):
    if problems:
        print("FAIL %d" % len(problems))
        for item in problems:
            print("- " + item)
        print("problems=%d" % len(problems))
    else:
        print("PASS source provenance structure")
        print("problems=0")
        print("contract=" + str(CONTRACT))
        print("cases=" + str(CASES))
        print("expectations=" + str(EXPECT))
        print("review=" + str(REVIEW))


if __name__ == "__main__":
    sys.exit(main())
