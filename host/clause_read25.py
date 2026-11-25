"""Ground same-utterance references and preserve provenance across host language turns."""
from copy import deepcopy
import hashlib
import json
import re

import context25 as cx
from language_boundary25 import quotes_in


INTRO = re.compile(r"\s*(?:(?:我|我们|手边|手头|手里|这里|这儿|眼前|书库|资料库|清单|列表|桌上)"
                   r"(?:这边|手头|手上|里|中|上)?(?:现有|目前有|放着|摆着|列着|包括|列出|有|是)|现有|列出)\s*")
JOIN = re.compile(r"\s*(?:、|，|,|和|与|以及|还有|跟|及)\s*")
LOOK = re.compile(r"\s*(?:(?:请|请你|麻烦|帮我|先)?(?:查查|查一查|看一看|看看|查一下|核对一下|确认一下|告诉我)"
                  r"\s*[,，]?\s*|请问\s*)?")
PRONOUN = re.compile(r"(?:那么)?(?:那它|它|那(?:份|个|本|件|册|项)|这(?:份|个|本|件|册|项))")
SPLIT = re.compile(r"[。；;]|[,，](?=(?:请问|查查|查一查|请查|帮我|看看|它|那它|那份|那本|那个))")
QUESTION = re.compile(r"吗|么|[？?]|(?:好|了|过)没(?:有)?[。？！?!\s]*$|能否|可否|是否|能不能|可不可以")
REFID = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
WITHDRAW = re.compile(r"^\s*(?:(?:我(?:要|想)|请(?:帮我)?|帮我)\s*)?(?:撤回|撤销)\s*")
RECORD_WORD = re.compile(r"(?<![a-zA-Z0-9_])[a-zA-Z][a-zA-Z0-9_-]*(?![a-zA-Z0-9_])")
REQUESTED_ID = re.compile(r"(?:(?:此前|刚才|之前|那条|这条|编号为|编号|发言|陈述|记录|原句|消息|是|为|的|号|第|\s|[:：#])*)"
                          r"(?P<key>[a-z][a-z0-9_]{0,47})(?:这条|那条|的陈述|的记录|的消息|吧|。|！|!|\s)*$")
FOLLOW_EVIDENCE = re.compile(r"为什么|为何|凭什么|依据|证据|理由|凭据")
FACETS = {"就绪":"ready_item", "已就绪":"ready_item", "准备好":"ready_item", "已经准备好":"ready_item",
          "可读":"readable", "能读":"readable", "阅读":"readable", "可供阅读":"readable", "可以阅读":"readable",
          "已核对":"verified", "核对":"verified", "核对完成":"verified", "校对完成":"verified",
          "外借":"borrow", "可借":"borrow", "副本就绪":"copy_ready"}


def _intro_entities(text, lex):
    prefix = INTRO.match(text)
    if not prefix:
        return []
    individuals = cx._entities(text, lex)
    if not individuals or len(individuals) > 12:
        return []
    cursor = prefix.end()
    for i, item in enumerate(individuals):
        gap = text[cursor:item["char_start"]]
        if item["char_start"] < cursor or (not JOIN.fullmatch(gap) if i else bool(gap.strip())):
            return []
        cursor = item["char_end"]
    if text[cursor:].strip():
        return []
    return individuals


def _bind_fixture_senses(out, lex):
    for option in out.get("alternatives") or []:
        bindings = option.get("sense_ids") or []
        fixtures = [sid for sid in bindings if sid.startswith("demo.")]
        if not fixtures:
            continue
        goal = option.get("goal") or {}
        matches = [e for e in lex.all_entries() if e.kind in ("predicate", "operator") and
                   e.canonical == goal.get("predicate") and e.status == "reviewed"]
        refs = [ref for ref in option.get("source_refs", []) if not any(ref.endswith("#" + f) for f in fixtures)]
        option["sense_ids"] = [s for s in bindings if s not in fixtures] + [e.sense_id for e in matches]
        option["source_refs"] = list(dict.fromkeys(refs + ["lexicon:" + lex.version + "#" + e.sense_id for e in matches]))
        if not matches and option.get("dispatch_target") != "none":
            option["dispatch_target"] = "none"
            out["disambiguation"] = "needs_clarification"
            out.setdefault("missing", []).append({"kind": "unknown_sense", "clarification_question": "当前版本缺少这个谓词的正式义项。"})


def _name_choices(out, lex):
    alternatives = out.get("alternatives") or []
    if len(alternatives) < 2 or out.get("disambiguation") != "ambiguous":
        return
    targets = [(a.get("metadata") or {}).get("target") or {} for a in alternatives]
    if not all(x.get("sense") and x.get("surface") for x in targets) or len({x["surface"] for x in targets}) == len(targets):
        return
    copies = deepcopy(alternatives)
    entries = {entry.sense_id: entry for entry in lex.all_entries(kind="entity")}
    labels = []
    for original, copied, target in zip(alternatives, copies, targets):
        entry = entries.get(target["sense"])
        if not entry:
            return
        label = next((h for h in entry.surface_forms if len(lex.lookup_surface(h, kind="entity")) == 1), None)
        if not label:
            return
        labels.append(label)
        copied["metadata"]["target"].update(surface=label, source_surface=target["surface"])
        copied["display"] = label
    import turn_reference25 as ref
    focus = ref._make_focus(copies, out["utterance_id"])
    if focus:
        out["context25"][ref.LAST] = focus
        for alt, label in zip(alternatives, labels):
            alt["display"] = label


def _reference(out, raw, previous):
    if not previous:
        return None
    import turn_reference25 as ref
    focus = ref._previous(previous)
    if focus:
        label = "|".join(map(re.escape, focus["labels"]))
        restated = re.sub(r"(?:刚才|刚刚|先前|前面|上面)(?:提过的|提到的|说的)?(?:这|那)(?:份|本|件|个|项)(?=" + label + ")", "", raw)
        if restated != raw and ref._select(restated, focus["labels"]):
            return ref.resolve(out, restated, previous)
    if not re.fullmatch(r"\s*(?:(?:那么|那|究竟|到底|现在|最终))*"
                        r"(?:有没有|有还是没有|到底如何|结果如何|可不可以|能不能|能否|行不行)"
                        r"(?:呀|啊|呢|了)?[。！？?!\s]*", raw):
        return None
    options = previous.get("alternatives") or []
    if previous.get("intent") not in {"query", "follow_up", "correction"} or not options:
        return None
    if previous.get("boundary", {}).get("category") not in {"proposal","unresolved_interpretation",
            "location_and_subject_bound","explicit_read_only_property"}:
        return None
    if not all(a.get("goal") and not a.get("variables") and a.get("dispatch_target") in {
            "read-channel:proof", "read-channel:reasoned_outcome", "none"} for a in options):
        return None
    for key in ("alternatives","clarified_options","disambiguation","missing","binding_kind","context25"):
        if key in previous:
            out[key] = deepcopy(previous[key])
    out.update(intent="query", ref_utterance_id=previous["utterance_id"])
    return out


def compose(out, raw, lex, previous=None):
    _bind_fixture_senses(out, lex)
    _name_choices(out, lex)
    followed = _reference(out, raw, previous)
    if followed is not None:
        return followed
    if len(raw) > 360 or "\n" in raw or quotes_in(raw) != ([], False):
        return out
    clean = raw.rstrip("。！？?! \t")
    splits = [m for m in SPLIT.finditer(clean) if _intro_entities(clean[:m.start()], lex)]
    if len(splits) != 1:
        return out
    split = splits[0]
    members = _intro_entities(clean[:split.start()], lex)
    question = raw[split.end():]
    lead = LOOK.match(question).end()
    rest = question[lead:]
    pronoun = PRONOUN.match(rest)
    if pronoun:
        candidates, end = members, pronoun.end()
    else:
        named = cx._entities(rest, lex)
        if len(named) != 1 or named[0]["char_start"] != 0:
            return out
        candidates = [e for e in members if e["value"] == named[0]["value"]]
        end = named[0]["char_end"]
    suffix = rest[end:]
    if not candidates or not (lead or QUESTION.search(suffix)):
        return out
    pred = cx._suffix(suffix)
    if not pred:
        out.update(intent="query", alternatives=[], disambiguation="needs_clarification",
                   missing=[{"kind": "unknown_sense", "clarification_question": "你要核对上文对象的哪一种具体状态？"}])
        out["context25"].update(scope="same_turn_referent")
        return out
    target_turn = out["utterance_id"]
    members_view = [cx._entity_view(e, target_turn) for e in candidates]
    for item in members:
        cx._add_span(out, cx._span(raw, item["char_start"], item["char_end"], "entity"))
    start = split.end() + lead
    cx._add_span(out, cx._span(raw, start, start + end, "anaphora" if pronoun else "entity"))
    cx._add_span(out, cx._span(raw, split.end(), len(raw), "question_clause"))
    terms = [cx._read(ent, pred, target_turn) for ent in members_view]
    cx._set_candidates(out, terms, members_view, pred)
    out["context25"].update(scope="same_turn_referent", complete_roles=len(candidates) == 1,
                            introduced=[cx._entity_view(e, target_turn) for e in members])
    out.pop("ref_utterance_id", None)
    return out


def mapped(alt, read, lex):
    subject = read["subject"]["surface"]
    attribute = read["property"]["surface"]
    location = read.get("location_qualifier")
    facet = re.sub(r"^(?:(?:已经|目前|当前|现在|仍然|已))+", "", attribute.strip())
    pred = FACETS.get(attribute) or FACETS.get(facet)
    if not pred:
        return None
    senses = [entry for entry in lex.all_entries(kind="predicate")
              if entry.canonical == pred and list(entry.arg_types) == ["sym"]]
    if not senses:
        return None
    labels = [subject] + ([location["surface"]] if location else [])
    values, identifiers = [], {entry.sense_id for entry in senses}
    for label in labels:
        matches = lex.lookup_surface(label, kind="entity")
        if len(matches) > 1:
            return None
        values.append(matches[0].canonical if matches else label)
        identifiers.update(e.sense_id for e in matches)
    typed = deepcopy(alt)
    typed.update(goal={"predicate": pred + ("_at" if location else ""), "polarity": "positive",
                       "arguments": [{"type":"sym", "value":value} for value in values]},
                 sense_ids=sorted(identifiers), dispatch_target="read-channel:reasoned_outcome",
                 display=((location["surface"] + "的") if location else "") + subject + "是否" + attribute)
    typed["source_refs"] = list(dict.fromkeys(typed.get("source_refs", []) +
                                ["lexicon:" + lex.version + "#" + sid for sid in sorted(identifiers)]))
    typed.setdefault("metadata", {})["bound_lexicon_version"] = lex.version
    return typed


def finish(out, lex):
    b = out.get("boundary") or {}
    alts = out.get("alternatives") or []
    if (b.get("decision") == "pass" and b.get("category") == "explicit_read_only_property"
            and len(alts) == 1 and alts[0].get("dispatch_target") == "host:read_only_state_query"):
        typed = mapped(alts[0], b["read_query"], lex)
        if typed:
            out["alternatives"] = [typed]
    return out


def antecedents(db, session, record):
    # The original utterance is linguistic provenance. Only native proof can establish a world fact.
    turn = record.get("ref_utterance_id")
    if not isinstance(turn, str) or not REFID.fullmatch(turn):
        return []
    candidates = [turn]
    for item in record.get("alternatives") or []:
        candidates.extend(ref[10:] for ref in item.get("source_refs", []) if isinstance(ref, str)
                          and ref.startswith("utterance:") and REFID.fullmatch(ref[10:]))
    found = []
    for key in list(dict.fromkeys(candidates))[:8]:
        if key == record.get("utterance_id"):
            continue
        row = db.execute("SELECT raw_pin,json_extract(parsed,'$.raw_text') FROM joint25_turns "
                         "WHERE session=? AND turn=?", (session, key)).fetchone()
        if row and isinstance(row[1], str) and hashlib.sha256(row[1].encode()).hexdigest() == row[0]:
            found.append({"utterance_id": key, "raw_sha256": row[0], "text": row[1][:100]})
    return found


def version_issue(db, payload, active):
    """An explicit L1 version must name the active grammar or the immutable replay being requested."""
    context = payload.get("context") or {}
    supplied = [part["lexicon_version"] for part in (payload, context) if "lexicon_version" in part]
    if not supplied:
        return None
    if any(not isinstance(ver, str) or not ver or ver != supplied[0] for ver in supplied):
        return "词典版本格式不符，或本轮携带互不相同的版本。"
    expected = active
    request = context.get("request")
    if request and db.execute("SELECT 1 FROM sqlite_master WHERE name='joint25_turns' AND type='table'").fetchone():
        prior = db.execute("SELECT raw_pin, source_version FROM joint25_turns WHERE session=? AND turn=?",
                           (context.get("session","main"),request)).fetchone()
        if prior and prior[0] == hashlib.sha256(payload["text"].encode()).hexdigest():
            expected = prior[1]
    if supplied[0] != expected:
        return "本轮找不到所指定的词典版本，或它与已保存回合的解析版本不同。"
    return None


def named_withdrawal(raw):
    lead = WITHDRAW.match(raw)
    if not lead or quotes_in(raw) != ([], False):
        return None
    tail = raw[lead.end():]
    ids = RECORD_WORD.findall(tail)
    if not ids:
        return None
    match = REQUESTED_ID.fullmatch(tail)
    return match["key"] if match and ids == [match["key"]] else ""


def _withdrawn(db, session, target):
    rows=db.execute("SELECT json_extract(parsed,'$.raw_text') FROM joint25_turns "
                    "WHERE session=? AND json_extract(parsed,'$.retract_target_id')=? AND "
                    "json_extract(parsed,'$.boundary.decision')='pass' AND json_extract(parsed,'$.intent')='retraction'",
                    (session,target))
    for (raw,) in rows:
        explicit = named_withdrawal(raw)
        if explicit is None or explicit == target:
            return True
    return False


def bind_withdrawal(db, out, raw, session):
    """Bind an explicit language withdrawal to one prior assertion in this session's durable history."""
    target = named_withdrawal(raw)
    if target is None:
        return None
    row = db.execute("SELECT raw_pin,parsed FROM joint25_turns WHERE session=? AND turn=?", (session,target)).fetchone()
    original = json.loads(row[1]) if row else {}
    valid = bool(row and original.get("utterance_id") == target and original.get("intent") == "assertion"
                 and original.get("boundary", {}).get("decision") == "pass" and
                 row[0] == hashlib.sha256(original["raw_text"].encode()).hexdigest() and not _withdrawn(db,session,target))
    out.update(intent="retraction", alternatives=[], retract_target_id=None, ref_utterance_id=None, missing=[],
               disambiguation="needs_clarification")
    if valid:
        pin = row[0]
        out.update(disambiguation="unique", retract_target_id=target, ref_utterance_id=target, alternatives=[{
            "candidate_id":"c1", "goal":{"predicate":"retract_proposal","polarity":"positive",
                                        "arguments":[{"type":"record_id","value":target}]},
            "variables":[], "premises":[], "sense_ids":[], "polarity":"positive", "dispatch_target":"proposal:withdraw",
            "source_refs":["utterance:"+out["utterance_id"], "utterance:"+target, "target-sha256:"+pin],
            "metadata":{"requires_core_authorization":True, "original_raw_sha256":pin}}])
    else:
        out["missing"]=[{"kind":"missing_retraction_target",
                         "clarification_question":"请提供本会话中一条仍可撤回的原陈述编号。"}]
    out["context25"].update(scope="named_withdrawal", requested_id=target)
    return target


def align_withdrawal_state(state, old, out, named):
    if named is None:
        return
    accepted = out.get("retract_target_id") if out.get("boundary",{}).get("decision") == "pass" else None
    for key, old_entry in (old or {}).get("turns",{}).items():
        entry=state["turns"].get(key)
        if entry:
            entry["active"] = False if key == accepted else old_entry.get("active", True)
    state["last_pending_retraction"] = None if accepted else (old or {}).get("last_pending_retraction")
    if out["utterance_id"] in state["turns"]:
        state["turns"][out["utterance_id"]]["record_dict"] = deepcopy(out)
